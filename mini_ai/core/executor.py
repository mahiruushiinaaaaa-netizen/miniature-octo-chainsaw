"""
executor.py – Tool execution layer for mini_ai.
Responsible for running tool actions and returning standardized observations.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
import webbrowser
from pathlib import Path
from typing import Any, cast

from dataclasses import dataclass, field
from typing import Any, cast, Dict, List, Optional, Callable

from .config import Config
from .platform_adapter import get_platform_adapter
from ..ui import ok, err, confirm_diff
from ..tools.file_writer import SafeFileWriter
from ..agents.coder import apply_edit_block
from .repo import pre_edit_commit, post_edit_commit
from ..tools.linter import lint_file
from .path_manager import PathManager
from .workspace_index import build_workspace_index, compact_index_summary, relevant_files
from .sandbox import LocalSandbox, VenvSandbox, SandboxProvider
from ..tools.code_utils import run_python_code
from ..tools.task_tools import make_task_brief, make_todo_markdown, write_task_note
from ..ui.choice_ui import choose_from_list, normalize_options, confirm
from .approval import should_auto_approve
from .schemas import get_schema
from .logger import get_logger
from .indexer import get_indexer
from .metrics import get_metrics_collector
from .recovery import RecoveryManager
from .errors import ExecutionError, ErrorContext
from .environment_inspector import inspect_environment
from .sandbox.security import CommandRiskScorer
from .rag import RAGManager
from .context_injector import ContextInjector
from .command_memory import CommandMemory
from .batch import BatchExecutor
from .multi_action import MultiActionExecutor
from .tool_reliability import RecoverySuggester, SchemaValidator
from .change_tracker import FileChangeTracker
from ..tools.data_tools import json_query, csv_query, text_transform, regex_tool, calculate, datetime_util
from ..tools.system_tools import system_info, env_var, process_manage, clipboard_op, file_info, diff_files, screenshot
from ..tools.network_tools import http_request, sqlite_query
from ..tools.archive_tools import archive_op, scaffold
from ..tools.git_ops import git_op
from ..tools.docker_ops import docker_op
from ..tools.package_ops import package_op
from ..tools.code_ops import code_analyze
from ..tools.test_ops import test_op
from ..tools.convert_ops import convert, format_convert, number_convert
from ..tools.net_ops import net_op
from ..tools.project_ops import project_init, project_info, dependency_tree, project_health
from ..tools.file_ops_ext import file_op_ext
from ..tools.text_ops import text_op, json_format, template_render, markdown_op
from ..tools.crypto_ops import crypto_op
from ..tools.assistant_tools import (
    organize_files, undo_organize, smart_cleanup, file_summary,
    schedule_reminder, check_reminders, quick_note, list_notes, system_health,
)
from ..tools.productivity_tools import (
    open_app, list_processes as list_procs_tool, kill_process,
    timer_op, snippet_op, smart_rename, wifi_passwords,
    startup_programs, quick_calc, clipboard_history,
)
from ..tools.life_tools import (
    weather, translate, email_draft, pomodoro,
    habit_tracker, expense_tracker, daily_planner, api_test,
)
from ..tools.power_tools import (
    screenshot, ip_info, text_to_speech, bookmarks,
    motivation, system_action, speed_test, text_stats,
    color_convert, lorem_ipsum,
)
from ..tools.smart_tools import (
    shorten_url, define_word, timezone_convert, countdown,
    random_generate, regex_test, port_scan, uptime_check,
    git_summary, world_clock,
)
from ..tools.daily_tools import (
    age_calc, bmi_calc, tip_calc, loan_calc,
    water_tracker, sleep_tracker, flashcards, contacts,
    daily_affirmation,
)
from ..tools.automation_tools import (
    youtube_download, pdf_summarize, image_resize, auto_backup,
    daily_digest, project_stats, dependency_audit, docker_helper,
    auto_commit, cron_scheduler,
)

@dataclass
class ExecutionContext:
    """Stateful execution context to track workspace state."""
    cwd: Path
    created_files: list[Path] = field(default_factory=list)
    created_folders: list[Path] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    last_output: Optional[str] = None
    errors: list[str] = field(default_factory=list)
    capabilities: dict[str, Any] = field(default_factory=dict)


ALLOWED_COMMANDS = [
    # Core system
    "python", "python3", "pip", "pip3", "pipx", "uv", "uvx", "poetry",
    "powershell", "pwsh", "cmd", "wsl", "bash", "sh",
    # JavaScript/Node ecosystem
    "node", "npm", "npx", "yarn", "bun", "bunx", "pnpm", "deno", "tsx", "ts-node",
    # PHP ecosystem
    "php", "composer", "artisan", "phpunit", "pest", "sail", "laravel",
    # Version control
    "git", "gh", "svn",
    # Package managers
    "winget", "choco", "scoop", "apt", "brew", "snap", "cargo", "go",
    # File operations
    "ls", "dir", "cd", "mkdir", "rm", "rmdir", "cp", "mv", "cat", "type",
    "echo", "grep", "find", "head", "tail", "sort", "wc", "diff", "patch",
    "tar", "zip", "unzip", "7z", "rar",
    # Network
    "curl", "wget", "ssh", "scp", "rsync", "ping", "nslookup", "tracert",
    # Database
    "sqlite3", "mysql", "psql", "mongosh", "redis-cli",
    # Docker/Containers
    "docker", "docker-compose", "podman", "kubectl", "helm",
    # Cloud CLI
    "aws", "az", "gcloud", "firebase", "vercel", "netlify", "fly", "railway",
    # Build tools
    "make", "cmake", "gradle", "mvn", "ant",
    # Mobile development
    "adb", "flutter", "dart", "expo", "react-native", "pod", "xcodebuild",
    # Rust/Go/C
    "cargo", "rustc", "go", "gcc", "g++", "clang", "dotnet",
    # Testing
    "pytest", "jest", "vitest", "mocha", "phpunit", "cypress",
    # Linting/Formatting
    "eslint", "prettier", "black", "ruff", "flake8", "mypy", "rubocop",
    # Ruby
    "ruby", "gem", "bundle", "rails", "rake",
    # Java/Kotlin
    "java", "javac", "kotlin", "kotlinc", "mvn", "gradle",
    # System utilities
    "systemctl", "service", "tasklist", "taskkill", "netstat", "ipconfig",
    "ifconfig", "whoami", "hostname", "env", "set", "reg",
    # Media/Documents
    "ffmpeg", "ffprobe", "magick", "convert", "pandoc", "wkhtmltopdf",
    # Misc dev tools
    "terraform", "ansible", "vagrant", "ngrok", "localtunnel",
    "jq", "yq", "sed", "awk", "xargs", "tee",
]


_MAX_READ_BYTES = 200_000
_MAX_SEARCH_BYTES = 1_000_000
_SHELL_META_RE = re.compile(r"[|&;<>\n]")

logger = get_logger("executor")

_SAFE_RETRY_TOOLS = {
    "read_files",
    "list_dir",
    "search_files",
}

class ToolExecutor:
    def __init__(self, config: Config, pm: PathManager, writer: SafeFileWriter, on_command_start=None, on_command_output=None, on_command_end=None):
        self.config = config
        self.pm = pm
        self.writer = writer
        self.active_processes: dict[str, subprocess.Popen] = {}
        self.rag = RAGManager(config)
        self._context_injector = ContextInjector(config, rag_manager=self.rag)
        self._metrics = get_metrics_collector()
        self._recovery = RecoveryManager()
        self.adapter = get_platform_adapter()
        self.context = ExecutionContext(cwd=pm.effective_root)
        self.context.capabilities = inspect_environment()
        # Callbacks for GUI visibility (optional)
        self._on_command_start = on_command_start  # callable(cmd, cwd)
        self._on_command_output = on_command_output  # callable(text)
        self._on_command_end = on_command_end  # callable(exit_code)

        # Initialize Sandbox
        self.sandbox = self._init_sandbox()

        # Initialize Command Memory for RAG-based command persistence
        self.cmd_memory = CommandMemory(config)

        # Tool Registry
        self.registry: Dict[str, Callable] = {
            "filesystem_create_file": self.tool_filesystem_create_file,
            "filesystem_create_directory": self.tool_filesystem_create_directory,
            "git_init": self.tool_git_init,
            "git_add": self.tool_git_add,
            "git_commit": self.tool_git_commit,
            "python_execute": self.tool_python_execute,
            "javascript_execute": self.tool_javascript_execute,
            "laravel_create_project": self.tool_laravel_create_project,
            "laravel_install_breeze": self.tool_laravel_install_breeze,
            "laravel_migrate": self.tool_laravel_migrate,
            "create_framework_project": self.tool_create_framework_project,
            # --- Expanded tool set ---
            "json_query": self.tool_json_query,
            "csv_query": self.tool_csv_query,
            "text_transform": self.tool_text_transform,
            "system_info": self.tool_system_info,
            "http_request": self.tool_http_request,
            "sqlite_query": self.tool_sqlite_query,
            "archive": self.tool_archive,
            "clipboard": self.tool_clipboard,
            "env_var": self.tool_env_var,
            "process_manage": self.tool_process_manage,
            "diff_files": self.tool_diff_files,
            "screenshot": self.tool_screenshot,
            "timer": self.tool_timer,
            "file_info": self.tool_file_info,
            "scaffold": self.tool_scaffold,
            "calculate": self.tool_calculate,
            "datetime_util": self.tool_datetime_util,
            "regex_tool": self.tool_regex_tool,
            # --- Tool Expansion (19 new compound tools) ---
            "git_op": self.tool_git_op,
            "docker_op": self.tool_docker_op,
            "package_op": self.tool_package_op,
            "code_analyze": self.tool_code_analyze,
            "test_op": self.tool_test_op,
            "convert": self.tool_convert,
            "format_convert": self.tool_format_convert,
            "number_convert": self.tool_number_convert,
            "net_op": self.tool_net_op,
            "project_init": self.tool_project_init,
            "project_info": self.tool_project_info,
            "dependency_tree": self.tool_dependency_tree,
            "project_health": self.tool_project_health,
            "file_op_ext": self.tool_file_op_ext,
            "text_op": self.tool_text_op,
            "json_format": self.tool_json_format,
            "template_render": self.tool_template_render,
            "markdown_op": self.tool_markdown_op,
            "crypto_op": self.tool_crypto_op,
            # --- Assistant / Productivity tools ---
            "organize_files": self.tool_organize_files,
            "undo_organize": self.tool_undo_organize,
            "smart_cleanup": self.tool_smart_cleanup,
            "file_summary": self.tool_file_summary,
            "schedule_reminder": self.tool_schedule_reminder,
            "check_reminders": self.tool_check_reminders,
            "quick_note": self.tool_quick_note,
            "list_notes": self.tool_list_notes,
            "system_health": self.tool_system_health,
            "open_app": self.tool_open_app,
            "list_processes": self.tool_list_processes,
            "kill_process": self.tool_kill_process,
            "timer": self.tool_timer,
            "snippet": self.tool_snippet,
            "smart_rename": self.tool_smart_rename,
            "wifi_passwords": self.tool_wifi_passwords,
            "startup_programs": self.tool_startup_programs,
            "quick_calc": self.tool_quick_calc,
            "clipboard_history": self.tool_clipboard_history,
            # --- Life management tools ---
            "weather": self.tool_weather,
            "translate": self.tool_translate,
            "email_draft": self.tool_email_draft,
            "pomodoro": self.tool_pomodoro,
            "habit_tracker": self.tool_habit_tracker,
            "expense_tracker": self.tool_expense_tracker,
            "daily_planner": self.tool_daily_planner,
            "api_test": self.tool_api_test,
            # --- Power tools ---
            "screenshot": self.tool_screenshot_capture,
            "ip_info": self.tool_ip_info,
            "text_to_speech": self.tool_text_to_speech,
            "bookmarks": self.tool_bookmarks,
            "motivation": self.tool_motivation,
            "system_action": self.tool_system_action,
            "speed_test": self.tool_speed_test,
            "text_stats": self.tool_text_stats,
            "color_convert": self.tool_color_convert,
            "lorem_ipsum": self.tool_lorem_ipsum,
            # --- Smart tools ---
            "shorten_url": self.tool_shorten_url,
            "define_word": self.tool_define_word,
            "timezone_convert": self.tool_timezone_convert,
            "countdown": self.tool_countdown,
            "random_generate": self.tool_random_generate,
            "regex_test": self.tool_regex_test,
            "port_scan": self.tool_port_scan,
            "uptime_check": self.tool_uptime_check,
            "git_summary": self.tool_git_summary,
            "world_clock": self.tool_world_clock,
            # --- Daily life tools ---
            "age_calc": self.tool_age_calc,
            "bmi_calc": self.tool_bmi_calc,
            "tip_calc": self.tool_tip_calc,
            "loan_calc": self.tool_loan_calc,
            "water_tracker": self.tool_water_tracker,
            "sleep_tracker": self.tool_sleep_tracker,
            "flashcards": self.tool_flashcards,
            "contacts": self.tool_contacts,
            "daily_affirmation": self.tool_daily_affirmation,
            # --- Automation tools ---
            "youtube_download": self.tool_youtube_download,
            "pdf_summarize": self.tool_pdf_summarize,
            "image_resize": self.tool_image_resize,
            "auto_backup": self.tool_auto_backup,
            "daily_digest": self.tool_daily_digest,
            "project_stats": self.tool_project_stats,
            "dependency_audit": self.tool_dependency_audit,
            "docker_helper": self.tool_docker_helper,
            "auto_commit": self.tool_auto_commit,
            "cron_scheduler": self.tool_cron_scheduler,
        }

    def _init_sandbox(self) -> SandboxProvider:
        """Initialize the configured sandbox provider."""
        sb_type = getattr(self.config, "sandbox_type", "local").lower()
        if sb_type == "venv":
            return VenvSandbox(self.pm)
        # Default to Local for now (Docker can be added later)
        return LocalSandbox(self.pm)

    def kill_all_processes(self) -> list[str]:
        """Terminate all active background processes tracked by the executor."""
        stopped = []
        
        # 1. Kill tracked processes
        for name, proc in list(self.active_processes.items()):
            try:
                if proc and proc.poll() is None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=2)
                    except Exception:
                        proc.kill()
                    stopped.append(name)
            except Exception: pass
        self.active_processes.clear()

        # 2. Kill orphan player via state file PID
        import tempfile
        try:
            state_file = Path(tempfile.gettempdir()) / "miniai_player_state.json"
            if state_file.exists():
                with open(state_file, 'r') as f:
                    state = json.load(f)
                pid = state.get("pid")
                if pid:
                    try:
                        os.kill(pid, 9) # Force kill orphan
                        stopped.append(f"orphan_player({pid})")
                    except: pass
                # Clean up state file to signal stop
                os.remove(state_file)
        except: pass

        return stopped

    def execute(self, action: dict[str, Any], assume_yes: bool = False) -> tuple[bool, str]:
        """Execute a tool action and return (is_final, observation_json)."""
        kind = str(action.get("action", "")).strip()
        start_time = time.perf_counter()
        _run_tool: Any = None
        
        logger.debug(f"Executing tool: {kind}", operation="tool_execute", context={"tool": kind})
        
        # Validate against schema
        schema = get_schema(kind)
        if schema:
            ok_params, reason = schema.validate(action)
            if not ok_params:
                self._metrics.record_operation(f"tool_{kind}", 0, success=False)
                return False, self.result(False, f"Parameter validation failed: {reason}")
        
        try:
            # Check registry first
            method = self.registry.get(kind) or getattr(self, f"tool_{kind}", None)
            
            if method:
                def _run_tool() -> tuple[bool, str]:
                    return method(action, assume_yes)
 
                result = _run_tool()
                
                # Update context
                self.context.last_output = result[1]
                
                # Record success metrics
                duration_ms = (time.perf_counter() - start_time) * 1000
                self._metrics.record_operation(f"tool_{kind}", duration_ms, success=True)
                return result
            
            self._metrics.record_operation(f"tool_{kind}", 0, success=False)
            return False, self.result(False, f"Unknown action: {kind}")
            
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_operation(f"tool_{kind}", duration_ms, success=False)
            
            # Log error with context
            logger.error(
                f"Tool execution failed: {kind}",
                operation="tool_execute",
                context={"tool": kind, "error": str(exc)},
                error=exc,
            )
            
            # Attempt recovery for certain error types
            recovery_result = self._recovery.attempt_recovery(
                exc,
                operation=f"tool_{kind}",
                context={"action": action, "assume_yes": assume_yes},
                retry=_run_tool if (_run_tool and kind in _SAFE_RETRY_TOOLS) else None,
            )
            
            if recovery_result.success:
                logger.info(f"Recovered from error in {kind}", operation="recovery")
                recovered = recovery_result.result
                if isinstance(recovered, tuple) and len(recovered) == 2:
                    self._metrics.record_operation(
                        f"tool_{kind}_recovered",
                        (time.perf_counter() - start_time) * 1000,
                        success=True,
                    )
                    return recovered
                return False, self.result(True, f"Recovered: {recovered}")
            
            return False, self.result(False, f"Error executing {kind}: {str(exc)}")

    def _needs_shell(self, cmd: str) -> bool:
        return bool(_SHELL_META_RE.search(cmd))

    def result(self, success: bool, output: str, **extra: Any) -> str:
        output = output.strip()
        if len(output) > 2000:
            output = output[:2000] + "\n...[truncated]"
        data = {"success": success, "output": output}
        data.update(extra)
        return json.dumps(self._to_json_safe(data), ensure_ascii=False)

    def _to_json_safe(self, value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(k): self._to_json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._to_json_safe(v) for v in value]
        return value

    # --- Tool Implementations ---

    def tool_answer(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        content = str(action.get("content", "Done."))
        # Strip internal system hints that shouldn't be shown to the user
        for hint in ("If this completes the user's request, use the 'answer' tool to finish.",
                     "use the 'answer' tool to finish."):
            content = content.replace(hint, "").strip()
        return True, self.result(True, content)

    def tool_write_files(self, action: dict[str, Any], ay: bool) -> tuple[bool, str]:
        files = action.get("files", [])
        batch = self.writer.write_batch(files, assume_yes=ay)
        return False, self.result(batch.all_ok, batch.summary(), written=batch.written, failed=batch.failed)

    def tool_edit_blocks(self, action: dict[str, Any], ay: bool) -> tuple[bool, str]:
        blocks = action.get("blocks", [])
        
        # Git safety net: commit any pending user changes before AI acts
        if blocks:
            pre_edit_commit(str(self.pm.effective_root))
            
        results = []
        all_ok = True
        written = []
        failed = []
        
        for block in blocks:
            filepath = block.get("file", "")
            search = block.get("search", "")
            replace = block.get("replace", "")
            
            target = self.pm.resolve_target(filepath)
            ok_write, reason = self.pm.validate_write_path(target)
            if not ok_write:
                failed.append(f"{filepath}: {reason}")
                results.append(f"Failed {filepath}: {reason}")
                all_ok = False
                continue
                
            try:
                if target.exists():
                    original = target.read_text(encoding="utf-8")
                else:
                    original = ""
                    
                success, new_content = apply_edit_block(original, search, replace)
                
                if success:
                    if not assume_yes:
                        old_c = target.read_text(encoding="utf-8") if target.exists() else ""
                        if not confirm_diff(filepath, old_c, new_content):
                            results.append(f"Skipped {filepath} (user rejected)")
                            continue

                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(new_content, encoding="utf-8")
                    written.append(filepath)
                    
                    lint_err = lint_file(str(target), new_content)
                    if lint_err:
                        results.append(f"Successfully updated {filepath}, BUT found errors:\n{lint_err}")
                        all_ok = False
                    else:
                        results.append(f"Successfully updated {filepath}")
                else:
                    failed.append(filepath)
                    # For weak models, provide the actual file contents to help them self-heal
                    preview = original[:2000] if original else "(file is empty)"
                    results.append(f"Failed to match SEARCH block in {filepath}.\nActual file contents:\n{preview}\nTry again with a correct SEARCH block.")
                    all_ok = False
            except Exception as e:
                failed.append(filepath)
                results.append(f"Error updating {filepath}: {str(e)}")
                all_ok = False
                
        output = "\n".join(results)
        
        # Git safety net: commit AI changes
        if written:
            post_edit_commit(str(self.pm.effective_root), "edit_blocks")
            
        return False, self.result(all_ok, output, written=written, failed=failed)

    def tool_read_files(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        files_raw = action.get("files", [])
        files = [str(f) for f in files_raw] if isinstance(files_raw, list) else [str(files_raw)]

        chunks = []
        read_paths = []
        failed_paths = []

        for f in files:
            # Use new path verification for better error messages
            exists, path, suggestions = self.pm.verify_path_exists(f)
            if not exists:
                error_msg = f"{f} (not found)"
                if suggestions:
                    error_msg += f" - Suggestions: {', '.join(suggestions[:2])}"
                # Also show parent directory contents for debugging
                parent_hint = self.pm.suggest_path_correction(f)
                if parent_hint and "Contents of" in parent_hint:
                    error_msg += f"\n{parent_hint.split('Contents of')[1].split('---')[0] if 'Contents of' in parent_hint else ''}"
                failed_paths.append(error_msg)
                continue
            try:
                from ..tools.file_ops import is_probably_text
                if not is_probably_text(path):
                    failed_paths.append(f"{f} (binary or non-text)")
                    continue
                
                stat = path.stat()
                size = stat.st_size
                
                # Delegate context enrichment to the context injection layer
                # which handles strategy decisions (embedding retrieval, TF-IDF fallback, raw content)
                content = path.read_text(encoding="utf-8", errors="replace")
                query = self.context.last_output[:200] if self.context.last_output else f"Context from {f}"
                
                # For large files, use context injector to get relevant snippets
                tokens_estimate = len(content) // 4  # rough token estimate
                if size > _MAX_READ_BYTES or tokens_estimate > self.config.ctx:
                    snippets = self._context_injector.enrich(f, content, query)
                    if snippets:
                        snippet_text = "\n".join(
                            f"[{s.source_path} (score={s.score:.2f}, offset={s.offset_start}-{s.offset_end})]\n{s.content}"
                            for s in snippets
                        )
                        chunks.append(f"\n--- FILE: {f} (context-enriched) ---\n{snippet_text}")
                        read_paths.append(str(path))
                        continue

                with path.open("rb") as handle:
                    raw = handle.read(_MAX_READ_BYTES)
                content = raw.decode("utf-8", errors="replace")
                if size > _MAX_READ_BYTES:
                    content += "\n...[truncated]"
                chunks.append(f"\n--- FILE: {f} ---\n{content[:12000]}")
                read_paths.append(str(path))
            except Exception as e:
                failed_paths.append(f"{f} ({str(e)})")
        
        return False, self.result(True, "".join(chunks), read=read_paths, failed=failed_paths)

    def tool_workspace_map(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        root = self.pm.resolve_target(str(action.get("path", ".")))
        max_depth = int(action.get("max_depth", 3))
        
        lines = []
        try:
            for child in sorted(root.rglob("*")):
                rel = child.relative_to(root)
                depth = len(rel.parts)
                if depth > max_depth: continue
                if any(p.startswith(".") or p in {"node_modules", "vendor"} for p in rel.parts): continue
                
                indent = "  " * (depth - 1)
                marker = "/" if child.is_dir() else ""
                lines.append(f"{indent}{rel.name}{marker}")
                if len(lines) > 100: break
            
            return False, self.result(True, "\n".join(lines), path=str(root))
        except Exception as e:
            return False, self.result(False, str(e))

    def tool_run_cmd(self, action: dict[str, Any], ay: bool) -> tuple[bool, str]:
        import re
        from pathlib import Path

        cmd = str(action.get("command", ""))
        cwd = self.pm.resolve_target(str(action.get("cwd", ".")))

        # Smart Windows file creation fallback.
        # Handles commands like:
        # type nul > file.py
        # echo. > file.py
        # even when paths contain spaces and broken quoting.
        create_match = re.search(r'(?:type\s+nul|echo\.)\s*>\s*(.+)', cmd, re.IGNORECASE)
        if create_match:
            raw_target = create_match.group(1).strip().strip('"').strip("'")
            try:
                target_path = Path(raw_target)
                if not target_path.is_absolute():
                    target_path = Path(cwd) / target_path

                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.touch(exist_ok=True)

                if target_path.exists():
                    return False, self.result(True, f"Created file: {target_path}")
                return False, self.result(False, f"Failed to create file: {target_path}")
            except Exception as e:
                return False, self.result(False, f"File creation failed: {e}")

        # Smart Windows directory creation fallback
        mkdir_match = re.search(r'^mkdir\s+(?:-p\s+)?(.+)', cmd, re.IGNORECASE)
        if mkdir_match:
            raw_target = mkdir_match.group(1).strip().strip('"').strip("'")
            try:
                # Handle potential multiple targets or broken quoting by checking for existence
                target_path = Path(raw_target)
                if not target_path.is_absolute():
                    target_path = Path(cwd) / target_path
                
                target_path.mkdir(parents=True, exist_ok=True)
                if target_path.exists():
                    return False, self.result(True, f"Created directory structure: {target_path}")
            except Exception:
                # If path is too complex (contains multiple dirs in one line), fall through to shell
                pass

        if not self.config.allow_run:
            return False, self.result(False, "Command execution disabled. Start with --allow-run to enable.")
        
        # Sandbox check (Phase 6)
        cmd_parts = cmd.split()
        cmd_base = cmd_parts[0].lower() if cmd_parts else ""
        
        # Risk assessment
        risk_score = CommandRiskScorer.get_risk_score(cmd)
        
        if risk_score == 2:
             # High risk: ALWAYS ask for approval unless explicitly forced by ay (but even then, maybe ask)
             if not confirm(f"HIGH RISK COMMAND DETECTED: {cmd}\nAre you absolutely sure?"):
                 return False, self.result(False, "User rejected high-risk command.")

        # Block known destructive patterns (fallback if risk scorer missed something or if we want hard blocks)
        destructive_patterns = ["rm -rf", "del /s", "format", "rd /s", "mkfs", "dd if="]
        if any(p in cmd.lower() for p in destructive_patterns) and risk_score < 2:
             return False, self.result(False, f"Command blocked for safety (destructive pattern): {cmd}")

        # Strict whitelist enforcement
        if cmd_base not in ALLOWED_COMMANDS:
             # Check if it's a relative path to a local script (allowed if it exists)
             try:
                 if not (Path(cwd) / cmd_base).exists():
                     return False, self.result(False, f"Command '{cmd_base}' is not in the allowed whitelist: {ALLOWED_COMMANDS}")
             except Exception:
                 return False, self.result(False, f"Command blocked: {cmd_base}")

        # Auto-install missing dependencies before running the command
        from .dep_installer import ensure_deps_for_command, is_installed
        if not is_installed(cmd_base):
            dep_ok, dep_msg = ensure_deps_for_command(cmd_base)
            if not dep_ok:
                return False, self.result(False, f"Missing dependency: {dep_msg}")
            elif dep_msg:
                logger.info(f"Auto-installed deps for {cmd_base}: {dep_msg}")

        if not ay and not should_auto_approve(destructive=(risk_score > 0)):
            if not confirm(f"Run command in {cwd}: {cmd}?"):
                return False, self.result(False, "User cancelled command")

        try:
            # Notify GUI that command is starting
            if self._on_command_start:
                self._on_command_start(cmd, str(cwd))

            # Use GUI callbacks if available, otherwise use LiveTerminalBox
            if self._on_command_output:
                # GUI mode: stream output via callback
                res = self.sandbox.execute(cmd, timeout=600, on_output=self._on_command_output)
            else:
                # Terminal mode: use LiveTerminalBox
                from ..ui import LiveTerminalBox
                with LiveTerminalBox(cmd) as box:
                    res = self.sandbox.execute(cmd, timeout=600, on_output=box.append)

            return_code = res.exit_code
            stdout = res.stdout
            stderr = res.stderr

            output = stdout + ("\n" + stderr if stderr else "")

            # Notify GUI that command ended
            if self._on_command_end:
                self._on_command_end(return_code)

            if return_code == 0:
                # Update persistent CWD if it was a cd command (supporting optional /d flag)
                import re
                cd_match = re.search(r"(?:^|&&|;)\s*cd\s+(?:/d\s+)?([^&;]+)", cmd, re.IGNORECASE)
                if cd_match:
                    new_rel = cd_match.group(1).strip().strip('"').strip("'")
                    try:
                        # Handle both absolute and relative targets
                        target_path = Path(new_rel)
                        if not target_path.is_absolute():
                            target_path = (cwd / new_rel).resolve()
                        else:
                            target_path = target_path.resolve()
                            
                        if target_path.exists() and target_path.is_dir():
                            self.context.cwd = target_path
                            self.pm.set_target(self.context.cwd)
                            output += f"\n[Session] CWD updated to: {self.context.cwd}\nSUCCESS: You have arrived at the destination. Use 'answer' to finish this task if navigation was your goal."
                    except Exception:
                        pass
                
                # Auto-detect project creation and update CWD to the new project directory
                # This handles: composer create-project X name, npx create-X name, cargo new name, etc.
                project_create_patterns = [
                    r"composer\s+create-project\s+\S+\s+(\S+)",  # composer create-project vendor/pkg name
                    r"npx\s+create-\S+\s+(\S+)",  # npx create-react-app name
                    r"npx\s+\S+@\S+\s+(?:new|init)\s+(\S+)",  # npx @nestjs/cli new name
                    r"cargo\s+new\s+(\S+)",  # cargo new name
                    r"flutter\s+create\s+(\S+)",  # flutter create name
                    r"django-admin\s+startproject\s+(\S+)",  # django-admin startproject name
                    r"rails\s+new\s+(\S+)",  # rails new name
                    r"dotnet\s+new\s+\S+\s+-n\s+(\S+)",  # dotnet new webapp -n name
                ]
                if not cd_match:
                    for pattern in project_create_patterns:
                        proj_match = re.search(pattern, cmd, re.IGNORECASE)
                        if proj_match:
                            proj_name = proj_match.group(1).strip().strip('"').strip("'")
                            proj_dir = (cwd / proj_name).resolve()
                            if proj_dir.exists() and proj_dir.is_dir():
                                self.context.cwd = proj_dir
                                self.pm.set_target(self.context.cwd)
                                output += f"\n[Session] Auto-navigated to new project: {self.context.cwd}"
                            break

            # Record command to memory for future RAG retrieval
            try:
                self.cmd_memory.record(
                    command=cmd,
                    cwd=str(cwd),
                    exit_code=return_code,
                    context={"files": [], "description": f"Command executed in session"}
                )
            except Exception as mem_err:
                logger.debug(f"Failed to record command to memory: {mem_err}")

            return False, self.result(return_code == 0, output, exit_code=return_code, stdout=stdout, stderr=stderr)

        except Exception as e:
            # Auto-retry for transient network failures (npm, composer, pip)
            error_str = str(e)
            is_timeout = "TimeoutExpired" in type(e).__name__ or "timed out" in error_str.lower()
            is_network = any(kw in error_str.lower() for kw in ["econnreset", "enotfound", "etimedout", "network", "socket"])
            
            if (is_timeout or is_network) and any(pkg in cmd.lower() for pkg in ["npm", "composer", "pip", "yarn", "cargo"]):
                # One retry for package manager network failures
                try:
                    from ..ui import warn
                    warn(f"Network issue detected, retrying: {cmd[:50]}...")
                    if self._on_command_output:
                        res = self.sandbox.execute(cmd, timeout=600, on_output=self._on_command_output)
                    else:
                        from ..ui import LiveTerminalBox
                        with LiveTerminalBox(f"RETRY: {cmd}") as box:
                            res = self.sandbox.execute(cmd, timeout=600, on_output=box.append)
                    output = res.stdout + ("\n" + res.stderr if res.stderr else "")
                    if res.exit_code == 0:
                        return False, self.result(True, output, exit_code=0)
                except Exception:
                    pass
            
            # Record failed command to memory
            try:
                self.cmd_memory.record(
                    command=cmd,
                    cwd=str(cwd),
                    exit_code=-1,
                    context={"files": [], "description": f"Command failed: {str(e)}"}
                )
            except Exception:
                pass
            return False, self.result(False, str(e))

    def tool_workspace_index(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path = self.pm.resolve_target(str(action.get("path", ".")))
        goal = str(action.get("goal", ""))
        index = build_workspace_index(path, use_cache=action.get("use_cache", True))
        summary = compact_index_summary(index, goal)
        return False, self.result(True, summary, path=str(path))

    def tool_workspace_scan(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path_text = str(action.get("path", "")).strip()
        if not path_text or path_text in {".", "./"}:
            root = self.pm.resolve_workspace_only(".")
        else:
            root = self.pm.resolve_target(path_text)

        goal = str(action.get("goal", "")).strip()
        max_files = int(action.get("max_files", 12))
        max_snippets = int(action.get("max_snippets", 5))
        snippet_chars = int(action.get("snippet_chars", 1600))

        max_files = max(1, min(max_files, 40))
        max_snippets = max(0, min(max_snippets, 10))
        snippet_chars = max(200, min(snippet_chars, 6000))

        index = build_workspace_index(root, use_cache=action.get("use_cache", True))
        stack = list(index.get("stack", []))
        entry_points = list(index.get("entry_points", []))

        relevant = relevant_files(index, goal, limit=max_files) if goal else []
        snippets: list[dict[str, Any]] = []

        if goal and relevant:
            # Use RAG to get the most relevant snippets from the top candidate files
            candidate_contents = {}
            for path_str in relevant[:max_snippets * 2]: # Look at more candidates for RAG
                p = Path(path_str)
                if p.exists() and p.is_file():
                    try:
                        candidate_contents[path_str] = p.read_text(encoding="utf-8", errors="replace")
                    except: continue
            
            if candidate_contents:
                rag_snippets = self.rag.retrieve_relevant_snippets(goal, candidate_contents, top_k=max_snippets)
                for rs in rag_snippets:
                    snippets.append({
                        "path": rs["path"],
                        "preview": rs["content"],
                        "score": rs["score"]
                    })
        
        # Fallback to simple snippets if RAG failed or no goal
        if not snippets:
            for path_str in relevant[:max_snippets]:
                path = Path(path_str)
                try:
                    if not path.exists() or not path.is_file():
                        continue
                    from ..tools.file_ops import is_probably_text
                    if not is_probably_text(path):
                        continue
                    with path.open("r", encoding="utf-8", errors="replace") as handle:
                        preview = handle.read(snippet_chars).rstrip()
                    snippets.append({"path": str(path), "preview": preview})
                except Exception as exc:
                    snippets.append({"path": str(path), "error": str(exc)})

        summary_lines = [
            "Workspace scan summary",
            f"Root: {root}",
            f"Stack: {', '.join(stack) or 'unknown'}",
        ]
        if entry_points:
            summary_lines.append("Entry points:")
            summary_lines.extend(f"- {item}" for item in entry_points[:10])
        if relevant:
            summary_lines.append("Top relevant files:")
            summary_lines.extend(f"- {item}" for item in relevant[:max_files])

        if goal:
            summary_lines.append("Suggested next steps:")
            summary_lines.append("1. Review entry points and top relevant files.")
            summary_lines.append("2. Inspect snippets for key functions and data flows.")
            summary_lines.append("3. Decide smallest edit set and apply changes.")
            summary_lines.append("")
            summary_lines.append(make_task_brief(goal, project_root=str(root)))

        output = "\n".join(summary_lines).strip()
        return False, self.result(
            True,
            output,
            root=str(root),
            stack=stack,
            entry_points=entry_points,
            relevant_files=relevant,
            snippets=snippets,
        )

    def tool_list_dir(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path = self.pm.resolve_target(str(action.get("path", ".")))
        if not path.exists(): return False, self.result(False, "Directory not found")
        items = [f"{f.name}/" if f.is_dir() else f.name for f in path.iterdir()]
        return False, self.result(True, "\n".join(items), path=str(path))

    def tool_navigate(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        """Change working directory (cd). Sets PathManager target for subsequent commands."""
        raw_path = str(action.get("path", "")).strip()
        if not raw_path:
            return False, self.result(False, "No path provided")
        # Resolve symbolic names
        from pathlib import Path as _P
        symbolic_map = {
            "downloads": str(_P.home() / "Downloads"),
            "download": str(_P.home() / "Downloads"),
            "desktop": str(_P.home() / "Desktop"),
            "documents": str(_P.home() / "Documents"),
            "home": str(_P.home()),
            "~": str(_P.home()),
            "pictures": str(_P.home() / "Pictures"),
            "music": str(_P.home() / "Music"),
            "videos": str(_P.home() / "Videos"),
        }
        resolved = symbolic_map.get(raw_path.lower(), raw_path)
        path = _P(resolved).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            return False, self.result(False, f"Directory not found: {path}")
        self.pm.set_target(path)
        return True, self.result(True, f"Navigated to: {path}", path=str(path))

    def tool_make_dir(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path = self.pm.resolve_target(str(action.get("path", "")))
        existed_before = path.exists()
        success, msg = self.writer.make_dir(path)
        return False, self.result(success, msg, path=str(path), existed=existed_before)

    def tool_delete_path(self, action: dict[str, Any], ay: bool) -> tuple[bool, str]:
        path = self.pm.resolve_target(str(action.get("path", "")))
        if not path.exists():
            return False, self.result(False, f"Path not found: {path}")

        if not ay and not should_auto_approve(destructive=True):
            if not confirm(f"Permanently delete {path}?"):
                return False, self.result(False, "User cancelled deletion")

        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            ok(f"Deleted {path}")
            return False, self.result(True, f"Deleted {path}")
        except Exception as e:
            return False, self.result(False, str(e))

    def tool_move_path(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        src = self.pm.resolve_target(str(action.get("src", "")))
        dst = self.pm.resolve_target(str(action.get("dst", "")))
        if not src.exists():
            return False, self.result(False, f"Source not found: {src}")

        ok_write, reason = self.pm.validate_write_path(dst)
        if not ok_write:
            return False, self.result(False, reason)

        if not _ay and not should_auto_approve(destructive=True):
            if not confirm(f"Move {src} to {dst}? This will replace existing items."):
                return False, self.result(False, "User cancelled move")

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            ok(f"Moved {src} to {dst}")
            return False, self.result(True, f"Moved {src} to {dst}")
        except Exception as e:
            return False, self.result(False, str(e))

    def tool_copy_path(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        src = self.pm.resolve_target(str(action.get("src", "")))
        dst = self.pm.resolve_target(str(action.get("dst", "")))
        if not src.exists():
            return False, self.result(False, f"Source not found: {src}")

        ok_write, reason = self.pm.validate_write_path(dst)
        if not ok_write:
            return False, self.result(False, reason)

        if dst.exists() and not _ay and not should_auto_approve(destructive=True):
            if not confirm(f"Copy {src} to {dst}? This may overwrite existing files."):
                return False, self.result(False, "User cancelled copy")

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
            else:
                shutil.copy2(str(src), str(dst))
            ok(f"Copied {src} to {dst}")
            return False, self.result(True, f"Copied {src} to {dst}")
        except Exception as e:
            return False, self.result(False, str(e))

    def tool_batch_read_files(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        """Batch read multiple files efficiently - optimized version of read_files for bulk operations."""
        files_raw = action.get("files", [])
        files = [str(f) for f in files_raw] if isinstance(files_raw, list) else [str(files_raw)]

        if not files:
            return False, self.result(False, "No files specified for batch read")

        chunks = []
        read_paths = []
        failed_paths = []
        total_bytes = 0

        for f in files:
            exists, path, suggestions = self.pm.verify_path_exists(f)
            if not exists:
                error_msg = f"{f} (not found)"
                if suggestions:
                    error_msg += f" - Suggestions: {', '.join(suggestions[:2])}"
                failed_paths.append(error_msg)
                continue

            try:
                from ..tools.file_ops import is_probably_text
                if not is_probably_text(path):
                    failed_paths.append(f"{f} (binary or non-text)")
                    continue

                stat = path.stat()
                size = stat.st_size

                if size > _MAX_READ_BYTES:
                    with path.open("rb") as handle:
                        raw = handle.read(_MAX_READ_BYTES)
                    content = raw.decode("utf-8", errors="replace") + "\n...[truncated]"
                else:
                    content = path.read_text(encoding="utf-8", errors="replace")

                total_bytes += min(size, _MAX_READ_BYTES)
                chunks.append(f"\n--- FILE: {f} ---\n{content[:12000]}")
                read_paths.append(str(path))

            except Exception as e:
                failed_paths.append(f"{f} ({str(e)})")

        summary = f"Batch read: {len(read_paths)} succeeded, {len(failed_paths)} failed, {total_bytes} bytes"
        return False, self.result(True, "".join(chunks), read=read_paths, failed=failed_paths, summary=summary)

    def tool_batch_delete_files(self, action: dict[str, Any], ay: bool) -> tuple[bool, str]:
        """Batch delete multiple files or directories."""
        paths_raw = action.get("paths", [])
        paths = [str(p) for p in paths_raw] if isinstance(paths_raw, list) else [str(paths_raw)]

        if not paths:
            return False, self.result(False, "No paths specified for batch delete")

        deleted = []
        failed = []
        skipped = []

        for p in paths:
            target = self.pm.resolve_target(p)

            if not target.exists():
                skipped.append(f"{p} (not found)")
                continue

            ok_write, reason = self.pm.validate_write_path(target)
            if not ok_write:
                failed.append(f"{p}: {reason}")
                continue

            if not ay and not should_auto_approve(destructive=True):
                if not confirm(f"Delete {p}?"):
                    skipped.append(f"{p} (user cancelled)")
                    continue

            try:
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
                deleted.append(p)
            except Exception as e:
                failed.append(f"{p}: {str(e)}")

        all_ok = len(failed) == 0
        summary = f"Batch delete: {len(deleted)} deleted, {len(failed)} failed, {len(skipped)} skipped"
        return False, self.result(all_ok, summary, deleted=deleted, failed=failed, skipped=skipped)

    def tool_batch_copy_paths(self, action: dict[str, Any], ay: bool) -> tuple[bool, str]:
        """Batch copy multiple files or directories."""
        operations = action.get("operations", [])
        if not operations:
            return False, self.result(False, "No operations specified for batch copy")

        copied = []
        failed = []
        skipped = []

        for op in operations:
            src = self.pm.resolve_target(str(op.get("src", "")))
            dst = self.pm.resolve_target(str(op.get("dst", "")))

            if not src.exists():
                failed.append(f"{op}: Source not found")
                continue

            ok_write, reason = self.pm.validate_write_path(dst)
            if not ok_write:
                failed.append(f"{op}: {reason}")
                continue

            if dst.exists() and not ay and not should_auto_approve(destructive=True):
                if not confirm(f"Copy {src} to {dst}?"):
                    skipped.append(f"{src} -> {dst} (user cancelled)")
                    continue

            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if src.is_dir():
                    shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
                else:
                    shutil.copy2(str(src), str(dst))
                copied.append(f"{src} -> {dst}")
            except Exception as e:
                failed.append(f"{src} -> {dst}: {str(e)}")

        all_ok = len(failed) == 0
        summary = f"Batch copy: {len(copied)} copied, {len(failed)} failed, {len(skipped)} skipped"
        return False, self.result(all_ok, summary, copied=copied, failed=failed, skipped=skipped)

    def tool_batch_move_paths(self, action: dict[str, Any], ay: bool) -> tuple[bool, str]:
        """Batch move/rename multiple files or directories."""
        operations = action.get("operations", [])
        if not operations:
            return False, self.result(False, "No operations specified for batch move")

        moved = []
        failed = []
        skipped = []

        for op in operations:
            src = self.pm.resolve_target(str(op.get("src", "")))
            dst = self.pm.resolve_target(str(op.get("dst", "")))

            if not src.exists():
                failed.append(f"{op}: Source not found")
                continue

            ok_write, reason = self.pm.validate_write_path(dst)
            if not ok_write:
                failed.append(f"{op}: {reason}")
                continue

            if not ay and not should_auto_approve(destructive=True):
                if not confirm(f"Move {src} to {dst}?"):
                    skipped.append(f"{src} -> {dst} (user cancelled)")
                    continue

            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                moved.append(f"{src} -> {dst}")
            except Exception as e:
                failed.append(f"{src} -> {dst}: {str(e)}")

        all_ok = len(failed) == 0
        summary = f"Batch move: {len(moved)} moved, {len(failed)} failed, {len(skipped)} skipped"
        return False, self.result(all_ok, summary, moved=moved, failed=failed, skipped=skipped)

    def tool_search_files(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        root = self.pm.resolve_target(str(action.get("path", ".")))
        pattern = str(action.get("pattern", ""))
        include = action.get("include", "*")
        
        if not pattern:
            return False, self.result(False, "Missing search pattern")

        matches = []
        try:
            for path in root.rglob(include):
                if not path.is_file(): continue
                if any(p.startswith(".") or p in {"node_modules", "vendor", "__pycache__"} for p in path.parts): continue
                try:
                    if path.stat().st_size > _MAX_SEARCH_BYTES:
                        continue
                except OSError:
                    continue
                
                from ..tools.file_ops import is_probably_text
                if not is_probably_text(path):
                    continue
                
                try:
                    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                    for i, line in enumerate(lines, 1):
                        if re.search(pattern, line, re.IGNORECASE):
                            rel = str(path.relative_to(root))
                            matches.append(f"{rel}:{i}: {line.strip()[:120]}")
                            if len(matches) >= 50:
                                break
                except:
                    continue
                
                if len(matches) >= 50: break
            
            return False, self.result(True, "\n".join(matches) if matches else "No matches found.", count=len(matches))
        except Exception as e:
            return False, self.result(False, str(e))

    # --- Shared HTTP helper ---

    def _http_fetch(self, url: str, timeout: int = 15) -> str:
        """Fetch a URL with proper SSL, User-Agent, and proxy support."""
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ctx = ssl.create_default_context()

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        req = urllib.request.Request(url, headers=headers)
        handler = urllib.request.HTTPSHandler(context=ctx)
        opener = urllib.request.build_opener(handler)
        with opener.open(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def _extract_headers(self, html: str) -> str:
        """Extract h1-h4 headers from HTML to create a document map."""
        headers = re.findall(r'<(h[1-4])[^>]*>(.*?)</\1>', html, re.I | re.S)
        lines = []
        for tag, content in headers:
            level = int(tag[1])
            text = re.sub(r"<[^>]+>", " ", content).strip()
            if text:
                lines.append(f"{'#' * level} {text}")
        return "\n".join(lines) if lines else "No headers found."

    def _extract_ddg_url(self, raw_href: str) -> str:
        """Decode a DuckDuckGo redirect URL to the real destination."""
        raw_href = raw_href.replace("&amp;", "&")
        if raw_href.startswith("//duckduckgo.com/l/"):
            raw_href = "https:" + raw_href
        if "duckduckgo.com/l/" in raw_href:
            parsed = urllib.parse.urlparse(raw_href)
            params = urllib.parse.parse_qs(parsed.query)
            if "uddg" in params:
                return urllib.parse.unquote(params["uddg"][0])
        if raw_href.startswith("//"):
            return "https:" + raw_href
        return raw_href

    def _scrape_ddg_results(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        """Scrape DuckDuckGo HTML for search results. Returns [{title, url, snippet}]."""
        results: list[dict[str, str]] = []
        search_urls = [
            "https://duckduckgo.com/html/?q=" + urllib.parse.quote(query),
            "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote(query),
        ]

        for search_url in search_urls:
            try:
                html = self._http_fetch(search_url, timeout=12)
            except Exception:
                continue

            # DDG HTML uses class="result__a"; DDG Lite uses rel="nofollow"
            patterns = [
                r'class="result__a"[^>]+href="(.*?)"[^>]*>(.*?)</a>',
                r'<a[^>]+rel="nofollow"[^>]+href="(.*?)"[^>]*>(.*?)</a>',
            ]
            for pattern in patterns:
                for match in re.finditer(pattern, html, re.IGNORECASE | re.DOTALL):
                    raw_href = match.group(1)
                    title = re.sub(r"<[^>]+>", " ", match.group(2))
                    title = re.sub(r"\s+", " ", title).strip()
                    url = self._extract_ddg_url(raw_href)
                    if url and title and url.startswith("http"):
                        results.append({"title": title, "url": url})
                    if len(results) >= max_results:
                        break
                if results:
                    break
            if results:
                break

        # Also try to grab snippets from DDG HTML result__snippet
        if results:
            try:
                snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</[^>]+>', html, re.I | re.S)
                for i, snippet in enumerate(snippets):
                    if i < len(results):
                        clean = re.sub(r"<[^>]+>", " ", snippet)
                        clean = re.sub(r"\s+", " ", clean).strip()
                        results[i]["snippet"] = clean[:200]
            except Exception:
                pass

        return results

    def _extract_steps(self, text: str, max_steps: int = 10) -> str:
        """Extract numbered or bulleted steps from text."""
        lines = text.split('\n')
        steps = []
        for line in lines:
            line = line.strip()
            # Look for numbered steps: 1. 2. etc., or bullets: - * 
            if re.match(r'^\d+[\.\)]\s+', line) and len(line) > 10:
                steps.append(line)
            # Also look for "Step 1:" etc.
            elif re.match(r'(?i)step \d+[:\.\)]', line):
                steps.append(line)
            # Look for command/code indicators
            elif line.startswith('$ ') or line.startswith('> ') or line.startswith('npm ') or line.startswith('npx '):
                if len(line) > 5:
                    steps.append(f"`{line}`")
        if steps:
            return "\n".join(steps[:max_steps])
        return ""
    
    def _extract_code_and_lists(self, text: str, max_chars: int = 2000) -> str:
        """Extract code blocks and list items as fallback step extraction."""
        lines = text.split('\n')
        extracted = []
        in_code_block = False
        
        for line in lines:
            stripped = line.strip()
            # Detect code blocks
            if stripped.startswith('```') or stripped.startswith('~~~'):
                in_code_block = not in_code_block
                extracted.append(line)
            elif in_code_block:
                extracted.append(line)
            # Detect inline code (commands)
            elif '`' in stripped and len(stripped) > 3:
                extracted.append(stripped)
            # Detect list items
            elif re.match(r'^[\*\-\+]\s+', stripped) and len(stripped) > 5:
                extracted.append(stripped)
            # Detect numbered items
            elif re.match(r'^\d+[\.\)]\s+', stripped) and len(stripped) > 5:
                extracted.append(stripped)
        
        result = "\n".join(extracted)
        if len(result) > max_chars:
            result = result[:max_chars] + "\n... (truncated)"
        return result if result else "(No clear steps found in documentation)"

    # --- Web Search Tool ---

    def tool_web_search(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        """Focused web search. Returns best single result with detailed steps for setup queries."""
        query = str(action.get("query", "") or action.get("url", "") or action.get("content", "")).strip()
        if not query:
            return False, self.result(False, "Missing search query")

        results = []
        # Method 1: DDG library
        try:
            try:
                from ddgs import DDGS
            except Exception:
                from duckduckgo_search import DDGS

            # Get only top 3 results for focused search
            ddg_results = list(DDGS().text(query, max_results=3))
            for r in ddg_results:
                results.append({
                    "title": r.get("title", "?"),
                    "url": r.get("href", "?"),
                    "snippet": r.get("body", "")
                })
        except Exception:
            # Method 2: DDG HTML scraping fallback
            results = self._scrape_ddg_results(query, max_results=3)

        if not results:
            return False, self.result(False, f"No search results found for: {query}")

        # For setup/install queries, focus on the best result and extract detailed steps
        is_setup_query = any(word in query.lower() for word in ["setup", "install", "how to", "create", "build", "guide"])
        lines = [f"Best result for: {query}", ""]
        
        # Get the best result (usually first)
        best = results[0]
        lines.append(f"Source: {best['title']}")
        lines.append(f"URL: {best['url']}")
        if best.get("snippet"):
            lines.append(f"Summary: {best['snippet'][:300]}")
        lines.append("")
        
        # For setup queries, fetch and extract detailed steps
        if is_setup_query:
            lines.append("=" * 50)
            lines.append("STEP-BY-STEP GUIDE:")
            lines.append("=" * 50)
            try:
                html = self._http_fetch(best["url"], timeout=15)
                # Better HTML cleaning
                text = re.sub(r'<(script|style|nav|footer|header|aside|form)[^>]*>.*?</\1>', '', html, flags=re.I | re.S)
                text = re.sub(r'<[^>]+>', '\n', text)
                text = re.sub(r'\n\s*\n', '\n\n', text)
                text = re.sub(r'[ \t]+', ' ', text).strip()
                steps_content = self._extract_steps(text, max_steps=15)
                if steps_content:
                    lines.append(steps_content)
                else:
                    # Fallback: extract code blocks and numbered lists
                    lines.append(self._extract_code_and_lists(text))
            except Exception as e:
                lines.append(f"(Could not fetch detailed steps: {str(e)[:50]})")
        
        if len(results) > 1:
            lines.append("")
            lines.append("Other references:")
            for r in results[1:]:
                lines.append(f"  - {r['title']}: {r['url']}")

        return False, self.result(True, "\n".join(lines))

    # --- Index & Search Tools ---

    def tool_index_doc(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        """Manually index a local file or text for documentation search."""
        path = action.get("path")
        content = action.get("content")
        name = action.get("name", "doc")
        
        if path:
            p = Path(path)
            if p.exists():
                content = p.read_text(encoding="utf-8", errors="replace")
                name = p.name
        
        if not content:
            return False, self.result(False, "No content to index")
            
        try:
            get_indexer(self.config.workspace).add_document(name, content)
            return False, self.result(True, f"Successfully indexed '{name}'")
        except Exception as e:
            return False, self.result(False, f"Indexing failed: {str(e)}")

    def tool_search_docs(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        """Search through previously indexed documentation using a query."""
        query = action.get("query")
        if not query:
            return False, self.result(False, "Missing search query")
            
        try:
            results = get_indexer(self.config.workspace).search(query)
            if not results:
                return False, self.result(False, f"No local documentation found for: {query}")
                
            lines = [f"Local search results for: {query}", ""]
            for r in results:
                lines.append(f"Doc: {Path(r['path']).name} (Score: {r['score']})")
                lines.append(f"Content: {r['content'][:500]}...")
                lines.append("-" * 20)
                
            return False, self.result(True, "\n".join(lines))
        except Exception as e:
            return False, self.result(False, f"Search failed: {str(e)}")

    # --- URL Fetch Tool ---

    def tool_read_url(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        """Fetch and return text content from a direct URL. Supports 'mode':'map' for headers."""
        url = str(action.get("url", "") or action.get("query", "")).strip()
        mode = str(action.get("mode", "full")).lower()
        
        if not url:
            return False, self.result(False, "Missing URL")

        if not url.startswith(("http://", "https://")):
            return self.tool_web_search({"query": url}, _ay)

        try:
            html = self._http_fetch(url)
            
            if mode == "map":
                content = self._extract_headers(html)
                return False, self.result(True, content, url=url, mode="map")
            
            # Clean text but preserve some structure
            text = re.sub(r'<(script|style|nav|footer)[^>]*>.*?</\1>', '', html, flags=re.I | re.S)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            
            # Auto-index for later searching
            try:
                name = re.sub(r'\W+', '_', url)[-50:]
                get_indexer(self.config.workspace).add_document(name, text)
            except Exception:
                pass

            limit = 5000 if mode == "full" else 1500
            return False, self.result(True, text[:limit], url=url, truncated=len(text) > limit)
            
        except urllib.error.HTTPError as e:
            return False, self.result(False, f"HTTP {e.code}: {e.reason}")
        except Exception as e:
            return False, self.result(False, f"Request failed: {str(e)}")

    def tool_open_browser(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        url = str(action.get("url", ""))
        if not url.startswith(("http://", "https://")):
            # If it's not a URL, assume it's a search query
            query = urllib.parse.quote(url)
            url = f"https://www.google.com/search?q={query}"

        try:
            webbrowser.open(url)
            ok(f"Opened browser: {url}")
            return False, self.result(True, f"Opened {url} in browser")
        except Exception as e:
            return False, self.result(False, str(e))

    def tool_play_media(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        """Headless media player. Works with URLs, queries, and local files."""
        # Check multiple common keys to be robust against model variations
        url_or_query = ""
        for key in ("url", "query", "song", "name", "target", "content"):
            if key in action and action[key]:
                url_or_query = str(action[key]).strip()
                break

        if not url_or_query:
            return False, self.result(False, "Missing URL or query. Provide it via 'url' or 'query' key.")

        final_url = url_or_query
        title = "Unknown Audio"
        
        # Handle local files first
        if os.path.exists(url_or_query):
            title = os.path.basename(url_or_query)
            final_url = os.path.abspath(url_or_query)
            return self._play_audio_file(final_url, title)
        
        # Try to search/resolve using yt-dlp for URLs and queries
        if not url_or_query.startswith(("http://", "https://")):
            try:
                import yt_dlp
                
                # First try direct search for YouTube
                ydl_opts = {
                    "format": "bestaudio",
                    "quiet": True,
                    "no_warnings": True,
                    "default_search": "ytsearch1",  # Search YouTube specifically
                    "socket_timeout": 30,
                }
                
                with yt_dlp.YoutubeDL(cast(Any, ydl_opts)) as ydl:
                    info = ydl.extract_info(url_or_query, download=False)
                    
                    # Handle single video result
                    if isinstance(info, dict):
                        # If entries (from search), get first result
                        if "entries" in info and isinstance(info["entries"], list) and info["entries"]:
                            info = info["entries"][0]
                        
                        # Get best audio URL and title
                        title = info.get("title", "Unknown Title")
                        final_url = info.get("url")
                        
                        if not final_url:
                            # Fallback: try to get from formats
                            formats = info.get("formats", [])
                            for fmt in formats:
                                if fmt.get("vcodec") == "none" and fmt.get("acodec") != "none":
                                    final_url = fmt.get("url")
                                    break
                        
                        if final_url:
                            ok(f"Found: {title}")
                            return self._play_audio_file(final_url, title, original_query=url_or_query)
                        else:
                            return False, self.result(False, f"Could not extract audio URL from: {url_or_query}")
            except ImportError:
                # Auto-install yt-dlp if assume_yes is True
                if _ay:
                    ok("Installing yt-dlp...")
                    try:
                        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "yt-dlp"], 
                                     timeout=60, check=True)
                        ok("yt-dlp installed. Retrying...")
                        # Retry the import and operation
                        import yt_dlp
                        
                        ydl_opts = {
                            "format": "bestaudio",
                            "quiet": True,
                            "no_warnings": True,
                            "default_search": "ytsearch1",
                            "socket_timeout": 30,
                        }
                        
                        with yt_dlp.YoutubeDL(cast(Any, ydl_opts)) as ydl:
                            info = ydl.extract_info(url_or_query, download=False)
                            
                            if isinstance(info, dict):
                                if "entries" in info and isinstance(info["entries"], list) and info["entries"]:
                                    info = info["entries"][0]
                                
                                title = info.get("title", "Unknown Title")
                                final_url = info.get("url")
                                
                                if not final_url:
                                    formats = info.get("formats", [])
                                    for fmt in formats:
                                        if fmt.get("vcodec") == "none" and fmt.get("acodec") != "none":
                                            final_url = fmt.get("url")
                                            break
                                
                                if final_url:
                                    ok(f"Found: {title}")
                                    return self._play_audio_file(final_url, title, original_query=url_or_query)
                                else:
                                    return False, self.result(False, f"Could not extract audio URL from: {url_or_query}")
                    except subprocess.TimeoutExpired:
                        return False, self.result(False, "yt-dlp installation timed out.")
                    except subprocess.CalledProcessError:
                        return False, self.result(False, "Failed to install yt-dlp. Run 'pip install yt-dlp' manually.")
                    except Exception as e:
                        return False, self.result(False, f"Error installing yt-dlp: {e}")
                else:
                    return False, self.result(False, "yt-dlp not installed. Run 'pip install yt-dlp' to enable music playback.")
            except Exception as e:
                logger.debug(f"yt-dlp search failed: {e}")
                # Fall through to try direct URL playback
        
        # Try to play as direct URL
        if url_or_query.startswith(("http://", "https://")):
            return self._play_audio_file(url_or_query, title, original_query=url_or_query)
        
        return False, self.result(False, f"Could not resolve: {url_or_query}")

    def _play_audio_file(self, url: str, title: str, original_query: str = None) -> tuple[bool, str]:
        """Headless audio player with floating UI. Reuses existing player if possible."""
        import tempfile
        import json
        
        # If player is already running, just send a 'play' command to it
        cmd_file = Path(tempfile.gettempdir()) / "miniai_player_cmd.json"
        state_file = Path(tempfile.gettempdir()) / "miniai_player_state.json"
        
        # Check if player process is alive
        player_active = False
        if "player" in self.active_processes:
            if self.active_processes["player"].poll() is None:
                player_active = True
        elif state_file.exists():
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
                pid = state.get("pid")
                if pid:
                    os.kill(pid, 0) # Check if alive
                    player_active = True
            except: pass

        if player_active:
            try:
                with open(cmd_file, 'w') as f:
                    json.dump({"command": "play", "query": original_query or url}, f)
                ok(f"Sent play command to active player: {title}")
                return False, self.result(True, f"Now playing (reused player): {title}")
            except Exception as e:
                logger.debug(f"Failed to send command: {e}")
                # Fall back to spawning new if command fails

        # Stop any existing background player (including orphans)
        self.kill_all_processes()

        try:
            # Spawn headless audio player as subprocess
            # Use DEVNULL for stdout/stderr to prevent pipe buffer blocking
            player_proc = subprocess.Popen(
                [sys.executable, "-m", "mini_ai.tools.audio_player", str(url), title],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )
            self.active_processes["player"] = player_proc
            # Wait up to 3s for process to confirm it started (not crash immediately)
            for attempt in range(12):  # 12 * 0.25 = 3 seconds
                time.sleep(0.25)
                poll_result = player_proc.poll()
                if poll_result is not None and poll_result != 0:
                    # Process exited with error — try browser fallback
                    try:
                        webbrowser.open(url, new=2)
                        ok(f"Opened in browser: {title}")
                        return False, self.result(True, f"Opened in browser: {title}")
                    except Exception:
                        return False, self.result(False, f"Audio player failed to start (exit code {poll_result}). Check VLC is installed.")
                if poll_result is None:
                    break  # Still running — good
            
            # Spawn floating UI (watching the audio player process)
            from ..tools.floating_player import spawn_player
            spawn_player(title, player_proc.pid)
            
            ok(f"Started new player: {title}")
            return False, self.result(True, f"Started player: {title}")
        
        except subprocess.TimeoutExpired:
            return False, self.result(False, "Audio player startup timed out")
        except Exception as e:
            logger.debug(f"Audio playback error: {e}")
            return False, self.result(False, f"Playback error: {str(e)}")

    def tool_enqueue_media(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        """Add a track to the current player's queue."""
        query = action.get("query") or action.get("url")
        if not query:
            return False, self.result(False, "Missing 'query' or 'url' to enqueue.")
        
        import tempfile
        import json
        cmd_file = Path(tempfile.gettempdir()) / "miniai_player_cmd.json"
        try:
            with open(cmd_file, 'w') as f:
                json.dump({"command": "enqueue", "query": query}, f)
            ok(f"Enqueued: {query}")
            return False, self.result(True, f"Track enqueued: {query}")
        except Exception as e:
            return False, self.result(False, f"Failed to enqueue: {str(e)}")

    def tool_media_next(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        """Skip to the next track in the queue or autoplay."""
        import tempfile
        import json
        cmd_file = Path(tempfile.gettempdir()) / "miniai_player_cmd.json"
        try:
            with open(cmd_file, 'w') as f:
                json.dump({"command": "skip"}, f)
            return False, self.result(True, "Skipped to next track.")
        except Exception as e:
            return False, self.result(False, f"Skip failed: {e}")

    def tool_stop_media(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        stopped = self.kill_all_processes()
        if stopped:
            ok("Stopped audio/video playback and background processes.")
            return False, self.result(True, f"Stopped: {', '.join(stopped)}")
        return False, self.result(False, "No playback or background processes were active.")

    def tool_media_status(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        import tempfile
        import json
        state_file = Path(tempfile.gettempdir()) / "miniai_player_state.json"
        if state_file.exists():
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
                if state.get("status") in ["playing", "buffering", "paused"]:
                    title = state.get('title', 'Unknown')
                    status = state.get('status')
                    elapsed = state.get('elapsed', 0)
                    duration = state.get('duration', 0)
                    return False, self.result(True, f"Currently playing: {title}\nStatus: {status}\nElapsed: {elapsed}s / {duration}s")
            except Exception:
                pass
        return False, self.result(True, "No media is currently playing.")

    # --- New Structured Tools (Phase 2 & 3) ---

    def tool_filesystem_create_file(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path_str = action.get("path", "")
        target = self.pm.resolve_target(path_str)
        
        # Safety Check (Phase 6)
        ok_path, reason = self.pm.validate_write_path(target)
        if not ok_path:
            return False, self.result(False, f"Safety violation: {reason}")
            
        from ..tools.filesystem_tools import create_file
        res = create_file(str(target))
        
        # Verification (Phase 6)
        success = res["success"] and target.exists()
        if success:
            self.context.created_files.append(target)
        
        return False, self.result(success, res["output"])

    def tool_filesystem_create_directory(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path_str = action.get("path", "")
        target = self.pm.resolve_target(path_str)
        from ..tools.filesystem_tools import create_directory
        res = create_directory(str(target))
        
        # Verification (Phase 6)
        success = res["success"] and target.exists() and target.is_dir()
        if success:
            self.context.created_folders.append(target)
            
        return False, self.result(success, res["output"])

    def tool_git_init(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path_str = action.get("path", ".")
        target = self.pm.resolve_target(path_str)
        from ..tools.git_tools import git_init
        res = git_init(str(target))
        return False, self.result(res["success"], res["output"])

    def tool_git_add(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path_str = action.get("path", ".")
        files = action.get("files", [])
        target = self.pm.resolve_target(path_str)
        from ..tools.git_tools import git_add
        res = git_add(str(target), files)
        return False, self.result(res["success"], res["output"])

    def tool_git_commit(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path_str = action.get("path", ".")
        message = action.get("message", "AI commit")
        target = self.pm.resolve_target(path_str)
        from ..tools.git_tools import git_commit
        res = git_commit(str(target), message)
        return False, self.result(res["success"], res["output"])

    def tool_python_execute(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        code = action.get("code", "")
        # If using VenvSandbox, we can run code directly in the venv
        if isinstance(self.sandbox, VenvSandbox):
            import tempfile
            from .path_utils import ensure_ext
            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
                f.write(code)
                temp_path = f.name
            
            try:
                res = self.sandbox.execute(f"python {temp_path}")
                return False, self.result(res.success, res.output)
            finally:
                try: os.unlink(temp_path)
                except: pass
        else:
            from ..tools.python_tools import execute_python
            res = execute_python(code)
            return False, self.result(res["success"], res["output"])

    def tool_laravel_create_project(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        name = action.get("name", "my-app")
        cwd = self.pm.resolve_target(action.get("cwd", "."))
        # Use the new unified project creation with auto-dep-install
        from .dep_installer import create_project_with_deps
        success, output = create_project_with_deps("laravel", name, str(cwd))
        return False, self.result(success, output)

    def tool_laravel_install_breeze(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path = self.pm.resolve_target(action.get("path", "."))
        stack = action.get("stack", "blade")
        from ..tools.laravel_tools import install_breeze
        success, output = install_breeze(path, stack)
        return False, self.result(success, output)

    def tool_laravel_migrate(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path = self.pm.resolve_target(action.get("path", "."))
        from ..tools.laravel_tools import run_migrations
        success, output = run_migrations(path)
        return False, self.result(success, output)

    def tool_create_framework_project(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        """Create a project using any supported framework with auto-dependency installation.
        
        Supports: laravel, react, react-native, vue, next, angular, django, flask,
        fastapi, express, nestjs, svelte, astro, expo, flutter, dotnet, rails, etc.
        """
        framework = str(action.get("framework", "")).strip()
        name = str(action.get("name", "my-app")).strip()
        cwd = self.pm.resolve_target(str(action.get("cwd", ".")))
        
        if not framework:
            from .dep_installer import FRAMEWORK_CREATE_COMMANDS
            available = ", ".join(sorted(FRAMEWORK_CREATE_COMMANDS.keys()))
            return False, self.result(False, f"No framework specified. Available: {available}")
        
        from .dep_installer import create_project_with_deps
        success, output = create_project_with_deps(framework, name, str(cwd))
        return False, self.result(success, output)

    def tool_javascript_execute(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        code = action.get("code", "")
        timeout_seconds = int(action.get("timeout_seconds", 5))
        
        deno_path = self._find_deno()
        if not deno_path:
            return False, self.result(False, "Deno binary not found. Please install Deno (https://deno.land/) to run JavaScript/TypeScript snippets.")
            
        import tempfile
        # Create a temporary .ts file to support both JS and TS
        with tempfile.NamedTemporaryFile("w", suffix=".ts", delete=False, encoding="utf-8") as f:
            f.write(code)
            temp_path = f.name
            
        try:
            # Deno permission flags for maximum safety
            cmd = [
                deno_path,
                "run",
                "--allow-read=.",
                "--allow-write=.",
                "--no-prompt",
                "--deny-net",
                "--deny-env",
                "--deny-sys",
                "--deny-run",
                "--deny-ffi",
                temp_path
            ]
            
            start_time = time.perf_counter()
            proc = subprocess.run(
                cmd,
                cwd=str(self.pm.effective_root),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env={"NO_COLOR": "true"}
            )
            
            elapsed = (time.perf_counter() - start_time) * 1000
            output = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
            
            return False, self.result(proc.returncode == 0, output, duration_ms=elapsed)
            
        except subprocess.TimeoutExpired:
            return False, self.result(False, f"Execution timed out after {timeout_seconds} seconds.")
        except Exception as e:
            return False, self.result(False, f"Execution error: {str(e)}")
        finally:
            try: os.unlink(temp_path)
            except: pass

    def _find_deno(self) -> str | None:
        """Find the deno binary on the system."""
        # 1. Check if 'deno' is in PATH
        deno_in_path = shutil.which("deno")
        if deno_in_path:
            return deno_in_path
            
        # 2. Check common Windows installation path
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            common_win_path = Path(local_app_data) / "deno" / "bin" / "deno.exe"
            if common_win_path.exists():
                return str(common_win_path)
                
        # 3. Check LM Studio internal path as a fallback (if present)
        # Assuming LM Studio might be installed in default location
        user_home = Path.home()
        lms_deno = user_home / ".lmstudio" / ".internal" / "utils" / "deno.exe"
        if lms_deno.exists():
            return str(lms_deno)

        return None

    def get_command_hints_for_prompt(self, query: str) -> str:
        """Retrieve command hints to enrich the system prompt."""
        patterns = self.cmd_memory.retrieve_relevant(query, str(self.context.cwd))
        return self.cmd_memory.format_hints(patterns)

    def get_command_memory_stats(self) -> dict[str, Any]:
        """Get command memory statistics."""
        return self.cmd_memory.get_stats()

    # --- Expanded Tool Implementations (Data, System, Utility) ---

    def tool_json_query(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        file_path = str(action.get("file", ""))
        query = str(action.get("query", ""))
        resolved = self.pm.resolve_target(file_path)
        res = json_query(str(resolved), query)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_csv_query(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        file_path = str(action.get("file", ""))
        operation = str(action.get("operation", "head"))
        args = str(action.get("args", ""))
        resolved = self.pm.resolve_target(file_path)
        res = csv_query(str(resolved), operation, args)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_text_transform(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        input_text = str(action.get("input", ""))
        operation = str(action.get("operation", ""))
        pattern = str(action.get("pattern", ""))
        replacement = str(action.get("replacement", ""))
        # If input looks like a path, resolve it
        if os.path.sep in input_text or "/" in input_text:
            resolved = self.pm.resolve_target(input_text)
            if resolved.exists():
                input_text = str(resolved)
        res = text_transform(input_text, operation, pattern, replacement)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_system_info(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        query = str(action.get("query", "all"))
        res = system_info(query)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_http_request(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        method = str(action.get("method", "GET"))
        url = str(action.get("url", ""))
        headers = action.get("headers")
        body = action.get("body")
        timeout = int(action.get("timeout", 30))
        res = http_request(method, url, headers, body, timeout)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_sqlite_query(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        database = str(action.get("database", ""))
        query_str = str(action.get("query", ""))
        params = action.get("params")
        resolved = self.pm.resolve_target(database)
        res = sqlite_query(str(resolved), query_str, params)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_archive(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", ""))
        path = str(action.get("path", ""))
        files = action.get("files")
        destination = action.get("destination")
        fmt = action.get("format")
        resolved_path = str(self.pm.resolve_target(path))
        resolved_files = [str(self.pm.resolve_target(f)) for f in files] if files else None
        resolved_dest = str(self.pm.resolve_target(destination)) if destination else None
        res = archive_op(operation, resolved_path, resolved_files, resolved_dest, fmt)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_clipboard(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", ""))
        content = str(action.get("content", ""))
        res = clipboard_op(operation, content)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_env_var(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", ""))
        name = str(action.get("name", ""))
        value = str(action.get("value", ""))
        res = env_var(operation, name, value)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_process_manage(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", ""))
        target = str(action.get("target", ""))
        sig = str(action.get("signal", "term"))
        res = process_manage(operation, target, sig)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_diff_files(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        file1 = str(action.get("file1", ""))
        file2 = str(action.get("file2", ""))
        fmt = str(action.get("format", "unified"))
        resolved1 = str(self.pm.resolve_target(file1))
        resolved2 = str(self.pm.resolve_target(file2))
        res = diff_files(resolved1, resolved2, fmt)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_screenshot(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        output_path = str(action.get("output", ""))
        region = str(action.get("region", "full"))
        resolved = str(self.pm.resolve_target(output_path))
        res = screenshot(resolved, region)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_timer(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        """Simple timer - records a reminder (non-blocking)."""
        operation = str(action.get("operation", ""))
        duration = str(action.get("duration", ""))
        message = str(action.get("message", "Timer"))
        if operation == "set":
            return False, self.result(True, f"Timer set: {duration} - {message}")
        elif operation == "list":
            return False, self.result(True, "No active timers")
        return False, self.result(True, f"Timer operation: {operation}")

    def tool_file_info(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path = str(action.get("path", ""))
        detail = str(action.get("detail", "basic"))
        resolved = str(self.pm.resolve_target(path))
        res = file_info(resolved, detail)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_scaffold(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        template = str(action.get("template", ""))
        name = str(action.get("name", ""))
        options = action.get("options") or {}
        res = scaffold(template, name, options)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_calculate(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        expression = str(action.get("expression", ""))
        res = calculate(expression)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_datetime_util(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", ""))
        value = str(action.get("value", ""))
        fmt = str(action.get("format", ""))
        tz = str(action.get("timezone", ""))
        res = datetime_util(operation, value, fmt, tz)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_regex_tool(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", ""))
        pattern = str(action.get("pattern", ""))
        text = str(action.get("text", ""))
        replacement = str(action.get("replacement", ""))
        flags = str(action.get("flags", ""))
        res = regex_tool(operation, pattern, text, replacement, flags)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    # ═══════════════════════════════════════════════════════════════════════
    # EXPANDED TOOL SET WRAPPERS
    # ═══════════════════════════════════════════════════════════════════════

    def tool_git_op(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", "status"))
        args = str(action.get("args", ""))
        path = str(action.get("path", "."))
        resolved = str(self.pm.resolve_target(path))
        res = git_op(operation, args, resolved)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_docker_op(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", ""))
        target = str(action.get("target", ""))
        options = str(action.get("options", ""))
        res = docker_op(operation, target, options)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_package_op(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        manager = str(action.get("manager", ""))
        operation = str(action.get("operation", ""))
        package = str(action.get("package", ""))
        options = str(action.get("options", ""))
        res = package_op(manager, operation, package, options)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_code_analyze(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", ""))
        path = str(action.get("path", "."))
        options = str(action.get("options", ""))
        resolved = str(self.pm.resolve_target(path))
        res = code_analyze(operation, resolved, options)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_test_op(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", "run"))
        path = str(action.get("path", "."))
        framework = str(action.get("framework", ""))
        options = str(action.get("options", ""))
        resolved = str(self.pm.resolve_target(path))
        res = test_op(operation, resolved, framework, options)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_convert(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        category = str(action.get("category", ""))
        value = str(action.get("value", ""))
        from_unit = str(action.get("from_unit", ""))
        to_unit = str(action.get("to_unit", ""))
        res = convert(category, value, from_unit, to_unit)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_format_convert(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", ""))
        input_text = str(action.get("input", ""))
        options = str(action.get("options", ""))
        res = format_convert(operation, input_text, options)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_number_convert(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        value = str(action.get("value", ""))
        from_base = str(action.get("from_base", ""))
        to_base = str(action.get("to_base", ""))
        res = number_convert(value, from_base, to_base)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_net_op(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", ""))
        target = str(action.get("target", ""))
        options = str(action.get("options", ""))
        res = net_op(operation, target, options)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_project_init(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        template = str(action.get("template", ""))
        name = str(action.get("name", ""))
        path = str(action.get("path", "."))
        options = str(action.get("options", ""))
        resolved = str(self.pm.resolve_target(path))
        res = project_init(template, name, resolved, options)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_project_info(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path = str(action.get("path", "."))
        resolved = str(self.pm.resolve_target(path))
        res = project_info(resolved)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_dependency_tree(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path = str(action.get("path", "."))
        depth = int(action.get("depth", 3))
        resolved = str(self.pm.resolve_target(path))
        res = dependency_tree(resolved, depth)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_project_health(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path = str(action.get("path", "."))
        resolved = str(self.pm.resolve_target(path))
        res = project_health(resolved)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_file_op_ext(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", ""))
        path = str(action.get("path", "."))
        options = str(action.get("options", ""))
        resolved = str(self.pm.resolve_target(path))
        res = file_op_ext(operation, resolved, options)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_text_op(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", ""))
        input_text = str(action.get("input", ""))
        options = str(action.get("options", ""))
        res = text_op(operation, input_text, options)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_json_format(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        input_text = str(action.get("input", ""))
        operation = str(action.get("operation", "pretty"))
        res = json_format(input_text, operation)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_template_render(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        template = str(action.get("template", ""))
        variables = str(action.get("variables", ""))
        res = template_render(template, variables)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_markdown_op(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", ""))
        input_text = str(action.get("input", ""))
        res = markdown_op(operation, input_text)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_crypto_op(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", ""))
        input_text = str(action.get("input", ""))
        key = str(action.get("key", ""))
        algorithm = str(action.get("algorithm", "sha256"))
        res = crypto_op(operation, input_text, key, algorithm)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    # --- Assistant / Productivity Tools ---

    def tool_organize_files(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path = str(action.get("path", str(self.pm.effective_root)))
        mode = str(action.get("mode", "preview"))
        categories = str(action.get("categories", ""))
        res = organize_files(path, mode, categories)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_undo_organize(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        res = undo_organize()
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_smart_cleanup(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path = str(action.get("path", str(self.pm.effective_root)))
        mode = str(action.get("mode", "preview"))
        res = smart_cleanup(path, mode)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_file_summary(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path = str(action.get("path", str(self.pm.effective_root)))
        res = file_summary(path)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_schedule_reminder(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        message = str(action.get("message", ""))
        minutes = int(action.get("minutes", 0))
        time_str = str(action.get("time", ""))
        res = schedule_reminder(message, minutes, time_str)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_check_reminders(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        res = check_reminders()
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_quick_note(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        content = str(action.get("content", ""))
        title = str(action.get("title", ""))
        res = quick_note(content, title)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_list_notes(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        days = int(action.get("days", 7))
        res = list_notes(days)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_system_health(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        res = system_health()
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_open_app(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        name = str(action.get("name", ""))
        res = open_app(name)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_list_processes(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        sort_by = str(action.get("sort_by", "memory"))
        limit = int(action.get("limit", 15))
        res = list_procs_tool(sort_by, limit)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_kill_process(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        target = str(action.get("target", ""))
        res = kill_process(target)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_timer(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", "check_timer"))
        seconds = int(action.get("seconds", 0))
        label = str(action.get("label", ""))
        res = timer_op(operation, seconds, label)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_snippet(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", "list"))
        name = str(action.get("name", ""))
        content = str(action.get("content", ""))
        res = snippet_op(operation, name, content)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_smart_rename(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path = str(action.get("path", str(self.pm.effective_root)))
        pattern = str(action.get("pattern", ""))
        mode = str(action.get("mode", "preview"))
        res = smart_rename(path, pattern, mode)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_wifi_passwords(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        res = wifi_passwords()
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_startup_programs(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", "list"))
        res = startup_programs(operation)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_quick_calc(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        expression = str(action.get("expression", ""))
        res = quick_calc(expression)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_clipboard_history(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", "show"))
        content = str(action.get("content", ""))
        res = clipboard_history(operation, content)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    # --- Life Management Tools ---

    def tool_weather(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        location = str(action.get("location", ""))
        units = str(action.get("units", "metric"))
        res = weather(location, units)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_translate(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        text = str(action.get("text", ""))
        to_lang = str(action.get("to", action.get("to_lang", "en")))
        from_lang = str(action.get("from", action.get("from_lang", "auto")))
        res = translate(text, to_lang, from_lang)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_email_draft(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        to = str(action.get("to", ""))
        subject = str(action.get("subject", ""))
        body = str(action.get("body", ""))
        tone = str(action.get("tone", "professional"))
        res = email_draft(to, subject, body, tone)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_pomodoro(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", "status"))
        work_min = int(action.get("work_min", 25))
        break_min = int(action.get("break_min", 5))
        res = pomodoro(operation, work_min, break_min)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_habit_tracker(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", "list"))
        habit = str(action.get("habit", ""))
        note = str(action.get("note", ""))
        res = habit_tracker(operation, habit, note)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_expense_tracker(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", "summary"))
        amount = float(action.get("amount", 0))
        category = str(action.get("category", ""))
        description = str(action.get("description", ""))
        res = expense_tracker(operation, amount, category, description)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_daily_planner(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", "show"))
        task = str(action.get("task", ""))
        time_slot = str(action.get("time", ""))
        priority = str(action.get("priority", "normal"))
        res = daily_planner(operation, task, time_slot, priority)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_api_test(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        url = str(action.get("url", ""))
        method = str(action.get("method", "GET"))
        headers = str(action.get("headers", ""))
        body = str(action.get("body", ""))
        res = api_test(url, method, headers, body)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    # --- Power Tools ---

    def tool_screenshot_capture(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        save_path = str(action.get("path", ""))
        res = screenshot(save_path)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_ip_info(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        target = str(action.get("target", action.get("ip", "")))
        res = ip_info(target)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_text_to_speech(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        text = str(action.get("text", ""))
        rate = int(action.get("rate", 150))
        res = text_to_speech(text, rate)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_bookmarks(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", "list"))
        url = str(action.get("url", ""))
        title = str(action.get("title", ""))
        tags = str(action.get("tags", ""))
        res = bookmarks(operation, url, title, tags)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_motivation(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        res = motivation()
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_system_action(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        act = str(action.get("action_type", action.get("operation", "")))
        res = system_action(act)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_speed_test(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        res = speed_test()
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_text_stats(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        text = str(action.get("text", ""))
        file_path = str(action.get("file", ""))
        res = text_stats(text, file_path)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_color_convert(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        color = str(action.get("color", ""))
        res = color_convert(color)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_lorem_ipsum(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        paragraphs = int(action.get("paragraphs", 1))
        words = int(action.get("words", 0))
        res = lorem_ipsum(paragraphs, words)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    # --- Smart Tools ---

    def tool_shorten_url(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        url = str(action.get("url", ""))
        res = shorten_url(url)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_define_word(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        word = str(action.get("word", ""))
        res = define_word(word)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_timezone_convert(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        time_str = str(action.get("time", ""))
        from_tz = str(action.get("from", action.get("from_tz", "")))
        to_tz = str(action.get("to", action.get("to_tz", "")))
        res = timezone_convert(time_str, from_tz, to_tz)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_countdown(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        target = str(action.get("target", action.get("date", "")))
        res = countdown(target)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_random_generate(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        gen_type = str(action.get("type", "number"))
        count = int(action.get("count", 1))
        res = random_generate(gen_type, count, **{k: v for k, v in action.items() if k not in ("action", "type", "count")})
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_regex_test(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        pattern = str(action.get("pattern", ""))
        text = str(action.get("text", ""))
        operation = str(action.get("operation", "findall"))
        res = regex_test(pattern, text, operation)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_port_scan(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        host = str(action.get("host", "localhost"))
        ports = str(action.get("ports", "80,443,3000,3306,5432,8080,8000"))
        res = port_scan(host, ports)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_uptime_check(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        url = str(action.get("url", ""))
        res = uptime_check(url)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_git_summary(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path = str(action.get("path", str(self.pm.effective_root)))
        res = git_summary(path)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_world_clock(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        res = world_clock()
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    # --- Daily Life Tools ---

    def tool_age_calc(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        birthdate = str(action.get("birthdate", action.get("date", "")))
        res = age_calc(birthdate)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_bmi_calc(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        weight = float(action.get("weight", 0))
        height = float(action.get("height", 0))
        unit = str(action.get("unit", "metric"))
        res = bmi_calc(weight, height, unit)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_tip_calc(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        bill = float(action.get("bill", 0))
        tip_pct = float(action.get("tip", action.get("percent", 15)))
        split = int(action.get("split", 1))
        res = tip_calc(bill, tip_pct, split)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_loan_calc(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        principal = float(action.get("principal", action.get("amount", 0)))
        rate = float(action.get("rate", 0))
        years = int(action.get("years", action.get("term", 30)))
        res = loan_calc(principal, rate, years)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_water_tracker(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", "status"))
        amount = int(action.get("amount", 250))
        res = water_tracker(operation, amount)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_sleep_tracker(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", "status"))
        hours = float(action.get("hours", 0))
        quality = str(action.get("quality", ""))
        res = sleep_tracker(operation, hours, quality)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_flashcards(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", "quiz"))
        deck = str(action.get("deck", "default"))
        front = str(action.get("front", action.get("question", "")))
        back = str(action.get("back", action.get("answer", "")))
        res = flashcards(operation, deck, front, back)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_contacts(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", "list"))
        name = str(action.get("name", ""))
        phone = str(action.get("phone", ""))
        email = str(action.get("email", ""))
        note = str(action.get("note", ""))
        res = contacts(operation, name, phone, email, note)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_daily_affirmation(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        res = daily_affirmation()
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    # --- Automation Tools ---

    def tool_youtube_download(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        url = str(action.get("url", action.get("query", "")))
        output_dir = str(action.get("output_dir", action.get("output", "")))
        fmt = str(action.get("format", "mp4"))
        quality = str(action.get("quality", "best"))
        res = youtube_download(url, output_dir, fmt, quality)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_pdf_summarize(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        file_path = str(action.get("file", action.get("path", "")))
        max_pages = int(action.get("max_pages", 20))
        mode = str(action.get("mode", "summary"))
        resolved = str(self.pm.resolve_target(file_path))
        res = pdf_summarize(resolved, max_pages, mode)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_image_resize(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        file_path = str(action.get("file", action.get("path", "")))
        width = int(action.get("width", 0))
        height = int(action.get("height", 0))
        scale = float(action.get("scale", 0.0))
        output = str(action.get("output", ""))
        quality = int(action.get("quality", 85))
        resolved = str(self.pm.resolve_target(file_path))
        res = image_resize(resolved, width, height, scale, output, quality)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_auto_backup(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path = str(action.get("path", str(self.pm.effective_root)))
        destination = str(action.get("destination", ""))
        mode = str(action.get("mode", "snapshot"))
        max_backups = int(action.get("max_backups", 10))
        resolved = str(self.pm.resolve_target(path))
        res = auto_backup(resolved, destination, mode, max_backups)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_daily_digest(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path = str(action.get("path", str(self.pm.effective_root)))
        scope = str(action.get("scope", "today"))
        res = daily_digest(path, scope)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_project_stats(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path = str(action.get("path", str(self.pm.effective_root)))
        resolved = str(self.pm.resolve_target(path))
        res = project_stats(resolved)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_dependency_audit(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path = str(action.get("path", str(self.pm.effective_root)))
        fix = bool(action.get("fix", False))
        resolved = str(self.pm.resolve_target(path))
        res = dependency_audit(resolved, fix)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_docker_helper(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", ""))
        target = str(action.get("target", ""))
        options = str(action.get("options", ""))
        res = docker_helper(operation, target, options)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_auto_commit(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        path = str(action.get("path", str(self.pm.effective_root)))
        message = str(action.get("message", ""))
        mode = str(action.get("mode", "smart"))
        res = auto_commit(path, message, mode)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

    def tool_cron_scheduler(self, action: dict[str, Any], _ay: bool) -> tuple[bool, str]:
        operation = str(action.get("operation", "list"))
        name = str(action.get("name", ""))
        schedule = str(action.get("schedule", ""))
        command = str(action.get("command", ""))
        path = str(action.get("path", ""))
        res = cron_scheduler(operation, name, schedule, command, path)
        return False, self.result(res["success"], res.get("result", res.get("error", "")))

