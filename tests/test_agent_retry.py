"""
Tests for the retry logic in agent.py (_generate_with_retry and RetryState).

Validates Requirements: 8.1, 8.3, 8.4, 8.5, 8.6, 5.6, 5.7, 9.5
"""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock
from typing import Optional

import pytest

from mini_ai.core.retry import generate_with_retry as _generate_with_retry, RetryState
from mini_ai.core.self_healing import SelfHealingParser
from mini_ai.core.schemas import TOOL_SCHEMAS


@pytest.fixture
def mock_config():
    """Create a minimal mock config for testing."""
    config = MagicMock()
    config.model = "test-model"
    config.temp = 0.7
    config.ctx = 4096
    config.grammar_adaptive = False
    config.streaming_parse = False
    return config


@pytest.fixture
def registered_tools():
    """Set of registered tool names."""
    return set(TOOL_SCHEMAS.keys())


class TestRetryState:
    """Tests for the RetryState dataclass."""

    def test_initial_state(self):
        state = RetryState()
        assert state.consecutive_empties == 0
        assert state.grammar_disabled is False

    def test_state_tracks_empties(self):
        state = RetryState()
        state.consecutive_empties = 2
        assert state.consecutive_empties == 2

    def test_grammar_disabled_flag(self):
        state = RetryState()
        state.grammar_disabled = True
        assert state.grammar_disabled is True


class TestGenerateWithRetryEmptyOutput:
    """Tests for retry on empty model output (Req 8.3, 8.4)."""

    @patch("mini_ai.core.retry.generate")
    def test_retry_without_grammar_on_first_empty(self, mock_generate, mock_config):
        """On empty output with grammar: zero-cost recovery then retry without grammar (Req 8.3)."""
        # New flow: grammar → zero-cost recovery → no-grammar → nudge
        # First call returns empty (with grammar), zero-cost also empty, third (no grammar) returns valid
        mock_generate.side_effect = [
            "",  # First call with grammar → empty
            "",  # Zero-cost recovery (temp bump) → empty
            '{"action": "run_cmd", "cmd": "echo hello"}',  # Retry without grammar → success
        ]

        output, action, state = _generate_with_retry(
            config=mock_config,
            prompt="test prompt",
            system_text="system",
            grammar="some_grammar",
            max_tokens=256,
        )

        assert action is not None
        assert action["action"] == "run_cmd"
        # 3 calls: original + zero-cost + no-grammar
        assert mock_generate.call_count == 3
        # Third call (no-grammar retry) should have grammar=None
        assert mock_generate.call_args_list[2][1].get("grammar") is None

    @patch("mini_ai.core.retry.generate")
    def test_nudge_prompt_on_second_empty(self, mock_generate, mock_config):
        """On all retries empty: nudge with one-shot example (Req 8.4)."""
        # New flow: grammar → zero-cost → no-grammar → nudge
        mock_generate.side_effect = [
            "",  # First call → empty
            "",  # Zero-cost recovery → empty
            "",  # Retry without grammar → empty
            '{"action": "answer", "content": "done"}',  # Nudge retry → success
        ]

        output, action, state = _generate_with_retry(
            config=mock_config,
            prompt="test prompt",
            system_text="system",
            grammar="some_grammar",
            max_tokens=256,
            one_shot_example='{"action": "answer", "content": "done"}',
        )

        assert action is not None
        assert action["action"] == "answer"
        assert mock_generate.call_count == 4
        # Fourth call should include the nudge prompt with one-shot example
        fourth_call_prompt = mock_generate.call_args_list[3][1].get("prompt") or mock_generate.call_args_list[3][0][1]
        assert "Example:" in fourth_call_prompt or "Output JSON:" in fourth_call_prompt

    @patch("mini_ai.core.retry.generate")
    def test_all_retries_exhausted_returns_none(self, mock_generate, mock_config):
        """When all retries produce empty output, returns None."""
        mock_generate.return_value = ""

        output, action, state = _generate_with_retry(
            config=mock_config,
            prompt="test prompt",
            system_text="system",
            grammar="some_grammar",
            max_tokens=256,
        )

        assert output is None
        assert action is None
        # New flow: original + zero-cost + no-grammar + nudge = 4 calls
        assert mock_generate.call_count == 4


