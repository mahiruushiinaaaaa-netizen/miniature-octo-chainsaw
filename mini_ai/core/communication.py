"""
communication.py – Utilities for optimizing AI-System communication.
Focuses on intelligent feedback, concise prompts, and tool discovery.
"""
from __future__ import annotations
import json
import re
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .schemas import ToolSchema

def format_tool_for_ai(schema: ToolSchema) -> str:
    """Format a tool schema into a concise JSON example for the system prompt."""
    params = {}
    for p in schema.params:
        if p.type == "string":
            val = f"<{p.name}>"
        elif p.type == "list":
            val = [f"<{p.name}_item>"]
        elif p.type == "dict":
            val = {"key": "value"}
        elif p.type == "int":
            val = 0
        elif p.type == "bool":
            val = False
        else:
            val = None
        params[p.name] = val
    
    example = {"plan": "Reason for action", "action": schema.name, **params}
    return json.dumps(example)

def get_intelligent_hint(tool: str, output: str, success: bool, exit_code: int | None = None) -> str | None:
    """Provide specific, actionable hints based on common failure patterns."""
    if success:
        return None
    
    out_low = output.lower()
    
    if tool == "run_cmd":
        if exit_code == 127 or "not recognized" in out_low or "command not found" in out_low:
             cmd = output.split("'")[1] if "'" in output else "command"
             if "touch" in out_low:
                 return "HINT: 'touch' is not native on Windows. Use 'type nul > file' instead."
             return f"HINT: Binary '{cmd}' not found. Check environment or install it."
        
        if "syntax of the command is incorrect" in out_low:
             if "-p" in out_low:
                 return "HINT: 'mkdir -p' is not supported on Windows. Use 'mkdir' without '-p' (it creates parent dirs by default on Windows)."
             if '"' not in output:
                 return "HINT: Possible quoting error. On Windows, ALWAYS use DOUBLE QUOTES for paths with spaces."
        
        if "already exists" in out_low and "mkdir" in out_low:
             if '"' not in output:
                 return "HINT: 'already exists' often means you missed double quotes around a path with spaces. Windows is splitting the path into multiple arguments."
        
        if "permission denied" in out_low:
             return "HINT: Permission denied. Try a different directory or check file attributes."
             
        if "no such file or directory" in out_low:
             return "HINT: Path does not exist. Use 'list_dir' or 'workspace_map' to verify paths."
        
        if "too many arguments to \"create-project\"" in out_low:
             return "HINT: Use 'composer create-project laravel/laravel <dir>' then install dependencies separately."


    if tool == "edit_blocks":
        if "Failed to match SEARCH block" in output:
             return "HINT: The SEARCH block MUST match the file content EXACTLY, including indentation and newlines."

    if tool == "read_files":
        if "not found" in out_low:
             return "HINT: File not found. Double check the path relative to the workspace root."

    return None

