# Requirements Document

## Introduction

This document specifies requirements for optimizing and improving the mini_ai v39 project across four key areas: performance optimization for laptop hardware, improved file-to-function connections, enhanced model communication protocols, and reliable tool calling for arbitrary tasks. The system currently runs local LLMs (primarily Qwen2.5 3B) via llama-server and uses a text-wrapped tool calling approach with GBNF grammar enforcement.

## Glossary

- **Agent_Loop**: The main iterative cycle in `agent.py` where the model generates actions, the system executes them, and observations are fed back
- **Backend**: The `backend.py` module responsible for HTTP communication with llama-server and response caching
- **Context_Window**: The total token budget available to the model for processing (currently 4096–8192 tokens)
- **Executor**: The `executor.py` module that dispatches tool actions and returns structured observations
- **GBNF_Grammar**: A grammar format used by llama-server to constrain model output to valid JSON at the token-generation level
- **Observation**: A structured result returned to the model after tool execution, containing success status and output
- **Orchestrator**: The multi-phase agent that breaks complex goals into task graphs and routes them to specialized sub-agents
- **Prompt_Builder**: The system that constructs the full prompt from system text, repo map, session context, history, and user goal
- **RAG_Manager**: The Retrieval Augmented Generation module that chunks files and retrieves relevant snippets via embeddings
- **Repo_Map**: An AST-based summary of Python/JS function and class signatures used to give the model workspace awareness
- **Tool_Schema**: A structured definition of a tool's name, parameters, types, and validation rules
- **Workspace_Index**: A cached file tree with token extraction and relevance scoring for file discovery

## Requirements

### Requirement 1: Lazy Module Loading

**User Story:** As a developer running mini_ai on a laptop, I want the system to load modules only when needed, so that startup time is minimized and RAM usage stays low.

#### Acceptance Criteria

1. WHEN the application starts, THE Agent_Loop SHALL defer importing heavy modules (psutil, ast, RAG_Manager, HealthMonitor) until the first function call or class instantiation that requires them
2. WHEN a module is lazily loaded for the first time, THE Agent_Loop SHALL complete the import and make the module available for use within 200ms on a system with 8GB RAM and a spinning disk
3. THE Backend SHALL maintain a connection pool of no more than 2 persistent HTTP connections to llama-server, and SHALL NOT open additional connections when the pool is exhausted but instead queue requests until a connection becomes available
4. IF a lazily-loaded module fails to import, THEN THE Agent_Loop SHALL log the error at WARNING level, skip functionality provided by that module, and continue operating with remaining modules
5. IF a lazily-loaded module import exceeds 200ms, THEN THE Agent_Loop SHALL log a warning with the module name and actual load duration, and SHALL still complete the import without aborting
6. WHEN the application starts with all heavy modules deferred, THE Agent_Loop SHALL reach a ready-to-accept-input state within 2 seconds on a system with 8GB RAM

### Requirement 2: Prompt Token Budget Management

**User Story:** As a developer using a small model on limited hardware, I want the prompt to stay within strict token limits, so that the model does not experience slow pre-fill or context overflow.

#### Acceptance Criteria

1. IF the model context window is 4096 tokens or fewer, THEN THE Prompt_Builder SHALL enforce a total prompt size ceiling of 3000 tokens
2. WHEN the combined prompt exceeds the token budget, THE Prompt_Builder SHALL discard content sections in reverse priority order (repo map first, then session context, then observations beyond the 3 most recent entries) until the prompt fits within the budget, preserving system instructions and current goal unconditionally
3. THE Prompt_Builder SHALL measure prompt size by dividing the total character count of the assembled prompt by 4 and SHALL reject the prompt from being sent to the Backend if the resulting token estimate exceeds the configured token budget
4. WHEN the Repo_Map exceeds 400 tokens as measured by the 4:1 character-to-token ratio, THE Prompt_Builder SHALL truncate the Repo_Map to include only files with a BM25 relevance score above 1.5 for the current goal
5. IF the observation history exceeds 2000 characters, THEN THE Prompt_Builder SHALL summarize all observations except the 3 most recent into a single-line-per-observation format containing only the tool name and a success or failure indicator
6. IF the prompt still exceeds the token budget after applying all truncation and summarization rules, THEN THE Prompt_Builder SHALL drop the repo map section entirely and log a warning indicating the budget could not be met with all sections included

### Requirement 3: Parallel Batch Operations

**User Story:** As a developer working on multi-file tasks, I want the system to execute independent file operations in parallel, so that tasks complete faster on my laptop.