class TestGenerateWithRetryGrammarDisable:
    """Tests for grammar disable after consecutive empties (Req 5.6)."""

    @patch("mini_ai.core.retry.generate")
    def test_grammar_disabled_after_2_consecutive_empties(self, mock_generate, mock_config):
        """After 2 consecutive empties, grammar is disabled for session (Req 5.6)."""
        mock_generate.return_value = ""

        state = RetryState()
        _, _, state = _generate_with_retry(
            config=mock_config,
            prompt="test prompt",
            system_text="system",
            grammar="some_grammar",
            max_tokens=256,
            retry_state=state,
        )

        # After all retries fail, consecutive_empties should be >= 2
        assert state.grammar_disabled is True

    @patch("mini_ai.core.retry.generate")
    def test_grammar_not_used_when_disabled(self, mock_generate, mock_config):
        """When grammar is disabled, generate is called without grammar."""
        mock_generate.return_value = '{"action": "answer", "content": "hi"}'

        state = RetryState(consecutive_empties=2, grammar_disabled=True)
        output, action, state = _generate_with_retry(
            config=mock_config,
            prompt="test prompt",
            system_text="system",
            grammar="some_grammar",
            max_tokens=256,
            retry_state=state,
        )

        assert action is not None
        # First call should have grammar=None since grammar_disabled=True
        first_call_kwargs = mock_generate.call_args_list[0][1]
        assert first_call_kwargs.get("grammar") is None


class TestGenerateWithRetrySelfHealing:
    """Tests for SelfHealingParser integration (Req 8.5, 8.6)."""

    @patch("mini_ai.core.retry.generate")
    def test_invalid_json_passed_to_self_healing(self, mock_generate, mock_config):
        """Invalid JSON despite grammar is passed to SelfHealingParser (Req 8.5)."""
        # Output looks like a failed JSON action attempt (parse_action returns None for these)
        mock_generate.return_value = 'I will now {"action": "run_cmd"'  # Contains "I will" → parse_action returns None

        mock_parser = MagicMock()
        mock_parser.parse.return_value = (
            {"action": "run_cmd", "cmd": "echo hi"},
            ["fixed missing brace"],
        )

        output, action, state = _generate_with_retry(
            config=mock_config,
            prompt="test prompt",
            system_text="system",
            grammar="some_grammar",
            max_tokens=256,
            self_healing_parser=mock_parser,
        )

        assert action is not None
        assert action["action"] == "run_cmd"
        mock_parser.parse.assert_called_once()

    @patch("mini_ai.core.retry.generate")
    def test_self_healing_failure_triggers_reprompt(self, mock_generate, mock_config):
        """SelfHealingParser failure triggers re-prompt with one-shot (Req 8.6)."""
        # First generate returns output that parse_action returns None for (narration pattern)
        # Re-prompt returns valid output
        mock_generate.side_effect = [
            "I will run the command now to check the status",  # Contains "I will" → None
            '{"action": "answer", "content": "fixed"}',
        ]

        mock_parser = MagicMock()
        mock_parser.parse.return_value = (None, [])  # Parser fails

        output, action, state = _generate_with_retry(
            config=mock_config,
            prompt="test prompt",
            system_text="system",
            grammar="some_grammar",
            max_tokens=256,
            self_healing_parser=mock_parser,
            one_shot_example='{"action": "answer", "content": "example"}',
        )

        assert action is not None
        assert action["action"] == "answer"
        # Should have called generate twice (original + re-prompt)
        assert mock_generate.call_count == 2
        # Re-prompt should contain the one-shot example
        reprompt_call = mock_generate.call_args_list[1]
        reprompt_text = reprompt_call[1].get("prompt") or reprompt_call[0][1]
        assert "Example:" in reprompt_text