def compact_observation(tool: str, output: str, success: bool, limit: int = 2000) -> str:
    """Compact and structure the observation for the AI."""
    status = "SUCCESS" if success else "FAILED"
    
    # Extract only the most relevant part of large outputs
    if len(output) > limit:
        # If it's a log, keep the end
        if any(x in tool for x in ("run_cmd", "web_search", "read_url")):
            output = output[:limit//4] + "\n... [intermediate output truncated] ...\n" + output[-limit//2:]
        elif any(x in tool for x in ("list_dir", "workspace_map", "workspace_index")):
            # For lists, keep the first 30 lines
            lines = output.split("\n")
            if len(lines) > 30:
                output = "\n".join(lines[:30]) + f"\n... [truncated, {len(lines)-30} more items hidden]"
            else:
                output = output[:limit] + "\n... [truncated]"
        else:
            output = output[:limit] + "\n... [truncated]"
            
    res = f"TOOL: {tool} | STATUS: {status}\nOUTPUT: {output}"
    return res.strip()


# ---------------------------------------------------------------------------
# Observation Compressor (Task 5.5 – Requirements 12.1–12.6)
# ---------------------------------------------------------------------------

class ObservationCompressor:
    """Intelligent compression of tool outputs for context efficiency.

    Thresholds:
        - Outputs > COMPRESS_THRESHOLD chars are compressed to ≤ MAX_COMPRESSED chars.
        - Outputs ≤ COMPRESS_THRESHOLD chars pass through in template format.
        - run_cmd outputs > CMD_TRUNCATE_THRESHOLD use head/tail preservation.
    """

    COMPRESS_THRESHOLD = 1000   # Req 12.6: pass-through below this
    MAX_COMPRESSED = 500        # Req 12.1: compressed ceiling
    CMD_TRUNCATE_THRESHOLD = 2000  # Req 12.3: special run_cmd threshold
    CMD_KEEP_HEAD = 200         # Req 12.3: first N chars kept
    CMD_KEEP_TAIL = 500         # Req 12.3: last N chars kept

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def compress(self, tool: str, output: str, success: bool) -> str:
        """Compress a single tool observation based on tool type and size.

        Returns the observation in structured template format.
        For outputs ≤ 1000 chars the content is unmodified (Req 12.6).
        For outputs > 1000 chars the content is compressed to ≤ 500 chars (Req 12.1).
        """
        status = "success" if success else "fail"

        # Req 12.6: pass through unmodified for small outputs
        if len(output) <= self.COMPRESS_THRESHOLD:
            return self._template(tool, status, output)

        # Req 12.3: run_cmd special handling for very large outputs
        if tool == "run_cmd" and len(output) > self.CMD_TRUNCATE_THRESHOLD:
            compressed = self._truncate_cmd(output)
            return self._template(tool, status, compressed)

        # Req 12.1: generic compression to ≤ 500 chars
        compressed = self._extract_key_info(tool, output, success)
        return self._template(tool, status, compressed)

    def deduplicate(self, observations: list[str]) -> list[str]:
        """Replace consecutive identical observations with repetition count.

        Req 12.4: exact character match detection.
        """
        if not observations:
            return []

        result: list[str] = []
        i = 0
        while i < len(observations):
            current = observations[i]
            count = 1
            while i + count < len(observations) and observations[i + count] == current:
                count += 1
            if count > 1:
                result.append(f"{current}\n[repeated {count} times]")
            else:
                result.append(current)
            i += count
        return result

    def summarize_old(
        self,
        observations: list[str],
        budget_chars: int,
    ) -> str:
        """Summarize observations older than 3 turns when history exceeds budget.

        Req 12.5: triggers when total history > 60% of context budget.
        Observations older than 3 turns are collapsed into a progress summary
        of no more than 200 characters.

        Args:
            observations: Full list of observations (oldest first).
            budget_chars: Total context budget in characters.

        Returns:
            Combined string of summarized old + recent observations.
        """
        total_chars = sum(len(o) for o in observations)
        threshold = int(budget_chars * 0.6)

        # If under 60% of budget, return as-is joined
        if total_chars <= threshold:
            return "\n".join(observations)

        # Keep the 3 most recent observations intact
        if len(observations) <= 3:
            return "\n".join(observations)

        old_observations = observations[:-3]
        recent_observations = observations[-3:]

        # Summarize old observations into a progress line (max 200 chars)
        summary = self._build_progress_summary(old_observations)

        parts = [summary] + recent_observations
        return "\n".join(parts)

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _template(self, tool: str, status: str, content: str) -> str:
        """Format using the structured template (Req 12.2)."""
        return f"[{tool.upper()}] STATUS: {status} | KEY_INFO: {content}"

    def _truncate_cmd(self, output: str) -> str:
        """Truncate run_cmd output keeping head and tail (Req 12.3).

        Keeps first CMD_KEEP_HEAD chars + last CMD_KEEP_TAIL chars with
        a truncation indicator showing how many characters were omitted.
        """
        head = output[: self.CMD_KEEP_HEAD]
        tail = output[-self.CMD_KEEP_TAIL :]
        truncated_count = len(output) - self.CMD_KEEP_HEAD - self.CMD_KEEP_TAIL
        return f"{head}... [{truncated_count} characters truncated] ...{tail}"

    def _extract_key_info(self, tool: str, output: str, success: bool) -> str:
        """Extract the most relevant information from a large output.

        Strategies:
        - Error messages (lines containing 'error', 'fail', 'exception')
        - File paths and line numbers
        - First meaningful line + last meaningful line
        - Truncate to MAX_COMPRESSED chars
        """
        lines = output.split("\n")
        key_lines: list[str] = []

        # Collect error/important lines
        error_patterns = re.compile(
            r"(error|fail|exception|traceback|warning|not found|denied)",
            re.IGNORECASE,
        )
        path_pattern = re.compile(r"[A-Za-z]?:?[\\/][\w\\/.\-]+|line \d+", re.IGNORECASE)

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if error_patterns.search(stripped):
                key_lines.append(stripped)
            elif path_pattern.search(stripped) and len(key_lines) < 8:
                key_lines.append(stripped)

        # If we found key lines, use them
        if key_lines:
            extracted = " | ".join(key_lines)
        else:
            # Fallback: first line + last line
            non_empty = [l.strip() for l in lines if l.strip()]
            if len(non_empty) >= 2:
                extracted = f"{non_empty[0]} ... {non_empty[-1]}"
            elif non_empty:
                extracted = non_empty[0]
            else:
                extracted = output[:self.MAX_COMPRESSED]

        # Enforce MAX_COMPRESSED limit
        if len(extracted) > self.MAX_COMPRESSED:
            extracted = extracted[: self.MAX_COMPRESSED - 3] + "..."

        return extracted

    def _build_progress_summary(self, old_observations: list[str]) -> str:
        """Build a single progress summary line from old observations (max 200 chars).

        Extracts tool names and success/fail status from each old observation.
        """
        summaries: list[str] = []
        tool_pattern = re.compile(r"\[(\w+)\]\s*STATUS:\s*(success|fail)", re.IGNORECASE)

        for obs in old_observations:
            match = tool_pattern.search(obs)
            if match:
                tool_name = match.group(1).lower()
                status = "ok" if match.group(2).lower() == "success" else "fail"
                summaries.append(f"{tool_name}:{status}")
            else:
                # Try to extract from legacy format
                if "STATUS:" in obs.upper():
                    # Grab first word-like token after [ or TOOL:
                    legacy = re.search(r"(?:TOOL:|^\[?)(\w+)", obs)
                    if legacy:
                        summaries.append(f"{legacy.group(1).lower()}:?")
                    else:
                        summaries.append("?:?")
                else:
                    summaries.append("?:?")

        summary = f"[PROGRESS] {', '.join(summaries)}"

        # Enforce 200 char limit
        if len(summary) > 200:
            summary = summary[:197] + "..."

        return summary


# ---------------------------------------------------------------------------
# Structured Communication Protocol (Requirement 6)
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)

