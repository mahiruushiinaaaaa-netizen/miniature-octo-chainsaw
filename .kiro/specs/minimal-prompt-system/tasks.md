# Implementation Plan: Minimal Prompt System

## Overview

Replace the monolithic prompt architecture with an ultra-lean modular design optimized for 3B parameter models. The implementation creates a new `mini_ai/core/micro_prompts.py` module containing `MicroPromptTemplate`, `MicroPromptRegistry`, and `PromptAssembler`, adds a `MINIMAL_JSON_GRAMMAR` to the existing grammars module, and integrates the new system into the agent loop.

## Tasks

- [x] 1. Create MicroPromptTemplate dataclass and validation
  - [x] 1.1 Create `mini_ai/core/micro_prompts.py` with the `MicroPromptTemplate` frozen dataclass
    - Define the frozen dataclass with fields: intent, template, one_shot_example, available_tools, max_prompt_tokens, max_gen_tokens
    - Implement `__post_init__` validation: intent must be one of TASK/QUERY/EDIT/EXPLORE/COMPLEX; template must contain `{goal}`; one_shot_example must be valid JSON with "action" key; available_tools must be non-empty (1-20 items); max_prompt_tokens in [200, 1000]; max_gen_tokens in [64, 512]
    - Raise `ValueError` with descriptive message on validation failure
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

  - [-]* 1.2 Write property test for MicroPromptTemplate validation
    - **Property 10: Template Validation**
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**

  - [-]* 1.3 Write unit tests for MicroPromptTemplate
    - Test valid construction succeeds
    - Test immutability (frozen=True raises FrozenInstanceError on assignment)
    - Test each validation rule rejects invalid input with appropriate error message
    - _Requirements: 1.7, 1.8_

- [x] 2. Implement MicroPromptRegistry
  - [x] 2.1 Implement `MicroPromptRegistry` class in `mini_ai/core/micro_prompts.py`
    - Implement `__init__` with `_templates: dict[str, MicroPromptTemplate]` and call `_register_defaults()`
    - Implement `get(intent)` returning the matching template or EXPLORE as fallback (handles None, empty string, unknown intents)
    - Implement `register(template)` to add/override templates
    - Implement `_register_defaults()` with built-in templates for TASK, QUERY, EDIT, EXPLORE intents with appropriate one-shot examples and tool lists
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [-]* 2.2 Write property test for Registry idempotence
    - **Property 7: Registry Idempotence**
    - **Validates: Requirements 2.5**

  - [-]* 2.3 Write property test for unknown intent fallback
    - **Property 8: Unknown Intent Fallback**
    - **Validates: Requirements 2.3, 8.2**

  - [-]* 2.4 Write property test for valid intent returns matching template
    - **Property 9: Valid Intent Returns Matching Template**
    - **Validates: Requirements 2.2**

- [x] 3. Implement PromptAssembler with token budget enforcement
  - [x] 3.1 Implement `PromptAssembler` class in `mini_ai/core/micro_prompts.py`
    - Define `SYSTEM_PROMPT` constant (~50 tokens, ≤60 estimated)
    - Implement `estimate_tokens(text)` as `len(text) // 4`
    - Implement `assemble(intent, goal, last_result, step)` following the assembly algorithm from design
    - Implement `aggressive_truncate(text, max_tokens)` with "..." indicator
    - On step 1 or last_result is None: include one_shot_example
    - On step > 1 with last_result: include compact last_result (≤300 chars), exclude example
    - Enforce token budget: truncate context first, then goal, preserving at least first 50 chars of goal
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9_

  - [-]* 3.2 Write property test for token budget invariant
    - **Property 1: Token Budget Invariant**
    - **Validates: Requirements 3.3, 4.2, 4.5, 4.6, 4.7, 4.8**

  - [-]* 3.3 Write property test for system prompt constancy
    - **Property 2: System Prompt Constancy**
    - **Validates: Requirements 3.1, 4.4**

  - [-]* 3.4 Write property test for goal preservation
    - **Property 3: Goal Preservation**
    - **Validates: Requirements 3.2, 3.7**

  - [-]* 3.5 Write property test for one-shot example on first step
    - **Property 4: One-Shot Example on First Step**
    - **Validates: Requirements 3.4**

  - [-]* 3.6 Write property test for last result replaces example
    - **Property 5: Last Result Replaces Example on Subsequent Steps**
    - **Validates: Requirements 3.5**

  - [ ]* 3.7 Write property test for no bloat on TASK intent
    - **Property 13: No Bloat for TASK Intent**
    - **Validates: Requirements 6.3**

  - [ ]* 3.8 Write property test for token estimation consistency
    - **Property 11: Token Estimation Consistency**
    - **Validates: Requirements 4.1**

  - [ ]* 3.9 Write property test for truncation indicator
    - **Property 12: Truncation Indicator**
    - **Validates: Requirements 4.3**

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement GBNF grammar selection
  - [x] 5.1 Add `MINIMAL_JSON_GRAMMAR` to `mini_ai/core/grammars.py`
    - Create a simplified grammar without the mandatory "plan" field
    - Grammar enforces: `{"action": tool_name, ...params}` format
    - Include all registered tool names in the `tool_name` production rule
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 9.2_

  - [x] 5.2 Implement `select_grammar_for_intent(intent)` in `mini_ai/core/micro_prompts.py`
    - TASK/QUERY/EXPLORE → return `MINIMAL_JSON_GRAMMAR`
    - EDIT → return None (free-form SEARCH/REPLACE)
    - COMPLEX → return `MINIMAL_JSON_GRAMMAR`
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ]* 5.3 Write property test for grammar enforcement per intent
    - **Property 6: Grammar Enforcement for JSON Intents**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**

  - [ ]* 5.4 Write property test for generation token limits per intent
    - **Property 14: Generation Token Limits per Intent**
    - **Validates: Requirements 7.2**

