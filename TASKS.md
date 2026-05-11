#### Done (Latest)
- **Batch Executor**: Created `mini_ai/core/batch.py` with `BatchExecutor` class for parallel file operations:
  - `BatchExecutor` class with `MAX_BATCH_SIZE=50`, `MAX_WORKERS=4`
  - `batch_read(paths, pm)`: Concurrent file reads using `ThreadPoolExecutor`, per-file failure isolation
  - `batch_write(files, writer)`: Concurrent file writes via `SafeFileWriter`, per-file status tracking
  - `FileResult` dataclass: path, success, content (reads), error (failures), size
  - `BatchResult` dataclass: succeeded/failed lists, duration_ms, summary property, total count
  - Rejects batches > 50 with clear `ValueError` message
  - Per-file failures handled independently (no abort on single failure)
  - Consolidated result with per-file status and summary counts
  - Requirements: 3.1, 3.2, 3.3, 3.4, 3.5

- **Tool Calling Reliability Pipeline**: Created `mini_ai/core/tool_reliability.py` with four classes for robust tool calling:
  - `LoopDetector`: Sliding window (size 10) loop detection. Records (tool, params) tuples and triggers when same tuple appears ≥3 times in window. Uses canonical JSON key for consistent comparison. (Req 8.3, 8.4)
  - `ToolDisabler`: Per-session tool enable/disable based on failure counts. Disables after 3 consecutive failures, re-enables on explicit valid call (record_success). Required category protection: re-enables least-recently-disabled tool if all tools in filesystem/execution/output category become disabled. (Req 8.6, 8.7)
  - `RecoverySuggester`: Maps error categories to concrete recovery suggestions. Covers file-not-found, permission-denied, timeout, invalid-input, syntax-error, connection-error, batch-limit. Auto-classifies errors via pattern matching. (Req 8.5)
  - `SchemaValidator`: Validates tool actions against ToolSchema registry producing structured `ValidationResult` with per-parameter errors (missing/wrong_type), expected types, and auto-generated usage examples. (Req 8.1, 8.2)
  - Added `ValidationError` and `ValidationResult` dataclasses for structured error reporting
  - Added `ToolRecord` dataclass for per-tool failure state tracking
  - Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7

- **Adaptive Grammar Selector**: Created `mini_ai/core/adaptive_grammar.py` with `AdaptiveGrammarSelector` class:
  - `_detect_model_size(model_path)`: Extracts parameter count from GGUF filename using regex pattern matching (e.g., "3B" → 3.0, "0.5B" → 0.5). Defaults to 3.0 (< 7B) if no pattern found or model path is None.
  - `select_grammar()`: Returns `THINK_JSON_GRAMMAR` for < 7B models, `JSON_ACTION_GRAMMAR` for ≥ 7B, or `None` if grammar disabled
  - `record_empty_response()`: Tracks consecutive empty responses, disables grammar after 2 consecutive empties
  - `record_success()`: Resets empty response counter on successful (non-empty) model output
  - Imports grammar constants from `mini_ai/core/grammars.py`
  - Requirements: 7.1, 7.2, 7.3, 7.4, 7.5

- **MULTI_ACTION_GRAMMAR**: Added `MULTI_ACTION_GRAMMAR` constant to `mini_ai/core/grammars.py`:
  - Supports both single-action `{"plan": ..., "action": ...}` and multi-action `{"plan": ..., "actions": [...]}` formats
  - Backward compatible with existing grammars (optional `<think>` block prefix)
  - Includes `depends_on` field support in action objects (integer array referencing action indices)
  - Dedicated `action_field` rule distinguishing `depends_on` from generic key-value fields
  - Same tool_name set as existing grammars for consistency
  - Requirements: 9.5

- **Token Budget Manager**: Extended `mini_ai/core/prompting.py` with `TokenBudgetManager` class and `PromptSection` dataclass:
  - `CHAR_TO_TOKEN_RATIO = 4` for token estimation
  - Budget calculation: `min(ctx_size - 1096, 3000)` for ctx ≤ 4096, else `ctx_size - 1096`
  - `PromptSection` dataclass with name, content, priority, mandatory, max_tokens
  - `add_section()`: Adds labeled prompt sections with priority metadata
  - `build()`: Assembles prompt within budget using priority-based trimming
  - `estimate_tokens(text)`: Returns `len(text) // 4`
  - Raises `ValueError` if mandatory sections alone exceed budget
  - Repo map BM25 filtering: truncates to entries with score > 1.5 when repo map > 400 tokens
  - Observation summarization: single-line format for all but 3 most recent when history > 2000 chars
  - Drops repo map entirely as last resort with logged warning
  - Trimming order: repo_map (priority 3) → context (priority 2) → history (priority 1)
  - Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6

