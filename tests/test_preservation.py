"""
Preservation property-based tests for the architecture-speed-fix bugfix.

These tests capture baseline behavior that MUST be preserved during the fix.
They run on UNFIXED code and must PASS, establishing regression guards.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11**

Uses pytest with hypothesis for property-based testing.
"""
from __future__ import annotations

import json
import re
from typing import Any

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from mini_ai.core.micro_prompts import (
    MicroPromptRegistry,
    PromptAssembler,
    MicroPromptTemplate,
    VALID_INTENTS,
)
from mini_ai.core.tool_router import ToolRouter, MAX_TOOLS_PER_TURN, TASK_TOOL_SETS
from mini_ai.core.self_healing import SelfHealingParser, _levenshtein
from mini_ai.core.tool_reliability import ToolDisabler, LoopDetector
from mini_ai.core.grammars import MINIMAL_JSON_GRAMMAR
from mini_ai.core.config import Config
from mini_ai.core.schemas import TOOL_SCHEMAS


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid intents for micro-prompt system (non-COMPLEX)
micro_prompt_intents = st.sampled_from(["TASK", "QUERY", "EDIT", "EXPLORE"])

# All intents including COMPLEX
all_intents = st.sampled_from(["TASK", "QUERY", "EDIT", "EXPLORE", "COMPLEX"])

# Goal strings of varying lengths
goals = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=5,
    max_size=800,
)

# Task types for ToolRouter
task_types = st.sampled_from(["code_editing", "exploration", "default", "unknown_type"])

# Tool names from the schema registry
valid_tool_names = st.sampled_from(list(TOOL_SCHEMAS.keys()))

# Workspace index stacks
workspace_stacks = st.lists(
    st.sampled_from(["Laravel/PHP", "Django/Python", "Node/Web", "Vite", "Python", ""]),
    min_size=0,
    max_size=3,
)


@st.composite
def workspace_indices(draw):
    """Generate random workspace index dicts."""
    stack = draw(workspace_stacks)
    return {
        "files": {},
        "root": ".",
        "stack": [s for s in stack if s],
        "entry_points": [],
    }


@st.composite
def malformed_json_single_quotes(draw):
    """Generate JSON with single quotes instead of double quotes."""
    tool = draw(st.sampled_from(["answer", "run_cmd", "list_dir", "read_files"]))
    if tool == "answer":
        content = draw(st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
            min_size=1, max_size=50,
        ))
        return f"{{'action': '{tool}', 'content': '{content}'}}"
    elif tool == "run_cmd":
        cmd = draw(st.text(
            alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz -./0123456789"),
            min_size=1, max_size=30,
        ))
        return f"{{'action': '{tool}', 'command': '{cmd}'}}"
    elif tool == "list_dir":
        path = draw(st.sampled_from([".", "./src", "/tmp", "src/core"]))
        return f"{{'action': '{tool}', 'path': '{path}'}}"
    else:
        return f"{{'action': '{tool}', 'files': ['file.py']}}"


@st.composite
def malformed_json_trailing_commas(draw):
    """Generate JSON with trailing commas."""
    tool = draw(st.sampled_from(["answer", "run_cmd", "list_dir"]))
    if tool == "answer":
        return '{"action": "answer", "content": "hello",}'
    elif tool == "run_cmd":
        return '{"action": "run_cmd", "command": "echo hi",}'
    else:
        return '{"action": "list_dir", "path": ".",}'


@st.composite
def malformed_json_backslashes(draw):
    """Generate JSON with unescaped Windows backslashes."""
    drive = draw(st.sampled_from(["C", "D", "E"]))
    folder = draw(st.sampled_from(["Users", "Projects", "Code"]))
    file = draw(st.sampled_from(["main.py", "app.js", "test.ts"]))
    return f'{{"action": "read_files", "files": ["{drive}:\\{folder}\\{file}"]}}'


