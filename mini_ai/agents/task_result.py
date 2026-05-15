"""
task_result.py – Structured result object for agent task execution.

Provides a TaskResult dataclass that replaces raw string returns from
agent_mode(), enabling the orchestrator to determine success/failure
via a structured boolean field instead of heuristic string matching.

Requirements: 3.4, 3.5
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TaskResult:
    """Structured result from agent_mode() execution.

    Attributes:
        success: Whether the task completed successfully.
        output: The textual output/answer from the agent.
        tool_name: The last tool that produced the final result (if any).
        exit_code: Exit code from command execution (if applicable).
    """
    success: bool
    output: str
    tool_name: Optional[str] = None
    exit_code: Optional[int] = None

    def to_json(self) -> str:
        """Serialize to JSON string for structured communication."""
        return json.dumps({
            "success": self.success,
            "output": self.output,
            "tool_name": self.tool_name,
            "exit_code": self.exit_code,
        })

    @classmethod
    def from_json(cls, raw: str) -> "TaskResult":
        """Parse a JSON string into a TaskResult.

        If parsing fails or "success" field is missing, treats as failure
        with the raw string as output.
        """
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or "success" not in data:
                return cls(success=False, output=raw)
            return cls(
                success=bool(data["success"]),
                output=str(data.get("output", "")),
                tool_name=data.get("tool_name"),
                exit_code=data.get("exit_code"),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            return cls(success=False, output=raw)

    def __str__(self) -> str:
        """String representation returns the JSON form."""
        return self.to_json()
