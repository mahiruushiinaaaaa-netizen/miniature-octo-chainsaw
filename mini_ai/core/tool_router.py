"""
tool_router.py – Context-aware tool routing for task-specific tool selection.

Selects tool sets based on task classification and workspace context,
ensuring the model receives only relevant tools (max 8 per turn) to
reduce confusion and improve tool calling accuracy.

Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7
"""
from __future__ import annotations

from typing import Any

from .logger import get_logger

logger = get_logger("tool_router")

# ---------------------------------------------------------------------------
# Task-specific tool sets
# ---------------------------------------------------------------------------

TASK_TOOL_SETS: dict[str, list[str]] = {
    "code_editing": ["edit_blocks", "read_files", "run_cmd", "write_files", "search_files", "answer"],
    "exploration": [
        "read_files", "list_dir", "workspace_scan", "search_files",
        "web_search", "file_info", "answer",
    ],
    "default": [
        "read_files", "list_dir", "run_cmd", "write_files",
        "edit_blocks", "web_search", "answer",
    ],
    "data_processing": [
        "json_query", "csv_query", "text_transform", "regex_tool",
        "calculate", "read_files", "write_files", "answer",
    ],
    "system_admin": [
        "run_cmd", "system_info", "process_manage", "env_var",
        "file_info", "archive", "answer",
    ],
    "web_api": [
        "http_request", "web_search", "read_url", "run_cmd",
        "write_files", "answer",
    ],
    "database": [
        "sqlite_query", "run_cmd", "read_files", "write_files",
        "answer",
    ],
}

MAX_TOOLS_PER_TURN = 8

# ---------------------------------------------------------------------------
# Framework detection → additional tools mapping
# ---------------------------------------------------------------------------

FRAMEWORK_TOOLS: dict[str, list[str]] = {
    "Laravel/PHP": ["laravel_create_project", "run_cmd", "git_init"],
    "Django/Python": ["python_execute", "run_cmd", "git_init"],
    "Node/Web": ["javascript_execute", "run_cmd", "git_init"],
    "Vite": ["javascript_execute", "run_cmd"],
    "Python": ["python_execute", "run_cmd", "git_init"],
    "Rust": ["run_cmd", "git_init"],
    "Go": ["run_cmd", "git_init"],
    "Docker": ["run_cmd", "system_info"],
    "Database": ["sqlite_query", "run_cmd"],
}

# ---------------------------------------------------------------------------
# Tool equivalence map for suggest_alternative()
# ---------------------------------------------------------------------------

TOOL_EQUIVALENCES: dict[str, list[str]] = {
    "write_files": ["edit_blocks"],
    "edit_blocks": ["write_files"],
    "list_dir": ["workspace_scan", "workspace_map"],
    "workspace_scan": ["list_dir", "workspace_map"],
    "workspace_map": ["list_dir", "workspace_scan"],
    "search_files": ["workspace_scan", "read_files", "regex_tool"],
    "web_search": ["read_url", "http_request"],
    "read_url": ["web_search", "http_request"],
    "run_cmd": ["python_execute", "javascript_execute"],
    "python_execute": ["run_cmd"],
    "javascript_execute": ["run_cmd"],
    "git_init": ["run_cmd"],
    "laravel_create_project": ["run_cmd"],
    "batch_read_files": ["read_files"],
    "read_files": ["batch_read_files"],
    "make_dir": ["run_cmd"],
    "delete_path": ["run_cmd"],
    "move_path": ["run_cmd"],
    "copy_path": ["run_cmd"],
    "json_query": ["python_execute", "run_cmd"],
    "csv_query": ["python_execute", "run_cmd"],
    "text_transform": ["regex_tool", "python_execute"],
    "regex_tool": ["text_transform", "search_files"],
    "calculate": ["python_execute"],
    "datetime_util": ["python_execute", "run_cmd"],
    "system_info": ["run_cmd"],
    "http_request": ["read_url", "web_search", "run_cmd"],
    "sqlite_query": ["run_cmd", "python_execute"],
    "archive": ["run_cmd"],
    "clipboard": ["run_cmd"],
    "env_var": ["run_cmd"],
    "process_manage": ["run_cmd"],
    "diff_files": ["run_cmd"],
    "screenshot": ["run_cmd"],
    "file_info": ["list_dir", "run_cmd"],
    "scaffold": ["write_files"],
    "timer": ["run_cmd"],
}