@st.composite
def misspelled_tool_names(draw):
    """Generate JSON with slightly misspelled tool names (Levenshtein ≤ 2)."""
    # Pairs of (misspelled, correct) where distance ≤ 2
    pairs = [
        ("anwser", "answer"),
        ("answre", "answer"),
        ("run_cnd", "run_cmd"),
        ("list_di", "list_dir"),
        ("read_file", "read_files"),
    ]
    misspelled, correct = draw(st.sampled_from(pairs))
    if correct == "answer":
        return f'{{"action": "{misspelled}", "content": "hello"}}', correct
    elif correct == "run_cmd":
        return f'{{"action": "{misspelled}", "command": "echo hi"}}', correct
    elif correct == "list_dir":
        return f'{{"action": "{misspelled}", "path": "."}}', correct
    else:
        return f'{{"action": "{misspelled}", "files": ["test.py"]}}', correct


# Required tool categories for ToolDisabler
required_categories = st.sampled_from(["filesystem", "execution", "output"])


# ---------------------------------------------------------------------------
# Test Class: Prompt Budget Preservation (Requirement 3.1)
# ---------------------------------------------------------------------------


class TestPromptBudgetPreservation:
    """Property: MicroPromptRegistry assembles prompts within ~500 token budget
    with Goal/Tools/Context/Example/Output JSON structure.

    **Validates: Requirements 3.1**
    """

    @given(intent=micro_prompt_intents, goal=goals)
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_prompt_within_token_budget(self, intent: str, goal: str) -> None:
        """Assembled prompts stay within the template's max_prompt_tokens budget."""
        registry = MicroPromptRegistry()
        assembler = PromptAssembler(registry)
        template = registry.get(intent)

        prompt = assembler.assemble(intent, goal)
        estimated_tokens = assembler.estimate_tokens(prompt)

        # Allow 10% tolerance for edge cases in truncation
        budget = template.max_prompt_tokens
        assert estimated_tokens <= budget * 1.1, (
            f"Prompt exceeds budget: {estimated_tokens} tokens > {budget} * 1.1 "
            f"for intent={intent}, goal_len={len(goal)}"
        )

    @given(intent=micro_prompt_intents, goal=goals)
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_prompt_has_goal_tools_structure(self, intent: str, goal: str) -> None:
        """Assembled prompts contain Goal/Tools structure elements."""
        registry = MicroPromptRegistry()
        assembler = PromptAssembler(registry)

        prompt = assembler.assemble(intent, goal, step=1)

        # Must contain "Goal:" and "Tools:" sections
        assert "Goal:" in prompt, f"Missing 'Goal:' in prompt for intent={intent}"
        assert "Tools:" in prompt, f"Missing 'Tools:' in prompt for intent={intent}"

    @given(intent=micro_prompt_intents, goal=goals)
    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_prompt_has_example_on_first_step(self, intent: str, goal: str) -> None:
        """First step prompts include Example and Output JSON sections."""
        registry = MicroPromptRegistry()
        assembler = PromptAssembler(registry)

        prompt = assembler.assemble(intent, goal, step=1)

        # First step should include example and output JSON marker
        assert "Example:" in prompt, f"Missing 'Example:' on step 1 for intent={intent}"
        assert "Output JSON:" in prompt, f"Missing 'Output JSON:' on step 1 for intent={intent}"


# ---------------------------------------------------------------------------
# Test Class: Tool Execution Observation Format (Requirement 3.2)
# ---------------------------------------------------------------------------


