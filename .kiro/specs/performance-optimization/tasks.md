# Implementation Plan: Performance Optimization

## Overview

This plan implements 15 performance and reliability modules for mini_ai v39, ordered by dependency: foundational infrastructure first (lazy loader, config, connection pool), then workspace intelligence (dependency graph, change tracker, repo map), communication layer (token budget, structured protocol, observation compressor, streaming parser), and finally execution layer (batch executor, multi-action, tool reliability, self-healing, tool router). Each task builds incrementally on previous work, with property-based tests validating correctness properties from the design.

## Tasks

- [x] 1. Foundational infrastructure modules
  - [x] 1.1 Implement Lazy Module Loader (`mini_ai/core/lazy_loader.py`)
    - Create `LazyModule` class with `__getattr__` proxy that defers `importlib.import_module` until first attribute access
    - Track load time in `_load_time_ms` and log WARNING if > 200ms
    - Handle import failures gracefully: log WARNING, raise `AttributeError` on subsequent access
    - Update `mini_ai/agents/agent.py` to use `LazyModule` for psutil, health_monitor, and rag imports
    - _Requirements: 1.1, 1.2, 1.4, 1.5_

  - [ ]* 1.2 Write property test for lazy loading (Property 1)
    - **Property 1: Lazy loading defers imports until first use**
    - **Validates: Requirements 1.1**
    - Create `tests/test_lazy_loader.py` using hypothesis
    - Verify module import does NOT execute at LazyModule construction time
    - Verify module IS available after first attribute access

  - [x] 1.3 Extend Config with performance fields (`mini_ai/core/config.py`)
    - Add fields: `lazy_loading`, `token_budget_strict`, `batch_max_workers`, `streaming_parse`, `grammar_adaptive`, `tool_routing`, `self_healing`, `max_tools_per_turn`, `connection_pool_size`, `reconnect_timeout`
    - All fields have sensible defaults (as specified in design)
    - Ensure backward compatibility with existing config loading
    - _Requirements: 7.3, 13.1_

  - [x] 1.4 Implement Connection Pool (`mini_ai/core/connection_pool.py`)
    - Create `ConnectionPool` class with configurable max connections (default 4), keep-alive support
    - Implement `get_connection()` that queues when pool exhausted (max 2 for agent, 4 general)
    - Implement `release()` to return connections to pool
    - Implement `pre_warm()` to send empty prompt with `n_predict=1` to warm KV cache
    - Create `RetryPolicy` class with exponential backoff (1s, 2s, 4s) for 503 responses, max 3 retries
    - Create `ReconnectionManager` that polls health endpoint every 5s for up to 60s on connection loss
    - _Requirements: 1.3, 13.1, 13.2, 13.3, 13.4, 13.5_

  - [ ]* 1.5 Write property test for connection pool (Property 2) and retry (Property 30)
    - **Property 2: Connection pool size invariant**
    - **Property 30: Retry with exponential backoff on 503**
    - **Validates: Requirements 1.3, 13.1, 13.4**
    - Create `tests/test_connection_pool.py` using hypothesis with mocked HTTP
    - Verify active connections never exceed pool max under any acquire/release sequence
    - Verify retry delays follow 1s, 2s, 4s pattern and error raised after 3 failures