- **Structured Communication Protocol**: Extended `mini_ai/core/communication.py` with three new classes for structured model communication:
  - `StructuredPromptFormatter`: Formats prompt sections with labeled delimiters [GOAL], [HISTORY], [CONTEXT], [TOOLS], [MEMORY], [REPO_MAP]. Mandatory sections ([GOAL], [TOOLS]) always included even if empty. Canonical ordering with support for extra sections. (Req 6.1)
  - `ResponseValidator`: Validates model JSON responses for parseable JSON with valid "action" key matching registered tool names. Tracks consecutive failures, provides nudge messages with JSON schema + concrete example, supports retry logic (simplify prompt after 3 failures, abort after 4). (Req 6.2, 6.3, 6.4, 6.5)
  - `ToolSuccessTracker`: Tracks per-session tool success/failure counts. Recommends top 3 tools with ≥5 invocations ordered by success-to-total ratio. Provides formatted hint string for system prompt. (Req 6.6)
  - Added `ToolSuccessRecord` dataclass, `SECTION_LABELS` and `MANDATORY_SECTIONS` constants
  - All existing code preserved (appended new classes at end of file)
  - Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6

- **Streaming Response Parser**: Created `mini_ai/core/streaming.py` with `StreamingActionParser` class for early JSON action detection:
  - `ParseEvent` enum: BUFFERING, ACTION_READY, INVALID_CANDIDATE, STREAM_END
  - `StreamingActionParser` class with brace-depth counter, string-state tracking, and buffer
  - `feed(token)`: Tracks brace depth character-by-character, handles escaped quotes and braces inside strings
  - Attempts JSON parse at each brace-depth-zero boundary
  - Validates parsed JSON against ToolSchema registry (checks "action" key matches registered tool, validates params)
  - Discards invalid candidates (bad JSON, unknown tool, failed schema validation) and continues buffering
  - `finish()`: Signals stream end, tries full-buffer parse as fallback, returns STREAM_END if no valid action found
  - `get_action()`: Returns the validated action dict when ACTION_READY
  - `get_reasoning_text()`: Returns full buffer as plain text when stream ends without valid action
  - `reset()`: Resets parser state for reuse
  - Requirements: 10.1, 10.2, 10.4, 10.5

- **Observation Compressor**: Added `ObservationCompressor` class to `mini_ai/core/communication.py`:
  - `compress(tool, output, success)`: Compresses outputs > 1000 chars to ≤ 500 chars using key info extraction (Req 12.1, 12.6)
  - Structured template format: `[TOOL_NAME] STATUS: success/fail | KEY_INFO: extracted_data` (Req 12.2)
  - `run_cmd` special handling: keeps first 200 + last 500 chars with `... [N characters truncated] ...` for outputs > 2000 chars (Req 12.3)
  - `deduplicate(observations)`: Replaces consecutive identical observations with `[repeated N times]` (Req 12.4)
  - `summarize_old(observations, budget_chars)`: Summarizes observations older than 3 turns into ≤ 200 char progress line when history > 60% of context budget (Req 12.5)
  - Key info extraction uses regex patterns for errors, file paths, line numbers
  - Progress summary extracts tool names and status from structured template format
  - Tests: 19 unit tests in `tests/test_observation_compressor.py` (all passing)
  - Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6

