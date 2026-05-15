"""
test_tool_pipeline.py – Unit tests for the unified tool-calling pipeline.

Tests the pipeline stages independently and the full process_model_output flow.
Validates that JSON extraction runs BEFORE narration heuristics (bug fix 1.9)
and that SelfHealingParser integrates correctly as Stage 2 (bug fix 1.8).

Requirements: 1.1, 1.3, 1.4, 2.1, 2.8, 2.9, 3.5, 3.10, 3.11
"""
import pytest
from unittest.mock import MagicMock

from mini_ai.core.tool_pipeline import (
    process_model_output,
    parse_action,
    _stage_edit_blocks,
    _stage_json_extraction,
    _stage_self_healing,
    _stage_validate_action,
    _try_extract_json,
    _is_narration,
    _is_refusal,
    StageResult,
)


# --- Mock tool schemas for testing ---
MOCK_TOOL_SCHEMAS = {
    "run_cmd": MagicMock(name="run_cmd"),
    "write_files": MagicMock(name="write_files"),
    "read_files": MagicMock(name="read_files"),
    "list_dir": MagicMock(name="list_dir"),
    "answer": MagicMock(name="answer"),
    "web_search": MagicMock(name="web_search"),
    "edit_blocks": MagicMock(name="edit_blocks"),
}


class TestProcessModelOutput:
    """Tests for the main entry point: process_model_output."""

    def test_valid_json_action_returns_immediately(self):
        """First-attempt valid JSON executes immediately (Req 3.11)."""
        raw = '{"action": "run_cmd", "command": "echo hello"}'
        result = process_model_output(raw, MOCK_TOOL_SCHEMAS)
        assert result is not None
        assert result["action"] == "run_cmd"
        assert result["command"] == "echo hello"

    def test_json_in_narration_extracted_before_heuristics(self):
        """JSON extraction runs BEFORE narration detection (fixes bug 1.9)."""
        # This text contains "let me" which would trigger narration heuristic
        raw = 'Let me run this: {"action": "run_cmd", "command": "echo hi"}'
        result = process_model_output(raw, MOCK_TOOL_SCHEMAS)
        assert result is not None
        assert result["action"] == "run_cmd"
        assert result["command"] == "echo hi"

    def test_json_with_i_will_prefix_extracted(self):
        """JSON after 'I will' narration is still extracted."""
        raw = 'I will execute this command now: {"action": "run_cmd", "command": "ls"}'
        result = process_model_output(raw, MOCK_TOOL_SCHEMAS)
        assert result is not None
        assert result["action"] == "run_cmd"

    def test_json_with_step_prefix_extracted(self):
        """JSON after 'Step 1' narration is still extracted."""
        raw = 'Step 1: {"action": "list_dir", "path": "."}'
        result = process_model_output(raw, MOCK_TOOL_SCHEMAS)
        assert result is not None
        assert result["action"] == "list_dir"

    def test_empty_input_returns_none(self):
        """Empty input returns None."""
        assert process_model_output("", MOCK_TOOL_SCHEMAS) is None
        assert process_model_output("   ", MOCK_TOOL_SCHEMAS) is None
        assert process_model_output(None, MOCK_TOOL_SCHEMAS) is None

    def test_think_blocks_stripped(self):
        """<think> blocks are stripped before parsing."""
        raw = '<think>Let me think about this...</think>{"action": "answer", "content": "42"}'
        result = process_model_output(raw, MOCK_TOOL_SCHEMAS)
        assert result is not None
        assert result["action"] == "answer"
        assert result["content"] == "42"

    def test_pure_narration_returns_none(self):
        """Pure narration without JSON returns None (forces nudge)."""
        raw = "I will first check the directory structure and then create the file."
        result = process_model_output(raw, MOCK_TOOL_SCHEMAS)
        assert result is None

    def test_plain_text_treated_as_answer(self):
        """Plain text without narration markers is treated as answer."""
        raw = "The answer is 42."
        result = process_model_output(raw, MOCK_TOOL_SCHEMAS)
        assert result is not None
        assert result["action"] == "answer"
        assert result["content"] == "The answer is 42."

    def test_refusal_returns_none(self):
        """Refusal patterns return None."""
        raw = "I'm sorry, but I cannot access your files directly."
        result = process_model_output(raw, MOCK_TOOL_SCHEMAS)
        assert result is None

    def test_search_replace_blocks_highest_priority(self):
        """SEARCH/REPLACE blocks take priority over JSON."""
        raw = '''main.py
<<<<<<< SEARCH
    def hello():
        pass
=======
    def hello():
        print("World")
>>>>>>> REPLACE

{"action": "run_cmd", "command": "echo ignored"}'''
        result = process_model_output(raw, MOCK_TOOL_SCHEMAS)
        assert result is not None
        assert result["action"] == "edit_blocks"
        assert len(result["blocks"]) == 1

    def test_trailing_comma_handled(self):
        """Trailing commas in JSON are handled."""
        raw = '{"action": "run_cmd", "command": "echo hello",}'
        result = process_model_output(raw, MOCK_TOOL_SCHEMAS)
        assert result is not None
        assert result["action"] == "run_cmd"

    def test_markdown_fenced_json(self):
        """JSON in markdown code fences is extracted."""
        raw = '```json\n{"action": "run_cmd", "command": "echo hello"}\n```'
        result = process_model_output(raw, MOCK_TOOL_SCHEMAS)
        assert result is not None
        assert result["action"] == "run_cmd"

    def test_self_healing_parser_used_when_extraction_fails(self):
        """SelfHealingParser is invoked when JSON extraction fails (Stage 2)."""
        # Use input that Stage 1 cannot repair: no matching braces pattern
        # that would be recognized as JSON, but SelfHealingParser can handle
        raw = "action: run_cmd, command: echo hello"
        
        mock_parser = MagicMock()
        mock_parser.parse.return_value = (
            {"action": "run_cmd", "command": "echo hello"},
            ["reconstructed_from_text"],
        )
        
        result = process_model_output(raw, MOCK_TOOL_SCHEMAS, self_healing_parser=mock_parser)
        assert result is not None
        assert result["action"] == "run_cmd"
        mock_parser.parse.assert_called_once()

    def test_failed_action_attempt_with_search_markers_returns_none(self):
        """Text containing <<<<<<< markers returns None (failed edit attempt)."""
        raw = 'I tried to edit but <<<<<<< SEARCH was malformed'
        result = process_model_output(raw, MOCK_TOOL_SCHEMAS)
        assert result is None

    def test_unknown_tool_still_returned(self):
        """Unknown tool names are still returned (executor handles them)."""
        raw = '{"action": "unknown_tool", "param": "value"}'
        result = process_model_output(raw, MOCK_TOOL_SCHEMAS)
        assert result is not None
        assert result["action"] == "unknown_tool"


