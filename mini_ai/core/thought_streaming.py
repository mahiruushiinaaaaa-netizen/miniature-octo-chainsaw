"""
thought_streaming.py – ThoughtStreamingHandler for agent UI rendering.

Handles streaming token display for thinking/planning/reasoning blocks
in both sequential (console) and dual-pane (live) modes.
"""
from __future__ import annotations

import re
from typing import Optional

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class ThoughtStreamingHandler:
    """Token handler that detects thinking/planning blocks and renders them in UI."""

    def __init__(self, original_on_token=None, live_view=None):
        self.original_on_token = original_on_token
        self.live_view = live_view
        self.buffer = ""
        self.is_thinking = False
        self.is_planning = False
        self.thought_stream = None
        self.plan_stream = None

    def __call__(self, token: str):
        if self.original_on_token:
            self.original_on_token(token)
        self.buffer += token

        # 1. Handle explicit <think> tags
        if not self.is_thinking and "<think>" in self.buffer:
            self.is_thinking = True
            if not self.live_view:
                from ..ui import MarkdownStream
                self.thought_stream = MarkdownStream(title="THOUGHTS", border_style="#BD93F9")

        # 2. Handle JSON 'plan' or 'thoughts' field if streaming
        if not self.is_planning and ('"plan": "' in self.buffer or '"thoughts": "' in self.buffer):
            self.is_planning = True
            if not self.live_view:
                from ..ui import MarkdownStream
                self.plan_stream = MarkdownStream(title="PLAN", border_style="#8BE9FD")

        # 3. Handle raw text before JSON as thinking
        if not self.is_thinking and not self.is_planning and len(self.buffer) > 10:
            if "{" not in self.buffer and "<<<<<<" not in self.buffer:
                self.is_thinking = True
                if not self.live_view:
                    from ..ui import MarkdownStream
                    self.thought_stream = MarkdownStream(title="REASONING", border_style="#BD93F9")

        # Sequential mode (no live_view): print to console
        if not self.live_view:
            if self.is_thinking:
                if not hasattr(self, 'thought_stream') or self.thought_stream is None:
                    from ..ui import MarkdownStream
                    self.thought_stream = MarkdownStream(title="REASONING", border_style="#BD93F9")
                clean_token = token.replace("<think>", "").replace("</think>", "")
                self.thought_stream.update(clean_token)
            elif self.is_planning and self.plan_stream:
                self.plan_stream.update(token)
        else:
            # Dual-pane/Live mode updates
            from ..ui import update_agent_thoughts
            if self.is_thinking:
                update_agent_thoughts(self.buffer)
            elif self.is_planning:
                update_agent_thoughts(f"### PLAN\n{self.buffer}\n")

        # Update dual-pane if active
        if self.live_view:
            from ..ui import update_agent_thoughts
            think_match = _THINK_RE.search(self.buffer)
            if think_match:
                update_agent_thoughts(think_match.group(0).strip("<think>").strip("</think>"))
            elif self.is_planning:
                plan_match = re.search(r'"(?:plan|thoughts)":\s*"([^"]*)', self.buffer)
                if plan_match:
                    update_agent_thoughts(f"### PLAN\n{plan_match.group(1)}")
            else:
                update_agent_thoughts(self.buffer[-500:])

        # Stop thinking if we see start of action/closing tags
        if (self.is_thinking or self.is_planning) and (
            "<<<<<<" in token or "</think>" in token or '", "action"' in self.buffer[-20:]
        ):
            self.is_thinking = False
            self.is_planning = False
            if self.thought_stream:
                self.thought_stream.update("", final=True)
            if self.plan_stream:
                self.plan_stream.update("", final=True)