- **Workspace Index Incremental Rebuild**: Extended `mini_ai/core/workspace_index.py` with `WorkspaceIndexManager` class:
  - Integrates `DependencyGraph` and `FileChangeTracker` into workspace index workflow
  - `initialize()`: Builds/loads index and wires up dep_graph + change_tracker
  - `rebuild_incremental()`: Processes only changed-mtime files, removes deleted file entries, re-indexes affected files + direct importers
  - `lookup_function(name)`: Returns `FunctionLookupResult` with file, start_line, end_line, callers (supports qualified and unqualified names)
  - `get_callers(function_name)`: Returns list of callers within indexed workspace
  - `invalidate_file(rel_path)`: Invalidates cache for file + direct dependents, removes stale function mappings
  - `add_function_mapping()`: Manual function-to-file mapping with line numbers
  - Returns `FunctionLookupResult(found=False)` with empty fields for non-existent function names
  - Added `FunctionLookupResult` dataclass for structured lookup results
  - Cleaned up redundant local logger imports (now uses module-level logger)
  - Requirements: 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
  - Tests: 21 unit tests in `tests/test_workspace_index_manager.py` (all passing)

- **Enhanced Repo Map v2**: Extended `mini_ai/tools/repomap.py` with cross-reference support:
  - `classify_file_role(path, signatures)`: Assigns exactly one role from closed set {entry_point, utility, model, controller, test, config, unknown} based on path patterns and signature heuristics
  - `generate_repo_map_v2(root, goal, dep_graph, max_tokens)`: Goal-focused repo map with import edges, role annotations, and dependency-hop filtering
  - Filters to files within 2 dependency hops of highest-relevance file using DependencyGraph BFS
  - Falls back to entry_point files + 1 hop when no file scores above relevance threshold of 5
  - Handles syntax-error files gracefully (includes with role + [syntax-error] tag + partial edges)
  - Enforces max 400 tokens (1600 chars) with BM25 filtering above 1.5 threshold
  - BM25 scoring uses standard k1=1.5, b=0.75 parameters with IDF weighting
  - Existing `generate_repo_map()` preserved for backward compatibility
  - Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6

- **Dependency Graph**: Created `mini_ai/core/dep_graph.py` with `DependencyGraph` class for workspace intelligence:
  - `FunctionInfo` dataclass with file, name, start_line, end_line, callers
  - `build_from_index(workspace_index)`: Parses Python (from X import Y, import X) and JS/TS (import from, require()) statements from indexed files
  - `invalidate(changed_file)`: Returns `{file} ∪ {direct importers}` (one hop only)
  - `get_function_info(name)`: Returns FunctionInfo with file, lines, callers (supports qualified and unqualified lookup)
  - `files_within_hops(start, max_hops=2)`: BFS traversal over both forward and reverse edges
  - Builds forward (`_imports`) and reverse (`_importers`) maps
  - Resolves Python module paths (dot notation to file paths, relative imports)
  - Resolves JS/TS paths (relative imports, extension resolution, index files)
  - Requirements: 4.1, 4.2, 4.3, 4.4, 4.5

- **File Change Tracker**: Created `mini_ai/core/change_tracker.py` with `FileChangeTracker` class for session-based file modification tracking:
  - Uses `os.path.getmtime()` for efficient mtime comparison without full directory re-scans
  - `check_file(path)`: Compares stored vs disk mtime, returns True if changed, caches new mtime
  - `record_write(path)`: Updates mtime cache after executor writes a file
  - `get_modified_files()`: Returns max 50 most recent modified file paths (relative)
  - `should_reindex()`: Returns True when >20 files modified, triggering incremental re-index
  - `get_files_for_reindex(dep_graph)`: Returns modified files + direct importers from dependency graph
  - Handles cache update failures by invalidating entry and logging warning
  - Stores relative paths (forward-slash normalized) for cross-platform consistency
  - Requirements: 14.1, 14.2, 14.3, 14.5, 14.6, 14.7

- **Connection Pool**: Created `mini_ai/core/connection_pool.py` with three classes for optimized HTTP communication:
  - `ConnectionPool`: Thread-safe HTTP connection pool with configurable max connections (2 for agent, 4 general), keep-alive support, queuing when exhausted, and KV cache pre-warming via `pre_warm()`
  - `RetryPolicy`: Exponential backoff (1s, 2s, 4s) for 503 responses with max 3 retries, plus `RetryableError` exception class
  - `ReconnectionManager`: Polls health endpoint every 5s for up to 60s on connection loss
  - Factory helpers: `create_pool_for_agent()` (max 2) and `create_pool_general()` (max 4)
  - Uses stdlib `http.client` consistent with existing backend, thread-safe with `threading.Condition`