#### Acceptance Criteria

1. WHEN the Executor receives a batch_read_files action with 2 or more file paths (up to a maximum of 50 paths), THE Executor SHALL read all files concurrently using thread pooling with a maximum of 4 worker threads
2. WHEN the Executor receives a batch_write_files action with 2 or more files (up to a maximum of 50 files), THE Executor SHALL write files concurrently and return a consolidated result containing per-file status (success or failure), the file path, and an error reason for each failed file
3. THE Executor SHALL complete a batch of 10 file reads (each file up to 200KB in size) within 500ms on a system with SSD storage
4. IF any file in a batch operation fails, THEN THE Executor SHALL continue processing remaining files and return a partial result that lists each file's individual outcome (success with content, or failure with error reason) along with a summary count of succeeded and failed operations
5. IF a batch operation receives more than 50 file paths, THEN THE Executor SHALL reject the request and return an error indicating the batch size limit was exceeded

### Requirement 4: Intelligent Workspace Indexing

**User Story:** As a developer, I want the workspace index to accurately connect files to their functions and dependencies, so that the model receives relevant context for any task.

#### Acceptance Criteria

1. THE Workspace_Index SHALL extract import/require statements from Python, JavaScript, and TypeScript files to build a dependency graph that maps each file to the set of files it imports and the set of files that import it
2. WHEN a file is modified, THE Workspace_Index SHALL invalidate only the cache entries for that file and its direct dependents (files one level away in the dependency graph that import the modified file) within 100ms
3. THE Workspace_Index SHALL store function-to-file mappings for top-level functions, exported functions, and class methods, allowing lookup of which file defines a given function name along with its start and end line numbers
4. WHEN the model requests context for a specific function, THE Workspace_Index SHALL return the file path, line range (start line and end line), and list of callers within the indexed workspace
5. IF the model requests context for a function name that does not exist in the index, THEN THE Workspace_Index SHALL return an empty result set with an indication that no matching function was found
6. THE Workspace_Index SHALL rebuild incrementally by processing only files whose modification time has changed since the last index build, and SHALL remove index entries for files that no longer exist on disk
7. THE Workspace_Index SHALL support workspaces containing up to 10,000 indexable files and SHALL complete a full initial index build within 30 seconds for a workspace of that size

### Requirement 5: Enhanced Repo Map with Cross-References

**User Story:** As a developer, I want the repo map to show how files relate to each other, so that the model understands the project structure beyond just signatures.

#### Acceptance Criteria

1. THE Repo_Map SHALL include import relationships between files as directed edges (e.g., "agent.py → backend.py") by parsing import statements in Python (.py) and JavaScript/TypeScript (.js, .ts, .jsx, .tsx) files
2. THE Repo_Map SHALL annotate each file entry with exactly one role from the following closed set: "entry_point", "utility", "model", "controller", "test", "config", "unknown" — assigned based on filename patterns, directory location, and detected signatures
3. WHEN generating the Repo_Map for a specific goal, THE Repo_Map SHALL identify the most relevant file as the file with the highest relevance score from the Workspace_Index scoring function, and filter to show only files within 2 dependency hops (direct imports and their direct imports) of that file
4. IF no file scores above a relevance threshold of 5 for the current goal, THEN THE Repo_Map SHALL fall back to showing all entry_point files and their direct imports (1 hop)
5. THE Repo_Map SHALL complete generation for a workspace of 200 files within 2 seconds of wall-clock time on the host machine
6. IF a file cannot be parsed for signatures due to syntax errors or unsupported format, THEN THE Repo_Map SHALL still include the file with its role annotation and any import edges that were successfully extracted before the parse failure

### Requirement 6: Structured Model Communication Protocol

**User Story:** As a developer, I want the model to receive clear, structured context and return predictable responses, so that communication overhead is minimized and accuracy improves.

#### Acceptance Criteria

1. THE Prompt_Builder SHALL format all context sections using labeled delimiters (e.g., `[GOAL]`, `[HISTORY]`, `[CONTEXT]`) that the model can reference by name, including at minimum the sections: GOAL, HISTORY, CONTEXT, and TOOLS
2. WHEN the model produces a response, THE Backend SHALL validate that the response is parseable JSON containing an "action" key whose value matches a registered tool name before passing to the Executor
3. IF the model produces output that is not parseable JSON or lacks a valid "action" key, THEN THE Communication module SHALL respond with a nudge message that includes the exact JSON schema expected and a single concrete example of a valid response
4. WHEN the model produces an invalid response three consecutive times, THE Communication module SHALL retry by removing context sections not labeled as mandatory (HISTORY, CONTEXT) while preserving mandatory sections (GOAL, TOOLS), and re-sending the request
5. IF the model produces an invalid response after the simplified retry described in criterion 4, THEN THE Communication module SHALL abort the current action and return an error indication to the caller specifying that the model failed to produce a valid response
6. THE Communication module SHALL track per-session success and failure counts for each tool and, once a tool has been invoked at least 5 times in the session, include a "recommended tools" hint in the prompt listing the top 3 tools with the highest success-to-total ratio for the current task type

