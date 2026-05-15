"""
Minimal Prompt System - Micro-prompt templates and assembly.

Ultra-lean, modular prompt architecture optimized for 3B parameter models
on constrained hardware. Enforces strict token budgets and uses task-specific
micro-prompt templates for fast, focused generation.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from mini_ai.core.grammars import MINIMAL_JSON_GRAMMAR

logger = logging.getLogger(__name__)


# Valid intent types for micro-prompt templates
VALID_INTENTS = frozenset({"TASK", "QUERY", "EDIT", "EXPLORE", "COMPLEX"})


@dataclass(frozen=True)
class MicroPromptTemplate:
    """Immutable micro-prompt template for a specific task type.

    Each template defines the prompt structure, one-shot example, available
    tools, and token budget constraints for a single intent type.
    """

    intent: str  # "TASK", "QUERY", "EDIT", "EXPLORE", "COMPLEX"
    template: str  # Template string with {goal} placeholder
    one_shot_example: str  # Valid JSON string with "action" key
    available_tools: list[str]  # Tool names available for this intent
    max_prompt_tokens: int = 500  # Hard cap for assembled prompt [200, 1000]
    max_gen_tokens: int = 256  # Generation limit [64, 512]

    def __post_init__(self) -> None:
        """Validate all fields at creation time."""
        # Validate intent
        if self.intent not in VALID_INTENTS:
            raise ValueError(
                f"intent must be one of {sorted(VALID_INTENTS)}, "
                f"got '{self.intent}'"
            )

        # Validate template
        if not isinstance(self.template, str):
            raise ValueError(
                f"template must be a string, got {type(self.template).__name__}"
            )
        if len(self.template) > 2000:
            raise ValueError(
                f"template must be at most 2000 characters, "
                f"got {len(self.template)}"
            )
        if "{goal}" not in self.template:
            raise ValueError(
                "template must contain '{goal}' placeholder"
            )

        # Validate one_shot_example
        if not isinstance(self.one_shot_example, str):
            raise ValueError(
                f"one_shot_example must be a string, "
                f"got {type(self.one_shot_example).__name__}"
            )
        if len(self.one_shot_example) > 500:
            raise ValueError(
                f"one_shot_example must be at most 500 characters, "
                f"got {len(self.one_shot_example)}"
            )
        try:
            parsed = json.loads(self.one_shot_example)
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(
                f"one_shot_example must be valid JSON, parse error: {e}"
            )
        if not isinstance(parsed, dict) or "action" not in parsed:
            raise ValueError(
                "one_shot_example must be a JSON object containing an 'action' key"
            )
        if not isinstance(parsed["action"], str) or not parsed["action"].strip():
            raise ValueError(
                "one_shot_example 'action' value must be a non-empty string"
            )

        # Validate available_tools
        if not isinstance(self.available_tools, list):
            raise ValueError(
                f"available_tools must be a list, "
                f"got {type(self.available_tools).__name__}"
            )
        if len(self.available_tools) < 1:
            raise ValueError(
                "available_tools must contain at least 1 item"
            )
        if len(self.available_tools) > 20:
            raise ValueError(
                f"available_tools must contain at most 20 items, "
                f"got {len(self.available_tools)}"
            )
        for i, tool in enumerate(self.available_tools):
            if not isinstance(tool, str) or not tool.strip():
                raise ValueError(
                    f"available_tools[{i}] must be a non-empty string"
                )

        # Validate max_prompt_tokens
        if not isinstance(self.max_prompt_tokens, int):
            raise ValueError(
                f"max_prompt_tokens must be an integer, "
                f"got {type(self.max_prompt_tokens).__name__}"
            )
        if self.max_prompt_tokens < 200 or self.max_prompt_tokens > 1000:
            raise ValueError(
                f"max_prompt_tokens must be between 200 and 1000, "
                f"got {self.max_prompt_tokens}"
            )

        # Validate max_gen_tokens
        if not isinstance(self.max_gen_tokens, int):
            raise ValueError(
                f"max_gen_tokens must be an integer, "
                f"got {type(self.max_gen_tokens).__name__}"
            )
        if self.max_gen_tokens < 64 or self.max_gen_tokens > 512:
            raise ValueError(
                f"max_gen_tokens must be between 64 and 512, "
                f"got {self.max_gen_tokens}"
            )


class MicroPromptRegistry:
    """Registry of micro-prompt templates indexed by intent type.

    On initialization, registers default templates for TASK, QUERY, EDIT,
    and EXPLORE intents. Unknown intents fall back to EXPLORE template.
    """

    def __init__(self) -> None:
        self._templates: dict[str, MicroPromptTemplate] = {}
        self._register_defaults()

    def get(self, intent: str) -> MicroPromptTemplate:
        """Get template for intent. Falls back to EXPLORE if unknown.

        Handles None, empty string, and unrecognized intents gracefully
        by returning the EXPLORE template without raising an exception.
        """
        if not intent or intent not in self._templates:
            if intent and intent not in self._templates:
                logger.warning(
                    "Unrecognized intent '%s', falling back to EXPLORE", intent
                )
            return self._templates["EXPLORE"]
        return self._templates[intent]

    def register(self, template: MicroPromptTemplate) -> None:
        """Register or override a template for its intent type."""
        self._templates[template.intent] = template

    def _register_defaults(self) -> None:
        """Register built-in templates for TASK, QUERY, EDIT, EXPLORE."""
        self.register(MicroPromptTemplate(
            intent="TASK",
            template=(
                "Goal: {goal}\n"
                "Tools: {tools}\n"
                "{context}"
                "Example: {example}\n"
                "Output JSON:"
            ),
            one_shot_example='{"action": "run_cmd", "command": "composer create-project laravel/laravel my-app"}',
            available_tools=["run_cmd", "write_files", "list_dir", "web_search", "read_files", "make_dir", "scaffold", "answer"],
            max_prompt_tokens=500,
            max_gen_tokens=256,
        ))

        self.register(MicroPromptTemplate(
            intent="QUERY",
            template=(
                "Goal: {goal}\n"
                "Tools: {tools}\n"
                "{context}"
                "Example: {example}\n"
                "Output JSON:"
            ),
            one_shot_example='{"action": "answer", "content": "The answer is 42."}',
            available_tools=["run_cmd", "web_search", "read_files", "calculate", "datetime_util", "system_info", "answer"],
            max_prompt_tokens=400,
            max_gen_tokens=128,
        ))

        self.register(MicroPromptTemplate(
            intent="EDIT",
            template=(
                "Goal: {goal}\n"
                "Tools: {tools}\n"
                "{context}"
                "Example: {example}\n"
                "Output JSON:"
            ),
            one_shot_example='{"action": "write_files", "files": [{"path": "src/main.py", "content": "print(\'hello\')"}]}',
            available_tools=["write_files", "read_files", "run_cmd", "search_files", "edit_blocks", "diff_files", "answer"],
            max_prompt_tokens=700,
            max_gen_tokens=512,
        ))

        self.register(MicroPromptTemplate(
            intent="EXPLORE",
            template=(
                "Goal: {goal}\n"
                "Tools: {tools}\n"
                "{context}"
                "Example: {example}\n"
                "Output JSON:"
            ),
            one_shot_example='{"action": "list_dir", "path": "."}',
            available_tools=["run_cmd", "read_files", "list_dir", "write_files", "web_search", "search_files", "file_info", "answer"],
            max_prompt_tokens=600,
            max_gen_tokens=256,
        ))


class StepMemory:
    """Ultra-compact rolling memory for the micro-prompt agent loop.

    Maintains a short list of key facts learned across steps (errors,
    failed commands, successful actions) compressed to ~50 tokens max.
    This gives the model context without bloating the prompt.
    """

    def __init__(self, max_chars: int = 200) -> None:
        self._facts: list[str] = []
        self._max_chars = max_chars

    def record_error(self, tool: str, error_summary: str) -> None:
        """Record a tool error as a compact fact."""
        # Extract the key info from the error
        short = error_summary[:80].split("\n")[0].strip()
        fact = f"{tool} FAILED: {short}"
        self._add_fact(fact)

    def record_success(self, tool: str, summary: str) -> None:
        """Record a successful action as a compact fact."""
        short = summary[:60].split("\n")[0].strip()
        fact = f"{tool} OK: {short}"
        self._add_fact(fact)

    def record_fact(self, fact: str) -> None:
        """Record an arbitrary fact."""
        self._add_fact(fact[:80])

    def _add_fact(self, fact: str) -> None:
        """Add a fact, evicting oldest if over budget."""
        self._facts.append(fact)
        # Evict oldest facts until we're within budget
        while self._total_chars() > self._max_chars and len(self._facts) > 1:
            self._facts.pop(0)

    def _total_chars(self) -> int:
        return sum(len(f) for f in self._facts) + len(self._facts)  # +separators

    def get_memory_line(self) -> str:
        """Get the compact memory string for injection into prompts.

        Returns empty string if no facts recorded.
        """
        if not self._facts:
            return ""
        return "Memory: " + "; ".join(self._facts) + "\n"

    def clear(self) -> None:
        """Clear all recorded facts."""
        self._facts.clear()


class PromptAssembler:
    """Assembles minimal prompts within strict token budgets.

    Combines a constant system prompt with task-specific micro-prompt templates,
    enforcing hard token caps per intent type. Designed for 3B parameter models
    on constrained hardware where every token counts.
    """

    SYSTEM_PROMPT: str = (
        "You execute tasks by outputting a single JSON action on Windows. "
        'Format: {"action": "tool_name", ...params}. '
        "Use specialized tools over run_cmd when possible. Never narrate. "
        "If a command fails, try a different approach."
    )

    def __init__(
        self, registry: MicroPromptRegistry, max_total_tokens: int = 500
    ) -> None:
        self._registry = registry
        self._max_tokens = max_total_tokens

    # Compiled regex patterns for sensitive data detection
    _SENSITIVE_PATTERNS: list[re.Pattern[str]] = [
        # API key prefixes: sk-, ghp_, AKIA followed by alphanumeric chars
        re.compile(r'\bsk-[A-Za-z0-9]{20,}'),
        re.compile(r'\bghp_[A-Za-z0-9]{20,}'),
        re.compile(r'\bAKIA[A-Z0-9]{12,}'),
        # Environment variable references: ${VAR_NAME} (braced form - always sensitive)
        re.compile(r'\$\{[A-Za-z_][A-Za-z0-9_]{2,}\}'),
        # $VAR_NAME - require underscore-containing names (like $API_KEY, $DB_HOST)
        re.compile(r'\$[A-Z][A-Z0-9]*_[A-Z0-9_]+\b'),
        # Password/secret/token field assignments (key=value or key: value patterns)
        re.compile(
            r'(?:password|secret|token|api_key|apikey|auth_token|access_token)'
            r'\s*[=:]\s*["\']?([^\s"\',}\]]+)',
            re.IGNORECASE,
        ),
    ]

    def _redact_sensitive(self, text: str) -> str:
        """Detect and redact sensitive data patterns from text.

        Scans for:
        - API key prefixes: "sk-", "ghp_", "AKIA" followed by alphanumeric chars
        - Environment variable references: $VAR_NAME or ${VAR_NAME}
        - Strings assigned to password/secret/token fields

        Replaces detected sensitive values with [REDACTED].

        Args:
            text: The text to scan and redact.

        Returns:
            Text with sensitive values replaced by [REDACTED].
        """
        result = text

        # Redact API key patterns (sk-, ghp_, AKIA)
        result = self._SENSITIVE_PATTERNS[0].sub('[REDACTED]', result)
        result = self._SENSITIVE_PATTERNS[1].sub('[REDACTED]', result)
        result = self._SENSITIVE_PATTERNS[2].sub('[REDACTED]', result)

        # Redact environment variable references
        result = self._SENSITIVE_PATTERNS[3].sub('[REDACTED]', result)
        result = self._SENSITIVE_PATTERNS[4].sub('[REDACTED]', result)

        # Redact password/secret/token field values
        # For this pattern, we replace the entire match but preserve the field name
        def _redact_field_value(match: re.Match[str]) -> str:
            full = match.group(0)
            value = match.group(1)
            return full.replace(value, '[REDACTED]')

        result = self._SENSITIVE_PATTERNS[5].sub(_redact_field_value, result)

        return result

    def estimate_tokens(self, text: str) -> int:
        """Estimate tokens using len // 4 heuristic.

        This is a fast approximation suitable for budget enforcement
        without requiring a tokenizer dependency.
        """
        return len(text) // 4

    def aggressive_truncate(self, text: str, max_tokens: int) -> str:
        """Truncate text to fit within token budget.

        If the text exceeds max_tokens (estimated), it is cut and "..."
        is appended as a truncation indicator.

        Args:
            text: The text to potentially truncate.
            max_tokens: Maximum allowed estimated tokens.

        Returns:
            The original text if within budget, or truncated text with "...".
        """
        max_chars = max_tokens * 4
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3] + "..."

    def assemble(
        self,
        intent: str,
        goal: str,
        last_result: str | None = None,
        step: int = 1,
        memory: str = "",
    ) -> str:
        """Build the complete prompt under token budget.

        Assembly algorithm:
        1. Get template for intent from registry
        2. System prompt is constant (~50 tokens)
        3. Format micro-prompt with goal and context:
           - step==1 or last_result is None: include one_shot_example
           - step>1 with last_result: include compact last_result, exclude example
        4. Enforce token budget (template.max_prompt_tokens):
           - If over budget: truncate context first, then goal
           - Always preserve at least first 50 chars of goal
        5. Return assembled prompt string

        Args:
            intent: The classified intent (TASK, QUERY, EDIT, EXPLORE, etc.)
            goal: The user's goal text.
            last_result: Result from previous step, or None.
            step: Current step number (1-based).
            memory: Compact memory line from StepMemory (e.g. "Memory: cmd FAILED: ...").

        Returns:
            Assembled prompt string within token budget.
        """
        template = self._registry.get(intent)
        tools_str = ", ".join(template.available_tools)

        # Determine context and example based on step
        if step == 1 or last_result is None:
            # First step: include one-shot example, no context
            example_str = template.one_shot_example
            context_str = memory  # Memory only (may be empty on step 1)
        else:
            # Subsequent steps: include compact last_result, exclude example
            compact_result = last_result[:300] if len(last_result) > 300 else last_result
            example_str = ""
            context_str = f"{memory}Last result: {compact_result}\n"

        # Format the user text from template
        user_text = template.template.format(
            goal=goal,
            tools=tools_str,
            example=example_str,
            context=context_str,
        )

        # Enforce token budget
        budget = template.max_prompt_tokens
        system_tokens = self.estimate_tokens(self.SYSTEM_PROMPT + "\n")
        total = self.estimate_tokens(self.SYSTEM_PROMPT + "\n" + user_text)

        if total > budget:
            # Available tokens for user_text
            available_user_tokens = budget - system_tokens

            # Strategy: truncate context first, then goal
            if context_str and step > 1 and last_result is not None:
                # Try reducing context (last_result portion)
                # Rebuild with truncated context
                reduced_context = self.aggressive_truncate(
                    context_str, available_user_tokens // 2
                )
                user_text = template.template.format(
                    goal=goal,
                    tools=tools_str,
                    example=example_str,
                    context=reduced_context,
                )
                total = self.estimate_tokens(self.SYSTEM_PROMPT + "\n" + user_text)

            if total > budget:
                # Still over budget - truncate goal while preserving at least 50 chars
                available_user_tokens = budget - system_tokens

                # Calculate how much space goal can have
                # Build the template with a placeholder to measure overhead
                overhead_text = template.template.format(
                    goal="",
                    tools=tools_str,
                    example=example_str if (step == 1 or last_result is None) else "",
                    context=context_str if (step > 1 and last_result is not None) else "",
                )
                overhead_tokens = self.estimate_tokens(overhead_text)
                goal_budget_tokens = available_user_tokens - overhead_tokens

                # Preserve at least first 50 chars of goal
                if len(goal) < 50:
                    truncated_goal = goal
                else:
                    goal_max_chars = max(50, goal_budget_tokens * 4)
                    if len(goal) > goal_max_chars:
                        truncated_goal = goal[: goal_max_chars - 3] + "..."
                    else:
                        truncated_goal = goal

                # Also truncate context if still needed
                if step > 1 and last_result is not None:
                    remaining_tokens = available_user_tokens - self.estimate_tokens(
                        template.template.format(
                            goal=truncated_goal,
                            tools=tools_str,
                            example="",
                            context="",
                        )
                    )
                    if remaining_tokens > 0:
                        reduced_context = self.aggressive_truncate(
                            context_str, remaining_tokens
                        )
                    else:
                        reduced_context = ""
                    user_text = template.template.format(
                        goal=truncated_goal,
                        tools=tools_str,
                        example="",
                        context=reduced_context,
                    )
                else:
                    user_text = template.template.format(
                        goal=truncated_goal,
                        tools=tools_str,
                        example=example_str,
                        context="",
                    )

                # Final check - if still over, do aggressive truncate on entire user_text
                total = self.estimate_tokens(self.SYSTEM_PROMPT + "\n" + user_text)
                if total > budget:
                    user_text = self.aggressive_truncate(
                        user_text, available_user_tokens
                    )

        # Final total check and warning
        final_total = self.estimate_tokens(self.SYSTEM_PROMPT + "\n" + user_text)
        if final_total > budget:
            logger.warning(
                "Prompt exceeds token budget after truncation: "
                "%d tokens > %d budget for intent '%s'",
                final_total,
                budget,
                intent,
            )

        # Redact sensitive data from user_text before returning
        user_text = self._redact_sensitive(user_text)

        return self.SYSTEM_PROMPT + "\n" + user_text


def select_grammar_for_intent(intent: str) -> str | None:
    """Select GBNF grammar based on intent type.

    Returns the appropriate grammar to constrain model output:
    - TASK/QUERY/EXPLORE: Returns MINIMAL_JSON_GRAMMAR (forces valid JSON action)
    - EDIT: Returns None (allows free-form SEARCH/REPLACE blocks)
    - COMPLEX or any other intent: Returns MINIMAL_JSON_GRAMMAR

    Args:
        intent: The classified intent type string.

    Returns:
        GBNF grammar string for JSON intents, or None for EDIT intent.
    """
    if intent in ("TASK", "QUERY", "EXPLORE"):
        return MINIMAL_JSON_GRAMMAR
    elif intent == "EDIT":
        return None
    else:
        return MINIMAL_JSON_GRAMMAR
