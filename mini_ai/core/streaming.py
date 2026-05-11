"""
streaming.py – Streaming response parser for early JSON action detection.

Parses JSON actions from streaming tokens using brace-depth tracking.
When the brace depth returns to zero, attempts to parse the buffered JSON
and validates it against the ToolSchema registry. This enables early action
execution before the full response is generated.

Requirements: 10.1, 10.2, 10.4, 10.5
"""
from __future__ import annotations

import json
import logging
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mini_ai.core.schemas import ToolSchema

logger = logging.getLogger(__name__)


class ParseEvent(Enum):
    """Events emitted by the streaming parser."""

    BUFFERING = "buffering"
    ACTION_READY = "action_ready"
    INVALID_CANDIDATE = "invalid_candidate"
    STREAM_END = "stream_end"


class StreamingActionParser:
    """Parses JSON actions from streaming tokens using brace-depth tracking.

    Feeds tokens one at a time. Tracks opening/closing braces to detect
    complete JSON objects. When brace depth returns to zero, attempts to
    parse the candidate JSON and validate it against the tool schema registry.

    If validation passes, emits ACTION_READY. If it fails, discards the
    candidate and continues buffering for the next brace-depth-zero boundary.

    If the stream ends without any valid action, the entire buffer is treated
    as plain reasoning text.
    """

    def __init__(self, schema_registry: dict[str, ToolSchema]):
        self._schema_registry = schema_registry
        self._buffer: str = ""
        self._brace_depth: int = 0
        self._in_string: bool = False
        self._escape_next: bool = False
        self._candidate_start: int = -1
        self._action: dict | None = None
        self._candidates: list[str] = []
        self._stream_ended: bool = False

    @property
    def action(self) -> dict | None:
        """Return the validated action if one was detected."""
        return self._action

    def get_action(self) -> dict | None:
        """Return the validated action if one was detected."""
        return self._action

    @property
    def buffer(self) -> str:
        """Return the current buffer contents (useful for reasoning text)."""
        return self._buffer

    def feed(self, token: str) -> ParseEvent | None:
        """Feed a token into the parser.

        Tracks brace depth character by character. When depth returns to zero
        after being > 0, extracts the candidate JSON substring and attempts
        to parse and validate it.

        Returns:
            ParseEvent.ACTION_READY - valid action detected, call get_action()
            ParseEvent.INVALID_CANDIDATE - candidate failed validation, continuing
            ParseEvent.BUFFERING - still accumulating tokens
            None - token processed, no event
        """
        if self._stream_ended or self._action is not None:
            return None

        for char in token:
            self._buffer += char
            event = self._process_char(char)
            if event is not None:
                return event

        # Still buffering if we haven't returned an event
        if self._brace_depth > 0:
            return ParseEvent.BUFFERING
        return None

    def finish(self) -> ParseEvent:
        """Signal end of stream.

        If no valid action was found during streaming, treats the entire
        buffer as plain reasoning text and returns STREAM_END.

        Returns:
            ParseEvent.ACTION_READY if a valid action was already found
            ParseEvent.STREAM_END if no valid action was detected
        """
        self._stream_ended = True

        if self._action is not None:
            return ParseEvent.ACTION_READY

        # Try one final parse of the entire buffer in case there's a
        # complete JSON object we missed (e.g., no trailing content)
        if self._buffer.strip():
            event = self._try_parse_full_buffer()
            if event == ParseEvent.ACTION_READY:
                return event

        return ParseEvent.STREAM_END

    def get_reasoning_text(self) -> str:
        """Return the buffer as plain reasoning text.

        Should be called after finish() returns STREAM_END to get the
        full response text for re-prompting.
        """
        return self._buffer

    def reset(self) -> None:
        """Reset parser state for reuse."""
        self._buffer = ""
        self._brace_depth = 0
        self._in_string = False
        self._escape_next = False
        self._candidate_start = -1
        self._action = None
        self._candidates = []
        self._stream_ended = False

    def _process_char(self, char: str) -> ParseEvent | None:
        """Process a single character, tracking brace depth and string state."""
        # Handle string escaping
        if self._escape_next:
            self._escape_next = False
            return None

        if char == "\\" and self._in_string:
            self._escape_next = True
            return None

        # Handle string boundaries
        if char == '"' and not self._escape_next:
            self._in_string = not self._in_string
            return None

        # Skip characters inside strings - they don't affect brace depth
        if self._in_string:
            return None

        # Track brace depth
        if char == "{":
            if self._brace_depth == 0:
                # Mark the start of a potential JSON object
                self._candidate_start = len(self._buffer) - 1
            self._brace_depth += 1
        elif char == "}":
            if self._brace_depth > 0:
                self._brace_depth -= 1
                if self._brace_depth == 0:
                    # Complete JSON candidate found
                    return self._try_parse_candidate()

        return None

    def _try_parse_candidate(self) -> ParseEvent | None:
        """Attempt to parse and validate a JSON candidate at brace-depth zero."""
        if self._candidate_start < 0:
            return None

        candidate_str = self._buffer[self._candidate_start:]
        self._candidates.append(candidate_str)

        try:
            parsed = json.loads(candidate_str)
        except (json.JSONDecodeError, ValueError):
            logger.debug("Streaming parser: candidate failed JSON parse")
            self._candidate_start = -1
            return ParseEvent.INVALID_CANDIDATE

        if not isinstance(parsed, dict):
            logger.debug("Streaming parser: candidate is not a dict")
            self._candidate_start = -1
            return ParseEvent.INVALID_CANDIDATE

        # Validate against tool schema registry
        if self._validate_action(parsed):
            self._action = parsed
            logger.debug(
                "Streaming parser: valid action detected - %s",
                parsed.get("action", "unknown"),
            )
            return ParseEvent.ACTION_READY

        logger.debug("Streaming parser: candidate failed schema validation")
        self._candidate_start = -1
        return ParseEvent.INVALID_CANDIDATE

    def _validate_action(self, parsed: dict) -> bool:
        """Validate parsed JSON against the ToolSchema registry.

        A valid action must have an "action" key whose value matches a
        registered tool name, and the parameters must pass schema validation.
        """
        action_name = parsed.get("action")
        if not action_name or not isinstance(action_name, str):
            return False

        schema = self._schema_registry.get(action_name)
        if schema is None:
            return False

        # Extract parameters (everything except "action" and "plan")
        params = {
            k: v for k, v in parsed.items() if k not in ("action", "plan")
        }

        # Validate parameters against schema
        valid, _error = schema.validate(params)
        return valid

    def _try_parse_full_buffer(self) -> ParseEvent | None:
        """Try to extract a JSON object from the full buffer as a last resort.

        Looks for the first '{' and last '}' in the buffer and attempts
        to parse that substring.
        """
        text = self._buffer.strip()
        first_brace = text.find("{")
        last_brace = text.rfind("}")

        if first_brace < 0 or last_brace <= first_brace:
            return None

        candidate_str = text[first_brace : last_brace + 1]

        try:
            parsed = json.loads(candidate_str)
        except (json.JSONDecodeError, ValueError):
            return None

        if not isinstance(parsed, dict):
            return None

        if self._validate_action(parsed):
            self._action = parsed
            return ParseEvent.ACTION_READY

        return None