class TestStageJsonExtraction:
    """Tests for Stage 1: JSON extraction."""

    def test_simple_json(self):
        result = _stage_json_extraction('{"action": "run_cmd", "command": "ls"}')
        assert result.success
        assert result.action["action"] == "run_cmd"

    def test_json_with_surrounding_text(self):
        result = _stage_json_extraction('Here is the action: {"action": "answer", "content": "done"} end')
        assert result.success
        assert result.action["action"] == "answer"

    def test_no_json(self):
        result = _stage_json_extraction("Just plain text without any JSON")
        assert not result.success

    def test_json_without_action_key(self):
        result = _stage_json_extraction('{"name": "test", "value": 42}')
        assert not result.success

    def test_nested_json(self):
        raw = '{"action": "write_files", "files": {"test.py": "print(1)"}}'
        result = _stage_json_extraction(raw)
        assert result.success
        assert result.action["action"] == "write_files"

    def test_windows_path_backslashes(self):
        """Windows paths with backslashes are handled."""
        raw = r'{"action": "read_files", "files": ["C:\\Users\\test\\file.py"]}'
        result = _stage_json_extraction(raw)
        assert result.success
        assert result.action["action"] == "read_files"


class TestStageValidation:
    """Tests for Stage 3: Action validation."""

    def test_valid_action(self):
        action = {"action": "run_cmd", "command": "echo hi"}
        result = _stage_validate_action(action, {"run_cmd", "answer"})
        assert result.success
        assert result.action == action

    def test_invalid_action(self):
        action = {"action": "nonexistent_tool"}
        result = _stage_validate_action(action, {"run_cmd", "answer"})
        assert not result.success

    def test_empty_registered_tools_skips_validation(self):
        action = {"action": "anything"}
        result = _stage_validate_action(action, set())
        assert result.success

    def test_none_action(self):
        result = _stage_validate_action(None, {"run_cmd"})
        assert not result.success

    def test_empty_action_name(self):
        result = _stage_validate_action({"action": ""}, {"run_cmd"})
        assert not result.success


