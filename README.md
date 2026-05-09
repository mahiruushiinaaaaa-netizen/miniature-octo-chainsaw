# Mini-AI v39

A production-grade autonomous coding assistant designed with low-end models and low-end PCs in mind, heavily inspired by the architecture of Aider.

## Features & Optimizations
- **Consolidated Modular Architecture**: Professionally structured into `core`, `agents`, `tools`, and `ui` packages for maximum maintainability.
- **Dynamic Context Sizing:** Context limits dynamically adjust to fit within your model's maximum token window, ensuring no token truncation or OOM errors.
- **Search/Replace Self-Healing:** The agent uses an optimized `SEARCH/REPLACE` diffing engine. If your model makes a typo, the agent feeds the actual file contents back to the model allowing it to instantly self-correct.
- **JSON Heuristics:** Employs advanced JSON repair regex heuristics to tolerate formatting mistakes common in smaller models (like using single quotes instead of double quotes).
- **Aider-Parity Commands:** Includes slash commands like `/add`, `/diff`, `/commit`, `/lint`, `/test`, and `/watch`.
- **Fast, Minimal Execution:** Optimized execution loops that prevent API bloat by keeping chat history and observations extremely lean.
- **Dynamic Model Routing:** Automatically routes "talking" and "analyzing" tasks to a fast secondary model and "coding" tasks to your primary heavy model when started with `--dual-model`.
- **Tri-Model Architecture:** Start with `--tri-model` to unleash a 3-agent orchestration pipeline. An Agent plans the tasks, an Analyzer investigates the repo and writes context briefs, and a strict Coder model executes the edits.
- **Robust Agent Orchestration:** Features a stateful `ExecutionContext` with persistent session management, CWD tracking across commands, and automatic environment capability detection.
- **Framework-Specific Tools:** Includes specialized tools for Laravel project creation, Breeze installation, and migration management, with automatic "step-by-step" guidance extraction from web searches.
- **Isolated Execution Sandbox**: Features a pluggable sandbox system (`LocalSandbox`, `VenvSandbox`) that isolates command execution and Python dependencies, protecting your host system and project environment.
- **Platform-Agnostic Interface:** Uses a `PlatformAdapter` to normalize filesystem and process operations across Windows, Linux, and macOS.
- **Smart Media Player**: Includes an ultra-light floating music player with VLC background playback, autoplay (relevance-based), track queuing, and intelligent enqueuing (searches while playing automatically add to the queue).

## Project Structure
- `mini_ai/core/`: Infrastructure, configuration, and execution logic.
- `mini_ai/agents/`: Agent implementations (Orchestrator, Planner, Coder, Reviewer).
- `mini_ai/tools/`: Utilities, file operations, and third-party integrations.
- `mini_ai/ui/`: Rich terminal and GUI components.

## Usage
Run the CLI and interact with the agent natively:
```bash
python run.py
```
Or launch the GUI:
```bash
python launch_gui.py
```
Use `/help` inside the CLI to see the full list of available slash commands.

## Requirements
- Python 3.9+
- A configured LLM Backend (e.g., local Ollama, Groq, Anthropic, or OpenAI).

## Documentation
- [Tool Calling Guide](DOCS/TOOL_CALLING.md) — Understanding how the agent interacts with your system.
- [Orchestrator Guide](DOCS/ORCHESTRATOR.md) — Mastering the Tri-Model orchestration pipeline.
- [Sandbox Plan](sandbox_plan.md) — Roadmap for advanced, stateful command execution.

## Repository Status
This project is currently managed via Git. All core features have been committed to the local `master` branch.

## Notes
Built as an efficient, memory-safe alternative to Aider for low-resource environments.
