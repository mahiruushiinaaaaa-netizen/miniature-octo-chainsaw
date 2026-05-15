# Architecture Speed Fix - Bugfix Design

## Overview

Mini-AI v39 suffers from three interconnected architectural defects that degrade performance on constrained hardware (Intel i5, 4GB RAM, 3B parameter models): a monolithic 1500-line agent.py with duplicated loop detection and scattered parsing, RAG tightly coupled to the executor with N+1 embedding calls and no fallback, and a retry system that burns expensive LLM calls without short-circuiting. This fix decomposes the agent into focused modules with a unified tool-calling pipeline, decouples RAG into a context injection layer with batched embeddings and TF-IDF fallback, and introduces zero-cost recovery with structured result objects for the orchestrator.

## Glossary

- **Bug_Condition (C)**: The architectural conditions that trigger performance degradation — monolithic structure causing duplicated logic, RAG coupling causing N+1 calls, and retry logic causing unnecessary LLM invocations
- **Property (P)**: The desired behavior — decomposed modules with single-responsibility, decoupled RAG with batched/fallback retrieval, and speed-first retry with short-circuit paths
- **Preservation**: Existing prompt assembly, tool execution observation format, ToolRouter caps, connection pooling, SelfHealingParser behavior, config flag fallbacks, ToolDisabler category protection, COMPLEX intent handling, system prompt token budgets, and GBNF grammar constraints that must remain unchanged
- **agent.py**: The monolithic ~1500-line file in `mini_ai/agents/agent.py` containing the agent loop, prompt building, JSON parsing, streaming handlers, loop detection, and retry logic
- **ToolExecutor**: The class in `mini_ai/core/executor.py` that executes tool actions and currently embeds RAG strategy decisions inline
- **RAGManager**: The class in `mini_ai/core/rag.py` that performs embedding-based retrieval with per-chunk embedding calls
- **_generate_with_retry**: The function in `agent.py` that handles empty/invalid model output with up to 3 LLM generation calls per step
- **LoopDetector**: The sliding-window loop detection class in `mini_ai/core/tool_reliability.py` (the canonical implementation)
- **Inline loop detection**: The duplicated action_history, action_name_list, strict_repeat_count, and consecutive_name_repeats logic in agent.py

## Bug Details

### Bug Condition

The bug manifests when the agent loop executes on constrained hardware (Intel i5, 4GB RAM, 3B models) and encounters any of: (a) duplicated loop detection paths causing inconsistent behavior, (b) RAG making N+1 embedding calls per retrieval, (c) retry logic making up to 3 full LLM generation calls (~50s each) without short-circuiting, or (d) the orchestrator misclassifying task results via string pattern matching.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type AgentLoopExecution
  OUTPUT: boolean
  
  condition_monolithic := input.agent_file_lines > 300
         AND input.has_inline_loop_detection = TRUE
         AND input.has_duplicated_parsing_logic = TRUE
  
  condition_rag := input.rag_embedded_in_executor = TRUE
         AND (input.embedding_calls_per_retrieval > 2
              OR (input.embeddings_unavailable = TRUE AND input.fallback_returns_empty = TRUE))
  
  condition_retry := input.previous_step_succeeded = TRUE
         AND input.current_output_empty = TRUE
         AND input.performs_expensive_retries = TRUE
  
  condition_orchestrator := input.success_determined_by_string_matching = TRUE
  
  RETURN condition_monolithic OR condition_rag OR condition_retry OR condition_orchestrator
