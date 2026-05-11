"""
self_healing.py – Self-healing JSON parser for small model tool calling.

Repairs common JSON errors produced by small LLMs (single quotes, unescaped
backslashes, trailing commas, misspelled tool names) and provides session-level
correction hints to reduce repeated errors.

Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from .schemas import ToolSchema, TOOL_SCHEMAS, describe_tool
from .logger import get_logger

logger = get_logger("self_healing")


def _levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(a) < len(b):
        return _levenshtein(b, a)
    if not b:
        return len(a)

    prev_row = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr_row = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr_row.append(min(
                curr_row[j] + 1,        # insert
                prev_row[j + 1] + 1,    # delete
                prev_row[j] + cost,     # substitute
            ))
        prev_row = curr_row

    return prev_row[-1]


class SelfHealingParser:
    """Repairs common JSON errors from small models.

    The repair pipeline applies fixes in order:
      1. Single quotes → double quotes
      2. Unescaped Windows backslashes → escaped
      3. Trailing commas → removed
      4. Re-parse (1 attempt)

    After parsing, tool name correction via Levenshtein distance is applied.
    Extra fields not in the tool schema are ignored during execution.
    """

    def __init__(self, tool_registry: dict[str, ToolSchema] | None = None):
        self._registry: dict[str, ToolSchema] = tool_registry or TOOL_SCHEMAS
        self._correction_log: Counter = Counter()

    def parse(self, raw: str) -> tuple[dict | None, list[str]]:
        """Parse JSON with repair pipeline.

        Returns:
            (parsed_action, corrections_applied) on success.
            (None, [error_message]) on failure.
        """
        corrections: list[str] = []

        # First, try parsing as-is
        action = self._try_parse(raw)
        if action is not None:
            # Even if it parsed, still try to fix tool name
            action, name_corrections = self._apply_tool_name_fix(action)
            corrections.extend(name_corrections)
            return action, corrections

        # Apply repair pipeline
        repaired = raw

        # Step 1: Fix single quotes
        fixed_quotes = self._fix_single_quotes(repaired)
        if fixed_quotes != repaired:
            corrections.append("single_quotes")
            self._correction_log["single_quotes"] += 1
            repaired = fixed_quotes

        # Step 2: Fix backslashes
        fixed_backslashes = self._fix_backslashes(repaired)
        if fixed_backslashes != repaired:
            corrections.append("backslash")
            self._correction_log["backslash"] += 1
            repaired = fixed_backslashes

        # Step 3: Fix trailing commas
        fixed_commas = self._fix_trailing_commas(repaired)
        if fixed_commas != repaired:
            corrections.append("trailing_comma")
            self._correction_log["trailing_comma"] += 1
            repaired = fixed_commas

        # Re-parse (1 attempt)
        action = self._try_parse(repaired)
        if action is not None:
            # Apply tool name fix
            action, name_corrections = self._apply_tool_name_fix(action)
            if action is None:
                # Tool name fix returned None (ambiguous match)
                return None, name_corrections
            corrections.extend(name_corrections)
            return action, corrections

        # Repair failed — return error with corrective example
        tool_name = self._extract_likely_tool_name(raw)
        example = self._build_corrective_example(tool_name)
        error_msg = (
            f"JSON parse failed after repair. {example}"
        )
        return None, [error_msg]

    def _try_parse(self, text: str) -> dict | None:
        """Attempt JSON parse, return dict or None."""
        try:
            # Strip leading/trailing whitespace and any think blocks
            cleaned = text.strip()
            # Remove <think>...</think> prefix if present
            think_match = re.match(r'<think>.*?</think>\s*', cleaned, re.DOTALL)
            if think_match:
                cleaned = cleaned[think_match.end():]

            result = json.loads(cleaned)
            if isinstance(result, dict):
                return result
            return None
        except (json.JSONDecodeError, ValueError):
            return None

    def _fix_single_quotes(self, text: str) -> str:
        """Replace single quotes with double quotes for JSON compatibility.

        Uses a simple heuristic: if the text has no double quotes but has
        single quotes in JSON-like structure, replace all single quotes.
        Otherwise use a character-by-character approach.
        """
        # Simple heuristic: if the text looks like it uses single quotes as
        # JSON delimiters (e.g., {'action': 'answer'}), replace them.
        if '"' not in text and "'" in text:
            # Entire JSON uses single quotes — safe to replace all
            return text.replace("'", '"')

        # Mixed quotes: character-by-character replacement of single quotes
        # that appear to be JSON delimiters (not inside double-quoted strings)
        result = []
        in_double_quote = False
        i = 0
        while i < len(text):
            ch = text[i]
            if ch == '\\' and in_double_quote and i + 1 < len(text):
                # Escaped character inside double-quoted string — keep as-is
                result.append(ch)
                result.append(text[i + 1])
                i += 2
                continue
            elif ch == '"' and not in_double_quote:
                in_double_quote = True
                result.append(ch)
            elif ch == '"' and in_double_quote:
                in_double_quote = False
                result.append(ch)
            elif ch == "'" and not in_double_quote:
                # Replace single quote with double quote when outside double-quoted strings
                result.append('"')
            else:
                result.append(ch)
            i += 1
        return "".join(result)

    def _fix_backslashes(self, text: str) -> str:
        """Escape unescaped Windows backslashes in JSON string values.

        Targets patterns like C:\\Users\\path that should be C:\\\\Users\\\\path
        in valid JSON.
        """
        # Match backslashes that are NOT already escaped (not preceded by another backslash)
        # and NOT part of valid JSON escape sequences (\", \\, \/, \b, \f, \n, \r, \t, \uXXXX)
        def _escape_in_strings(match: re.Match) -> str:
            content = match.group(1)
            # Escape lone backslashes that aren't already part of valid JSON escapes
            escaped = re.sub(
                r'\\(?!["\\/bfnrtu])',
                r'\\\\',
                content,
            )
            return f'"{escaped}"'

        # Find string values (between double quotes) and fix backslashes inside them
        # This handles the case where the JSON already has double quotes but bad backslashes
        result = re.sub(
            r'"((?:[^"\\]|\\.)*?(?:\\(?!["\\/bfnrtu])(?:[^"\\]|\\.)*?)+)"',
            _escape_in_strings,
            text,
        )

        # Also handle the case where single quotes were already replaced
        # but backslashes in paths like C:\Users\... remain unescaped
        if result == text:
            # Try a simpler approach: find path-like patterns and escape them
            result = re.sub(
                r'(?<=")((?:[A-Za-z]:)?(?:\\[^"\\,}\]\s]+)+)(?=")',
                lambda m: m.group(1).replace('\\', '\\\\'),
                text,
            )

        return result

    def _fix_trailing_commas(self, text: str) -> str:
        """Remove trailing commas before } or ] in JSON."""
        # Remove comma followed by optional whitespace and closing brace/bracket
        result = re.sub(r',\s*([}\]])', r'\1', text)
        return result

    def _fix_tool_name(self, name: str) -> str | None:
        """Correct a tool name using Levenshtein distance.

        Returns:
            Corrected name if exactly one match within distance ≤ 2.
            None if ambiguous (multiple matches) or no close match.
        """
        # Exact match — no correction needed
        if name in self._registry:
            return name

        candidates = []
        for valid_name in self._registry:
            dist = _levenshtein(name, valid_name)
            if dist <= 2:
                candidates.append((valid_name, dist))

        if len(candidates) == 1:
            return candidates[0][0]
        elif len(candidates) > 1:
            # Ambiguous — reject
            return None
        else:
            # No close match
            return None

    def _apply_tool_name_fix(self, action: dict) -> tuple[dict | None, list[str]]:
        """Apply tool name correction to a parsed action dict.

        Returns:
            (corrected_action, corrections) or (None, [error_msg]) if ambiguous.
        """
        corrections: list[str] = []
        tool_name = action.get("action", "")

        if not tool_name:
            return action, corrections

        # Check if tool name is already valid
        if tool_name in self._registry:
            return action, corrections

        corrected = self._fix_tool_name(tool_name)

        if corrected is not None:
            # Single unambiguous match
            corrections.append(f"tool_name:{tool_name}->{corrected}")
            self._correction_log["tool_name"] += 1
            action = dict(action)
            action["action"] = corrected
            return action, corrections
        else:
            # Check if ambiguous (multiple candidates within distance 2)
            candidates = [
                name for name in self._registry
                if _levenshtein(tool_name, name) <= 2
            ]
            if len(candidates) > 1:
                error_msg = (
                    f"Ambiguous tool name '{tool_name}'. "
                    f"Matches multiple tools: {', '.join(sorted(candidates))}. "
                    f"Please use the exact tool name."
                )
                return None, [error_msg]
            else:
                # No close match — return action as-is (executor will handle unknown tool)
                return action, corrections

    def get_session_hints(self, min_count: int = 2, top_k: int = 3) -> str:
        """Return top corrections as hints for the system prompt.

        Only includes corrections that occurred at least `min_count` times.
        Returns at most `top_k` hints.
        """
        # Filter corrections that meet the minimum count threshold
        frequent = [
            (error_type, count)
            for error_type, count in self._correction_log.most_common()
            if count >= min_count
        ][:top_k]

        if not frequent:
            return ""

        hint_messages = {
            "single_quotes": "Use double quotes (\") not single quotes (') in JSON",
            "backslash": "Escape backslashes in file paths (use \\\\ not \\)",
            "trailing_comma": "Do not put a comma before } or ] in JSON",
            "tool_name": "Check tool names carefully for typos",
        }

        lines = ["[JSON FORMAT HINTS - avoid these repeated errors:]"]
        for error_type, count in frequent:
            msg = hint_messages.get(error_type, f"Fix: {error_type}")
            lines.append(f"- {msg} (corrected {count}x)")

        return "\n".join(lines)

    def _extract_likely_tool_name(self, raw: str) -> str | None:
        """Try to extract the intended tool name from malformed JSON."""
        # Look for "action": "..." or 'action': '...' patterns
        match = re.search(r"""['"]action['"][\s:]+['"]([^'"]+)['"]""", raw)
        if match:
            return match.group(1)
        return None

    def _build_corrective_example(self, tool_name: str | None) -> str:
        """Build a corrective example showing valid JSON for the tool."""
        if tool_name and tool_name in self._registry:
            schema = self._registry[tool_name]
            example_params = {}
            for param in schema.params:
                if param.required:
                    if param.type == "string":
                        example_params[param.name] = f"<{param.name}>"
                    elif param.type == "list":
                        example_params[param.name] = [f"<{param.name}_item>"]
                    elif param.type == "dict":
                        example_params[param.name] = {}
                    elif param.type == "int":
                        example_params[param.name] = 0
                    elif param.type == "bool":
                        example_params[param.name] = True

            example = {"action": tool_name}
            example.update(example_params)
            return f"Correct format: {json.dumps(example)}"

        # Generic example
        return 'Correct format: {"action": "tool_name", "param": "value"}'

    def reset(self) -> None:
        """Reset the correction log for a new session."""
        self._correction_log.clear()
