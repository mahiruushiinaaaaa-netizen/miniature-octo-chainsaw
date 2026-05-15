# Requirements Document

## Introduction

The Minimal Prompt System replaces the monolithic prompt architecture in mini_ai with an ultra-lean, modular design optimized for 3B parameter models running on constrained hardware (i5-10210U, 8GB RAM). The system enforces strict token budgets, uses task-specific micro-prompt templates, and leverages GBNF grammar enforcement to achieve 10-20 second response times instead of the current 188+ seconds.

## Glossary

- **PromptAssembler**: The component responsible for combining system prompt, micro-prompt template, goal, and context into a final prompt string within token budget constraints.
- **MicroPromptTemplate**: An immutable data structure defining a task-type-specific prompt template with slots for dynamic content, a one-shot example, and available tool names.
- **MicroPromptRegistry**: A registry that stores and retrieves MicroPromptTemplate instances indexed by intent type.
- **IntentClassifier**: The existing component that classifies user goals into intent types (TASK, QUERY, EDIT, EXPLORE, COMPLEX).
- **GBNF_Grammar**: A grammar specification that constrains model output to valid JSON action format.
- **Token_Budget**: The maximum number of estimated tokens allowed for an assembled prompt, enforced as a hard cap.
- **System_Prompt**: The constant 2-3 line prompt (~50 tokens) that never changes across any request.
- **One_Shot_Example**: A single concrete JSON example included in the prompt to demonstrate expected output format.
- **Intent**: A classification label (TASK, QUERY, EDIT, EXPLORE, COMPLEX) representing the type of user goal.

## Requirements

### Requirement 1: Micro-Prompt Template Structure

**User Story:** As a developer, I want prompt templates to be immutable data structures with well-defined fields, so that prompt construction is predictable and validated at creation time.

#### Acceptance Criteria

1. THE MicroPromptTemplate SHALL store an intent field restricted to one of: "TASK", "QUERY", "EDIT", "EXPLORE", "COMPLEX"
2. THE MicroPromptTemplate SHALL contain a template string of at most 2000 characters that includes a `{goal}` placeholder
3. THE MicroPromptTemplate SHALL contain a one_shot_example field that is a valid JSON string of at most 500 characters, parseable without error, containing an "action" key with a non-empty string value
4. THE MicroPromptTemplate SHALL contain an available_tools list of 1 to 20 items where each item is a non-empty string
5. THE MicroPromptTemplate SHALL enforce max_prompt_tokens between 200 and 1000
6. THE MicroPromptTemplate SHALL enforce max_gen_tokens between 64 and 512
7. THE MicroPromptTemplate SHALL be immutable after creation such that any attempt to modify a field raises an error
8. IF any field fails validation at creation time, THEN THE MicroPromptTemplate SHALL reject construction by raising a validation error indicating which field is invalid and what constraint was violated

### Requirement 2: Micro-Prompt Registry

**User Story:** As a developer, I want a registry that maps intents to prompt templates, so that the correct template is always retrieved for a given task type.

#### Acceptance Criteria

1. WHEN the MicroPromptRegistry is initialized, THE MicroPromptRegistry SHALL register default templates for TASK, QUERY, EDIT, and EXPLORE intents, where each default template contains a non-empty template string with a {goal} placeholder, a valid JSON one_shot_example with an "action" key, and a non-empty available_tools list
2. WHEN a valid intent (one of TASK, QUERY, EDIT, EXPLORE, or COMPLEX) is requested via the get method, THE MicroPromptRegistry SHALL return the MicroPromptTemplate whose intent field matches the requested intent
3. IF an intent string that is not one of TASK, QUERY, EDIT, EXPLORE, or COMPLEX is requested, THEN THE MicroPromptRegistry SHALL return the EXPLORE template as a fallback without raising an exception
4. WHEN a template is registered for an existing intent, THE MicroPromptRegistry SHALL replace the previous template so that subsequent get calls for that intent return the newly registered template
5. THE MicroPromptRegistry SHALL return the same template object instance (identity equality) for repeated get calls with the same intent, provided no new template has been registered for that intent between calls
6. IF the get method is called with any input including None or an empty string, THEN THE MicroPromptRegistry SHALL return a MicroPromptTemplate without raising an exception

### Requirement 3: Prompt Assembly

**User Story:** As a developer, I want prompts assembled from a constant system prompt plus a task-specific micro-prompt, so that total prompt size stays under 500 tokens and the model receives only relevant context.