class TestStageSelfHealing:
    """Tests for Stage 2: Self-healing repair."""

    def test_no_parser_returns_failure(self):
        result = _stage_self_healing("some text", None)
        assert not result.success

    def test_parser_success(self):
        mock_parser = MagicMock()
        mock_parser.parse.return_value = (
            {"action": "run_cmd", "command": "ls"},
            ["single_quotes"],
        )
        result = _stage_self_healing("{'action': 'run_cmd'}", mock_parser)
        assert result.success
        assert result.action["action"] == "run_cmd"

    def test_parser_failure(self):
        mock_parser = MagicMock()
        mock_parser.parse.return_value = (None, ["parse error"])
        result = _stage_self_healing("garbage text", mock_parser)
        assert not result.success


class TestTryExtractJson:
    """Tests for the _try_extract_json helper."""

    def test_simple_extraction(self):
        result = _try_extract_json('{"action": "answer", "content": "hi"}')
        assert result is not None
        obj = json.loads(result)
        assert obj["action"] == "answer"

    def test_extraction_from_narration(self):
        """Key test: extracts JSON even when surrounded by narration."""
        text = 'I will now run: {"action": "run_cmd", "command": "echo test"} and wait'
        result = _try_extract_json(text)
        assert result is not None
        obj = json.loads(result)
        assert obj["action"] == "run_cmd"

    def test_markdown_fences_removed(self):
        text = '```json\n{"action": "list_dir", "path": "."}\n```'
        result = _try_extract_json(text)
        assert result is not None

    def test_no_action_key_returns_none(self):
        result = _try_extract_json('{"name": "test"}')
        assert result is None

    def test_empty_text(self):
        assert _try_extract_json("") is None
        assert _try_extract_json("no braces here") is None


class TestIsNarration:
    """Tests for narration detection heuristic."""

    def test_narration_patterns(self):
        assert _is_narration("I will check the files first")
        assert _is_narration("First, let me look at the code")
        assert _is_narration("Step 1: Read the file")
        assert _is_narration("Let me search for the function")
        assert _is_narration("I need to find the bug")

    def test_non_narration(self):
        assert not _is_narration("The answer is 42")
        assert not _is_narration("File created successfully")
        assert not _is_narration("Hello world")


class TestIsRefusal:
    """Tests for refusal detection."""

    def test_refusal_patterns(self):
        assert _is_refusal("I'm sorry, but I cannot access your files")
        assert _is_refusal("I can't assist with that request")
        assert _is_refusal("I don't have access to the filesystem")

    def test_non_refusal(self):
        assert not _is_refusal("Running the command now")
        assert not _is_refusal("Here is the file content")
        assert not _is_refusal('{"action": "run_cmd", "command": "ls"}')


class TestParseActionCompat:
    """Tests for the parse_action compatibility wrapper."""

    def test_basic_json(self):
        result = parse_action('{"action": "run_cmd", "command": "echo hi"}')
        assert result is not None
        assert result["action"] == "run_cmd"

    def test_narration_with_json(self):
        """Key regression test: narration + JSON should extract JSON."""
        result = parse_action('Let me run this: {"action": "run_cmd", "command": "echo hi"}')
        assert result is not None
        assert result["action"] == "run_cmd"

    def test_pure_narration(self):
        result = parse_action("I will first check the directory")
        assert result is None

    def test_empty(self):
        result = parse_action("")
        assert result is None


# Need json import for TestTryExtractJson
import json
