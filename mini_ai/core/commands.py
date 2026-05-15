"""
commands.py – Aider-parity command router and REPL handler.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..agents.agent import agent_mode, request_stop, _try_quick_math
from ..agents.orchestrator import orchestrated_agent_mode
from ..agents.task_result import TaskResult
from .backend import generate
from .config import Config
from ..ui import ok, err, warn, ai, panel, set_compact, set_raw, STATE, flow
from ..ui.choice_ui import choose_from_list
from .memory import PersistentMemory
from .approval import approval_mode, set_approval_mode
from .path_manager import PathManager
from ..tools.file_ops import read_file_command
from ..tools.linter import lint_file
from .executor import ToolExecutor
from ..tools.file_writer import SafeFileWriter


# ─── Chat History ─────────────────────────────────────────────────────────────

class ChatHistory:
    """Append-only markdown log of the conversation (like aider's chat history)."""
    
    def __init__(self, workspace: Path):
        self.path = workspace / ".mini_ai_chat_history.md"
    
    def append(self, role: str, content: str) -> None:
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                ts = datetime.now().strftime("%H:%M:%S")
                f.write(f"\n#### {role} [{ts}]\n{content}\n")
        except OSError:
            pass
    
    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass

# ─── Command Router ──────────────────────────────────────────────────────────

class CommandRouter:
    def __init__(self, config: Config):
        self.config = config
        self.ui_config = config.ui_config or config
        self.memory = PersistentMemory()
        self.autopilot_mode = "safe" if config.allow_run else "ask"
        set_approval_mode(self.autopilot_mode)
        self.verbose = False
        self.use_orchestrator = False
        self.watcher = None
        self.chat_log: list[dict] = []
        self.chat_history = ChatHistory(Path(config.workspace))
        self.added_files: set[str] = set()  # Files explicitly added to context (aider /add)
        self.last_goal: Optional[str] = None
        self.observations: list[str] = []
        self.last_target: Optional[Path] = None
        self.last_file: Optional[Path] = None  # Last created/edited file for continuations
        
        # Prompt rewriter (0.5B model via Ollama for cleaning up user input)
        self._rewriter = None
        try:
            from .prompt_rewriter import PromptRewriter
            self._rewriter = PromptRewriter(config, model_name=getattr(config, 'ollama_fast_model', 'qwen2.5:0.5b'))
        except Exception:
            pass
        
        # AI Goal Dispatcher (0.5B model via Ollama for tool classification)
        self._goal_dispatcher = None
        try:
            from .goal_dispatcher import GoalDispatcher
            fast_model = getattr(config, 'ollama_fast_model', 'qwen2.5:0.5b')
            self._goal_dispatcher = GoalDispatcher(model_name=fast_model)
        except Exception:
            pass
        
        # Pre-warm the intent classifier (shares same model, cached singleton)
        try:
            from .intent_classifier import get_classifier
            fast_model = getattr(config, 'ollama_fast_model', 'qwen2.5:0.5b')
            get_classifier(model=fast_model)  # Initialize singleton early
        except Exception:
            pass
        
        # CopixTUI integration
        self.copix = None
        if getattr(config, 'use_copix', False):
            try:
                from ..ui import CopixTUI
                model_name = getattr(config, 'model', None)
                model_name = model_name.name if model_name else "Mini AI"
                self.copix = CopixTUI(model_name=model_name)
            except Exception:
                pass  # Fall back to old UI if CopixTUI fails

    def handle(self, command: str) -> bool:
        if not command:
            return True
        if command in {"/quit", "/exit", "exit"}:
            return False
        
        # Log user input
        self.chat_history.append("USER", command)

        if command.startswith("/"):
            return self._handle_slash_command(command)

        if command.startswith("!"):
            # Aider-style: ! runs shell command directly
            return self._run_shell(command[1:].strip())

        # Check for direct play commands
        lowered = command.lower().strip()
        is_question = lowered.startswith(("what", "who", "how", "where", "is ", "are "))
        play_keywords = ["play", "stream", "listen", "watch", "put on", "queue"]
        if any(kw in lowered for kw in play_keywords) and not is_question:
            # Handle play commands directly
            try:
                pm = PathManager(self.config.workspace)
                writer = SafeFileWriter(pm)
                executor = ToolExecutor(self.config, pm, writer)
                action = {"action": "play_media", "query": command}
                is_final, result_json = executor.execute(action, assume_yes=True)
                
                import json
                try:
                    result_data = json.loads(result_json)
                    output = result_data.get("output", "")
                    ok(output)
                    self.chat_history.append("ASSISTANT", output)
                    self.memory.add_event(f"Direct play: {command}\nResult: {output}")
                except Exception:
                    self.chat_history.append("ASSISTANT", result_json)
                    self.memory.add_event(f"Direct play: {command}\nResult: {result_json}")
                return True
            except Exception as e:
                err(f"Failed to play media: {e}")
                return True

        # Everything else goes to the agent
        self.run_agent(command)
        return True

    def _run_shell(self, cmd: str) -> bool:
        """Run a shell command directly, like aider's ! prefix."""
        if not cmd:
            err("Usage: !<command>")
            return True
        if not self.config.allow_run:
            warn("Command execution disabled. Use --allow-run to enable.")
            return True
        panel("SHELL", f"`{cmd}`")
        try:
            result = subprocess.run(
                cmd, shell=True,
                cwd=str(self.config.workspace),
                capture_output=True, text=True, timeout=120,
            )
            output = (result.stdout + result.stderr).strip()
            if output:
                print(output)
            if result.returncode != 0:
                err(f"Exit code: {result.returncode}")
            else:
                ok("Command completed.")
        except Exception as e:
            err(f"Error: {e}")
        return True

    def _handle_slash_command(self, command: str) -> bool:
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""

        # ── Help ──────────────────────────────────────────────────────────
        if cmd == "/help":
            self._show_help()

        # ── Agent / Autopilot ─────────────────────────────────────────────
        elif cmd == "/autopilot":
            self.autopilot_mode = "safe"
            set_approval_mode("safe")
            ok("Autopilot enabled (auto-approve actions).")
            if args:
                self.run_agent(args)
        elif cmd == "/ask":
            self.autopilot_mode = "ask"
            set_approval_mode("ask")
            ok("Manual approval enabled.")

        # ── Orchestrator ──────────────────────────────────────────────────
        elif cmd == "/orchestrate":
            if args:
                self.use_orchestrator = True
            else:
                self.use_orchestrator = not self.use_orchestrator
            ok(f"Orchestrator mode: {'ON' if self.use_orchestrator else 'OFF'}")
            if args:
                self.run_agent(args)

        # ── Clear (aider /clear) ──────────────────────────────────────────
        elif cmd == "/clear":
            self.chat_log.clear()
            self.memory.forget_all()
            self.chat_history.clear()
            ok("Chat history and context cleared.")

        # ── Reset (aider /reset) ──────────────────────────────────────────
        elif cmd == "/reset":
            self.chat_log.clear()
            self.memory.forget_all()
            self.added_files.clear()
            self.chat_history.clear()
            self.last_goal = None
            self.observations.clear()
            ok("All files dropped and chat history cleared.")

        # ── Diff (aider /diff) ────────────────────────────────────────────
        elif cmd == "/diff":
            self._show_diff()

        # ── Tokens (aider /tokens) ────────────────────────────────────────
        elif cmd == "/tokens":
            self._show_token_usage()

        # ── Commit (aider /commit) ────────────────────────────────────────
        elif cmd == "/commit":
            self._git_commit(args)

        # ── Lint (aider /lint) ────────────────────────────────────────────
        elif cmd == "/lint":
            self._lint_files(args)

        # ── Git (aider /git) ──────────────────────────────────────────────
        elif cmd == "/git":
            self._run_git(args)

        # ── Drop (aider /drop) ────────────────────────────────────────────
        elif cmd == "/drop":
            if args:
                self.added_files.discard(args)
                ok(f"Dropped {args} from context.")
            else:
                self.added_files.clear()
                ok("Dropped all files from context.")

        # ── Add (aider /add) ──────────────────────────────────────────────
        elif cmd == "/add":
            if not args:
                err("Usage: /add <path>")
            else:
                pm = PathManager(self.config.workspace)
                target = pm.resolve_target(args)
                if target.exists():
                    self.added_files.add(str(target))
                    try:
                        content = target.read_text(encoding="utf-8")
                        self.memory.add_event(
                            f"Context from {args}:\n{content[:10000]}"
                        )
                        ok(f"Added {args} to chat context.")
                    except Exception as e:
                        err(f"Could not read {args}: {e}")
                else:
                    err(f"File not found: {args}")

        # ── Web (aider /web) ─────────────────────────────────────────────
        elif cmd == "/web":
            self._scrape_web(args)

        # ── Test (aider /test) ────────────────────────────────────────────
        elif cmd == "/test":
            self._run_tests(args)

        # ── Watch (aider /watch) ──────────────────────────────────────────
        elif cmd == "/watch":
            self._toggle_watch()

        # ── Undo (aider /undo) ────────────────────────────────────────────
        elif cmd == "/undo":
            self._git_undo()

        # ── Read ──────────────────────────────────────────────────────────
        elif cmd == "/read":
            if args:
                read_file_command(args)
            else:
                err("Usage: /read <path>")

        # ── Workspace / CD ────────────────────────────────────────────────
        elif cmd == "/workspace":
            if args:
                new_ws = Path(args).expanduser().resolve()
                if new_ws.exists() and new_ws.is_dir():
                    self.config.workspace = new_ws
                    ok(f"Workspace root changed to: {new_ws}")
                else:
                    err(f"Folder not found or not a directory: {new_ws}")
            else:
                print(f"Current workspace: {self.config.workspace}")

        elif cmd == "/cd":
            if args:
                pm = PathManager(self.config.workspace)
                try:
                    target = pm.resolve_target(args)
                    if target.exists() and target.is_dir():
                        pm.set_target(target)
                        ok(f"Target directory (CD) changed to: {target}")
                        # Update the persistent target for the next agent run
                        self.last_target = target
                        self.observations = [f"CWD: {target}"]
                    else:
                        err(f"Folder not found: {target}")
                except Exception as exc:
                    err(f"Could not CD: {exc}")
            else:
                err("Usage: /cd <path>")

        # ── Set Target ────────────────────────────────────────────────────

        # ── Memory ────────────────────────────────────────────────────────
        elif cmd == "/memory":
            print(self.memory.display())
        elif cmd == "/forgetall":
            self.memory.forget_all()
            ok("Memory cleared.")

        # ── Verbose ───────────────────────────────────────────────────────
        elif cmd == "/verbose":
            self.verbose = not self.verbose
            set_raw(self.verbose)
            ok(f"Verbose: {self.verbose}")

        # ── UI ────────────────────────────────────────────────────────────
        elif cmd == "/ui":
            set_compact(not STATE.compact)
            ok("UI toggled.")

        # ── Model dir ─────────────────────────────────────────────────────
        elif cmd == "/modelsdir":
            print(f"Current models folder: {self.config.models_dir}")

        # ── Run (aider /run) ──────────────────────────────────────────────
        elif cmd == "/run":
            self._run_shell(args)

        # ── Stop / Interrupt ──────────────────────────────────────────────
        elif cmd == "/stop":
            try:
                request_stop()
                ok("Stop requested. Attempting to terminate active operations...")
            except Exception as e:
                err(f"Stop failed: {e}")
            return True
        elif cmd == "/interrupt":
            try:
                request_stop()
                ok("Interrupt requested. Attempting to terminate active operations...")
            except Exception as e:
                err(f"Interrupt failed: {e}")
            return True

        else:
            err(f"Unknown command: {cmd}. Type /help for available commands.")
        
        return True

    def _show_help(self) -> None:
        help_text = """
**Available Commands:**

| Command | Description |
|---------|-------------|
| `/help` | Show this help |
| `/add <path>` | Add file to chat context |
| `/drop [path]` | Remove file(s) from context |
| `/read <path>` | Display a file |
| `/clear` | Clear chat history |
| `/reset` | Drop all files and clear history |
| `/diff` | Show diff of AI changes |
| `/tokens` | Show context window usage |
| `/commit [msg]` | Commit changes |
| `/lint [path]` | Lint files and show errors |
| `/undo` | Revert last AI edit |
| `/test <cmd>` | Run tests, auto-fix on failure |
| `/watch` | Toggle file watcher |
| `/web <url>` | Scrape webpage into context |
| `/git <cmd>` | Run git command |
| `/run <cmd>` | Run shell command |
| `/stop` | Stop current operation and background processes |
| `/interrupt` | Alias for /stop |
| `!<cmd>` | Run shell command (shortcut) |
| `/autopilot [task]` | Auto-approve mode |
| `/ask` | Manual approval mode |
| `/orchestrate` | Toggle planner mode |
| `/verbose` | Toggle debug output |
| `/model` | Change AI model |
| `/memory` | Show memory |
| `/forgetall` | Clear memory |
| `go` | Continue last goal |
| `/quit` | Exit |
"""
        panel("HELP", help_text)

    def _show_diff(self) -> None:
        """Show diff of changes since last commit (like aider /diff)."""
        try:
            result = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=str(self.config.workspace),
                capture_output=True, text=True, timeout=15,
            )
            diff = result.stdout.strip()
            if diff:
                panel("DIFF", f"```diff\n{diff[:5000]}\n```")
            else:
                ok("No changes to display.")
        except Exception as e:
            err(f"Could not run git diff: {e}")

    def _show_token_usage(self) -> None:
        """Show approximate token usage (like aider /tokens)."""
        ctx = self.config.ctx
        # Estimate current usage
        added_tokens = 0
        for fpath in self.added_files:
            try:
                size = Path(fpath).stat().st_size
                added_tokens += size // 4  # rough estimate
            except OSError:
                pass
        
        memory_tokens = len(self.memory.context_for("").encode()) // 4
        history_tokens = sum(len(json.dumps(e)) for e in self.chat_log) // 4
        total = added_tokens + memory_tokens + history_tokens
        remaining = ctx - total
        
        info = (
            f"**Context Window: {ctx} tokens**\n\n"
            f"| Category | Tokens |\n"
            f"|----------|--------|\n"
            f"| Added files | ~{added_tokens:,} |\n"
            f"| Memory | ~{memory_tokens:,} |\n"
            f"| Chat history | ~{history_tokens:,} |\n"
            f"| **Total** | **~{total:,}** |\n"
            f"| Remaining | ~{remaining:,} |"
        )
        panel("TOKENS", info)

    def _git_commit(self, message: str) -> None:
        """Commit changes with a message (like aider /commit)."""
        try:
            # Stage all changes
            subprocess.run(
                ["git", "add", "-A"],
                cwd=str(self.config.workspace),
                capture_output=True, timeout=10,
            )
            cmd = ["git", "commit", "-m", message or "mini-ai: manual commit"]
            result = subprocess.run(
                cmd,
                cwd=str(self.config.workspace),
                capture_output=True, text=True, timeout=15,
            )
            output = (result.stdout + result.stderr).strip()
            if result.returncode == 0:
                ok(f"Committed: {output[:200]}")
            else:
                warn(output[:300])
        except Exception as e:
            err(f"Commit failed: {e}")

    def _lint_files(self, path: str) -> None:
        """Lint files and show errors (like aider /lint)."""
        pm = PathManager(self.config.workspace)
        if path:
            targets = [pm.resolve_target(path)]
        else:
            # Lint all added files or dirty files
            targets = [Path(f) for f in self.added_files if Path(f).exists()]
            if not targets:
                # Lint dirty git files
                try:
                    result = subprocess.run(
                        ["git", "diff", "--name-only"],
                        cwd=str(self.config.workspace),
                        capture_output=True, text=True, timeout=10,
                    )
                    for f in result.stdout.strip().splitlines():
                        p = pm.resolve_target(f)
                        if p.exists():
                            targets.append(p)
                except Exception as e:
                    from .logger import get_logger
                    logger = get_logger("commands")
                    logger.debug(f"Git diff failed (not a git repo?): {e}")

        if not targets:
            ok("No files to lint.")
            return

        total_errors = 0
        for target in targets:
            if not target.exists() or not target.is_file():
                continue
            try:
                code = target.read_text(encoding="utf-8")
                errors = lint_file(str(target), code)
                if errors:
                    panel("LINT ERRORS", f"**{target.name}**\n```\n{errors}\n```")
                    total_errors += 1
                else:
                    ok(f"✓ {target.name} — clean")
            except Exception as e:
                err(f"Error linting {target.name}: {e}")

        if total_errors == 0:
            ok("All files passed lint checks.")

    def _run_git(self, args: str) -> None:
        """Run arbitrary git command (like aider /git)."""
        if not args:
            err("Usage: /git <command>")
            return
        try:
            result = subprocess.run(
                f"git {args}",
                shell=True,
                cwd=str(self.config.workspace),
                capture_output=True, text=True, timeout=30,
            )
            output = (result.stdout + result.stderr).strip()
            if output:
                print(output)
            if result.returncode != 0:
                err(f"Git exit code: {result.returncode}")
        except Exception as e:
            err(f"Git error: {e}")

    def _git_undo(self) -> None:
        """Undo last AI edit (like aider /undo)."""
        from .repo import git_undo
        success, msg = git_undo(str(self.config.workspace))
        if success:
            ok(msg)
        else:
            err(msg)

    def _scrape_web(self, url: str) -> None:
        """Scrape a URL and add to context (like aider /web)."""
        if not url:
            err("Usage: /web <url>")
            return
        import urllib.request
        try:
            panel("WEB", f"Scraping {url}...")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                html = response.read().decode("utf-8", errors="ignore")
                text = re.sub(r'<style.*?>.*?</style>', '', html, flags=re.I | re.S)
                text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.I | re.S)
                text = re.sub(r'<[^>]+>', ' ', text)
                text = re.sub(r'\s+', ' ', text).strip()
                self.memory.add_event(f"Web context from {url}:\n{text[:15000]}")
                ok(f"Added {url} to context ({len(text)} chars).")
        except Exception as e:
            err(f"Could not scrape {url}: {e}")

    def _run_tests(self, cmd: str) -> None:
        """Run tests and auto-fix on failure (like aider /test)."""
        if not cmd:
            err("Usage: /test <command>")
            return
        panel("TEST", f"Running: `{cmd}`")
        try:
            result = subprocess.run(
                cmd, shell=True,
                cwd=str(self.config.workspace),
                capture_output=True, text=True, timeout=120,
            )
            output = (result.stdout + result.stderr).strip()
            if result.returncode != 0:
                panel("TEST FAILED", f"```\n{output[:2000]}\n```")
                self.run_agent(
                    f"The tests failed. Fix the errors:\n\n"
                    f"Command: {cmd}\nOutput:\n{output[-2000:]}"
                )
            else:
                ok("All tests passed!")
                if output:
                    print(output[:500])
        except Exception as e:
            err(f"Could not run tests: {e}")

    def _is_filesystem_query(self, goal: str) -> bool:
        """Detect simple filesystem count/search queries (avoid full agent mode)."""
        lowered = goal.lower()
        # Keywords that indicate a simple filesystem task
        fs_keywords = ["count", "search", "find", "list", "how many", "show me", "look in", "check", "dir", "ls"]
        return any(kw in lowered for kw in fs_keywords) and any(
            ext in lowered for ext in [
                ".mp3", ".flac", ".wav", ".m4a", ".ogg", ".aac",  # music
                ".mp4", ".mkv", ".avi", ".mov",  # video
                ".jpg", ".png", ".gif", ".bmp",  # images
                "music", "video", "picture", "photo", "image", "file", "dir", "folder"
            ]
        )

    def _execute_filesystem_query(self, goal: str) -> Optional[str]:
        """Execute a filesystem query directly using list_dir tool."""
        try:
            pm = PathManager(self.config.workspace)
            writer = SafeFileWriter(pm)
            executor = ToolExecutor(self.config, pm, writer)
            
            # Try common paths: Music, Videos, Pictures, Downloads, Desktop
            common_paths = [
                str(Path.home() / "Music"),
                str(Path.home() / "Videos"),
                str(Path.home() / "Pictures"),
                str(Path.home() / "Downloads"),
                str(Path.home() / "Desktop"),
                str(self.config.workspace),
            ]
            
            # Detect which directory the user is asking about
            lowered = goal.lower()
            search_path = None
            for path in common_paths:
                path_name = Path(path).name.lower()
                if path_name in lowered or ("music" in lowered and "Music" in path):
                    search_path = path
                    break
            
            # Fallback to Music if keywords match
            if not search_path:
                if any(kw in lowered for kw in ["music", ".mp3", ".flac", ".wav"]):
                    search_path = str(Path.home() / "Music")
                elif any(kw in lowered for kw in ["video", ".mp4", ".mkv"]):
                    search_path = str(Path.home() / "Videos")
                elif any(kw in lowered for kw in ["picture", "photo", "image", ".jpg", ".png"]):
                    search_path = str(Path.home() / "Pictures")
            
            if not search_path:
                search_path = str(self.config.workspace)
            
            # Detect file extension pattern
            pattern = None
            if "music" in lowered or any(ext in lowered for ext in [".mp3", ".flac", ".wav", ".m4a", ".ogg", ".aac"]):
                pattern = "*.mp3 *.flac *.wav *.m4a *.ogg *.aac"
            elif "video" in lowered or any(ext in lowered for ext in [".mp4", ".mkv", ".avi"]):
                pattern = "*.mp4 *.mkv *.avi *.mov"
            elif "image" in lowered or "photo" in lowered or any(ext in lowered for ext in [".jpg", ".png", ".gif"]):
                pattern = "*.jpg *.jpeg *.png *.gif *.bmp"
            
            # Execute list_dir
            action = {"action": "list_dir", "path": search_path, "recursive": True}
            if pattern:
                action["pattern"] = pattern
            
            is_final, result_json = executor.execute(action, assume_yes=True)
            
            # Parse result and count files
            try:
                result_data = json.loads(result_json)
                output = result_data.get("output", "")
                
                # Count files in output
                file_count = len([line for line in output.split("\n") if line.strip() and not line.startswith("---")])
                summary = f"Found {file_count} file(s) in {Path(search_path).name}. Details:\n{output[:500]}"
                
                panel("FILESYSTEM", summary)
                return summary
            except Exception as e:
                err(f"Could not parse result: {e}")
                return None
        
        except Exception as e:
            from .logger import get_logger
            logger = get_logger("commands")
            logger.debug(f"Filesystem query failed: {e}")
            return None

    def _is_direct_action(self, goal: str) -> bool:
        """Detect simple direct action requests that don't need full agent reasoning.
        
        Covers ~40% of user requests with instant dispatch (no LLM call).
        """
        lowered = goal.lower().strip()
        is_question = lowered.startswith(("what", "who", "how", "where", "is ", "are ", "can ", "does ", "do "))
        
        # Simple project creation: "create a python project", "create a flask app here"
        if re.match(r'create (?:a |an )?(?:python|node|flask|fastapi|express|cli)\s+(?:project|app|package)', lowered):
            return True
        # Framework project creation: "create a laravel project", "create a react native app"
        framework_keywords = [
            "laravel", "react", "vue", "angular", "django", "next", "nuxt",
            "svelte", "astro", "remix", "nestjs", "flutter", "expo", "electron",
            "tauri", "vite", "rails", "spring", "blazor", "dotnet",
        ]
        if re.match(r'(?:create|make|init|initialize|scaffold|setup|start)\s+(?:a |an |new )?', lowered):
            # Don't intercept multi-step tasks (those go to COMPLEX agent)
            multi_step_signals = [" then ", " and then ", " after that ", " also ", " plus ",
                                  "make the ui", "make it look", "look like", "copy the", "style it"]
            if any(sig in lowered for sig in multi_step_signals):
                return False
            if any(fw in lowered for fw in framework_keywords):
                return True
        
        # Play/stream music, videos
        play_keywords = ["play", "stream", "listen", "watch", "put on", "queue"]
        if any(kw in lowered for kw in play_keywords) and not is_question:
            return True
        
        # Git commands
        if lowered.startswith("git ") or lowered in ("git status", "git log", "git branch"):
            return True
        
        # Docker commands
        if lowered.startswith("docker "):
            return True
        
        # Package manager commands
        pkg_prefixes = ("npm ", "pip ", "yarn ", "pnpm ", "cargo ", "composer ", "go get ", "go install ")
        if any(lowered.startswith(p) for p in pkg_prefixes):
            return True
        
        # Network operations
        net_keywords = ["ping ", "dns ", "port check ", "traceroute ", "whois "]
        if any(lowered.startswith(kw) for kw in net_keywords):
            return True
        
        # Unit conversion: "convert X unit to unit" or "X km to mi"
        if lowered.startswith("convert ") or re.match(r'^\d+\.?\d*\s*\w+\s+(?:to|in)\s+\w+$', lowered):
            return True
        
        # Time/date
        if lowered in ("time", "date", "now", "what time is it", "current time", "today", "what day is it"):
            return True
        
        # Math expressions (contains operators and digits)
        if re.match(r'^[\d\s\+\-\*/\(\)\.\^%]+$', lowered) and any(c.isdigit() for c in lowered):
            return True
        
        # Crypto/hash/uuid/password
        crypto_triggers = ["hash ", "uuid", "generate uuid", "generate password", "random string", "password"]
        if any(lowered.startswith(t) or lowered == t for t in crypto_triggers):
            return True
        
        # Test running
        if lowered in ("run tests", "pytest", "test", "run test", "npm test", "cargo test"):
            return True
        if lowered.startswith("pytest ") or lowered.startswith("run tests"):
            return True
        
        # Code analysis shortcuts
        if lowered.startswith("lint ") or lowered.startswith("format "):
            return True
        if lowered in ("project health", "project info", "dependency tree"):
            return True
        
        # File operations
        if lowered.startswith("tree ") or lowered == "tree":
            return True
        if lowered.startswith("disk usage ") or lowered.startswith("find large ") or lowered.startswith("find duplicates "):
            return True
        
        # Assistant features
        assistant_triggers = [
            "organize", "arrange", "sort my files", "clean up", "cleanup",
            "tidy up", "declutter", "file summary", "what's in my",
            "remind me", "set reminder", "set a reminder", "check reminders",
            "note", "take a note", "save note", "show notes", "my notes",
            "system health", "health check", "disk space", "how much space",
            "undo organize", "undo the",
            # New productivity features
            "open app", "launch", "start app",
            "kill process", "end task", "close app",
            "running processes", "what's running", "top processes",
            "start timer", "stop timer", "set timer", "stopwatch",
            "wifi password", "wifi passwords", "show wifi",
            "startup programs", "startup apps", "what starts on boot",
            "clipboard history", "copy to clipboard",
            "rename files", "batch rename", "smart rename",
            "save snippet", "get snippet", "my snippets",
            # Life management features
            "weather", "what's the weather", "temperature",
            "translate", "translation",
            "draft email", "email draft", "write email",
            "pomodoro", "start pomodoro", "focus time",
            "log habit", "my habits", "habit",
            "spent", "expense", "spending", "how much did i spend",
            "my plan", "today's plan", "add to plan", "schedule",
            "test api", "api test",
            # Power tools
            "screenshot", "take screenshot", "capture screen",
            "my ip", "ip info", "what's my ip", "ip address",
            "say ", "speak ", "read aloud", "text to speech",
            "bookmark", "save bookmark", "my bookmarks",
            "motivate me", "motivation", "inspire me", "quote",
            "lock screen", "lock pc", "sleep pc", "shutdown", "restart",
            "speed test", "internet speed", "test speed",
            "word count", "text stats", "count words",
            "color", "convert color", "hex to rgb",
            "lorem ipsum", "placeholder text", "dummy text",
            # Smart tools
            "shorten", "short url", "tinyurl",
            "define ", "definition", "what does", "meaning of",
            "time in ", "timezone", "world clock", "what time in",
            "days until", "countdown", "how many days",
            "random", "generate random", "pick random",
            "regex", "test regex", "match pattern",
            "scan ports", "port scan", "open ports",
            "is it up", "uptime", "check if",
            "git summary", "git info", "repo info",
            # Daily life tools
            "my age", "age calculator", "how old",
            "bmi", "body mass",
            "tip calculator", "calculate tip", "split bill",
            "loan calculator", "mortgage", "monthly payment",
            "drank water", "water intake", "log water",
            "slept", "sleep log", "bedtime", "sleep tracker",
            "flashcard", "study", "quiz me",
            "add contact", "my contacts", "find contact",
            "affirmation", "affirm",
            # Automation tools
            "download youtube", "youtube download", "yt-dlp", "download video",
            "download audio", "download mp3", "download mp4",
            "summarize pdf", "pdf summary", "read pdf", "extract pdf",
            "resize image", "scale image", "shrink image", "image resize",
            "backup", "auto backup", "create backup", "snapshot",
            "daily digest", "my digest", "today's digest", "activity summary",
            "project stats", "code stats", "loc", "lines of code",
            "audit dependencies", "dependency audit", "check dependencies",
            "outdated packages", "vulnerable packages",
            "docker compose", "compose up", "compose down", "docker build",
            "docker prune", "docker stats", "generate dockerfile",
            "auto commit", "smart commit", "commit changes", "quick commit",
            "cron", "schedule task", "scheduled tasks", "add cron",
            "list cron", "remove cron", "my tasks",
        ]
        if any(trigger in lowered for trigger in assistant_triggers):
            return True
        
        # Web search
        search_keywords = ["search", "google", "look up", "find info"]
        if any(kw in lowered for kw in search_keywords) and len(lowered.split()) > 2:
            return True
        
        # Open URL
        if lowered.startswith("open ") and ("http" in lowered or "www." in lowered or ".com" in lowered):
            return True
        
        # Shell command with explicit markers
        run_keywords = ["run", "execute", "bash", "cmd"]
        if any(kw in lowered for kw in run_keywords) and any(c in goal for c in ["=", "--", ":", "|"]):
            return True
        
        return False

    def _execute_direct_action(self, goal: str) -> Optional[str]:
        """Execute a direct action immediately without full agent reasoning.
        
        Instant dispatch: regex pattern → tool call. No LLM overhead.
        Covers: git, docker, packages, network, conversion, time, math, crypto,
        tests, lint, project health, file ops, search, open URL, shell commands.
        """
        try:
            pm = PathManager(self.config.workspace)
            if self.last_target:
                pm.set_target(self.last_target)
            writer = SafeFileWriter(pm)
            executor = ToolExecutor(self.config, pm, writer)
            
            lowered = goal.lower().strip()
            
            # ── Media status ──
            if any(p in lowered for p in ["what's playing", "what is playing", "current song", "now playing", "what song"]):
                action = {"action": "media_status"}
                return self._exec_and_display(executor, action, "MEDIA STATUS")
            
            # ── Simple Project Creation ──
            proj_match = re.match(r'create (?:a |an )?(\w+)\s+(?:project|app|package)(?:\s+(?:called|named)\s+(\w+))?(?:\s+(?:in|at|into)\s+(.+))?', lowered)
            if proj_match:
                template_map = {"python": "python_package", "node": "node_app", "flask": "flask_app",
                                "fastapi": "fastapi_app", "express": "express_app", "cli": "cli_tool"}
                lang = proj_match.group(1)
                name = proj_match.group(2) or f"my_{lang}_project"
                location = proj_match.group(3) or ""
                
                # Check if this is a framework that should use create_project_with_deps
                from .dep_installer import detect_framework_from_goal, create_project_with_deps
                detected_fw = detect_framework_from_goal(goal)
                if detected_fw:
                    # Resolve location
                    if location:
                        location = location.strip()
                        loc_map = {"downloads": str(Path.home() / "Downloads"), "download": str(Path.home() / "Downloads"),
                                   "desktop": str(Path.home() / "Desktop"), "documents": str(Path.home() / "Documents")}
                        clean_loc = re.sub(r'\s*(folder|directory|dir)$', '', location).strip()
                        resolved_loc = loc_map.get(clean_loc, "")
                        if not resolved_loc:
                            p = Path(location).expanduser().resolve()
                            if p.exists() and p.is_dir():
                                resolved_loc = str(p)
                        target = resolved_loc or str(pm.effective_root)
                    else:
                        target = str(pm.effective_root)
                    
                    success, output = create_project_with_deps(detected_fw, name, target)
                    if success:
                        ai(output[-500:] if len(output) > 500 else output)
                    else:
                        err(output[:500])
                    self.memory.add_event(f"PROJECT INIT ({detected_fw}): {output[:300]}")
                    return output
                
                # Fallback to simple template-based creation
                template = template_map.get(lang, "python_package")
                # Resolve location
                if location:
                    location = location.strip()
                    # Handle symbolic locations
                    loc_map = {"downloads": str(Path.home() / "Downloads"), "download": str(Path.home() / "Downloads"),
                               "pc downloads folder": str(Path.home() / "Downloads"), "pc downloads": str(Path.home() / "Downloads"),
                               "desktop": str(Path.home() / "Desktop"), "documents": str(Path.home() / "Documents"),
                               "my downloads": str(Path.home() / "Downloads"), "my desktop": str(Path.home() / "Desktop")}
                    # Check symbolic names (strip "folder", "directory" suffixes)
                    clean_loc = re.sub(r'\s*(folder|directory|dir)$', '', location).strip()
                    resolved_loc = loc_map.get(clean_loc, "")
                    if not resolved_loc:
                        # Try as literal path
                        p = Path(location).expanduser().resolve()
                        if p.exists() and p.is_dir():
                            resolved_loc = str(p)
                    if resolved_loc:
                        action = {"action": "project_init", "template": template, "name": name, "path": resolved_loc}
                        return self._exec_and_display(executor, action, "PROJECT INIT")
                # Default to CWD
                action = {"action": "project_init", "template": template, "name": name, "path": str(pm.effective_root)}
                return self._exec_and_display(executor, action, "PROJECT INIT")
            
            # ── Git Operations ──
            if lowered.startswith("git "):
                parts = goal[4:].strip().split(maxsplit=1)
                operation = parts[0].lower() if parts else "status"
                args = parts[1] if len(parts) > 1 else ""
                # Map common git subcommands to our operations
                git_map = {"status": "status", "log": "log", "branch": "branch", "stash": "stash",
                           "tag": "tag", "remote": "remote", "blame": "blame", "diff": "diff_staged",
                           "merge": "merge", "rebase": "rebase", "cherry-pick": "cherry_pick", "reset": "reset"}
                op = git_map.get(operation, operation)
                action = {"action": "git_op", "operation": op, "args": args, "path": str(pm.effective_root)}
                return self._exec_and_display(executor, action, f"GIT {operation.upper()}")
            
            # ── Docker Operations ──
            if lowered.startswith("docker "):
                parts = goal[7:].strip().split(maxsplit=1)
                operation = parts[0].lower() if parts else "ps"
                target = parts[1] if len(parts) > 1 else ""
                docker_map = {"ps": "ps", "images": "images", "run": "run", "stop": "stop",
                              "rm": "rm", "logs": "logs", "build": "build", "pull": "pull",
                              "exec": "exec", "inspect": "inspect", "compose": "compose_up"}
                op = docker_map.get(operation, operation)
                if operation == "compose" and "down" in target:
                    op = "compose_down"
                    target = ""
                action = {"action": "docker_op", "operation": op, "target": target}
                return self._exec_and_display(executor, action, f"DOCKER {operation.upper()}")
            
            # ── Package Manager Operations ──
            pkg_managers = {"npm": "npm", "pip": "pip", "yarn": "yarn", "pnpm": "pnpm",
                           "cargo": "cargo", "composer": "composer"}
            for prefix, mgr in pkg_managers.items():
                if lowered.startswith(prefix + " "):
                    parts = goal[len(prefix)+1:].strip().split(maxsplit=1)
                    operation = parts[0].lower() if parts else "list"
                    package = parts[1] if len(parts) > 1 else ""
                    action = {"action": "package_op", "manager": mgr, "operation": operation, "package": package}
                    return self._exec_and_display(executor, action, f"{mgr.upper()} {operation.upper()}")
            if lowered.startswith("go get ") or lowered.startswith("go install "):
                parts = goal.split(maxsplit=2)
                package = parts[2] if len(parts) > 2 else ""
                action = {"action": "package_op", "manager": "go", "operation": "install", "package": package}
                return self._exec_and_display(executor, action, "GO INSTALL")
            
            # ── Network Operations ──
            if lowered.startswith("ping "):
                target = goal[5:].strip()
                action = {"action": "net_op", "operation": "ping", "target": target}
                return self._exec_and_display(executor, action, "PING")
            if lowered.startswith("dns "):
                target = goal[4:].strip()
                action = {"action": "net_op", "operation": "dns", "target": target}
                return self._exec_and_display(executor, action, "DNS LOOKUP")
            if lowered.startswith("port check ") or lowered.startswith("check port "):
                target = re.sub(r'^(?:port check|check port)\s+', '', goal, flags=re.IGNORECASE).strip()
                action = {"action": "net_op", "operation": "port_check", "target": target}
                return self._exec_and_display(executor, action, "PORT CHECK")
            if lowered.startswith("traceroute "):
                target = goal[11:].strip()
                action = {"action": "net_op", "operation": "traceroute", "target": target}
                return self._exec_and_display(executor, action, "TRACEROUTE")
            if lowered.startswith("whois "):
                target = goal[6:].strip()
                action = {"action": "net_op", "operation": "whois", "target": target}
                return self._exec_and_display(executor, action, "WHOIS")
            
            # ── Unit Conversion ──
            if lowered.startswith("convert "):
                # "convert 5 km to mi" or "convert 100 f to c"
                match = re.match(r'convert\s+([\d.]+)\s*(\w+)\s+(?:to|in)\s+(\w+)', lowered)
                if match:
                    value, from_u, to_u = match.group(1), match.group(2), match.group(3)
                    # Auto-detect category
                    cat = self._detect_unit_category(from_u, to_u)
                    action = {"action": "convert", "category": cat, "value": value, "from_unit": from_u, "to_unit": to_u}
                    return self._exec_and_display(executor, action, "CONVERT")
            # "5 km to mi" pattern
            conv_match = re.match(r'^([\d.]+)\s*(\w+)\s+(?:to|in)\s+(\w+)$', lowered)
            if conv_match:
                value, from_u, to_u = conv_match.group(1), conv_match.group(2), conv_match.group(3)
                cat = self._detect_unit_category(from_u, to_u)
                action = {"action": "convert", "category": cat, "value": value, "from_unit": from_u, "to_unit": to_u}
                return self._exec_and_display(executor, action, "CONVERT")
            
            # ── Time/Date ──
            if lowered in ("time", "date", "now", "what time is it", "current time", "today", "what day is it"):
                action = {"action": "datetime_util", "operation": "now"}
                return self._exec_and_display(executor, action, "TIME")
            
            # ── Math ──
            if re.match(r'^[\d\s\+\-\*/\(\)\.\^%]+$', lowered) and any(c.isdigit() for c in lowered):
                expr = goal.strip().replace("^", "**")
                action = {"action": "calculate", "expression": expr}
                return self._exec_and_display(executor, action, "CALCULATE")
            
            # ── Crypto/Hash/UUID/Password ──
            if lowered.startswith("hash "):
                text = goal[5:].strip()
                action = {"action": "crypto_op", "operation": "hash", "input": text}
                return self._exec_and_display(executor, action, "HASH")
            if lowered in ("uuid", "generate uuid"):
                action = {"action": "crypto_op", "operation": "uuid"}
                return self._exec_and_display(executor, action, "UUID")
            if lowered in ("password", "generate password") or lowered.startswith("generate password"):
                length = re.search(r'\d+', goal)
                action = {"action": "crypto_op", "operation": "password", "input": length.group() if length else "16"}
                return self._exec_and_display(executor, action, "PASSWORD")
            if lowered.startswith("random"):
                length = re.search(r'\d+', goal)
                action = {"action": "crypto_op", "operation": "random", "input": length.group() if length else "32"}
                return self._exec_and_display(executor, action, "RANDOM")
            
            # ── Test Running ──
            if lowered in ("run tests", "pytest", "test", "run test", "npm test", "cargo test") or lowered.startswith("pytest ") or lowered.startswith("run tests"):
                action = {"action": "test_op", "operation": "run", "path": str(pm.effective_root)}
                return self._exec_and_display(executor, action, "RUNNING TESTS")
            
            # ── Code Analysis ──
            if lowered.startswith("lint "):
                path = goal[5:].strip() or "."
                action = {"action": "code_analyze", "operation": "lint", "path": str(pm.resolve_target(path))}
                return self._exec_and_display(executor, action, "LINT")
            if lowered.startswith("format ") and not lowered.startswith("format_convert"):
                path = goal[7:].strip() or "."
                action = {"action": "code_analyze", "operation": "format_check", "path": str(pm.resolve_target(path))}
                return self._exec_and_display(executor, action, "FORMAT CHECK")
            
            # ── Project Operations ──
            if lowered in ("project health", "health check", "check health"):
                action = {"action": "project_health", "path": str(pm.effective_root)}
                return self._exec_and_display(executor, action, "PROJECT HEALTH")
            if lowered in ("project info", "project details"):
                action = {"action": "project_info", "path": str(pm.effective_root)}
                return self._exec_and_display(executor, action, "PROJECT INFO")
            if lowered in ("dependency tree", "deps", "dependencies"):
                action = {"action": "dependency_tree", "path": str(pm.effective_root)}
                return self._exec_and_display(executor, action, "DEPENDENCIES")
            
            # ── File Operations ──
            if lowered == "tree" or lowered.startswith("tree "):
                path = goal[5:].strip() if lowered.startswith("tree ") else "."
                action = {"action": "file_op_ext", "operation": "tree", "path": str(pm.resolve_target(path))}
                return self._exec_and_display(executor, action, "TREE")
            if lowered.startswith("disk usage "):
                path = goal[11:].strip()
                action = {"action": "file_op_ext", "operation": "disk_usage", "path": str(pm.resolve_target(path))}
                return self._exec_and_display(executor, action, "DISK USAGE")
            if lowered.startswith("find large "):
                path = goal[11:].strip()
                action = {"action": "file_op_ext", "operation": "find_large", "path": str(pm.resolve_target(path))}
                return self._exec_and_display(executor, action, "FIND LARGE FILES")
            if lowered.startswith("find duplicates "):
                path = goal[16:].strip()
                action = {"action": "file_op_ext", "operation": "find_duplicates", "path": str(pm.resolve_target(path))}
                return self._exec_and_display(executor, action, "FIND DUPLICATES")
            
            # ── Play/Stream Media ──
            if any(kw in lowered for kw in ["play", "stream", "listen", "watch", "put on", "queue"]):
                action = {"action": "play_media", "query": goal}
                return self._exec_and_display(executor, action, "PLAYING MEDIA")
            
            # ── Assistant: Organize Files ──
            if any(kw in lowered for kw in ["organize", "arrange", "sort my files", "tidy up", "declutter"]):
                # Detect target directory
                target_path = str(pm.effective_root)
                dir_map = {"downloads": str(Path.home() / "Downloads"), "desktop": str(Path.home() / "Desktop"),
                           "documents": str(Path.home() / "Documents"), "pictures": str(Path.home() / "Pictures")}
                for dirname, dirpath in dir_map.items():
                    if dirname in lowered:
                        target_path = dirpath
                        break
                # Default to preview mode for safety
                mode = "execute" if any(w in lowered for w in ["now", "do it", "execute", "go ahead"]) else "preview"
                action = {"action": "organize_files", "path": target_path, "mode": mode}
                return self._exec_and_display(executor, action, "ORGANIZE FILES")
            
            # ── Assistant: Undo Organize ──
            if "undo" in lowered and ("organize" in lowered or "arrange" in lowered or "move" in lowered):
                action = {"action": "undo_organize"}
                return self._exec_and_display(executor, action, "UNDO ORGANIZE")
            
            # ── Assistant: Smart Cleanup ──
            if any(kw in lowered for kw in ["clean up", "cleanup", "remove junk", "remove temp"]):
                target_path = str(pm.effective_root)
                dir_map = {"downloads": str(Path.home() / "Downloads"), "desktop": str(Path.home() / "Desktop")}
                for dirname, dirpath in dir_map.items():
                    if dirname in lowered:
                        target_path = dirpath
                        break
                mode = "execute" if any(w in lowered for w in ["now", "do it", "execute"]) else "preview"
                action = {"action": "smart_cleanup", "path": target_path, "mode": mode}
                return self._exec_and_display(executor, action, "CLEANUP")
            
            # ── Assistant: File Summary ──
            if any(kw in lowered for kw in ["file summary", "what's in my", "summarize"]):
                target_path = str(pm.effective_root)
                dir_map = {"downloads": str(Path.home() / "Downloads"), "desktop": str(Path.home() / "Desktop"),
                           "documents": str(Path.home() / "Documents")}
                for dirname, dirpath in dir_map.items():
                    if dirname in lowered:
                        target_path = dirpath
                        break
                action = {"action": "file_summary", "path": target_path}
                return self._exec_and_display(executor, action, "FILE SUMMARY")
            
            # ── Assistant: Reminders ──
            if any(kw in lowered for kw in ["remind me", "set reminder", "set a reminder"]):
                # Extract message and time
                message = goal
                minutes = 0
                for kw in ["remind me to ", "remind me ", "set reminder ", "set a reminder "]:
                    if kw in lowered:
                        message = goal[lowered.index(kw) + len(kw):].strip()
                        break
                # Check for "in X minutes"
                import re as _re_remind
                time_match = _re_remind.search(r'in\s+(\d+)\s*(?:min|minute|minutes|m)\b', lowered)
                if time_match:
                    minutes = int(time_match.group(1))
                    message = _re_remind.sub('', message).strip()
                action = {"action": "schedule_reminder", "message": message, "minutes": minutes}
                return self._exec_and_display(executor, action, "REMINDER SET")
            
            if "check reminder" in lowered or "my reminder" in lowered or "reminders" in lowered:
                action = {"action": "check_reminders"}
                return self._exec_and_display(executor, action, "REMINDERS")
            
            # ── Assistant: Notes ──
            if any(kw in lowered for kw in ["take a note", "save note", "note:"]):
                content = goal
                for kw in ["take a note ", "save note ", "note: ", "note "]:
                    if kw in lowered:
                        content = goal[lowered.index(kw) + len(kw):].strip()
                        break
                action = {"action": "quick_note", "content": content}
                return self._exec_and_display(executor, action, "NOTE SAVED")
            
            if any(kw in lowered for kw in ["show notes", "my notes", "list notes", "recent notes"]):
                action = {"action": "list_notes"}
                return self._exec_and_display(executor, action, "NOTES")
            
            # ── Assistant: System Health ──
            if any(kw in lowered for kw in ["system health", "health check", "disk space", "how much space", "ram usage", "cpu usage"]):
                action = {"action": "system_health"}
                return self._exec_and_display(executor, action, "SYSTEM HEALTH")
            
            # ── Productivity: Open App ──
            if any(kw in lowered for kw in ["open app", "launch ", "start app"]):
                app_name = goal
                for kw in ["open app ", "launch ", "start app ", "open "]:
                    if kw in lowered:
                        app_name = goal[lowered.index(kw) + len(kw):].strip()
                        break
                action = {"action": "open_app", "name": app_name}
                return self._exec_and_display(executor, action, "OPENING APP")
            
            # ── Productivity: Process Management ──
            if any(kw in lowered for kw in ["running processes", "what's running", "top processes", "show processes"]):
                action = {"action": "list_processes", "sort_by": "memory"}
                return self._exec_and_display(executor, action, "PROCESSES")
            
            if any(kw in lowered for kw in ["kill process", "end task", "close app", "kill "]):
                target = goal
                for kw in ["kill process ", "end task ", "close app ", "kill "]:
                    if kw in lowered:
                        target = goal[lowered.index(kw) + len(kw):].strip()
                        break
                action = {"action": "kill_process", "target": target}
                return self._exec_and_display(executor, action, "KILL PROCESS")
            
            # ── Productivity: Timer/Stopwatch ──
            if any(kw in lowered for kw in ["start stopwatch", "start timer", "begin timer"]):
                import re as _re_timer
                sec_match = _re_timer.search(r'(\d+)\s*(?:sec|second|s\b|min|minute|m\b)', lowered)
                if sec_match:
                    val = int(sec_match.group(1))
                    if "min" in lowered:
                        val *= 60
                    action = {"action": "timer", "operation": "set_timer", "seconds": val}
                else:
                    action = {"action": "timer", "operation": "start_stopwatch"}
                return self._exec_and_display(executor, action, "TIMER")
            
            if any(kw in lowered for kw in ["stop stopwatch", "stop timer", "timer done"]):
                action = {"action": "timer", "operation": "stop_stopwatch"}
                return self._exec_and_display(executor, action, "TIMER")
            
            if any(kw in lowered for kw in ["check timer", "how long", "time left"]):
                action = {"action": "timer", "operation": "check_timer"}
                return self._exec_and_display(executor, action, "TIMER")
            
            # ── Productivity: Wi-Fi Passwords ──
            if any(kw in lowered for kw in ["wifi password", "wifi passwords", "show wifi", "saved wifi"]):
                action = {"action": "wifi_passwords"}
                return self._exec_and_display(executor, action, "WIFI PASSWORDS")
            
            # ── Productivity: Startup Programs ──
            if any(kw in lowered for kw in ["startup programs", "startup apps", "what starts on boot", "autostart"]):
                action = {"action": "startup_programs"}
                return self._exec_and_display(executor, action, "STARTUP PROGRAMS")
            
            # ── Productivity: Clipboard ──
            if any(kw in lowered for kw in ["clipboard history", "show clipboard", "recent copies"]):
                action = {"action": "clipboard_history", "operation": "show"}
                return self._exec_and_display(executor, action, "CLIPBOARD")
            
            if "copy to clipboard" in lowered or "copy this" in lowered:
                content = goal
                for kw in ["copy to clipboard ", "copy this "]:
                    if kw in lowered:
                        content = goal[lowered.index(kw) + len(kw):].strip()
                        break
                action = {"action": "clipboard_history", "operation": "copy", "content": content}
                return self._exec_and_display(executor, action, "COPIED")
            
            # ── Productivity: Snippets ──
            if any(kw in lowered for kw in ["save snippet", "save a snippet"]):
                # Parse "save snippet name: content"
                parts = goal.split(":", 1)
                name = parts[0].replace("save snippet", "").replace("save a snippet", "").strip()
                content = parts[1].strip() if len(parts) > 1 else ""
                action = {"action": "snippet", "operation": "save", "name": name, "content": content}
                return self._exec_and_display(executor, action, "SNIPPET SAVED")
            
            if any(kw in lowered for kw in ["get snippet", "show snippet", "my snippets", "list snippets"]):
                if "list" in lowered or "my snippets" in lowered:
                    action = {"action": "snippet", "operation": "list"}
                else:
                    name = goal
                    for kw in ["get snippet ", "show snippet "]:
                        if kw in lowered:
                            name = goal[lowered.index(kw) + len(kw):].strip()
                            break
                    action = {"action": "snippet", "operation": "get", "name": name}
                return self._exec_and_display(executor, action, "SNIPPET")
            
            # ── Productivity: Smart Rename ──
            if any(kw in lowered for kw in ["rename files", "batch rename", "smart rename"]):
                target_path = str(pm.effective_root)
                pattern = "cleanup"  # Default
                if "date" in lowered:
                    pattern = "date_prefix"
                elif "number" in lowered:
                    pattern = "number"
                elif "lowercase" in lowered:
                    pattern = "lowercase"
                mode = "execute" if "now" in lowered else "preview"
                action = {"action": "smart_rename", "path": target_path, "pattern": pattern, "mode": mode}
                return self._exec_and_display(executor, action, "RENAME FILES")
            
            # ── Life: Weather ──
            if any(kw in lowered for kw in ["weather", "temperature", "forecast"]):
                location = ""
                for kw in ["weather in ", "weather for ", "temperature in "]:
                    if kw in lowered:
                        location = goal[lowered.index(kw) + len(kw):].strip()
                        break
                action = {"action": "weather", "location": location}
                return self._exec_and_display(executor, action, "WEATHER")
            
            # ── Life: Translate ──
            if any(kw in lowered for kw in ["translate", "translation"]):
                import re as _re_tr
                # Pattern: "translate X to Y" or "translate X in Y"
                match = _re_tr.search(r'translate\s+["\']?(.+?)["\']?\s+(?:to|in|into)\s+(\w+)', goal, re.IGNORECASE)
                if match:
                    text, to_lang = match.group(1).strip(), match.group(2).strip()
                    action = {"action": "translate", "text": text, "to": to_lang}
                    return self._exec_and_display(executor, action, "TRANSLATE")
            
            # ── Life: Email Draft ──
            if any(kw in lowered for kw in ["draft email", "email draft", "write email", "compose email"]):
                # Try to extract "to X about Y"
                import re as _re_email
                match = _re_email.search(r'(?:to|for)\s+(\w+)\s+(?:about|regarding|re)\s+(.+)', goal, re.IGNORECASE)
                if match:
                    to, subject = match.group(1), match.group(2).strip()
                else:
                    to, subject = "Recipient", goal.replace("draft email", "").replace("email draft", "").strip() or "Follow up"
                action = {"action": "email_draft", "to": to, "subject": subject}
                return self._exec_and_display(executor, action, "EMAIL DRAFT")
            
            # ── Life: Pomodoro ──
            if any(kw in lowered for kw in ["pomodoro", "focus time", "focus session"]):
                if "stop" in lowered or "end" in lowered:
                    op = "stop"
                elif "status" in lowered or "check" in lowered:
                    op = "status"
                elif "stats" in lowered:
                    op = "stats"
                else:
                    op = "start"
                action = {"action": "pomodoro", "operation": op}
                return self._exec_and_display(executor, action, "POMODORO")
            
            # ── Life: Habit Tracker ──
            if any(kw in lowered for kw in ["log habit", "habit:", "my habits", "habits this week"]):
                if "week" in lowered:
                    action = {"action": "habit_tracker", "operation": "week"}
                elif any(kw in lowered for kw in ["log habit", "habit:"]):
                    habit_name = goal
                    for kw in ["log habit ", "habit: ", "log "]:
                        if kw in lowered:
                            habit_name = goal[lowered.index(kw) + len(kw):].strip()
                            break
                    action = {"action": "habit_tracker", "operation": "log", "habit": habit_name}
                else:
                    action = {"action": "habit_tracker", "operation": "list"}
                return self._exec_and_display(executor, action, "HABITS")
            
            # ── Life: Expense Tracker ──
            if any(kw in lowered for kw in ["spent", "expense", "spending"]):
                import re as _re_exp
                # Pattern: "spent 50 on groceries" or "expense 20 food"
                match = _re_exp.search(r'(?:spent|expense)\s+\$?(\d+\.?\d*)\s+(?:on\s+)?(\w+)', lowered)
                if match:
                    amount, category = float(match.group(1)), match.group(2)
                    action = {"action": "expense_tracker", "operation": "add", "amount": amount, "category": category}
                elif "summary" in lowered or "how much" in lowered:
                    action = {"action": "expense_tracker", "operation": "summary"}
                elif "today" in lowered:
                    action = {"action": "expense_tracker", "operation": "today"}
                else:
                    action = {"action": "expense_tracker", "operation": "summary"}
                return self._exec_and_display(executor, action, "EXPENSES")
            
            # ── Life: Daily Planner ──
            if any(kw in lowered for kw in ["my plan", "today's plan", "add to plan", "schedule", "daily plan"]):
                if "add" in lowered:
                    task_text = goal
                    for kw in ["add to plan ", "add to schedule ", "plan: "]:
                        if kw in lowered:
                            task_text = goal[lowered.index(kw) + len(kw):].strip()
                            break
                    action = {"action": "daily_planner", "operation": "add", "task": task_text}
                elif "done" in lowered or "complete" in lowered:
                    task_ref = goal.split("done")[-1].strip() if "done" in lowered else "1"
                    action = {"action": "daily_planner", "operation": "done", "task": task_ref}
                else:
                    action = {"action": "daily_planner", "operation": "show"}
                return self._exec_and_display(executor, action, "PLANNER")
            
            # ── Life: API Test ──
            if any(kw in lowered for kw in ["test api", "api test"]):
                import re as _re_api
                url_match = _re_api.search(r'(https?://\S+)', goal)
                url = url_match.group(1) if url_match else ""
                method = "POST" if "post" in lowered else "PUT" if "put" in lowered else "DELETE" if "delete" in lowered else "GET"
                action = {"action": "api_test", "url": url, "method": method}
                return self._exec_and_display(executor, action, "API TEST")
            
            # ── Power: Screenshot ──
            if any(kw in lowered for kw in ["screenshot", "take screenshot", "capture screen"]):
                action = {"action": "screenshot"}
                return self._exec_and_display(executor, action, "SCREENSHOT")
            
            # ── Power: IP Info ──
            if any(kw in lowered for kw in ["my ip", "ip info", "what's my ip", "ip address"]):
                target = ""
                import re as _re_ip
                ip_match = _re_ip.search(r'(\d+\.\d+\.\d+\.\d+)', goal)
                if ip_match:
                    target = ip_match.group(1)
                action = {"action": "ip_info", "target": target}
                return self._exec_and_display(executor, action, "IP INFO")
            
            # ── Power: Text-to-Speech ──
            if any(kw in lowered for kw in ["say ", "speak ", "read aloud", "text to speech"]):
                text = goal
                for kw in ["say ", "speak ", "read aloud ", "text to speech "]:
                    if kw in lowered:
                        text = goal[lowered.index(kw) + len(kw):].strip()
                        break
                action = {"action": "text_to_speech", "text": text}
                return self._exec_and_display(executor, action, "SPEAKING")
            
            # ── Power: Bookmarks ──
            if any(kw in lowered for kw in ["bookmark", "save bookmark", "my bookmarks"]):
                if "save" in lowered or "add" in lowered:
                    import re as _re_bm
                    url_match = _re_bm.search(r'(https?://\S+)', goal)
                    url = url_match.group(1) if url_match else ""
                    title = goal.replace("save bookmark", "").replace("bookmark", "").replace(url, "").strip()
                    action = {"action": "bookmarks", "operation": "add", "url": url, "title": title}
                else:
                    action = {"action": "bookmarks", "operation": "list"}
                return self._exec_and_display(executor, action, "BOOKMARKS")
            
            # ── Power: Motivation ──
            if any(kw in lowered for kw in ["motivate me", "motivation", "inspire me", "quote"]):
                action = {"action": "motivation"}
                return self._exec_and_display(executor, action, "MOTIVATION")
            
            # ── Power: System Actions ──
            if any(kw in lowered for kw in ["lock screen", "lock pc", "lock computer"]):
                action = {"action": "system_action", "operation": "lock"}
                return self._exec_and_display(executor, action, "SYSTEM")
            if "sleep pc" in lowered or "sleep computer" in lowered:
                action = {"action": "system_action", "operation": "sleep"}
                return self._exec_and_display(executor, action, "SYSTEM")
            if "empty recycle" in lowered or "empty trash" in lowered:
                action = {"action": "system_action", "operation": "empty_recycle_bin"}
                return self._exec_and_display(executor, action, "SYSTEM")
            
            # ── Power: Speed Test ──
            if any(kw in lowered for kw in ["speed test", "internet speed", "test speed", "how fast is my internet"]):
                action = {"action": "speed_test"}
                return self._exec_and_display(executor, action, "SPEED TEST")
            
            # ── Power: Word Count / Text Stats ──
            if any(kw in lowered for kw in ["word count", "text stats", "count words"]):
                text = goal
                for kw in ["word count ", "text stats ", "count words in "]:
                    if kw in lowered:
                        text = goal[lowered.index(kw) + len(kw):].strip()
                        break
                # Check if it's a file path
                if os.path.exists(text):
                    action = {"action": "text_stats", "file": text}
                else:
                    action = {"action": "text_stats", "text": text}
                return self._exec_and_display(executor, action, "TEXT STATS")
            
            # ── Power: Color Convert ──
            if any(kw in lowered for kw in ["convert color", "hex to rgb", "color info"]):
                color = goal
                for kw in ["convert color ", "color info ", "hex to rgb "]:
                    if kw in lowered:
                        color = goal[lowered.index(kw) + len(kw):].strip()
                        break
                action = {"action": "color_convert", "color": color}
                return self._exec_and_display(executor, action, "COLOR")
            
            # ── Power: Lorem Ipsum ──
            if any(kw in lowered for kw in ["lorem ipsum", "placeholder text", "dummy text"]):
                import re as _re_lorem
                num_match = _re_lorem.search(r'(\d+)', goal)
                count = int(num_match.group(1)) if num_match else 1
                if "word" in lowered:
                    action = {"action": "lorem_ipsum", "words": count}
                else:
                    action = {"action": "lorem_ipsum", "paragraphs": count}
                return self._exec_and_display(executor, action, "LOREM IPSUM")
            
            # ── Smart: Shorten URL ──
            if any(kw in lowered for kw in ["shorten", "short url", "tinyurl"]):
                import re as _re_short
                url_match = _re_short.search(r'(https?://\S+)', goal)
                url = url_match.group(1) if url_match else goal.split()[-1]
                action = {"action": "shorten_url", "url": url}
                return self._exec_and_display(executor, action, "SHORT URL")
            
            # ── Smart: Dictionary ──
            if any(kw in lowered for kw in ["define ", "definition", "meaning of"]):
                word = goal
                for kw in ["define ", "definition of ", "meaning of ", "what does ", "what is "]:
                    if kw in lowered:
                        word = goal[lowered.index(kw) + len(kw):].strip().split()[0]
                        break
                word = word.strip("?.,!")
                action = {"action": "define_word", "word": word}
                return self._exec_and_display(executor, action, "DEFINITION")
            
            # ── Smart: World Clock / Timezone ──
            if any(kw in lowered for kw in ["world clock", "time zones"]):
                action = {"action": "world_clock"}
                return self._exec_and_display(executor, action, "WORLD CLOCK")
            
            if any(kw in lowered for kw in ["time in ", "what time in", "timezone"]):
                import re as _re_tz
                # "time in tokyo" or "convert 3pm est to pht"
                city_match = _re_tz.search(r'(?:time in|what time in)\s+(\w+)', lowered)
                if city_match:
                    to_tz = city_match.group(1)
                    action = {"action": "timezone_convert", "to": to_tz}
                    return self._exec_and_display(executor, action, "TIMEZONE")
            
            # ── Smart: Countdown ──
            if any(kw in lowered for kw in ["days until", "countdown", "how many days until"]):
                target = goal
                for kw in ["days until ", "countdown to ", "how many days until "]:
                    if kw in lowered:
                        target = goal[lowered.index(kw) + len(kw):].strip()
                        break
                action = {"action": "countdown", "target": target}
                return self._exec_and_display(executor, action, "COUNTDOWN")
            
            # ── Smart: Random Generate ──
            if any(kw in lowered for kw in ["random color", "random name", "random number", "generate random", "pick random"]):
                gen_type = "number"
                if "color" in lowered: gen_type = "color"
                elif "name" in lowered: gen_type = "name"
                elif "emoji" in lowered: gen_type = "emoji"
                elif "sentence" in lowered: gen_type = "sentence"
                action = {"action": "random_generate", "type": gen_type, "count": 3}
                return self._exec_and_display(executor, action, "RANDOM")
            
            # ── Smart: Port Scan ──
            if any(kw in lowered for kw in ["scan ports", "port scan", "open ports"]):
                host = "localhost"
                import re as _re_port
                host_match = _re_port.search(r'(?:scan|ports on)\s+(\S+)', lowered)
                if host_match:
                    host = host_match.group(1)
                action = {"action": "port_scan", "host": host}
                return self._exec_and_display(executor, action, "PORT SCAN")
            
            # ── Smart: Uptime Check ──
            if any(kw in lowered for kw in ["is it up", "uptime", "check if"]):
                import re as _re_up
                url_match = _re_up.search(r'(https?://\S+|\S+\.\S+)', goal)
                url = url_match.group(1) if url_match else ""
                if url:
                    action = {"action": "uptime_check", "url": url}
                    return self._exec_and_display(executor, action, "UPTIME")
            
            # ── Smart: Git Summary ──
            if any(kw in lowered for kw in ["git summary", "git info", "repo info", "repo status"]):
                action = {"action": "git_summary", "path": str(pm.effective_root)}
                return self._exec_and_display(executor, action, "GIT SUMMARY")
            
            # ── Daily: Age Calculator ──
            if any(kw in lowered for kw in ["my age", "age calculator", "how old am i"]):
                import re as _re_age
                date_match = _re_age.search(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}/\d{1,2}/\d{4})', goal)
                if date_match:
                    action = {"action": "age_calc", "birthdate": date_match.group(1)}
                    return self._exec_and_display(executor, action, "AGE")
            
            # ── Daily: BMI ──
            if any(kw in lowered for kw in ["bmi", "body mass"]):
                import re as _re_bmi
                nums = _re_bmi.findall(r'(\d+\.?\d*)', goal)
                if len(nums) >= 2:
                    action = {"action": "bmi_calc", "weight": float(nums[0]), "height": float(nums[1])}
                    return self._exec_and_display(executor, action, "BMI")
            
            # ── Daily: Tip Calculator ──
            if any(kw in lowered for kw in ["tip calculator", "calculate tip", "split bill"]):
                import re as _re_tip
                nums = _re_tip.findall(r'(\d+\.?\d*)', goal)
                if nums:
                    bill = float(nums[0])
                    tip_pct = float(nums[1]) if len(nums) > 1 else 15
                    split = int(nums[2]) if len(nums) > 2 else 1
                    action = {"action": "tip_calc", "bill": bill, "tip": tip_pct, "split": split}
                    return self._exec_and_display(executor, action, "TIP")
            
            # ── Daily: Loan Calculator ──
            if any(kw in lowered for kw in ["loan calculator", "mortgage", "monthly payment"]):
                import re as _re_loan
                nums = _re_loan.findall(r'(\d+\.?\d*)', goal)
                if len(nums) >= 2:
                    principal = float(nums[0])
                    rate = float(nums[1])
                    years = int(nums[2]) if len(nums) > 2 else 30
                    action = {"action": "loan_calc", "principal": principal, "rate": rate, "years": years}
                    return self._exec_and_display(executor, action, "LOAN")
            
            # ── Daily: Water Tracker ──
            if any(kw in lowered for kw in ["drank water", "water intake", "log water", "drink water"]):
                if "status" in lowered or "how much" in lowered:
                    action = {"action": "water_tracker", "operation": "status"}
                else:
                    import re as _re_water
                    ml_match = _re_water.search(r'(\d+)\s*(?:ml|ML)', goal)
                    amount = int(ml_match.group(1)) if ml_match else 250
                    action = {"action": "water_tracker", "operation": "add", "amount": amount}
                return self._exec_and_display(executor, action, "WATER")
            
            # ── Daily: Sleep Tracker ──
            if any(kw in lowered for kw in ["slept", "sleep log", "sleep tracker"]):
                import re as _re_sleep
                hrs_match = _re_sleep.search(r'(\d+\.?\d*)\s*(?:h|hour)', lowered)
                if hrs_match:
                    action = {"action": "sleep_tracker", "operation": "log", "hours": float(hrs_match.group(1))}
                else:
                    action = {"action": "sleep_tracker", "operation": "status"}
                return self._exec_and_display(executor, action, "SLEEP")
            
            if "bedtime" in lowered or "when should i sleep" in lowered:
                action = {"action": "sleep_tracker", "operation": "suggest"}
                return self._exec_and_display(executor, action, "BEDTIME")
            
            # ── Daily: Flashcards ──
            if any(kw in lowered for kw in ["flashcard", "quiz me", "study cards"]):
                if "add" in lowered:
                    parts = goal.split(":")
                    front = parts[1].strip() if len(parts) > 1 else ""
                    back = parts[2].strip() if len(parts) > 2 else ""
                    action = {"action": "flashcards", "operation": "add", "front": front, "back": back}
                else:
                    action = {"action": "flashcards", "operation": "quiz"}
                return self._exec_and_display(executor, action, "FLASHCARDS")
            
            # ── Daily: Contacts ──
            if any(kw in lowered for kw in ["add contact", "my contacts", "find contact", "contact book"]):
                if "add" in lowered:
                    name_part = goal.replace("add contact", "").strip()
                    action = {"action": "contacts", "operation": "add", "name": name_part}
                elif "find" in lowered or "search" in lowered:
                    query = goal.split("find")[-1].strip() if "find" in lowered else goal.split("search")[-1].strip()
                    action = {"action": "contacts", "operation": "search", "name": query}
                else:
                    action = {"action": "contacts", "operation": "list"}
                return self._exec_and_display(executor, action, "CONTACTS")
            
            # ── Daily: Affirmation ──
            if any(kw in lowered for kw in ["affirmation", "affirm me", "positive message"]):
                action = {"action": "daily_affirmation"}
                return self._exec_and_display(executor, action, "AFFIRMATION")
            
            # ── Automation: YouTube Download ──
            if any(kw in lowered for kw in ["download youtube", "youtube download", "yt-dlp",
                                            "download video", "download audio", "download mp3", "download mp4"]):
                import re as _re_yt
                url_match = _re_yt.search(r'(https?://\S+)', goal)
                url = url_match.group(1) if url_match else goal.split()[-1]
                fmt = "mp3" if "mp3" in lowered or "audio" in lowered else "mp4"
                quality = "720" if "720" in lowered else "480" if "480" in lowered else "best"
                action = {"action": "youtube_download", "url": url, "format": fmt, "quality": quality}
                return self._exec_and_display(executor, action, "DOWNLOADING")
            
            # ── Automation: PDF Summarize ──
            if any(kw in lowered for kw in ["summarize pdf", "pdf summary", "read pdf", "extract pdf"]):
                file_path = ""
                for kw in ["summarize pdf ", "pdf summary ", "read pdf ", "extract pdf "]:
                    if kw in lowered:
                        file_path = goal[lowered.index(kw) + len(kw):].strip()
                        break
                if not file_path:
                    file_path = goal.split()[-1]
                mode = "outline" if "outline" in lowered else "extract" if "extract" in lowered else "summary"
                action = {"action": "pdf_summarize", "file": file_path, "mode": mode}
                return self._exec_and_display(executor, action, "PDF SUMMARY")
            
            # ── Automation: Image Resize ──
            if any(kw in lowered for kw in ["resize image", "scale image", "shrink image", "image resize"]):
                import re as _re_img
                file_path = ""
                # Try to find a file path
                path_match = _re_img.search(r'[\w/\\]+\.(?:jpg|jpeg|png|gif|webp|bmp)', goal, re.IGNORECASE)
                if path_match:
                    file_path = path_match.group(0)
                # Try to find dimensions
                dim_match = _re_img.search(r'(\d+)\s*[xX×]\s*(\d+)', goal)
                scale_match = _re_img.search(r'(\d+)%', goal)
                width_match = _re_img.search(r'width\s*[:=]?\s*(\d+)', lowered)
                if dim_match:
                    action = {"action": "image_resize", "file": file_path, "width": int(dim_match.group(1)), "height": int(dim_match.group(2))}
                elif scale_match:
                    action = {"action": "image_resize", "file": file_path, "scale": int(scale_match.group(1)) / 100.0}
                elif width_match:
                    action = {"action": "image_resize", "file": file_path, "width": int(width_match.group(1))}
                else:
                    action = {"action": "image_resize", "file": file_path, "scale": 0.5}
                return self._exec_and_display(executor, action, "IMAGE RESIZE")
            
            # ── Automation: Auto-Backup ──
            if any(kw in lowered for kw in ["backup", "auto backup", "create backup", "snapshot"]):
                target_path = str(pm.effective_root)
                # Check for specific path mentions
                parts = goal.split()
                for p in parts:
                    if os.path.exists(p) or os.path.sep in p or "/" in p:
                        target_path = p
                        break
                mode = "list" if "list" in lowered or "show" in lowered else "incremental" if "incremental" in lowered else "snapshot"
                action = {"action": "auto_backup", "path": target_path, "mode": mode}
                return self._exec_and_display(executor, action, "BACKUP")
            
            # ── Automation: Daily Digest ──
            if any(kw in lowered for kw in ["daily digest", "my digest", "today's digest", "activity summary"]):
                scope = "week" if "week" in lowered else "yesterday" if "yesterday" in lowered else "today"
                action = {"action": "daily_digest", "path": str(pm.effective_root), "scope": scope}
                return self._exec_and_display(executor, action, "DAILY DIGEST")
            
            # ── Automation: Project Stats ──
            if any(kw in lowered for kw in ["project stats", "code stats", "lines of code"]) or lowered == "loc":
                action = {"action": "project_stats", "path": str(pm.effective_root)}
                return self._exec_and_display(executor, action, "PROJECT STATS")
            
            # ── Automation: Dependency Audit ──
            if any(kw in lowered for kw in ["audit dependencies", "dependency audit", "check dependencies",
                                            "outdated packages", "vulnerable packages"]):
                fix = "fix" in lowered or "update" in lowered
                action = {"action": "dependency_audit", "path": str(pm.effective_root), "fix": fix}
                return self._exec_and_display(executor, action, "DEPENDENCY AUDIT")
            
            # ── Automation: Docker Helper ──
            if any(kw in lowered for kw in ["docker compose", "compose up", "compose down",
                                            "docker build", "docker prune", "docker stats",
                                            "generate dockerfile"]):
                if "compose up" in lowered or "compose start" in lowered:
                    operation = "compose_up"
                elif "compose down" in lowered or "compose stop" in lowered:
                    operation = "compose_down"
                elif "compose log" in lowered:
                    operation = "compose_logs"
                elif "compose status" in lowered or "compose ps" in lowered:
                    operation = "compose_status"
                elif "build" in lowered:
                    operation = "build"
                elif "prune" in lowered or "clean" in lowered:
                    operation = "prune"
                elif "stats" in lowered:
                    operation = "stats"
                elif "generate" in lowered or "dockerfile" in lowered:
                    operation = "generate"
                    # Detect project type
                    target = "python"
                    for t in ["node", "go", "rust", "python"]:
                        if t in lowered:
                            target = t
                            break
                    action = {"action": "docker_helper", "operation": operation, "target": target}
                    return self._exec_and_display(executor, action, "DOCKERFILE")
                else:
                    operation = "compose_status"
                action = {"action": "docker_helper", "operation": operation}
                return self._exec_and_display(executor, action, "DOCKER")
            
            # ── Automation: Auto-Commit ──
            if any(kw in lowered for kw in ["auto commit", "smart commit", "commit changes", "quick commit"]):
                message = ""
                for kw in ["auto commit ", "smart commit ", "commit changes ", "quick commit "]:
                    if kw in lowered:
                        message = goal[lowered.index(kw) + len(kw):].strip()
                        break
                action = {"action": "auto_commit", "path": str(pm.effective_root), "message": message, "mode": "smart"}
                return self._exec_and_display(executor, action, "AUTO COMMIT")
            
            # ── Automation: Cron Scheduler ──
            if any(kw in lowered for kw in ["cron", "schedule task", "scheduled tasks",
                                            "add cron", "list cron", "remove cron"]):
                if "list" in lowered or "show" in lowered or "scheduled tasks" in lowered:
                    action = {"action": "cron_scheduler", "operation": "list"}
                elif "add" in lowered or "schedule task" in lowered:
                    # Try to parse: "schedule task <name> every <interval> <command>"
                    import re as _re_cron
                    match = _re_cron.search(
                        r'(?:add cron|schedule task)\s+(\w+)\s+(every\s+\d+[mhd]|daily\s+\d{1,2}:\d{2}|hourly)\s+(.+)',
                        goal, re.IGNORECASE
                    )
                    if match:
                        name, schedule, command = match.group(1), match.group(2), match.group(3)
                        action = {"action": "cron_scheduler", "operation": "add",
                                  "name": name, "schedule": schedule, "command": command}
                    else:
                        action = {"action": "cron_scheduler", "operation": "list"}
                elif "remove" in lowered or "delete" in lowered:
                    name = goal.split()[-1]
                    action = {"action": "cron_scheduler", "operation": "remove", "name": name}
                elif "run" in lowered:
                    name = goal.split()[-1]
                    action = {"action": "cron_scheduler", "operation": "run", "name": name}
                elif "check" in lowered or "due" in lowered:
                    action = {"action": "cron_scheduler", "operation": "check"}
                else:
                    action = {"action": "cron_scheduler", "operation": "list"}
                return self._exec_and_display(executor, action, "CRON SCHEDULER")
            
            # ── Open URL ──
            if lowered.startswith("open ") and ("http" in lowered or "www." in lowered or ".com" in lowered):
                url = goal[5:].strip()
                action = {"action": "open_browser", "url": url}
                return self._exec_and_display(executor, action, "OPENING")
            
            # ── Web Search ──
            if any(kw in lowered for kw in ["search", "google", "look up", "find info"]):
                search_query = goal
                for kw in ["search ", "google ", "look up ", "find info "]:
                    if kw in lowered:
                        idx = lowered.index(kw)
                        search_query = goal[idx + len(kw):].strip()
                        break
                action = {"action": "web_search", "query": search_query}
                return self._exec_and_display(executor, action, "SEARCHING")
            
            # ── Shell Command ──
            if any(kw in lowered for kw in ["run ", "execute "]):
                cmd = goal
                for kw in ["run ", "execute "]:
                    if kw in lowered:
                        idx = lowered.index(kw)
                        cmd = goal[idx + len(kw):].strip()
                        break
                action = {"action": "run_cmd", "command": cmd}
                return self._exec_and_display(executor, action, "EXECUTING")
            
            return None
        
        except Exception as e:
            from .logger import get_logger
            logger = get_logger("commands")
            logger.debug(f"Direct action execution failed: {e}")
            return None

    def _exec_and_display(self, executor: 'ToolExecutor', action: dict, label: str) -> Optional[str]:
        """Execute a tool action and display the result cleanly. Returns output string."""
        is_final, result_json = executor.execute(action, assume_yes=True)
        try:
            result_data = json.loads(result_json)
            output = result_data.get("output", "")
            success = result_data.get("success", False)
            if success:
                ai(output[:2000] if len(output) > 2000 else output)
            else:
                err(output[:500])
            self.memory.add_event(f"{label}: {output[:300]}")
            return output
        except Exception:
            return result_json

    def _detect_unit_category(self, from_unit: str, to_unit: str) -> str:
        """Auto-detect conversion category from unit names."""
        length_units = {"m", "km", "cm", "mm", "mi", "yd", "ft", "in", "nm", "mile", "miles", "meter", "meters", "feet", "inch", "inches"}
        weight_units = {"kg", "g", "mg", "lb", "oz", "ton", "st", "pound", "pounds", "gram", "grams", "ounce"}
        temp_units = {"c", "f", "k", "celsius", "fahrenheit", "kelvin"}
        speed_units = {"m/s", "km/h", "mph", "knot", "ft/s", "kph"}
        data_units = {"b", "kb", "mb", "gb", "tb", "pb", "bit", "byte", "bytes"}
        time_units = {"s", "ms", "us", "ns", "min", "h", "d", "w", "sec", "hour", "day", "week", "minute"}
        
        both = {from_unit.lower(), to_unit.lower()}
        if both & length_units: return "length"
        if both & weight_units: return "weight"
        if both & temp_units: return "temperature"
        if both & speed_units: return "speed"
        if both & data_units: return "data_size"
        if both & time_units: return "time"
        return "length"  # default fallback

    def _try_ai_dispatch(self, goal: str) -> Optional[str]:
        """Use 0.5B model to classify goal → tool call for ambiguous requests.
        
        Only triggers for SHORT, TOOL-SHAPED requests that regex missed.
        Does NOT trigger for questions, complex goals, or creative tasks.
        
        Speed: ~0.5-1s (tiny model + GBNF grammar + max_tokens=50)
        """
        if not self._goal_dispatcher or not self._goal_dispatcher.is_ready:
            return None
        
        lowered = goal.lower().strip()
        
        # ONLY dispatch short, action-oriented requests (≤8 words)
        if len(lowered.split()) > 8:
            return None
        
        # Don't dispatch questions
        if lowered.startswith(("what", "how", "why", "where", "when", "who", "is ", "are ", "can ", "explain", "tell me")):
            return None
        
        # Don't dispatch goals that are clearly multi-step or creative
        skip_patterns = [
            "create ", "build ", "make ", "write ", "implement ", "design ",
            "refactor ", "fix ", "debug ", "deploy ", "setup ", "configure ",
            " and ", " then ", " after that", " step by step",
        ]
        if any(p in lowered for p in skip_patterns):
            return None
        
        try:
            from .goal_dispatcher import build_action_from_dispatch
            
            dispatch = self._goal_dispatcher.dispatch(goal)
            if not dispatch:
                return None
            
            # "agent" means the model thinks this needs full reasoning
            if dispatch["tool"] == "agent":
                return None
            
            # Build the action dict
            pm = PathManager(self.config.workspace)
            if self.last_target:
                pm.set_target(self.last_target)
            
            action = build_action_from_dispatch(dispatch, pm)
            if not action:
                return None
            
            # Execute the tool
            writer = SafeFileWriter(pm)
            executor = ToolExecutor(self.config, pm, writer)
            
            tool_name = dispatch["tool"]
            
            is_final, result_json = executor.execute(action, assume_yes=True)
            
            result_data = json.loads(result_json)
            output = result_data.get("output", "")
            success = result_data.get("success", False)
            
            if success:
                ai(output[:2000] if len(output) > 2000 else output)
            else:
                # If dispatch failed, don't return — let it fall through to agent
                err(f"Dispatch failed: {output[:200]}")
                return None
            
            return output
        
        except Exception as e:
            from .logger import get_logger
            logger = get_logger("commands")
            logger.debug(f"AI dispatch failed: {e}")
            return None

    def _is_vague_command(self, goal: str) -> bool:
        """Detect vague/unclear commands that need web search for context."""
        lowered = goal.lower().strip()
        # Skip if it's a continuation command
        if self._is_continuation_command(goal):
            return False
        
        # Pronouns or context words indicate it's likely a follow-up, not vague
        context_keywords = ["it", "them", "these", "those", "they", "file", "folder", "result", "that", "this"]
        if any(f" {kw} " in f" {lowered} " or lowered.endswith(kw) for kw in context_keywords):
            return False

        vague_patterns = [
            "help me", "help me with", "make it", "make me", "get me",
            "how to", "what is", "tell me about", "explain", "what's", "why is",
            "i need", "can you", "can i", "how do i", "how do you"
        ]
        # Vague if: matches pattern AND is short (< 8 words)
        if any(pattern in lowered for pattern in vague_patterns) and len(lowered.split()) < 8:
            return True
        return False
    
    def _search_for_vague_intent(self, goal: str) -> Optional[str]:
        """Search web for context on vague commands."""
        try:
            pm = PathManager(self.config.workspace)
            writer = SafeFileWriter(pm)
            executor = ToolExecutor(self.config, pm, writer)
            
            # Expand vague goal into a proper search query
            search_query = self._expand_vague_goal(goal)
            panel("WEB SEARCH", f"Searching for: {search_query}")
            
            action = {"action": "web_search", "query": search_query}
            is_final, result_json = executor.execute(action, assume_yes=True)
            
            try:
                result_data = json.loads(result_json)
                output = result_data.get("output", "")
                summary = f"Found information about: {search_query}\n\n{output[:1000]}"
                ok(summary)
                return summary
            except Exception:
                return result_json
        except Exception as e:
            from .logger import get_logger
            logger = get_logger("commands")
            logger.debug(f"Vague intent search failed: {e}")
            return None

    def _is_setup_guidance(self, goal: str) -> bool:
        """Detect setup/build/install requests that ACTUALLY need web search.
        
        Does NOT trigger for simple project creation when user has a clear target.
        """
        lowered = goal.lower().strip()

        # Never trigger if user said "here" or has a CWD set — they know what they want
        if "here" in lowered or self.last_target:
            return False
        
        # Never trigger for simple "create a X project" — the agent can handle that
        if lowered.startswith(("create a ", "create an ", "make a ", "make an ")):
            # Only trigger if it's a complex framework that needs specific install steps
            complex_frameworks = ["react native", "expo", "android", "ios", "flutter", "electron"]
            if not any(fw in lowered for fw in complex_frameworks):
                return False

        setup_keywords = [
            "set up", "setup", "install", "initialize", "init", "scaffold",
            "react native", "next js", "next.js", "expo", "android", "ios",
        ]
        action_words = ["help", "guide", "how to", "what should i", "what do i"]

        has_setup_shape = any(kw in lowered for kw in setup_keywords)
        has_action_shape = any(kw in lowered for kw in action_words)

        if has_setup_shape and has_action_shape:
            return True

        return False

    def _search_setup_guidance(self, goal: str) -> Optional[str]:
        """Search web for setup/build guidance and return a short actionable summary."""
        expanded = self._expand_vague_goal(goal)
        if not expanded or expanded == "how to get started":
            expanded = goal

        # Nudge the query toward installation/setup instructions.
        if "how to" not in expanded.lower() and "install" not in expanded.lower():
            expanded = f"how to {expanded}"

        return self._search_for_vague_intent(expanded)
    
    def _expand_vague_goal(self, goal: str) -> str:
        """Expand vague goal into a proper search query."""
        # Use the 0.5B rewriter model if available for best results
        if self._rewriter and not self._rewriter.is_ready:
            # Lazy-start the rewriter on first use
            self._rewriter.start()
        if self._rewriter and self._rewriter.is_ready:
            return self._rewriter.extract_search_query(goal)
        
        # Fallback: rule-based extraction
        lowered = goal.lower().strip()
        
        # Strip conversational filler words
        filler_words = {
            "the", "how", "can", "do", "get", "make", "help", "me", "you", 
            "with", "i", "need", "want", "please", "to", "a", "an", "my",
            "some", "just", "really", "actually", "basically", "like",
            "would", "could", "should", "am", "is", "are", "was", "were",
            "it", "this", "that", "for", "on", "in", "at", "of",
        }
        words = [w for w in goal.split() if len(w) > 1 and w.lower() not in filler_words]
        
        if not words:
            return "how to get started"
        
        # Extract the core topic (the meaningful part)
        core = " ".join(words)
        
        # If it already looks like a search query, use it directly
        if lowered.startswith(("how to ", "what is ", "install ", "setup ")):
            return goal.strip()
        
        # Detect the action verb and topic
        action_verbs = {"install", "installing", "setup", "setting", "create", "creating", "build", "building", "deploy", "deploying"}
        topic_words = []
        has_action = False
        for w in words:
            if w.lower() in action_verbs:
                has_action = True
            else:
                topic_words.append(w)
        
        topic = " ".join(topic_words) if topic_words else core
        
        if has_action:
            return f"install {topic} step by step"
        else:
            return f"how to {topic}"
    
    def _try_quick_response(self, goal: str) -> Optional[str]:
        """Master dispatcher for quick everyday utilities that don't need agent reasoning."""
        lowered = goal.lower().strip()
        result = (
            self._quick_time_date(lowered, goal) or
            self._quick_utilities(lowered, goal) or
            self._quick_unit_conversion(lowered, goal) or
            self._quick_text_ops(lowered, goal) or
            self._quick_open_url(lowered, goal) or
            self._quick_system_info(lowered, goal) or
            self._quick_find_files(lowered, goal)
        )
        return result
    
    def _quick_time_date(self, lowered: str, original: str) -> Optional[str]:
        """Handle time/date queries: what time, what day, when is, etc."""
        # Use word-boundary-aware matching to avoid "update" matching "date"
        time_phrases = ["what time", "current time", "what's the time", "what day", "today", "what date"]
        # "date" alone must be a standalone word (not part of "update")
        import re
        is_date_query = any(p in lowered for p in time_phrases) or re.search(r'\bdate\b', lowered) and len(lowered.split()) <= 4
        if is_date_query:
            from datetime import datetime
            now = datetime.now()
            day_name = now.strftime("%A")
            date_str = now.strftime("%B %d, %Y")
            time_str = now.strftime("%I:%M %p")
            result = f"{day_name}, {date_str} at {time_str}"
            panel("TIME & DATE", result)
            ok(result)
            return result
        return None
    
    def _quick_open_url(self, lowered: str, original: str) -> Optional[str]:
        """Handle URL opening: open google, go to youtube, browse X, etc."""
        open_keywords = ["open ", "go to ", "browse ", "visit ", "navigate to "]
        if any(kw in lowered for kw in open_keywords):
            # Avoid matching "open this file" or "open folder"
            if any(x in lowered for x in ["this file", "that file", "folder", "directory"]):
                 return None
            # Avoid matching common file extensions
            if any(ext in lowered for ext in [".py", ".js", ".ts", ".html", ".css", ".json", ".md", ".txt", ".glb", ".zip"]):
                 return None
            
            url_part = original
            for kw in open_keywords:
                if kw in lowered:
                    url_part = original[lowered.index(kw) + len(kw):].strip()
                    break
            shortcuts = {"google": "https://www.google.com", "youtube": "https://www.youtube.com", "github": "https://github.com", "twitter": "https://twitter.com", "facebook": "https://facebook.com", "reddit": "https://reddit.com", "stackoverflow": "https://stackoverflow.com", "docs": "https://docs.python.org"}
            url = shortcuts.get(url_part, url_part)
            if not url.startswith(("http://", "https://")):
                url = f"https://{url}" if "." in url else f"https://www.google.com/search?q={url}"
            try:
                import webbrowser
                webbrowser.open(url)
                result = f"Opened: {url}"
                ok(result)
                return result
            except Exception:
                return None
        return None
    
    def _quick_system_info(self, lowered: str, original: str) -> Optional[str]:
        """Handle system queries: disk space, memory, CPU, OS, etc."""
        sys_keywords = ["disk space", "memory", "cpu", "system info", "how much disk", "available space", "free memory"]
        if any(kw in lowered for kw in sys_keywords):
            try:
                import os
                try:
                    import psutil
                    use_psutil = True
                except ImportError:
                    use_psutil = False
                
                stats = []
                if use_psutil:
                    if "memory" in lowered or "all" in lowered:
                        mem = psutil.virtual_memory()
                        stats.append(f"Memory: {mem.percent}% used ({mem.available // (1024**3)}GB available)")
                    if "disk" in lowered or "space" in lowered or "all" in lowered:
                        disk = psutil.disk_usage("/" if os.name != "nt" else "C:\\")
                        stats.append(f"Disk: {disk.percent}% used ({disk.free // (1024**3)}GB free)")
                    if "cpu" in lowered or "all" in lowered:
                        cpu = psutil.cpu_percent(interval=0.1)
                        stats.append(f"CPU: {cpu}% used")
                else:
                    stats.append("psutil not installed. Run: pip install psutil")
                if not stats:
                    mem = psutil.virtual_memory()
                    disk = psutil.disk_usage("/" if os.name != "nt" else "C:\\")
                    stats.append(f"Memory: {mem.available // (1024**3)}GB available")
                    stats.append(f"Disk: {disk.free // (1024**3)}GB free")
                result = "\n".join(stats)
                panel("SYSTEM INFO", result)
                ok(result)
                return result
            except Exception:
                return None
        return None
    
    def _quick_unit_conversion(self, lowered: str, original: str) -> Optional[str]:
        """Handle unit conversions: km to miles, F to C, lbs to kg, etc."""
        if "convert" in lowered or "to " in lowered or any(u in lowered for u in ["km", "miles", "feet", "celsius", "fahrenheit", "lbs", "kg"]):
            try:
                import re
                match = re.search(r'(\d+\.?\d*)\s*([a-z]+)\s+(?:to|in|as)\s+([a-z]+)', lowered)
                if match:
                    value, from_unit, to_unit = float(match.group(1)), match.group(2), match.group(3)
                    conversions = {("km", "miles"): value * 0.621371, ("miles", "km"): value / 0.621371, ("m", "feet"): value * 3.28084, ("feet", "m"): value / 3.28084, ("kg", "lbs"): value * 2.20462, ("lbs", "kg"): value / 2.20462, ("c", "f"): (value * 9/5) + 32, ("celsius", "fahrenheit"): (value * 9/5) + 32, ("f", "c"): (value - 32) * 5/9, ("fahrenheit", "celsius"): (value - 32) * 5/9}
                    key = (from_unit, to_unit)
                    if key in conversions:
                        result = f"{value} {from_unit} = {conversions[key]:.2f} {to_unit}"
                        panel("UNIT CONVERSION", result)
                        ok(result)
                        return result
            except Exception:
                pass
        return None
    
    def _quick_text_ops(self, lowered: str, original: str) -> Optional[str]:
        """Handle text operations: uppercase, lowercase, reverse, count, base64, etc."""
        text_keywords = [("uppercase", lambda t: t.upper()), ("lowercase", lambda t: t.lower()), ("reverse", lambda t: t[::-1]), ("count words", lambda t: f"{len(t.split())} words"), ("count chars", lambda t: f"{len(t)} characters")]
        for keyword, operation in text_keywords:
            if keyword in lowered:
                parts = original.split(keyword, 1)
                if len(parts) > 1:
                    text = parts[1].strip()
                    result = str(operation(text))
                    panel("TEXT OP", result)
                    ok(result)
                    return result
        if "base64 encode" in lowered or "encode base64" in lowered:
            try:
                import base64
                parts = original.lower().split("encode", 1)
                if len(parts) > 1:
                    text = parts[1].strip().strip('"').strip("'")
                    encoded = base64.b64encode(text.encode()).decode()
                    ok(encoded)
                    return encoded
            except Exception:
                pass
        if "base64 decode" in lowered or "decode base64" in lowered:
            try:
                import base64
                parts = original.lower().split("decode", 1)
                if len(parts) > 1:
                    text = parts[1].strip().strip('"').strip("'")
                    decoded = base64.b64decode(text).decode()
                    ok(decoded)
                    return decoded
            except Exception:
                pass
        return None
    
    def _quick_find_files(self, lowered: str, original: str) -> Optional[str]:
        """Handle find file queries: find my file.txt, locate, search for filename, etc."""
        find_keywords = ["find", "locate", "where is", "search for file"]
        if any(kw in lowered for kw in find_keywords):
            filename = original
            for kw in find_keywords:
                if kw in lowered:
                    idx = lowered.index(kw) + len(kw)
                    filename = original[idx:].strip()
                    break
            try:
                from pathlib import Path
                import os
                search_root = Path.home()
                matches = []
                for root, dirs, files in os.walk(search_root):
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ["node_modules", "__pycache__"]]
                    for file in files:
                        if filename.lower() in file.lower():
                            matches.append(str(Path(root) / file))
                            if len(matches) >= 10:
                                break
                    if len(matches) >= 10:
                        break
                if matches:
                    result = "\n".join(matches[:5])
                    panel("FOUND FILES", result)
                    ok(result)
                    return result
            except Exception:
                pass
        return None
    
    def _quick_utilities(self, lowered: str, original: str) -> Optional[str]:
        """Handle quick utilities: UUID, random, dice, coin flip, hash, etc."""
        import re
        if "uuid" in lowered or "generate uuid" in lowered:
            import uuid
            result = str(uuid.uuid4())
            ok(result)
            return result
        if "open sandbox" in lowered or "what is sandbox" in lowered:
            result = (
                "The sandbox is the execution layer that isolates AI commands from your OS. "
                "It is CURRENTLY ACTIVE in 'LOCAL' mode (Host-Level Isolation). "
                "Every command run through the terminal is monitored and scored for risk."
            )
            panel("SANDBOX INFO", result)
            ok("Sandbox is already open and protecting your system.")
            return result
        if "random number" in lowered or "dice" in lowered or "roll" in lowered:
            import random
            try:
                match = re.search(r'(\d+)\s*(?:to|-|d)\s*(\d+)', lowered)
                if match:
                    low, high = int(match.group(1)), int(match.group(2))
                    result = str(random.randint(low, high))
                else:
                    result = str(random.randint(1, 6))
                ok(result)
                return result
            except Exception:
                pass
        if "coin" in lowered and "flip" in lowered:
            import random
            result = random.choice(["Heads", "Tails"])
            ok(result)
            return result
        if "choose" in lowered or "pick" in lowered:
            try:
                import random
                match = re.search(r'(?:between|from)\s+(.+)', lowered)
                if match:
                    options_str = match.group(1)
                    options = [o.strip() for o in re.split(r'(?:and|,)', options_str)]
                    options = [o.strip() for o in options if o.strip()]
                    if options:
                        result = random.choice(options)
                        ok(result)
                        return result
            except Exception:
                pass
        if "md5" in lowered or "sha256" in lowered or "hash" in lowered:
            try:
                import hashlib
                text = original
                for kw in ["md5", "sha256", "hash"]:
                    if kw in lowered:
                        text = original.split(kw, 1)[1].strip().strip('"').strip("'")
                        break
                if "sha256" in lowered:
                    result = hashlib.sha256(text.encode()).hexdigest()
                else:
                    result = hashlib.md5(text.encode()).hexdigest()
                ok(result)
                return result
            except Exception:
                pass
        return None

    def _toggle_watch(self) -> None:
        """Toggle file watcher (like aider /watch)."""
        from .watch import FileWatcher
        if self.watcher:
            self.watcher.stop()
            self.watcher = None
            ok("File watcher stopped.")
        else:
            def callback(path, goal):
                panel("WATCHER", f"File: {path.name}\nGoal: {goal}")
                self.run_agent(f"In file {path}, {goal}")
            
            self.watcher = FileWatcher(str(self.config.workspace), callback)
            self.watcher.start()
            ok("File watcher started. Add 'AI:' comments in your code to trigger edits.")

    def _classify_intent(self, goal: str) -> str:
        """Classify goal intent. AI-first (0.5B model, ~0.3s), regex fallback."""
        # ── AI classifier (fast, accurate) ──
        try:
            from .intent_classifier import get_classifier
            classifier = get_classifier(
                model=getattr(self.config, 'ollama_fast_model', 'qwen2.5:0.5b')
            )
            ai_intent = classifier.classify(goal)
            if ai_intent:
                return ai_intent
        except Exception:
            pass

        # ── Regex fallback (instant, no model needed) ──
        return self._classify_intent_regex(goal)

    def _classify_intent_regex(self, goal: str) -> str:
        """Fast local heuristic to categorize task complexity for dynamic routing."""
        lowered = goal.lower().strip()
        
        # Conversational memory questions (check FIRST — these reference previous conversation)
        convo_memory_patterns = [
            "my name", "what is my", "what's my", "who am i",
            "remember", "i told you", "i said", "you said",
            "do you know me", "what did i", "recall",
            "i am ", "i'm ", "call me",
            "how did you", "how do you know", "what can you do",
            "who are you", "what are you",
            # Session memory questions
            "what music", "what song", "what did we", "what have we",
            "what did you", "what were we", "what are we playing",
            "last song", "last track", "what was playing",
            "what did we do", "what have you done", "what just happened",
        ]
        if any(p in lowered for p in convo_memory_patterns):
            return "CONVO"

        # Simple Conversational greetings
        if lowered in {"hi", "hello", "hey", "how are you", "what's up", "help", "thanks", "thank you", "ok", "okay", "yes", "no", "what", "huh", "hmm", "sup", "yo", "bye", "goodbye"}:
            return "CONVO"

        # Tier 4: Complex Orchestration (check first to avoid misclassification)
        if any(keyword in lowered for keyword in ["refactor", "build a full", "architect", "from scratch"]):
            if len(lowered.split()) > 4:
                return "COMPLEX"
        
        # Multi-step framework tasks: setup + customize = COMPLEX
        framework_keywords = ["laravel", "react", "vue", "angular", "django", "next", "flutter", "expo", "nestjs"]
        multi_step_signals = [" then ", " and then ", " after that ", " with ", " also ", " plus "]
        coding_signals = ["make the ui", "make it look", "copy the", "clone the", "style it", "design", "customize", "modify the"]
        if any(fw in lowered for fw in framework_keywords):
            if any(sig in lowered for sig in multi_step_signals + coding_signals):
                return "COMPLEX"
        
        # Generic multi-step tasks (even without framework keywords)
        # "create X then Y", "build X and make it Y", "setup X with Y"
        if any(sig in lowered for sig in [" then ", " and then ", " after that "]):
            if any(kw in lowered for kw in ["create", "build", "make", "setup", "install", "write", "add"]):
                if len(lowered.split()) > 6:
                    return "COMPLEX"

        # Navigation commands → TASK (agent will use navigate tool)
        nav_phrases = ["take me to ", "go to ", "navigate to ", "switch to ", "move to ", "bring me to "]
        if any(p in lowered for p in nav_phrases):
            # Only if it mentions a folder/directory/known location, not a URL
            if any(w in lowered for w in ["folder", "directory", "dir", "downloads", "desktop", "documents", "home", "pictures", "music", "videos"]) or not any(c in lowered for c in [".", "http", "www"]):
                return "TASK"

        # Filesystem listing commands → TASK
        if lowered in ("list", "ls", "dir", "list files", "show files", "list here", "ls here"):
            return "TASK"
        if any(p in lowered for p in ["list file", "list inside", "files in", "show file", "what's in", "what is in"]):
            return "TASK"

        # Simple file/folder creation → TASK
        if any(p in lowered for p in ["create a ", "create an", "create another", "create file", "create story",
                                       "make a file", "make a folder", "make another", "make a story",
                                       "create folder", "new file", "touch ", "write a "]):
            return "TASK"

        # 3. Tier 1: Query / Knowledge Search (check before broad CONVO catch-all)
        if lowered.startswith(("how ", "what ", "where ", "explain", "why ", "find ")):
            if not any(k in lowered for k in ["fix", "change", "edit", "add", "remove", "update"]):
                return "QUERY"

        # Setup / build guidance should use the fast helper model and web search first.
        if any(keyword in lowered for keyword in ["setup", "set up", "install", "create project", "create app", "build app", "starter", "scaffold", "initialize", "init"]):
            if not any(ext in lowered for ext in [".py", ".js", ".ts", ".html", ".css", "/", "\\"]):
                return "QUERY"
                
        # 4. Tier 2: Targeted Edit (check before broad CONVO catch-all)
        if any(keyword in lowered for keyword in ["fix", "edit", "change", "add ", "remove ", "update "]):
            # If they mention a file extension or path, it's highly targeted
            if any(ext in lowered for ext in [".py", ".js", ".ts", ".html", ".css", "/", "\\"]):
                return "EDIT"
            return "EDIT"

        # Simple short conversational (catch-all for short non-technical messages)
        if len(lowered) < 25 and not any(c in lowered for c in ["/", "\\", "."]) and not any(k in lowered for k in ["file", "files", "list", "ls", "dir", "fix", "code", "run", "make", "create", "bug", "error", "how", "what", "where", "why", "when"]):
            return "CONVO"
                
        # 5. Tier 3: Default Explore
        return "EXPLORE"

    def _is_continuation_command(self, goal: str) -> bool:
        """Detect phrases like 'do it', 'do that', 'go ahead' that refer to previous goal."""
        lowered = goal.lower().strip()
        continuation_phrases = [
            "do it", "do that", "go ahead", "proceed", "execute", "make it happen",
            "run it", "start it", "begin", "go on", "continue", "next step",
            "now do it", "please do", "execute it"
        ]
        # Must be a short command (<=5 words) AND match a continuation phrase
        # Exclude questions (starting with what/how/why/who/where/when)
        if lowered.startswith(("what", "how", "why", "who", "where", "when", "can")):
            return False
        return any(phrase in lowered for phrase in continuation_phrases) and len(lowered.split()) <= 5

    def _enrich_task_goal(self, goal: str) -> str:
        """Enrich a TASK goal with the correct command for small models.
        
        Small models (3B) can't reliably infer the correct install command from
        just the framework name. This injects the exact command into the goal
        so the model uses it directly. Also runs pre-flight dependency checks.
        
        For COMPLEX multi-step tasks (e.g. "setup laravel with breeze then make UI like facebook"),
        provides a full step-by-step execution plan.
        """
        lowered = goal.lower()
        
        # Detect if this is a multi-step task (framework setup + coding)
        multi_step_signals = [" then ", " and then ", " after that ", " also ", " plus "]
        coding_signals = ["make the ui", "make it look", "copy the", "clone the", "style it", 
                         "design", "customize", "modify the", "look like", "similar to"]
        is_multi_step = any(sig in lowered for sig in multi_step_signals + coding_signals)
        
        # Pre-flight: detect framework and ensure deps are installed BEFORE agent starts
        try:
            from .dep_installer import (
                ensure_deps_for_framework, is_installed, FRAMEWORK_DEPS,
                detect_framework_from_goal, get_framework_create_command,
                create_project_with_deps,
            )
            
            # Use smart framework detection
            detected = detect_framework_from_goal(goal)
            if detected:
                # Get the base framework for dependency resolution
                base_framework = detected.split("-")[0] if "-" in detected else detected
                dep_key = base_framework
                if dep_key == "nextjs":
                    dep_key = "next"
                if dep_key in FRAMEWORK_DEPS or base_framework in FRAMEWORK_DEPS:
                    from ..ui import ok, warn
                    warn(f"Checking dependencies for {detected}...")
                    success, msg = ensure_deps_for_framework(dep_key if dep_key in FRAMEWORK_DEPS else base_framework)
                    if success:
                        ok(f"All dependencies ready for {detected}")
                    else:
                        ok(f"Note: {msg}")
                
                # For multi-step tasks, provide a comprehensive execution plan
                if is_multi_step:
                    return self._build_complex_task_plan(goal, detected)
                
                # Get the exact creation command for simple tasks
                create_info = get_framework_create_command(detected, "my-app")
                if create_info:
                    cmd = create_info["cmd"]
                    
                    # Extract target path if present
                    path_match = re.search(r'(?:in|at|into)\s+([A-Za-z]:[\\/][^\s]+|[\\/][^\s]+|~/[^\s]+)', goal, re.IGNORECASE)
                    if path_match:
                        target_dir = path_match.group(1)
                    elif "download" in lowered:
                        target_dir = str(Path.home() / "Downloads")
                    elif "desktop" in lowered:
                        target_dir = str(Path.home() / "Desktop")
                    elif self.last_target:
                        target_dir = str(self.last_target)
                    else:
                        target_dir = None
                    
                    # Extract custom project name if specified
                    name_match = re.search(r'(?:called|named)\s+["\']?([\w\-]+)["\']?', goal, re.IGNORECASE)
                    if name_match:
                        custom_name = name_match.group(1)
                        cmd = cmd.replace("my-app", custom_name)
                    
                    enriched = f"{goal}\n\nEXECUTE: {cmd}"
                    if create_info.get("post_cmds"):
                        enriched += f"\nTHEN RUN (in project dir): {' && '.join(create_info['post_cmds'][:2])}"
                    if target_dir:
                        enriched += f"\nCWD: {target_dir}"
                    return enriched
        except Exception:
            pass
        
        # For multi-step tasks without a detected framework, still provide structure
        if is_multi_step:
            return self._build_complex_task_plan(goal, None)
        
        # For single-step tasks that mention a framework but aren't creation commands
        # (e.g. "install tailwind in my project", "add authentication")
        # Just pass through — the agent can handle these with its normal flow
        
        return goal

    def _build_complex_task_plan(self, goal: str, detected_framework: str | None) -> str:
        """Build a detailed step-by-step execution plan for complex multi-step tasks.
        
        This gives the agent a clear roadmap so it doesn't waste steps figuring out what to do.
        Works for:
        - Framework creation + customization
        - Multi-file coding tasks
        - Setup + configuration tasks
        - Any "do X then do Y" pattern
        """
        lowered = goal.lower()
        target_dir = self.last_target or Path(self.config.workspace)
        
        plan_parts = [goal, "\n\n### EXECUTION PLAN (follow these steps in order):"]
        step_num = 1
        
        # Step 1: Project creation (if framework detected)
        if detected_framework:
            from .dep_installer import get_framework_create_command
            create_info = get_framework_create_command(detected_framework, "my-app")
            if create_info:
                plan_parts.append(f"\nSTEP {step_num}: Create the project")
                plan_parts.append(f"  RUN: {create_info['cmd']}")
                plan_parts.append(f"  CWD: {target_dir}")
                step_num += 1
                
                # Post-install steps
                if create_info.get("post_cmds"):
                    for pc in create_info["post_cmds"]:
                        plan_parts.append(f"\nSTEP {step_num}: {pc}")
                        plan_parts.append(f"  RUN: {pc}")
                        plan_parts.append(f"  CWD: {target_dir}/my-app")
                        step_num += 1
        
        # Detect additional extensions/packages mentioned
        if "breeze" in lowered and detected_framework and "laravel" in detected_framework:
            if "breeze" not in (detected_framework or ""):
                plan_parts.append(f"\nSTEP {step_num}: Install Laravel Breeze")
                plan_parts.append(f"  RUN: composer require laravel/breeze --dev")
                plan_parts.append(f"  CWD: {target_dir}/my-app")
                step_num += 1
                plan_parts.append(f"\nSTEP {step_num}: Run Breeze installer")
                plan_parts.append(f"  RUN: php artisan breeze:install blade --no-interaction")
                plan_parts.append(f"  CWD: {target_dir}/my-app")
                step_num += 1
                plan_parts.append(f"\nSTEP {step_num}: Install npm dependencies")
                plan_parts.append(f"  RUN: npm install")
                plan_parts.append(f"  CWD: {target_dir}/my-app")
                step_num += 1
                plan_parts.append(f"\nSTEP {step_num}: Build frontend assets")
                plan_parts.append(f"  RUN: npm run build")
                plan_parts.append(f"  CWD: {target_dir}/my-app")
                step_num += 1
        elif "breeze" in lowered and detected_framework and "breeze" in detected_framework:
            # Already handled by the create_info post_cmds above
            pass
        
        # Detect additional packages/extensions to install
        extra_packages = {
            "tailwind": ("npm install -D tailwindcss postcss autoprefixer", "npx tailwindcss init -p"),
            "sanctum": ("composer require laravel/sanctum", "php artisan vendor:publish --provider=\"Laravel\\Sanctum\\SanctumServiceProvider\""),
            "passport": ("composer require laravel/passport", "php artisan migrate"),
            "inertia": ("composer require inertiajs/inertia-laravel", None),
            "livewire": ("composer require livewire/livewire", None),
            "typescript": ("npm install -D typescript @types/node", "npx tsc --init"),
            "eslint": ("npm install -D eslint", "npx eslint --init"),
            "prettier": ("npm install -D prettier", None),
            "jest": ("npm install -D jest", None),
            "vitest": ("npm install -D vitest", None),
        }
        for pkg_name, (install_cmd, post_cmd) in extra_packages.items():
            if pkg_name in lowered and pkg_name not in (detected_framework or ""):
                plan_parts.append(f"\nSTEP {step_num}: Install {pkg_name}")
                plan_parts.append(f"  RUN: {install_cmd}")
                step_num += 1
                if post_cmd:
                    plan_parts.append(f"\nSTEP {step_num}: Configure {pkg_name}")
                    plan_parts.append(f"  RUN: {post_cmd}")
                    step_num += 1
        
        # Detect UI/styling tasks
        ui_targets = {
            "facebook": "Facebook-style UI with blue header (#1877F2), white cards, rounded avatars, news feed layout, like/comment/share buttons, sticky header, create-post box",
            "twitter": "Twitter/X-style UI with dark/light theme, tweet cards, sidebar navigation, trending section, compose tweet button, blue accents (#1DA1F2)",
            "instagram": "Instagram-style UI with grid photo layout, stories bar at top, bottom navigation, heart icons, gradient logo colors, explore grid",
            "youtube": "YouTube-style UI with video grid thumbnails, sidebar navigation, red accents (#FF0000), search bar, channel avatars, view counts",
            "spotify": "Spotify-style UI with dark theme (#191414), green accents (#1DB954), card-based layout, sidebar playlists, now-playing bar at bottom",
            "github": "GitHub-style UI with repository cards, contribution graph, tab navigation, green commit indicators, code blocks, issue lists",
            "whatsapp": "WhatsApp-style UI with green header (#25D366), chat list with avatars, message bubbles (green sent, white received), timestamp, double-check marks",
            "netflix": "Netflix-style UI with dark background, red accents (#E50914), horizontal scroll carousels, large hero banner, category rows",
            "slack": "Slack-style UI with sidebar channels, message thread, workspace switcher, emoji reactions, file attachments, purple accents (#4A154B)",
            "discord": "Discord-style UI with dark theme (#36393F), server list sidebar, channel list, message area, user list, blurple accents (#5865F2)",
            "linkedin": "LinkedIn-style UI with blue header (#0A66C2), profile cards, feed posts, connection suggestions, job listings",
            "tiktok": "TikTok-style UI with full-screen video cards, bottom navigation, like/comment/share on right side, music ticker at bottom",
        }
        
        for platform, description in ui_targets.items():
            if platform in lowered:
                plan_parts.append(f"\nSTEP {step_num}: Customize the UI to look like {platform.title()}")
                plan_parts.append(f"  DESIGN: {description}")
                plan_parts.append(f"  ACTION: Use write_files to create/edit the main view/template files")
                plan_parts.append(f"  IMPORTANT: Write COMPLETE file content, not partial. Include all HTML, CSS, and structure.")
                if detected_framework and "laravel" in (detected_framework or ""):
                    plan_parts.append(f"  TARGET FILES: resources/views/welcome.blade.php, resources/views/dashboard.blade.php")
                    plan_parts.append(f"  CSS: Use Tailwind CSS classes (included with Breeze) or inline <style> blocks")
                elif detected_framework and any(fw in (detected_framework or "") for fw in ["react", "next", "vue"]):
                    plan_parts.append(f"  TARGET FILES: src/App.jsx or app/page.js (depends on framework)")
                    plan_parts.append(f"  CSS: Use inline styles or create a CSS module")
                step_num += 1
                break
        else:
            # Generic coding/customization task (no specific platform detected)
            # Split on "then" to find the second part of the task
            then_parts = lowered.split(" then ")
            if len(then_parts) > 1:
                second_task = then_parts[1].strip()
                plan_parts.append(f"\nSTEP {step_num}: {second_task.capitalize()}")
                plan_parts.append(f"  ACTION: Use write_files or edit_blocks to implement this")
                plan_parts.append(f"  IMPORTANT: Write COMPLETE file content. Read existing files first if editing.")
                step_num += 1
            elif any(sig in lowered for sig in ["make the ui", "make it look", "style it", "design", "customize"]):
                plan_parts.append(f"\nSTEP {step_num}: Customize the UI as requested")
                plan_parts.append(f"  ACTION: Use write_files to create/edit view/template files")
                step_num += 1
        
        plan_parts.append(f"\nSTEP {step_num}: Use 'answer' tool to report completion")
        plan_parts.append("\n\n### RULES:")
        plan_parts.append("- Execute ONE command per step using run_cmd")
        plan_parts.append("- Use write_files to create/edit templates, components, CSS, etc.")
        plan_parts.append("- Do NOT explain what you will do. Just DO IT.")
        plan_parts.append("- The CWD auto-updates after project creation. Use run_cmd with cwd param if needed.")
        plan_parts.append("- When writing UI files, write the COMPLETE file (not just a snippet)")
        plan_parts.append("- If a command fails, try an alternative approach (don't repeat the same command)")
        
        return "\n".join(plan_parts)

    def run_agent(self, goal: str) -> None:
        """Run the agent, orchestrator, or fast-convo based on goal."""
        # Check for continuation commands BEFORE vague detection
        is_continuation = self._is_continuation_command(goal) and self.last_goal
        
        # Continuation logic: if goal is 'go', use last goal
        if goal.lower().strip() in ("go", "continue", "next") and self.last_goal:
            goal = self.last_goal
        elif is_continuation:
            # For 'do it' style commands, append execution intent to previous goal
            goal = f"{self.last_goal} - now actually execute this and create the files"
            # Force coding model by using primary config
            force_coding = True
        else:
            self.last_goal = goal
            # Reset observations but preserve CWD if user navigated
            if self.last_target:
                self.observations = [f"CWD: {self.last_target}"]
            else:
                self.observations = []
            # Pre-inject directory listing so agent doesn't waste a step on list_dir
            target_dir = self.last_target or Path(self.config.workspace)
            try:
                items = [f"{f.name}/" if f.is_dir() else f.name for f in sorted(target_dir.iterdir()) if not f.name.startswith(".")]
                if items:
                    self.observations.append(f"FILES in {target_dir}: {' '.join(items[:20])}")
            except Exception:
                pass
            force_coding = False

        self.chat_history.append("USER", goal)
        
        # ── Direct Command Shortcuts (instant, no AI needed) ──
        # Handle cd, ls/dir, and other obvious shell commands directly
        lowered_goal = goal.lower().strip()
        if lowered_goal.startswith("cd ") or lowered_goal.startswith("cd\\") or lowered_goal.startswith("cd/"):
            # Direct cd — no AI needed
            target = goal[2:].strip().strip('"').strip("'")
            # Handle natural language: "cd to downloads", "cd to desktop"
            if target.lower().startswith("to "):
                target = target[3:].strip()
            # Handle symbolic names
            symbolic_map = {
                "downloads": str(Path.home() / "Downloads"),
                "download": str(Path.home() / "Downloads"),
                "desktop": str(Path.home() / "Desktop"),
                "documents": str(Path.home() / "Documents"),
                "home": str(Path.home()),
                "~": str(Path.home()),
            }
            resolved_target = symbolic_map.get(target.lower(), target)
            if resolved_target:
                target_path = Path(resolved_target).expanduser().resolve()
                if target_path.exists() and target_path.is_dir():
                    self.last_target = target_path
                    self.observations = [f"CWD: {target_path}"]
                    ok(f"→ {target_path}")
                    self.memory.add_event(f"Navigated to: {target_path}")
                    return
                else:
                    err(f"Directory not found: {resolved_target}")
                    return

        # ── Direct ls/list/dir handler (instant, no AI needed) ──
        if lowered_goal in ("list", "ls", "dir", "list files", "show files", "ls here", "list here",
                            "show me the files", "list this directory", "what files are here") or \
           any(p in lowered_goal for p in ["list inside this", "files in this", "what's in this",
                                            "files here", "list this", "what files", "show files",
                                            "show me files", "what's in this"]):
            target_dir = self.last_target or Path(self.config.workspace)
            if target_dir.exists() and target_dir.is_dir():
                items = []
                for f in sorted(target_dir.iterdir()):
                    items.append(f"{f.name}/" if f.is_dir() else f.name)
                output = f"Found {len(items)} file(s) in {target_dir.name}. Details: {' '.join(items[:30])}"
                if len(items) > 30:
                    output += f" ... and {len(items) - 30} more"
                flow("direct → list_dir")
                from ..ui import panel
                panel("FILESYSTEM", output)
                self.chat_history.append("ASSISTANT", output)
                self.memory.add_event(f"Listed: {target_dir}")
                return

        # ── Direct folder creation handler (instant, no AI needed) ──
        # Patterns: "create folder X", "make a directory X", "create the X folder", "mkdir X"
        import re as _re_mkdir
        mkdir_match = _re_mkdir.search(
            r'\b(?:create|make|new)\s+(?:a\s+|the\s+)?(?:folder|directory|dir)\s+(?:called\s+|named\s+)?["\']?([\w\-\.]+)["\']?',
            lowered_goal
        )
        if not mkdir_match:
            mkdir_match = _re_mkdir.search(
                r'\b(?:create|make|new)\s+(?:the\s+)?["\']?([\w\-\.]+)["\']?\s+(?:folder|directory|dir)\b',
                lowered_goal
            )
        if not mkdir_match and lowered_goal.startswith("mkdir "):
            name = lowered_goal[6:].strip().strip('"').strip("'")
            if name:
                mkdir_match = type('M', (), {'group': lambda self, n: name})()
        if mkdir_match:
            dir_name = mkdir_match.group(1).strip()
            if dir_name and len(dir_name) < 100:
                target_dir = self.last_target or Path(self.config.workspace)
                new_dir = target_dir / dir_name
                try:
                    new_dir.mkdir(parents=True, exist_ok=True)
                    flow("direct → mkdir")
                    ok(f"Created folder: {new_dir}")
                    self.chat_history.append("ASSISTANT", f"Created folder {dir_name}")
                    self.memory.add_event(f"Created folder: {new_dir}")
                    return
                except Exception as e:
                    err(f"Failed to create folder: {e}")
                    return

        intent = self._classify_intent(goal)
        # Continuation commands should use coding model regardless of classification
        if is_continuation:
            intent = "EXPLORE"
        flow(f"classified: {intent}")

        # ── Fast Navigation Route (use small model to extract target) ──
        if intent == "TASK" or (intent in ("CONVO", "EXPLORE") and any(w in lowered_goal for w in ["folder", "directory"]) and any(w in lowered_goal for w in ["open", "go", "enter", "into"])):
            nav_phrases = ["take me to ", "go to ", "navigate to ", "switch to ", "move to ", "bring me to ", "open "]
            is_nav = any(p in lowered_goal for p in nav_phrases) and any(w in lowered_goal for w in ["folder", "directory", "dir", "downloads", "desktop", "documents", "home", "pictures", "music", "videos"])
            # Also catch "open X folder" or "open the folder named X"
            if not is_nav and "open" in lowered_goal and ("folder" in lowered_goal or "directory" in lowered_goal):
                is_nav = True
            if is_nav:
                # Use the fast model to extract the folder name
                from .backend import ollama_generate
                fast_model = getattr(self.config, 'ollama_fast_model', 'qwen2.5:0.5b')
                flow(f"intent={intent} → nav extract via {fast_model}")
                extract_prompt = (
                    f"Extract ONLY the folder/directory name from this request. "
                    f"Output just the folder name as-is (e.g. downloads, my-laravel-app, code). No explanation.\n"
                    f"Request: {goal}\nFolder:"
                )
                extracted = ollama_generate(
                    fast_model, extract_prompt,
                    system_text="Extract the folder name. Output only the name, nothing else.",
                    max_tokens=15, temperature=0
                )
                if extracted:
                    extracted = extracted.strip().strip('"').strip("'").lower()
                    # Remove noise
                    for noise in ["folder", "directory", "dir", "the", "my", "pc"]:
                        extracted = extracted.replace(noise, "").strip()
                    
                    symbolic_map = {
                        "downloads": str(Path.home() / "Downloads"),
                        "download": str(Path.home() / "Downloads"),
                        "desktop": str(Path.home() / "Desktop"),
                        "documents": str(Path.home() / "Documents"),
                        "document": str(Path.home() / "Documents"),
                        "home": str(Path.home()),
                        "~": str(Path.home()),
                        "pictures": str(Path.home() / "Pictures"),
                        "music": str(Path.home() / "Music"),
                        "videos": str(Path.home() / "Videos"),
                    }
                    # Try exact match in symbolic_map first (handle common abbreviations)
                    resolved = symbolic_map.get(extracted)
                    # Also try to find symbolic names that appear IN the original goal text
                    # (in case the 0.5B extracted wrong but the goal clearly mentions desktop/downloads/etc)
                    if resolved is None:
                        for key in ("downloads", "download", "desktop", "documents", "document",
                                    "home", "pictures", "music", "videos"):
                            if key in lowered_goal:
                                resolved = symbolic_map.get(key)
                                break
                    if resolved is None:
                        # Try relative to current navigated directory first
                        if self.last_target:
                            # Exact match
                            candidate = self.last_target / extracted
                            if candidate.exists() and candidate.is_dir():
                                resolved = str(candidate)
                            else:
                                # Fuzzy match: find subdirectory containing the extracted name
                                # Only if extracted is long enough to not be ambiguous (>= 3 chars)
                                if len(extracted) >= 3:
                                    for sub in self.last_target.iterdir():
                                        if sub.is_dir() and extracted in sub.name.lower():
                                            resolved = str(sub)
                                            break
                    if resolved is None:
                        # Try as absolute/literal path
                        candidate = Path(extracted).expanduser().resolve()
                        if candidate.exists() and candidate.is_dir():
                            resolved = str(candidate)
                    if resolved:
                        target_path = Path(resolved).resolve()
                        if target_path.exists() and target_path.is_dir():
                            self.last_target = target_path
                            self.observations = [f"CWD: {target_path}"]
                            ok(f"→ {target_path}")
                            self.memory.add_event(f"Navigated to: {target_path}")
                            return
                    # Nav was requested but no match — return gracefully, don't fall through to slow agent
                    err(f"Could not find directory: {extracted!r}")
                    return

        # ── Fast Project Creation Route (no agent needed) ──
        is_create_cmd = any(w in lowered_goal for w in ["create ", "make ", "new file", "touch ", "write a ", "init ", "initialize "])
        # Use word-boundary regex to avoid matching "app" in "app.js"
        import re as _re_proj
        is_project_word = bool(_re_proj.search(r'\b(?:project|laravel|react\s+native|nextjs|next\.js|angular|django|express|nestjs|flutter|expo|svelte|astro|nuxt|vite|remix|tauri|electron|blazor|rails|spring)\b', lowered_goal))
        # "application" and "react app" need special handling
        is_application_phrase = bool(_re_proj.search(r'\bapplication\b|\breact\s+app\b|\bvue\s+app\b|\bnext\s+app\b|\bflask\s+app\b|\bweb\s+app\b|\bmobile\s+app\b|\bfastapi\s+app\b', lowered_goal))
        # Must NOT have a file extension pattern (e.g. "app.js", "index.html")
        has_file_ext = bool(_re_proj.search(r'\b\w+\.[a-z]{1,5}\b', lowered_goal))
        # Must NOT be a multi-step task (those go to COMPLEX agent with full plan)
        multi_step_signals = [" then ", " and then ", " after that ", " also ", " plus ",
                              "make the ui", "make it look", "look like", "copy the", "style it"]
        is_multi_step = any(sig in lowered_goal for sig in multi_step_signals)
        is_project = (is_project_word or is_application_phrase) and not has_file_ext and not is_multi_step
        if is_create_cmd and is_project:
            # Use the unified dep_installer framework detection + creation
            from .dep_installer import detect_framework_from_goal, create_project_with_deps
            detected_fw = detect_framework_from_goal(goal)
            if detected_fw:
                flow(f"intent={intent} → fast project create via dep_installer ({detected_fw})")
                target_dir = self.last_target or Path(self.config.workspace)
                
                # Extract custom project name if specified
                name_match = _re_proj.search(r'(?:called|named)\s+["\']?([\w\-]+)["\']?', goal, re.IGNORECASE)
                proj_name = name_match.group(1) if name_match else "my-app"
                
                success, output = create_project_with_deps(detected_fw, proj_name, str(target_dir))
                if success:
                    ai(output[-500:] if len(output) > 500 else output)
                else:
                    err(output[:500])
                self.chat_history.append("ASSISTANT", output[:300])
                return
            else:
                # Fallback: use 0.5B model to extract the command
                from .backend import ollama_generate
                fast_model = getattr(self.config, 'ollama_fast_model', 'qwen2.5:0.5b')
                flow(f"intent={intent} → fast project create via {fast_model}")
                extract_prompt = (
                    f"Output the FIRST shell command to create this project. ONE command only. No chaining with &&.\n"
                    f"IMPORTANT: Only the first step. No extra packages. No explanation.\n\n"
                    f"create a react app→npx create-react-app my-app\n"
                    f"create a react native project→npx react-native@latest init MyApp\n"
                    f"create a next.js app→npx create-next-app@latest my-app\n"
                    f"create a laravel project→composer create-project laravel/laravel my-app\n"
                    f"create laravel with breeze→composer create-project laravel/laravel my-app\n"
                    f"create a vue app→npm create vue@latest my-app\n"
                    f"create an angular app→npx @angular/cli new my-app\n"
                    f"create a flask app→pip install flask\n"
                    f"create a django project→django-admin startproject myproject\n"
                    f"create an express app→npm init -y\n"
                    f"create a vite react app→npm create vite@latest my-app -- --template react\n"
                    f"create a flutter app→flutter create my_app\n"
                    f"create a nestjs app→npx @nestjs/cli new my-app\n"
                    f"create a rust project→cargo new my-app\n"
                    f"create a go project→go mod init my-app\n"
                    f"{goal}→"
                )
                cmd = ollama_generate(
                    fast_model, extract_prompt,
                    system_text="Output ONE shell command. No && chaining. No explanation.",
                    max_tokens=30, temperature=0
                )
                if cmd and cmd.strip() and not cmd.strip().startswith(("#", "/", "I ")):
                    cmd = cmd.strip().split("\n")[0].split("&&")[0].strip()  # Force single command
                    target_dir = self.last_target or Path(self.config.workspace)
                    
                    # Pre-install dependencies for the detected command
                    from .dep_installer import ensure_deps_for_command
                    dep_ok, dep_msg = ensure_deps_for_command(cmd)
                    if not dep_ok:
                        err(dep_msg)
                        return
                    
                    flow(f"  → running: {cmd}")
                    import subprocess
                    try:
                        result = subprocess.run(
                            cmd, shell=True, cwd=str(target_dir),
                            capture_output=True, text=True, timeout=300
                        )
                        output = result.stdout[-500:] or result.stderr[-500:] or "Done"
                        if result.returncode == 0:
                            ok(f"✓ {cmd}")
                            ai(output[:200] if output != "Done" else f"Project created successfully.")
                        else:
                            err(f"Command failed: {output[:200]}")
                        self.chat_history.append("ASSISTANT", output[:300])
                        return
                    except subprocess.TimeoutExpired:
                        err("Command timed out (300s)")
                        return
                    except Exception as e:
                        err(f"Failed: {e}")
                        return

        # ── Fast File Creation Route (use small model to extract filename + content) ──
        is_file_target = any(w in lowered_goal for w in ["file", "story", "poem", "script", "letter", ".txt", ".py", ".js", ".html", ".css", ".json", ".md"])
        # Skip create route if this is clearly an edit command (contains edit phrases)
        edit_signal_phrases = ["make it longer", "make it shorter", "make it", "add more", "extend",
                               "longer", "shorter", "rewrite", "improve it", "update it", "modify",
                               "more detail", "expand it", "elaborate", "edit the", "edit this"]
        is_edit_signal = any(p in lowered_goal for p in edit_signal_phrases)
        if is_create_cmd and is_file_target and not is_edit_signal:
                from .backend import ollama_generate
                import re as _re
                fast_model = getattr(self.config, 'ollama_fast_model', 'qwen2.5:0.5b')
                flow(f"intent={intent} → fast file create via {fast_model}")

                # Try to extract filename from the goal itself first (fastest path)
                filename = None
                # Pattern 1: explicit filename like "test.py" or "index.html"
                m = _re.search(r'\b([\w\-]+\.[a-zA-Z0-9]{1,5})\b', goal)
                if m:
                    filename = m.group(1)
                # Pattern 2: "named X" or "called X"
                if not filename:
                    m = _re.search(r'(?:named|called)\s+["\']?([\w\-\.]+)["\']?', lowered_goal)
                    if m:
                        filename = m.group(1)
                        if "." not in filename:
                            filename += ".txt"

                # Fallback: infer from content type words
                if not filename:
                    ext_map = {
                        "python": ".py", "py file": ".py", "py ": ".py",
                        "javascript": ".js", "js file": ".js", "js ": ".js",
                        "html": ".html", "css": ".css", "json": ".json",
                        "markdown": ".md", "md file": ".md",
                    }
                    ext = ".txt"
                    for kw, e in ext_map.items():
                        if kw in lowered_goal:
                            ext = e
                            break
                    # Name based on content type
                    name_map = {
                        "story": "story", "poem": "poem", "letter": "letter",
                        "essay": "essay", "article": "article", "script": "script",
                        "note": "note", "readme": "README",
                    }
                    base = "file"
                    for kw, n in name_map.items():
                        if kw in lowered_goal:
                            base = n
                            break
                    filename = f"{base}{ext}" if not base.endswith(ext) else base

                # Sanitize filename
                filename = filename.replace("\\", "/").split("/")[-1]
                filename = _re.sub(r'[<>:"|?*]', '', filename)  # Remove Windows-invalid chars

                # Determine content: try to extract literal content after "with"/"containing"
                content = ""
                m = _re.search(r'\b(?:with|containing|saying|that says)\s+(.+?)(?:\s+inside|\s+in it|\s*$)', lowered_goal)
                if m:
                    literal = m.group(1).strip().strip('"').strip("'")
                    # Strip leading articles
                    literal = _re.sub(r'^(a |an |the )', '', literal).strip()
                    # Only use as literal if it's simple (≤6 words, no content-type words)
                    if literal and len(literal.split()) <= 6 and not any(w in literal for w in ["story", "poem", "essay", "article", "script", "letter"]):
                        content = literal
                        # Smart filename inference: use first word of content if no filename set
                        if filename in ("file.txt", "file.py", "file.md"):
                            first_word = literal.split()[0].lower()
                            first_word = _re.sub(r'[^a-z0-9]', '', first_word)
                            if first_word:
                                ext = filename.split(".")[-1]
                                filename = f"{first_word}.{ext}"

                # If content needs generation (story, poem, code, etc.), use main model
                # But NOT if the word is just part of a filename (e.g. "script.js")
                _re_ng = _re
                needs_generation = any(
                    _re_ng.search(rf'\b{w}\b(?!\.[a-z]{{1,5}})', lowered_goal)
                    for w in ["story", "poem", "essay", "letter", "article", "function", "class", "program"]
                )
                # "script" and "code" only count if referring to writing, not a filename
                if not needs_generation:
                    if _re_ng.search(r'\b(?:write|create)\s+(?:a\s+)?(?:python\s+|js\s+|javascript\s+)?(?:script|function|code|program)\b', lowered_goal):
                        needs_generation = True

                if needs_generation:
                    # For creative content, use fast model (3-5x faster, quality is fine for short pieces)
                    # For code, use main model (needs better structure understanding)
                    is_code = any(w in lowered_goal for w in ["code", "script", "function", "class", "program"])
                    if is_code:
                        gen_model = getattr(self.config, 'ollama_model', 'phi4-mini:latest')
                    else:
                        gen_model = getattr(self.config, 'ollama_fast_model', 'qwen2.5:0.5b')
                    flow(f"  → generating content via {gen_model}")
                    # Stronger prompt for creative content
                    content_type = "content"
                    for kw in ["story", "poem", "essay", "article", "letter"]:
                        if kw in lowered_goal:
                            content_type = kw
                            break
                    gen_prompt = (
                        f"Write a complete, engaging {content_type} based on this request:\n"
                        f"{goal}\n\n"
                        f"Requirements:\n"
                        f"- Actually write the {content_type}, don't describe what it would be\n"
                        f"- Be creative and specific\n"
                        f"- Output ONLY the {content_type} text, no preamble, no markdown fences"
                    )
                    gen_tokens = 300
                    if "long" in lowered_goal or "detailed" in lowered_goal or "500" in lowered_goal:
                        gen_tokens = 500
                    elif "short" in lowered_goal or "brief" in lowered_goal:
                        gen_tokens = 200
                    generated = ollama_generate(
                        gen_model, gen_prompt,
                        system_text=f"You are a creative writer. Write actual {content_type} content. No meta-commentary.",
                        max_tokens=gen_tokens, temperature=0.8
                    )
                    if generated and generated.strip():
                        content = generated.strip()
                        # Strip markdown code fences if the model added them
                        if content.startswith("```"):
                            lines = content.split("\n")
                            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

                target_dir = self.last_target or Path(self.config.workspace)
                filepath = target_dir / filename
                try:
                    filepath.write_text(content, encoding="utf-8")
                    ok(f"Created: {filepath}")
                    self.last_file = filepath
                    self.chat_history.append("ASSISTANT", f"Created {filename}")
                    self.memory.add_event(f"Created file: {filepath}")
                    return
                except Exception as e:
                    err(f"Failed to create file: {e}")
                    return

        # ── Fast Content Edit Route (continuation: "make it longer", "add more", etc.) ──
        # Also detect file references: "edit the story file", "make the text file longer"
        edit_phrases = ["make it", "add more", "make this", "extend", "longer", "shorter",
                       "rewrite", "improve", "change it", "update it", "modify",
                       "more detail", "expand", "elaborate", "edit the", "edit this",
                       "make the"]
        if any(p in lowered_goal for p in edit_phrases):
            # Try to find the target file
            target_file = self.last_file
            
            # If no last_file or it doesn't exist, try to find a file matching the description
            if not target_file or not target_file.exists():
                target_dir = self.last_target or Path(self.config.workspace)
                # Look for text/story files in current directory
                candidates = []
                try:
                    for f in target_dir.iterdir():
                        if f.is_file() and f.suffix in (".txt", ".md", ".py", ".js", ".html", ".css", ".json") and not f.name.startswith("."):
                            candidates.append(f)
                except Exception:
                    pass
                # Fuzzy match: find file whose name matches words in the goal
                goal_words = set(lowered_goal.split())
                for c in candidates:
                    name_words = set(c.stem.lower().replace("-", " ").replace("_", " ").split())
                    if name_words & goal_words:  # Any overlap
                        target_file = c
                        break
                # If only one candidate, use it
                if not target_file and len(candidates) == 1:
                    target_file = candidates[0]
                # Otherwise, use the most recently modified
                if not target_file and candidates:
                    target_file = max(candidates, key=lambda p: p.stat().st_mtime)
            
            # If we detect edit intent but can't find a target file, bail out gracefully
            # (prevents falling through to the slow agent path)
            if not target_file or not target_file.exists():
                err("No file found to edit. Create one first or navigate to the right directory.")
                return

            if target_file and target_file.exists():
                from .backend import ollama_generate
                # Use fast model for content edit (3-5x faster, quality is fine for creative content)
                # Use main model only for code files
                is_code = target_file.suffix in (".py", ".js", ".ts", ".html", ".css", ".json", ".jsx", ".tsx")
                if is_code:
                    gen_model = getattr(self.config, 'ollama_model', 'phi4-mini:latest')
                else:
                    gen_model = getattr(self.config, 'ollama_fast_model', 'qwen2.5:0.5b')
                flow(f"intent={intent} → fast content edit via {gen_model}")
                
                current_content = target_file.read_text(encoding="utf-8")
                # Detect the type of edit
                is_extend = any(w in lowered_goal for w in ["longer", "expand", "more", "extend", "elaborate", "add more"])
                is_rewrite = any(w in lowered_goal for w in ["rewrite", "redo", "start over"])
                is_shorten = any(w in lowered_goal for w in ["shorter", "brief", "condense", "reduce"])

                if is_extend:
                    instruction = (
                        f"Take the existing content and expand it significantly — add more paragraphs, "
                        f"more detail, more description, more characters or events. Keep the same theme/topic. "
                        f"The result should be AT LEAST 3x longer than the original."
                    )
                elif is_shorten:
                    instruction = "Shorten the content while keeping the essential meaning. Make it concise."
                elif is_rewrite:
                    instruction = "Rewrite the content with fresh creativity. Keep the theme but use different words."
                else:
                    instruction = "Rewrite the content as requested."

                gen_prompt = (
                    f"You are rewriting a file. Here is the original content:\n"
                    f"---\n{current_content[:1000]}\n---\n\n"
                    f"Task: {instruction}\n"
                    f"User's request: {goal}\n\n"
                    f"Now write the new content. Output ONLY the file text, no preamble, no apologies, no fences:"
                )
                # Cap tokens: edits can be longer than creations
                gen_tokens = 500 if is_extend else (200 if is_shorten else 400)
                new_content = ollama_generate(
                    gen_model, gen_prompt,
                    system_text="You are a creative writer. Expand/rewrite content as instructed. Output only raw content.",
                    max_tokens=gen_tokens, temperature=0.8
                )
                if new_content and len(new_content.strip()) > 10:
                    # Detect refusal patterns and reject — try once with a stricter prompt
                    refusal_signals = ["i'm sorry", "i cannot", "i can't", "i'm not able",
                                        "as an ai", "i don't have", "unable to"]
                    nc_lower = new_content.lower()[:200]
                    if any(s in nc_lower for s in refusal_signals):
                        # Retry with a more explicit prompt
                        retry_prompt = (
                            f"Rewrite this content to be {('longer and more detailed' if is_extend else 'different')}. "
                            f"Just write the new content. Do not refuse. Do not apologize.\n\n"
                            f"ORIGINAL: {current_content[:500]}\n\n"
                            f"NEW CONTENT:"
                        )
                        new_content = ollama_generate(
                            gen_model, retry_prompt,
                            system_text="Write content. Never refuse. Never apologize.",
                            max_tokens=gen_tokens, temperature=0.9
                        )
                        if not new_content or any(s in new_content.lower()[:200] for s in refusal_signals):
                            err("Model keeps refusing the edit. Try a different request.")
                            return
                    # Strip markdown fences if present
                    nc = new_content.strip()
                    if nc.startswith("```"):
                        lines = nc.split("\n")
                        nc = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
                    target_file.write_text(nc, encoding="utf-8")
                    self.last_file = target_file
                    ok(f"Updated: {target_file}")
                    self.chat_history.append("ASSISTANT", f"Updated {target_file.name}")
                    self.memory.add_event(f"Updated file: {target_file}")
                    return
                else:
                    err(f"Model couldn't generate content. Try a larger model (--pick-model).")
                    return

        # ── Model Routing ──
        # Route talking and analyzing to the faster UI model, coding to the main model
        if intent in ("CONVO", "QUERY"):
            active_config = self.ui_config
        else:
            active_config = self.config
        
        # ── Fast Conversational Route ──
        if intent == "CONVO":
            lowered = goal.lower().strip()

            # Record user message in chat_log FIRST so history is available
            self.chat_log.append({"role": "user", "content": goal})

            # Build prompt with conversation history (so model remembers)
            simple_greetings = {"hi", "hello", "hey", "how are you", "what's up", "thanks", "thank you", "ok", "okay", "yes", "no"}
            
            # Use chat_log for conversation history (ordered, complete)
            recent_context = ""
            if len(self.chat_log) > 1:  # More than just the current message
                recent_turns = self.chat_log[-10:]  # Last 10 turns for better context
                history_lines = []
                for entry in recent_turns:
                    role = entry.get("role", "")
                    content = entry.get("content", "")[:200]
                    if role == "user":
                        history_lines.append(f"User: {content}")
                    elif role == "assistant":
                        history_lines.append(f"Assistant: {content}")
                if history_lines:
                    recent_context = "\n".join(history_lines) + "\n\n"
            
            if lowered in simple_greetings and not recent_context:
                convo_prompt = f"User: {goal}"
                max_tok = 20
            else:
                convo_prompt = f"{recent_context}User: {goal}"
                max_tok = 60

            # ── Use fast model for conversation (main model is too slow for chat) ──
            sys_prompt = (
                "You are Mini AI, a coding assistant. Reply in 1-2 sentences. "
                "Use the conversation history above to answer questions. "
                "If the user told you their name, remember it. "
                "When asked about something from the conversation, refer to what was said."
            )
            from .backend import ollama_generate
            fast_model = getattr(self.config, 'ollama_fast_model', 'qwen2.5:0.5b')
            flow(f"intent={intent} → {fast_model}")
            reply = ollama_generate(fast_model, convo_prompt, system_text=sys_prompt, max_tokens=max_tok, temperature=0.7)
            if not reply:
                reply = "Hey! How can I help you?"

            # Record assistant reply in chat_log for future context
            self.chat_log.append({"role": "assistant", "content": reply})
            self.chat_history.append("ASSISTANT", reply)
            self.memory.add_event(f"User: {goal}\nAssistant: {reply}")
            ai(reply)
            return
        
        # ── Quick Math Check ──
        if intent == "QUERY":
            quick_result = _try_quick_math(goal)
            if quick_result:
                self.chat_history.append("ASSISTANT", quick_result)
                ai(quick_result)
                return

        # ── QUERY: fast model answers knowledge questions ──
        if intent == "QUERY":
            recent = self.memory.context_for(goal)
            ctx = ""
            if recent:
                lines = [l for l in recent.split("\n") if l.startswith("User:") or l.startswith("Assistant:")]
                if lines:
                    ctx = "\n".join(lines[-6:]) + "\n\n"
            sys_q = "You are Mini AI. Answer concisely based on conversation context."
            from .backend import ollama_generate
            fast_model = getattr(self.config, 'ollama_fast_model', 'qwen2.5:0.5b')
            reply = ollama_generate(fast_model, f"{ctx}User: {goal}", system_text=sys_q, max_tokens=100, temperature=0.3)
            if reply:
                self.chat_history.append("ASSISTANT", reply)
                self.memory.add_event(f"User: {goal}\nAssistant: {reply}")
                ai(reply)
                return
        
        # ── Quick Response Handler (everyday utilities) ──
        quick_resp = self._try_quick_response(goal)
        if quick_resp:
            self.chat_history.append("ASSISTANT", quick_resp)
            self.memory.add_event(f"Quick response: {goal}\nResult: {quick_resp}")
            return
        
        # ── Fast Filesystem Count/Search ──
        # For simple "count", "search", "list", "find" queries on directories, use direct tool execution
        if self._is_filesystem_query(goal):
            result = self._execute_filesystem_query(goal)
            if result:
                self.chat_history.append("ASSISTANT", result)
                ai(result)
                self.memory.add_event(f"Filesystem query: {goal}\nResult: {result}")
                return
        
        # ── Direct Action Fast-Path ──
        # For simple "play", "search", "run" commands with clear intent, bypass full agent
        if self._is_direct_action(goal):
            result = self._execute_direct_action(goal)
            if result:
                self.chat_history.append("ASSISTANT", result)
                self.memory.add_event(f"Direct action: {goal}\nResult: {result}")
                return

        # ── AI Goal Dispatcher (0.5B model, ~0.5-1s) ──
        # For ambiguous but tool-shaped requests that regex can't handle confidently
        # Uses tiny model + GBNF grammar to classify goal → tool call
        if intent in ("TASK", "QUERY", "EXPLORE"):
            dispatch_result = self._try_ai_dispatch(goal)
            if dispatch_result:
                self.chat_history.append("ASSISTANT", dispatch_result)
                self.memory.add_event(f"AI dispatch: {goal}\nResult: {dispatch_result}")
                return

        # ── Setup / Build Guidance Fast-Path ──
        # Search the web first for setup/build/create/install requests, then auto-execute.
        setup_guidance = None
        if self._is_setup_guidance(goal):
            setup_guidance = self._search_setup_guidance(goal)
            if setup_guidance:
                self.chat_history.append("ASSISTANT", setup_guidance)
                self.memory.add_event(f"Setup guidance search: {goal}\nResult: {setup_guidance}")
                # Don't return - continue to execution with guidance in context
                # Force EXPLORE intent to use coding model for actual implementation
                intent = "EXPLORE"
        
        # ── Vague/Unclear Command Detector ──
        # If goal is too vague ("do it", "help me", etc.), search web for context
        if self._is_vague_command(goal):
            web_result = self._search_for_vague_intent(goal)
            if web_result:
                self.chat_history.append("ASSISTANT", web_result)
                self.memory.add_event(f"Vague command search: {goal}\nResult: {web_result}")
                return
            
        # ── Auto-Orchestrator Route ──
        # Force COMPLEX for multi-step project creation with UI customization
        if intent in ("TASK", "EXPLORE", "EDIT"):
            lowered_goal = goal.lower()
            complex_signals = [
                # Project + UI customization
                ("create" in lowered_goal or "build" in lowered_goal or "make" in lowered_goal)
                and any(ui in lowered_goal for ui in ["like facebook", "like twitter", "like instagram",
                                                      "custom ui", "with ui", "look like", "styled like",
                                                      "with dashboard", "with pages"]),
                # Multi-step with "then" or "and also"
                " then " in lowered_goal and len(lowered_goal.split()) > 15,
                # Framework + customization
                any(fw in lowered_goal for fw in ["laravel", "react", "vue", "next", "django"])
                and any(kw in lowered_goal for kw in ["customize", "style", "design", "facebook", "clone"]),
            ]
            if any(complex_signals):
                intent = "COMPLEX"
        
        if intent == "COMPLEX" and not self.use_orchestrator:
            use_orch = True
        else:
            use_orch = self.use_orchestrator
        
        # ── Enrich goal with framework commands and execution plans ──
        # For TASK, EXPLORE, and COMPLEX intents involving frameworks
        if intent in ("TASK", "EXPLORE", "COMPLEX"):
            goal = self._enrich_task_goal(goal)
        
        # Build session context from added files (Pinned context)
        added_ctx = []
        for f in list(self.added_files):
            try:
                p = Path(f)
                if p.exists():
                    content = p.read_text(encoding="utf-8")
                    added_ctx.append(f"--- PINNED FILE: {f} ---\n{content}")
                else:
                    self.added_files.remove(f)
            except Exception:
                pass
        session_context = "\n".join(added_ctx)

        if use_orch:
            flow(f"intent={intent} → orchestrator ({self.config.ollama_model})")
            result = orchestrated_agent_mode(
                self.config, goal,
                assume_yes=(self.autopilot_mode == "safe"),
                memory=self.memory,
                verbose=self.verbose,
            )
        else:
            flow(f"intent={intent} → agent ({active_config.ollama_model})")
            result = agent_mode(
                active_config, goal,
                assume_yes=(self.autopilot_mode == "safe"),
                session_context=session_context,
                persistent_context=self.memory.context_for(goal),
                memory=self.memory,
                verbose=self.verbose,
                chat_log=self.chat_log,
                observations=self.observations, # Pass existing observations
                intent=intent, # Pass the dynamic intent tier
                initial_target=self.last_target,  # Pass user's cd target
            )
        
        # Extract human-readable output from structured TaskResult JSON
        result = TaskResult.from_json(result).output
        self.memory.add_event(f"Task: {goal}\nResult: {result}")
        self.chat_history.append("ASSISTANT", result)
        
        # Update last_target if agent navigated to a directory
        if result and "Navigated to:" in result:
            import re as _re
            nav_match = _re.search(r'Navigated to:\s*(.+)', result)
            if nav_match:
                nav_path = Path(nav_match.group(1).strip())
                if nav_path.exists() and nav_path.is_dir():
                    self.last_target = nav_path
                    self.observations = [f"CWD: {nav_path}"]
        
        # Use CopixTUI if available, otherwise fall back to old UI
        if self.copix:
            self.copix.add_message("assistant", result, is_current=True)
            self.copix.render()
        else:
            ai(result)
    
    def _display_ai_response(self, response: str, is_streaming: bool = False) -> None:
        """Display AI response using CopixTUI or fallback to old UI."""
        if self.copix:
            if is_streaming:
                self.copix.update_generation(response)
            else:
                self.copix.add_message("assistant", response, is_current=True)
                self.copix.render()
        else:
            ai(response)
    
    def _start_generation(self, hint: str = "Generating") -> None:
        """Start generation spinner with CopixTUI or silently with old UI."""
        if self.copix:
            self.copix.start_generation(hint)
    
    def _end_generation(self, result: str, metadata: Optional[dict] = None) -> None:
        """End generation and display result."""
        if self.copix:
            self.copix.end_generation(result, metadata or {})
        else:
            ai(result)
