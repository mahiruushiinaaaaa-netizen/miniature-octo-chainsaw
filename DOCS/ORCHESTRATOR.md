# Orchestrator & Phased Intelligence

## Why "Phases" Matter
Small models (like Qwen2.5 3B) can sometimes "hallucinate" or jump to conclusions if they try to do everything at once. To prevent this, `mini_ai_v39` uses a **Phased Intelligence** approach.

## 1. Standard Mode: Internal Phases
Even in the standard chat loop, the agent now follows a **Thinking -> Planning -> Action** cycle.
- **Thinking**: The model uses `<think>` blocks to reason.
- **Planning**: Every JSON action now includes a `"plan"` field where the model must state its intent before performing the action.
- **Action**: The actual tool call.

## 2. Orchestrator Mode: Project-Level Phases
For complex tasks (like "build a full website"), you should enable **Orchestrator Mode**.
### How to enable:
In the CLI, type:
```text
/orchestrate
```
### What it does:
The system switches from a single-turn loop to a structured pipeline:
1. **Phase 1: Environment Analysis**: The agent scans your project to detect languages, frameworks, and structure.
2. **Phase 2: Global Planning**: The model creates a multi-step plan (Step 1, Step 2, etc.).
3. **Phase 3: Sequential Execution**: The agent executes each step one by one.
4. **Phase 4: Final Review**: A "Reviewer" agent checks the entire project to ensure the goal was met and no bugs were introduced.

## 3. Tri-Model Architecture (Advanced)
If you have enough RAM, you can run three specialized models at once:
- **Planner/Agent**: Handles the high-level strategy.
- **Analyzer**: Investigates the code and writes "Context Briefs".
- **Coder**: Focuses purely on writing the code based on the briefs.

### How to enable:
Run the CLI with the `--tri-model` flag:
```bash
python run.py --tri-model
```

## Tips to Prevent Hallucinations
- **Use `/orchestrate`** for anything more complex than a single-file edit.
- **Check the Thoughts**: Watch the `<think>` blocks. If the model starts repeating itself, it's about to hallucinate.
- **Be Specific**: Give the model a starting point (e.g., "Look at main.py first").
