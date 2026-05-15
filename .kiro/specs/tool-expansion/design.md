# Design Document: Tool Expansion for 100+ Task Coverage

## Overview

This design expands mini_ai's tool set from ~40 to 100+ tools, covering virtually every task a developer or power user would need. The expansion follows the existing 5-point integration pattern and prioritizes:

1. **Stdlib-only implementations** — No external dependencies required
2. **Graceful error handling** — Every tool returns helpful messages on failure
3. **Platform detection** — Windows-first with Unix fallbacks
4. **Consistent interface** — All tools return `{"success": bool, "result"|"error": str}`

## Architecture

### Integration Pattern (Existing — No Changes)

```
1. Tool Function    → mini_ai/tools/<category>_tools.py
2. Schema           → mini_ai/core/schemas.py (TOOL_SCHEMAS dict)
3. Executor Wrapper → mini_ai/core/executor.py (self.registry + tool_* method)
4. Grammar          → mini_ai/core/grammars.py (tool_name rule in all 4 grammars)
5. Tool Router      → mini_ai/core/tool_router.py (optional categorization)
```

### New Tool Modules

| Module | Tools | Purpose |
|--------|-------|---------|
| `git_ops.py` | 12 tools | Advanced git operations |
| `docker_ops.py` | 8 tools | Container management |
| `package_ops.py` | 6 tools | Package manager operations |
| `code_ops.py` | 8 tools | Code analysis & quality |
| `test_ops.py` | 4 tools | Test running & coverage |
| `convert_ops.py` | 3 tools | Unit/format conversion |
| `net_ops.py` | 6 tools | Network diagnostics |
| `project_ops.py` | 4 tools | Project scaffolding |
| `file_ops_ext.py` | 6 tools | Advanced file operations |
| `text_ops.py` | 4 tools | Advanced text processing |
| `crypto_ops.py` | 3 tools | Encryption & signing |

**Total new: 64 tools → Combined total: 104+ tools**

---

## Component Designs

### 1. Git Operations (`mini_ai/tools/git_ops.py`)

```python
def git_op(operation: str, args: str = "", path: str = ".") -> dict[str, Any]:
    """Unified git operations tool.
    
    Operations:
    - branch: list/create/delete/switch branches
    - stash: save/pop/list/drop stashes
    - log: show commit history (last N commits)
    - blame: show line-by-line authorship
    - cherry_pick: apply specific commits
    - rebase: rebase current branch
    - tag: list/create/delete tags
    - remote: list/add/remove remotes
    - status: working tree status
    - diff_staged: show staged changes
    - merge: merge branches
    - reset: reset to commit (soft/mixed/hard)
    """
```

**Schema:**
```python
"git_op": ToolSchema(
    name="git_op",
    params=[
        ParamSchema(name="operation", type="string", description="branch|stash|log|blame|cherry_pick|rebase|tag|remote|status|diff_staged|merge|reset"),
        ParamSchema(name="args", type="string", required=False, description="Operation arguments"),
        ParamSchema(name="path", type="string", required=False, description="Repository path"),
    ],
    description="Advanced git operations (branch, stash, log, blame, cherry-pick, rebase, tag, remote, merge, reset)",
)
```

### 2. Docker Operations (`mini_ai/tools/docker_ops.py`)

```python
def docker_op(operation: str, target: str = "", options: str = "") -> dict[str, Any]:
    """Docker container and image management.
    
    Operations:
    - ps: list running containers
    - images: list images
    - run: run a container
    - stop: stop container(s)
    - rm: remove container(s)
    - logs: view container logs
    - build: build image from Dockerfile
    - compose_up: docker-compose up
    - compose_down: docker-compose down
    - exec: execute command in container
    - pull: pull an image
    - inspect: inspect container/image
    """
```

### 3. Package Operations (`mini_ai/tools/package_ops.py`)

```python
def package_op(manager: str, operation: str, package: str = "", options: str = "") -> dict[str, Any]:
    """Package manager operations (npm, pip, cargo, composer, go).
    
    Managers: npm, pip, cargo, composer, go, yarn, pnpm
    Operations: install, uninstall, list, outdated, update, search, init
    """
```

### 4. Code Operations (`mini_ai/tools/code_ops.py`)