#### Acceptance Criteria

1. THE PromptAssembler SHALL use a constant System_Prompt that is no longer than 60 tokens (estimated as character count divided by 4) and returns the identical string on every invocation regardless of parameters
2. WHEN assembling a prompt, THE PromptAssembler SHALL combine the System_Prompt, the micro-prompt template formatted with the goal, the available tool names for the intent, and either the One_Shot_Example or a compact last_result
3. WHEN the assembled prompt exceeds the template's max_prompt_tokens value, THE PromptAssembler SHALL truncate context (last_result or example) first, then goal text, appending "..." to indicate truncation, until the estimated token count (character count divided by 4) is at or below the budget
4. WHEN step equals 1 or last_result is None, THE PromptAssembler SHALL include the One_Shot_Example in the assembled prompt
5. WHEN step is greater than 1 and last_result is provided, THE PromptAssembler SHALL include last_result truncated to no more than 300 characters in place of the One_Shot_Example
6. THE PromptAssembler SHALL produce a non-empty prompt string for all inputs where goal is a non-empty string, intent is valid, and step is greater than or equal to 1
7. THE PromptAssembler SHALL preserve at least the first 50 characters of the goal in the assembled prompt when the goal is 50 characters or longer
8. IF the goal is shorter than 50 characters, THEN THE PromptAssembler SHALL include the entire goal without truncation in the assembled prompt

### Requirement 4: Token Budget Enforcement

**User Story:** As a developer, I want strict token budget enforcement on all assembled prompts, so that the 3B model operates within its effective attention window and responds quickly.

#### Acceptance Criteria

