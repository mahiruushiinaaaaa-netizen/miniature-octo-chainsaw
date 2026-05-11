"""
Unit tests for ObservationCompressor (Task 5.5).
Validates Requirements 12.1–12.6.
"""
import pytest
from mini_ai.core.communication import ObservationCompressor


@pytest.fixture
def compressor():
    return ObservationCompressor()


# ---------------------------------------------------------------------------
# Req 12.6: Pass through unmodified for outputs ≤ 1000 characters
# ---------------------------------------------------------------------------

class TestPassThrough:
    def test_short_output_preserved(self, compressor):
        output = "File created successfully at /tmp/test.py"
        result = compressor.compress("write_files", output, success=True)
        assert output in result
        assert "[WRITE_FILES] STATUS: success" in result

    def test_exactly_1000_chars_preserved(self, compressor):
        output = "x" * 1000
        result = compressor.compress("read_files", output, success=True)
        assert output in result

    def test_template_format_applied(self, compressor):
        output = "some output"
        result = compressor.compress("list_dir", output, success=False)
        assert result == "[LIST_DIR] STATUS: fail | KEY_INFO: some output"


# ---------------------------------------------------------------------------
# Req 12.1: Compress outputs > 1000 chars to ≤ 500 chars
# ---------------------------------------------------------------------------

class TestCompression:
    def test_large_output_compressed_to_max(self, compressor):
        output = "error: something failed\n" * 200  # well over 1000 chars
        result = compressor.compress("read_files", output, success=False)
        # The KEY_INFO portion should be ≤ 500 chars
        key_info = result.split("KEY_INFO: ", 1)[1]
        assert len(key_info) <= 500

    def test_output_over_threshold_gets_compressed(self, compressor):
        output = "a" * 1500  # over 1000, no error patterns
        result = compressor.compress("some_tool", output, success=True)
        key_info = result.split("KEY_INFO: ", 1)[1]
        assert len(key_info) <= 500


# ---------------------------------------------------------------------------
# Req 12.2: Structured template format
# ---------------------------------------------------------------------------

class TestTemplate:
    def test_success_template(self, compressor):
        result = compressor.compress("run_cmd", "ok", success=True)
        assert result.startswith("[RUN_CMD] STATUS: success | KEY_INFO:")

    def test_fail_template(self, compressor):
        result = compressor.compress("edit_blocks", "error", success=False)
        assert result.startswith("[EDIT_BLOCKS] STATUS: fail | KEY_INFO:")


# ---------------------------------------------------------------------------
# Req 12.3: run_cmd special handling (head + tail preservation)
# ---------------------------------------------------------------------------

class TestRunCmdTruncation:
    def test_run_cmd_large_output_keeps_head_and_tail(self, compressor):
        # Create output > 2000 chars
        head_content = "HEAD_" * 50  # 250 chars
        middle = "M" * 3000
        tail_content = "TAIL_" * 120  # 600 chars
        output = head_content + middle + tail_content
        
        result = compressor.compress("run_cmd", output, success=True)
        key_info = result.split("KEY_INFO: ", 1)[1]
        
        # Should contain head (first 200 chars)
        assert key_info.startswith(output[:200])
        # Should contain tail (last 500 chars)
        assert key_info.endswith(output[-500:])
        # Should contain truncation indicator
        assert "characters truncated" in key_info

    def test_run_cmd_truncation_count_correct(self, compressor):
        output = "x" * 5000
        result = compressor.compress("run_cmd", output, success=True)
        # Truncated count should be 5000 - 200 - 500 = 4300
        assert "4300 characters truncated" in result

    def test_run_cmd_under_2000_uses_generic_compression(self, compressor):
        # Between 1000 and 2000 chars - should use generic compression, not head/tail
        output = "error: file not found\n" * 80  # ~1760 chars
        result = compressor.compress("run_cmd", output, success=False)
        # Should still be compressed but not use head/tail format
        assert "characters truncated" not in result


# ---------------------------------------------------------------------------
# Req 12.4: Deduplication of consecutive identical observations
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_consecutive_duplicates_collapsed(self, compressor):
        obs = ["[RUN_CMD] STATUS: success | KEY_INFO: ok"] * 5
        result = compressor.deduplicate(obs)
        assert len(result) == 1
        assert "[repeated 5 times]" in result[0]

    def test_non_consecutive_duplicates_preserved(self, compressor):
        obs = ["A", "B", "A", "B"]
        result = compressor.deduplicate(obs)
        assert len(result) == 4
        assert result == ["A", "B", "A", "B"]

    def test_mixed_duplicates(self, compressor):
        obs = ["A", "A", "B", "B", "B", "C"]
        result = compressor.deduplicate(obs)
        assert len(result) == 3
        assert "[repeated 2 times]" in result[0]
        assert "[repeated 3 times]" in result[1]
        assert result[2] == "C"

    def test_empty_list(self, compressor):
        assert compressor.deduplicate([]) == []

    def test_single_item(self, compressor):
        result = compressor.deduplicate(["only one"])
        assert result == ["only one"]


# ---------------------------------------------------------------------------
# Req 12.5: Summarize old observations when history > 60% of budget
# ---------------------------------------------------------------------------

class TestSummarizeOld:
    def test_under_budget_returns_joined(self, compressor):
        obs = ["[RUN_CMD] STATUS: success | KEY_INFO: ok"] * 3
        # Budget is large enough that 60% won't be exceeded
        result = compressor.summarize_old(obs, budget_chars=10000)
        assert "[PROGRESS]" not in result
        assert "ok" in result

    def test_over_budget_summarizes_old(self, compressor):
        # Create observations that exceed 60% of a small budget
        obs = [
            "[READ_FILES] STATUS: success | KEY_INFO: content loaded",
            "[RUN_CMD] STATUS: fail | KEY_INFO: command not found",
            "[EDIT_BLOCKS] STATUS: success | KEY_INFO: file edited",
            "[LIST_DIR] STATUS: success | KEY_INFO: 10 files",
            "[RUN_CMD] STATUS: success | KEY_INFO: tests passed",
        ]
        # Set budget so total > 60% of budget (total / budget > 0.6)
        total = sum(len(o) for o in obs)
        budget = int(total / 0.7)  # total is 70% of budget, exceeds 60% threshold
        
        result = compressor.summarize_old(obs, budget_chars=budget)
        # Should have [PROGRESS] summary for old observations
        assert "[PROGRESS]" in result
        # Last 3 observations should be intact
        assert obs[-1] in result
        assert obs[-2] in result
        assert obs[-3] in result

    def test_summary_max_200_chars(self, compressor):
        # Many old observations to test 200 char limit
        obs = [f"[TOOL_{i}] STATUS: success | KEY_INFO: data" for i in range(50)]
        result = compressor.summarize_old(obs, budget_chars=100)
        # Extract the progress line
        lines = result.split("\n")
        progress_line = [l for l in lines if "[PROGRESS]" in l]
        assert len(progress_line) == 1
        assert len(progress_line[0]) <= 200

    def test_three_or_fewer_observations_not_summarized(self, compressor):
        obs = ["[RUN_CMD] STATUS: success | KEY_INFO: ok"] * 3
        result = compressor.summarize_old(obs, budget_chars=10)
        # Even with tiny budget, 3 or fewer obs are kept as-is
        assert "[PROGRESS]" not in result
