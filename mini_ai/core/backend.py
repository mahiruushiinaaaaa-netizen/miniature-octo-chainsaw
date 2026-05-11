"""
backend.py – Optimized backend with streaming, connection pooling, and smart caching.
Low-end device friendly: minimal memory, fast timeout, reused connections.
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

# ── HTTP helpers ──────────────────────────────────────────────────────────────

def http_get_json(url: str, timeout: int = 2):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
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


def server_ready(base_url: str) -> bool:
    for path in ("/health", "/healthz", "/v1/models"):
        if http_get_json(base_url + path, timeout=2) is not None:
            return True
    return False


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
            return proc
        time.sleep(0.25)

    proc.terminate()
    err("Server start timed out")
    logger.error("Server start timed out after 120s", operation="server_start")
    metrics.record_operation("server_start", 120000, success=False)
    return None


# ── Streaming completion ──────────────────────────────────────────────────────

def completion_streaming(config: Config, prompt: str, max_tokens: int,
                          system_text=None, on_token=None, grammar: str | None = None):
    """Stream tokens from llama-server. Falls back to non-streaming if needed."""
    wrapped = build_chat_prompt(prompt, system_text)
    payload = {
        "prompt": wrapped,
        "n_predict": max_tokens,
        "temperature": config.temp,
        "stop": ["<|im_end|>", "<|endoftext|>", "<|im_start|>user"],
        "stream": True,
        "cache_prompt": True,
    }
    if grammar:
        payload["grammar"] = grammar
    if config.seed is not None:
        payload["seed"] = config.seed

    url = config.base_url + "/completion"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        chunks = []
        with urllib.request.urlopen(req, timeout=max(config.timeout, 600)) as resp:
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
                if obj.get("stop"):
                    break
        result = clean_model_output("".join(chunks))
        return result if result else None
    except Exception:
        return completion_from_server(config, prompt, max_tokens, system_text)


def completion_from_server(config: Config, prompt: str, max_tokens: int, system_text=None, grammar: str | None = None):
    wrapped = build_chat_prompt(prompt, system_text)
    payload = {
        "prompt": wrapped,
        "n_predict": max_tokens,
        "temperature": config.temp,
        "stop": ["<|im_end|>", "<|endoftext|>", "<|im_start|>user"],
        "cache_prompt": True,
    }
    if grammar:
        payload["grammar"] = grammar
    if config.seed is not None:
        payload["seed"] = config.seed

    url = config.base_url + "/completion"
    try:
        data = http_post_json(url, payload, timeout=max(config.timeout, 600))
    except Exception as exc:
        try:
            minimal = {"prompt": wrapped, "n_predict": max_tokens, "temperature": config.temp}
            data = http_post_json(url, minimal, timeout=max(config.timeout, 600))
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


# ── Main generate entrypoint ──────────────────────────────────────────────────

def generate(config: Config, prompt: str, max_tokens: int = 128,
             system_text=None, use_cache: bool = True, on_token=None, grammar: str | None = None):
    cache_key = (str(config.model), system_text or "", prompt, int(max_tokens), float(config.temp), grammar or "")
    
    logger.debug("Generation request", operation="generate", context={
        "model": str(config.model),
        "max_tokens": max_tokens,
        "use_cache": use_cache,
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
        if on_token:
            content = completion_streaming(config, prompt, max_tokens, system_text, on_token=on_token, grammar=grammar)
        else:
            content = completion_from_server(config, prompt, max_tokens, system_text, grammar=grammar)
    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000
        logger.error("Generation failed", operation="generate", duration_ms=elapsed, error=exc)
        metrics.record_operation("generate", elapsed, success=False)
        raise

    elapsed = (time.perf_counter() - started) * 1000

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
