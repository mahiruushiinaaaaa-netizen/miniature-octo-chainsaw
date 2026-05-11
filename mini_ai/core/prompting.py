"""
prompting.py – Lean prompt builder. /no_think disables chain-of-thought for speed.
"""
from __future__ import annotations

import re

_CLEAN_TOKENS = (
    "<|im_end|>", "<|endoftext|>",
    "<|im_start|>assistant", "<|im_start|>user",
)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN = re.compile(r"^<think>.*", re.DOTALL | re.IGNORECASE)


def build_chat_prompt(user_text: str, system_text: str | None = None) -> str:
    system_text = system_text or (
        "You are a helpful local AI assistant. Answer directly and concisely."
    )
    return (
        "<|im_start|>system\n"
        f"{system_text}\n"
        "<|im_end|>\n"
        "<|im_start|>user\n"
        f"{user_text}\n"
        "<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def clean_model_output(text: str) -> str:
    # text = _THINK_RE.sub("", text)
    # text = _THINK_OPEN.sub("", text)
    for tok in _CLEAN_TOKENS:
        text = text.replace(tok, "")
    text = text.strip()
    if text.lower().startswith("assistant"):
        text = text[len("assistant"):].strip()
    if text.startswith(":"):
        text = text[1:].strip()
    return text.strip()


# ---------------------------------------------------------------------------
# Token Budget Manager
# ---------------------------------------------------------------------------

import math
from dataclasses import dataclass, field
from typing import Optional

from mini_ai.core.logger import get_logger

_budget_logger = get_logger("token_budget")


@dataclass
class PromptSection:
    """A labeled section of the prompt with priority metadata."""
    name: str           # e.g., "GOAL", "HISTORY", "CONTEXT", "TOOLS", "REPO_MAP"
    content: str
    priority: int       # 0 = highest (never dropped), 3 = lowest (dropped first)
    mandatory: bool = False  # If True, never dropped regardless of budget
    max_tokens: Optional[int] = None  # Per-section cap


class TokenBudgetManager:
    """Enforces strict token budgets with priority-based section trimming.

    Budget calculation:
      - ctx_size <= 4096: min(ctx_size - 1096, 3000)
      - ctx_size > 4096:  ctx_size - 1096

    Trimming order (reverse priority):
      1. Drop repo_map (priority 3)
      2. Drop session context (priority 2)
      3. Summarize old observations (priority 1)
      4. Drop repo_map entirely as last resort
    """

    CHAR_TO_TOKEN_RATIO = 4

    def __init__(self, ctx_size: int):
        if ctx_size <= 4096:
            self.budget = min(ctx_size - 1096, 3000)
        else:
            self.budget = ctx_size - 1096
        self.ctx_size = ctx_size
        self.sections: dict[str, PromptSection] = {}

    def add_section(
        self,
        name: str,
        content: str,
        priority: int,
        mandatory: bool = False,
        max_tokens: Optional[int] = None,
    ) -> None:
        """Add a prompt section. Priority 0 = highest (never dropped first)."""
        self.sections[name] = PromptSection(
            name=name,
            content=content,
            priority=priority,
            mandatory=mandatory,
            max_tokens=max_tokens,
        )

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count using character-to-token ratio (len // 4)."""
        return len(text) // self.CHAR_TO_TOKEN_RATIO

    def build(self) -> str:
        """Assemble prompt within budget, dropping low-priority sections first.

        Trimming strategy:
          1. Apply per-section max_tokens caps
          2. If over budget, apply repo map BM25 filtering (score > 1.5)
          3. If over budget, summarize old observations (all but 3 most recent)
          4. If over budget, drop sections in reverse priority order (highest priority number first)
             - Skip mandatory sections
          5. If still over budget, drop repo map entirely as last resort and log warning

        Raises:
            ValueError: If the final assembled prompt still exceeds the budget
                        (only possible if mandatory sections alone exceed it).
        """
        # Work on a copy so we can mutate
        working: dict[str, PromptSection] = {}
        for name, section in self.sections.items():
            content = section.content
            # Apply per-section max_tokens cap
            if section.max_tokens is not None:
                max_chars = section.max_tokens * self.CHAR_TO_TOKEN_RATIO
                if len(content) > max_chars:
                    content = content[:max_chars]
            working[name] = PromptSection(
                name=section.name,
                content=content,
                priority=section.priority,
                mandatory=section.mandatory,
                max_tokens=section.max_tokens,
            )

        # Step 1: Check if we're within budget already
        if self._total_tokens(working) <= self.budget:
            return self._assemble(working)

        # Step 2: Apply repo map BM25 filtering if repo_map section exists and > 400 tokens
        if "REPO_MAP" in working:
            repo_section = working["REPO_MAP"]
            repo_tokens = self.estimate_tokens(repo_section.content)
            if repo_tokens > 400:
                filtered_content = self._filter_repo_map_bm25(repo_section.content)
                working["REPO_MAP"] = PromptSection(
                    name=repo_section.name,
                    content=filtered_content,
                    priority=repo_section.priority,
                    mandatory=repo_section.mandatory,
                    max_tokens=repo_section.max_tokens,
                )

        if self._total_tokens(working) <= self.budget:
            return self._assemble(working)

        # Step 3: Summarize old observations if history > 2000 chars
        if "HISTORY" in working:
            history_section = working["HISTORY"]
            if len(history_section.content) > 2000:
                summarized = self._summarize_observations(history_section.content)
                working["HISTORY"] = PromptSection(
                    name=history_section.name,
                    content=summarized,
                    priority=history_section.priority,
                    mandatory=history_section.mandatory,
                    max_tokens=history_section.max_tokens,
                )

        if self._total_tokens(working) <= self.budget:
            return self._assemble(working)

        # Step 4: Drop sections in reverse priority order (highest number = lowest priority)
        # Priority order for dropping: 3 (REPO_MAP) → 2 (CONTEXT) → 1 (HISTORY)
        sorted_sections = sorted(
            working.values(),
            key=lambda s: s.priority,
            reverse=True,  # Drop highest priority number first
        )

        for section in sorted_sections:
            if section.mandatory:
                continue
            if self._total_tokens(working) <= self.budget:
                break
            del working[section.name]

        if self._total_tokens(working) <= self.budget:
            return self._assemble(working)

        # Step 5: Drop repo map entirely as last resort
        if "REPO_MAP" in working:
            _budget_logger.warn(
                "Dropping repo map entirely — budget could not be met with all sections",
                operation="token_budget_build",
                context={"budget": self.budget, "total_tokens": self._total_tokens(working)},
            )
            del working["REPO_MAP"]

        assembled = self._assemble(working)
        estimated = self.estimate_tokens(assembled)
        if estimated > self.budget:
            raise ValueError(
                f"Prompt ({estimated} tokens) exceeds budget ({self.budget} tokens) "
                f"even after all trimming. Mandatory sections alone are too large."
            )
        return assembled

    def _total_tokens(self, sections: dict[str, PromptSection]) -> int:
        """Calculate total estimated tokens across all sections."""
        total_chars = sum(len(s.content) for s in sections.values())
        return total_chars // self.CHAR_TO_TOKEN_RATIO

    def _assemble(self, sections: dict[str, PromptSection]) -> str:
        """Assemble sections into final prompt string, ordered by priority."""
        ordered = sorted(sections.values(), key=lambda s: s.priority)
        parts = []
        for section in ordered:
            if section.content.strip():
                parts.append(f"[{section.name}]\n{section.content}")
        return "\n\n".join(parts)

    def _filter_repo_map_bm25(self, repo_map_content: str) -> str:
        """Truncate repo map to entries with BM25 score > 1.5.

        Each line in the repo map is treated as a file entry.
        We use a simple BM25-like scoring based on term frequency
        relative to the goal (if available in sections).
        Lines that don't score above 1.5 are removed.
        """
        goal_content = ""
        if "GOAL" in self.sections:
            goal_content = self.sections["GOAL"].content.lower()

        if not goal_content:
            # Without a goal, we can't score — just truncate to 400 tokens worth
            max_chars = 400 * self.CHAR_TO_TOKEN_RATIO
            return repo_map_content[:max_chars]

        lines = repo_map_content.strip().split("\n")
        if not lines:
            return repo_map_content

        # Extract goal terms for BM25-like scoring
        goal_terms = set(goal_content.split())

        scored_lines: list[tuple[float, str]] = []
        for line in lines:
            score = self._bm25_score_line(line, goal_terms, len(lines))
            scored_lines.append((score, line))

        # Keep only lines with score > 1.5
        filtered = [line for score, line in scored_lines if score > 1.5]

        if not filtered:
            # If nothing scores above threshold, keep top entries up to 400 tokens
            scored_lines.sort(key=lambda x: x[0], reverse=True)
            max_chars = 400 * self.CHAR_TO_TOKEN_RATIO
            result_lines = []
            char_count = 0
            for _, line in scored_lines:
                if char_count + len(line) + 1 > max_chars:
                    break
                result_lines.append(line)
                char_count += len(line) + 1
            return "\n".join(result_lines)

        return "\n".join(filtered)

    def _bm25_score_line(
        self, line: str, goal_terms: set[str], total_docs: int
    ) -> float:
        """Simple BM25-inspired scoring for a single repo map line.

        Uses term frequency of goal terms in the line, with IDF approximation.
        k1=1.5, b=0.75 (standard BM25 parameters).
        """
        line_lower = line.lower()
        line_terms = line_lower.split()
        if not line_terms:
            return 0.0

        k1 = 1.5
        b = 0.75
        avg_dl = 10.0  # Approximate average line length in terms
        dl = len(line_terms)

        score = 0.0
        for term in goal_terms:
            tf = line_terms.count(term)
            if tf == 0:
                continue
            # IDF approximation: log((N - n + 0.5) / (n + 0.5))
            # Since we don't have doc frequency, use a simple boost
            idf = math.log((total_docs + 0.5) / (1 + 0.5))
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * (dl / avg_dl))
            score += idf * (numerator / denominator)

        return score

    def _summarize_observations(self, history_content: str) -> str:
        """Summarize all observations except the 3 most recent.

        Each observation is expected to be separated by newlines.
        Old observations are reduced to single-line format:
          [tool_name] success/fail
        """
        # Split observations by double-newline or observation markers
        observations = self._split_observations(history_content)

        if len(observations) <= 3:
            return history_content

        # Keep 3 most recent in full
        recent = observations[-3:]
        old = observations[:-3]

        # Summarize old observations to single-line format
        summarized_lines = []
        for obs in old:
            summary = self._summarize_single_observation(obs)
            summarized_lines.append(summary)

        # Reassemble
        summary_block = "\n".join(summarized_lines)
        recent_block = "\n\n".join(recent)
        return f"{summary_block}\n\n{recent_block}"

    def _split_observations(self, content: str) -> list[str]:
        """Split observation history into individual observations."""
        # Try splitting by double newline first
        parts = content.split("\n\n")
        # Filter out empty parts
        return [p.strip() for p in parts if p.strip()]

    def _summarize_single_observation(self, observation: str) -> str:
        """Reduce a single observation to: [tool_name] success/fail."""
        lines = observation.strip().split("\n")
        first_line = lines[0] if lines else observation

        # Try to extract tool name from common patterns
        tool_name = "unknown"
        status = "done"

        # Pattern: [TOOL_NAME] STATUS: ...
        if first_line.startswith("[") and "]" in first_line:
            bracket_end = first_line.index("]")
            tool_name = first_line[1:bracket_end]
            rest = first_line[bracket_end + 1:].strip()
            if "fail" in rest.lower() or "error" in rest.lower():
                status = "fail"
            else:
                status = "success"
        # Pattern: Tool: tool_name ...
        elif ":" in first_line:
            parts = first_line.split(":", 1)
            tool_name = parts[0].strip()
            rest = parts[1].strip() if len(parts) > 1 else ""
            if "fail" in rest.lower() or "error" in rest.lower():
                status = "fail"
            else:
                status = "success"
        else:
            # Fallback: use first word as tool name
            words = first_line.split()
            if words:
                tool_name = words[0]
            if "fail" in observation.lower() or "error" in observation.lower():
                status = "fail"
            else:
                status = "success"

        return f"[{tool_name}] {status}"