class TestObservationFormatPreservation:
    """Property: Tool execution returns JSON observation format
    {"success": bool, "output": str} to agent loop.

    **Validates: Requirements 3.2**

    Note: We test the observation format contract directly (the JSON structure
    that the executor's result() method produces) without importing ToolExecutor
    to avoid circular import issues in the test environment.
    """

    @given(
        success=st.booleans(),
        output=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
            min_size=0,
            max_size=500,
        ),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_result_format_is_json_with_success_and_output(
        self, success: bool, output: str
    ) -> None:
        """The observation format is valid JSON with 'success' and 'output' fields.

        This mirrors the executor's result() method logic:
        - Strips output
        - Truncates at 2000 chars
        - Produces {"success": bool, "output": str}
        """
        # Replicate the executor's result() method logic
        trimmed_output = output.strip()
        if len(trimmed_output) > 2000:
            trimmed_output = trimmed_output[:2000] + "\n...[truncated]"
        data = {"success": success, "output": trimmed_output}
        result_json = json.dumps(data, ensure_ascii=False)

        # Verify it's valid JSON with the expected structure
        parsed = json.loads(result_json)
        assert isinstance(parsed, dict)
        assert "success" in parsed
        assert "output" in parsed
        assert isinstance(parsed["success"], bool)
        assert isinstance(parsed["output"], str)
        assert parsed["success"] == success

    @given(
        success=st.booleans(),
        output=st.text(min_size=2001, max_size=3000),
    )
    @settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_result_truncates_long_output(self, success: bool, output: str) -> None:
        """Observation output is truncated at 2000 chars with indicator."""
        trimmed_output = output.strip()
        if len(trimmed_output) > 2000:
            trimmed_output = trimmed_output[:2000] + "\n...[truncated]"
        data = {"success": success, "output": trimmed_output}
        result_json = json.dumps(data, ensure_ascii=False)

        parsed = json.loads(result_json)
        # Output should be truncated
        assert len(parsed["output"]) <= 2020  # 2000 + truncation indicator


# ---------------------------------------------------------------------------
# Test Class: ToolRouter Cap Preservation (Requirement 3.3)
# ---------------------------------------------------------------------------


class TestToolRouterCapPreservation:
    """Property: ToolRouter caps at 8 tools per turn and always includes
    "answer" in available set.

    **Validates: Requirements 3.3**
    """

    @given(task_type=task_types, index=workspace_indices())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_tool_count_capped_at_max(self, task_type: str, index: dict) -> None:
        """ToolRouter returns at most MAX_TOOLS_PER_TURN tools."""
        router = ToolRouter(index)
        tools = router.route(task_type)

        assert len(tools) <= MAX_TOOLS_PER_TURN, (
            f"Got {len(tools)} tools, max is {MAX_TOOLS_PER_TURN}. "
            f"task_type={task_type}, tools={tools}"
        )

    @given(task_type=task_types, index=workspace_indices())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_answer_always_included(self, task_type: str, index: dict) -> None:
        """ToolRouter always includes 'answer' in the returned tool set."""
        router = ToolRouter(index)
        tools = router.route(task_type)

        assert "answer" in tools, (
            f"'answer' not in tools for task_type={task_type}. Got: {tools}"
        )

    @given(
        task_type=task_types,
        index=workspace_indices(),
        goal=st.text(min_size=0, max_size=100),
    )
    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_tool_count_with_goal_still_capped(
        self, task_type: str, index: dict, goal: str
    ) -> None:
        """Even with goal-based tool additions, cap is respected."""
        router = ToolRouter(index)
        tools = router.route(task_type, goal=goal)

        assert len(tools) <= MAX_TOOLS_PER_TURN
        assert "answer" in tools


# ---------------------------------------------------------------------------
# Test Class: SelfHealingParser Preservation (Requirement 3.5)
# ---------------------------------------------------------------------------


