# Bugfix Requirements Document

## Introduction

Mini-AI v39 suffers from five interconnected architectural defects that degrade performance, maintainability, and reliability on the target hardware (Intel i5, 4GB RAM, 3B parameter models). The monolithic agent.py (~1500 lines), tightly coupled components, scattered tool-calling logic, ineffective RAG retrieval, and heuristic-based success detection all contribute to slower execution, duplicated code paths, and unreliable behavior. Speed is the primary concern — every extra token adds ~100ms of pre-fill time on this hardware.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN the agent loop executes THEN the system loads all prompt building, JSON parsing, streaming handlers, loop detection, retry logic, and tool execution coordination from a single 1500-line agent.py file, causing slow code navigation, impossible unit testing of individual concerns, and increased cognitive load for maintenance

1.2 WHEN tool_read_files is called in executor.py THEN the system embeds RAG strategy decisions (decide_strategy, retrieve_relevant_snippets) directly inside the tool execution method, coupling retrieval logic to the executor and preventing independent optimization of either component

1.3 WHEN the agent loop detects tool call loops THEN the system uses BOTH inline loop detection in agent.py (action_history list, action_name_list, consecutive_parse_fails counter) AND the LoopDetector class in tool_reliability.py, creating duplicated detection logic with inconsistent thresholds and behavior

1.4 WHEN RAGManager.retrieve_relevant_snippets() is called THEN the system calls get_embeddings() separately for EACH chunk of EACH file, making N+1 embedding API calls (1 for query + N for chunks) which is extremely slow on local hardware where each embedding call has significant latency

1.5 WHEN embeddings are unavailable (the common case on low-end hardware without embedding models) THEN the system returns an empty list from retrieve_relevant_snippets(), causing RAG to provide zero context enrichment and effectively disabling the entire RAG feature

1.6 WHEN the orchestrator evaluates task execution results THEN the system uses heuristic string matching ("failed" in result.lower()) to determine success or failure, causing false positives (e.g., "the test that previously failed now passes") and false negatives (e.g., errors without the word "failed")

1.7 WHEN the _generate_with_retry function executes THEN the system performs up to 3 separate LLM generation calls per step on empty output (grammar → no-grammar → nudge), each adding full pre-fill latency (~100ms per token × ~500 tokens = ~50 seconds per retry) without any fast-path short-circuit for known-good scenarios

1.8 WHEN the model outputs a tool call action THEN the system relies on scattered parsing logic across agent.py (parse_action, _try_extract_json, _generate_with_retry), self_healing.py (SelfHealingParser), and tool_reliability.py (SchemaValidator) without a unified pipeline, causing inconsistent error handling where some parse failures trigger retries, some trigger self-healing, and some silently fall through to "treat as answer"

1.9 WHEN the model outputs text that contains narration mixed with a valid JSON action (e.g., "Let me run this command: {"action": "run_cmd", ...}") THEN the system's parse_action function may incorrectly classify it as narration (returning None) due to the heuristic check for phrases like "let me" occurring before the JSON extraction attempt, causing valid tool calls to be dropped

### Expected Behavior (Correct)

2.1 WHEN the agent loop executes THEN the system SHALL load agent orchestration from a lean coordinator module (~200 lines) that delegates to separate focused modules for prompt assembly (micro_prompts.py), JSON parsing (self_healing.py), streaming (streaming.py), and retry logic (a dedicated retry module), each independently testable

2.2 WHEN tool_read_files is called THEN the system SHALL delegate all RAG decisions to a separate context injection layer that the executor calls via a clean interface (e.g., context_injector.enrich(path, content, query)), decoupling retrieval strategy from tool execution

2.3 WHEN the agent loop detects tool call loops THEN the system SHALL use ONLY the LoopDetector class from tool_reliability.py as the single source of truth for loop detection, removing all inline loop detection code from agent.py

2.4 WHEN RAGManager.retrieve_relevant_snippets() is called THEN the system SHALL batch all chunks into a single embedding call (or use a pre-computed index) to minimize API round-trips, reducing N+1 calls to at most 2 calls (1 for query, 1 batched for all chunks)