```python
def code_analyze(operation: str, path: str, options: str = "") -> dict[str, Any]:
    """Code analysis and quality tools.
    
    Operations:
    - complexity: cyclomatic complexity analysis
    - dead_code: find unused functions/imports
    - dependencies: list file dependencies
    - lint: run linter (auto-detect language)
    - format: auto-format code
    - metrics: LOC, functions, classes count
    - imports: analyze import structure
    - todos: find TODO/FIXME/HACK comments
    """
```

### 5. Test Operations (`mini_ai/tools/test_ops.py`)

```python
def test_op(operation: str, path: str = ".", framework: str = "", options: str = "") -> dict[str, Any]:
    """Test running and coverage.
    
    Operations:
    - run: run tests (auto-detect framework)
    - coverage: run with coverage report
    - list: list test files/functions
    - failed: re-run only failed tests
    """
```

### 6. Conversion Operations (`mini_ai/tools/convert_ops.py`)

```python
def convert(category: str, value: str, from_unit: str, to_unit: str) -> dict[str, Any]:
    """Unit and format conversion.
    
    Categories: length, weight, temperature, speed, data_size, time, area, volume
    """

def format_convert(operation: str, input_text: str, options: str = "") -> dict[str, Any]:
    """Format conversion between data formats.
    
    Operations: json_to_yaml, yaml_to_json, csv_to_json, json_to_csv, 
                xml_to_json, markdown_to_html, toml_to_json
    """

def number_convert(value: str, from_base: str, to_base: str) -> dict[str, Any]:
    """Number base conversion (binary, octal, decimal, hex)."""
```

### 7. Network Operations (`mini_ai/tools/net_ops.py`)

```python
def net_op(operation: str, target: str, options: str = "") -> dict[str, Any]:
    """Network diagnostics and utilities.
    
    Operations:
    - ping: ping a host
    - dns: DNS lookup
    - port_check: check if port is open
    - download: download file from URL
    - whois: domain whois lookup
    - traceroute: trace network path
    """
```

### 8. Project Operations (`mini_ai/tools/project_ops.py`)

```python
def project_init(template: str, name: str, path: str = ".", options: str = "") -> dict[str, Any]:
    """Initialize a new project from template.
    
    Templates: python_package, node_app, react_app, next_app, django_app,
               flask_app, fastapi_app, express_app, rust_app, go_app,
               cli_tool, library, monorepo
    """

def project_info(path: str = ".") -> dict[str, Any]:
    """Analyze project structure and provide summary."""

def dependency_tree(path: str = ".", depth: int = 3) -> dict[str, Any]:
    """Show project dependency tree."""

def project_health(path: str = ".") -> dict[str, Any]:
    """Check project health (outdated deps, missing files, lint issues)."""
```

### 9. Advanced File Operations (`mini_ai/tools/file_ops_ext.py`)

```python
def file_op_ext(operation: str, path: str, options: str = "") -> dict[str, Any]:
    """Advanced file operations.
    
    Operations:
    - find_duplicates: find duplicate files by hash
    - bulk_rename: rename files with pattern
    - tree: directory tree visualization
    - disk_usage: directory size analysis
    - find_large: find largest files
    - compare_dirs: compare two directories
    """
```

### 10. Text Operations (`mini_ai/tools/text_ops.py`)

```python
def text_op(operation: str, input_text: str, options: str = "") -> dict[str, Any]:
    """Advanced text processing.
    
    Operations:
    - sort_lines: sort lines (alpha, numeric, reverse, unique)
    - deduplicate: remove duplicate lines
    - column: extract/rearrange columns
    - wrap: word wrap to width
    """

def json_format(input_text: str, operation: str = "pretty") -> dict[str, Any]:
    """JSON formatting operations.
    
    Operations: pretty, compact, validate, path_query, merge, diff
    """

def template_render(template: str, variables: str) -> dict[str, Any]:
    """Render a template with variable substitution."""

def markdown_op(operation: str, input_text: str) -> dict[str, Any]:
    """Markdown operations: toc, lint, to_html, extract_links, extract_headings."""
```

### 11. Crypto Operations (`mini_ai/tools/crypto_ops.py`)