- **Lazy Module Loader**: Created `mini_ai/core/lazy_loader.py` with `LazyModule` class for deferred imports:
  - `__getattr__` proxy defers `importlib.import_module` until first attribute access
  - Tracks load time in `_load_time_ms`, logs WARNING if > 200ms
  - Handles import failures gracefully: logs WARNING, raises `AttributeError` on subsequent access
  - Updated `mini_ai/agents/agent.py` to use `LazyModule` for psutil, health_monitor, and rag imports
  - Reduces startup time by deferring heavy module loading until actually needed

- **Performance Config Fields**: Extended `Config` dataclass in `mini_ai/core/config.py` with 10 performance optimization fields:
  - `lazy_loading` (bool, default True), `token_budget_strict` (bool, default True), `batch_max_workers` (int, default 4)
  - `streaming_parse` (bool, default True), `grammar_adaptive` (bool, default True), `tool_routing` (bool, default True)
  - `self_healing` (bool, default True), `max_tools_per_turn` (int, default 8), `connection_pool_size` (int, default 4), `reconnect_timeout` (int, default 60)
  - All fields have sensible defaults, backward compatible with existing config loading

#### Done
- **Batch File Operations**: Added efficient bulk file operations for improved performance:
  - `batch_read_files`: Read multiple files in a single operation
  - `batch_delete_files`: Delete multiple files/directories at once
  - `batch_copy_paths`: Copy multiple files/directories in batch
  - `batch_move_paths`: Move/rename multiple files/directories in batch
  - Added schemas in `schemas.py` for all batch operations
  - Implemented tool handlers in `executor.py` with proper error handling and summaries
  - Operations report success/failure/skipped counts for transparency
  - Supports both files and directories in a single batch operation
- **Expanded Test Coverage**: Added comprehensive test suites:
  - `tests/test_executor.py`: Tests for ToolExecutor including batch operations, result truncation, JSON safety
  - `tests/test_commands.py`: Tests for CommandRouter including ChatHistory, slash commands, file operations
  - Tests cover batch_read_files, batch_delete_files, batch_copy_paths, batch_move_paths
  - Tests for schema validation of new batch operations
  - Tests for basic ToolExecutor functionality (result truncation, _to_json_safe, tool_answer)

#### Done
- **System Improvement Prompt**: Created `prompt.txt` with comprehensive guidelines to fix hallucinations and improve task execution:
  - Path handling rules (always use absolute paths, verify before use)
  - Task execution protocol (4 phases: Understanding, Planning, Execution, Verification)
  - UI visibility requirements (live command execution display, progress indicators)
  - Anti-hallucination measures (source verification, tool call discipline)
  - Structured response format with code citations
  - Error handling protocols
  - Workflow enforcement (read before edit, confirm before command)
  - **executor.py**: Auto-installs yt-dlp for music search when `assume_yes=True` (already implemented)
  - **audio_player.py**: Auto-installs python-vlc when audio playback starts (lines 23-38)
  - **music_player.py**: Auto-installs pygame for GUI music player when imported (lines 17-28)
  - **executor.py**: Enhanced _play_audio_file() to capture subprocess output and handle installation timeouts (lines 1197-1221)
  - System now waits 2 seconds for auto-installs to complete before checking subprocess status
  - All three dependency layers now handle missing packages gracefully
- **Audio Player Debugging & Wait Time Fix**: Enhanced audio player subprocess handling and error capture. Changes:
  - Increased wait time for auto-install from 2 seconds to 10 seconds (polling every 0.25s in a loop)
  - Better error capture and reporting from audio_player subprocess stderr
  - Added debug output to audio_player.py to show VLC module loading status
  - Better handling of subprocess timeout exceptions (now kills the process properly)
  - Now displays full error messages (up to 150 chars) to help diagnose issues
  - Executor now reports exact errors from audio player startup failures
  - Modified `tool_play_media()` in `executor.py` to detect ImportError for yt-dlp
  - When `assume_yes=True` and yt-dlp is missing, runs `pip install -q yt-dlp` automatically
  - Retries the music query after installation completes
  - Added `sys` import for subprocess execution
  - Users can now say "yes" to play music and yt-dlp will be installed automatically