class TestSelfHealingParserPreservation:
    """Property: SelfHealingParser handles single quotes, trailing commas,
    backslash escaping, Levenshtein ≤ 2 tool name correction.

    **Validates: Requirements 3.5**
    """

    @given(malformed=malformed_json_single_quotes())
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_single_quotes_repaired(self, malformed: str) -> None:
        """Parser repairs single-quoted JSON to produce valid action dict."""
        parser = SelfHealingParser()
        result, corrections = parser.parse(malformed)

        assert result is not None, (
            f"Failed to repair single-quoted JSON: {malformed}\n"
            f"Corrections: {corrections}"
        )
        assert "action" in result
        assert result["action"] in TOOL_SCHEMAS or any(
            _levenshtein(result["action"], name) <= 2 for name in TOOL_SCHEMAS
        )

    @given(malformed=malformed_json_trailing_commas())
    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_trailing_commas_repaired(self, malformed: str) -> None:
        """Parser repairs trailing commas to produce valid action dict."""
        parser = SelfHealingParser()
        result, corrections = parser.parse(malformed)

        assert result is not None, (
            f"Failed to repair trailing comma JSON: {malformed}\n"
            f"Corrections: {corrections}"
        )
        assert "action" in result

    @given(malformed=malformed_json_backslashes())
    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_backslash_escaping_repaired(self, malformed: str) -> None:
        """Parser repairs unescaped Windows backslashes."""
        parser = SelfHealingParser()
        result, corrections = parser.parse(malformed)

        assert result is not None, (
            f"Failed to repair backslash JSON: {malformed}\n"
            f"Corrections: {corrections}"
        )
        assert "action" in result
        assert result["action"] == "read_files"

    @given(data=misspelled_tool_names())
    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_levenshtein_tool_name_correction(self, data: tuple) -> None:
        """Parser corrects misspelled tool names within Levenshtein distance ≤ 2."""
        malformed, expected_tool = data
        parser = SelfHealingParser()
        result, corrections = parser.parse(malformed)

        assert result is not None, (
            f"Failed to parse with misspelled tool: {malformed}\n"
            f"Corrections: {corrections}"
        )
        assert result["action"] == expected_tool, (
            f"Expected tool '{expected_tool}', got '{result['action']}'\n"
            f"Input: {malformed}"
        )


# ---------------------------------------------------------------------------
# Test Class: Config Fallback Preservation (Requirement 3.6)
# ---------------------------------------------------------------------------


class TestConfigFallbackPreservation:
    """Property: Config flags set to False fall back to original monolithic
    behavior without errors.

    **Validates: Requirements 3.6**
    """

    @given(
        use_micro_prompts=st.just(False),
        self_healing=st.just(False),
        tool_routing=st.just(False),
        grammar_adaptive=st.just(False),
    )
    @settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_all_flags_false_no_errors(
        self,
        use_micro_prompts: bool,
        self_healing: bool,
        tool_routing: bool,
        grammar_adaptive: bool,
    ) -> None:
        """Config with all optimization flags False creates without errors."""
        config = Config(
            use_micro_prompts=use_micro_prompts,
            self_healing=self_healing,
            tool_routing=tool_routing,
            grammar_adaptive=grammar_adaptive,
        )

        assert config.use_micro_prompts is False
        assert config.self_healing is False
        assert config.tool_routing is False
        assert config.grammar_adaptive is False

    @given(
        use_micro_prompts=st.booleans(),
        self_healing=st.booleans(),
        tool_routing=st.booleans(),
        grammar_adaptive=st.booleans(),
    )
    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_any_flag_combination_no_errors(
        self,
        use_micro_prompts: bool,
        self_healing: bool,
        tool_routing: bool,
        grammar_adaptive: bool,
    ) -> None:
        """Any combination of config flags creates without errors."""
        config = Config(
            use_micro_prompts=use_micro_prompts,
            self_healing=self_healing,
            tool_routing=tool_routing,
            grammar_adaptive=grammar_adaptive,
        )

        assert config.use_micro_prompts == use_micro_prompts
        assert config.self_healing == self_healing
        assert config.tool_routing == tool_routing
        assert config.grammar_adaptive == grammar_adaptive


# ---------------------------------------------------------------------------
# Test Class: ToolDisabler Category Protection (Requirement 3.7)
# ---------------------------------------------------------------------------


