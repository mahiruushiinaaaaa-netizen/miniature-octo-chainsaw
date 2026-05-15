"""
goal_dispatcher.py – AI-powered goal → tool dispatch using 0.5B model via Ollama.

Uses a tiny model with a tight GBNF grammar to classify user goals into
structured tool calls in ~0.3-1s. Only used for ambiguous inputs that
the regex instant-dispatch can't handle confidently.

Flow:
  1. User says "check my project"
  2. 0.5B model outputs: {"tool":"project_health","args":"."} in ~0.5s
  3. Tool executes instantly
  4. Total: ~0.5-1s instead of 5-15s with full agent loop
"""
from __future__ import annotations

import json
from typing import Any, Optional

from .logger import get_logger

logger = get_logger("goal_dispatcher")


# Ultra-minimal system prompt (~20 tokens)
_DISPATCH_SYSTEM = "Map the user request to a tool call. Output JSON only."

# GBNF grammar that forces structured output: {"tool":"name","op":"value","args":"value"}
# This makes the 0.5B model output ONLY the tool call, no thinking/narration
_DISPATCH_GRAMMAR = r'''
root ::= "{" space "\"tool\"" space ":" space tool_name "," space "\"op\"" space ":" space string "," space "\"args\"" space ":" space string space "}"
tool_name ::= "\"git_op\"" | "\"docker_op\"" | "\"package_op\"" | "\"code_analyze\"" | "\"test_op\"" | "\"convert\"" | "\"net_op\"" | "\"project_init\"" | "\"project_info\"" | "\"project_health\"" | "\"dependency_tree\"" | "\"file_op_ext\"" | "\"text_op\"" | "\"json_format\"" | "\"markdown_op\"" | "\"crypto_op\"" | "\"run_cmd\"" | "\"web_search\"" | "\"read_files\"" | "\"write_files\"" | "\"list_dir\"" | "\"search_files\"" | "\"calculate\"" | "\"datetime_util\"" | "\"http_request\"" | "\"sqlite_query\"" | "\"system_info\"" | "\"clipboard\"" | "\"screenshot\"" | "\"diff_files\"" | "\"file_info\"" | "\"open_browser\"" | "\"play_media\"" | "\"youtube_download\"" | "\"pdf_summarize\"" | "\"image_resize\"" | "\"auto_backup\"" | "\"daily_digest\"" | "\"project_stats\"" | "\"dependency_audit\"" | "\"docker_helper\"" | "\"auto_commit\"" | "\"cron_scheduler\"" | "\"answer\"" | "\"agent\""
string ::= "\"" ( [^"\\\x00-\x1F] | "\\" ["\\/bfnrt] )* "\""
space ::= [ \t\n\r]*
'''

# One-shot examples embedded in the prompt for accuracy (adds ~100 tokens but massively improves accuracy)
_EXAMPLES = """Examples:
"check my project" → {"tool":"project_health","op":"","args":"."}
"analyze code complexity" → {"tool":"code_analyze","op":"complexity","args":"."}
"show git branches" → {"tool":"git_op","op":"branch","args":"list"}
"install flask" → {"tool":"package_op","op":"install","args":"flask"}
"what ports are open" → {"tool":"net_op","op":"port_scan","args":"localhost"}
"find large files" → {"tool":"file_op_ext","op":"find_large","args":"."}
"create a flask app called myapp" → {"tool":"project_init","op":"flask_app","args":"myapp"}
"download this youtube video" → {"tool":"youtube_download","op":"mp4","args":""}
"summarize the pdf" → {"tool":"pdf_summarize","op":"summary","args":""}
"resize image to 800px" → {"tool":"image_resize","op":"width","args":"800"}
"backup my project" → {"tool":"auto_backup","op":"snapshot","args":"."}
"show my daily digest" → {"tool":"daily_digest","op":"today","args":"."}
"project stats" → {"tool":"project_stats","op":"","args":"."}
"audit dependencies" → {"tool":"dependency_audit","op":"","args":"."}
"docker compose up" → {"tool":"docker_helper","op":"compose_up","args":""}
"commit my changes" → {"tool":"auto_commit","op":"smart","args":"."}
"list scheduled tasks" → {"tool":"cron_scheduler","op":"list","args":""}
"build me a todo app with react" → {"tool":"agent","op":"","args":""}
"fix the login bug" → {"tool":"agent","op":"","args":""}
"""