1. THE PromptAssembler SHALL estimate tokens using integer division of character count by 4 (len(text) // 4)
2. THE PromptAssembler SHALL enforce that the combined estimated token count of system_text and user_text never exceeds the template max_prompt_tokens regardless of input goal length
3. WHEN truncation is required to meet the token budget, THE PromptAssembler SHALL truncate context first, then goal text, and append "..." at the point of truncation within the affected text segment
4. THE System_Prompt SHALL never exceed 60 estimated tokens
5. WHEN a TASK intent is assembled, THE PromptAssembler SHALL enforce a maximum of 500 total prompt tokens (system_text + user_text combined)
6. WHEN a QUERY intent is assembled, THE PromptAssembler SHALL enforce a maximum of 400 total prompt tokens (system_text + user_text combined)
7. WHEN an EDIT intent is assembled, THE PromptAssembler SHALL enforce a maximum of 700 total prompt tokens (system_text + user_text combined)
8. WHEN an EXPLORE intent is assembled, THE PromptAssembler SHALL enforce a maximum of 600 total prompt tokens (system_text + user_text combined)
9. IF the assembled prompt still exceeds the token budget after truncation of all non-mandatory content, THEN THE PromptAssembler SHALL log a warning and return the truncated prompt rather than raising an error

### Requirement 5: Grammar Enforcement

**User Story:** As a developer, I want GBNF grammar enforcement applied to model output based on intent type, so that the model produces valid JSON actions without narration.

#### Acceptance Criteria

1. WHEN the intent is TASK, THE PromptAssembler SHALL select a GBNF_Grammar that constrains output to a JSON object containing a mandatory "action" field whose value is one of the registered tool names defined in the tool_name grammar rule
2. WHEN the intent is QUERY, THE PromptAssembler SHALL select a GBNF_Grammar that constrains output to a JSON object containing a mandatory "action" field whose value is one of the registered tool names defined in the tool_name grammar rule
3. WHEN the intent is EXPLORE, THE PromptAssembler SHALL select a GBNF_Grammar that constrains output to a JSON object containing a mandatory "action" field whose value is one of the registered tool names defined in the tool_name grammar rule
4. WHEN the intent is EDIT, THE PromptAssembler SHALL select no grammar to allow free-form SEARCH/REPLACE blocks
5. THE GBNF_Grammar SHALL enforce that the "action" field value matches exactly one of the tool names enumerated in the tool_name production rule, rejecting any output with an unregistered tool name
6. IF the model produces 2 consecutive empty responses while grammar is enforced, THEN THE PromptAssembler SHALL disable grammar enforcement for the remainder of the session and fall back to JSON parsing with repair
7. WHEN the model size is less than 7 billion parameters, THE PromptAssembler SHALL select the THINK_JSON_GRAMMAR variant that permits an optional think block prefix before the JSON object

### Requirement 6: Intent Classification Integration

**User Story:** As a developer, I want the prompt system to use intent classification to select the appropriate micro-prompt template, so that each task type receives only the context it needs.

#### Acceptance Criteria

1. WHEN a non-empty user goal is received, THE IntentClassifier SHALL classify it into one of: TASK, QUERY, EDIT, EXPLORE, or COMPLEX within 50 milliseconds
2. WHEN an intent is classified, THE PromptAssembler SHALL retrieve the corresponding template from the MicroPromptRegistry
3. IF the classified intent has no registered template in the MicroPromptRegistry, THEN THE PromptAssembler SHALL fall back to the EXPLORE template
4. WHEN a TASK intent is assembled, THE PromptAssembler SHALL exclude repo maps, memory content, RAG results, and session context from the prompt
5. IF the user goal is empty or contains only whitespace, THEN THE IntentClassifier SHALL return the EXPLORE intent without attempting keyword matching

### Requirement 7: Performance Targets

**User Story:** As a user, I want response times under 20 seconds for standard tasks, so that the AI assistant is usable on my constrained hardware.

#### Acceptance Criteria

1. THE PromptAssembler SHALL set max_gen_tokens to 256 for TASK intent and 128 for QUERY intent when assembling a prompt
2. WHEN a TASK prompt is assembled, THE PromptAssembler SHALL enforce a hard cap of 500 tokens on the total prompt size (system prompt + user prompt combined), truncating context to fit within the budget
3. WHEN a QUERY prompt is assembled, THE PromptAssembler SHALL enforce a hard cap of 400 tokens on the total prompt size (system prompt + user prompt combined), truncating context to fit within the budget
4. IF the assembled prompt exceeds the intent's token budget after truncation, THEN THE PromptAssembler SHALL log a warning and return the truncated prompt rather than failing

### Requirement 8: Error Handling and Resilience

**User Story:** As a developer, I want the prompt system to handle edge cases gracefully, so that the agent loop never crashes due to prompt construction failures.

#### Acceptance Criteria

1. IF the assembled prompt exceeds the template's max_prompt_tokens value after aggressive truncation has been applied, THEN THE PromptAssembler SHALL log a warning containing the estimated token count and the budget limit, and return the truncated prompt without raising an exception
2. IF the IntentClassifier returns a string that is not one of the valid intent types (TASK, QUERY, EDIT, EXPLORE, COMPLEX), THEN THE MicroPromptRegistry SHALL log the unrecognized intent string and return the EXPLORE template
3. IF the model produces empty or whitespace-only output despite grammar enforcement, THEN THE system SHALL retry the generation exactly once without grammar constraints
4. IF the retry without grammar in criterion 3 also produces empty or whitespace-only output, THEN THE system SHALL return a fallback action containing the one-shot example from the current template as a nudge prompt and retry once more
5. IF the model produces output that fails JSON parsing despite grammar enforcement, THEN THE system SHALL pass the raw output to the SelfHealingParser for repair
6. IF the SelfHealingParser returns None (repair failed), THEN THE system SHALL re-prompt the model with the one-shot example appended and retry generation exactly once with grammar constraints re-enabled

### Requirement 9: Prompt Content Safety

**User Story:** As a developer, I want the minimal prompt system to avoid including sensitive data in prompts, so that secrets are never exposed to the model.

#### Acceptance Criteria

1. THE PromptAssembler SHALL exclude values matching sensitive data patterns (environment variables, API keys, tokens, passwords, and connection strings) from all assembled prompt sections by never injecting them into section content
2. THE GBNF_Grammar SHALL enforce that only tool names defined in the `tool_name` production rule appear in the action field of model output, rejecting any output containing an action value not in that rule
3. THE System_Prompt SHALL contain only role descriptions, response format instructions, and tool usage rules, with no API keys, file-system credentials, environment variable values, or user-specific secrets
4. IF the PromptAssembler detects a string matching a sensitive data pattern (key prefixes such as "sk-", "ghp_", "AKIA"; environment variable references; or strings assigned to fields named password, secret, or token) in candidate prompt content, THEN THE PromptAssembler SHALL omit that value and replace it with a placeholder indicating redaction
5. IF grammar enforcement is disabled at runtime due to consecutive empty responses, THEN THE System SHALL validate parsed model output against the registered tool name list and reject any action value not present in that list
