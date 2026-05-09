# Tool Calling Explained

## What is Tool Calling?
Tool calling (also known as Function Calling) is a capability in Large Language Models (LLMs) that allows them to interact with the outside world. Instead of only relying on the information they were trained on, the model can choose to use "tools" provided to it.

## How It Works
1. **Definition**: The system provides the model with a list of tools (functions) it can use, including descriptions of what they do and what parameters they need.
2. **Detection**: When you ask a question like "What is the weather in Tokyo?", the model realizes it doesn't have live data.
3. **The Call**: Instead of answering directly, the model outputs a structured request (usually JSON):
   ```json
   {
     "name": "get_weather",
     "parameters": { "location": "Tokyo" }
   }
   ```
4. **Execution**: The system (the code running the model) sees this JSON, runs the actual code for `get_weather("Tokyo")`, and gets the result (e.g., "22°C, Sunny").
5. **Observation**: The result is fed back to the model.
6. **Final Response**: The model uses the result to give you a human-friendly answer: "The weather in Tokyo is currently 22°C and sunny."

## Why It Matters for This Project
In `mini_ai_v39`, tool calling is the engine behind its autonomy. It allows the agent to:
- **Write Code**: By calling `replace_file_content`.
- **Explore Files**: By calling `list_dir` or `read_file`.
- **Run Tests**: By calling `run_command`.
- **Fix Errors**: By seeing the error output from a command and calling another tool to fix it.

## Supported Models
Not all models support tool calling well. 
- **High Support**: Models like `gpt-4o`, `claude-3.5-sonnet`, and `gemini-1.5-pro` have built-in tool calling support.
- **High Support (Small Models)**: `Qwen2.5-3B-Instruct` and `Llama-3.1-8B-Instruct` are excellent. Qwen2.5 in particular is highly optimized for tool calling even at 3B parameters.
- **Medium Support**: Older models like `llama-3-8b` can do it but might make JSON formatting mistakes.

## Tips for Small Models (like Qwen2.5 3B)
If you are using a model like **Qwen2.5-3B-Instruct-Q4_K_M**, here is how to get the best performance:

1. **Quantization Impact**: A `Q4_K_M` quantization is a good balance. However, if you see the model "hallucinating" tool names, try a `Q6_K` or `Q8_0` version if your RAM allows.
2. **Context Window**: Keep your task focused. Small models can lose "attention" if the conversation history gets too long.
3. **JSON Self-Healing**: This project automatically fixes common small-model JSON errors (like single quotes or missing commas). If the model fails, the system will nudge it to try again with a "Hint".
4. **Dual Model Strategy**: If the 3B model is too slow for complex reasoning, consider using the `--dual-model` flag to offload simple chat tasks to an even faster model, or use the 3B model as the "fast" model and a larger one (like 7B or 14B) as the "coder".

## What This System Lacks (Current Limitations)
While `mini_ai_v39` is highly optimized for local use, it currently lacks some advanced "Native" tool calling features found in cloud-based APIs:

1. **Strict Syntax Enforcement (Grammars)**: The system relies on the model's intelligence to output valid JSON. It does not yet use "GBNF Grammars" to force the model to stay within JSON rules. This means small models (like 3B) might still output invalid syntax occasionally.
2. **Parallel Tool Calling**: The agent can only perform one action per turn. It cannot say "Search the web AND read this file at the same time."
3. **Native Tool API Integration**: It uses "Text-Wrapped" tool definitions (sending instructions in the system prompt) rather than the "Native JSON Schema" parameters used by high-end APIs.
4. **Streaming Parser**: The system waits for the full model response before trying to extract the action. It doesn't yet "see" the tool call as it's being typed.

### Suggested Improvements
- **Add Grammar Support**: (DONE) Implementing GBNF grammars would make 3B models virtually bulletproof against JSON syntax errors.
- **Implement Multi-Action Parsing**: Allowing the agent to emit a list of actions `[{"action":...}, {"action":...}]` for faster parallel execution.

## System Optimization: GBNF Grammars
I have successfully implemented **GBNF Grammar support** for your local setup. This is a game-changer for models like **Qwen2.5 3B**.

### How it works:
1. **Force JSON**: The system now sends a strict rule to the model during its action phase. This rule says: "You are allowed to think, but your action MUST be a valid JSON object."
2. **Eliminate Syntax Errors**: Because the rule is enforced at the token-generation level, the model literally cannot output a missing comma or a single quote where a double quote belongs.
3. **Optimized for Qwen**: This allows the 3B model to perform with the reliability of a much larger model, as it no longer has to "remember" JSON syntax rules—they are enforced by the system.
