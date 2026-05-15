"""
prompt_rewriter.py – Lightweight prompt rewriter + task planner using a small model via Ollama.

Uses a tiny 0.5B model (via Ollama API) to:
1. Rewrite messy user input into clean, structured prompts
2. Extract proper search queries from vague requests
3. Plan task decomposition (e.g., install Laravel → check PHP → check composer → run command)

The 0.5B model runs via Ollama and generates in 1-3 seconds.
"""
from __future__ import annotations

import json
from typing import Optional

from .logger import get_logger

logger = get_logger("prompt_rewriter")


# System prompt for search query extraction — kept minimal for speed
_SEARCH_EXTRACTOR_SYSTEM = (
    "Extract a web search query from the user's request. "
    "Output ONLY the search query (5-10 words max), nothing else. No explanation."
)

# System prompt for goal rewriting
_REWRITER_SYSTEM = (
    "Rewrite this into a clear, concise technical instruction. "
    "Output ONLY the rewritten text (1 sentence max), nothing else."
)

# System prompt for task planning (dependency-aware)
_PLANNER_SYSTEM = (
    "You are a task planner. List the REQUIRED commands in order, one per line. "
    "Include dependency installations if needed. Windows commands only. "
    "Format: just the commands, no explanations. Max 5 lines."
)


class PromptRewriter:
    """Rewrites user prompts using a small model via Ollama for clarity.
    
    Uses Ollama's API to run a 0.5B model for fast prompt preprocessing.
    Falls back to rule-based extraction if Ollama isn't available.
    """

    def __init__(self, config: "Config", model_name: str = "qwen2.5:0.5b") -> None:
        """Initialize the prompt rewriter.
        
        Args:
            config: Main app config.
            model_name: Ollama model name to use for rewriting.
        """
        self._config = config
        self._model_name = model_name
        self._ollama_url = "http://127.0.0.1:11434"
        self._ready: Optional[bool] = None  # None = not checked yet

    def _check_ready(self) -> bool:
        """Check if Ollama is running and has the model available."""
        # Always re-check if previously failed (Ollama may have started since)
        if self._ready is True:
            return True
        
        # Ensure Ollama is running via server manager
        from .server_manager import get_server_manager
        mgr = get_server_manager()
        if not mgr.ensure_ollama():
            self._ready = False
            return False
        
        import urllib.request
        try:
            req = urllib.request.Request(
                f"{self._ollama_url}/api/tags",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                models = [m.get("name", "") for m in data.get("models", [])]
                # Check if our model (or a variant) is available
                self._ready = any(
                    self._model_name.split(":")[0] in m 
                    for m in models
                )
                if self._ready:
                    logger.info(f"Rewriter model available via Ollama: {self._model_name}")
                else:
                    logger.debug(f"Rewriter model '{self._model_name}' not found in Ollama. Available: {models[:5]}")
                return self._ready
        except Exception as e:
            logger.debug(f"Ollama not available: {e}")
            self._ready = False
            return False

    def start(self) -> bool:
        """Check if the rewriter is available (lazy check)."""
        return self._check_ready()

    def stop(self) -> None:
        """No-op for Ollama-based rewriter (Ollama manages its own lifecycle)."""
        pass

    @property
    def is_ready(self) -> bool:
        """Check if the rewriter is available."""
        if self._ready is None:
            return self._check_ready()
        return self._ready

    def rewrite_goal(self, goal: str) -> str:
        """Rewrite a user goal into a clear, actionable instruction.
        
        If the rewriter isn't available, returns the original goal unchanged.
        """
        if not self.is_ready:
            return goal
        
        # Don't rewrite very short or already clear goals
        if len(goal) < 15 or goal.startswith(("install ", "create ", "run ", "fix ")):
            return goal
        
        result = self._generate(
            prompt=f"Rewrite: \"{goal}\"",
            system=_REWRITER_SYSTEM,
            max_tokens=60,
        )
        
        # Validate — if empty or way longer than original, use original
        if not result or len(result) > len(goal) * 2:
            return goal
        
        return result.strip().strip('"').strip("'")

    def extract_search_query(self, goal: str) -> str:
        """Extract a clean web search query from a user request.
        
        If the rewriter isn't available, falls back to basic keyword extraction.
        """
        if not self.is_ready:
            return self._fallback_extract(goal)
        
        result = self._generate(
            prompt=f"Extract search query from: \"{goal}\"",
            system=_SEARCH_EXTRACTOR_SYSTEM,
            max_tokens=20,
        )
        
        if not result or len(result) < 3:
            return self._fallback_extract(goal)
        
        return result.strip().strip('"').strip("'")

    def plan_task(self, goal: str) -> Optional[list[str]]:
        """Plan a task by decomposing it into ordered commands.
        
        For example: "install laravel" →
        [
            "winget install Shivammathur.PHP",
            "winget install getcomposer.Composer",
            "composer create-project laravel/laravel my-laravel-app"
        ]
        
        Returns None if planner isn't available or plan is invalid.
        """
        if not self.is_ready:
            return None
        
        # Only plan for obvious dev/install tasks
        goal_lower = goal.lower()
        if not any(kw in goal_lower for kw in [
            "install", "setup", "create", "build", "deploy", "laravel",
            "django", "react", "vue", "next", "composer", "php", "node",
        ]):
            return None
        
        result = self._generate(
            prompt=f"Plan Windows commands for: \"{goal}\"",
            system=_PLANNER_SYSTEM,
            max_tokens=200,
        )
        
        if not result:
            return None
        
        # Parse lines — remove numbering, empty lines, explanations
        lines = []
        for line in result.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Remove leading numbering like "1. " or "1) " or "- "
            import re as _re
            line = _re.sub(r"^[\d]+[.)]\s*", "", line)
            line = _re.sub(r"^[-*]\s*", "", line)
            # Skip explanation lines
            if line.startswith(("#", "//", "Note:", "First,", "Then,", "Next,")):
                continue
            if len(line) < 3 or len(line) > 200:
                continue
            lines.append(line)
        
        return lines[:5] if lines else None

    def _fallback_extract(self, goal: str) -> str:
        """Basic keyword extraction when rewriter model isn't available."""
        filler = {
            "i", "me", "my", "you", "the", "a", "an", "to", "do", "can",
            "help", "need", "want", "please", "how", "get", "make", "with",
            "some", "just", "really", "actually", "basically", "like",
            "would", "could", "should", "am", "is", "are", "it", "this",
            "that", "for", "on", "in", "at", "of",
        }
        words = [w for w in goal.split() if w.lower() not in filler and len(w) > 1]
        if not words:
            return goal
        return " ".join(words)

    def _generate(self, prompt: str, system: str, max_tokens: int = 60) -> Optional[str]:
        """Generate from the rewriter model via Ollama API."""
        import urllib.request
        
        # Record activity with server manager
        from .server_manager import get_server_manager
        get_server_manager().touch()
        
        payload = {
            "model": self._model_name,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": 0.1,
            },
        }
        
        url = f"{self._ollama_url}/api/generate"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                result = json.loads(raw)
                content = result.get("response", "").strip()
                return content if content else None
        except Exception as e:
            logger.debug(f"Rewriter generation failed: {e}")
            return None