class GoalDispatcher:
    """Dispatches user goals to tools using a 0.5B model for classification.
    
    Optimizations for speed:
    - GBNF grammar forces structured output (no narration/thinking)
    - max_tokens=50 (tool call is ~30 tokens max)
    - temperature=0 (deterministic, no sampling overhead)
    - Tiny system prompt (~20 tokens)
    - Falls back to "agent" for complex tasks (full loop handles those)
    """

    def __init__(self, model_name: str = "qwen2.5:0.5b", ollama_url: str = "http://127.0.0.1:11434"):
        self._model = model_name
        self._url = ollama_url
        self._ready: Optional[bool] = None

    @property
    def is_ready(self) -> bool:
        """Check if Ollama is available (cached after first check)."""
        if self._ready is not None:
            return self._ready
        try:
            import urllib.request
            req = urllib.request.Request(f"{self._url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read().decode())
                models = [m.get("name", "") for m in data.get("models", [])]
                self._ready = any(self._model.split(":")[0] in m for m in models)
        except Exception:
            self._ready = False
        return self._ready

    def dispatch(self, goal: str) -> Optional[dict[str, str]]:
        """Classify a user goal into a structured tool call.
        
        Returns:
            {"tool": "tool_name", "op": "operation", "args": "arguments"}
            or None if dispatch fails or model unavailable.
            
            Special case: {"tool": "agent", ...} means "use full agent loop"
        """
        if not self.is_ready:
            return None

        # Build ultra-compact prompt
        prompt = f'{_EXAMPLES}\nUser: "{goal}"\nTool call:'

        try:
            import urllib.request
            
            payload = {
                "model": self._model,
                "prompt": prompt,
                "system": _DISPATCH_SYSTEM,
                "stream": False,
                "keep_alive": "30m",
                "options": {
                    "num_predict": 50,
                    "temperature": 0,
                    "top_k": 1,
                    "num_ctx": 512,
                },
            }
            
            # Add grammar if supported (Ollama supports it)
            # Grammar forces valid JSON output — no parsing failures
            payload["options"]["grammar"] = _DISPATCH_GRAMMAR

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self._url}/api/generate",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=3) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                result = json.loads(raw)
                content = result.get("response", "").strip()
                
                if not content:
                    return None

                # Parse the structured output
                parsed = json.loads(content)
                tool = parsed.get("tool", "").strip()
                op = parsed.get("op", "").strip()
                args = parsed.get("args", "").strip()

                if not tool:
                    return None

                logger.info(f"Dispatched: '{goal[:40]}' → {tool}({op}, {args})")
                return {"tool": tool, "op": op, "args": args}

        except json.JSONDecodeError as e:
            logger.debug(f"Dispatch parse error: {e}")
            return None
        except Exception as e:
            logger.debug(f"Dispatch failed: {e}")
            return None