END FUNCTION
```

### Examples

- **Duplicated loop detection**: Agent calls `run_cmd` 3 times → LoopDetector (threshold=3) fires AND inline `consecutive_name_repeats >= 3` fires independently with different recovery actions, causing unpredictable behavior
- **N+1 embedding calls**: Reading a 50KB file → chunks into ~38 pieces → 39 embedding API calls (1 query + 38 chunks) × ~1.3s each = ~50 seconds for a single file read on local hardware
- **Embeddings unavailable (common case)**: No embedding model loaded → `retrieve_relevant_snippets()` returns `[]` → RAG provides zero context → agent hallucinates without workspace grounding
- **Expensive retry on responsive model**: Step 4 succeeds (model is responsive) → Step 5 returns empty (prompt issue) → system makes 3 full LLM calls (~150s total) instead of short-circuiting
- **Orchestrator false positive**: Task output contains "the test that previously failed now passes" → `"failed" in result.lower()` matches → task marked as failed despite success

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Micro-prompt system assembles prompts within ~500 token budget with Goal/Tools/Context/Example/Output JSON structure (Requirement 3.1)
- Tool execution returns JSON observation format `{"success": bool, "output": str}` to the agent loop (Requirement 3.2)
- ToolRouter caps at 8 tools per turn and always includes "answer" (Requirement 3.3)
- Connection pool uses persistent keep-alive with exponential backoff on 503, max 3 retries (Requirement 3.4)
- SelfHealingParser handles single quotes, trailing commas, backslash escaping, Levenshtein ≤ 2 tool name correction (Requirement 3.5)
- Config flags set to False fall back to original monolithic behavior without errors (Requirement 3.6)
- ToolDisabler protects required categories by re-enabling LRU tool as last resort (Requirement 3.7)
- COMPLEX intent uses full monolithic prompt system with complete context (Requirement 3.8)
- System prompt templates remain at or below 60 tokens (len(text) // 4) (Requirement 3.9)
- GBNF grammar enforces same JSON structure without modification (Requirement 3.10)
- First-attempt valid JSON tool calls execute immediately without additional overhead (Requirement 3.11)

**Scope:**
All inputs that do NOT involve the decomposed modules, RAG retrieval, retry logic, or orchestrator result evaluation should be completely unaffected by this fix. This includes:
- Direct tool execution (write_files, run_cmd, list_dir, etc.)
- Streaming token handling and UI rendering
- PersistentMemory and SessionMemory operations
- Workspace indexing and file change tracking
- Sandbox and security scoring

## Hypothesized Root Cause

Based on the bug description, the most likely issues are:

1. **Organic Growth Without Refactoring**: agent.py grew from a simple loop to 1500 lines as features were added (streaming, micro-prompts, loop detection, retry, RAG grounding) without extracting concerns into modules. The inline loop detection (action_history, action_name_list, strict_repeat_count, consecutive_name_repeats) was added before LoopDetector existed and never removed.

2. **RAG Designed for Server-Side Embeddings**: The RAGManager was ported from a plugin architecture that assumed fast server-side embeddings. The per-chunk `get_embeddings()` call pattern works fine with a remote API but is catastrophically slow on local hardware. No fallback was implemented because the original design assumed embeddings would always be available.

3. **Defensive Retry Without Cost Awareness**: The `_generate_with_retry` function was designed to maximize reliability (never miss a valid action) without considering that each retry costs ~50 seconds on 3B models. There's no awareness of whether the model is "responsive" (previous step worked) vs "struggling" (multiple failures).

4. **Orchestrator String Matching as Quick Fix**: The orchestrator's success detection (`"failed" in result.lower()`) was a quick heuristic that worked for simple cases but breaks on natural language outputs that mention failure in non-failure contexts.

## Correctness Properties

Property 1: Bug Condition - Decomposed Agent Produces Identical Tool Execution

_For any_ agent loop execution where the bug condition holds (monolithic structure with duplicated logic), the fixed decomposed agent SHALL produce the same tool execution sequence and final answer as the original monolithic agent for the same input goal, while using only LoopDetector as the single loop detection mechanism and processing tool calls through the unified pipeline (extract → heal → validate → execute).

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.8, 2.9**

Property 2: Preservation - Non-Decomposed Paths Unchanged

_For any_ input where the bug condition does NOT hold (COMPLEX intent using monolithic prompts, config flags disabled, first-attempt valid JSON, non-RAG tool calls), the fixed code SHALL produce exactly the same behavior as the original code, preserving prompt assembly budgets, observation formats, ToolRouter caps, connection pooling, SelfHealingParser repairs, config fallbacks, ToolDisabler protection, and GBNF grammar constraints.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11**


## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `mini_ai/agents/agent.py` → decompose into coordinator + modules

**Specific Changes**:

1. **Extract Retry Module** (`mini_ai/core/retry.py`):
   - Move `_generate_with_retry`, `RetryState` to a dedicated module
   - Add `previous_step_succeeded: bool` parameter to enable short-circuit
   - Add zero-cost recovery (temperature bump +0.1 or seed change) as first retry attempt
   - Keep existing cascade (grammar-removal → nudge) as fallback after zero-cost fails
   - Track both zero-cost empty and original empty toward consecutive_empties threshold

2. **Create Unified Tool-Calling Pipeline** (`mini_ai/core/tool_pipeline.py`):
   - Single entry point: `process_model_output(raw_output) → ToolAction | None`
   - Stage 1: JSON extraction via `_try_extract_json` (brace-matching scan for dict with "action" key) — runs BEFORE narration heuristics
   - Stage 2: If extraction fails, attempt `SelfHealingParser.parse()` returning repaired dict or None
   - Stage 3: If a dict is returned, validate "action" field against registered tool schema names
   - Stage 4: If all stages fail, return None (no valid action)
   - Move `parse_action`, `_try_extract_json`, `_is_refusal` into this module
   - Narration heuristics ("i will", "first,", "step 1") only checked AFTER JSON extraction fails

3. **Remove Inline Loop Detection from agent.py**:
   - Remove `action_history: list[str]` and `action_name_list: list[str]` tracking
   - Remove `strict_repeat_count = action_history.count(action_sig)` check
   - Remove `consecutive_name_repeats` counting loop
   - Keep only `loop_detector.record()` and `loop_detector.is_looping()` from LoopDetector
   - Preserve the recovery behavior (tool disabling, web search fallback) but trigger it only from LoopDetector

4. **Lean Agent Coordinator** (refactored `mini_ai/agents/agent.py`):
   - Target: ≤300 lines (excluding blanks/comments)
   - Imports and delegates to: `retry.py`, `tool_pipeline.py`, `micro_prompts.py`, `streaming.py`, `self_healing.py`, `tool_reliability.py`
   - Retains: step loop, context assembly, executor dispatch, observation recording, UI calls
   - Each delegated module is importable and callable without instantiating the full agent

---

**File**: `mini_ai/core/executor.py` → decouple RAG

**Specific Changes**:

5. **Create Context Injection Layer** (`mini_ai/core/context_injector.py`):
   - Interface: `enrich(path: str, content: str, query: str) → list[ScoredSnippet]`
   - `ScoredSnippet` dataclass: `{source_path: str, score: float, content: str, offset_start: int, offset_end: int}`
   - Delegates to RAGManager for embedding-based retrieval
   - Falls back to TF-IDF when embeddings unavailable
   - Returns first 3000 chars as raw block if both methods fail (with warning log)

6. **Batch Embeddings in RAGManager**:
   - Replace per-chunk `get_embeddings(chunk)` loop with single batched call
   - New method: `get_embeddings_batch(texts: list[str]) → list[list[float]]`
   - At most 2 API round-trips: 1 for query, 1 for all chunks batched
   - If backend doesn't support batch, chunk into groups of 16 and make ceil(N/16) calls (still far fewer than N)

7. **TF-IDF Fallback** (in `mini_ai/core/context_injector.py`):
   - Pure Python TF-IDF using `collections.Counter` and `math.log` (no external deps)
   - Tokenize query and chunks on whitespace + punctuation
   - Score chunks by sum of TF-IDF weights for query terms
   - Return top 1-5 snippets (≤1500 chars each), completing within 500ms for 100KB files
   - Each snippet includes source path, score (0.0-1.0 normalized), and character offset range

8. **Remove RAG Logic from Executor**:
   - Replace `self.rag.decide_strategy()` and `self.rag.retrieve_relevant_snippets()` calls in `tool_read_files` with `self._context_injector.enrich(path, content, query)`
   - Executor no longer imports or instantiates RAGManager directly for strategy decisions
   - RAGManager remains as the embedding engine, called by context_injector

---

**File**: `mini_ai/agents/orchestrator.py` → structured results

**Specific Changes**:

9. **Structured Result Objects**:
   - Define `TaskResult` dataclass: `{success: bool, output: str, tool_name: str | None, exit_code: int | None}`
   - `agent_mode()` returns `TaskResult` (or serialized JSON string with "success" field) instead of raw text
   - Orchestrator reads `result.success` boolean directly — no string pattern matching

10. **Remove Heuristic String Matching**:
    - Remove: `has_error = "failed" in result.lower() or "error" in result.lower()`
    - Remove: `success = not has_error and ("final answer" in result.lower() or ...)`
    - Replace with: parse result as JSON, read "success" field
    - If JSON parse fails or "success" field missing → treat as failure, include raw output in observation

---

**File**: `mini_ai/core/retry.py` → speed-first retry

**Specific Changes**:

11. **Short-Circuit on Responsive Model**:
    - New parameter: `previous_step_succeeded: bool`
    - If `previous_step_succeeded=True` AND output is empty → return `(None, None, retry_state)` immediately
    - Rationale: model is known responsive, empty output = prompt issue, not generation failure

12. **Zero-Cost Recovery**:
    - Before grammar-removal retry: re-send same prompt with `temp + 0.1` (or `seed + 1` if temp already > 0)
    - No grammar recompilation, no prompt modification → near-zero additional cost
    - If zero-cost also returns empty → proceed to existing cascade
    - Both empties count toward consecutive_empties threshold of 2

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bugs on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bugs BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that exercise the duplicated loop detection, N+1 embedding calls, retry behavior on responsive models, and orchestrator string matching. Run these tests on the UNFIXED code to observe failures and understand the root cause.

**Test Cases**:
1. **Duplicated Loop Detection Test**: Simulate 3 identical tool calls → verify BOTH LoopDetector AND inline detection fire independently with different thresholds (will demonstrate inconsistency on unfixed code)
2. **N+1 Embedding Calls Test**: Call `retrieve_relevant_snippets` with a 50KB file → count embedding API calls → verify N+1 pattern (will show >30 calls on unfixed code)
3. **No-Fallback RAG Test**: Set embeddings unavailable → call `retrieve_relevant_snippets` → verify empty list returned with zero context (will demonstrate zero enrichment on unfixed code)
4. **Expensive Retry After Success Test**: Simulate step N succeeding then step N+1 returning empty → measure retry calls → verify 3 full LLM calls made (will show ~150s wasted on unfixed code)
5. **Orchestrator False Positive Test**: Pass result "the test that previously failed now passes" → verify incorrectly classified as failure (will fail on unfixed code)
6. **Narration-Embedded JSON Test**: Pass `'Let me run this: {"action": "run_cmd", "command": "echo hi"}'` to `parse_action` → verify JSON is dropped due to "let me" heuristic (will demonstrate bug on unfixed code)

**Expected Counterexamples**:
- Inline loop detection fires at different thresholds than LoopDetector
- Embedding call count scales linearly with chunk count (N+1)
- Empty retrieval results when embeddings unavailable
- 3 expensive LLM calls even when model was responsive on previous step
- String "failed" in success output causes false failure classification

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := fixedAgentLoop(input)
  ASSERT unified_pipeline_used(result)
  ASSERT only_loop_detector_for_detection(result)
  ASSERT embedding_calls <= 2 for retrieval
  ASSERT tfidf_fallback_returns_snippets when embeddings_unavailable
  ASSERT short_circuit_when_previous_succeeded(result)
  ASSERT orchestrator_uses_structured_result(result)
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT fixedAgentLoop(input) = originalAgentLoop(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain (random goals, intents, config flags)
- It catches edge cases that manual unit tests might miss (unusual tool combinations, boundary token counts)
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for COMPLEX intent, disabled config flags, first-attempt valid JSON, and non-RAG tools, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Prompt Budget Preservation**: Generate random goals and intents → verify assembled prompts stay within ~500 token budget with same structure
2. **Observation Format Preservation**: Execute random valid tool actions → verify JSON observation format unchanged
3. **ToolRouter Cap Preservation**: Generate random task types → verify ≤8 tools and "answer" always included
4. **Config Fallback Preservation**: Set all optimization flags to False → verify original monolithic behavior without errors
5. **SelfHealingParser Preservation**: Generate malformed JSON with single quotes, trailing commas → verify same repair behavior
6. **First-Attempt Fast Path**: Generate valid JSON tool calls → verify no additional parsing overhead beyond current

### Unit Tests

- Test unified tool pipeline stages independently (extract, heal, validate, route)
- Test context injector with mocked embedding backend (batch call verification)
- Test TF-IDF fallback scoring accuracy and performance (< 500ms for 100KB)
- Test retry module short-circuit logic (previous_step_succeeded = True → immediate return)
- Test zero-cost recovery (temperature bump, seed change)
- Test structured TaskResult parsing in orchestrator
- Test that inline loop detection code is absent from agent.py

### Property-Based Tests

- Generate random model outputs (valid JSON, invalid JSON, narration + JSON, pure narration) → verify unified pipeline produces correct classification for all
- Generate random file contents (1KB-100KB) → verify context injector returns 1-5 snippets with valid scores and offsets within 500ms
- Generate random agent loop histories (success/failure sequences) → verify retry short-circuit fires correctly when previous step succeeded
- Generate random task results with "failed"/"error" substrings in success messages → verify orchestrator uses structured field not string matching

### Integration Tests

- Full agent loop execution with decomposed modules → verify same tool execution sequence as monolithic for identical inputs
- RAG retrieval through context injector → verify batched embedding calls and TF-IDF fallback produce relevant snippets
- Orchestrator with structured results → verify correct success/failure classification across diverse task outputs
- Config flag toggling → verify seamless fallback between decomposed and monolithic paths