### Requirement 7: Adaptive Grammar Selection

**User Story:** As a developer using different model sizes, I want the grammar enforcement to adapt to model capability, so that capable models are not over-constrained and weak models are properly guided.

#### Acceptance Criteria

1. WHEN a model with fewer than 7 billion parameters is detected, THE Backend SHALL apply the THINK_JSON_GRAMMAR to enforce valid JSON output with an optional think block prefix
2. WHEN a model with 7 billion or more parameters is detected, THE Backend SHALL apply the JSON_ACTION_GRAMMAR that enforces a valid JSON action object without a mandatory think block prefix
3. WHEN a model file is loaded, THE Backend SHALL extract the parameter size from the GGUF filename by matching a numeric pattern followed by "B" (e.g., "3B", "7B", "14B") and store the detected size in the Config
4. IF the GGUF filename does not contain a recognizable size pattern, THEN THE Backend SHALL default to treating the model as having fewer than 7 billion parameters and apply the THINK_JSON_GRAMMAR
5. IF the applied grammar causes the model to produce empty output (null, empty string, or whitespace-only response) on 2 consecutive requests within the same session, THEN THE Backend SHALL disable grammar enforcement for the remainder of that session and rely on JSON parsing with repair to extract the action object from unstructured output

### Requirement 8: Tool Calling Reliability Pipeline

**User Story:** As a developer, I want tool calls to succeed reliably regardless of task complexity, so that the agent can autonomously complete multi-step workflows.

#### Acceptance Criteria

1. WHEN the model emits a JSON action, THE Executor SHALL validate all required parameters against the Tool_Schema before execution and SHALL reject the action without executing if any parameter fails type or presence checks
2. IF a required parameter is missing from a tool call, THEN THE Executor SHALL return a structured error response containing the tool name, a list of each missing parameter with its expected type, and a usage example showing the correct invocation format
3. WHILE the Agent_Loop is processing a session, THE Agent_Loop SHALL track a sliding window of the last 10 tool calls and SHALL detect an action loop when the same tool is called 3 times with identical parameters within that window, injecting a "loop detected" observation that names the repeated tool and instructs the model to use a different approach
4. IF a loop detection observation has been injected and the model repeats the same tool call a 4th consecutive time, THEN THE Agent_Loop SHALL temporarily remove that tool from the available tools list for the remainder of the current goal and append an observation listing alternative tools the model may use instead
5. WHEN a tool execution fails, THE Executor SHALL provide a recovery suggestion that maps the error category to a concrete next action, covering at minimum: file-not-found (suggest listing the parent directory), permission-denied (suggest verifying path or running with elevated access), timeout (suggest reducing scope or increasing timeout), and invalid-input (suggest re-reading the schema)
6. WHILE a per-session tool success registry is active, THE Agent_Loop SHALL disable any tool that has failed 3 consecutive times by excluding it from the system prompt tool list, and SHALL re-enable the tool when the model emits an action explicitly naming that tool with valid parameters, at which point the tool is re-added to the available list for one execution attempt
7. IF all tools in a required category (filesystem, execution, or output) become disabled simultaneously, THEN THE Agent_Loop SHALL re-enable the least-recently-disabled tool in that category and append an observation indicating the tool has been restored as a last resort

### Requirement 9: Multi-Action Planning Support

**User Story:** As a developer working on complex tasks, I want the model to plan and execute multiple related actions efficiently, so that multi-step tasks complete faster.

#### Acceptance Criteria