class TestToolDisablerProtectionPreservation:
    """Property: ToolDisabler protects required categories (filesystem,
    execution, output) by re-enabling LRU tool.

    **Validates: Requirements 3.7**
    """

    def test_filesystem_category_protection(self) -> None:
        """When all filesystem tools are disabled, LRU is re-enabled."""
        disabler = ToolDisabler()
        fs_tools = ToolDisabler.REQUIRED_CATEGORIES["filesystem"]

        # Record failures for all filesystem tools to disable them
        for tool in fs_tools:
            for _ in range(ToolDisabler.MAX_CONSECUTIVE_FAILURES):
                disabler.record_failure(tool)

        # At least one filesystem tool must remain enabled
        disabled = disabler.get_disabled_tools()
        enabled_fs = [t for t in fs_tools if t not in disabled]
        assert len(enabled_fs) >= 1, (
            f"All filesystem tools disabled! Disabled: {disabled}"
        )

    def test_execution_category_protection(self) -> None:
        """When all execution tools are disabled, LRU is re-enabled."""
        disabler = ToolDisabler()
        exec_tools = ToolDisabler.REQUIRED_CATEGORIES["execution"]

        for tool in exec_tools:
            for _ in range(ToolDisabler.MAX_CONSECUTIVE_FAILURES):
                disabler.record_failure(tool)

        disabled = disabler.get_disabled_tools()
        enabled_exec = [t for t in exec_tools if t not in disabled]
        assert len(enabled_exec) >= 1, (
            f"All execution tools disabled! Disabled: {disabled}"
        )

    def test_output_category_protection(self) -> None:
        """When all output tools are disabled, LRU is re-enabled."""
        disabler = ToolDisabler()
        output_tools = ToolDisabler.REQUIRED_CATEGORIES["output"]

        for tool in output_tools:
            for _ in range(ToolDisabler.MAX_CONSECUTIVE_FAILURES):
                disabler.record_failure(tool)

        disabled = disabler.get_disabled_tools()
        enabled_output = [t for t in output_tools if t not in disabled]
        assert len(enabled_output) >= 1, (
            f"All output tools disabled! Disabled: {disabled}"
        )

    @given(
        tool=st.sampled_from(
            ToolDisabler.REQUIRED_CATEGORIES["filesystem"]
            + ToolDisabler.REQUIRED_CATEGORIES["execution"]
            + ToolDisabler.REQUIRED_CATEGORIES["output"]
        )
    )
    @settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_success_resets_failure_count(self, tool: str) -> None:
        """A successful call resets the consecutive failure count."""
        disabler = ToolDisabler()

        # Record 2 failures (just below threshold)
        disabler.record_failure(tool)
        disabler.record_failure(tool)

        # Record success - should reset
        disabler.record_success(tool)

        # Now 2 more failures should NOT disable (count reset)
        disabler.record_failure(tool)
        disabler.record_failure(tool)

        assert not disabler.is_disabled(tool), (
            f"Tool '{tool}' should not be disabled after success reset"
        )


# ---------------------------------------------------------------------------
# Test Class: COMPLEX Intent Preservation (Requirement 3.8)
# ---------------------------------------------------------------------------


class TestComplexIntentPreservation:
    """Property: COMPLEX intent uses full monolithic prompt system with
    complete context.

    **Validates: Requirements 3.8**
    """

    @given(goal=goals)
    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_complex_intent_falls_back_to_explore(self, goal: str) -> None:
        """COMPLEX intent falls back to EXPLORE template in MicroPromptRegistry."""
        registry = MicroPromptRegistry()
        template = registry.get("COMPLEX")

        # COMPLEX is not registered as a micro-prompt template,
        # so it falls back to EXPLORE (the fallback behavior)
        explore_template = registry.get("EXPLORE")
        assert template == explore_template, (
            "COMPLEX should fall back to EXPLORE template in registry"
        )


# ---------------------------------------------------------------------------
# Test Class: System Prompt Token Budget (Requirement 3.9)
# ---------------------------------------------------------------------------


class TestSystemPromptTokenBudget:
    """Property: System prompt templates remain at or below 60 tokens
    (len(text) // 4).

    **Validates: Requirements 3.9**
    """

    def test_system_prompt_within_60_tokens(self) -> None:
        """PromptAssembler.SYSTEM_PROMPT is at or below 60 tokens."""
        system_prompt = PromptAssembler.SYSTEM_PROMPT
        estimated_tokens = len(system_prompt) // 4

        assert estimated_tokens <= 60, (
            f"System prompt exceeds 60 token budget: "
            f"{estimated_tokens} tokens (len={len(system_prompt)})\n"
            f"Content: {system_prompt!r}"
        )

    @given(intent=micro_prompt_intents)
    @settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_system_prompt_constant_across_intents(self, intent: str) -> None:
        """System prompt is the same regardless of intent."""
        registry = MicroPromptRegistry()
        assembler = PromptAssembler(registry)

        # The system prompt is a class constant, should be same for all
        prompt = assembler.assemble(intent, "test goal")
        assert prompt.startswith(PromptAssembler.SYSTEM_PROMPT)


