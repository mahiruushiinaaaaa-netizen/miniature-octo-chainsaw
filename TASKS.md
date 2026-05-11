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
- **Workspace Explorer Sidebar**: Port the sidebar concept to a toggleable panel rather than a fixed dual-pane.

#### Done (Latest)
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