- [x] 2. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Workspace intelligence modules
  - [x] 3.1 Implement Dependency Graph (`mini_ai/core/dep_graph.py`)
    - Create `DependencyGraph` class with `_imports` and `_importers` dicts
    - Implement `build_from_index()` to parse Python import/require statements from indexed files
    - Implement `invalidate(changed_file)` returning `{file} ∪ {direct importers}` (one hop only)
    - Implement `get_function_info(name)` returning `FunctionInfo` with file, lines, callers
    - Implement `files_within_hops(start, max_hops=2)` using BFS traversal
    - Create `FunctionInfo` dataclass with file, name, start_line, end_line, callers
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ]* 3.2 Write property tests for dependency graph (Properties 9, 10, 11, 13)
    - **Property 9: Dependency graph invalidation scope**
    - **Property 10: Function-to-file mapping round-trip**
    - **Property 11: Incremental rebuild processes only changed files**
    - **Property 13: Repo map hop-based filtering**
    - **Validates: Requirements 4.2, 4.3, 4.4, 4.6, 5.3**
    - Create `tests/test_dep_graph.py` using hypothesis
    - Generate random graph structures and verify invalidation returns exactly one-hop dependents
    - Verify function lookup round-trips correctly
    - Verify BFS returns only files within specified hop count

  - [x] 3.3 Implement File Change Tracker (`mini_ai/core/change_tracker.py`)
    - Create `FileChangeTracker` class with mtime cache and modified files list (max 50)
    - Implement `check_file(path)` comparing stored vs disk mtime
    - Implement `record_write(path)` to update cache after executor writes
    - Implement `get_modified_files()` returning max 50 most recent entries
    - Implement `should_reindex()` returning True when > 20 files modified
    - Implement `get_files_for_reindex(dep_graph)` returning modified files + direct importers
    - Handle cache update failures by invalidating entry and logging
    - _Requirements: 14.1, 14.2, 14.3, 14.5, 14.6, 14.7_

  - [ ]* 3.4 Write property tests for change tracker (Properties 31, 32)
    - **Property 31: File change detection via mtime**
    - **Property 32: Modified files list cap**
    - **Validates: Requirements 14.1, 14.3, 14.6**
    - Create `tests/test_change_tracker.py` using hypothesis
    - Verify mtime comparison correctness for changed vs unchanged files
    - Verify list never exceeds 50 entries regardless of modification count

  - [x] 3.5 Extend Workspace Index for incremental rebuild (`mini_ai/core/workspace_index.py`)
    - Integrate `DependencyGraph` and `FileChangeTracker` into existing workspace index
    - Implement incremental rebuild: process only changed-mtime files, remove deleted file entries
    - Add function-to-file mapping storage with start/end line numbers
    - Support lookup of callers within indexed workspace
    - Return empty result with indication for non-existent function names
    - _Requirements: 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [x] 3.6 Enhance Repo Map with cross-references (`mini_ai/tools/repomap.py`)
    - Implement `classify_file_role(path, signatures)` returning one of: entry_point, utility, model, controller, test, config, unknown
    - Implement `generate_repo_map_v2()` with import edges, role annotations, and goal-focused filtering
    - Filter to files within 2 dependency hops of highest-relevance file
    - Fallback to entry_point files + 1 hop when no file scores above relevance threshold of 5
    - Handle syntax-error files gracefully (include with role + partial edges)
    - Enforce max 400 tokens (1600 chars) with BM25 filtering above 1.5
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [ ]* 3.7 Write property test for repo map role classification (Property 12)
    - **Property 12: Repo map role classification from closed set**
    - **Validates: Requirements 5.2**
    - Create `tests/test_repo_map.py` using hypothesis
    - Generate random file paths and signature sets, verify output is always from the closed set

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Communication layer modules
  - [x] 5.1 Implement Token Budget Manager (`mini_ai/core/prompting.py` extension)
    - Create `TokenBudgetManager` class with `CHAR_TO_TOKEN_RATIO = 4`
    - Implement budget calculation: `min(ctx_size - 1096, 3000)` for ctx ≤ 4096, else `ctx_size - 1096`
    - Create `PromptSection` dataclass with name, content, priority, mandatory, max_tokens
    - Implement `add_section()` and `build()` with priority-based trimming (drop repo_map first → session context → old observations)
    - Implement `estimate_tokens(text)` as `len(text) // 4`
    - Reject prompt if estimate exceeds budget
    - Implement repo map BM25 filtering: truncate to entries with score > 1.5 when repo map > 400 tokens
    - Implement observation summarization: single-line format for all but 3 most recent when history > 2000 chars
    - Drop repo map entirely as last resort, log warning
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [ ]* 5.2 Write property tests for token budget (Properties 3, 4, 5, 6)
    - **Property 3: Token budget enforcement with priority-based trimming**
    - **Property 4: Token estimation consistency**
    - **Property 5: Repo map BM25 filtering under budget pressure**
    - **Property 6: Observation history summarization**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
    - Create `tests/test_token_budget.py` using hypothesis
    - Generate random section sets and budgets, verify output always within budget with mandatory sections present
    - Verify `estimate_tokens(s) == len(s) // 4` for all strings

  - [x] 5.3 Implement Structured Communication Protocol (`mini_ai/core/communication.py` extension)
    - Create `StructuredPromptFormatter` with labeled delimiters: [GOAL], [HISTORY], [CONTEXT], [TOOLS], [MEMORY], [REPO_MAP]
    - Create `ResponseValidator` that checks for parseable JSON with valid "action" key matching registered tool names
    - Implement nudge message with JSON schema and concrete example for invalid responses
    - Implement retry logic: remove non-mandatory sections after 3 consecutive invalid responses
    - Abort after simplified retry still fails, return error to caller
    - Create `ToolSuccessTracker` tracking per-session success/failure, recommending top 3 tools with ≥5 invocations
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [ ]* 5.4 Write property tests for communication (Properties 14, 15, 16)
    - **Property 14: Structured prompt contains all mandatory labeled sections**
    - **Property 15: Response validation correctness**
    - **Property 16: Tool success recommendation accuracy**
    - **Validates: Requirements 6.1, 6.2, 6.6**
    - Create `tests/test_communication.py` using hypothesis
    - Verify [GOAL] and [TOOLS] always present in formatted output
    - Verify validation returns True for valid JSON with valid action, False otherwise
    - Verify recommendations ordered by success ratio with ≥5 invocation threshold

  - [x] 5.5 Implement Observation Compressor (`mini_ai/core/communication.py` extension)
    - Create `ObservationCompressor` class with thresholds: compress > 1000 chars to ≤ 500 chars
    - Implement structured template: `[TOOL_NAME] STATUS: success/fail | KEY_INFO: extracted_data`
    - Implement `run_cmd` special handling: keep first 200 + last 500 chars with `... [N characters truncated] ...`
    - Implement `deduplicate()` replacing consecutive identical observations with `[repeated N times]`
    - Implement `summarize_old()` for observations older than 3 turns when history > 60% of context budget
    - Pass through unmodified for outputs ≤ 1000 characters (still in template format)
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [ ]* 5.6 Write property tests for observation compression (Properties 27, 28, 29)
    - **Property 27: Observation compression respects threshold**
    - **Property 28: Command output truncation preserves head and tail**
    - **Property 29: Observation deduplication**
    - **Validates: Requirements 12.1, 12.3, 12.4, 12.6**
    - Add tests to `tests/test_communication.py`
    - Verify compressed output ≤ 500 chars for inputs > 1000 chars
    - Verify head/tail preservation for run_cmd outputs > 2000 chars
    - Verify consecutive duplicates replaced with repetition count

  - [x] 5.7 Implement Streaming Response Parser (`mini_ai/core/streaming.py`)
    - Create `StreamingActionParser` class with brace-depth counter and buffer
    - Implement `feed(token)` that tracks brace depth and attempts JSON parse at depth zero
    - Implement `ParseEvent` enum: BUFFERING, ACTION_READY, INVALID_CANDIDATE, STREAM_END
    - Validate parsed JSON against ToolSchema registry before returning ACTION_READY
    - Discard invalid candidates and continue buffering for next brace-depth-zero boundary
    - Treat stream completion without valid JSON as plain reasoning text
    - _Requirements: 10.1, 10.2, 10.4, 10.5_

  - [ ]* 5.8 Write property test for streaming parser (Property 25)
    - **Property 25: Streaming parser detects action at brace-depth zero**
    - **Validates: Requirements 10.1**
    - Create `tests/test_streaming_parser.py` using hypothesis
    - Generate valid JSON actions, split into random token chunks, verify parser detects complete action at correct boundary

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Adaptive grammar and backend integration
  - [x] 7.1 Implement Adaptive Grammar Selector (`mini_ai/core/adaptive_grammar.py`)
    - Create `AdaptiveGrammarSelector` class with model size detection from GGUF filename
    - Implement `_detect_model_size()` extracting numeric pattern + "B" from filename (e.g., "3B" → 3.0)
    - Default to < 7B if no pattern found
    - Implement `select_grammar()`: return THINK_JSON_GRAMMAR for < 7B, JSON_ACTION_GRAMMAR for ≥ 7B
    - Implement `record_empty_response()`: disable grammar after 2 consecutive empty responses
    - Implement `record_success()`: reset empty response counter
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [ ]* 7.2 Write property tests for adaptive grammar (Properties 17, 18)
    - **Property 17: Adaptive grammar selection by model size**
    - **Property 18: GGUF filename size extraction**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4**
    - Create `tests/test_adaptive_grammar.py` using hypothesis
    - Generate model sizes and verify correct grammar selection
    - Generate filenames with/without size patterns and verify extraction

  - [x] 7.3 Extend GBNF Grammar for multi-action support (`mini_ai/core/grammars.py`)
    - Add `MULTI_ACTION_GRAMMAR` supporting both `{"action": ...}` and `{"actions": [...]}` formats
    - Maintain backward compatibility with existing single-action grammar
    - Include `depends_on` field support in action objects
    - _Requirements: 9.5_

  - [-] 7.4 Integrate adaptive grammar and connection pool into Backend (`mini_ai/core/backend.py`)
    - Replace direct HTTP calls with `ConnectionPool` usage
    - Add `AdaptiveGrammarSelector` to grammar selection logic
    - Set read timeout to 600s for CPU-only hardware
    - Add keep-alive headers to all requests
    - Integrate pre-warm on server ready
    - Wire streaming token reception to `StreamingActionParser`
    - Close HTTP connection after early action detection to abort remaining stream
    - _Requirements: 7.1, 7.2, 7.5, 10.2, 10.3, 13.1, 13.2, 13.3_