# ---------------------------------------------------------------------------
# ToolRouter
# ---------------------------------------------------------------------------


class ToolRouter:
    """Selects tool sets based on task classification and workspace context.

    Uses workspace index stack detection to add framework-specific tools,
    and enforces a maximum of MAX_TOOLS_PER_TURN tools per generation turn.

    Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7
    """

    def __init__(self, workspace_index: dict[str, Any], capabilities: dict[str, Any] | None = None):
        """Initialize the tool router.

        Args:
            workspace_index: The workspace index dict (from build_workspace_index).
            capabilities: Optional dict of system capabilities/features enabled.
        """
        self._index = workspace_index
        self._capabilities = capabilities or {}

    def route(self, task_type: str, goal: str = "") -> list[str]:
        """Return filtered tool list (max 8) for the given task type.

        Selects the base tool set from TASK_TOOL_SETS, adds framework-specific
        tools detected from the workspace, and caps at MAX_TOOLS_PER_TURN.

        Args:
            task_type: One of "code_editing", "exploration", or "default".
            goal: Optional goal string for context-aware routing.

        Returns:
            List of tool names, guaranteed to have at most MAX_TOOLS_PER_TURN items
            and always including "answer".

        Requirements: 11.1, 11.2, 11.4, 11.7
        """
        # Get base tool set for the task type, fall back to default
        base_tools = list(TASK_TOOL_SETS.get(task_type, TASK_TOOL_SETS["default"]))

        # Add framework-specific tools
        framework_tools = self._detect_framework_tools()
        for tool in framework_tools:
            if tool not in base_tools:
                base_tools.append(tool)

        # Add goal-based tools if relevant keywords detected
        goal_tools = self._detect_goal_tools(goal)
        for tool in goal_tools:
            if tool not in base_tools:
                base_tools.append(tool)

        # Ensure "answer" is always present
        if "answer" not in base_tools:
            base_tools.append("answer")

        # Cap at MAX_TOOLS_PER_TURN, keeping "answer" guaranteed
        if len(base_tools) > MAX_TOOLS_PER_TURN:
            # Remove "answer" temporarily, truncate, then re-add
            base_tools = [t for t in base_tools if t != "answer"]
            base_tools = base_tools[: MAX_TOOLS_PER_TURN - 1]
            base_tools.append("answer")

        return base_tools

    def _detect_framework_tools(self) -> list[str]:
        """Add framework-specific tools based on workspace stack detection.

        Reads the "stack" field from the workspace index and maps detected
        frameworks to their corresponding tools.

        Returns:
            List of additional tool names for detected frameworks.

        Requirements: 11.3
        """
        detected_stack: list[str] = self._index.get("stack", [])
        additional_tools: list[str] = []

        for framework in detected_stack:
            framework_specific = FRAMEWORK_TOOLS.get(framework, [])
            for tool in framework_specific:
                if tool not in additional_tools:
                    additional_tools.append(tool)

        return additional_tools

    def suggest_alternative(self, requested_tool: str, available: list[str]) -> str | None:
        """Find equivalent tool in available set for an unavailable tool request.

        Uses the TOOL_EQUIVALENCES mapping to find a suitable replacement
        that exists in the current available tool set.

        Args:
            requested_tool: The tool name that was requested but is unavailable.
            available: The list of currently available tools.

        Returns:
            The name of an equivalent available tool, or None if no alternative exists.

        Requirements: 11.5
        """
        equivalences = TOOL_EQUIVALENCES.get(requested_tool, [])
        for candidate in equivalences:
            if candidate in available:
                return candidate
        return None

    def handle_unavailable_tool(self, requested_tool: str, available: list[str]) -> str:
        """Return an error message when a requested tool is not in the current set.

        If an equivalent tool exists in the available set, names it.
        Otherwise, lists all currently available tools.

        Args:
            requested_tool: The tool name that was requested.
            available: The list of currently available tools.

        Returns:
            Error message string with guidance on alternatives.

        Requirements: 11.5, 11.6
        """
        alternative = self.suggest_alternative(requested_tool, available)

        if alternative:
            return (
                f"Tool '{requested_tool}' is not available in the current tool set. "
                f"Use '{alternative}' instead for the same action."
            )

        available_str = ", ".join(available)
        return (
            f"Tool '{requested_tool}' is not available in the current tool set. "
            f"Available tools: {available_str}"
        )

    def _detect_goal_tools(self, goal: str) -> list[str]:
        """Detect additional tools based on goal keywords.

        Args:
            goal: The current task goal string.

        Returns:
            List of additional tool names relevant to the goal.
        """
        if not goal:
            return []

        goal_lower = goal.lower()
        additional: list[str] = []

        # Web-related goals
        if any(kw in goal_lower for kw in ("search", "find online", "look up", "google")):
            additional.append("web_search")

        # Git-related goals
        if any(kw in goal_lower for kw in ("git", "commit", "repository", "repo init")):
            additional.append("git_init")

        # Laravel-related goals
        if any(kw in goal_lower for kw in ("laravel", "artisan", "breeze")):
            additional.append("laravel_create_project")

        # File search goals
        if any(kw in goal_lower for kw in ("find file", "search for", "grep", "locate")):
            additional.append("search_files")

        # Data processing goals
        if any(kw in goal_lower for kw in ("json", "parse json", "query json", "extract data")):
            additional.append("json_query")
        if any(kw in goal_lower for kw in ("csv", "spreadsheet", "tabular", "data analysis")):
            additional.append("csv_query")
        if any(kw in goal_lower for kw in ("regex", "pattern", "replace text", "transform")):
            additional.append("regex_tool")

        # Math/calculation goals
        if any(kw in goal_lower for kw in ("calculate", "math", "compute", "formula", "convert")):
            additional.append("calculate")

        # Date/time goals
        if any(kw in goal_lower for kw in ("date", "time", "timestamp", "timezone", "schedule")):
            additional.append("datetime_util")

        # System/admin goals
        if any(kw in goal_lower for kw in ("system info", "cpu", "memory", "disk space", "processes")):
            additional.append("system_info")
        if any(kw in goal_lower for kw in ("kill process", "stop process", "background")):
            additional.append("process_manage")

        # API/HTTP goals
        if any(kw in goal_lower for kw in ("api", "http", "request", "endpoint", "fetch", "post", "rest")):
            additional.append("http_request")

        # Database goals
        if any(kw in goal_lower for kw in ("database", "sqlite", "sql", "query", "table")):
            additional.append("sqlite_query")

        # Archive goals
        if any(kw in goal_lower for kw in ("zip", "archive", "compress", "extract", "tar", "unzip")):
            additional.append("archive")

        # Clipboard goals
        if any(kw in goal_lower for kw in ("clipboard", "copy", "paste")):
            additional.append("clipboard")

        # Screenshot goals
        if any(kw in goal_lower for kw in ("screenshot", "capture screen", "screen grab")):
            additional.append("screenshot")

        # Scaffold/template goals
        if any(kw in goal_lower for kw in ("scaffold", "template", "boilerplate", "generate", "starter")):
            additional.append("scaffold")

        # Diff/compare goals
        if any(kw in goal_lower for kw in ("diff", "compare", "difference")):
            additional.append("diff_files")

        # Environment variable goals
        if any(kw in goal_lower for kw in ("env var", "environment variable", "set variable")):
            additional.append("env_var")

        # File info goals
        if any(kw in goal_lower for kw in ("file size", "file info", "metadata", "hash", "checksum")):
            additional.append("file_info")

        # Timer goals
        if any(kw in goal_lower for kw in ("timer", "remind", "alarm", "countdown")):
            additional.append("timer")

        return additional