SECTION_LABELS = ["[GOAL]", "[HISTORY]", "[CONTEXT]", "[TOOLS]", "[MEMORY]", "[REPO_MAP]"]
MANDATORY_SECTIONS = {"[GOAL]", "[TOOLS]"}


class StructuredPromptFormatter:
    """Formats prompt sections with labeled delimiters.

    Accepts a dict mapping section names (without brackets) to content strings.
    Produces a prompt where each non-empty section is wrapped with its label.
    Mandatory sections ([GOAL], [TOOLS]) are always included even if empty.

    Validates: Requirements 6.1
    """

    def format(self, sections: dict[str, str]) -> str:
        """Produce labeled prompt: [GOAL] ... [HISTORY] ... etc.

        Args:
            sections: Mapping of section name (e.g. "GOAL", "HISTORY") to content.

        Returns:
            Formatted prompt string with labeled delimiters.
        """
        parts: list[str] = []

        # Process in canonical order to ensure consistent output
        canonical_order = ["GOAL", "HISTORY", "CONTEXT", "TOOLS", "MEMORY", "REPO_MAP"]

        for name in canonical_order:
            label = f"[{name}]"
            content = sections.get(name, "")

            # Always include mandatory sections; skip empty non-mandatory ones
            if not content and label not in MANDATORY_SECTIONS:
                continue

            parts.append(f"{label}\n{content}")

        # Include any extra sections not in canonical order
        for name, content in sections.items():
            if name not in canonical_order and content:
                parts.append(f"[{name}]\n{content}")

        return "\n\n".join(parts)