- [ ] 8. Execution layer modules
  - [x] 8.1 Implement Self-Healing JSON Parser (`mini_ai/core/self_healing.py`)
    - Create `SelfHealingParser` class with tool registry reference
    - Implement `_fix_single_quotes()`: replace single quotes with double quotes
    - Implement `_fix_backslashes()`: escape unescaped Windows backslashes in JSON
    - Implement `_fix_trailing_commas()`: remove trailing commas before `}` or `]`
    - Implement `_fix_tool_name()`: Levenshtein distance ≤ 2 correction to exactly one valid tool; reject if ambiguous
    - Implement `parse(raw)` with repair pipeline: single quotes → backslashes → trailing commas → re-parse (1 attempt)
    - Ignore extra fields not in tool schema during execution
    - Maintain `_correction_log` (Counter) and implement `get_session_hints(min_count=2, top_k=3)`
    - Return error with corrective example if repair fails
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7_

  - [ ]* 8.2 Write property tests for self-healing (Properties 33, 34, 35, 36, 37)
    - **Property 33: Single-quote JSON repair round-trip**
    - **Property 34: Levenshtein tool name correction**
    - **Property 35: Extra fields are ignored during execution**
    - **Property 36: Windows backslash repair**
    - **Property 37: Session correction hints reflect top errors**
    - **Validates: Requirements 15.1, 15.2, 15.3, 15.4, 15.5, 15.7**
    - Create `tests/test_self_healing.py` using hypothesis
    - Generate valid JSON, replace quotes, verify round-trip
    - Generate tool names with edits, verify correction or rejection
    - Generate actions with extra fields, verify execution ignores them

  - [-] 8.3 Implement Batch Executor (`mini_ai/core/batch.py`)
    - Create `BatchExecutor` class with MAX_BATCH_SIZE=50, MAX_WORKERS=4
    - Implement `batch_read(paths, pm)` using `concurrent.futures.ThreadPoolExecutor`
    - Implement `batch_write(files, writer)` with concurrent writes
    - Create `BatchResult` and `FileResult` dataclasses
    - Reject batches > 50 with clear error message
    - Handle per-file failures independently (no abort on single failure)
    - Return consolidated result with per-file status and summary counts
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [ ]* 8.4 Write property tests for batch executor (Properties 7, 8)
    - **Property 7: Batch read correctness with partial failure handling**
    - **Property 8: Batch write correctness with per-file status**
    - **Validates: Requirements 3.1, 3.2, 3.4**
    - Create `tests/test_batch_executor.py` using hypothesis
    - Generate mixed valid/invalid path sets, verify valid paths return correct content unaffected by failures
    - Generate write operations, verify on-disk content matches requested content

  - [x] 8.5 Implement Tool Calling Reliability Pipeline (`mini_ai/core/tool_reliability.py`)
    - Create `LoopDetector` with sliding window of 10, threshold of 3 identical (tool, params) tuples
    - Create `ToolDisabler` with max 3 consecutive failures before disabling; re-enable on explicit valid call
    - Implement required category protection: re-enable least-recently-disabled tool if all tools in filesystem/execution/output category disabled
    - Create `RecoverySuggester` mapping error categories to concrete suggestions
    - Implement schema validation producing structured errors with missing params, expected types, and usage example
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [ ]* 8.6 Write property tests for tool reliability (Properties 19, 20, 21, 22)
    - **Property 19: Schema validation produces correct structured errors**
    - **Property 20: Loop detection triggers at correct threshold**
    - **Property 21: Recovery suggestion mapping completeness**
    - **Property 22: Tool disabling on consecutive failures**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.5, 8.6**
    - Create `tests/test_tool_reliability.py` using hypothesis
    - Generate tool call sequences, verify loop detection triggers at exactly 3 repeats in window of 10
    - Generate failure sequences, verify disabling at exactly 3 consecutive failures

  - [-] 8.7 Implement Multi-Action Executor (`mini_ai/core/multi_action.py`)
    - Create `MultiActionExecutor` with MAX_BATCH_SIZE=10
    - Implement `_validate_dependencies()` checking for out-of-range indices and circular dependencies
    - Implement `_topological_sort()` returning execution layers (parallel within, sequential between)
    - Implement `execute_batch()` running independent actions in parallel, dependent actions sequentially
    - Cancel all transitive dependents on action failure, continue independent actions
    - Return `BatchActionResult` with per-index results and cancelled list
    - Reject batches > 10 with clear error
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.6, 9.7_

  - [ ]* 8.8 Write property tests for multi-action executor (Properties 23, 24)
    - **Property 23: Multi-action dependency validation**
    - **Property 24: Multi-action failure propagation**
    - **Validates: Requirements 9.3, 9.4, 9.6**
    - Create `tests/test_multi_action.py` using hypothesis
    - Generate action batches with valid/invalid dependency structures, verify rejection of invalid
    - Generate batches with simulated failures, verify correct cancellation of transitive dependents