def build_action_from_dispatch(dispatch: dict[str, str], pm: "PathManager") -> Optional[dict[str, Any]]:
    """Convert a dispatch result into an executor-ready action dict.
    
    Maps the simplified {tool, op, args} format to the full action schema
    expected by ToolExecutor.execute().
    """
    tool = dispatch["tool"]
    op = dispatch["op"]
    args = dispatch["args"]

    if tool == "agent":
        return None  # Signal: use full agent loop

    # Tools with operation + args pattern
    op_tools = {
        "git_op": {"action": "git_op", "operation": op or "status", "args": args, "path": str(pm.effective_root)},
        "docker_op": {"action": "docker_op", "operation": op or "ps", "target": args},
        "code_analyze": {"action": "code_analyze", "operation": op or "metrics", "path": args or str(pm.effective_root)},
        "test_op": {"action": "test_op", "operation": op or "run", "path": args or str(pm.effective_root)},
        "net_op": {"action": "net_op", "operation": op or "ping", "target": args},
        "file_op_ext": {"action": "file_op_ext", "operation": op or "tree", "path": args or str(pm.effective_root)},
        "text_op": {"action": "text_op", "operation": op, "input": args},
        "json_format": {"action": "json_format", "input": args, "operation": op or "pretty"},
        "markdown_op": {"action": "markdown_op", "operation": op, "input": args},
        "crypto_op": {"action": "crypto_op", "operation": op or "hash", "input": args},
        "project_health": {"action": "project_health", "path": args or str(pm.effective_root)},
        "project_info": {"action": "project_info", "path": args or str(pm.effective_root)},
        "dependency_tree": {"action": "dependency_tree", "path": args or str(pm.effective_root)},
        "system_info": {"action": "system_info", "query": op or args or "all"},
        "datetime_util": {"action": "datetime_util", "operation": op or "now", "value": args},
        "calculate": {"action": "calculate", "expression": args or op},
        "clipboard": {"action": "clipboard", "operation": op or "paste", "content": args},
        "screenshot": {"action": "screenshot", "output": args or "screenshot.png"},
        "diff_files": {"action": "diff_files", "file1": op, "file2": args},
        "file_info": {"action": "file_info", "path": args or "."},
        "open_browser": {"action": "open_browser", "url": args},
        "play_media": {"action": "play_media", "query": args},
        "web_search": {"action": "web_search", "query": args},
        "run_cmd": {"action": "run_cmd", "command": args or op},
        "read_files": {"action": "read_files", "files": [args] if args else ["."]},
        "list_dir": {"action": "list_dir", "path": args or "."},
        "search_files": {"action": "search_files", "path": str(pm.effective_root), "pattern": args},
        "http_request": {"action": "http_request", "method": "GET", "url": args},
        "sqlite_query": {"action": "sqlite_query", "database": op, "query": args},
    }

    # Package op needs special handling (manager in op field)
    if tool == "package_op":
        # op might be "npm install" or just "install"
        parts = op.split(maxsplit=1) if op else ["pip", "list"]
        if len(parts) == 2 and parts[0] in ("npm", "pip", "yarn", "cargo", "composer", "go", "pnpm"):
            return {"action": "package_op", "manager": parts[0], "operation": parts[1], "package": args}
        return {"action": "package_op", "manager": "pip", "operation": op or "list", "package": args}

    # Project init needs template + name
    if tool == "project_init":
        return {"action": "project_init", "template": op or "python_package", "name": args or "my_project", "path": str(pm.effective_root)}

    # Convert needs category detection
    if tool == "convert":
        # op = "5 km", args = "mi" or op = "length", args = "5 km mi"
        return {"action": "convert", "category": "length", "value": op, "from_unit": "", "to_unit": args}

    # --- Automation tools ---
    if tool == "youtube_download":
        return {"action": "youtube_download", "url": args, "format": op or "mp4"}
    if tool == "pdf_summarize":
        return {"action": "pdf_summarize", "file": args or ".", "mode": op or "summary"}
    if tool == "image_resize":
        return {"action": "image_resize", "file": args, "width": int(op) if op.isdigit() else 0, "scale": 0.5 if not op.isdigit() else 0.0}
    if tool == "auto_backup":
        return {"action": "auto_backup", "path": args or str(pm.effective_root), "mode": op or "snapshot"}
    if tool == "daily_digest":
        return {"action": "daily_digest", "path": args or str(pm.effective_root), "scope": op or "today"}
    if tool == "project_stats":
        return {"action": "project_stats", "path": args or str(pm.effective_root)}
    if tool == "dependency_audit":
        return {"action": "dependency_audit", "path": args or str(pm.effective_root)}
    if tool == "docker_helper":
        return {"action": "docker_helper", "operation": op or "compose_status", "target": args}
    if tool == "auto_commit":
        return {"action": "auto_commit", "path": args or str(pm.effective_root), "mode": op or "smart"}
    if tool == "cron_scheduler":
        return {"action": "cron_scheduler", "operation": op or "list", "name": args}

    return op_tools.get(tool)
