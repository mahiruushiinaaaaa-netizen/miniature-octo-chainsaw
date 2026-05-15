"""
intent_classifier.py – AI-powered intent classification using 0.5B model.

Replaces the regex-based _classify_intent() with a tiny AI call that outputs
exactly one intent word. Falls back to regex if Ollama is unavailable.

Intents:
  CONVO   – greeting, memory question, casual chat → answer instantly from memory/LLM
  QUERY   – knowledge question, "how do I", "what is" → answer with LLM
  TASK    – run a command, install, create project → execute tool directly
  EDIT    – fix/change/refactor code → agent loop with edit tools
  EXPLORE – complex multi-step, unclear → full agent loop
  COMPLEX – massive orchestration task → orchestrator

Speed target: < 0.5s (0.5B model, 1 output token via GBNF)
"""
from __future__ import annotations

import json
import urllib.request
from typing import Optional

from .logger import get_logger

logger = get_logger("intent_classifier")

# ── Grammar: forces exactly one intent word ──────────────────────────────────
_INTENT_GRAMMAR = r'''
root ::= intent
intent ::= "CONVO" | "QUERY" | "TASK" | "EDIT" | "EXPLORE" | "COMPLEX"
'''

# ── System prompt: ultra-short (~20 tokens) ───────────────────────────────────
_SYSTEM = "Classify the user request into one word: CONVO QUERY TASK EDIT EXPLORE COMPLEX. Output only the word."

# ── Few-shot examples baked into the prompt (~80 tokens total) ───────────────
_EXAMPLES = (
    'hi→CONVO\n'
    'what time is it→CONVO\n'
    'what music did we play→CONVO\n'
    'how does async work→QUERY\n'
    'explain recursion→QUERY\n'
    'git status→TASK\n'
    'npm install express→TASK\n'
    'ping google.com→TASK\n'
    'create a flask app→TASK\n'
    'create a txt file with hello world→TASK\n'
    'make a new file called test.py→TASK\n'
    'take me to downloads→TASK\n'
    'go to desktop folder→TASK\n'
    'navigate to documents directory→TASK\n'
    'fix the login bug→EDIT\n'
    'refactor this function→EDIT\n'
    'add error handling→EDIT\n'
    'build a full todo app with auth→COMPLEX\n'
    'create a laravel project with breeze like facebook→COMPLEX\n'
    'make a website with login and dashboard→COMPLEX\n'
    'create a project with custom UI→COMPLEX\n'
    'build an app with multiple pages→COMPLEX\n'
    'deploy to production→EXPLORE\n'
)


class IntentClassifier:
    """AI-powered intent classifier using 0.5B Ollama model.
    
    Falls back to regex classifier if Ollama unavailable.
    Caches results for repeated identical inputs.
    """

    def __init__(self, model: str = "qwen2.5:0.5b", url: str = "http://127.0.0.1:11434"):
        self._model = model
        self._url = url
        self._ready: Optional[bool] = None
        self._cache: dict[str, str] = {}  # goal → intent cache

    @property
    def is_ready(self) -> bool:
        if self._ready is not None:
            return self._ready
        try:
            req = urllib.request.Request(f"{self._url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=1) as resp:
                data = json.loads(resp.read().decode())
                models = [m.get("name", "") for m in data.get("models", [])]
                self._ready = any(self._model.split(":")[0] in m for m in models)
        except Exception:
            self._ready = False
        return self._ready

    def classify(self, goal: str) -> str:
        """Classify goal into intent. Returns one of: CONVO QUERY TASK EDIT EXPLORE COMPLEX."""
        # Cache hit
        key = goal.strip().lower()[:80]
        if key in self._cache:
            return self._cache[key]

        if not self.is_ready:
            return ""  # Signal: use regex fallback

        try:
            prompt = f"{_EXAMPLES}\n{goal}→"
            payload = {
                "model": self._model,
                "prompt": prompt,
                "system": _SYSTEM,
                "stream": False,
                "keep_alive": "30m",
                "options": {
                    "num_predict": 3,   # One word max (COMPLEX = 7 chars)
                    "temperature": 0,
                    "top_k": 1,
                    "num_ctx": 512,     # Tiny context = fast
                },
            }
            # Grammar forces exactly one valid intent word
            payload["options"]["grammar"] = _INTENT_GRAMMAR

            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{self._url}/api/generate",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                result = json.loads(resp.read().decode())
                intent = result.get("response", "").strip().upper()

            valid = {"CONVO", "QUERY", "TASK", "EDIT", "EXPLORE", "COMPLEX"}
            if intent in valid:
                self._cache[key] = intent
                logger.debug(f"AI intent: '{goal[:40]}' → {intent}")
                return intent

        except Exception as e:
            logger.debug(f"Intent classification failed: {e}")

        return ""  # Fallback to regex


# Module-level singleton
_classifier: Optional[IntentClassifier] = None


def get_classifier(model: str = "qwen2.5:0.5b") -> IntentClassifier:
    global _classifier
    if _classifier is None:
        _classifier = IntentClassifier(model=model)
    return _classifier
