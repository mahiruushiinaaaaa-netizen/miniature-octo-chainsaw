"""
schemas.py – Tool schemas with validation for reliable tool calling.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ParamType = Literal["string", "list", "dict", "int", "bool", "number"]


@dataclass
class ParamSchema:
    name: str
    type: ParamType
    required: bool = True
    description: str = ""
    items_type: ParamType | None = None


@dataclass
class ToolSchema:
    name: str
    params: list[ParamSchema]
    description: str = ""

    def validate(self, args: dict[str, Any]) -> tuple[bool, str]:
        for param in self.params:
            value = args.get(param.name)
            if value is None:
                if param.required:
                    return False, f"Missing required parameter '{param.name}'"
                continue

            if not self._validate_type(value, param.type, param.items_type):
                return (
                    False,
                    f"Parameter '{param.name}' has type {type(value).__name__}, expected {param.type}",
                )

        return True, ""

    @staticmethod
    def _validate_type(value: Any, expected: ParamType, items_type: ParamType | None = None) -> bool:
        type_map = {
            "string": str,
            "int": int,
            "bool": bool,
            "number": (int, float),
            "list": list,
            "dict": dict,
        }
        expected_class = type_map.get(expected)
        if not isinstance(value, expected_class):
            return False
        if expected == "list" and items_type and value:
            item_class = type_map.get(items_type)
            if item_class and not all(isinstance(item, item_class) for item in value):
                return False
        return True


TOOL_SCHEMAS = {
    "answer": ToolSchema(
        name="answer",
        params=[ParamSchema(name="content", type="string", description="Final response text")],
    ),
    "read_files": ToolSchema(
        name="read_files",
        params=[
            ParamSchema(
                name="files",
                type="list",
                items_type="string",
                description="List of file paths to read",
            )
        ],
    ),
    "write_files": ToolSchema(
        name="write_files",
        params=[
            ParamSchema(
                name="files",
                type="list",
                description="List of {path, content} dicts to write",
            )
        ],
    ),
    "delete_path": ToolSchema(
        name="delete_path",
        params=[ParamSchema(name="path", type="string", description="Path to delete")],
    ),
    "move_path": ToolSchema(
        name="move_path",
        params=[
            ParamSchema(name="src", type="string", description="Source path"),
            ParamSchema(name="dst", type="string", description="Destination path"),
        ],
    ),
    "copy_path": ToolSchema(
        name="copy_path",
        params=[
            ParamSchema(name="src", type="string", description="Source path"),
            ParamSchema(name="dst", type="string", description="Destination path"),
        ],
    ),
    "search_files": ToolSchema(
        name="search_files",
        params=[
            ParamSchema(name="path", type="string", description="Root path to search"),
            ParamSchema(name="pattern", type="string", description="Regex pattern"),
            ParamSchema(name="include", type="string", required=False, description="File glob"),
        ],
    ),
    "list_dir": ToolSchema(
        name="list_dir",
        params=[ParamSchema(name="path", type="string", description="Directory path")],
    ),
    "navigate": ToolSchema(
        name="navigate",
        params=[ParamSchema(name="path", type="string", description="Directory path to navigate/cd to")],
    ),
    "make_dir": ToolSchema(
        name="make_dir",
        params=[ParamSchema(name="path", type="string", description="Directory path to create")],
    ),
    "workspace_map": ToolSchema(
        name="workspace_map",
        params=[
            ParamSchema(name="path", type="string", description="Root path"),
            ParamSchema(name="max_depth", type="int", required=False, description="Max depth"),
        ],
    ),
    "workspace_index": ToolSchema(
        name="workspace_index",
        params=[
            ParamSchema(name="path", type="string", description="Root path"),
            ParamSchema(name="goal", type="string", description="Task goal"),
        ],
    ),
    "workspace_scan": ToolSchema(
        name="workspace_scan",
        params=[
            ParamSchema(name="path", type="string", description="Root path"),
            ParamSchema(name="goal", type="string", description="Task goal"),
            ParamSchema(name="max_files", type="int", required=False),
            ParamSchema(name="max_snippets", type="int", required=False),
        ],
    ),
    "run_cmd": ToolSchema(
        name="run_cmd",
        params=[
            ParamSchema(name="command", type="string", description="Shell command to run"),
            ParamSchema(name="cwd", type="string", required=False, description="Working directory"),
        ],
    ),
    "web_search": ToolSchema(
        name="web_search",
        params=[ParamSchema(name="query", type="string", description="Search query")],
    ),
    "read_url": ToolSchema(
        name="read_url",
        params=[ParamSchema(name="url", type="string", description="URL to fetch")],
    ),
    "open_browser": ToolSchema(
        name="open_browser",
        params=[ParamSchema(name="url", type="string", description="URL to open")],
    ),
    "play_media": ToolSchema(
        name="play_media",
        params=[ParamSchema(name="query", type="string", description="Song/media query")],
    ),
    "stop_media": ToolSchema(
        name="stop_media",
        params=[],
    ),
    "media_status": ToolSchema(
        name="media_status",
        params=[],
        description="Check what media or song is currently playing",
    ),
    "enqueue_media": ToolSchema(
        name="enqueue_media",
        params=[ParamSchema(name="query", type="string", description="Song/media query to add to queue")],
    ),
    "media_next": ToolSchema(
        name="media_next",
        params=[],
        description="Skip to the next song in the queue",
    ),
    "python_execute": ToolSchema(
        name="python_execute",
        params=[ParamSchema(name="code", type="string", description="Python code to run")],
        description="Execute a Python code snippet in the current sandbox",
    ),
    "javascript_execute": ToolSchema(
        name="javascript_execute",
        params=[
            ParamSchema(name="code", type="string", description="JS/TS code to run"),
            ParamSchema(name="timeout_seconds", type="int", required=False, description="Execution timeout"),
        ],
        description="Execute a JavaScript or TypeScript code snippet using Deno",
    ),
    "batch_read_files": ToolSchema(
        name="batch_read_files",
        params=[
            ParamSchema(
                name="files",
                type="list",
                items_type="string",
                description="List of file paths to read in a single operation",
            )
        ],
        description="Read multiple files in a single batch operation for efficiency",
    ),
    "batch_delete_files": ToolSchema(
        name="batch_delete_files",
        params=[
            ParamSchema(
                name="paths",
                type="list",
                items_type="string",
                description="List of file/directory paths to delete",
            )
        ],
        description="Delete multiple files or directories in a single batch operation",
    ),
    "batch_copy_paths": ToolSchema(
        name="batch_copy_paths",
        params=[
            ParamSchema(
                name="operations",
                type="list",
                description="List of {src, dst} dicts specifying copy operations",
            )
        ],
        description="Copy multiple files or directories in a single batch operation",
    ),
    "batch_move_paths": ToolSchema(
        name="batch_move_paths",
        params=[
            ParamSchema(
                name="operations",
                type="list",
                description="List of {src, dst} dicts specifying move/rename operations",
            )
        ],
        description="Move/rename multiple files or directories in a single batch operation",
    ),
    "batch_write_files": ToolSchema(
        name="batch_write_files",
        params=[
            ParamSchema(
                name="files",
                type="list",
                description="List of {path, content} dicts to write concurrently",
            )
        ],
        description="Write multiple files concurrently in a single batch operation",
    ),
    # --- Data Processing Tools ---
    "json_query": ToolSchema(
        name="json_query",
        params=[
            ParamSchema(name="file", type="string", description="Path to JSON file"),
            ParamSchema(name="query", type="string", description="JMESPath-style query expression (e.g. 'data[0].name', 'keys(@)', 'length(items)')"),
        ],
        description="Query and extract data from JSON files using path expressions",
    ),
    "csv_query": ToolSchema(
        name="csv_query",
        params=[
            ParamSchema(name="file", type="string", description="Path to CSV file"),
            ParamSchema(name="operation", type="string", description="Operation: 'head', 'tail', 'filter', 'sort', 'count', 'columns', 'stats'"),
            ParamSchema(name="args", type="string", required=False, description="Operation arguments (e.g. column name, filter expression)"),
        ],
        description="Query and analyze CSV files (head/tail/filter/sort/count/stats)",
    ),
    "text_transform": ToolSchema(
        name="text_transform",
        params=[
            ParamSchema(name="input", type="string", description="Input text or file path"),
            ParamSchema(name="operation", type="string", description="Operation: 'regex_replace', 'extract', 'split', 'join', 'template', 'base64_encode', 'base64_decode', 'url_encode', 'url_decode', 'hash'"),
            ParamSchema(name="pattern", type="string", required=False, description="Regex pattern or template string"),
            ParamSchema(name="replacement", type="string", required=False, description="Replacement string"),
        ],
        description="Transform text with regex, encoding, hashing, and templating operations",
    ),
    # --- System Information Tools ---
    "system_info": ToolSchema(
        name="system_info",
        params=[
            ParamSchema(name="query", type="string", description="What to check: 'all', 'cpu', 'memory', 'disk', 'network', 'processes', 'env', 'ports'"),
        ],
        description="Get system information (CPU, memory, disk, network, processes, environment variables, open ports)",
    ),
    # --- HTTP/API Tools ---
    "http_request": ToolSchema(
        name="http_request",
        params=[
            ParamSchema(name="method", type="string", description="HTTP method: GET, POST, PUT, PATCH, DELETE, HEAD"),
            ParamSchema(name="url", type="string", description="Full URL to request"),
            ParamSchema(name="headers", type="dict", required=False, description="Request headers dict"),
            ParamSchema(name="body", type="string", required=False, description="Request body (JSON string for POST/PUT/PATCH)"),
            ParamSchema(name="timeout", type="int", required=False, description="Timeout in seconds (default 30)"),
        ],
        description="Make HTTP requests to APIs (GET/POST/PUT/PATCH/DELETE) with custom headers and body",
    ),
    # --- Database Tools ---
    "sqlite_query": ToolSchema(
        name="sqlite_query",
        params=[
            ParamSchema(name="database", type="string", description="Path to SQLite database file"),
            ParamSchema(name="query", type="string", description="SQL query to execute"),
            ParamSchema(name="params", type="list", required=False, description="Query parameters for parameterized queries"),
        ],
        description="Execute SQL queries on SQLite databases (SELECT, INSERT, UPDATE, DELETE, CREATE TABLE)",
    ),
    # --- Archive Tools ---
    "archive": ToolSchema(
        name="archive",
        params=[
            ParamSchema(name="operation", type="string", description="Operation: 'create', 'extract', 'list'"),
            ParamSchema(name="path", type="string", description="Archive file path"),
            ParamSchema(name="files", type="list", required=False, description="Files to include (for create)"),
            ParamSchema(name="destination", type="string", required=False, description="Extraction destination"),
            ParamSchema(name="format", type="string", required=False, description="Archive format: 'zip', 'tar', 'tar.gz', 'tar.bz2' (default: auto-detect)"),
        ],
        description="Create, extract, or list archive contents (zip, tar, tar.gz, tar.bz2)",
    ),
    # --- Clipboard Tool ---
    "clipboard": ToolSchema(
        name="clipboard",
        params=[
            ParamSchema(name="operation", type="string", description="Operation: 'copy' or 'paste'"),
            ParamSchema(name="content", type="string", required=False, description="Content to copy (required for 'copy')"),
        ],
        description="Copy text to or paste text from the system clipboard",
    ),
    # --- Environment Variable Tool ---
    "env_var": ToolSchema(
        name="env_var",
        params=[
            ParamSchema(name="operation", type="string", description="Operation: 'get', 'set', 'list', 'unset'"),
            ParamSchema(name="name", type="string", required=False, description="Variable name"),
            ParamSchema(name="value", type="string", required=False, description="Variable value (for 'set')"),
        ],
        description="Manage environment variables (get/set/list/unset) for the current session",
    ),
    # --- Process Management Tool ---
    "process_manage": ToolSchema(
        name="process_manage",
        params=[
            ParamSchema(name="operation", type="string", description="Operation: 'list', 'kill', 'start_bg', 'status'"),
            ParamSchema(name="target", type="string", required=False, description="Process name, PID, or command to start"),
            ParamSchema(name="signal", type="string", required=False, description="Signal for kill: 'term', 'kill', 'int' (default: term)"),
        ],
        description="Manage system processes (list, kill, start background, check status)",
    ),
    # --- Diff/Patch Tool ---
    "diff_files": ToolSchema(
        name="diff_files",
        params=[
            ParamSchema(name="file1", type="string", description="First file path"),
            ParamSchema(name="file2", type="string", description="Second file path"),
            ParamSchema(name="format", type="string", required=False, description="Output format: 'unified', 'context', 'summary' (default: unified)"),
        ],
        description="Compare two files and show differences",
    ),
    # --- Screenshot Tool ---
    "screenshot": ToolSchema(
        name="screenshot",
        params=[
            ParamSchema(name="output", type="string", description="Output file path for the screenshot"),
            ParamSchema(name="region", type="string", required=False, description="Region: 'full', 'window', or 'x,y,w,h' coordinates"),
        ],
        description="Take a screenshot of the screen or a specific region",
    ),
    # --- Scheduler/Timer Tool ---
    "timer": ToolSchema(
        name="timer",
        params=[
            ParamSchema(name="operation", type="string", description="Operation: 'set', 'list', 'cancel'"),
            ParamSchema(name="duration", type="string", required=False, description="Duration (e.g. '5m', '1h', '30s')"),
            ParamSchema(name="message", type="string", required=False, description="Reminder message"),
            ParamSchema(name="id", type="string", required=False, description="Timer ID (for cancel)"),
        ],
        description="Set timers and reminders",
    ),
    # --- File Metadata Tool ---
    "file_info": ToolSchema(
        name="file_info",
        params=[
            ParamSchema(name="path", type="string", description="File or directory path"),
            ParamSchema(name="detail", type="string", required=False, description="Detail level: 'basic', 'full', 'hash' (default: basic)"),
        ],
        description="Get detailed file metadata (size, dates, permissions, hash, MIME type)",
    ),
    # --- Template/Scaffold Tool ---
    "scaffold": ToolSchema(
        name="scaffold",
        params=[
            ParamSchema(name="template", type="string", description="Template type: 'api_endpoint', 'react_component', 'python_class', 'test_file', 'dockerfile', 'github_action', 'readme', 'gitignore', 'env_file'"),
            ParamSchema(name="name", type="string", description="Name for the generated item"),
            ParamSchema(name="options", type="dict", required=False, description="Template-specific options"),
        ],
        description="Generate code scaffolds and boilerplate from templates",
    ),
    # --- Math/Calculation Tool ---
    "calculate": ToolSchema(
        name="calculate",
        params=[
            ParamSchema(name="expression", type="string", description="Mathematical expression to evaluate (Python syntax)"),
        ],
        description="Evaluate mathematical expressions safely (supports arithmetic, trig, log, statistics)",
    ),
    # --- Date/Time Tool ---
    "datetime_util": ToolSchema(
        name="datetime_util",
        params=[
            ParamSchema(name="operation", type="string", description="Operation: 'now', 'format', 'parse', 'diff', 'add', 'timezone'"),
            ParamSchema(name="value", type="string", required=False, description="Date/time value or expression"),
            ParamSchema(name="format", type="string", required=False, description="Date format string"),
            ParamSchema(name="timezone", type="string", required=False, description="Timezone name (e.g. 'UTC', 'US/Eastern')"),
        ],
        description="Date/time operations (current time, formatting, parsing, differences, timezone conversion)",
    ),
    # --- Regex Tool ---
    "regex_tool": ToolSchema(
        name="regex_tool",
        params=[
            ParamSchema(name="operation", type="string", description="Operation: 'match', 'findall', 'replace', 'split', 'test', 'explain'"),
            ParamSchema(name="pattern", type="string", description="Regular expression pattern"),
            ParamSchema(name="text", type="string", required=False, description="Text to apply regex on"),
            ParamSchema(name="replacement", type="string", required=False, description="Replacement string (for 'replace')"),
            ParamSchema(name="flags", type="string", required=False, description="Regex flags: 'i' (ignore case), 'm' (multiline), 's' (dotall)"),
        ],
        description="Regex operations (match, findall, replace, split, test, explain pattern)",
    ),
    # ═══════════════════════════════════════════════════════════════════════
    # EXPANDED TOOL SET (tool-expansion spec)
    # ═══════════════════════════════════════════════════════════════════════
    "git_op": ToolSchema(
        name="git_op",
        params=[
            ParamSchema(name="operation", type="string", description="Operation: status|branch|stash|log|blame|cherry_pick|rebase|tag|remote|diff_staged|merge|reset"),
            ParamSchema(name="args", type="string", required=False, description="Operation arguments"),
            ParamSchema(name="path", type="string", required=False, description="Repository path"),
        ],
        description="Advanced git operations (branch, stash, log, blame, cherry-pick, rebase, tag, remote, merge, reset)",
    ),
    "docker_op": ToolSchema(
        name="docker_op",
        params=[
            ParamSchema(name="operation", type="string", description="Operation: ps|images|run|stop|rm|logs|build|compose_up|compose_down|exec|pull|inspect"),
            ParamSchema(name="target", type="string", required=False, description="Container/image name or ID"),
            ParamSchema(name="options", type="string", required=False, description="Additional flags"),
        ],
        description="Docker container and image management",
    ),
    "package_op": ToolSchema(
        name="package_op",
        params=[
            ParamSchema(name="manager", type="string", description="Package manager: npm|pip|cargo|composer|go|yarn|pnpm"),
            ParamSchema(name="operation", type="string", description="Operation: install|uninstall|list|outdated|update|search|init"),
            ParamSchema(name="package", type="string", required=False, description="Package name"),
            ParamSchema(name="options", type="string", required=False, description="Additional flags"),
        ],
        description="Package manager operations (npm, pip, cargo, composer, go, yarn, pnpm)",
    ),
    "code_analyze": ToolSchema(
        name="code_analyze",
        params=[
            ParamSchema(name="operation", type="string", description="Operation: complexity|dead_code|dependencies|metrics|imports|todos|lint|format_check"),
            ParamSchema(name="path", type="string", description="File or directory path"),
            ParamSchema(name="options", type="string", required=False, description="Operation-specific options"),
        ],
        description="Code analysis (complexity, dead code, metrics, TODOs, lint, imports)",
    ),
    "test_op": ToolSchema(
        name="test_op",
        params=[
            ParamSchema(name="operation", type="string", description="Operation: run|coverage|list|failed"),
            ParamSchema(name="path", type="string", required=False, description="Project root path"),
            ParamSchema(name="framework", type="string", required=False, description="Force framework: pytest|jest|vitest|phpunit|cargo|go|mocha"),
            ParamSchema(name="options", type="string", required=False, description="Extra flags"),
        ],
        description="Run tests, coverage, list test files (auto-detects framework)",
    ),
    "convert": ToolSchema(
        name="convert",
        params=[
            ParamSchema(name="category", type="string", description="Category: length|weight|temperature|speed|data_size|time|area|volume"),
            ParamSchema(name="value", type="string", description="Numeric value to convert"),
            ParamSchema(name="from_unit", type="string", description="Source unit"),
            ParamSchema(name="to_unit", type="string", description="Target unit"),
        ],
        description="Unit conversion (length, weight, temperature, speed, data size, time, area, volume)",
    ),
    "format_convert": ToolSchema(
        name="format_convert",
        params=[
            ParamSchema(name="operation", type="string", description="Operation: json_to_yaml|yaml_to_json|csv_to_json|json_to_csv|markdown_to_html|toml_to_json"),
            ParamSchema(name="input", type="string", description="Input text to convert"),
            ParamSchema(name="options", type="string", required=False, description="Conversion options"),
        ],
        description="Convert between data formats (JSON, YAML, CSV, TOML, Markdown, HTML)",
    ),
    "number_convert": ToolSchema(
        name="number_convert",
        params=[
            ParamSchema(name="value", type="string", description="Number to convert"),
            ParamSchema(name="from_base", type="string", description="Source base: bin|oct|dec|hex"),
            ParamSchema(name="to_base", type="string", description="Target base: bin|oct|dec|hex"),
        ],
        description="Number base conversion (binary, octal, decimal, hexadecimal)",
    ),
    "net_op": ToolSchema(
        name="net_op",
        params=[
            ParamSchema(name="operation", type="string", description="Operation: ping|dns|port_check|download|whois|traceroute|local_ip|port_scan"),
            ParamSchema(name="target", type="string", description="Host, URL, or host:port"),
            ParamSchema(name="options", type="string", required=False, description="Operation options"),
        ],
        description="Network diagnostics (ping, DNS, port check, download, whois, traceroute, port scan)",
    ),
    "project_init": ToolSchema(
        name="project_init",
        params=[
            ParamSchema(name="template", type="string", description="Template: python_package|node_app|flask_app|fastapi_app|express_app|cli_tool|library"),
            ParamSchema(name="name", type="string", description="Project name"),
            ParamSchema(name="path", type="string", required=False, description="Parent directory"),
            ParamSchema(name="options", type="string", required=False, description="Template options"),
        ],
        description="Initialize a new project from template",
    ),
    "project_info": ToolSchema(
        name="project_info",
        params=[
            ParamSchema(name="path", type="string", required=False, description="Project root path (default: current dir)"),
        ],
        description="Analyze project structure (language, framework, dependencies, entry points)",
    ),
    "dependency_tree": ToolSchema(
        name="dependency_tree",
        params=[
            ParamSchema(name="path", type="string", required=False, description="Project root path"),
            ParamSchema(name="depth", type="int", required=False, description="Max depth (default 3)"),
        ],
        description="Show project dependency tree",
    ),
    "project_health": ToolSchema(
        name="project_health",
        params=[
            ParamSchema(name="path", type="string", required=False, description="Project root path"),
        ],
        description="Check project health (README, tests, gitignore, license, lock file)",
    ),
    "file_op_ext": ToolSchema(
        name="file_op_ext",
        params=[
            ParamSchema(name="operation", type="string", description="Operation: find_duplicates|bulk_rename|tree|disk_usage|find_large|compare_dirs"),
            ParamSchema(name="path", type="string", description="Target path"),
            ParamSchema(name="options", type="string", required=False, description="Operation options"),
        ],
        description="Advanced file operations (duplicates, bulk rename, tree, disk usage, compare dirs)",
    ),
    "text_op": ToolSchema(
        name="text_op",
        params=[
            ParamSchema(name="operation", type="string", description="Operation: sort_lines|deduplicate|column|wrap|reverse|number_lines|trim|frequency"),
            ParamSchema(name="input", type="string", description="Input text"),
            ParamSchema(name="options", type="string", required=False, description="Operation options"),
        ],
        description="Advanced text processing (sort, deduplicate, column extract, wrap, frequency)",
    ),
    "json_format": ToolSchema(
        name="json_format",
        params=[
            ParamSchema(name="input", type="string", description="JSON text"),
            ParamSchema(name="operation", type="string", required=False, description="Operation: pretty|compact|validate|keys|flatten (default: pretty)"),
        ],
        description="JSON formatting (pretty print, compact, validate, extract keys, flatten)",
    ),
    "template_render": ToolSchema(
        name="template_render",
        params=[
            ParamSchema(name="template", type="string", description="Template with {{variable}} placeholders"),
            ParamSchema(name="variables", type="string", description="Variables as JSON or 'key=value,key2=value2'"),
        ],
        description="Render templates with variable substitution",
    ),
    "markdown_op": ToolSchema(
        name="markdown_op",
        params=[
            ParamSchema(name="operation", type="string", description="Operation: toc|extract_links|extract_headings|word_count|stats"),
            ParamSchema(name="input", type="string", description="Markdown text"),
        ],
        description="Markdown operations (TOC, extract links/headings, word count, stats)",
    ),
    "crypto_op": ToolSchema(
        name="crypto_op",
        params=[
            ParamSchema(name="operation", type="string", description="Operation: hash|hash_file|hmac_sign|hmac_verify|random|uuid|password|encode|decode|checksum"),
            ParamSchema(name="input", type="string", required=False, description="Input text or file path"),
            ParamSchema(name="key", type="string", required=False, description="Key for HMAC operations"),
            ParamSchema(name="algorithm", type="string", required=False, description="Algorithm: md5|sha1|sha256|sha512 or encoding: base64|base32|hex"),
        ],
        description="Crypto utilities (hash, HMAC, random, UUID, password, encode/decode)",
    ),
    "create_framework_project": ToolSchema(
        name="create_framework_project",
        params=[
            ParamSchema(name="framework", type="string", description="Framework: laravel|react|react-native|vue|next|angular|django|flask|fastapi|express|nestjs|svelte|expo|flutter|dotnet-web|dotnet-api|rails|rust|go|vite|nuxt|astro|remix|electron|tauri"),
            ParamSchema(name="name", type="string", required=False, description="Project name (default: my-app)"),
            ParamSchema(name="cwd", type="string", required=False, description="Directory to create project in"),
        ],
        description="Create a framework project with auto-dependency installation. Handles PHP, Node, Python, Rust, Go, .NET, Flutter, etc.",
    ),
    "organize_files": ToolSchema(
        name="organize_files",
        params=[
            ParamSchema(name="path", type="string", description="Directory to organize (e.g. Downloads, Desktop)"),
            ParamSchema(name="mode", type="string", required=False, description="'preview' (default, show plan) or 'execute' (move files)"),
            ParamSchema(name="categories", type="string", required=False, description="Comma-separated: Documents,Images,Videos,Music,Archives,Installers,Code,Design"),
        ],
        description="Safely organize files by type. NEVER moves project files. Preview first, then execute. Supports undo.",
    ),
    "undo_organize": ToolSchema(
        name="undo_organize",
        params=[],
        description="Undo the last file organization operation (moves files back to original locations).",
    ),
    "smart_cleanup": ToolSchema(
        name="smart_cleanup",
        params=[
            ParamSchema(name="path", type="string", description="Directory to clean"),
            ParamSchema(name="mode", type="string", required=False, description="'preview' or 'execute'"),
        ],
        description="Find and remove temp files, empty dirs, Thumbs.db, .DS_Store, Zone.Identifier files.",
    ),
    "file_summary": ToolSchema(
        name="file_summary",
        params=[
            ParamSchema(name="path", type="string", description="Directory to summarize"),
        ],
        description="Get file counts by type, total size, date range for a directory.",
    ),
    "schedule_reminder": ToolSchema(
        name="schedule_reminder",
        params=[
            ParamSchema(name="message", type="string", description="Reminder text"),
            ParamSchema(name="minutes", type="number", required=False, description="Minutes from now"),
            ParamSchema(name="time", type="string", required=False, description="Specific time like '3:00 PM'"),
        ],
        description="Set a reminder for later.",
    ),
    "check_reminders": ToolSchema(
        name="check_reminders",
        params=[],
        description="Check pending reminders.",
    ),
    "quick_note": ToolSchema(
        name="quick_note",
        params=[
            ParamSchema(name="content", type="string", description="Note content"),
            ParamSchema(name="title", type="string", required=False, description="Note title/tag"),
        ],
        description="Save a quick note (stored by date).",
    ),
    "list_notes": ToolSchema(
        name="list_notes",
        params=[
            ParamSchema(name="days", type="number", required=False, description="Number of days to show (default: 7)"),
        ],
        description="List recent notes.",
    ),
    "system_health": ToolSchema(
        name="system_health",
        params=[],
        description="Quick system health check: disk space, RAM, CPU usage.",
    ),
}


def get_schema(action_name: str) -> ToolSchema | None:
    return TOOL_SCHEMAS.get(action_name)


def describe_tool(action_name: str) -> str:
    schema = get_schema(action_name)
    if not schema:
        return f"Unknown tool: {action_name}"
    parts = [f"Tool: {action_name}"]
    if schema.description:
        parts.append(f"  Description: {schema.description}")
    if schema.params:
        parts.append("  Parameters:")
        for param in schema.params:
            req = "required" if param.required else "optional"
            parts.append(f"    - {param.name} ({param.type}) [{req}]")
            if param.description:
                parts.append(f"      {param.description}")
    return "\n".join(parts)
