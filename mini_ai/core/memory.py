"""
memory.py – Persistent and session memory. Compact display for GUI.
Rich memory system with strategies and learning.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

APP_DIR = Path.home() / ".mini_ai_cli"
MEMORY_FILE = APP_DIR / "memory.json"


def load_memory() -> dict[str, Any]:
    try:
        if MEMORY_FILE.exists():
            return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        from .core import get_logger
        logger = get_logger("memory")
        logger.warning(f"Failed to load memory from {MEMORY_FILE}: {e}. Starting with empty memory.")
    return {"events": [], "projects": {}, "facts": [], "strategies": [], "learned_patterns": []}


def save_memory(data: dict[str, Any]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir=str(APP_DIR),
        prefix="memory_",
        suffix=".tmp",
    ) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        tmp_path = Path(handle.name)
    tmp_path.replace(MEMORY_FILE)


class SessionMemory:
    """Tracks state for the active coding session (RAM only)."""

    def __init__(self):
        self.events: list[str] = []
        self.generated_files: list[str] = []
        self.active_target: str = ""

    def add_event(self, event: str):
        self.events.append(event.strip())
        self.events = self.events[-15:]

    def record_generated_file(self, path: str):
        if path not in self.generated_files:
            self.generated_files.append(path)

    def set_active_target(self, path: str):
        self.active_target = path.replace("\\", "/")

    def context(self, limit: int = 800) -> str:
        parts = []
        if self.active_target:
            parts.append(f"Active Target: {self.active_target}")
        if self.generated_files:
            parts.append("Files Created: " + ", ".join(self.generated_files))
        if self.events:
            parts.append("Recent History:\n" + "\n".join(self.events[-4:]))
        return "\n\n".join(parts)[-limit:]


class PersistentMemory:
    """Tracks state across multiple app launches."""

    def __init__(self):
        self.data = load_memory()

    def save(self):
        save_memory(self.data)

    def add_event(self, event: str):
        events = self.data.setdefault("events", [])
        events.append(event[:800])          # trim per-event to save disk
        self.data["events"] = events[-60:]  # keep last 60 (down from 80)
        self.save()

    def remember_fact(self, fact: str):
        facts = self.data.setdefault("facts", [])
        if fact not in facts:
            facts.append(fact[:400])
            self.save()

    def forget_all(self):
        self.data = {"events": [], "projects": {}, "facts": [], "strategies": [], "learned_patterns": []}
        self.save()

    def record_strategy(self, pattern: str, success_rate: float) -> None:
        """Record a successful strategy for future reference."""
        strategies = self.data.setdefault("strategies", [])
        existing = next((s for s in strategies if s.get("pattern") == pattern), None)
        if existing:
            existing["uses"] = existing.get("uses", 1) + 1
            existing["last_used"] = time.time()
            existing["success_rate"] = success_rate
        else:
            strategies.append(
                {
                    "pattern": pattern[:200],
                    "uses": 1,
                    "success_rate": success_rate,
                    "created_at": time.time(),
                    "last_used": time.time(),
                }
            )
        self.data["strategies"] = strategies[-50:]  # keep last 50
        self.save()

    def record_learned_pattern(self, pattern: str, category: str) -> None:
        """Record a learned pattern (naming convention, code style, etc.)."""
        patterns = self.data.setdefault("learned_patterns", [])
        if pattern not in [p.get("pattern") for p in patterns]:
            patterns.append(
                {"pattern": pattern[:300], "category": category, "learned_at": time.time()}
            )
        self.data["learned_patterns"] = patterns[-30:]  # keep last 30
        self.save()

    def get_relevant_strategies(self, task_type: str, limit: int = 5) -> list[str]:
        """Get successful strategies relevant to this task type."""
        strategies = self.data.get("strategies", [])
        relevant = [s for s in strategies if task_type.lower() in s.get("pattern", "").lower()]
        relevant.sort(key=lambda s: s.get("success_rate", 0), reverse=True)
        return [s.get("pattern", "") for s in relevant[:limit]]

    def get_learned_patterns(self, category: str | None = None, limit: int = 5) -> list[str]:
        """Get learned patterns (naming, structure, etc.)."""
        patterns = self.data.get("learned_patterns", [])
        if category:
            patterns = [p for p in patterns if p.get("category") == category]
        return [p.get("pattern", "") for p in patterns[-limit:]]

    def context_for(self, text: str, limit: int = 1200) -> str:
        facts = self.data.get("facts", [])
        patterns = self.data.get("learned_patterns", [])
        ctx_parts = []
        if facts:
            ctx_parts.append("Remembered facts:\n" + "\n".join(facts[-5:]))
        if patterns:
            ctx_parts.append("Learned Patterns:\n" + "\n".join([p.get("pattern", "") for p in patterns[-3:]]))
            
        return "\n\n".join(ctx_parts)[-limit:]

    def display(self) -> str:
        """Human-readable summary for the Memory tab."""
        facts = self.data.get("facts", [])
        events = self.data.get("events", [])
        strategies = self.data.get("strategies", [])
        patterns = self.data.get("learned_patterns", [])

        lines = []
        lines.append(f"━━ Facts ({len(facts)}) ━━")
        for f in facts[-20:]:
            lines.append(f"  • {f}")

        if strategies:
            lines.append(f"\n━━ Strategies ({len(strategies)}) ━━")
            for s in strategies[-10:]:
                uses = s.get("uses", 0)
                sr = s.get("success_rate", 0)
                lines.append(f"  • {s.get('pattern', '')[:80]} ({uses} uses, {sr:.0%} success)")

        if patterns:
            lines.append(f"\n━━ Learned Patterns ({len(patterns)}) ━━")
            for p in patterns[-10:]:
                lines.append(f"  • [{p.get('category', 'other')}] {p.get('pattern', '')[:80]}")

        lines.append(f"\n━━ Events ({len(events)}) ━━")
        for e in events[-30:]:
            lines.append(f"  {e[:120]}")

        return "\n".join(lines) if lines else "(empty)"