- [~] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Tool routing and agent loop integration
  - [-] 10.1 Implement Context-Aware Tool Router (`mini_ai/core/tool_router.py`)
    - Create `TASK_TOOL_SETS` dict for code_editing, exploration, and default task types
    - Create `ToolRouter` class with workspace index and capabilities references
    - Implement `route(task_type, goal)` returning filtered tool list (max 8 tools)
    - Implement `_detect_framework_tools()` adding framework-specific tools (e.g., laravel_create_project, git_init)
    - Implement `suggest_alternative()` finding equivalent tool in available set for unavailable requests
    - Return error with available alternatives when requested tool not in current set
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7_

  - [ ]* 10.2 Write property test for tool router (Property 26)
    - **Property 26: Tool routing produces correct bounded tool sets**
    - **Validates: Requirements 11.1, 11.2, 11.4**
    - Create `tests/test_tool_router.py` using hypothesis
    - Generate task types and framework detections, verify output matches defined sets and never exceeds 8 tools

  - [~] 10.3 Integrate all modules into Agent Loop (`mini_ai/agents/agent.py`)
    - Wire `LazyModule` imports for heavy modules
    - Integrate `SelfHealingParser` for JSON repair before executor dispatch
    - Integrate `LoopDetector` and `ToolDisabler` into the action processing loop
    - Integrate `ToolRouter` for task-type-based tool selection
    - Integrate `StreamingActionParser` for early action detection from streaming responses
    - Integrate `ObservationCompressor` for tool output compression
    - Integrate `TokenBudgetManager` into prompt assembly
    - Add session error correction hints to system prompt
    - _Requirements: 1.1, 8.3, 8.4, 8.6, 10.2, 10.3, 11.1, 12.1, 15.1, 15.7_

  - [~] 10.4 Integrate modules into Executor (`mini_ai/core/executor.py`)
    - Wire `BatchExecutor` for batch_read_files and batch_write_files actions
    - Wire `MultiActionExecutor` for multi-action JSON responses
    - Integrate `RecoverySuggester` for error responses
    - Integrate schema validation with structured error responses
    - Ignore extra fields in tool calls (pass only schema-defined params)
    - Annotate observations for recently-modified files
    - _Requirements: 3.1, 3.2, 8.1, 8.2, 8.5, 9.1, 14.4, 15.4_

  - [~] 10.5 Integrate modules into Orchestrator (`mini_ai/agents/orchestrator.py`)
    - Wire `ToolRouter` for task classification and tool set selection
    - Add framework detection to workspace analysis phase
    - _Requirements: 11.1, 11.2, 11.3, 11.7_