1. WHEN the model emits a JSON response containing an "actions" array with 2 to 10 action objects, THE Executor SHALL execute actions that have no "depends_on" field in parallel and actions that declare dependencies sequentially after their dependencies complete
2. THE Agent_Loop SHALL allow the model to declare action dependencies using a "depends_on" field containing a list of zero-based integer indices referencing previous actions within the same batch
3. IF a "depends_on" field references an index that is out of range or creates a circular dependency, THEN THE Executor SHALL reject the entire batch and return an error message indicating the invalid dependency structure
4. WHEN parallel actions complete, THE Executor SHALL aggregate all results into a single observation message where each result is keyed by its action index so the model can identify which result corresponds to which action
5. THE GBNF_Grammar SHALL be extended to support both single-action format (`{"action": ...}`) and multi-action format (`{"actions": [...]}`) while maintaining backward compatibility with existing single-action responses
6. IF any action in a multi-action batch fails, THEN THE Executor SHALL cancel all actions that directly or transitively depend on the failed action, continue executing independent actions, and return a partial result indicating per-action success or failure status
7. IF the "actions" array contains more than 10 actions, THEN THE Executor SHALL reject the batch and return an error message indicating the maximum batch size of 10 has been exceeded

### Requirement 10: Streaming Response Processing

**User Story:** As a developer on a laptop, I want the system to process model output as it streams, so that tool calls can begin executing before the full response is generated.

#### Acceptance Criteria

1. WHEN the Backend receives streaming tokens from llama-server, THE Agent_Loop SHALL maintain a brace-depth counter and attempt to parse a complete JSON action each time the brace depth returns to zero
2. WHEN a parsed JSON object passes ToolSchema validation, THE Executor SHALL begin execution within 50ms of detection while the Backend continues receiving any remaining stream tokens
3. WHEN a valid action has been extracted and the Executor has begun execution, THE Backend SHALL close the HTTP connection to llama-server to abort the remaining stream generation
4. IF the early-parsed JSON object fails ToolSchema validation, THEN THE Backend SHALL discard that candidate, continue receiving the full stream, and re-parse the complete output once the stream ends or a subsequent brace-depth-zero boundary is reached
5. IF the stream completes without yielding any JSON object that passes ToolSchema validation, THEN THE Backend SHALL treat the complete response as plain reasoning text and return it to the Agent_Loop for re-prompting
6. THE streaming parser SHALL add no more than 50ms latency compared to waiting for the full response, measured on actions whose closing brace appears within the first 50% of total generated tokens

### Requirement 11: Context-Aware Tool Routing

**User Story:** As a developer, I want the system to automatically select the right tools for each task type, so that the model does not waste turns using inappropriate tools.

#### Acceptance Criteria

1. WHEN the Orchestrator classifies a task as "code editing", THE Agent_Loop SHALL include only edit_blocks, read_files, run_cmd, and answer in the available tools
2. WHEN the Orchestrator classifies a task as "exploration", THE Agent_Loop SHALL include read_files, list_dir, workspace_scan, search_files, web_search, and answer in the available tools
3. WHEN the Agent_Loop assembles the tool set for a task AND the Workspace_Index detects a supported framework in the project, THE Agent_Loop SHALL add the corresponding framework-specific tools (e.g., laravel_create_project and git_init for Laravel) to the available tool set before the model's first generation turn
4. THE Agent_Loop SHALL present no more than 8 tools to the model in a single generation turn, counting all tools including the mandatory "answer" tool
5. IF the model attempts to call a tool not included in the current tool set AND an equivalent tool exists in the current set, THEN THE Executor SHALL return an error message indicating the requested tool is unavailable and naming the available alternative tool for the intended action
6. IF the model attempts to call a tool not included in the current tool set AND no equivalent tool exists in the current set, THEN THE Executor SHALL return an error message indicating the requested tool is unavailable and listing all currently available tools
7. IF the Orchestrator cannot classify a task into a defined category, THEN THE Agent_Loop SHALL fall back to the default "agent" tool set containing read_files, list_dir, run_cmd, write_files, edit_blocks, and answer

### Requirement 12: Efficient Observation Compression

**User Story:** As a developer, I want tool outputs to be compressed intelligently before being fed back to the model, so that the context window is used efficiently.

#### Acceptance Criteria

1. WHEN a tool output exceeds 1000 characters, THE Communication module SHALL compress it to a maximum of 500 characters by extracting error messages, file paths, line numbers, and success/failure indicators from the output
2. THE Communication module SHALL format compressed observations using the structured template: `[TOOL_NAME] STATUS: success/fail | KEY_INFO: extracted_data`
3. WHEN a run_cmd tool returns output exceeding 2000 characters, THE Communication module SHALL keep the first 200 characters and last 500 characters separated by the truncation indicator `... [N characters truncated] ...` where N is the number of omitted characters
4. THE Communication module SHALL detect consecutive observations containing identical output strings (exact character match) and replace duplicates with a single instance followed by a repetition count in the format `[repeated N times]`
5. IF the total observation history exceeds 60% of the available context budget measured in characters, THEN THE Prompt_Builder SHALL summarize all observations older than 3 turns into a single progress summary line of no more than 200 characters
6. IF a tool output is 1000 characters or fewer, THEN THE Communication module SHALL pass the output through unmodified in the structured template format

