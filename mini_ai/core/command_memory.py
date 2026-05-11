"""
command_memory.py – RAG-based command pattern persistence for Mini AI.
Stores and retrieves successful command patterns to help the agent learn from past executions.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .config import Config
from .logger import get_logger

logger = get_logger("command_memory")


@dataclass
class CommandPattern:
    """A recorded command execution pattern."""
    command: str
    cwd: str
    exit_code: int
    success: bool
    timestamp: float = field(default_factory=time.time)
    context: dict[str, Any] = field(default_factory=dict)
    file_patterns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "success": self.success,
            "timestamp": self.timestamp,
            "context": self.context,
            "file_patterns": self.file_patterns,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CommandPattern":
        return cls(
            command=data.get("command", ""),
            cwd=data.get("cwd", ""),
            exit_code=data.get("exit_code", -1),
            success=data.get("success", False),
            timestamp=data.get("timestamp", 0),
            context=data.get("context", {}),
            file_patterns=data.get("file_patterns", []),
        )


class CommandMemory:
    """
    Persistent memory for command patterns using RAG-style retrieval.
    Helps the agent remember what commands worked in similar contexts.
    """

    def __init__(self, config: Config, storage_path: Optional[Path] = None):
        self.config = config
        self.storage_path = storage_path or self._default_storage_path()
        self.patterns: list[CommandPattern] = []
        self._load()

    def _default_storage_path(self) -> Path:
        """Default location for command memory storage."""
        # Store in workspace or home directory
        workspace = getattr(self.config, 'workspace', None)
        if workspace:
            base = Path(workspace) / ".mini_ai"
        else:
            base = Path.home() / ".mini_ai"
        base.mkdir(parents=True, exist_ok=True)
        return base / "command_memory.json"

    def _load(self) -> None:
        """Load stored patterns from disk."""
        if not self.storage_path.exists():
            logger.info(f"No command memory found at {self.storage_path}")
            return

        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            self.patterns = [CommandPattern.from_dict(p) for p in data.get("patterns", [])]
            logger.info(f"Loaded {len(self.patterns)} command patterns from memory")
        except Exception as e:
            logger.warning(f"Failed to load command memory: {e}")
            self.patterns = []

    def _save(self) -> None:
        """Save patterns to disk."""
        try:
            data = {
                "version": 1,
                "last_updated": time.time(),
                "patterns": [p.to_dict() for p in self.patterns],
            }
            self.storage_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to save command memory: {e}")

    def record(self, command: str, cwd: str, exit_code: int, context: Optional[dict] = None) -> None:
        """
        Record a command execution for future retrieval.

        Args:
            command: The command that was executed
            cwd: Working directory where command ran
            exit_code: Command exit code (0 = success)
            context: Additional context (files modified, etc.)
        """
        # Extract file patterns from context
        file_patterns = []
        if context:
            files = context.get("files", [])
            file_patterns = [self._extract_pattern(f) for f in files]

        pattern = CommandPattern(
            command=command,
            cwd=cwd,
            exit_code=exit_code,
            success=(exit_code == 0),
            context=context or {},
            file_patterns=file_patterns,
        )

        # Don't store duplicates (same command in same directory)
        for i, existing in enumerate(self.patterns):
            if existing.command == command and existing.cwd == cwd:
                # Update with latest result
                self.patterns[i] = pattern
                logger.debug(f"Updated existing command pattern: {command[:50]}")
                self._save()
                return

        self.patterns.append(pattern)
        logger.info(f"Recorded new command pattern: {command[:50]} (exit={exit_code})")

        # Limit memory size (keep last 100 successful patterns, 50 failed)
        self._prune_old_patterns()
        self._save()

    def _extract_pattern(self, filepath: str) -> str:
        """Extract a pattern from a filepath (e.g., '*.py', 'test_*')."""
        path = Path(filepath)
        # Return extension pattern
        if path.suffix:
            return f"*{path.suffix}"
        return path.name

    def _prune_old_patterns(self) -> None:
        """Keep memory size manageable by removing old patterns."""
        successful = [p for p in self.patterns if p.success]
        failed = [p for p in self.patterns if not p.success]

        # Sort by timestamp (newest first)
        successful.sort(key=lambda p: p.timestamp, reverse=True)
        failed.sort(key=lambda p: p.timestamp, reverse=True)

        # Keep most recent
        to_keep = successful[:100] + failed[:50]
        self.patterns = to_keep

    def retrieve_relevant(self, query: str, cwd: str, limit: int = 3) -> list[CommandPattern]:
        """
        Retrieve relevant command patterns based on query and current directory.

        Args:
            query: The current task/goal description
            cwd: Current working directory
            limit: Maximum number of patterns to return

        Returns:
            List of relevant command patterns, sorted by relevance
        """
        if not self.patterns:
            return []

        scored = []
        query_lower = query.lower()

        for pattern in self.patterns:
            score = 0.0

            # Score based on command similarity to query
            cmd_lower = pattern.command.lower()
            if any(word in cmd_lower for word in query_lower.split()):
                score += 0.3

            # Score based on directory match
            if pattern.cwd == cwd:
                score += 0.4  # Same directory is highly relevant
            elif cwd.startswith(pattern.cwd):
                score += 0.2  # Subdirectory

            # Prefer successful commands
            if pattern.success:
                score += 0.2

            # Prefer recent commands
            age_hours = (time.time() - pattern.timestamp) / 3600
            if age_hours < 24:
                score += 0.1  # Commands from last 24 hours

            scored.append((score, pattern))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Return top patterns above threshold
        relevant = [p for s, p in scored if s > 0.3][:limit]
        logger.debug(f"Retrieved {len(relevant)} relevant command patterns for query")
        return relevant

    def format_hints(self, patterns: list[CommandPattern]) -> str:
        """Format command patterns as hints for the AI prompt."""
        if not patterns:
            return ""

        lines = ["### Previously Successful Commands in Similar Contexts:", ""]

        for i, p in enumerate(patterns[:3], 1):
            status = "✓" if p.success else "✗"
            lines.append(f"{i}. {status} `{p.command}`")
            lines.append(f"   CWD: {p.cwd}")
            if p.context.get("files"):
                files_str = ", ".join(p.context["files"][:3])
                if len(p.context["files"]) > 3:
                    files_str += f" (+{len(p.context['files']) - 3} more)"
                lines.append(f"   Files: {files_str}")
            lines.append("")

        return "\n".join(lines)

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about command memory."""
        successful = len([p for p in self.patterns if p.success])
        failed = len([p for p in self.patterns if not p.success])
        return {
            "total": len(self.patterns),
            "successful": successful,
            "failed": failed,
            "storage_path": str(self.storage_path),
        }