- **GUI Works Without Models**: Fixed the GUI to allow workspace directory changes even when no models are found. Changes:
  - Modified `_load_config_bg()` in `gui.py` (line 527-540) to continue initialization instead of returning early when no model is found
  - Set `_config = None` and initialized `_memory` even without a model, allowing the app to function in read-only mode
  - Added system message: "No model loaded. You can still change workspace and configure settings."
  - Modified `_browse_workspace()` to retry config loading after directory change (useful if new dir contains models)
  - Users can now change directories and configure settings without a model loaded
- **Agent Refusal Fix**: Fixed issue where agent would refuse to help by saying "I cannot access your PC" instead of using available tools. Changes:
  - Added `_is_refusal()` check in `parse_action()` before treating text as answer (line 283-284 in agent.py)
  - Expanded refusal patterns to catch: "i can't directly", "i cannot access", "unable to access", "i'm sorry, but i can't", etc.
  - Added specific refusal nudge: "You refused to help... This is INCORRECT - you HAVE tools available"
  - Added Rule 13: "NEVER REFUSE: You CAN access files, run commands, and perform any task"
- **CopixTUI – Copilot/Codex-style Interface**: Created a new `copix_tui.py` module with a minimalist "tech-noir" aesthetic inspired by GitHub Copilot and OpenAI Codex. Now integrated into CLI:
  - **Usage**: `py run.py --copix` to enable the new interface
  - **Bug Fixes**:
    - Fixed `name 'args' is not defined` error: `repl()` function (line 381) was referencing `args` from global scope - changed to use `use_copix` parameter
    - Stored metrics config in local variables before try block (lines 510-512), updated finally block to use locals (lines 604-616)
    - **Fixed logging suppression**: `configure_logging()` now updates ALL existing logger levels (line 287-289), `get_logger()` uses global `_default_level` instead of hardcoded INFO (line 265)
  - Slim header with model name and ● LIVE indicator
  - Elegant ❯ prompt symbol in Copilot blue (#58a6ff)
  - Markdown rendering with automatic syntax highlighting (Python, JS, SQL, etc.)
  - Subtle "Generating..." spinner with throttled updates
  - Muted footer showing duration, tokens/sec, and content length
  - Auto-dimming of previous messages (the "Dim Rule")
  - Color palette: Microsoft Blue (#0078d4) and Copilot Purple (#a371f7)
  - **Integration**: Added `--copix` flag to CLI, `CommandRouter` uses CopixTUI when enabled, `repl()` uses ❯ prompt
- **Hybrid "Live Box" UI**: Replaced the rigid Dual-Pane split with a more natural sequential flow. Reasoning and planning now stream as standard terminal text, while active command execution is isolated in a dedicated, live-updating **Terminal Execution** box.
- **Improved Thought Visibility**: Thoughts and plans now stream in real-time even in sequential mode, ensuring transparency during the planning phase.
- **Refined Refusal Detection**: Fixed a bug where valid JSON actions containing words like "assist" or "help" were incorrectly flagged as refusals, causing premature agent termination.
- **Dual-Pane Agent UI (Legacy)**: Implemented a professional split-screen interface using `rich.Layout`. (Note: Now optional/fallback to Live Box mode).
- **Internal Windows `mkdir` Handler**: Intercepts `mkdir -p` and unquoted paths on Windows, using native Python `pathlib` for reliable directory creation.
- **Intelligent Windows Hints**: Added actionable guidance for common shell errors (syntax, quoting) to help models self-correct.
- **Fixed Real-time Thinking Display**: `update_agent_thoughts()` and `update_agent_terminal()` in `ui.py` were no-ops (line 345-347) - now they render THINKING and TERMINAL panels with rich/Markdown, plus buffer getters for CopixTUI integration
- **Fixed Memory Loading Bug**: `memory.py` had incorrect import `from .core import get_logger` (line 23) inside the core package - changed to `from .logger import get_logger`, also fixed `logger.warning` → `logger.warn`
- **Fixed cmd.exe Terminal Compatibility**: Added `_detect_terminal_capabilities()` in `copix_tui.py` to detect legacy Windows Command Prompt vs modern terminals (Windows Terminal, VS Code). For cmd.exe:
  - Unicode symbols (❯, ●, ◉) fall back to ASCII (>, *, >)
  - Rich Panels are replaced with simple text output (no box-drawing characters)
  - Live spinners replaced with simple "Generating..." text
  - Added `_Symbols` class for capability-aware symbol selection
- **Fixed Conversation Memory**: Resolved a bug where recent events were missing from AI context.

#### Next
- **Performance Optimization**: Continue with task 8.4 (Property tests for batch executor) and remaining execution/integration tasks
- **Workspace Explorer Sidebar**: Port the sidebar concept to a toggleable panel rather than a fixed dual-pane.

#### Done (Latest)
- **Multi-Action Executor**: Created `mini_ai/core/multi_action.py` with `MultiActionExecutor` class for batch action execution with dependency resolution:
  - `MAX_BATCH_SIZE = 10`: Rejects batches > 10 with clear error message (Req 9.7)
  - `_validate_dependencies()`: Checks for out-of-range indices, self-references, non-int deps, and circular dependencies using DFS cycle detection (Req 9.3)
  - `_topological_sort()`: Returns execution layers using Kahn's algorithm (BFS). Actions within a layer run in parallel, layers execute sequentially (Req 9.1, 9.2)
  - `execute_batch()`: Runs independent actions in parallel (ThreadPoolExecutor, max 4 workers), dependent actions sequentially after deps complete (Req 9.1)
  - `_get_transitive_dependents()`: BFS to find all actions transitively depending on a failed action
  - Failure propagation: Cancels all transitive dependents on action failure, continues independent actions (Req 9.6)
  - `ActionResult` dataclass: index, tool, success, output, cancelled fields
  - `BatchActionResult` dataclass: per-index results dict + cancelled list + summary property (Req 9.4)
  - Requirements: 9.1, 9.2, 9.3, 9.4, 9.6, 9.7

- **Self-Healing JSON Parser**: Created `mini_ai/core/self_healing.py` with `SelfHealingParser` class for automatic JSON repair from small model outputs:
  - `_fix_single_quotes()`: Character-by-character replacement of single quotes with double quotes, handles mixed-quote scenarios
  - `_fix_backslashes()`: Escapes unescaped Windows backslashes in JSON string values (e.g., `C:\Users\...` → `C:\\Users\\...`)
  - `_fix_trailing_commas()`: Removes trailing commas before `}` or `]`
  - `_fix_tool_name()`: Levenshtein distance ≤ 2 correction to exactly one valid tool; rejects ambiguous matches with candidate list
  - `parse(raw)`: Repair pipeline (single quotes → backslashes → trailing commas → re-parse, 1 attempt). Strips `<think>` blocks before parsing.
  - Extra fields not in tool schema are preserved in parsed dict (ignored during execution by executor)
  - `_correction_log` (Counter) tracks error types per session
  - `get_session_hints(min_count=2, top_k=3)`: Returns formatted hints for system prompt based on frequent corrections
  - Returns error with corrective example (tool-specific or generic) if repair fails
  - `reset()`: Clears correction log for new session
  - Pure Python Levenshtein implementation (no external dependencies)
  - Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7

- **RAG for Command Persistence**: Implemented command memory system to help agent remember successful patterns:
  - Created `command_memory.py` with `CommandMemory` class for storing/retrieving command patterns
  - Records command, cwd, exit code, timestamp, and context for each execution
  - Retrieves relevant patterns based on query similarity and directory matching
  - Integrates with `ToolExecutor` to record all command executions automatically
  - Enriches agent system prompt with successful command hints via `get_command_hints_for_prompt()`
  - Prunes old patterns (keeps 100 successful, 50 failed) to manage memory
  - Stores in `.mini_ai/command_memory.json` for persistence across sessions
- **Refined Terminal Box Layout**: Prevented flickering during high-velocity command output:
  - Added output batching system (`_cmd_output_buffer`, `_cmd_output_pending`)
  - 50ms batch intervals for smoother rendering via `_flush_cmd_output()`
  - `after_idle` scheduling to prevent layout thrashing when showing panel
  - Scrollback limiting (5000 chars) to prevent memory bloat
  - Single configure/insert/see/configure cycle for efficiency
- **Wired GUI Command Panel to Agent**: Full integration of live command execution:
  - `executor.py`: Added callback parameters (`on_command_start`, `on_command_output`, `on_command_end`) to `ToolExecutor`
  - `agent.py`: Added callback parameters to `agent_mode()` and pass them to `ToolExecutor`
  - `gui.py`: Implemented `_on_command_start_cb`, `_on_command_output_cb`, `_on_command_end_cb` that queue events
  - Updated `_drain_tokens()` to handle command events and update the live command panel
  - Commands now show live in the GUI with streaming output and exit codes
- **Integrated Prompt into Agent**: Modified `agent.py` to load and inject `prompt.txt` into system prompts via `_load_system_prompt()` function
- **Live Command Terminal in GUI**: Enhanced `gui.py` with collapsible command execution panel (`_cmd_panel`) showing:
  - Real-time command status with elapsed time
  - Live output streaming in scrollable text area
  - Show/hide helpers (`_show_cmd_panel`, `_hide_cmd_panel`, `_append_cmd_output`)
- **Progress Indicator System**: Added `_progress_label` to chat tab showing "Thinking...", "Reading..." status during operations
- **Path Verification Integration**: Enhanced `path_manager.py` with:
  - `verify_path_exists()` - verifies paths and suggests alternatives
  - `suggest_path_correction()` - generates helpful messages with directory listings
  - Updated `executor.py` `tool_read_files` to use new verification for better error messages

#### Done
- **RAG Grounding & Anti-Hallucination**: Integrated prompt grounding inside `agent_mode` using the `RAGManager`. Agent now retrieves relevant workspace snippets before generation, enriches prompts, and requires file-path citations when using retrieved context. This reduces hallucination and improves factual correctness.
- **Reviewer-based Task Verification**: Enhanced `orchestrator.py` tri-model flow to use `review_final_output()` with strict verification (confidence >= 0.6, zero issues). Tasks are re-attempted up to 2 times if review fails. Added `format_review()` display in orchestrator.
- **Citation Heuristics**: Added `_heuristic_citation_check()` to detect file-path citations in agent output. Planner now tags tasks requiring citations with "requires_citation" tag.
- **RAG Graceful Fallback**: Fixed HTTP 501 handling in `backend.get_embeddings()` to silently return empty vectors when embeddings aren't supported, allowing agent to continue without RAG-enhanced context. Updated `rag.py` to not log warnings for expected failures.

#### Notes
- **User Preference**: The user explicitly requested moving away from the dual-pane split to a more "Codex-style" interaction where thinking is sequential but execution is boxed.
- **Windows Stability**: Internal fallbacks for common shell commands (mkdir, touch) are much more reliable than trying to prompt the model to learn Windows syntax perfectly.
- **System Prompt**: `prompt.txt` contains authoritative behavior guidelines for the AI to prevent hallucinations and improve task execution. Now loaded into agent system prompts via `_load_system_prompt()`.
- **GUI Command Panel**: New live command execution panel in chat tab fully wired to agent:
  - `ToolExecutor` accepts callbacks: `on_command_start(cmd, cwd)`, `on_command_output(text)`, `on_command_end(exit_code)`
  - `agent_mode()` forwards callbacks from GUI to executor
  - GUI uses thread-safe queue to stream command output to UI in real-time
  - Panel shows command, working directory, elapsed time, and streaming output
  - **Flicker-free updates**: 50ms output batching, `after_idle` scheduling, scrollback limiting
- **Command Memory**: `command_memory.py` provides RAG-style command persistence:
  - Records all commands with cwd, exit code, timestamp, context
  - Retrieves relevant patterns based on query similarity and directory match
  - Enriches agent prompts with successful command hints
  - Stores in `.mini_ai/command_memory.json`, prunes old patterns (100 successful, 50 failed)
- **Path Verification**: `path_manager.py` now includes `verify_path_exists()` and `suggest_path_correction()` to detect hallucinated paths and suggest alternatives with directory listings.
- **CopixTUI Usage**:
  ```python
  from mini_ai.ui import CopixTUI
  
  copix = CopixTUI(model_name="Qwen 3")
  
  # Add user message
  copix.add_message("user", "Write a fibonacci function")
  copix.render()
  
  # Start generation
  copix.start_generation("Thinking")
  # ... stream tokens ...
  copix.end_generation(response_text, {"duration_ms": 1250, "tokens_per_sec": 45.2})
  copix.render()
  
  # Get user input with ❯ prompt
  user_input = copix.get_input()
  ```
