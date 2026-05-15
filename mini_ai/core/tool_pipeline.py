"""
tool_pipeline.py – Unified tool-calling pipeline for model output processing.

Processes model output through clear sequential stages, prioritizing JSON
extraction over narration detection. This fixes the bug where valid JSON
embedded in narration text was incorrectly dropped by heuristic checks.

Pipeline stages (in order):
  Stage 0: SEARCH/REPLACE block detection (edit_blocks) — highest priority
  Stage 1: JSON extraction via brace-matching scan for dict with "action" key
  Stage 2: Self-healing repair via SelfHealingParser if extraction fails
  Stage 3: Validate "action" field against registered tool schema names
  Stage 4: Narration heuristics — only checked AFTER JSON extraction AND self-healing fail
  Stage 5: If all stages fail, return None (no valid action)

Key design decisions:
  - JSON extraction runs BEFORE narration heuristics (fixes bug 1.9)
  - SelfHealingParser runs as Stage 2 (fixes bug 1.8)
  - First-attempt valid JSON executes immediately without overhead (Req 3.11)
  - Module is importable and callable without instantiating the full agent

Requirements: 1.1, 1.3, 1.4, 2.1, 2.8, 2.9, 3.5, 3.10, 3.11
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

from .logger import get_logger

if TYPE_CHECKING:
    from .self_healing import SelfHealingParser

logger = get_logger("tool_pipeline")

# Regex to strip <think>...</think> blocks from model output
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


@dataclass
class StageResult:
    """Result from a pipeline stage indicating success or failure."""
    success: bool
    action: Optional[dict[str, Any]] = None
    stage: str = ""
    detail: str = ""


def process_model_output(
    raw_output: str,
    tool_schemas: dict[str, Any],
    self_healing_parser: Optional["SelfHealingParser"] = None,
) -> Optional[dict[str, Any]]:
    """Process model output through the unified tool-calling pipeline.

    Single entry point for all model output parsing. Processes through
    sequential stages with explicit success-or-failure at each stage.

    Args:
        raw_output: Raw text output from the model.
        tool_schemas: Dict mapping tool names to their schemas (e.g., TOOL_SCHEMAS).
        self_healing_parser: Optional SelfHealingParser instance for JSON repair.

    Returns:
        Parsed action dict with "action" key if a valid tool call is found,
        or None if no valid action could be extracted.
    """
    if not raw_output or not raw_output.strip():
        return None

    # Strip reasoning/think blocks for parsing (keep raw_output intact for fallback)
    text = _THINK_RE.sub("", raw_output).strip()
    if not text:
        return None

    registered_tools = set(tool_schemas.keys()) if tool_schemas else set()

    # --- Stage 0: SEARCH/REPLACE blocks (highest priority) ---
    stage0_result = _stage_edit_blocks(text)
    if stage0_result.success:
        logger.debug("Stage 0 (edit_blocks): success")
        return stage0_result.action

    # --- Stage 1: JSON extraction via brace-matching ---
    stage1_result = _stage_json_extraction(text)
    if stage1_result.success:
        # Stage 3: Validate action name against registered tools
        action = stage1_result.action
        validation = _stage_validate_action(action, registered_tools)
        if validation.success:
            logger.debug("Stage 1 (JSON extraction) + Stage 3 (validation): success")
            return validation.action
        # If validation fails (unknown tool), still return the action
        # The executor will handle unknown tools appropriately
        logger.debug(
            f"Stage 1 success but Stage 3 validation note: {validation.detail}",
        )
        return action

    # --- Stage 2: Self-healing repair ---
    stage2_result = _stage_self_healing(text, self_healing_parser)
    if stage2_result.success:
        # Stage 3: Validate action name
        action = stage2_result.action
        validation = _stage_validate_action(action, registered_tools)
        if validation.success:
            logger.debug("Stage 2 (self-healing) + Stage 3 (validation): success")
            return validation.action
        logger.debug(
            f"Stage 2 success but Stage 3 validation note: {validation.detail}",
        )
        return action

    # --- Stage 4: Narration heuristics (ONLY after JSON extraction AND self-healing fail) ---
    # If the text looks like narration/planning, return None to force a nudge
    if _is_narration(text):
        logger.debug("Stage 4 (narration heuristics): detected narration, returning None")
        return None

    # --- Check for refusal patterns ---
    if _is_refusal(text):
        logger.debug("Refusal detected, returning None")
        return None

    # --- Check for failed action attempts ---
    # If it contains '{"action"' or '<<<<', parsing FAILED above — don't treat as answer
    if '{"action"' in text.replace(" ", "").replace('"', '') or "<<<<<<" in text:
        return None

    # --- Fallback: treat plain text as answer ---
    return {"action": "answer", "content": text.strip()}


# ---------------------------------------------------------------------------
# Pipeline Stages
# ---------------------------------------------------------------------------


def _stage_edit_blocks(text: str) -> StageResult:
    """Stage 0: Detect SEARCH/REPLACE blocks (highest priority).

    These blocks are the primary editing mechanism and take precedence
    over any JSON action in the same output.
    """
    # Lazy import to avoid circular dependency (agents → core → agents)
    try:
        from ..agents.coder import find_blocks
    except ImportError:
        # Fallback: inline minimal detection for SEARCH/REPLACE markers
        if "<<<<<<< SEARCH" in text and ">>>>>>> REPLACE" in text:
            # Can't parse without find_blocks, but signal that blocks exist
            return StageResult(
                success=False,
                stage="edit_blocks",
                detail="Edit blocks detected but coder module unavailable",
            )
        return StageResult(success=False, stage="edit_blocks", detail="No edit blocks found")

    blocks = find_blocks(text)
    if blocks:
        return StageResult(
            success=True,
            action={"action": "edit_blocks", "blocks": blocks},
            stage="edit_blocks",
            detail=f"Found {len(blocks)} edit block(s)",
        )
    return StageResult(success=False, stage="edit_blocks", detail="No edit blocks found")


def _stage_json_extraction(text: str) -> StageResult:
    """Stage 1: Extract JSON via brace-matching scan for dict with 'action' key.

    Scans for the first valid-looking JSON object with matching braces.
    Runs BEFORE narration heuristics to ensure valid JSON in narration is not dropped.
    """
    json_str = _try_extract_json(text)
    if json_str:
        json_str = json_str.strip()
        try:
            # Handle potential trailing commas or other minor issues
            json_str = re.sub(r',\s*\}', '}', json_str)
            json_str = re.sub(r',\s*\]', ']', json_str)
            obj = json.loads(json_str)
            if isinstance(obj, dict) and "action" in obj:
                return StageResult(
                    success=True,
                    action=obj,
                    stage="json_extraction",
                    detail="Valid JSON with action key extracted",
                )
        except json.JSONDecodeError:
            # Attempt basic repair for small models (single quotes)
            try:
                repaired = re.sub(r"\'(\w+)\'\s*:", r'"\1":', json_str)
                repaired = re.sub(r":\s*\'(.*?)\'", r': "\1"', repaired)
                obj = json.loads(repaired)
                if isinstance(obj, dict) and "action" in obj:
                    return StageResult(
                        success=True,
                        action=obj,
                        stage="json_extraction",
                        detail="JSON extracted after basic quote repair",
                    )
            except Exception:
                pass

    return StageResult(
        success=False,
        stage="json_extraction",
        detail="No valid JSON with action key found",
    )


def _stage_self_healing(
    text: str,
    self_healing_parser: Optional["SelfHealingParser"],
) -> StageResult:
    """Stage 2: Attempt self-healing repair via SelfHealingParser.

    Handles single quotes, trailing commas, backslash escaping, and
    Levenshtein ≤ 2 tool name correction.
    """
    if self_healing_parser is None:
        return StageResult(
            success=False,
            stage="self_healing",
            detail="No SelfHealingParser provided",
        )

    healed_action, corrections = self_healing_parser.parse(text)
    if healed_action and isinstance(healed_action, dict) and "action" in healed_action:
        detail = f"Healed with corrections: {corrections}" if corrections else "Parsed without corrections"
        return StageResult(
            success=True,
            action=healed_action,
            stage="self_healing",
            detail=detail,
        )

    return StageResult(
        success=False,
        stage="self_healing",
        detail=f"Self-healing failed: {corrections}" if corrections else "Self-healing returned None",
    )


def _stage_validate_action(
    action: Optional[dict[str, Any]],
    registered_tools: set[str],
) -> StageResult:
    """Stage 3: Validate 'action' field against registered tool schema names.

    Returns success if the action name is in the registered tools set.
    If registered_tools is empty, validation is skipped (always succeeds).
    """
    if action is None:
        return StageResult(success=False, stage="validation", detail="No action to validate")

    action_name = action.get("action", "")
    if not action_name:
        return StageResult(success=False, stage="validation", detail="Empty action name")

    # If no registered tools provided, skip validation
    if not registered_tools:
        return StageResult(
            success=True,
            action=action,
            stage="validation",
            detail="Validation skipped (no registered tools)",
        )

    if action_name in registered_tools:
        return StageResult(
            success=True,
            action=action,
            stage="validation",
            detail=f"Action '{action_name}' is registered",
        )

    return StageResult(
        success=False,
        action=action,  # Still return the action for caller to decide
        stage="validation",
        detail=f"Action '{action_name}' not in registered tools",
    )


# ---------------------------------------------------------------------------
# Helper Functions (moved from agent.py)
# ---------------------------------------------------------------------------


def _try_extract_json(text: str) -> Optional[str]:
    """Extract a potential JSON block via brace-matching scan.

    Scans for the first valid-looking JSON object with matching braces
    that contains an "action" key.
    """
    # Remove markdown fences
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)

    # Scan for first matching { } pair
    stack = 0
    start = -1
    for i, char in enumerate(text):
        if char == '{':
            if stack == 0:
                start = i
            stack += 1
        elif char == '}':
            stack -= 1
            if stack == 0 and start != -1:
                candidate = text[start:i + 1]
                try:
                    # Basic validation: must be a dict with 'action'
                    obj = json.loads(candidate)
                    if isinstance(obj, dict) and "action" in obj:
                        return candidate
                except json.JSONDecodeError:
                    # Attempt repairs in order: trailing commas, single quotes, backslashes
                    repaired = candidate
                    # Fix trailing commas
                    repaired = re.sub(r',\s*\}', '}', repaired)
                    repaired = re.sub(r',\s*\]', ']', repaired)
                    try:
                        obj = json.loads(repaired)
                        if isinstance(obj, dict) and "action" in obj:
                            return repaired
                    except (json.JSONDecodeError, ValueError):
                        pass
                    # Fix single quotes → double quotes (common with small models)
                    try:
                        repaired = re.sub(r"'(\w+)'\s*:", r'"\1":', candidate)
                        repaired = re.sub(r":\s*'(.*?)'", r': "\1"', repaired)
                        # Also fix single-quoted array elements
                        repaired = re.sub(r"\[\s*'(.*?)'\s*\]", r'["\1"]', repaired)
                        obj = json.loads(repaired)
                        if isinstance(obj, dict) and "action" in obj:
                            return repaired
                    except (json.JSONDecodeError, ValueError):
                        pass
                    # Fix Windows paths (single backslashes)
                    try:
                        repaired = re.sub(r'\\(?![\\"/bfnrtu])', r'\\\\', candidate)
                        obj = json.loads(repaired)
                        if isinstance(obj, dict) and "action" in obj:
                            return repaired
                    except (json.JSONDecodeError, ValueError):
                        pass
                    # Not valid JSON or missing 'action', keep looking
                    pass

    # Fallback: scan for any { } block using regex (non-greedy)
    matches = re.findall(r'\{[^{}]*\}', text)
    for match in matches:
        try:
            obj = json.loads(match)
            if isinstance(obj, dict) and "action" in obj:
                return match
        except (json.JSONDecodeError, ValueError):
            continue

    return None


def _is_narration(text: str) -> bool:
    """Detect narration/planning text that should NOT be treated as an answer.

    IMPORTANT: This is only checked AFTER JSON extraction and self-healing
    both fail. Valid JSON embedded in narration is handled by earlier stages.
    """
    lowered = text.lower()
    return any(p in lowered for p in (
        "i will", "first,", "step 1", "i'll", "next steps", "planning to",
        "let's", "i need to", "running a ", "i am going to", "let me ",
        "searching", "finding", "executing", "i'm here to",
        "goal:", "user goal:", "history:", "tools (json):",
        "you are mini ai", "### rules:"
    ))


def _is_refusal(text: str) -> bool:
    """Detect if the model is refusing a request.

    Only checks the first few hundred chars to avoid false positives
    in large tool outputs or plans.
    """
    snippet = text[:400].lower()
    return any(phrase in snippet for phrase in (
        "can't assist", "cannot assist", "can't help", "cannot help", "unable to help",
        "i'm sorry, but i cannot", "as an ai, i cannot", "i cannot directly",
        "i can't directly", "i do not have the ability", "i don't have access",
        "i cannot access", "i can't access", "unable to access",
        "i cannot manipulate", "i can't manipulate", "cannot modify files",
        "i'm sorry, but i can't", "i am not able to", "i'm not able to"
    ))


# ---------------------------------------------------------------------------
# Convenience: parse_action (drop-in replacement for agent.py's parse_action)
# ---------------------------------------------------------------------------


def parse_action(
    text: str,
    tool_schemas: Optional[dict[str, Any]] = None,
    self_healing_parser: Optional["SelfHealingParser"] = None,
) -> Optional[dict[str, Any]]:
    """Parse model output for tool actions — drop-in replacement for agent.py's parse_action.

    This is a convenience wrapper around process_model_output that provides
    backward compatibility with the original parse_action signature.

    Args:
        text: Raw model output text.
        tool_schemas: Optional tool schemas dict. If None, uses TOOL_SCHEMAS.
        self_healing_parser: Optional SelfHealingParser for JSON repair.

    Returns:
        Parsed action dict or None.
    """
    if tool_schemas is None:
        from .schemas import TOOL_SCHEMAS
        tool_schemas = TOOL_SCHEMAS

    return process_model_output(text, tool_schemas, self_healing_parser)
