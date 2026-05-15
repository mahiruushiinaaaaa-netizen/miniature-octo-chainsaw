"""
backend.py – Optimized backend with streaming, connection pooling, and smart caching.
Low-end device friendly: minimal memory, fast timeout, reused connections.

Integrates:
- ConnectionPool for HTTP connection reuse with keep-alive
- AdaptiveGrammarSelector for model-size-aware grammar selection
- StreamingActionParser for early action detection during streaming
- Pre-warm on server ready to initialize KV cache
- 600s read timeout for CPU-only hardware
"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.request
import urllib.error
from collections import OrderedDict
from typing import Any, Callable

from .config import Config
from ..ui import err, ok, status
from .prompting import build_chat_prompt, clean_model_output
from .logger import get_logger
from .metrics import get_metrics_collector
from .errors import NetworkError, ModelError, ErrorContext


logger = get_logger("backend")
metrics = get_metrics_collector()

# ── Adaptive LRU Cache (smaller on low-end devices) ─────────────────────────
def _get_cache_size() -> int:
    """Get appropriate cache size based on available memory."""
    try:
        import psutil
        ram_mb = psutil.virtual_memory().available / (1024 * 1024)
        # Smaller cache on low-memory systems
        if ram_mb < 2000:
            return 8
        elif ram_mb < 4000:
            return 16
        else:
            return 48
    except ImportError:
        return 24  # Conservative default

class _LRUCache:
    def __init__(self, maxsize: int = None):
        self._store: OrderedDict = OrderedDict()
        self._maxsize = maxsize or _get_cache_size()

    def get(self, key):
        if key in self._store:
            self._store.move_to_end(key)
            return self._store[key]
        return None

    def set(self, key, value: str) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        else:
            if len(self._store) >= self._maxsize:
                self._store.popitem(last=False)
        self._store[key] = value

    def clear(self) -> None:
        self._store.clear()

_GENERATION_CACHE = _LRUCache()


# ── Connection pool and adaptive grammar singletons ───────────────────────────

# These are lazily initialized per-config to avoid import-time side effects.
_connection_pool = None  # type: Any
_adaptive_grammar = None  # type: Any
_pool_config_url = None  # Track which URL the pool was created for


def _get_connection_pool(config: Config):
    """Get or create the connection pool for the given config."""
    global _connection_pool, _pool_config_url
    if not config.streaming_parse:
        return None
    if _connection_pool is None or _pool_config_url != config.base_url:
        from .connection_pool import create_pool_general
        _connection_pool = create_pool_general(
            config.base_url,
            timeout=max(config.timeout, 600),
        )
        _pool_config_url = config.base_url
        logger.info(f"Connection pool created for {config.base_url}")
    return _connection_pool


def _get_adaptive_grammar(config: Config):
    """Get or create the adaptive grammar selector for the given config."""
    global _adaptive_grammar
    if not config.grammar_adaptive:
        return None
    if _adaptive_grammar is None:
        from .adaptive_grammar import AdaptiveGrammarSelector
        _adaptive_grammar = AdaptiveGrammarSelector(config)
    return _adaptive_grammar


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def http_get_json(url: str, timeout: int = 2):
    try:
        req = urllib.request.Request(
            url,
            headers={"Connection": "keep-alive"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if 200 <= resp.status < 300:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw.strip() else {}
    except Exception as e:
        logger.debug(f"HTTP GET failed for {url}: {e}")
        return None
    return None


def http_post_json(url: str, payload: dict, timeout: int) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Connection": "keep-alive"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw.strip() else {}


def _pool_post_json(pool, path: str, payload: dict, timeout: int) -> dict:
    """POST JSON using the connection pool instead of urllib directly."""
    from .connection_pool import RetryableError
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Connection": "keep-alive",
    }
    conn = pool.get_connection(timeout=30)
    try:
        conn.request("POST", path, body=body, headers=headers)
        response = conn.getresponse()
        if response.status == 503:
            response.read()  # Drain body before reuse
            raise RetryableError(f"Server busy (503)", status_code=503)
        raw = response.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw.strip() else {}
    except RetryableError:
        pool.release(conn)
        raise
    except Exception:
        # Connection may be broken, don't return to pool
        try:
            conn.close()
        except Exception:
            pass
        # Decrement checked_out manually since we're not calling release
        with pool._available_condition:
            pool._checked_out = max(0, pool._checked_out - 1)
            pool._available_condition.notify()
        raise
    else:
        pool.release(conn)


def _pool_post_json_safe(pool, path: str, payload: dict, timeout: int) -> dict:
    """POST JSON using connection pool with retry policy for 503 responses."""
    from .connection_pool import RetryPolicy, RetryableError

    retry = RetryPolicy()

    def do_request():
        return _pool_post_json(pool, path, payload, timeout)

    return retry.execute_with_retry(do_request)


def server_ready(base_url: str) -> bool:
    for path in ("/health", "/healthz", "/v1/models"):
        if http_get_json(base_url + path, timeout=2) is not None:
            return True
    return False


# ── Ollama Backend ────────────────────────────────────────────────────────────

_OLLAMA_URL = "http://127.0.0.1:11434"


def ollama_available() -> bool:
    """Check if Ollama is running."""
    return http_get_json(f"{_OLLAMA_URL}/api/tags", timeout=2) is not None


def ollama_generate(
    model: str,
    prompt: str,
    system_text: str | None = None,
    max_tokens: int = 256,
    temperature: float = 0.0,
    grammar: str | None = None,
    on_token: Callable | None = None,
) -> str | None:
    """Generate text using Ollama's API.
    
    Supports both streaming (with on_token callback) and non-streaming modes.
    Grammar is passed as a GBNF string if provided.
    """
    # Aggressive speed tuning: keep model loaded, larger batch
    is_small = "0.5b" in model.lower() or "0.8b" in model.lower()
    # Use FIXED num_ctx — varying it causes Ollama to reload the model (very slow on CPU)
    # Keep size minimal-but-consistent so the KV cache stays warm
    ctx_size = 1024 if is_small else 2048
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": on_token is not None,
        "keep_alive": "30m",  # Keep model in RAM between calls — huge speedup
        "options": {
            "num_predict": max_tokens,
            "temperature": temperature,
            "num_ctx": ctx_size,
            "num_batch": 1024,  # Larger batch for faster prompt processing
            "num_thread": 0,  # Let Ollama auto-detect optimal threads
        },
    }
    if system_text:
        payload["system"] = system_text
    
    url = f"{_OLLAMA_URL}/api/generate"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            if on_token:
                # Streaming mode — Ollama returns newline-delimited JSON
                content_parts = []
                for line in resp:
                    line = line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                        token = chunk.get("response", "")
                        if token:
                            content_parts.append(token)
                            on_token(token)
                        if chunk.get("done", False):
                            break
                    except json.JSONDecodeError:
                        continue
                return "".join(content_parts) if content_parts else None
            else:
                # Non-streaming mode
                raw = resp.read().decode("utf-8", errors="replace")
                result = json.loads(raw)
                content = result.get("response", "").strip()
                return content if content else None
    except Exception as e:
        logger.debug(f"Ollama generation failed: {e}")
        return None


def start_server(config: Config):
    if not config.server_bin:
        err("llama-server not found")
        logger.error("llama-server binary not found", context={"server_bin": str(config.server_bin)})
        return None

    command = [
        str(config.server_bin),
        "-m", str(config.model),
        "-t", str(config.threads),
        "-c", str(config.ctx),
        "--host", config.host,
        "--port", str(config.port),
        "--log-disable",
        "-np", "1",
    ]

    if config.seed is not None:
        command += ["--seed", str(config.seed)]

    status(f"Starting llama-server [{config.role}]")
    logger.info(f"Starting llama-server [{config.role}]", operation="server_start", context={
        "host": config.host,
        "port": config.port,
        "model": str(config.model),
        "threads": config.threads,
    })
    
    start_time = time.perf_counter()
    proc = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    deadline = time.time() + 120
    while time.time() < deadline:
        if proc.poll() is not None:
            err("llama-server exited during startup")
            logger.error("llama-server exited during startup", operation="server_start")
            return None
        if server_ready(config.base_url):
            elapsed = (time.perf_counter() - start_time) * 1000
            ok(f"Server ready [{config.role}]")
            logger.info(f"Server ready [{config.role}]", operation="server_start", duration_ms=elapsed)
            metrics.record_operation("server_start", elapsed, success=True)
            # Pre-warm KV cache if connection pool is enabled
            _pre_warm_on_ready(config)
            return proc
        time.sleep(0.25)

    proc.terminate()
    err("Server start timed out")
    logger.error("Server start timed out after 120s", operation="server_start")
    metrics.record_operation("server_start", 120000, success=False)
    return None


def _pre_warm_on_ready(config: Config) -> None:
    """Pre-warm the KV cache after server reports ready.
    
    Sends a single request with empty prompt and n_predict=1 to initialize
    the KV cache so subsequent requests start faster.
    Only runs when streaming_parse (connection pool) is enabled.
    """
    pool = _get_connection_pool(config)
    if pool is not None:
        try:
            pool.pre_warm()
        except Exception as e:
            logger.warn(f"Pre-warm failed (non-fatal): {e}")
    else:
        # Fallback: pre-warm via urllib if pool not enabled
        try:
            payload = {"prompt": "", "n_predict": 1, "temperature": 0.0, "cache_prompt": True}
            http_post_json(config.base_url + "/completion", payload, timeout=30)
            logger.info("KV cache pre-warmed via direct request")
        except Exception as e:
            logger.warn(f"Pre-warm failed (non-fatal): {e}")


# ── Grammar selection helper ──────────────────────────────────────────────────

def _select_grammar(config: Config, explicit_grammar: str | None) -> str | None:
    """Select the appropriate grammar for a generation request.
    
    Priority:
    1. Explicit grammar passed by caller (always used if provided)
    2. Adaptive grammar selector (if grammar_adaptive is enabled)
    3. None (no grammar enforcement)
    """
    if explicit_grammar is not None:
        return explicit_grammar

    selector = _get_adaptive_grammar(config)
    if selector is not None:
        return selector.select_grammar()

    return None


def _record_grammar_result(config: Config, content: str | None) -> None:
    """Record success/failure with the adaptive grammar selector."""
    selector = _get_adaptive_grammar(config)
    if selector is None:
        return

    if content and content.strip():
        selector.record_success()
    else:
        selector.record_empty_response()


# ── Streaming completion ──────────────────────────────────────────────────────

def completion_streaming(config: Config, prompt: str, max_tokens: int,
                          system_text=None, on_token=None, grammar: str | None = None,
                          schema_registry: dict | None = None):
    """Stream tokens from llama-server. Falls back to non-streaming if needed.
    
    When streaming_parse is enabled and a schema_registry is provided, tokens
    are fed to a StreamingActionParser for early action detection. If a valid
    action is detected mid-stream, the HTTP connection is closed to abort the
    remaining generation.
    """
    wrapped = build_chat_prompt(prompt, system_text)
    effective_grammar = _select_grammar(config, grammar)
    
    payload = {
        "prompt": wrapped,
        "n_predict": max_tokens,
        "temperature": config.temp,
        "stop": ["<|im_end|>", "<|endoftext|>", "<|im_start|>user"],
        "stream": True,
        "cache_prompt": True,
    }
    if effective_grammar:
        payload["grammar"] = effective_grammar
    if config.seed is not None:
        payload["seed"] = config.seed

    # Determine read timeout: 600s for CPU-only hardware (Requirement 13.3)
    read_timeout = max(config.timeout, 600)

    # Set up streaming action parser if enabled
    streaming_parser = None
    if config.streaming_parse and schema_registry:
        from .streaming import StreamingActionParser
        streaming_parser = StreamingActionParser(schema_registry)

    # Try connection pool first, fall back to urllib
    pool = _get_connection_pool(config)
    
    if pool is not None:
        result = _streaming_via_pool(
            pool, config, payload, read_timeout, on_token, streaming_parser
        )
        if result is not None:
            return result
        # Pool streaming failed, fall back to urllib
        logger.debug("Pool streaming failed, falling back to urllib")

    # Fallback: stream via urllib (original behavior)
    return _streaming_via_urllib(config, payload, read_timeout, on_token, streaming_parser)


def _streaming_via_pool(pool, config: Config, payload: dict, timeout: int,
                         on_token: Callable | None,
                         streaming_parser) -> str | None:
    """Stream tokens using the connection pool. Returns None on failure."""
    from .streaming import ParseEvent
    
    conn = None
    try:
        conn = pool.get_connection(timeout=30)
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Connection": "keep-alive",
        }
        conn.request("POST", "/completion", body=body, headers=headers)
        response = conn.getresponse()

        if response.status != 200:
            # Read body and release connection
            response.read()
            pool.release(conn)
            conn = None
            return None

        chunks = []
        early_action = None

        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            payload_str = line[5:].strip()
            if payload_str == "[DONE]":
                break
            try:
                obj = json.loads(payload_str)
            except json.JSONDecodeError:
                continue
            token = obj.get("content", "")
            if token:
                chunks.append(token)
                if on_token:
                    on_token(token)
                # Feed to streaming parser for early action detection
                if streaming_parser is not None:
                    event = streaming_parser.feed(token)
                    if event == ParseEvent.ACTION_READY:
                        early_action = streaming_parser.get_action()
                        logger.info(
                            "Early action detected via streaming parser, "
                            "closing connection to abort remaining stream"
                        )
                        # Close connection to abort remaining stream (Req 10.3)
                        try:
                            conn.close()
                        except Exception:
                            pass
                        # Don't release back to pool - it's closed
                        with pool._available_condition:
                            pool._checked_out = max(0, pool._checked_out - 1)
                            pool._available_condition.notify()
                        conn = None
                        break
            if obj.get("stop"):
                break

        # Release connection if still held
        if conn is not None:
            pool.release(conn)
            conn = None

        # If early action was detected, return the raw JSON for the caller
        if early_action is not None:
            # Return the JSON string so the agent loop can use it directly
            return json.dumps(early_action)

        # Finish streaming parser
        if streaming_parser is not None:
            streaming_parser.finish()

        result = clean_model_output("".join(chunks))
        return result if result else None

    except Exception as e:
        logger.debug(f"Pool streaming error: {e}")
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            with pool._available_condition:
                pool._checked_out = max(0, pool._checked_out - 1)
                pool._available_condition.notify()
        return None


def _streaming_via_urllib(config: Config, payload: dict, timeout: int,
                           on_token: Callable | None,
                           streaming_parser) -> str | None:
    """Stream tokens via urllib (original behavior with streaming parser support)."""
    from .streaming import ParseEvent

    url = config.base_url + "/completion"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Connection": "keep-alive"},
        method="POST",
    )

    try:
        chunks = []
        early_action = None

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                payload_str = line[5:].strip()
                if payload_str == "[DONE]":
                    break
                try:
                    obj = json.loads(payload_str)
                except json.JSONDecodeError:
                    continue
                token = obj.get("content", "")
                if token:
                    chunks.append(token)
                    if on_token:
                        on_token(token)
                    # Feed to streaming parser for early action detection
                    if streaming_parser is not None:
                        event = streaming_parser.feed(token)
                        if event == ParseEvent.ACTION_READY:
                            early_action = streaming_parser.get_action()
                            logger.info(
                                "Early action detected via streaming parser, "
                                "closing HTTP connection to abort stream"
                            )
                            # Close the connection to abort remaining stream (Req 10.3)
                            break
                if obj.get("stop"):
                    break

        # If early action was detected, return the raw JSON
        if early_action is not None:
            return json.dumps(early_action)

        # Finish streaming parser
        if streaming_parser is not None:
            streaming_parser.finish()

        result = clean_model_output("".join(chunks))
        return result if result else None
    except Exception:
        return completion_from_server(config, prompt=None, max_tokens=0, system_text=None,
                                      _payload_override=payload)


def completion_from_server(config: Config, prompt: str | None, max_tokens: int,
                           system_text=None, grammar: str | None = None,
                           _payload_override: dict | None = None):
    """Non-streaming completion from llama-server.
    
    Uses connection pool with retry policy when available, falls back to urllib.
    """
    if _payload_override is not None:
        # Used by streaming fallback - payload already built
        payload = dict(_payload_override)
        payload.pop("stream", None)
    else:
        wrapped = build_chat_prompt(prompt, system_text)
        effective_grammar = _select_grammar(config, grammar)
        payload = {
            "prompt": wrapped,
            "n_predict": max_tokens,
            "temperature": config.temp,
            "stop": ["<|im_end|>", "<|endoftext|>", "<|im_start|>user"],
            "cache_prompt": True,
        }
        if effective_grammar:
            payload["grammar"] = effective_grammar
        if config.seed is not None:
            payload["seed"] = config.seed

    # Read timeout: 600s for CPU-only hardware (Requirement 13.3)
    read_timeout = max(config.timeout, 600)
    url = config.base_url + "/completion"

    # Try connection pool with retry first
    pool = _get_connection_pool(config)
    if pool is not None:
        try:
            data = _pool_post_json_safe(pool, "/completion", payload, read_timeout)
        except Exception as pool_exc:
            logger.debug(f"Pool request failed, falling back to urllib: {pool_exc}")
            # Try reconnection if connection was lost
            _try_reconnect(config)
            data = _urllib_post_with_fallback(config, url, payload, read_timeout)
    else:
        data = _urllib_post_with_fallback(config, url, payload, read_timeout)

    content = data.get("content") or data.get("response")
    if not isinstance(content, str) or not content.strip():
        logger.error(
            "Server returned no or empty content",
            operation="completion",
            context={
                "response_keys": list(data.keys()) if isinstance(data, dict) else "not-a-dict",
                "response_sample": str(data)[:200]
            },
        )
        raise ModelError(
            "Server returned no content",
            context=ErrorContext(
                operation="completion",
                resource=url,
                recoverable=True,
                suggested_action="Try a different model or increase context size, then retry",
            ),
        )
    
    return clean_model_output(content)


def _urllib_post_with_fallback(config: Config, url: str, payload: dict, timeout: int) -> dict:
    """POST via urllib with minimal-payload fallback on failure."""
    try:
        data = http_post_json(url, payload, timeout=timeout)
    except Exception as exc:
        try:
            # Minimal fallback: strip grammar and extra fields
            wrapped = payload.get("prompt", "")
            minimal = {
                "prompt": wrapped,
                "n_predict": payload.get("n_predict", 128),
                "temperature": payload.get("temperature", config.temp),
            }
            data = http_post_json(url, minimal, timeout=timeout)
        except Exception as exc2:
            raise NetworkError(
                f"Server request failed: {exc2}",
                url=url,
                context=ErrorContext(
                    operation="completion",
                    resource=url,
                    recoverable=True,
                    suggested_action="Ensure llama-server is running and reachable, then retry",
                ),
                cause=exc2,
            ) from exc2
    return data


def _try_reconnect(config: Config) -> None:
    """Attempt reconnection using ReconnectionManager on connection loss."""
    try:
        from .connection_pool import ReconnectionManager
        manager = ReconnectionManager(
            poll_interval=5,
            max_wait=config.reconnect_timeout,
        )
        health_url = config.base_url + "/health"
        if manager.wait_for_server(health_url):
            logger.info("Server reconnected successfully")
        else:
            logger.warn("Server reconnection timed out")
    except Exception as e:
        logger.debug(f"Reconnection attempt error: {e}")


def get_embeddings(config: Config, text: str, timeout: int = 60) -> list[float]:
    """Get embeddings from llama-server. Returns empty list if embeddings not supported."""
    url = config.base_url + "/embedding"
    payload = {"content": text}
    
    try:
        data = http_post_json(url, payload, timeout=timeout)
        embedding = data.get("embedding")
        if not embedding or not isinstance(embedding, list):
            # Server may not support embeddings (e.g., 501 Not Implemented)
            return []
        return [float(x) for x in embedding]
    except urllib.error.HTTPError as he:
        # Expected when server doesn't support embeddings (501 Not Implemented)
        if he.code == 501:
            logger.debug("Embeddings endpoint not supported by server (501 Not Implemented)", operation="embeddings")
        else:
            logger.debug(f"HTTP error getting embeddings: {he.code}", operation="embeddings")
        return []
    except Exception as e:
        # Silently fail for other errors - RAG is optional
        logger.debug(f"Embeddings unavailable: {type(e).__name__}", operation="embeddings")
        return []


def get_embeddings_batch(config: Config, texts: list[str], timeout: int = 60) -> list[list[float]]:
    """
    Get embeddings for multiple texts in a single batched API call.

    Tries the /embeddings (plural) endpoint first for true batch support.
    If that fails, falls back to individual /embedding calls grouped into
    batches of 16 (ceil(N/16) calls instead of N).

    Returns a list of embedding vectors (one per input text).
    Returns an empty vector [] for any text that fails to embed.
    """
    if not texts:
        return []

    # Try batch endpoint first (/embeddings plural)
    batch_result = _try_batch_endpoint(config, texts, timeout)
    if batch_result is not None:
        return batch_result

    # Fallback: individual calls grouped into batches of 16
    _BATCH_GROUP_SIZE = 16
    logger.debug(
        f"Batch endpoint unavailable, using grouped individual calls "
        f"({len(texts)} texts in groups of {_BATCH_GROUP_SIZE})"
    )
    results: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_GROUP_SIZE):
        group = texts[i:i + _BATCH_GROUP_SIZE]
        for text in group:
            embedding = get_embeddings(config, text, timeout=timeout)
            results.append(embedding)

    return results


def _try_batch_endpoint(config: Config, texts: list[str], timeout: int) -> list[list[float]] | None:
    """
    Try the /embeddings (plural) batch endpoint.
    Returns None if not supported, allowing fallback to individual calls.
    """
    url = config.base_url + "/embeddings"
    payload = {"content": texts}

    try:
        data = http_post_json(url, payload, timeout=timeout)

        # Try common response shapes
        if "results" in data and isinstance(data["results"], list):
            embeddings = []
            for item in data["results"]:
                if isinstance(item, dict) and "embedding" in item:
                    embeddings.append([float(x) for x in item["embedding"]])
                elif isinstance(item, list):
                    embeddings.append([float(x) for x in item])
                else:
                    embeddings.append([])
            if len(embeddings) == len(texts):
                return embeddings

        # Alternative format
        if "embeddings" in data and isinstance(data["embeddings"], list):
            embeddings = []
            for item in data["embeddings"]:
                if isinstance(item, list):
                    embeddings.append([float(x) for x in item])
                else:
                    embeddings.append([])
            if len(embeddings) == len(texts):
                return embeddings

        return None

    except urllib.error.HTTPError as he:
        logger.debug(f"Batch embeddings endpoint not supported ({he.code})", operation="embeddings_batch")
        return None
    except Exception as e:
        logger.debug(f"Batch embeddings failed: {type(e).__name__}", operation="embeddings_batch")
        return None


# ── Main generate entrypoint ──────────────────────────────────────────────────

def generate_fast(config: Config, prompt: str, system_text: str | None = None,
                  max_tokens: int = 80) -> str | None:
    """Generate using the fast 0.5B model (CONVO/QUERY route).
    
    Always uses ollama_fast_model. No fallback — if it fails, caller handles it.
    """
    fast_model = getattr(config, 'ollama_fast_model', 'qwen2.5:0.5b')
    return ollama_generate(
        model=fast_model,
        prompt=prompt,
        system_text=system_text,
        max_tokens=max_tokens,
        temperature=0.7,
    )


def generate(config: Config, prompt: str, max_tokens: int = 128,
             system_text=None, use_cache: bool = True, on_token=None,
             grammar: str | None = None, schema_registry: dict | None = None):
    """Generate text from llama-server or Ollama with caching, streaming, and adaptive grammar.
    
    Args:
        config: Backend configuration.
        prompt: The user/agent prompt text.
        max_tokens: Maximum tokens to generate.
        system_text: Optional system prompt text.
        use_cache: Whether to use the generation cache.
        on_token: Callback for streaming tokens.
        grammar: Explicit grammar override (bypasses adaptive selection).
        schema_registry: Tool schema registry for streaming action detection.
                        When provided with streaming_parse=True, enables early
                        action detection via StreamingActionParser.
    """
    # Resolve effective grammar for cache key
    effective_grammar = _select_grammar(config, grammar)
    cache_key = (str(config.model) or getattr(config, 'ollama_model', ''), 
                 system_text or "", prompt, int(max_tokens),
                 float(config.temp), effective_grammar or "")
    
    logger.debug("Generation request", operation="generate", context={
        "model": str(config.model) if config.model else getattr(config, 'ollama_model', 'unknown'),
        "max_tokens": max_tokens,
        "use_cache": use_cache,
        "use_ollama": getattr(config, 'use_ollama', False),
        "grammar_adaptive": config.grammar_adaptive,
        "streaming_parse": config.streaming_parse,
    })

    if use_cache:
        cached = _GENERATION_CACHE.get(cache_key)
        if cached is not None:
            ok("Generated from cache")
            logger.debug("Cache hit", operation="generate")
            metrics.increment("cache_hits")
            if on_token:
                on_token(cached)
            return cached
        metrics.increment("cache_misses")

    started = time.perf_counter()
    
    try:
        # Ensure servers are running (auto-start if idle-stopped)
        from .server_manager import get_server_manager
        mgr = get_server_manager()
        mgr.touch()  # Record activity
        
        # Route to Ollama if enabled
        if getattr(config, 'use_ollama', False):
            if not mgr.ensure_ollama():
                raise RuntimeError("Ollama is not available. Start Ollama and retry.")
            model_name = getattr(config, 'ollama_model', 'qwen2.5:3b')
            ollama_prompt = prompt
            if system_text and prompt.startswith(system_text):
                ollama_prompt = prompt[len(system_text):].lstrip("\n")
            content = ollama_generate(
                model=model_name,
                prompt=ollama_prompt,
                system_text=system_text,
                max_tokens=max_tokens,
                temperature=config.temp,
                grammar=None,
                on_token=on_token,
            )
        elif on_token or (config.streaming_parse and schema_registry):
            content = completion_streaming(
                config, prompt, max_tokens, system_text,
                on_token=on_token, grammar=grammar,
                schema_registry=schema_registry,
            )
        else:
            content = completion_from_server(
                config, prompt, max_tokens, system_text, grammar=grammar,
            )
    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000
        logger.error("Generation failed", operation="generate", duration_ms=elapsed, error=exc)
        metrics.record_operation("generate", elapsed, success=False)
        raise

    elapsed = (time.perf_counter() - started) * 1000

    # Record result with adaptive grammar selector
    _record_grammar_result(config, content)

    if content:
        if use_cache:
            _GENERATION_CACHE.set(cache_key, content)
        ok(f"Generated in {elapsed/1000:.2f}s")
        logger.info("Generation successful", operation="generate", duration_ms=elapsed, context={
            "content_length": len(content),
        })
        metrics.record_operation("generate", elapsed, success=True)
        return content

    err("No content generated")
    logger.warn("Generation returned empty content", operation="generate", duration_ms=elapsed)
    metrics.record_operation("generate", elapsed, success=False)
    return None


# ── Cleanup ───────────────────────────────────────────────────────────────────

def close_pool() -> None:
    """Close the connection pool. Call on shutdown."""
    global _connection_pool
    if _connection_pool is not None:
        _connection_pool.close_all()
        _connection_pool = None