- [~] 11. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. End-to-end integration and final wiring
  - [~] 12.1 Create shared test fixtures and generators (`tests/conftest.py`)
    - Create hypothesis strategies for: random file paths, JSON action objects, tool call sequences, prompt sections, observation histories
    - Create pytest fixtures for: mock workspace index, mock llama-server, temp file trees
    - Set up hypothesis profiles with `max_examples=100, deadline=None`
    - _Requirements: All (testing infrastructure)_

  - [ ]* 12.2 Write integration tests for full pipeline
    - Test end-to-end agent loop with mocked llama-server
    - Test streaming response → self-healing → executor pipeline
    - Test token budget enforcement across multiple turns
    - Test connection pool behavior under concurrent requests
    - _Requirements: All (integration validation)_

  - [ ]* 12.3 Write Laravel project installation integration test
    - Create test scenario: agent receives goal "Install a Laravel project in the Downloads folder"
    - Verify tool router detects Laravel framework and adds `laravel_create_project` and `git_init` tools
    - Verify batch file operations work for multi-file scaffolding
    - Verify self-healing handles any JSON errors from model during the workflow
    - Verify observation compression keeps context within budget across multiple tool calls
    - Test with mocked llama-server responses simulating the full Laravel setup flow
    - _Requirements: 11.3, 3.1, 3.2, 12.1, 15.1_