class TestGenerateWithRetryToolValidation:
    """Tests for tool name validation when grammar is disabled (Req 9.5)."""

    @patch("mini_ai.core.retry.generate")
    def test_unregistered_tool_rejected_when_grammar_disabled(self, mock_generate, mock_config):
        """Unregistered tool names are rejected when grammar is disabled (Req 9.5)."""
        mock_generate.return_value = '{"action": "fake_tool", "param": "value"}'

        state = RetryState(grammar_disabled=True)
        registered = {"run_cmd", "answer", "list_dir"}

        output, action, state = _generate_with_retry(
            config=mock_config,
            prompt="test prompt",
            system_text="system",
            grammar="some_grammar",
            max_tokens=256,
            retry_state=state,
            registered_tools=registered,
            self_healing_parser=MagicMock(parse=MagicMock(return_value=(None, []))),
        )

        # Action should be None because "fake_tool" is not registered
        assert action is None

    @patch("mini_ai.core.retry.generate")
    def test_registered_tool_accepted_when_grammar_disabled(self, mock_generate, mock_config):
        """Registered tool names are accepted when grammar is disabled (Req 9.5)."""
        mock_generate.return_value = '{"action": "run_cmd", "cmd": "echo hi"}'

        state = RetryState(grammar_disabled=True)
        registered = {"run_cmd", "answer", "list_dir"}

        output, action, state = _generate_with_retry(
            config=mock_config,
            prompt="test prompt",
            system_text="system",
            grammar="some_grammar",
            max_tokens=256,
            retry_state=state,
            registered_tools=registered,
        )

        assert action is not None
        assert action["action"] == "run_cmd"

    @patch("mini_ai.core.retry.generate")
    def test_tool_validation_not_applied_when_grammar_enabled(self, mock_generate, mock_config):
        """Tool validation is NOT applied when grammar is still enabled."""
        # When grammar is enabled, the grammar itself constrains tool names
        mock_generate.return_value = '{"action": "answer", "content": "hi"}'

        state = RetryState(grammar_disabled=False)
        registered = {"run_cmd", "list_dir"}  # "answer" not in this set

        output, action, state = _generate_with_retry(
            config=mock_config,
            prompt="test prompt",
            system_text="system",
            grammar="some_grammar",
            max_tokens=256,
            retry_state=state,
            registered_tools=registered,
        )

        # Should still accept because grammar is enabled (grammar handles validation)
        assert action is not None
        assert action["action"] == "answer"


class TestGenerateWithRetryConsecutiveReset:
    """Tests for consecutive empty counter reset on success."""

    @patch("mini_ai.core.retry.generate")
    def test_consecutive_empties_reset_on_success(self, mock_generate, mock_config):
        """Consecutive empties counter resets when valid output is received."""
        mock_generate.return_value = '{"action": "answer", "content": "done"}'

        state = RetryState(consecutive_empties=1)
        _, _, state = _generate_with_retry(
            config=mock_config,
            prompt="test prompt",
            system_text="system",
            grammar="some_grammar",
            max_tokens=256,
            retry_state=state,
        )

        assert state.consecutive_empties == 0

        assert state.consecutive_empties == 0


class TestShortCircuit:
    """Tests for short-circuit when previous step succeeded (Req 2.7, 3.1)."""

    @patch("mini_ai.core.retry.generate")
    def test_short_circuit_on_empty_when_previous_succeeded(self, mock_generate, mock_config):
        """When previous_step_succeeded=True and output is empty, return immediately."""
        mock_generate.return_value = ""  # Empty output

        output, action, state = _generate_with_retry(
            config=mock_config,
            prompt="test prompt",
            system_text="system",
            grammar="some_grammar",
            max_tokens=256,
            previous_step_succeeded=True,
        )

        # Should short-circuit: only 1 generate call (no retries)
        assert mock_generate.call_count == 1
        assert output is None
        assert action is None

    @patch("mini_ai.core.retry.generate")
    def test_no_short_circuit_when_previous_failed(self, mock_generate, mock_config):
        """When previous_step_succeeded=False, normal retry flow applies."""
        mock_generate.return_value = ""  # All empty

        output, action, state = _generate_with_retry(
            config=mock_config,
            prompt="test prompt",
            system_text="system",
            grammar="some_grammar",
            max_tokens=256,
            previous_step_succeeded=False,
        )

        # Should NOT short-circuit: full retry flow (4 calls with zero-cost)
        assert mock_generate.call_count == 4
        assert output is None
        assert action is None

    @patch("mini_ai.core.retry.generate")
    def test_short_circuit_tracks_consecutive_empties(self, mock_generate, mock_config):
        """Short-circuit still increments consecutive_empties counter."""
        mock_generate.return_value = ""

        state = RetryState(consecutive_empties=0)
        _, _, state = _generate_with_retry(
            config=mock_config,
            prompt="test prompt",
            system_text="system",
            grammar="some_grammar",
            max_tokens=256,
            previous_step_succeeded=True,
            retry_state=state,
        )

        assert state.consecutive_empties == 1

    @patch("mini_ai.core.retry.generate")
    def test_short_circuit_disables_grammar_at_threshold(self, mock_generate, mock_config):
        """Short-circuit disables grammar when consecutive_empties reaches 2."""
        mock_generate.return_value = ""

        state = RetryState(consecutive_empties=1)  # Already at 1
        _, _, state = _generate_with_retry(
            config=mock_config,
            prompt="test prompt",
            system_text="system",
            grammar="some_grammar",
            max_tokens=256,
            previous_step_succeeded=True,
            retry_state=state,
        )

        # Should be at 2 now and grammar disabled
        assert state.consecutive_empties == 2
        assert state.grammar_disabled is True

    @patch("mini_ai.core.retry.generate")
    def test_no_short_circuit_when_output_not_empty(self, mock_generate, mock_config):
        """Short-circuit only applies when output is empty."""
        mock_generate.return_value = '{"action": "answer", "content": "hi"}'

        output, action, state = _generate_with_retry(
            config=mock_config,
            prompt="test prompt",
            system_text="system",
            grammar="some_grammar",
            max_tokens=256,
            previous_step_succeeded=True,
        )

        # Output is not empty, so short-circuit doesn't apply
        assert action is not None
        assert action["action"] == "answer"