```python
def crypto_op(operation: str, input_text: str, key: str = "", algorithm: str = "aes") -> dict[str, Any]:
    """Cryptographic operations.
    
    Operations:
    - encrypt: encrypt text (Fernet/AES)
    - decrypt: decrypt text
    - generate_key: generate encryption key
    - sign: create HMAC signature
    - verify: verify HMAC signature
    - random: generate random string/bytes
    - uuid: generate UUID
    - password: generate secure password
    """
```

---

## Reliability Patterns

### Error Handling Standard

Every tool function follows this pattern:

```python
def tool_function(params...) -> dict[str, Any]:
    """Docstring with operations list."""
    try:
        # Validate inputs
        if not required_param:
            return {"success": False, "error": "Parameter 'x' is required. Usage: ..."}
        
        # Platform detection
        if platform.system() == "Windows":
            # Windows-specific implementation
        else:
            # Unix fallback
        
        # Execute
        result = do_work()
        return {"success": True, "result": result}
    
    except FileNotFoundError:
        return {"success": False, "error": f"Not found: {path}. Use list_dir to verify."}
    except PermissionError:
        return {"success": False, "error": f"Permission denied: {path}"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Operation timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "error": f"Unexpected error: {e}"}
```

### Command Availability Detection

```python
def _check_command(cmd: str) -> bool:
    """Check if a command is available on the system."""
    return shutil.which(cmd) is not None

def _require_command(cmd: str, install_hint: str = "") -> dict[str, Any] | None:
    """Return error dict if command not available, None if OK."""
    if not _check_command(cmd):
        msg = f"'{cmd}' is not installed."
        if install_hint:
            msg += f" Install with: {install_hint}"
        return {"success": False, "error": msg}
    return None
```

### Output Truncation

All tools truncate output to 3000 chars max with `...[truncated]` indicator.

---

## Grammar Updates

All 64 new tool names must be added to the `tool_name` rule in all 4 grammars:

```
tool_name ::= ... | "\"git_op\"" | "\"docker_op\"" | "\"package_op\"" | "\"code_analyze\"" | "\"test_op\"" | "\"convert\"" | "\"format_convert\"" | "\"number_convert\"" | "\"net_op\"" | "\"project_init\"" | "\"project_info\"" | "\"dependency_tree\"" | "\"project_health\"" | "\"file_op_ext\"" | "\"text_op\"" | "\"json_format\"" | "\"template_render\"" | "\"markdown_op\"" | "\"crypto_op\""
```

Note: We use **compound tools** (one tool name with an `operation` parameter) rather than individual tool names for each operation. This keeps the grammar manageable (19 new names vs 64) while still covering 100+ distinct task types.

---

## Tool Count Summary

| Category | Existing | New Tools | Task Types Covered |
|----------|----------|-----------|-------------------|
| Filesystem | 12 | 6 | 18 |
| Code/Edit | 4 | 8 | 12 |
| Execution | 3 | 4 | 7 |
| Data/Text | 6 | 4 | 10 |
| System | 7 | 0 | 7 |
| Network/Web | 4 | 6 | 10 |
| Git/VCS | 0 | 12 | 12 |
| Docker | 0 | 12 | 12 |
| Package Mgmt | 0 | 7 | 7 |
| Testing | 0 | 4 | 4 |
| Conversion | 0 | 3 | 10+ |
| Project | 1 | 4 | 5 |
| Crypto | 0 | 8 | 8 |
| Media | 5 | 0 | 5 |
| **Total** | **~42** | **~64** | **127+** |

---

## Executor Registration Pattern

Each new module gets imported at the top of executor.py and registered:

```python
# In executor.py imports:
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

# In self.registry:
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
```

---

## Design Decisions

1. **Compound tools over individual tools** — Using `git_op(operation="branch", args="list")` instead of separate `git_branch`, `git_stash`, etc. keeps grammar size manageable and reduces model confusion.

2. **Subprocess-based implementations** — Most tools delegate to system commands (git, docker, npm, pip) with proper error handling. This avoids reinventing complex logic.

3. **No external Python dependencies** — All implementations use stdlib only (subprocess, json, hashlib, pathlib, etc.).

4. **Consistent 5-second timeout** — All subprocess calls default to 30s timeout with override option.

5. **Output truncation at 3000 chars** — Prevents context overflow from verbose command output.