2.5 WHEN embeddings are unavailable THEN the system SHALL fall back to a fast keyword/TF-IDF-based retrieval method that provides meaningful context snippets without requiring embedding models, ensuring RAG always contributes useful context

2.6 WHEN the orchestrator evaluates task execution results THEN the system SHALL use structured result objects with explicit success/failure fields (e.g., {"success": bool, "output": str}) parsed from the executor's JSON response, not string pattern matching

2.7 WHEN _generate_with_retry encounters an empty response THEN the system SHALL first attempt a zero-cost recovery (re-send with temperature bump or seed change) before falling back to expensive grammar-removal or nudge retries, and SHALL skip retries entirely when the previous step succeeded (indicating the model is responsive)

2.8 WHEN the model outputs a tool call action THEN the system SHALL process it through a single unified tool-calling pipeline with clear stages: (1) extract JSON from raw output, (2) attempt self-healing repair if extraction fails, (3) validate against schema, (4) route to executor — with each stage having a single responsible module and no fallthrough to "treat as answer" unless all stages explicitly fail

2.9 WHEN the model outputs text that contains narration mixed with a valid JSON action THEN the system SHALL prioritize JSON extraction over narration detection, attempting to extract and validate the JSON action BEFORE checking for narration heuristics, ensuring valid tool calls embedded in explanatory text are never dropped

### Unchanged Behavior (Regression Prevention)

3.1 WHEN the micro-prompt system assembles prompts for TASK/QUERY/EDIT/EXPLORE intents THEN the system SHALL CONTINUE TO produce prompts within the ~500 token budget with the same structure (Goal/Tools/Context/Example/Output JSON)

3.2 WHEN tool execution succeeds or fails THEN the system SHALL CONTINUE TO return the same JSON observation format ({"success": bool, "output": str}) to the agent loop

3.3 WHEN the ToolRouter selects tools for a task type THEN the system SHALL CONTINUE TO cap at 8 tools per turn and always include "answer" in the available set

3.4 WHEN the connection pool manages HTTP connections to llama-server THEN the system SHALL CONTINUE TO use persistent keep-alive connections with the same retry policy (exponential backoff on 503, max 3 retries)

3.5 WHEN the SelfHealingParser repairs malformed JSON THEN the system SHALL CONTINUE TO handle single quotes, trailing commas, backslash escaping, and tool name correction (Levenshtein ≤ 2)

3.6 WHEN config flags (use_micro_prompts, self_healing, tool_routing, etc.) are set to False THEN the system SHALL CONTINUE TO fall back to the original monolithic behavior without errors

3.7 WHEN the ToolDisabler disables a tool after 3 consecutive failures THEN the system SHALL CONTINUE TO protect required categories (filesystem, execution, output) by re-enabling the LRU tool as a last resort

3.8 WHEN the agent processes COMPLEX intent tasks THEN the system SHALL CONTINUE TO use the full monolithic prompt system with complete context (repo map, session, memory) rather than micro-prompts