class TestZeroCostRecovery:
    """Tests for zero-cost recovery (temp bump / seed change) before expensive retries."""

    @patch("mini_ai.core.retry.generate")
    def test_zero_cost_recovery_succeeds(self, mock_generate, mock_config):
        """Zero-cost recovery (temp bump) succeeds on second attempt."""
        mock_generate.side_effect = [
            "",  # First call → empty
            '{"action": "run_cmd", "command": "ls"}',  # Zero-cost recovery → success
        ]

        output, action, state = _generate_with_retry(
            config=mock_config,
            prompt="test prompt",
            system_text="system",
            grammar="some_grammar",
            max_tokens=256,
        )

        assert action is not None
        assert action["action"] == "run_cmd"
        # Only 2 calls: original + zero-cost recovery (no grammar-removal or nudge needed)
        assert mock_generate.call_count == 2

    @patch("mini_ai.core.retry.generate")
    def test_zero_cost_recovery_uses_temp_bump(self, mock_generate, mock_config):
        """Zero-cost recovery bumps temperature when temp is 0."""
        mock_config.temp = 0.0
        mock_config.seed = None
        mock_generate.side_effect = [
            "",  # First call → empty
            '{"action": "answer", "content": "ok"}',  # Zero-cost → success
        ]

        output, action, state = _generate_with_retry(
            config=mock_config,
            prompt="test prompt",
            system_text="system",
            grammar="some_grammar",
            max_tokens=256,
        )

        assert action is not None
        # Second call should use a modified config with temp=0.1
        second_call = mock_generate.call_args_list[1]
        recovery_config = second_call[0][0]  # First positional arg is config
        assert recovery_config.temp == 0.1

    @patch("mini_ai.core.retry.generate")
    def test_zero_cost_recovery_uses_seed_bump(self, mock_generate, mock_config):
        """Zero-cost recovery bumps seed when temp > 0 and seed is set."""
        mock_config.temp = 0.7
        mock_config.seed = 42
        mock_generate.side_effect = [
            "",  # First call → empty
            '{"action": "answer", "content": "ok"}',  # Zero-cost → success
        ]

        output, action, state = _generate_with_retry(
            config=mock_config,
            prompt="test prompt",
            system_text="system",
            grammar="some_grammar",
            max_tokens=256,
        )

        assert action is not None
        # Second call should use seed=43
        second_call = mock_generate.call_args_list[1]
        recovery_config = second_call[0][0]
        assert recovery_config.seed == 43

    @patch("mini_ai.core.retry.generate")
    def test_zero_cost_empty_counts_toward_threshold(self, mock_generate, mock_config):
        """Both original empty and zero-cost empty count toward consecutive_empties."""
        mock_generate.return_value = ""  # All empty

        state = RetryState(consecutive_empties=0)
        _, _, state = _generate_with_retry(
            config=mock_config,
            prompt="test prompt",
            system_text="system",
            grammar="some_grammar",
            max_tokens=256,
            retry_state=state,
        )

        # Original empty (+1) + zero-cost empty (+1) = 2 → grammar disabled
        assert state.consecutive_empties >= 2
        assert state.grammar_disabled is True
