"""
tool_reliability.py – Tool calling reliability pipeline.

Provides loop detection, tool disabling, recovery suggestions, and schema
validation to ensure robust tool calling in the agent loop.
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .logger import get_logger
from .schemas import ToolSchema, TOOL_SCHEMAS, ParamSchema

logger = get_logger("tool_reliability")


# ---------------------------------------------------------------------------
# LoopDetector
# ---------------------------------------------------------------------------

class LoopDetector:
    """Sliding window loop detection for the agent loop.

    Tracks the last WINDOW_SIZE tool calls and detects when the same
    (tool, params) tuple appears LOOP_THRESHOLD or more times within
    the window.
    """

    WINDOW_SIZE = 10
    LOOP_THRESHOLD = 3

    def __init__(self) -> None:
        self._window: deque[str] = deque(maxlen=self.WINDOW_SIZE)

    def record(self, tool: str, params: dict) -> None:
        """Record a tool call into the sliding window."""
        # Create a canonical key from tool name and sorted params
        key = self._make_key(tool, params)
        self._window.append(key)

    def is_looping(self) -> tuple[bool, str | None]:
        """Check if any (tool, params) tuple appears >= LOOP_THRESHOLD times.

        Returns:
            (is_looping, repeated_tool_name or None)
        """
        if len(self._window) < self.LOOP_THRESHOLD:
            return False, None

        # Count occurrences of each key in the window
        counts: dict[str, int] = {}
        for key in self._window:
            counts[key] = counts.get(key, 0) + 1

        for key, count in counts.items():
            if count >= self.LOOP_THRESHOLD:
                # Extract tool name from the key
                tool_name = key.split("|", 1)[0]
                return True, tool_name

        return False, None

    def reset(self) -> None:
        """Clear the sliding window."""
        self._window.clear()

    @staticmethod
    def _make_key(tool: str, params: dict) -> str:
        """Create a canonical string key from tool name and params."""
        # Sort params for consistent hashing regardless of dict order
        try:
            params_str = json.dumps(params, sort_keys=True, default=str)
        except (TypeError, ValueError):
            params_str = str(sorted(params.items()))
        return f"{tool}|{params_str}"


# ---------------------------------------------------------------------------
# ToolDisabler
# ---------------------------------------------------------------------------

@dataclass
class ToolRecord:
    """Tracks per-tool failure state."""
    tool: str
    consecutive_failures: int = 0
    disabled: bool = False
    disabled_at: int = 0  # monotonic counter for LRU ordering


class ToolDisabler:
    """Manages per-session tool enable/disable based on failure counts.

    A tool is disabled after MAX_CONSECUTIVE_FAILURES consecutive failures.
    It can be re-enabled when the model explicitly calls it with valid params.
    If all tools in a required category become disabled, the least-recently-
    disabled tool in that category is re-enabled as a last resort.
    """

    MAX_CONSECUTIVE_FAILURES = 3

    # Required tool categories — at least one tool must remain enabled in each
    REQUIRED_CATEGORIES: dict[str, list[str]] = {
        "filesystem": [
            "read_files", "write_files", "list_dir", "search_files",
            "delete_path", "move_path", "copy_path", "make_dir",
            "batch_read_files",
        ],
        "execution": [
            "run_cmd", "python_execute", "javascript_execute",
        ],
        "output": [
            "answer",
        ],
    }

    def __init__(self) -> None:
        self._records: dict[str, ToolRecord] = {}
        self._disable_counter: int = 0  # monotonic counter for LRU

    def record_failure(self, tool: str) -> None:
        """Record a tool failure. Disables tool after MAX_CONSECUTIVE_FAILURES."""
        record = self._get_or_create(tool)
        record.consecutive_failures += 1

        if record.consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES and not record.disabled:
            record.disabled = True
            self._disable_counter += 1
            record.disabled_at = self._disable_counter
            logger.warn(
                f"Tool '{tool}' disabled after {self.MAX_CONSECUTIVE_FAILURES} consecutive failures",
                operation="tool_disable",
            )
            # Check required category protection
            self._check_category_protection()

    def record_success(self, tool: str) -> None:
        """Record a tool success. Resets consecutive failure count."""
        record = self._get_or_create(tool)
        record.consecutive_failures = 0
        # Re-enable if it was disabled (explicit valid call re-enables)
        if record.disabled:
            record.disabled = False
            logger.info(
                f"Tool '{tool}' re-enabled after successful call",
                operation="tool_reenable",
            )

    def re_enable_tool(self, tool: str) -> None:
        """Explicitly re-enable a tool for one execution attempt."""
        record = self._get_or_create(tool)
        if record.disabled:
            record.disabled = False
            record.consecutive_failures = 0
            logger.info(
                f"Tool '{tool}' re-enabled explicitly",
                operation="tool_reenable",
            )

    def get_disabled_tools(self) -> set[str]:
        """Return the set of currently disabled tool names."""
        return {name for name, rec in self._records.items() if rec.disabled}

    def is_disabled(self, tool: str) -> bool:
        """Check if a specific tool is disabled."""
        record = self._records.get(tool)
        return record.disabled if record else False

    def get_available_tools(self, base_tools: list[str]) -> list[str]:
        """Filter base_tools to exclude disabled tools."""
        disabled = self.get_disabled_tools()
        return [t for t in base_tools if t not in disabled]

    def _get_or_create(self, tool: str) -> ToolRecord:
        """Get or create a ToolRecord for the given tool name."""
        if tool not in self._records:
            self._records[tool] = ToolRecord(tool=tool)
        return self._records[tool]

    def _check_category_protection(self) -> None:
        """If all tools in a required category are disabled, re-enable the LRU one."""
        for category, tools in self.REQUIRED_CATEGORIES.items():
            # Check if ALL tools in this category are disabled
            category_records = [
                self._records[t] for t in tools if t in self._records
            ]
            # Only check if we have records for tools in this category
            if not category_records:
                continue

            all_disabled = all(rec.disabled for rec in category_records)
            # Also check tools that don't have records yet (they're not disabled)
            tools_without_records = [t for t in tools if t not in self._records]
            if tools_without_records:
                # Some tools have never been called, so they're not disabled
                continue

            if all_disabled:
                # Re-enable the least-recently-disabled tool (lowest disabled_at)
                lru_record = min(category_records, key=lambda r: r.disabled_at)
                lru_record.disabled = False
                lru_record.consecutive_failures = 0
                logger.warn(
                    f"All tools in '{category}' category were disabled. "
                    f"Re-enabled '{lru_record.tool}' as last resort.",
                    operation="category_protection",
                )


# ---------------------------------------------------------------------------
# RecoverySuggester
# ---------------------------------------------------------------------------

class RecoverySuggester:
    """Maps error categories to concrete recovery actions.

    Provides actionable suggestions when tool execution fails, helping
    the model recover from common error patterns.
    """

    ERROR_MAP: dict[str, str] = {
        "file-not-found": "List the parent directory to verify the path exists",
        "permission-denied": "Verify the path or try with elevated access",
        "timeout": "Reduce scope or increase timeout",
        "invalid-input": "Re-read the tool schema for correct parameters",
        "not-found": "List the parent directory to verify the path exists",
        "syntax-error": "Check the code for syntax errors before execution",
        "connection-error": "Check if the server is running and accessible",
        "batch-limit": "Reduce the number of items in the batch operation",
    }

    # Patterns to classify errors into categories
    _ERROR_PATTERNS: list[tuple[str, list[str]]] = [
        ("file-not-found", [
            "no such file", "file not found", "not found", "does not exist",
            "FileNotFoundError", "ENOENT",
        ]),
        ("permission-denied", [
            "permission denied", "access denied", "PermissionError",
            "EACCES", "EPERM",
        ]),
        ("timeout", [
            "timeout", "timed out", "TimeoutError", "deadline exceeded",
        ]),
        ("invalid-input", [
            "invalid", "missing required", "type error", "TypeError",
            "ValueError", "validation failed",
        ]),
        ("syntax-error", [
            "SyntaxError", "syntax error", "unexpected token",
        ]),
        ("connection-error", [
            "connection refused", "ConnectionError", "ECONNREFUSED",
            "network unreachable",
        ]),
        ("batch-limit", [
            "batch size", "too many", "limit exceeded", "maximum",
        ]),
    ]

    def suggest(self, error: Exception | str, tool: str) -> str:
        """Provide a recovery suggestion based on the error and tool.

        Args:
            error: The exception or error message string.
            tool: The tool name that failed.

        Returns:
            A concrete suggestion string for recovery.
        """
        error_str = str(error).lower()
        category = self._classify_error(error_str)

        suggestion = self.ERROR_MAP.get(category, "")
        if not suggestion:
            # Fallback generic suggestion
            suggestion = (
                f"Review the error message and try a different approach. "
                f"Consider using 'list_dir' to verify paths or 're-read the tool schema'."
            )

        return f"[Recovery for '{tool}'] {suggestion}"

    def suggest_by_category(self, category: str, tool: str) -> str:
        """Get suggestion for a known error category.

        Args:
            category: One of the keys in ERROR_MAP.
            tool: The tool name that failed.

        Returns:
            A concrete suggestion string.
        """
        suggestion = self.ERROR_MAP.get(category, "Try a different approach")
        return f"[Recovery for '{tool}'] {suggestion}"

    def _classify_error(self, error_str: str) -> str:
        """Classify an error string into a known category."""
        for category, patterns in self._ERROR_PATTERNS:
            for pattern in patterns:
                if pattern.lower() in error_str:
                    return category
        return "unknown"


# ---------------------------------------------------------------------------
# SchemaValidator
# ---------------------------------------------------------------------------

@dataclass
class ValidationError:
    """Structured validation error for a single parameter."""
    param_name: str
    issue: str  # "missing" or "wrong_type"
    expected_type: str
    actual_type: str | None = None


@dataclass
class ValidationResult:
    """Result of schema validation with structured error details."""
    valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    tool_name: str = ""
    usage_example: str = ""

    @property
    def error_message(self) -> str:
        """Format errors into a human-readable message."""
        if self.valid:
            return ""

        lines = [f"Schema validation failed for tool '{self.tool_name}':"]
        for err in self.errors:
            if err.issue == "missing":
                lines.append(f"  - Missing required parameter '{err.param_name}' (expected: {err.expected_type})")
            elif err.issue == "wrong_type":
                lines.append(
                    f"  - Parameter '{err.param_name}' has wrong type: "
                    f"got {err.actual_type}, expected {err.expected_type}"
                )

        if self.usage_example:
            lines.append(f"\nUsage example:\n{self.usage_example}")

        return "\n".join(lines)


class SchemaValidator:
    """Validates tool actions against their schemas, producing structured errors.

    Unlike the basic ToolSchema.validate(), this produces detailed error
    information including all missing params, expected types, and a usage
    example for the tool.
    """

    def __init__(self, tool_schemas: dict[str, ToolSchema] | None = None) -> None:
        self._schemas = tool_schemas or TOOL_SCHEMAS

    def validate(self, action: dict[str, Any]) -> ValidationResult:
        """Validate an action dict against its tool schema.

        Args:
            action: The action dict with at minimum an "action" key.

        Returns:
            ValidationResult with structured error details.
        """
        tool_name = str(action.get("action", "")).strip()

        if not tool_name:
            return ValidationResult(
                valid=False,
                errors=[ValidationError(
                    param_name="action",
                    issue="missing",
                    expected_type="string (tool name)",
                )],
                tool_name="(unknown)",
                usage_example='{"action": "tool_name", "param1": "value1"}',
            )

        schema = self._schemas.get(tool_name)
        if not schema:
            return ValidationResult(
                valid=False,
                errors=[ValidationError(
                    param_name="action",
                    issue="wrong_type",
                    expected_type=f"one of: {', '.join(sorted(self._schemas.keys()))}",
                    actual_type=f"'{tool_name}' (not a registered tool)",
                )],
                tool_name=tool_name,
                usage_example=self._generate_example(tool_name),
            )

        # Validate all parameters
        errors: list[ValidationError] = []
        for param in schema.params:
            value = action.get(param.name)

            if value is None:
                if param.required:
                    errors.append(ValidationError(
                        param_name=param.name,
                        issue="missing",
                        expected_type=param.type,
                    ))
                continue

            # Type check
            if not self._check_type(value, param.type):
                errors.append(ValidationError(
                    param_name=param.name,
                    issue="wrong_type",
                    expected_type=param.type,
                    actual_type=type(value).__name__,
                ))

        if errors:
            return ValidationResult(
                valid=False,
                errors=errors,
                tool_name=tool_name,
                usage_example=self._generate_usage_example(schema),
            )

        return ValidationResult(valid=True, tool_name=tool_name)

    def _check_type(self, value: Any, expected: str) -> bool:
        """Check if a value matches the expected type string."""
        type_map: dict[str, type | tuple[type, ...]] = {
            "string": str,
            "int": int,
            "bool": bool,
            "number": (int, float),
            "list": list,
            "dict": dict,
        }
        expected_class = type_map.get(expected)
        if expected_class is None:
            return True  # Unknown type, pass through
        return isinstance(value, expected_class)

    def _generate_usage_example(self, schema: ToolSchema) -> str:
        """Generate a usage example JSON string for a tool schema."""
        example: dict[str, Any] = {"action": schema.name}

        for param in schema.params:
            if not param.required:
                continue
            example[param.name] = self._example_value(param)

        try:
            return json.dumps(example, indent=2)
        except (TypeError, ValueError):
            return json.dumps({"action": schema.name})

    def _generate_example(self, tool_name: str) -> str:
        """Generate a generic example when tool is not found."""
        available = sorted(self._schemas.keys())[:5]
        return (
            f'Available tools include: {", ".join(available)}...\n'
            f'Example: {{"action": "{available[0]}", ...}}'
        )

    @staticmethod
    def _example_value(param: ParamSchema) -> Any:
        """Generate an example value for a parameter based on its type."""
        examples: dict[str, Any] = {
            "string": f"<{param.name}>",
            "int": 1,
            "bool": True,
            "number": 1.0,
            "list": [f"<{param.name}_item>"],
            "dict": {f"<key>": f"<value>"},
        }
        return examples.get(param.type, f"<{param.name}>")