class ResponseValidator:
    """Validates model JSON responses before passing to executor.

    Checks that the response is parseable JSON containing an "action" key
    whose value matches a registered tool name.

    Validates: Requirements 6.2, 6.3, 6.4, 6.5
    """

    # JSON schema expected from the model
    EXPECTED_SCHEMA = {
        "type": "object",
        "required": ["action"],
        "properties": {
            "plan": {"type": "string", "description": "Reasoning for the action"},
            "action": {"type": "string", "description": "Tool name to execute"},
        },
    }

    # Concrete example for nudge messages
    EXAMPLE_RESPONSE = json.dumps(
        {"plan": "Read the file to understand the code", "action": "read_files", "files": ["src/main.py"]},
        indent=2,
    )

    def __init__(self, registered_tools: list[str] | None = None):
        """Initialize with list of valid tool names.

        Args:
            registered_tools: List of valid tool names. If None, any non-empty
                action string is accepted.
        """
        self._registered_tools: set[str] = set(registered_tools) if registered_tools else set()
        self._consecutive_failures: int = 0

    @property
    def consecutive_failures(self) -> int:
        """Number of consecutive validation failures."""
        return self._consecutive_failures

    def validate(self, raw: str) -> tuple[bool, dict | None, str]:
        """Validate a raw model response string.

        Returns:
            Tuple of (valid, parsed_action_dict, error_message).
            If valid is True, parsed_action_dict contains the parsed JSON and
            error_message is empty. If valid is False, parsed_action_dict is None
            and error_message describes the issue.
        """
        # Try to parse JSON
        raw_stripped = raw.strip()
        parsed: dict | None = None

        try:
            parsed = json.loads(raw_stripped)
        except json.JSONDecodeError as e:
            self._consecutive_failures += 1
            return False, None, f"Invalid JSON: {e}"

        # Must be a dict
        if not isinstance(parsed, dict):
            self._consecutive_failures += 1
            return False, None, "Response must be a JSON object, not a list or primitive"

        # Must have "action" key
        action = parsed.get("action")
        if action is None:
            self._consecutive_failures += 1
            return False, None, 'Missing required "action" key in response'

        if not isinstance(action, str) or not action.strip():
            self._consecutive_failures += 1
            return False, None, '"action" must be a non-empty string'

        # Validate against registered tools if provided
        if self._registered_tools and action not in self._registered_tools:
            self._consecutive_failures += 1
            available = ", ".join(sorted(self._registered_tools))
            return False, None, (
                f'Unknown action "{action}". '
                f"Available tools: {available}"
            )

        # Valid response
        self._consecutive_failures = 0
        return True, parsed, ""

    def get_nudge_message(self) -> str:
        """Generate a nudge message with schema and example for invalid responses.

        Returns:
            A string containing the expected JSON schema and a concrete example.
        """
        schema_str = json.dumps(self.EXPECTED_SCHEMA, indent=2)
        tools_hint = ""
        if self._registered_tools:
            tools_hint = f"\nAvailable tools: {', '.join(sorted(self._registered_tools))}\n"

        return (
            "Your response must be valid JSON with an \"action\" key.\n"
            f"\nExpected schema:\n{schema_str}\n"
            f"{tools_hint}"
            f"\nExample of a valid response:\n{self.EXAMPLE_RESPONSE}\n"
            "\nPlease respond with valid JSON only."
        )

    def should_simplify_prompt(self) -> bool:
        """Check if we should remove non-mandatory sections (after 3 failures).

        Returns:
            True if 3 or more consecutive failures have occurred.
        """
        return self._consecutive_failures >= 3

    def should_abort(self) -> bool:
        """Check if we should abort (simplified retry also failed).

        After simplification (at failure 3), if the next attempt also fails
        (failure 4+), we should abort.

        Returns:
            True if we should abort the current action.
        """
        return self._consecutive_failures >= 4

    def get_error_result(self) -> dict:
        """Return an error indication for the caller when aborting.

        Returns:
            Dict with error information.
        """
        return {
            "error": True,
            "message": "Model failed to produce a valid response after retries",
            "consecutive_failures": self._consecutive_failures,
        }

    def reset(self) -> None:
        """Reset the consecutive failure counter."""
        self._consecutive_failures = 0