### Requirement 13: Connection Pool and Request Optimization

**User Story:** As a developer on a laptop, I want HTTP communication with llama-server to be optimized, so that network overhead does not slow down the agent loop.

#### Acceptance Criteria

1. THE Backend SHALL reuse HTTP connections across requests by including a "Connection: keep-alive" header on every request and maintaining a connection pool of up to 4 concurrent connections per server endpoint
2. WHEN llama-server reports ready on its health endpoint after startup, THE Backend SHALL send a single request with an empty prompt and n_predict set to 1 to pre-warm the KV cache before accepting agent requests
3. WHEN the model is generating a response, THE Backend SHALL set a read timeout of 600 seconds to accommodate slow generation on CPU-only hardware
4. IF llama-server returns a 503 (busy) status, THEN THE Backend SHALL retry the request using exponential backoff starting at 1 second and doubling each interval, for a maximum of 3 retry attempts, before raising an error to the caller
5. IF the Backend receives no HTTP response or a connection-refused error from llama-server during a session, THEN THE Backend SHALL attempt automatic reconnection by polling the server health endpoint every 5 seconds for up to 60 seconds before reporting failure to the caller

### Requirement 14: Workspace File Change Tracking

**User Story:** As a developer, I want the system to track which files have changed during a session, so that the model always works with current file contents.

#### Acceptance Criteria

1. THE Workspace_Index SHALL use filesystem modification timestamps (mtime) to detect changed files by comparing stored mtime values against current disk mtime values when a file is accessed, without requiring a full directory tree re-scan
2. WHEN the Executor writes or edits a file, THE Workspace_Index SHALL update its cache entry (content, mtime, and size) for that file within 500 milliseconds of the write operation completing
3. THE Session_Memory SHALL maintain a list of files modified during the current session (storing relative file paths) and include this list in the context provided to the model, limited to the most recent 50 entries if the total exceeds 50
4. WHEN the model requests to read a file that was modified in the current session, THE Executor SHALL read from disk (bypassing any stale cache) and annotate the observation with "recently modified"
5. IF more than 20 files are modified in a single session, THEN THE Workspace_Index SHALL trigger an incremental re-index limited to the modified files and files that directly import or reference them, completing within 10 seconds
6. WHEN a file's mtime on disk differs from the cached mtime at the time the Executor reads that file, THE Workspace_Index SHALL treat the file as externally modified, update its cache entry, and add the file to the Session_Memory modified-files list
7. IF the Workspace_Index cache update fails for any file, THEN THE Workspace_Index SHALL log the failure and invalidate the cache entry for that file so that subsequent reads fall through to disk

### Requirement 15: Tool Calling Self-Healing

**User Story:** As a developer using small models, I want the system to automatically fix common tool calling errors, so that tasks succeed without manual intervention.

#### Acceptance Criteria

1. WHEN the model produces JSON with single quotes instead of double quotes, THE Agent_Loop SHALL replace single quotes with double quotes and re-parse the JSON before passing to the Executor
2. WHEN the model produces a tool name that is a close match (Levenshtein distance ≤ 2) to exactly one valid tool name in the Tool_Schema registry, THE Agent_Loop SHALL correct the tool name to the matching valid name and proceed with execution
3. IF the model produces a tool name with Levenshtein distance ≤ 2 to more than one valid tool name, THEN THE Agent_Loop SHALL reject the call and return an error message indicating the ambiguous match along with the list of candidate tool names
4. WHEN the model includes extra fields not defined in the Tool_Schema, THE Executor SHALL ignore unknown fields and execute with the valid parameters only
5. IF the model produces a Windows path with unescaped backslashes in JSON, THEN THE Agent_Loop SHALL escape the backslashes before JSON parsing
6. IF JSON repair (single-quote replacement, backslash escaping, trailing comma removal) fails after 1 re-parse attempt, THEN THE Agent_Loop SHALL return an error message indicating the parse failure and include a corrective example showing valid JSON syntax for the attempted tool
7. THE Agent_Loop SHALL maintain a per-session error correction log that resets when a new agent_mode session starts, and SHALL include the top 3 corrections (each occurring at least 2 times) as structured hints appended to the system prompt to help the model avoid repeating the same errors within the session
