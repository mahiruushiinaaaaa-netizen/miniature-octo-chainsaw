"""
code_ops.py – Code analysis and quality tools.
Pure Python AST-based analysis for Python files, regex-based for others.
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any


def code_analyze(operation: str, path: str, options: str = "") -> dict[str, Any]:
    """Code analysis and quality tools.

    Operations:
    - complexity: cyclomatic complexity per function
    - dead_code: find unused imports and functions
    - dependencies: list file imports/requires
    - metrics: LOC, functions, classes count
    - imports: import structure analysis
    - todos: find TODO/FIXME/HACK comments
    - lint: run available linter (ruff/eslint/flake8)
    - format_check: check if code is formatted
    """
    operation = operation.lower().strip()
    target = Path(path).expanduser().resolve()

    if not target.exists():
        return {"success": False, "error": f"Path not found: {path}"}

    if operation == "complexity":
        return _analyze_complexity(target)
    elif operation == "dead_code":
        return _find_dead_code(target)
    elif operation == "dependencies":
        return _list_dependencies(target)
    elif operation == "metrics":
        return _code_metrics(target)
    elif operation == "imports":
        return _analyze_imports(target)
    elif operation == "todos":
        return _find_todos(target, options)
    elif operation == "lint":
        return _run_lint(target)
    elif operation == "format_check":
        return _format_check(target)
    else:
        return {"success": False, "error": f"Unknown operation: '{operation}'. Available: complexity, dead_code, dependencies, metrics, imports, todos, lint, format_check"}


def _analyze_complexity(path: Path) -> dict[str, Any]:
    """Calculate cyclomatic complexity for Python files."""
    if path.is_dir():
        results = []
        for f in path.rglob("*.py"):
            if "__pycache__" in str(f) or ".venv" in str(f):
                continue
            res = _file_complexity(f)
            if res:
                results.extend(res)
        if not results:
            return {"success": True, "result": "No Python files found"}
        results.sort(key=lambda x: x[1], reverse=True)
        lines = [f"  {name}: complexity {score}" for name, score in results[:30]]
        return {"success": True, "result": f"Cyclomatic Complexity (top 30):\n" + "\n".join(lines)}
    else:
        res = _file_complexity(path)
        if not res:
            return {"success": False, "error": "Could not analyze file (not Python or syntax error)"}
        lines = [f"  {name}: complexity {score}" for name, score in res]
        return {"success": True, "result": f"Complexity for {path.name}:\n" + "\n".join(lines)}


def _file_complexity(path: Path) -> list[tuple[str, int]]:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return []

    results = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            complexity = 1  # base
            for child in ast.walk(node):
                if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler,
                                      ast.With, ast.Assert, ast.comprehension)):
                    complexity += 1
                elif isinstance(child, ast.BoolOp):
                    complexity += len(child.values) - 1
            results.append((f"{path.name}:{node.name}", complexity))
    return results


def _find_dead_code(path: Path) -> dict[str, Any]:
    """Find unused imports and potentially unused functions in Python files."""
    if not path.suffix == ".py" and path.is_file():
        return {"success": False, "error": "dead_code analysis only supports Python files"}

    files = [path] if path.is_file() else list(path.rglob("*.py"))
    unused_imports = []
    unused_functions = []

    for f in files[:50]:  # limit
        if "__pycache__" in str(f) or ".venv" in str(f):
            continue
        try:
            source = f.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            continue

        # Find imports
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name != "*":
                        imported_names.add(alias.asname or alias.name)

        # Find used names in the rest of the code
        used_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    used_names.add(node.value.id)

        for name in imported_names - used_names:
            if not name.startswith("_"):
                unused_imports.append(f"  {f.name}: unused import '{name}'")

    results = []
    if unused_imports:
        results.append(f"Unused imports ({len(unused_imports)}):")
        results.extend(unused_imports[:30])
    else:
        results.append("No unused imports found")

    return {"success": True, "result": "\n".join(results)}


def _list_dependencies(path: Path) -> dict[str, Any]:
    """List imports/requires from a file."""
    if not path.is_file():
        return {"success": False, "error": "dependencies requires a file path"}

    source = path.read_text(encoding="utf-8", errors="replace")
    deps = []

    if path.suffix == ".py":
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        deps.append(f"import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    names = ", ".join(a.name for a in node.names)
                    deps.append(f"from {module} import {names}")
        except SyntaxError:
            deps = re.findall(r'^(?:from\s+\S+\s+)?import\s+.+', source, re.MULTILINE)
    elif path.suffix in (".js", ".ts", ".jsx", ".tsx"):
        deps = re.findall(r'(?:import|require)\s*\(?[\'"]([^\'"]+)[\'"]', source)
        deps = [f"require('{d}')" for d in deps]
    elif path.suffix == ".php":
        deps = re.findall(r'(?:use|require|include)\s+[\'"]?([^\s;\'\"]+)', source)

    if not deps:
        return {"success": True, "result": "No dependencies found"}
    return {"success": True, "result": f"Dependencies ({len(deps)}):\n" + "\n".join(f"  {d}" for d in deps[:50])}


def _code_metrics(path: Path) -> dict[str, Any]:
    """Count LOC, functions, classes."""
    if path.is_file():
        files = [path]
    else:
        files = [f for f in path.rglob("*") if f.is_file() and f.suffix in (".py", ".js", ".ts", ".jsx", ".tsx", ".php", ".rb", ".go", ".rs", ".java", ".c", ".cpp", ".h")]
        files = [f for f in files if "__pycache__" not in str(f) and "node_modules" not in str(f) and ".venv" not in str(f)]

    total_lines = 0
    total_blank = 0
    total_comment = 0
    total_functions = 0
    total_classes = 0
    file_count = 0

    for f in files[:200]:
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            file_count += 1
            total_lines += len(lines)
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    total_blank += 1
                elif stripped.startswith(("#", "//", "/*", "*", "'")):
                    total_comment += 1
            # Count functions/classes (rough)
            content = f.read_text(encoding="utf-8", errors="replace")
            total_functions += len(re.findall(r'(?:def |function |fn |func )\w+', content))
            total_classes += len(re.findall(r'(?:class |struct |interface )\w+', content))
        except Exception:
            continue

    code_lines = total_lines - total_blank - total_comment
    result = f"""Code Metrics:
  Files: {file_count}
  Total lines: {total_lines:,}
  Code lines: {code_lines:,}
  Blank lines: {total_blank:,}
  Comment lines: {total_comment:,}
  Functions: {total_functions}
  Classes: {total_classes}"""
    return {"success": True, "result": result}


def _analyze_imports(path: Path) -> dict[str, Any]:
    """Analyze import structure of a directory."""
    if not path.is_dir():
        return _list_dependencies(path)

    stdlib_imports = set()
    third_party = set()
    local_imports = set()

    for f in list(path.rglob("*.py"))[:100]:
        if "__pycache__" in str(f) or ".venv" in str(f):
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        _classify_import(top, path, stdlib_imports, third_party, local_imports)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        top = node.module.split(".")[0]
                        if node.level > 0:
                            local_imports.add(node.module)
                        else:
                            _classify_import(top, path, stdlib_imports, third_party, local_imports)
        except (SyntaxError, UnicodeDecodeError):
            continue

    result = []
    if third_party:
        result.append(f"Third-party ({len(third_party)}): {', '.join(sorted(third_party)[:20])}")
    if local_imports:
        result.append(f"Local ({len(local_imports)}): {', '.join(sorted(local_imports)[:20])}")
    if stdlib_imports:
        result.append(f"Stdlib ({len(stdlib_imports)}): {', '.join(sorted(stdlib_imports)[:20])}")

    return {"success": True, "result": "\n".join(result) or "No imports found"}


def _classify_import(name: str, project_root: Path, stdlib: set, third_party: set, local: set):
    """Classify an import as stdlib, third-party, or local."""
    import sys
    stdlib_modules = set(sys.stdlib_module_names) if hasattr(sys, 'stdlib_module_names') else {"os", "sys", "re", "json", "pathlib", "subprocess", "typing", "collections", "functools", "itertools", "math", "datetime", "hashlib", "base64", "io", "shutil", "tempfile", "time", "threading", "socket", "urllib", "http", "email", "csv", "ast", "inspect", "logging", "unittest", "dataclasses", "enum", "abc", "contextlib", "copy", "glob", "platform", "signal", "struct", "textwrap", "traceback", "uuid", "warnings", "weakref", "xml", "zipfile", "tarfile", "sqlite3", "ssl", "statistics", "string", "secrets"}
    if name in stdlib_modules:
        stdlib.add(name)
    elif (project_root / name).exists() or (project_root / f"{name}.py").exists():
        local.add(name)
    else:
        third_party.add(name)


def _find_todos(path: Path, pattern: str = "") -> dict[str, Any]:
    """Find TODO/FIXME/HACK comments."""
    patterns = pattern.split(",") if pattern else ["TODO", "FIXME", "HACK", "XXX", "BUG"]
    regex = re.compile(r'(?:' + '|'.join(re.escape(p.strip()) for p in patterns) + r')[\s:]+(.+)', re.IGNORECASE)

    files = [path] if path.is_file() else [f for f in path.rglob("*") if f.is_file() and f.suffix in (".py", ".js", ".ts", ".jsx", ".tsx", ".php", ".rb", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".css", ".html", ".md")]
    files = [f for f in files if "__pycache__" not in str(f) and "node_modules" not in str(f) and ".venv" not in str(f)]

    results = []
    for f in files[:100]:
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                match = regex.search(line)
                if match:
                    results.append(f"  {f.name}:{i}: {line.strip()[:100]}")
        except Exception:
            continue

    if not results:
        return {"success": True, "result": "No TODOs found"}
    return {"success": True, "result": f"Found {len(results)} items:\n" + "\n".join(results[:50])}


def _run_lint(path: Path) -> dict[str, Any]:
    """Run available linter."""
    import shutil as sh
    target = str(path)

    # Python
    if path.suffix == ".py" or (path.is_dir() and any(path.rglob("*.py"))):
        for linter in ["ruff", "flake8", "pylint"]:
            if sh.which(linter):
                try:
                    args = [linter, "check" if linter == "ruff" else "", target]
                    args = [a for a in args if a]
                    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
                    output = (result.stdout + result.stderr).strip()
                    return {"success": result.returncode == 0, "result" if result.returncode == 0 else "error": output[:3000] or "No issues found"}
                except Exception as e:
                    return {"success": False, "error": str(e)}
        return {"success": False, "error": "No Python linter found. Install: pip install ruff"}

    # JS/TS
    if path.suffix in (".js", ".ts", ".jsx", ".tsx") or (path.is_dir() and any(path.rglob("*.js"))):
        if sh.which("eslint"):
            try:
                result = subprocess.run(["eslint", target], capture_output=True, text=True, timeout=30)
                output = (result.stdout + result.stderr).strip()
                return {"success": result.returncode == 0, "result" if result.returncode == 0 else "error": output[:3000]}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "eslint not found. Install: npm install -g eslint"}

    return {"success": False, "error": f"No linter available for {path.suffix} files"}


def _format_check(path: Path) -> dict[str, Any]:
    """Check if code is properly formatted."""
    import shutil as sh
    target = str(path)

    if path.suffix == ".py":
        for fmt in ["black", "ruff"]:
            if sh.which(fmt):
                try:
                    args = [fmt, "format", "--check", target] if fmt == "ruff" else [fmt, "--check", target]
                    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
                    if result.returncode == 0:
                        return {"success": True, "result": "Code is properly formatted"}
                    return {"success": False, "error": f"Code needs formatting:\n{result.stdout[:2000]}"}
                except Exception as e:
                    return {"success": False, "error": str(e)}

    return {"success": False, "error": "No formatter available. Install: pip install ruff"}
