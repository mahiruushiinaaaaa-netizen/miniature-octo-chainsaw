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

from ..agents.agent import agent_mode, request_stop
from ..agents.orchestrator import orchestrated_agent_mode
from .backend import generate
from .config import Config
from ..ui import ok, err, warn, ai, panel, set_compact, set_raw, STATE
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
        """Detect simple direct action requests that don't need full agent reasoning."""
        lowered = goal.lower().strip()
        
        # Play/stream music, videos, etc.
        is_question = lowered.startswith(("what", "who", "how", "where", "is ", "are "))
        play_keywords = ["play", "stream", "listen", "watch", "put on", "queue"]
        if any(kw in lowered for kw in play_keywords) and not is_question:
            # Check if it includes media type indicators
            media_keywords = ["music", "song", "album", "playlist", "video", "youtube", "mp3", "audio"]
            if any(kw in lowered for kw in media_keywords):
                return True
        
        # Web search
        search_keywords = ["search", "google", "look up", "find info", "what is", "who is", "how to"]
        if any(kw in lowered for kw in search_keywords) and len(lowered.split()) > 2:
            return True
        
        # Run a shell command
        run_keywords = ["run", "execute", "bash", "cmd", "command"]
        if any(kw in lowered for kw in run_keywords) and any(c in goal for c in ["=", "--", ":", "|"]):
            return True
        
        return False

    def _execute_direct_action(self, goal: str) -> Optional[str]:
        """Execute a direct action immediately without full agent reasoning."""
        try:
            pm = PathManager(self.config.workspace)
            writer = SafeFileWriter(pm)
            executor = ToolExecutor(self.config, pm, writer)
            
            lowered = goal.lower()
            
            # Route play/stream requests to tool_play_media
            if any(kw in lowered for kw in ["play", "stream", "listen", "watch", "put on", "queue"]):
                panel("PLAYING MEDIA", f"Attempting to play: {goal[:60]}...")
                action = {"action": "play_media", "query": goal}
                is_final, result_json = executor.execute(action, assume_yes=True)
                
                import json
                try:
                    result_data = json.loads(result_json)
                    output = result_data.get("output", "")
                    ok(output)
                    return output
                except Exception:
                    return result_json
            
            # Route web search requests
            elif any(kw in lowered for kw in ["search", "google", "look up", "find info"]):
                # Extract search query
                search_query = goal
                for kw in ["search ", "google ", "look up ", "find info "]:
                    if kw in lowered:
                        idx = lowered.index(kw)
                        search_query = goal[idx + len(kw):].strip()
                        break
                
                panel("SEARCHING WEB", f"Query: {search_query[:60]}...")
                action = {"action": "web_search", "query": search_query}
                is_final, result_json = executor.execute(action, assume_yes=True)
                
                import json
                try:
                    result_data = json.loads(result_json)
                    output = result_data.get("output", "")
                    ok(output[:200])
                    return output
                except Exception:
                    return result_json
            
            # Route shell commands
            elif any(kw in lowered for kw in ["run ", "execute "]):
                # Extract command
                cmd = goal
                for kw in ["run ", "execute "]:
                    if kw in lowered:
                        idx = lowered.index(kw)
                        cmd = goal[idx + len(kw):].strip()
                        break
                
                panel("EXECUTING", f"Command: {cmd[:60]}...")
                action = {"action": "run_cmd", "command": cmd}
                is_final, result_json = executor.execute(action, assume_yes=True)
                
                import json
                try:
                    result_data = json.loads(result_json)
                    output = result_data.get("output", "")
                    ok(output[:200])
                    return output
                except Exception:
                    return result_json
            
            return None
        
        except Exception as e:
            from .logger import get_logger
            logger = get_logger("commands")
            logger.debug(f"Direct action execution failed: {e}")
            return None

    def _is_vague_command(self, goal: str) -> bool:
        """Detect vague/unclear commands that need web search for context."""
        lowered = goal.lower().strip()
        # Skip if it's a continuation command
        if self._is_continuation_command(goal):
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
        """Detect setup/build/install/create requests that should search the web first."""
        lowered = goal.lower().strip()

        setup_keywords = [
            "create a", "create an", "create project", "create app", "build a", "build an",
            "set up", "setup", "install", "initialize", "init", "scaffold", "starter",
            "react native", "next js", "next.js", "vite", "expo", "android", "ios",
        ]
        action_words = ["help", "make", "do it", "do this", "guide", "how to", "what should i", "what do i"]

        has_setup_shape = any(kw in lowered for kw in setup_keywords)
        has_action_shape = any(kw in lowered for kw in action_words)

        # Prefer web guidance for short setup/build requests that don't point at a specific file edit.
        if has_setup_shape and has_action_shape:
            return True

        if has_setup_shape and len(lowered.split()) <= 10:
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
        lowered = goal.lower().strip()
        
        # Extract meaningful words
        words = [w for w in goal.split() if len(w) > 2 and w.lower() not in ["the", "how", "can", "do", "get", "make", "help", "me", "you", "with"]]
        
        if not words:
            return "how to get started"
        
        # Build search query
        if "help me" in lowered:
            return f"how to {' '.join(words)}"
        elif "how to" in lowered or "how do" in lowered:
            return goal
        elif "what is" in lowered or "tell me" in lowered:
            return goal
        else:
            return f"how to {goal}"
    
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
        time_keywords = ["what time", "current time", "what's the time", "what day", "today", "date", "what date"]
        if any(kw in lowered for kw in time_keywords):
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
        """Fast local heuristic to categorize task complexity for dynamic routing."""
        lowered = goal.lower().strip()
        
        # 2. Tier 4: Complex Orchestration (check first to avoid misclassification)
        if any(keyword in lowered for keyword in ["refactor", "create app", "build a full", "architect", "from scratch"]):
            if len(lowered.split()) > 4:
                return "COMPLEX"
                
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
            return "EDIT"  # Edit intent even without file path
        
        # 1. Tier 0: Simple Conversational (exact matches only)
        if lowered in {"hi", "hello", "hey", "how are you", "what's up", "help", "thanks", "thank you", "ok", "okay", "yes", "no"}:
            return "CONVO"
        
        # Short statement without query/edit keywords = brief question/statement
        if len(lowered) < 25 and not any(c in lowered for c in ["/", "\\", "."]) and not any(k in lowered for k in ["file", "fix", "code", "run", "make", "create", "bug", "error", "how", "what", "where", "why", "when"]):
            return "CONVO"
                
        # 5. Tier 3: Default Explore
        return "EXPLORE"

    def _is_continuation_command(self, goal: str) -> bool:
        """Detect phrases like 'do it', 'do that', 'go ahead' that refer to previous goal."""
        lowered = goal.lower().strip()
        continuation_phrases = [
            "do it", "do that", "go ahead", "proceed", "execute", "make it happen",
            "run it", "start it", "begin", "go on", "continue", "next step",
            "now do it", "please do", "can you do", "execute it"
        ]
        return any(phrase in lowered for phrase in continuation_phrases) and len(lowered.split()) <= 5

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
            self.observations = [] # Reset observations for new goal
            force_coding = False

        self.chat_history.append("USER", goal)
        
        intent = self._classify_intent(goal)
        # Continuation commands should use coding model regardless of classification
        if is_continuation:
            intent = "EXPLORE"
        
        # ── Model Routing ──
        # Route talking and analyzing to the faster UI model, coding to the main model
        if intent in ("CONVO", "QUERY"):
            active_config = self.ui_config
            if active_config != self.config:
                panel("MODEL ROUTING", f"Using fast analytical model ({active_config.model.name}) for {intent}")
        else:
            active_config = self.config
            if self.ui_config != self.config:
                panel("MODEL ROUTING", f"Using primary coding model ({active_config.model.name}) for {intent}")
        
        # ── Fast Conversational Route ──
        if intent == "CONVO":
            panel("FAST CONVERSATION", "Bypassing repo-map and tools for simple greeting...")
            sys_prompt = "You are Mini AI. Respond conversationally and extremely briefly. No markdown code blocks."
            reply = generate(active_config, f"User says: {goal}", max_tokens=150, system_text=sys_prompt)
            if reply:
                self.chat_history.append("ASSISTANT", reply)
                ai(reply)
            return
        
        # ── Quick Math Check ──
        if intent == "QUERY":
            from .agent import _try_quick_math
            quick_result = _try_quick_math(goal)
            if quick_result:
                panel("QUICK CALCULATION", f"{goal.strip()} = {quick_result}")
                self.chat_history.append("ASSISTANT", quick_result)
                ai(quick_result)
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
        if intent == "COMPLEX" and not self.use_orchestrator:
            ok("Auto-detected a massive task. Dynamically enabling the Multi-Agent Orchestrator...")
            use_orch = True
        else:
            use_orch = self.use_orchestrator
        
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
            result = orchestrated_agent_mode(
                self.config, goal,
                assume_yes=(self.autopilot_mode == "safe"),
                memory=self.memory,
                verbose=self.verbose,
            )
        else:
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
            )
        
        self.memory.add_event(f"Task: {goal}\nResult: {result}")
        self.chat_history.append("ASSISTANT", result)
        panel("AGENT FINISHED", result)