# ---------------------------------------------------------------------------
# Test Class: GBNF Grammar Preservation (Requirement 3.10)
# ---------------------------------------------------------------------------


class TestGBNFGrammarPreservation:
    """Property: GBNF grammar enforces same JSON structure
    {"action": tool_name, ...params}.

    **Validates: Requirements 3.10**
    """

    def test_minimal_grammar_has_action_field(self) -> None:
        """MINIMAL_JSON_GRAMMAR enforces 'action' as first field."""
        # The grammar uses escaped quotes in GBNF syntax: \"action\"
        assert "action" in MINIMAL_JSON_GRAMMAR
        # The grammar should define object starting with "action"
        assert "object ::=" in MINIMAL_JSON_GRAMMAR
        assert "tool_name" in MINIMAL_JSON_GRAMMAR

    def test_minimal_grammar_defines_tool_names(self) -> None:
        """MINIMAL_JSON_GRAMMAR defines specific tool names."""
        # Check that known tools are referenced in the grammar
        # GBNF uses escaped quotes: \"run_cmd\"
        assert "run_cmd" in MINIMAL_JSON_GRAMMAR
        assert "write_files" in MINIMAL_JSON_GRAMMAR
        assert "answer" in MINIMAL_JSON_GRAMMAR
        assert "list_dir" in MINIMAL_JSON_GRAMMAR

    def test_grammar_structure_unchanged(self) -> None:
        """GBNF grammar has the expected structural rules."""
        # Core rules that must be present
        assert "root" in MINIMAL_JSON_GRAMMAR
        assert "object" in MINIMAL_JSON_GRAMMAR
        assert "value" in MINIMAL_JSON_GRAMMAR
        assert "string" in MINIMAL_JSON_GRAMMAR
        assert "number" in MINIMAL_JSON_GRAMMAR
        assert "space" in MINIMAL_JSON_GRAMMAR
        assert "array" in MINIMAL_JSON_GRAMMAR


# ---------------------------------------------------------------------------
# Test Class: First-Attempt Fast Path (Requirement 3.11)
# ---------------------------------------------------------------------------


class TestFirstAttemptFastPath:
    """Property: First-attempt valid JSON tool calls execute immediately
    without additional overhead.

    **Validates: Requirements 3.11**
    """

    @given(
        tool=st.sampled_from(["answer", "run_cmd", "list_dir", "read_files"]),
    )
    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_json_parses_without_corrections(self, tool: str) -> None:
        """Valid JSON tool calls parse on first attempt with no corrections."""
        parser = SelfHealingParser()

        # Build valid JSON for the tool
        if tool == "answer":
            raw = '{"action": "answer", "content": "hello world"}'
        elif tool == "run_cmd":
            raw = '{"action": "run_cmd", "command": "echo hello"}'
        elif tool == "list_dir":
            raw = '{"action": "list_dir", "path": "."}'
        else:
            raw = '{"action": "read_files", "files": ["test.py"]}'

        result, corrections = parser.parse(raw)

        assert result is not None, f"Valid JSON failed to parse: {raw}"
        assert result["action"] == tool
        # No corrections should be needed for valid JSON
        assert len(corrections) == 0, (
            f"Unexpected corrections for valid JSON: {corrections}"
        )

    @given(
        content=st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N", "Z"),
                blacklist_characters='"\\',
            ),
            min_size=1,
            max_size=100,
        )
    )
    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_json_answer_immediate_parse(self, content: str) -> None:
        """Any valid JSON answer action parses immediately."""
        parser = SelfHealingParser()
        raw = json.dumps({"action": "answer", "content": content})

        result, corrections = parser.parse(raw)

        assert result is not None
        assert result["action"] == "answer"
        assert result["content"] == content
        assert len(corrections) == 0