- [~] 13. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design (37 properties total)
- Unit tests validate specific examples and edge cases
- The design uses Python throughout — all implementations use Python 3.10+ features (dataclasses, type hints, match statements where appropriate)
- The `hypothesis` library is required for property-based testing (`pip install hypothesis`)
- Integration tests use mocked llama-server to avoid requiring a running inference server
- The Laravel integration test (12.3) validates the user's target scenario end-to-end

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.3"] },
    { "id": 1, "tasks": ["1.2", "1.4"] },
    { "id": 2, "tasks": ["1.5", "3.1", "3.3"] },
    { "id": 3, "tasks": ["3.2", "3.4", "3.5"] },
    { "id": 4, "tasks": ["3.6", "5.1"] },
    { "id": 5, "tasks": ["3.7", "5.2", "5.3", "5.5"] },
    { "id": 6, "tasks": ["5.4", "5.6", "5.7", "7.1"] },
    { "id": 7, "tasks": ["5.8", "7.2", "7.3"] },
    { "id": 8, "tasks": ["7.4", "8.1"] },
    { "id": 9, "tasks": ["8.2", "8.3", "8.5"] },
    { "id": 10, "tasks": ["8.4", "8.6", "8.7"] },
    { "id": 11, "tasks": ["8.8", "10.1"] },
    { "id": 12, "tasks": ["10.2", "10.3", "10.4", "10.5"] },
    { "id": 13, "tasks": ["12.1"] },
    { "id": 14, "tasks": ["12.2", "12.3"] }
  ]
}
```
