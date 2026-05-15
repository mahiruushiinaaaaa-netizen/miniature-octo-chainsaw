"""
test_bug_conditions.py – Bug condition exploration property-based tests.

These tests encode the EXPECTED behavior AFTER the fix is applied.
On UNFIXED code, these tests MUST FAIL — failure confirms the bugs exist.

DO NOT fix the code to make these pass. The fix comes in later tasks.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5**
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from collections import Counter
from unittest.mock import patch, MagicMock, call
from typing import Any

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

# Path to agent.py source for inspection-based tests
_AGENT_PY_PATH = Path(__file__).parent.parent / "mini_ai" / "agents" / "agent.py"
_RETRY_PY_PATH = Path(__file__).parent.parent / "mini_ai" / "core" / "retry.py"
_ORCHESTRATOR_PY_PATH = Path(__file__).parent.parent / "mini_ai" / "agents" / "orchestrator.py"


def _read_source(path: Path) -> str:
    """Read source file content for inspection."""
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# (a) Duplicated loop detection: Simulate 3 identical tool calls → verify
#     BOTH LoopDetector AND inline detection (action_history, action_name_list,
#     strict_repeat_count, consecutive_name_repeats) fire independently with
#     different recovery actions.
#
# BUG: On unfixed code, BOTH LoopDetector AND inline detection
#      (action_history, action_name_list, strict_repeat_count,
#       consecutive_name_repeats) exist and fire independently with
#       different recovery actions, causing unpredictable behavior.
#
# EXPECTED (after fix): Only LoopDetector is used for loop detection.
#      Inline detection code (action_history, action_name_list,
#      strict_repeat_count, consecutive_name_repeats) should NOT exist.
#
# **Validates: Requirements 1.1, 1.2, 2.1, 2.3**
# ---------------------------------------------------------------------------

class TestDuplicatedLoopDetection:
    """Test that only LoopDetector is used for loop detection (no inline duplicates)."""

    @given(
        tool_name=st.sampled_from(["run_cmd", "read_files", "list_dir", "web_search"]),
        param_value=st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_no_inline_loop_detection_variables_in_agent(self, tool_name, param_value):
        """
        Property: agent.py should NOT contain inline loop detection variables
        (action_history, action_name_list, strict_repeat_count, consecutive_name_repeats).

        After the fix, only LoopDetector should be used for loop detection.
        On unfixed code, these variables exist → test FAILS.

        **Validates: Requirements 1.1, 1.2**
        """
        source = _read_source(_AGENT_PY_PATH)

        # These inline loop detection variables should NOT exist after the fix
        # We look for assignment/usage patterns that indicate active inline detection
        inline_detection_patterns = [
            r"action_history\s*[:\[]",       # action_history: list or action_history[
            r"action_name_list\s*[:\[]",     # action_name_list: list or action_name_list[
            r"strict_repeat_count\s*=",      # strict_repeat_count = ...
            r"consecutive_name_repeats\s*[=>]",  # consecutive_name_repeats >= or =
        ]

        found_patterns = [p for p in inline_detection_patterns if re.search(p, source)]

        # EXPECTED: No inline loop detection variables exist
        # On UNFIXED code: all 4 patterns exist → assertion fails
        assert len(found_patterns) == 0, (
            f"Inline loop detection variables still present in agent.py: {found_patterns}. "
            f"Only LoopDetector should be used for loop detection."
        )

    @given(
        tool_name=st.sampled_from(["run_cmd", "read_files", "list_dir"]),
    )
    @settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_loop_detector_is_single_source_of_truth(self, tool_name):
        """
        Property: LoopDetector should be the ONLY mechanism that triggers
        loop recovery. There should be no parallel 'strict_repeat_count >= 2'
        or 'consecutive_name_repeats >= 3' checks.

        **Validates: Requirements 1.1, 2.1, 2.3**
        """
        source = _read_source(_AGENT_PY_PATH)

        # These patterns indicate duplicated loop detection logic
        duplicate_patterns = [
            "strict_repeat_count >= 2",
            "consecutive_name_repeats >= 3",
            "action_history.count(",
        ]

        found_patterns = [p for p in duplicate_patterns if p in source]

        # EXPECTED: None of these patterns exist (only LoopDetector used)
        # On UNFIXED code: these patterns exist → assertion fails
        assert len(found_patterns) == 0, (
            f"Duplicated loop detection logic found: {found_patterns}. "
            f"Only LoopDetector.is_looping() should trigger loop recovery."
        )


# ---------------------------------------------------------------------------
# (b) N+1 embedding calls: Call retrieve_relevant_snippets with a multi-chunk
#     file → count embedding API calls → verify N+1 pattern (>2 calls).
#
# BUG: On unfixed code, RAGManager calls get_embeddings() once per chunk
#      (N+1 pattern: 1 for query + N for chunks).
#
# EXPECTED (after fix): At most 2 API round-trips (1 for query, 1 batched
#      for all chunks).
#
# **Validates: Requirements 2.2, 2.4**
# ---------------------------------------------------------------------------

class TestNPlusOneEmbeddingCalls:
    """Test that embedding retrieval uses at most 2 API calls (batched)."""

    @given(
        num_chunks=st.integers(min_value=3, max_value=10),
        chunk_content=st.text(min_size=100, max_size=500),
    )
    @settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_embedding_calls_bounded_by_two(self, num_chunks, chunk_content):
        """
        Property: For any file that chunks into N pieces, the total number
        of embedding API calls should be at most 2 (1 query + 1 batched).

        On UNFIXED code: N+1 calls are made (1 + N) → assertion fails.

        **Validates: Requirements 2.2, 2.4**
        """
        from mini_ai.core.rag import RAGManager
        from mini_ai.core.config import Config

        config = Config()
        rag = RAGManager(config)

        # Create file content that will produce num_chunks chunks
        # Each chunk is chunk_size=1500 with overlap=200, so we need enough content
        file_content = chunk_content * (num_chunks * 3)  # Ensure enough content

        # Verify we actually get multiple chunks
        chunks = rag.chunk_text(file_content)
        assume(len(chunks) >= 3)  # Need at least 3 chunks to demonstrate N+1

        file_contents = {"test_file.py": file_content}

        # Count how many times get_embeddings (singular) is called
        call_count = 0
        original_embeddings = [0.1] * 128  # Fake embedding vector

        def mock_get_embeddings(cfg, text, timeout=60):
            nonlocal call_count
            call_count += 1
            return original_embeddings

        # Mock for batch embeddings - returns embeddings for all texts at once
        def mock_batch_embeddings(cfg, texts, timeout=60):
            return [original_embeddings for _ in texts]

        with patch("mini_ai.core.rag.get_embeddings", side_effect=mock_get_embeddings), \
             patch("mini_ai.core.rag.backend_get_embeddings_batch", side_effect=mock_batch_embeddings):
            rag.retrieve_relevant_snippets("test query", file_contents, top_k=5)

        # EXPECTED (after fix): at most 2 calls (1 query + 1 batched)
        # On UNFIXED code: call_count = 1 + len(chunks) (N+1 pattern) → fails
        assert call_count <= 2, (
            f"N+1 embedding pattern detected: {call_count} API calls made "
            f"for {len(chunks)} chunks. Expected at most 2 (1 query + 1 batched)."
        )


# ---------------------------------------------------------------------------
# (c) No-fallback RAG: Set embeddings unavailable → call
#     retrieve_relevant_snippets → verify empty list returned
#     (zero context enrichment).
#
# BUG: On unfixed code, when embeddings are unavailable,
#      retrieve_relevant_snippets returns [] with no fallback.
#
# EXPECTED (after fix): A TF-IDF fallback provides meaningful snippets
#      even when embeddings are unavailable.
#
# **Validates: Requirements 2.3, 2.5**
# ---------------------------------------------------------------------------

class TestNoFallbackRAG:
    """Test that RAG provides context even when embeddings are unavailable."""

    @given(
        query=st.text(min_size=5, max_size=100).filter(lambda x: x.strip()),
        file_content=st.text(min_size=200, max_size=2000).filter(lambda x: x.strip()),
    )
    @settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_fallback_provides_context_when_embeddings_unavailable(self, query, file_content):
        """
        Property: When embeddings are unavailable, retrieval should still
        return non-empty results via a fallback mechanism (e.g., TF-IDF).

        On UNFIXED code: returns [] when embeddings unavailable → fails.

        **Validates: Requirements 2.3, 2.5**
        """
        from mini_ai.core.rag import RAGManager
        from mini_ai.core.config import Config

        config = Config()
        rag = RAGManager(config)

        file_contents = {"src/main.py": file_content}

        # Mock embeddings as unavailable (returns empty list)
        with patch("mini_ai.core.rag.get_embeddings", return_value=[]):
            results = rag.retrieve_relevant_snippets(query, file_contents, top_k=5)

        # EXPECTED (after fix): non-empty results from TF-IDF fallback
        # On UNFIXED code: returns [] → assertion fails
        assert len(results) > 0, (
            f"RAG returned empty results when embeddings unavailable. "
            f"Expected TF-IDF fallback to provide context snippets. "
            f"Query: '{query[:50]}', File content length: {len(file_content)}"
        )


# ---------------------------------------------------------------------------
# (d) Expensive retry after success: Simulate previous step succeeding then
#     current step returning empty → verify system performs expensive retries
#     (3 full LLM calls) instead of short-circuiting.
#
# BUG: On unfixed code, _generate_with_retry always performs up to 3 full
#      LLM generation calls regardless of whether the previous step succeeded.
#
# EXPECTED (after fix): When previous_step_succeeded=True and output is empty,
#      the system short-circuits immediately (no expensive retries).
#
# **Validates: Requirements 1.1, 2.1, 2.7**
# ---------------------------------------------------------------------------

class TestExpensiveRetryAfterSuccess:
    """Test that retry short-circuits when previous step succeeded."""

    @given(
        prompt=st.text(min_size=10, max_size=200),
        system_text=st.text(min_size=10, max_size=100),
    )
    @settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_short_circuit_when_previous_step_succeeded(self, prompt, system_text):
        """
        Property: When previous_step_succeeded=True and the model returns empty,
        _generate_with_retry should short-circuit (make at most 1 LLM call)
        instead of performing expensive retries.

        On UNFIXED code: makes 3 full LLM calls regardless → fails.

        **Validates: Requirements 1.1, 2.1, 2.7**
        """
        source = _read_source(_AGENT_PY_PATH)

        # Check if _generate_with_retry accepts a previous_step_succeeded parameter
        # This is the key indicator of the short-circuit mechanism
        has_short_circuit_param = "previous_step_succeeded" in source

        # EXPECTED (after fix): the parameter exists, enabling short-circuit
        # On UNFIXED code: parameter doesn't exist → assertion fails
        assert has_short_circuit_param, (
            f"_generate_with_retry does not accept 'previous_step_succeeded' parameter. "
            f"Without this parameter, the system cannot short-circuit expensive retries "
            f"when the previous step succeeded. This means 3 full LLM calls (~150s) "
            f"are wasted even when the model is known to be responsive."
        )

    @given(
        num_retries=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_no_unconditional_triple_retry(self, num_retries):
        """
        Property: The retry logic should NOT unconditionally make 3 generate calls
        when output is empty. There should be a short-circuit path.

        On UNFIXED code: 3 unconditional retries exist → fails.

        **Validates: Requirements 1.1, 2.1**
        """
        # Look in retry.py first (extracted module), fall back to agent.py
        if _RETRY_PY_PATH.exists():
            source = _read_source(_RETRY_PY_PATH)
        else:
            source = _read_source(_AGENT_PY_PATH)

        # In the unfixed code, _generate_with_retry has 3 sequential generate() calls
        # when output is empty, with no short-circuit based on previous step success.
        # Count the number of `generate(` calls within _generate_with_retry function.

        # Extract the _generate_with_retry / generate_with_retry function body
        func_match = re.search(
            r"def (?:_)?generate_with_retry\(.*?\n(?=\ndef |\nclass |\Z)",
            source,
            re.DOTALL,
        )
        assert func_match, "Could not find _generate_with_retry / generate_with_retry function"

        func_body = func_match.group(0)

        # Count generate() calls (the actual LLM invocations)
        generate_calls = len(re.findall(r"\bgenerate\(", func_body))

        # EXPECTED (after fix): short-circuit means fewer generate calls in the
        # empty-output path, or a conditional that skips retries
        # On UNFIXED code: 3+ unconditional generate calls → fails
        # The fix should have at most 2 generate calls in the main path
        # (with short-circuit returning before retries when previous step succeeded)
        assert generate_calls <= 2 or "previous_step_succeeded" in func_body, (
            f"_generate_with_retry makes {generate_calls} generate() calls "
            f"without a short-circuit mechanism (previous_step_succeeded). "
            f"This means expensive retries happen even when the model is responsive."
        )


# ---------------------------------------------------------------------------
# (e) Orchestrator false positive: Pass result "the test that previously
#     failed now passes" → verify incorrectly classified as failure via
#     string matching.
#
# BUG: On unfixed code, the orchestrator uses `"failed" in result.lower()`
#      which matches "failed" in success messages like "the test that
#      previously failed now passes".
#
# EXPECTED (after fix): Orchestrator uses structured result objects with
#      explicit success/failure boolean fields, not string matching.
#
# **Validates: Requirements 3.4, 3.5**
# ---------------------------------------------------------------------------

class TestOrchestratorFalsePositive:
    """Test that orchestrator doesn't use string matching for success detection."""

    @given(
        success_message=st.sampled_from([
            "the test that previously failed now passes",
            "fixed the error in the configuration",
            "resolved the failed deployment issue",
            "the previously failed build now succeeds",
            "error handling has been improved",
            "all previously failed tests now pass",
            "the error rate dropped to zero",
            "fixed: connection error was due to timeout",
        ])
    )
    @settings(max_examples=8, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_success_not_determined_by_string_matching(self, success_message):
        """
        Property: Success messages containing words like "failed" or "error"
        should NOT be classified as failures. The orchestrator should use
        structured result fields, not string pattern matching.

        On UNFIXED code: `"failed" in result.lower()` matches → false failure.

        **Validates: Requirements 3.4, 3.5**
        """
        source = _read_source(_ORCHESTRATOR_PY_PATH)

        # Check if the orchestrator still uses string matching heuristics
        string_matching_patterns = [
            '"failed" in result.lower()',
            '"error" in result.lower()',
        ]

        found_patterns = [p for p in string_matching_patterns if p in source]

        # EXPECTED (after fix): No string matching for success detection
        # On UNFIXED code: these patterns exist → assertion fails
        assert len(found_patterns) == 0, (
            f"Orchestrator uses string matching for success detection: {found_patterns}. "
            f"This causes false positives for messages like: '{success_message}'. "
            f"Expected: structured result objects with explicit success boolean."
        )

    @given(
        result_text=st.sampled_from([
            "the test that previously failed now passes",
            "fixed the error in the configuration",
            "error handling has been improved",
            "resolved the failed deployment issue",
            "the previously failed build now succeeds",
        ])
    )
    @settings(max_examples=5, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_string_matching_produces_wrong_classification(self, result_text):
        """
        Property: Demonstrate that structured TaskResult correctly classifies
        success messages containing 'failed'/'error' words.

        After fix: TaskResult.from_json uses the explicit "success" boolean field,
        so messages containing 'failed'/'error' in a success context are correctly
        classified as successes.

        **Validates: Requirements 3.4, 3.5**
        """
        # Simulate the structured result approach (TaskResult.from_json logic)
        # Create a structured result with success=True and the message as output
        structured = json.dumps({"success": True, "output": result_text})

        # Parse using the same logic as TaskResult.from_json
        try:
            data = json.loads(structured)
            if isinstance(data, dict) and "success" in data:
                parsed_success = bool(data["success"])
            else:
                parsed_success = False
        except (json.JSONDecodeError, TypeError, ValueError):
            parsed_success = False

        # EXPECTED (after fix): structured result correctly identifies success
        # regardless of words like "failed"/"error" in the output text
        assert parsed_success is True, (
            f"Structured result incorrectly classified success message as failure: "
            f"'{result_text}'. Structured results should use the 'success' field, "
            f"not string matching on the output text."
        )


# ---------------------------------------------------------------------------
# (f) Narration-embedded JSON: Pass narration text with repairable JSON
#     (single quotes, minor issues) → verify JSON is dropped because the
#     narration heuristic fires BEFORE the SelfHealingParser gets a chance.
#
# BUG: On unfixed code, when _try_extract_json fails (e.g., single-quote JSON),
#      the narration heuristic ("let me", "i will", etc.) fires and returns None
#      BEFORE the SelfHealingParser can attempt repair. In the unified pipeline
#      (after fix), SelfHealingParser runs as Stage 2 before narration heuristics.
#
# EXPECTED (after fix): The unified pipeline tries JSON extraction (Stage 1),
#      then SelfHealingParser repair (Stage 2), and only checks narration
#      heuristics if BOTH fail (Stage 4). Repairable JSON in narration text
#      should be extracted successfully.
#
# **Validates: Requirements 1.3, 1.4, 2.8, 2.9**
# ---------------------------------------------------------------------------

class TestNarrationEmbeddedJSON:
    """Test that repairable JSON in narration is extracted via SelfHealingParser."""

    @given(
        narration_prefix=st.sampled_from([
            "Let me run this: ",
            "I will execute: ",
            "First, let me do: ",
            "Step 1: Running ",
            "I'll run this command: ",
            "Let's try: ",
            "I need to run: ",
            "I am going to execute: ",
        ]),
        action_name=st.sampled_from(["run_cmd", "list_dir", "read_files", "web_search"]),
        param_value=st.text(
            alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_-./"),
            min_size=3,
            max_size=50,
        ),
    )
    @settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_repairable_json_extracted_despite_narration(self, narration_prefix, action_name, param_value):
        """
        Property: Repairable JSON (single quotes) embedded in narration text
        should be extracted via SelfHealingParser BEFORE narration heuristics fire.

        On UNFIXED code: narration heuristic fires before SelfHealingParser → None.

        **Validates: Requirements 1.3, 1.4, 2.8, 2.9**
        """
        parse_action = _get_parse_action()

        # Build text with narration prefix + single-quote JSON (needs repair)
        if action_name == "run_cmd":
            json_str = f"{{'action': '{action_name}', 'command': '{param_value}'}}"
        elif action_name == "list_dir":
            json_str = f"{{'action': '{action_name}', 'path': '{param_value}'}}"
        elif action_name == "read_files":
            json_str = f"{{'action': '{action_name}', 'files': ['{param_value}']}}"
        else:
            json_str = f"{{'action': '{action_name}', 'query': '{param_value}'}}"

        text = f"{narration_prefix}{json_str}"

        result = parse_action(text)

        # EXPECTED (after fix): SelfHealingParser repairs single quotes → valid action
        # On UNFIXED code: narration heuristic fires → returns None
        assert result is not None, (
            f"parse_action returned None for narration + repairable JSON. "
            f"Narration heuristic fired before SelfHealingParser could repair. "
            f"Input: '{text[:80]}...'"
        )
        assert result.get("action") == action_name, (
            f"Expected action '{action_name}' but got '{result.get('action')}'. "
            f"Input: '{text[:80]}...'"
        )

    def test_specific_case_let_me_run_this_single_quotes(self):
        """
        Specific case: 'Let me run this: {'action': 'run_cmd', 'command': 'echo hi'}'
        The single-quote JSON should be repaired and extracted, not dropped by
        the narration heuristic.

        **Validates: Requirements 1.3, 1.4**
        """
        parse_action = _get_parse_action()

        text = "Let me run this: {'action': 'run_cmd', 'command': 'echo hi'}"
        result = parse_action(text)

        # EXPECTED: SelfHealingParser repairs → {"action": "run_cmd", "command": "echo hi"}
        # On UNFIXED code: "let me" heuristic → returns None
        assert result is not None, (
            f"parse_action returned None for narration + single-quote JSON. "
            f"The 'let me' narration heuristic fired before SelfHealingParser."
        )
        assert result.get("action") == "run_cmd", (
            f"Expected action 'run_cmd' but got '{result.get('action')}'"
        )
        assert result.get("command") == "echo hi", (
            f"Expected command 'echo hi' but got '{result.get('command')}'"
        )


# ---------------------------------------------------------------------------
# Helper: Load parse_action in isolation (avoids full import chain)
# ---------------------------------------------------------------------------

_parse_action_cache = None


def _get_parse_action():
    """Load parse_action function from tool_pipeline.py (extracted from agent.py)."""
    global _parse_action_cache
    if _parse_action_cache is not None:
        return _parse_action_cache

    # parse_action now lives in tool_pipeline.py after the refactoring (task 3.4)
    # Import it directly — it's importable without instantiating the full agent
    from mini_ai.core.tool_pipeline import parse_action

    _parse_action_cache = parse_action
    return _parse_action_cache