3.9 WHEN the system constructs prompts for any intent THEN the system SHALL ensure all system prompt templates (PromptAssembler.SYSTEM_PROMPT and any role-specific preambles) remain at or below 60 tokens (estimated as len(text) // 4) — modifications are permitted only if the result stays within this budget

3.10 WHEN the GBNF grammar (MINIMAL_JSON_GRAMMAR) constrains model output THEN the system SHALL CONTINUE TO enforce the same JSON structure ({"action": tool_name, ...params}) without modifying the grammar definition

3.11 WHEN tool calling succeeds on the first attempt (valid JSON, valid schema) THEN the system SHALL CONTINUE TO execute immediately without any additional parsing overhead or pipeline stages beyond what currently exists

## Detailed Requirements

### Requirement 1: Monolithic Agent Structure Decomposition

**User Story:** As a developer, I want the agent loop to be decomposed into focused modules, so that I can independently test and optimize each concern without navigating a 1500-line file.

#### Acceptance Criteria

1. WHEN the agent loop executes, THEN the system loads agent orchestration from a coordinator module of no more than 300 lines (excluding blank lines and comments) that delegates to separate focused modules for prompt assembly (micro_prompts.py), JSON parsing (self_healing.py), streaming (streaming.py), and retry logic (a dedicated retry module), where each module is importable and callable without instantiating the full agent loop
2. WHEN the agent loop detects tool call loops, THEN the system uses ONLY the LoopDetector class from tool_reliability.py as the single source of truth for loop detection, removing all inline loop detection code from agent.py including the action_history list, action_name_list, strict_repeat_count checks, and consecutive_name_repeats threshold logic
3. WHEN the model outputs a tool call action, THEN the system processes it through a single unified tool-calling pipeline with sequential stages: (1) extract JSON from raw output via _try_extract_json, (2) if extraction fails, attempt self-healing repair via SelfHealingParser.parse returning a repaired dict or None, (3) if a dict is returned, validate the "action" field against the registered tool schema names, (4) if valid, route to ToolExecutor.execute — where each stage returns an explicit success-or-failure result and the output is treated as "no valid action" only after all three parsing stages (extract, heal, validate) return failure
4. WHEN the model outputs text that contains narration mixed with a valid JSON action, THEN the system attempts JSON extraction (brace-matching scan for a dict containing an "action" key) and validates the extracted JSON BEFORE evaluating narration heuristics (the "i will", "first,", "step 1" keyword list), so that a valid JSON action embedded in narration text is executed rather than discarded

### Requirement 2: RAG Coupling and Effectiveness

**User Story:** As a developer, I want RAG to be decoupled from the executor and always provide useful context, so that the agent gets relevant workspace information regardless of whether embedding models are available.

#### Acceptance Criteria

1. WHEN tool_read_files is called, THEN the system SHALL delegate all RAG decisions to a separate context injection layer that the executor invokes through a defined interface accepting file path, file content, and query string as inputs and returning a list of scored context snippets, with no retrieval logic remaining in the executor module
2. WHEN RAGManager.retrieve_relevant_snippets() is called, THEN the system SHALL batch all chunks into a single embedding call (or use a pre-computed index) to produce at most 2 API round-trips (1 for the query embedding, 1 batched for all chunk embeddings), completing the retrieval within 5 seconds for files up to 100 KB on the target hardware
3. WHEN embeddings are unavailable, THEN the system SHALL fall back to a keyword/TF-IDF-based retrieval method that returns between 1 and 5 ranked snippets (each no longer than 1500 characters) scored by term-frequency relevance to the query, completing within 500 milliseconds for files up to 100 KB
4. IF both embedding-based retrieval and keyword/TF-IDF fallback fail to produce any snippets (due to errors or empty input), THEN the system SHALL return the first 3000 characters of the file content as a raw context block and log a warning indicating the retrieval failure reason
5. WHEN the context injection layer returns snippets, THEN each snippet SHALL include the source file path, a relevance score between 0.0 and 1.0, and the character offset range within the source file, enabling the caller to verify snippet origin

### Requirement 3: Speed-First Retry and Generation

**User Story:** As a developer, I want the retry logic to minimize expensive LLM calls and short-circuit when possible, so that the agent responds faster on constrained hardware.

#### Acceptance Criteria

1. WHEN _generate_with_retry encounters an empty response AND the immediately preceding agent loop step produced a non-empty response, THEN the system SHALL skip all retries and return None (short-circuit), because the model is known to be responsive and the empty output indicates a prompt issue rather than a generation failure
2. WHEN _generate_with_retry encounters an empty response AND the previous step did NOT produce a non-empty response, THEN the system SHALL first attempt up to 1 zero-cost recovery (re-sending the same prompt with a temperature increase of 0.1 or a changed random seed, requiring no grammar recompilation and no prompt modification) before falling back to grammar-removal or nudge retries
3. IF the zero-cost recovery attempt also returns an empty response, THEN the system SHALL proceed to the existing retry cascade (grammar-removal, then nudge retry) and count both the original empty and the zero-cost empty toward the consecutive empties threshold of 2
4. WHEN the orchestrator evaluates task execution results, THEN the system SHALL determine success or failure exclusively by reading the "success" boolean field from the executor's JSON response object (which contains at minimum the fields "success": bool and "output": str), and SHALL NOT use string pattern matching such as substring checks on the output text
5. IF the executor's JSON response cannot be parsed or the "success" field is missing, THEN the system SHALL treat the result as a failure and include the raw output in the observation for debugging