- [x] 6. Implement sensitive data filtering and prompt safety
  - [x] 6.1 Add sensitive data detection to `PromptAssembler`
    - Implement pattern matching for: "sk-", "ghp_", "AKIA" prefixes; env variable references; password/secret/token field values
    - Replace detected sensitive values with `[REDACTED]` placeholder
    - Ensure System_Prompt contains only role/format instructions, no secrets
    - _Requirements: 9.1, 9.3, 9.4_

  - [ ]* 6.2 Write unit tests for sensitive data filtering
    - Test detection of API key patterns (sk-, ghp_, AKIA)
    - Test environment variable reference detection
    - Test password/secret/token field value detection
    - Test that redaction placeholder is applied correctly
    - _Requirements: 9.1, 9.4_

- [x] 7. Integrate with agent loop
  - [x] 7.1 Refactor `agent_mode()` in `mini_ai/agents/agent.py` to use `PromptAssembler`
    - Import `MicroPromptRegistry`, `PromptAssembler`, `select_grammar_for_intent` from `mini_ai.core.micro_prompts`
    - Create registry and assembler instances at agent loop start
    - Replace `_build_system_prompt()` call with `assembler.assemble()` for prompt construction
    - Pass `select_grammar_for_intent(intent)` as grammar to `generate()` call
    - Set `max_tokens` from template's `max_gen_tokens` value
    - Keep existing fallback to old system for COMPLEX intent or when micro-prompt system is disabled via config
    - _Requirements: 6.2, 6.3, 6.4, 7.1, 7.2, 7.3_

  - [x] 7.2 Add config flag `use_micro_prompts` to `mini_ai/core/config.py`
    - Add boolean field `use_micro_prompts: bool = True` to Config dataclass
    - When False, agent falls back to existing `_build_system_prompt()` behavior
    - _Requirements: 6.2_

  - [ ]* 7.3 Write unit tests for agent loop integration
    - Test that assembler is used when `use_micro_prompts=True`
    - Test fallback to old system when `use_micro_prompts=False`
    - Test grammar is passed correctly to generate()
    - _Requirements: 6.2, 6.3, 7.1_

- [x] 8. Implement error handling and resilience
  - [x] 8.1 Add retry logic for empty model output in agent loop
    - On empty/whitespace output with grammar: retry once without grammar
    - On second empty output: return nudge prompt with one-shot example and retry once more
    - On invalid JSON despite grammar: pass to existing `SelfHealingParser`
    - On SelfHealingParser failure: re-prompt with one-shot example appended, retry with grammar
    - Add consecutive empty response counter; disable grammar after 2 consecutive empties
    - Validate parsed action against registered tool name list when grammar is disabled
    - _Requirements: 8.1, 8.3, 8.4, 8.5, 8.6, 5.6, 5.7, 9.5_

  - [ ]* 8.2 Write unit tests for error handling paths
    - Test retry without grammar on empty output
    - Test nudge prompt on second empty output
    - Test SelfHealingParser integration on invalid JSON
    - Test grammar disable after 2 consecutive empties
    - Test tool name validation when grammar disabled
    - _Requirements: 8.3, 8.4, 8.5, 8.6, 9.5_

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Wire everything together and final integration
  - [x] 10.1 Add module exports to `mini_ai/core/__init__.py`
    - Export `MicroPromptTemplate`, `MicroPromptRegistry`, `PromptAssembler`, `select_grammar_for_intent` from `micro_prompts`
    - Export `MINIMAL_JSON_GRAMMAR` from `grammars`
    - _Requirements: 6.2_

  - [ ]* 10.2 Write integration test for end-to-end prompt assembly
    - Test full flow: intent → registry lookup → assemble → verify token count and grammar selection
    - Test with various goal lengths (short, medium, very long) to verify truncation
    - Test multi-step scenario (step 1 with example, step 2+ with last_result)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.2, 5.1_

  - [ ]* 10.3 Write property test for intent classifier valid output
    - **Property 15: Intent Classifier Valid Output**
    - **Validates: Requirements 6.1**

- [x] 11. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The new module `mini_ai/core/micro_prompts.py` is the primary new file; existing files (`grammars.py`, `agent.py`, `config.py`) receive targeted modifications
- The config flag `use_micro_prompts` allows gradual rollout and easy rollback
- All property tests use the `hypothesis` library (already in the project's `.hypothesis/` directory)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "3.4", "3.5", "3.6", "3.7", "3.8", "3.9", "5.1"] },
    { "id": 4, "tasks": ["5.2", "5.3", "5.4", "6.1"] },
    { "id": 5, "tasks": ["6.2", "7.1", "7.2"] },
    { "id": 6, "tasks": ["7.3", "8.1"] },
    { "id": 7, "tasks": ["8.2", "10.1"] },
    { "id": 8, "tasks": ["10.2", "10.3"] }
  ]
}
```