@dataclass
class ToolSuccessRecord:
    """Per-tool success tracking record."""
    tool: str
    total: int = 0
    successes: int = 0
    failures: int = 0

    @property
    def success_ratio(self) -> float:
        """Success-to-total ratio."""
        return self.successes / self.total if self.total > 0 else 0.0


class ToolSuccessTracker:
    """Tracks per-session tool success/failure for recommendations.

    Once a tool has been invoked at least `min_invocations` times, it becomes
    eligible for recommendation. Recommendations are the top-K tools ordered
    by success-to-total ratio.

    Validates: Requirements 6.6
    """

    def __init__(self):
        self._records: dict[str, ToolSuccessRecord] = {}

    def record(self, tool: str, success: bool) -> None:
        """Record a tool invocation result.

        Args:
            tool: The tool name.
            success: Whether the invocation succeeded.
        """
        if tool not in self._records:
            self._records[tool] = ToolSuccessRecord(tool=tool)

        record = self._records[tool]
        record.total += 1
        if success:
            record.successes += 1
        else:
            record.failures += 1

    def get_recommendations(self, min_invocations: int = 5, top_k: int = 3) -> list[str]:
        """Get recommended tools based on success ratio.

        Only tools with at least `min_invocations` total calls are eligible.
        Returns the top `top_k` tools ordered by success-to-total ratio
        (descending). Ties are broken by total invocations (more = better).

        Args:
            min_invocations: Minimum number of invocations to be eligible.
            top_k: Maximum number of recommendations to return.

        Returns:
            List of tool names ordered by success ratio (best first).
        """
        eligible = [
            r for r in self._records.values()
            if r.total >= min_invocations
        ]

        # Sort by success ratio descending, then by total invocations descending
        eligible.sort(key=lambda r: (r.success_ratio, r.total), reverse=True)

        return [r.tool for r in eligible[:top_k]]

    def get_record(self, tool: str) -> ToolSuccessRecord | None:
        """Get the record for a specific tool.

        Args:
            tool: The tool name.

        Returns:
            The ToolSuccessRecord or None if not tracked.
        """
        return self._records.get(tool)

    def get_all_records(self) -> dict[str, ToolSuccessRecord]:
        """Get all tracked records.

        Returns:
            Dict mapping tool name to its ToolSuccessRecord.
        """
        return dict(self._records)

    def reset(self) -> None:
        """Reset all tracking data (e.g., on new session)."""
        self._records.clear()

    def format_recommendations_hint(self, min_invocations: int = 5, top_k: int = 3) -> str:
        """Format recommendations as a hint string for the system prompt.

        Args:
            min_invocations: Minimum invocations threshold.
            top_k: Number of tools to recommend.

        Returns:
            A formatted string with recommended tools, or empty string if none.
        """
        recs = self.get_recommendations(min_invocations=min_invocations, top_k=top_k)
        if not recs:
            return ""

        tools_str = ", ".join(recs)
        return f"Recommended tools (highest success rate): {tools_str}"
