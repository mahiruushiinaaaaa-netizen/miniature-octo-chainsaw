"""
test_task_result.py – Unit tests for TaskResult structured result object.

Validates Requirements 3.4, 3.5:
- TaskResult dataclass with success, output, tool_name, exit_code fields
- JSON serialization/deserialization
- Graceful fallback when JSON parse fails or "success" field missing
- Orchestrator uses structured result instead of string matching
"""
import json
import pytest
import importlib.util
import sys
import os

# Direct import of task_result module without triggering agents/__init__.py
_task_result_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "mini_ai", "agents", "task_result.py"
)
_spec = importlib.util.spec_from_file_location("mini_ai.agents.task_result", _task_result_path)
_module = importlib.util.module_from_spec(_spec)
sys.modules["mini_ai.agents.task_result"] = _module
_spec.loader.exec_module(_module)
TaskResult = _module.TaskResult


class TestTaskResultDataclass:
    """Test TaskResult creation and field access."""

    def test_success_result(self):
        r = TaskResult(success=True, output="Task completed", tool_name="answer")
        assert r.success is True
        assert r.output == "Task completed"
        assert r.tool_name == "answer"
        assert r.exit_code is None

    def test_failure_result(self):
        r = TaskResult(success=False, output="Error occurred", tool_name="run_cmd", exit_code=1)
        assert r.success is False
        assert r.output == "Error occurred"
        assert r.tool_name == "run_cmd"
        assert r.exit_code == 1

    def test_minimal_result(self):
        r = TaskResult(success=True, output="")
        assert r.success is True
        assert r.output == ""
        assert r.tool_name is None
        assert r.exit_code is None


class TestTaskResultSerialization:
    """Test JSON serialization round-trip."""

    def test_to_json_success(self):
        r = TaskResult(success=True, output="Done", tool_name="answer")
        j = r.to_json()
        data = json.loads(j)
        assert data["success"] is True
        assert data["output"] == "Done"
        assert data["tool_name"] == "answer"
        assert data["exit_code"] is None

    def test_to_json_failure(self):
        r = TaskResult(success=False, output="Failed: timeout", exit_code=124)
        j = r.to_json()
        data = json.loads(j)
        assert data["success"] is False
        assert data["output"] == "Failed: timeout"
        assert data["exit_code"] == 124

    def test_round_trip(self):
        original = TaskResult(success=True, output="hello world", tool_name="answer", exit_code=0)
        restored = TaskResult.from_json(original.to_json())
        assert restored.success == original.success
        assert restored.output == original.output
        assert restored.tool_name == original.tool_name
        assert restored.exit_code == original.exit_code


class TestTaskResultFromJson:
    """Test JSON parsing with graceful fallback."""

    def test_valid_json_success(self):
        raw = json.dumps({"success": True, "output": "All good"})
        r = TaskResult.from_json(raw)
        assert r.success is True
        assert r.output == "All good"

    def test_valid_json_failure(self):
        raw = json.dumps({"success": False, "output": "Something broke"})
        r = TaskResult.from_json(raw)
        assert r.success is False
        assert r.output == "Something broke"

    def test_missing_success_field_treated_as_failure(self):
        """If 'success' field is missing, treat as failure with raw output."""
        raw = json.dumps({"output": "some text", "tool_name": "run_cmd"})
        r = TaskResult.from_json(raw)
        assert r.success is False
        assert r.output == raw  # raw string preserved

    def test_invalid_json_treated_as_failure(self):
        """If JSON parse fails, treat as failure with raw string as output."""
        raw = "This is not JSON at all"
        r = TaskResult.from_json(raw)
        assert r.success is False
        assert r.output == raw

    def test_empty_string_treated_as_failure(self):
        r = TaskResult.from_json("")
        assert r.success is False
        assert r.output == ""

    def test_non_dict_json_treated_as_failure(self):
        """JSON array or primitive should be treated as failure."""
        raw = json.dumps([1, 2, 3])
        r = TaskResult.from_json(raw)
        assert r.success is False
        assert r.output == raw

    def test_success_message_with_failed_word_not_misclassified(self):
        """Key test: 'failed' in output should NOT cause false failure.
        
        This is the exact bug that string matching caused:
        'the test that previously failed now passes' was classified as failure.
        With structured results, success is determined by the boolean field.
        """
        raw = json.dumps({
            "success": True,
            "output": "the test that previously failed now passes"
        })
        r = TaskResult.from_json(raw)
        assert r.success is True  # NOT affected by 'failed' in output text

    def test_error_message_with_success_true(self):
        """Output containing 'error' doesn't override the success field."""
        raw = json.dumps({
            "success": True,
            "output": "Fixed the error in line 42"
        })
        r = TaskResult.from_json(raw)
        assert r.success is True

    def test_str_returns_json(self):
        r = TaskResult(success=True, output="test")
        s = str(r)
        data = json.loads(s)
        assert data["success"] is True
        assert data["output"] == "test"


class TestOrchestratorIntegration:
    """Test that orchestrator-style parsing works correctly."""

    def test_orchestrator_reads_success_directly(self):
        """Simulate orchestrator parsing agent_mode result."""
        # agent_mode returns JSON string
        agent_result = json.dumps({"success": True, "output": "Task done", "tool_name": "answer", "exit_code": None})
        
        # Orchestrator parses it
        task_result = TaskResult.from_json(agent_result)
        success = task_result.success
        
        assert success is True

    def test_orchestrator_handles_failure(self):
        agent_result = json.dumps({"success": False, "output": "Reached max steps."})
        task_result = TaskResult.from_json(agent_result)
        assert task_result.success is False

    def test_orchestrator_handles_legacy_string(self):
        """If somehow a raw string is returned (backward compat), treat as failure."""
        agent_result = "Some raw text without JSON structure"
        task_result = TaskResult.from_json(agent_result)
        assert task_result.success is False
        assert task_result.output == agent_result

    def test_no_string_matching_needed(self):
        """Verify that success determination doesn't depend on output content."""
        # These messages would have been misclassified by string matching
        tricky_messages = [
            "the test that previously failed now passes",
            "Fixed the error handling in auth module",
            "Resolved the failed connection issue",
            "Error messages are now properly formatted",
            "The previously failed tests all pass now",
        ]
        for msg in tricky_messages:
            raw = json.dumps({"success": True, "output": msg})
            r = TaskResult.from_json(raw)
            assert r.success is True, f"Message '{msg}' should be success but was classified as failure"
