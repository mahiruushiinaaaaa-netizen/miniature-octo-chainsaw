"""
retry.py – Speed-first retry module with short-circuit and zero-cost recovery.

Extracted from agent.py to enable independent testing and optimization.
Provides structured retry logic for empty/invalid model responses with:
- Short-circuit: skip retries when previous step succeeded (model is responsive)
- Zero-cost recovery: temp bump or seed change before expensive grammar/nudge retries
- Existing cascade: grammar-removal → nudge as fallback after zero-cost fails

Requirements: 1.1, 2.1, 2.7, 3.1, 3.2, 3.4, 3.6
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

from .backend import generate
from .config import Config
from .logger import get_logger
from .schemas import TOOL_SCHEMAS

if TYPE_CHECKING:
    from .self_healing import SelfHealingParser

logger = get_logger("retry")

# Regex to strip <think>...</think> blocks from model output
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


@dataclass
class RetryState:
    """Tracks retry state for the generate-with-retry logic.

    Maintains a consecutive empty response counter across agent loop steps.
    After 2 consecutive empties, grammar is disabled for the session.
    """
    consecutive_empties: int = 0
    grammar_disabled: bool = False


def generate_with_retry(
    config: Config,
    prompt: str,
    system_text: str,
    grammar: Optional[str],
    max_tokens: int,
    on_token=None,
    self_healing_parser: Optional["SelfHealingParser"] = None,
    one_shot_example: str = '{"action": "run_cmd", "command": "echo hello"}',
    registered_tools: Optional[set[str]] = None,
    retry_state: Optional[RetryState] = None,
    previous_step_succeeded: bool = False,
    parse_action_fn=None,
) -> tuple[Optional[str], Optional[dict], RetryState]:
    """Generate model output with structured retry logic for empty/invalid responses.

    Speed-first retry flow:
    0. SHORT-CIRCUIT: if previous_step_succeeded=True AND output is empty → return immediately
    1. Generate with grammar → if empty/whitespace:
    2. ZERO-COST RECOVERY: re-send same prompt with temp+0.1 or seed+1 (no grammar recompile)
    3. If zero-cost also empty → retry without grammar (grammar-removal)
    4. If still empty → append one-shot example as nudge, retry with grammar
    5. If output is non-empty but invalid JSON: pass to SelfHealingParser
    6. If SelfHealingParser fails: re-prompt with one-shot example, retry once with grammar
    7. Track consecutive empty responses; after 2 consecutive empties, disable grammar for session
    8. When grammar is disabled, validate parsed action against registered tool names

    Args:
        config: Backend configuration.
        prompt: The assembled prompt text.
        system_text: System prompt text.
        grammar: GBNF grammar string or None.
        max_tokens: Maximum tokens to generate.
        on_token: Token streaming callback.
        self_healing_parser: SelfHealingParser instance for JSON repair.
        one_shot_example: One-shot JSON example for nudge prompts.
        registered_tools: Set of valid tool names for validation when grammar disabled.
        retry_state: Existing retry state (tracks consecutive empties across steps).
        previous_step_succeeded: If True and output is empty, short-circuit (no retries).
        parse_action_fn: Function to parse raw output into action dict. If None, uses
                         a basic JSON extraction fallback.

    Returns:
        Tuple of (raw_output, parsed_action, updated_retry_state).
        - raw_output: The raw model output string (may be None if all retries fail).
        - parsed_action: Parsed action dict if successful, None if parsing failed.
        - retry_state: Updated RetryState for tracking across steps.
    """
    if retry_state is None:
        retry_state = RetryState()

    if registered_tools is None:
        registered_tools = set(TOOL_SCHEMAS.keys())

    # Use provided parse_action or fall back to basic JSON extraction
    _parse_action = parse_action_fn or _basic_parse_action

    # If grammar was disabled due to consecutive empties, don't use it
    effective_grammar = None if retry_state.grammar_disabled else grammar

    # --- Step 1: Generate with grammar ---
    output = generate(
        config, prompt, max_tokens=max_tokens,
        system_text=system_text, on_token=on_token,
        grammar=effective_grammar,
    )

    # Check for empty/whitespace output
    if not output or not output.strip():
        retry_state.consecutive_empties += 1

        # --- SHORT-CIRCUIT: previous step succeeded → model is responsive ---
        # Empty output = prompt issue, not generation failure. Skip retries.
        if previous_step_succeeded:
            logger.debug(
                "Short-circuit: previous step succeeded, skipping retries",
                context={"consecutive_empties": retry_state.consecutive_empties},
            )
            # Check grammar disable threshold
            if retry_state.consecutive_empties >= 2:
                retry_state.grammar_disabled = True
                logger.warn(
                    f"Grammar disabled after {retry_state.consecutive_empties} consecutive empty responses"
                )
            return None, None, retry_state

        logger.debug(
            "Empty output with grammar, attempting zero-cost recovery",
            context={"consecutive_empties": retry_state.consecutive_empties},
        )

        # --- Step 2: ZERO-COST RECOVERY (temp bump or seed change) ---
        # Re-send same prompt with slightly different sampling params.
        # No grammar recompilation, no prompt modification → near-zero cost.
        zero_cost_output = _zero_cost_recovery(
            config, prompt, system_text, effective_grammar, max_tokens, on_token
        )

        if zero_cost_output and zero_cost_output.strip():
            # Zero-cost recovery succeeded - reset empties and parse
            output = zero_cost_output
            retry_state.consecutive_empties = 0
        else:
            # Zero-cost also empty - count toward threshold
            retry_state.consecutive_empties += 1
            logger.debug(
                "Zero-cost recovery also empty, retrying without grammar",
                context={"consecutive_empties": retry_state.consecutive_empties},
            )

            # --- Step 3: Retry without grammar (grammar-removal) ---
            output = generate(
                config, prompt, max_tokens=max_tokens,
                system_text=system_text, on_token=on_token,
                grammar=None,
            )

            if not output or not output.strip():
                logger.debug(
                    "Third empty output, retrying with nudge prompt",
                    context={"consecutive_empties": retry_state.consecutive_empties},
                )

                # --- Step 4: Nudge with one-shot example, retry with grammar ---
                nudge_prompt = (
                    f"{prompt}\n\n"
                    f"You MUST output a JSON action. Example: {one_shot_example}\n"
                    f"Output JSON:"
                )
                output = generate(
                    config, nudge_prompt, max_tokens=max_tokens,
                    system_text=system_text, on_token=on_token,
                    grammar=effective_grammar,
                )

                if not output or not output.strip():
                    # All retries exhausted for empty output
                    if retry_state.consecutive_empties >= 2:
                        retry_state.grammar_disabled = True
                        logger.warn(
                            f"Grammar disabled after {retry_state.consecutive_empties} consecutive empty responses"
                        )
                    return None, None, retry_state

            # If we got output after retry, check if grammar should be disabled
            if retry_state.consecutive_empties >= 2:
                retry_state.grammar_disabled = True
                logger.warn(
                    f"Grammar disabled after {retry_state.consecutive_empties} consecutive empty responses"
                )

    # Got non-empty output - reset consecutive empties counter
    if output and output.strip():
        retry_state.consecutive_empties = 0

    # --- Step 5: Try parsing the output ---
    clean_output = _THINK_RE.sub("", output).strip() if output else ""

    if not clean_output:
        return output, None, retry_state

    # Try standard parse_action first
    action = _parse_action(output)

    if action is not None:
        # Validate tool name when grammar is disabled
        if retry_state.grammar_disabled and registered_tools:
            action_name = action.get("action", "")
            if action_name not in registered_tools:
                logger.warn(
                    f"Rejected unregistered tool '{action_name}' (grammar disabled)"
                )
                return output, None, retry_state
        return output, action, retry_state

    # --- Step 5 continued: Invalid JSON → SelfHealingParser ---
    if self_healing_parser is not None:
        healed_action, corrections = self_healing_parser.parse(clean_output)
        if healed_action and isinstance(healed_action, dict) and "action" in healed_action:
            # Validate tool name when grammar is disabled
            if retry_state.grammar_disabled and registered_tools:
                action_name = healed_action.get("action", "")
                if action_name not in registered_tools:
                    logger.warn(
                        f"Rejected unregistered tool '{action_name}' from healed output (grammar disabled)"
                    )
                    return output, None, retry_state
            if corrections:
                logger.debug(f"Self-healing applied: {corrections}")
            return output, healed_action, retry_state

    # --- Step 6: SelfHealingParser failed → re-prompt with one-shot example ---
    logger.debug("SelfHealingParser failed, re-prompting with one-shot example")
    reprompt = (
        f"{prompt}\n\n"
        f"Your previous output was invalid. You MUST output valid JSON.\n"
        f"Example: {one_shot_example}\n"
        f"Output JSON:"
    )
    output = generate(
        config, reprompt, max_tokens=max_tokens,
        system_text=system_text, on_token=on_token,
        grammar=effective_grammar,
    )

    if not output or not output.strip():
        return None, None, retry_state

    # Try parsing the re-prompted output
    action = _parse_action(output)
    if action is not None:
        # Validate tool name when grammar is disabled
        if retry_state.grammar_disabled and registered_tools:
            action_name = action.get("action", "")
            if action_name not in registered_tools:
                logger.warn(
                    f"Rejected unregistered tool '{action_name}' after re-prompt (grammar disabled)"
                )
                return output, None, retry_state
        return output, action, retry_state

    # Final attempt: self-healing on re-prompted output
    if self_healing_parser is not None:
        clean_reprompt_output = _THINK_RE.sub("", output).strip()
        if clean_reprompt_output:
            healed_action, corrections = self_healing_parser.parse(clean_reprompt_output)
            if healed_action and isinstance(healed_action, dict) and "action" in healed_action:
                if retry_state.grammar_disabled and registered_tools:
                    action_name = healed_action.get("action", "")
                    if action_name not in registered_tools:
                        return output, None, retry_state
                return output, healed_action, retry_state

    return output, None, retry_state


def _zero_cost_recovery(
    config: Config,
    prompt: str,
    system_text: str,
    grammar: Optional[str],
    max_tokens: int,
    on_token=None,
) -> Optional[str]:
    """Attempt zero-cost recovery by bumping temperature or changing seed.

    Re-sends the same prompt with slightly different sampling parameters.
    No grammar recompilation, no prompt modification → near-zero additional cost.

    Strategy:
    - If temp > 0: bump seed by 1 (cheapest change)
    - If temp == 0: bump temp to 0.1 (minimal creativity injection)
    """
    import copy

    # Create a modified config for the recovery attempt
    recovery_config = copy.copy(config)

    if config.temp > 0:
        # Bump seed - cheapest possible change
        if config.seed is not None:
            recovery_config.seed = config.seed + 1
        else:
            # No seed set, bump temp slightly
            recovery_config.temp = config.temp + 0.1
    else:
        # temp == 0 (greedy) → add minimal temperature
        recovery_config.temp = 0.1

    logger.debug(
        "Zero-cost recovery attempt",
        context={
            "original_temp": config.temp,
            "recovery_temp": recovery_config.temp,
            "original_seed": config.seed,
            "recovery_seed": recovery_config.seed,
        },
    )

    return generate(
        recovery_config, prompt, max_tokens=max_tokens,
        system_text=system_text, on_token=on_token,
        grammar=grammar,
    )


def _basic_parse_action(text: str) -> Optional[dict[str, Any]]:
    """Basic JSON action extraction fallback when no parse_action_fn is provided.

    This is a minimal parser that extracts JSON objects with an "action" key.
    The full parse_action from agent.py should be passed as parse_action_fn
    for complete functionality (SEARCH/REPLACE blocks, narration detection, etc.).
    """
    import json

    # Strip think blocks
    clean = _THINK_RE.sub("", text).strip()
    if not clean:
        return None

    # Try to find a JSON object with "action" key
    # Scan for first { and find matching }
    start = clean.find("{")
    if start == -1:
        return None

    depth = 0
    for i in range(start, len(clean)):
        if clean[i] == "{":
            depth += 1
        elif clean[i] == "}":
            depth -= 1
            if depth == 0:
                json_str = clean[start:i + 1]
                try:
                    obj = json.loads(json_str)
                    if isinstance(obj, dict) and "action" in obj:
                        return obj
                except json.JSONDecodeError:
                    pass
                break

    return None


# Legacy alias for backward compatibility
_generate_with_retry = generate_with_retry
