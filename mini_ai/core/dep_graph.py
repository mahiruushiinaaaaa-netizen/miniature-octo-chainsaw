"""
dep_graph.py – Directed dependency graph for workspace intelligence.

Builds forward (imports) and reverse (importers) maps from Python and JS/TS
import statements. Supports invalidation, function lookup, and BFS traversal.
"""
from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .logger import get_logger

logger = get_logger("dep_graph")

# --- Regex patterns for import extraction ---

# Python: "from foo.bar import baz" or "import foo.bar"
_PY_FROM_IMPORT_RE = re.compile(
    r"^\s*from\s+([\w.]+)\s+import\s+", re.MULTILINE
)
_PY_IMPORT_RE = re.compile(
    r"^\s*import\s+([\w.]+(?:\s*,\s*[\w.]+)*)", re.MULTILINE
)

# JS/TS: import ... from "path" or import ... from 'path'
_JS_IMPORT_RE = re.compile(
    r"""^\s*import\s+.*?\s+from\s+['"]([^'"]+)['"]""", re.MULTILINE
)
# JS/TS: require("path") or require('path')
_JS_REQUIRE_RE = re.compile(
    r"""require\(\s*['"]([^'"]+)['"]\s*\)"""
)

# Python function definitions (top-level and class methods)
_PY_FUNC_RE = re.compile(
    r"^(?:    |\t)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE
)
# JS/TS function definitions
_JS_FUNC_RE = re.compile(
    r"(?:^|\n)\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(",
)
# JS/TS arrow/const functions
_JS_CONST_FUNC_RE = re.compile(
    r"(?:^|\n)\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s+)?\(",
)

# Suffixes we parse for imports
_PYTHON_SUFFIXES = {".py"}
_JS_TS_SUFFIXES = {".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"}


@dataclass
class FunctionInfo:
    """Function metadata stored in the dependency graph."""
    file: str
    name: str
    start_line: int
    end_line: int
    callers: list[str] = field(default_factory=list)


class DependencyGraph:
    """Directed graph of file imports for workspace intelligence."""

    def __init__(self, root: Path):
        self.root = root
        self._imports: dict[str, set[str]] = {}      # file -> set of files it imports
        self._importers: dict[str, set[str]] = {}    # file -> set of files that import it
        self._functions: dict[str, FunctionInfo] = {}  # "module.func" or "func" -> info

    def build_from_index(self, workspace_index: dict[str, Any]) -> None:
        """Parse import statements from indexed text files.

        Args:
            workspace_index: Dict from build_workspace_index() containing
                'root', 'text_files' list of file info dicts.
        """
        self._imports.clear()
        self._importers.clear()
        self._functions.clear()

        root = Path(workspace_index.get("root", str(self.root)))
        text_files = workspace_index.get("text_files", [])

        # Build a lookup of relative paths for resolution
        all_rel_paths: set[str] = set()
        for entry in text_files:
            if isinstance(entry, dict):
                rel = entry.get("path", "")
                if rel:
                    all_rel_paths.add(rel)

        for entry in text_files:
            if not isinstance(entry, dict):
                continue
            rel_path = entry.get("path", "")
            suffix = entry.get("suffix", "")
            if not rel_path:
                continue

            # Initialize imports set for this file
            if rel_path not in self._imports:
                self._imports[rel_path] = set()

            # Read file content for parsing
            full_path = root / rel_path
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
            except (OSError, IOError):
                continue

            # Parse imports based on file type
            if suffix in _PYTHON_SUFFIXES:
                imported = self._parse_python_imports(rel_path, content, all_rel_paths)
                self._extract_python_functions(rel_path, content)
            elif suffix in _JS_TS_SUFFIXES:
                imported = self._parse_js_imports(rel_path, content, all_rel_paths)
                self._extract_js_functions(rel_path, content)
            else:
                continue

            # Update forward and reverse maps
            self._imports[rel_path] = imported
            for imp in imported:
                if imp not in self._importers:
                    self._importers[imp] = set()
                self._importers[imp].add(rel_path)

        logger.debug(
            f"Dependency graph built: {len(self._imports)} files, "
            f"{sum(len(v) for v in self._imports.values())} edges, "
            f"{len(self._functions)} functions"
        )

    def invalidate(self, changed_file: str) -> set[str]:
        """Return set of files to re-index: {changed_file} ∪ {direct importers}.

        One hop only — files that directly import the changed file.
        """
        result = {changed_file}
        # Add direct importers (files that import the changed file)
        if changed_file in self._importers:
            result.update(self._importers[changed_file])
        return result

    def get_function_info(self, name: str) -> FunctionInfo | None:
        """Lookup function by name, return file, lines, callers.

        Searches both qualified ("module.func") and unqualified ("func") names.
        """
        # Try exact match first
        if name in self._functions:
            return self._functions[name]

        # Try searching by unqualified name
        for key, info in self._functions.items():
            if info.name == name:
                return info

        return None

    def files_within_hops(self, start: str, max_hops: int = 2) -> set[str]:
        """BFS traversal returning files within N dependency hops.

        Traverses both forward (imports) and reverse (importers) edges.
        """
        if start not in self._imports and start not in self._importers:
            return {start}

        visited: set[str] = {start}
        queue: deque[tuple[str, int]] = deque([(start, 0)])

        while queue:
            current, depth = queue.popleft()
            if depth >= max_hops:
                continue

            # Forward edges: files that current imports
            for neighbor in self._imports.get(current, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))

            # Reverse edges: files that import current
            for neighbor in self._importers.get(current, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))

        return visited

    # --- Private helpers ---

    def _parse_python_imports(
        self, source_file: str, content: str, known_files: set[str]
    ) -> set[str]:
        """Extract Python imports and resolve to known workspace files."""
        imported: set[str] = set()

        # Handle "from X import Y"
        for match in _PY_FROM_IMPORT_RE.finditer(content):
            module_path = match.group(1)
            resolved = self._resolve_python_module(source_file, module_path, known_files)
            if resolved:
                imported.add(resolved)

        # Handle "import X" (possibly comma-separated)
        for match in _PY_IMPORT_RE.finditer(content):
            modules_str = match.group(1)
            for module_path in modules_str.split(","):
                module_path = module_path.strip()
                if module_path:
                    resolved = self._resolve_python_module(
                        source_file, module_path, known_files
                    )
                    if resolved:
                        imported.add(resolved)

        return imported

    def _resolve_python_module(
        self, source_file: str, module_path: str, known_files: set[str]
    ) -> str | None:
        """Resolve a Python module path to a workspace-relative file path.

        Tries:
        1. Direct path: foo.bar -> foo/bar.py or foo/bar/__init__.py
        2. Relative to source directory
        """
        # Convert dots to path separators
        parts = module_path.split(".")
        # Try as direct path: foo/bar.py
        candidate = "/".join(parts) + ".py"
        if candidate in known_files:
            return candidate

        # Try as package: foo/bar/__init__.py
        candidate = "/".join(parts) + "/__init__.py"
        if candidate in known_files:
            return candidate

        # Try relative to source file's directory
        source_dir = "/".join(source_file.split("/")[:-1])
        if source_dir:
            candidate = source_dir + "/" + "/".join(parts) + ".py"
            if candidate in known_files:
                return candidate
            candidate = source_dir + "/" + "/".join(parts) + "/__init__.py"
            if candidate in known_files:
                return candidate

        return None

    def _parse_js_imports(
        self, source_file: str, content: str, known_files: set[str]
    ) -> set[str]:
        """Extract JS/TS imports and resolve to known workspace files."""
        imported: set[str] = set()

        # Handle ES module imports: import X from "path"
        for match in _JS_IMPORT_RE.finditer(content):
            import_path = match.group(1)
            resolved = self._resolve_js_path(source_file, import_path, known_files)
            if resolved:
                imported.add(resolved)

        # Handle CommonJS: require("path")
        for match in _JS_REQUIRE_RE.finditer(content):
            import_path = match.group(1)
            resolved = self._resolve_js_path(source_file, import_path, known_files)
            if resolved:
                imported.add(resolved)

        return imported

    def _resolve_js_path(
        self, source_file: str, import_path: str, known_files: set[str]
    ) -> str | None:
        """Resolve a JS/TS import path to a workspace-relative file path.

        Handles relative paths (./foo, ../bar) and tries common extensions.
        """
        # Skip node_modules / bare specifiers
        if not import_path.startswith(".") and not import_path.startswith("/"):
            return None

        # Resolve relative to source file directory
        source_dir = "/".join(source_file.split("/")[:-1])
        if import_path.startswith("./") or import_path.startswith("../"):
            # Normalize the path
            parts = (source_dir + "/" + import_path).split("/")
            normalized: list[str] = []
            for part in parts:
                if part == "." or part == "":
                    continue
                elif part == "..":
                    if normalized:
                        normalized.pop()
                else:
                    normalized.append(part)
            resolved_base = "/".join(normalized)
        else:
            resolved_base = import_path.lstrip("/")

        # Try exact path first
        if resolved_base in known_files:
            return resolved_base

        # Try with common extensions
        extensions = [".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"]
        for ext in extensions:
            candidate = resolved_base + ext
            if candidate in known_files:
                return candidate

        # Try as directory with index file
        for ext in extensions:
            candidate = resolved_base + "/index" + ext
            if candidate in known_files:
                return candidate

        return None

    def _extract_python_functions(self, rel_path: str, content: str) -> None:
        """Extract top-level and method function definitions from Python file."""
        lines = content.split("\n")
        # Derive module name from path (e.g., "mini_ai/core/dep_graph.py" -> "dep_graph")
        module_name = rel_path.rsplit("/", 1)[-1].replace(".py", "")

        for match in _PY_FUNC_RE.finditer(content):
            func_name = match.group(1)
            # Skip private/dunder methods for the public index
            if func_name.startswith("__") and func_name.endswith("__"):
                continue

            start_line = content[:match.start()].count("\n") + 1
            end_line = self._find_python_func_end(lines, start_line - 1)

            qualified_name = f"{module_name}.{func_name}"
            self._functions[qualified_name] = FunctionInfo(
                file=rel_path,
                name=func_name,
                start_line=start_line,
                end_line=end_line,
                callers=[],
            )

    def _find_python_func_end(self, lines: list[str], start_idx: int) -> int:
        """Find the end line of a Python function by indentation."""
        if start_idx >= len(lines):
            return start_idx + 1

        # Determine the indentation of the def line
        def_line = lines[start_idx]
        def_indent = len(def_line) - len(def_line.lstrip())

        end_idx = start_idx + 1
        while end_idx < len(lines):
            line = lines[end_idx]
            # Skip empty lines and comments
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                end_idx += 1
                continue
            # If indentation is <= def indentation, function ended
            current_indent = len(line) - len(line.lstrip())
            if current_indent <= def_indent:
                break
            end_idx += 1

        return end_idx

    def _extract_js_functions(self, rel_path: str, content: str) -> None:
        """Extract function definitions from JS/TS file."""
        module_name = rel_path.rsplit("/", 1)[-1]
        # Remove extension
        for ext in (".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"):
            if module_name.endswith(ext):
                module_name = module_name[: -len(ext)]
                break

        lines = content.split("\n")

        # Named function declarations
        for match in _JS_FUNC_RE.finditer(content):
            func_name = match.group(1)
            # Find the actual line where the function keyword appears
            func_keyword_pos = content.find("function", match.start())
            start_line = content[:func_keyword_pos].count("\n") + 1
            end_line = self._find_js_func_end(lines, start_line - 1)

            qualified_name = f"{module_name}.{func_name}"
            self._functions[qualified_name] = FunctionInfo(
                file=rel_path,
                name=func_name,
                start_line=start_line,
                end_line=end_line,
                callers=[],
            )

        # Arrow/const function declarations
        for match in _JS_CONST_FUNC_RE.finditer(content):
            func_name = match.group(1)
            # Find the actual line where the const/let/var keyword appears
            match_text = content[match.start():match.end()]
            keyword_offset = 0
            for kw in ("export ", "const ", "let ", "var "):
                idx = match_text.find(kw)
                if idx >= 0:
                    keyword_offset = idx
                    break
            start_line = content[:match.start() + keyword_offset].count("\n") + 1
            end_line = self._find_js_func_end(lines, start_line - 1)

            qualified_name = f"{module_name}.{func_name}"
            if qualified_name not in self._functions:
                self._functions[qualified_name] = FunctionInfo(
                    file=rel_path,
                    name=func_name,
                    start_line=start_line,
                    end_line=end_line,
                    callers=[],
                )

    def _find_js_func_end(self, lines: list[str], start_idx: int) -> int:
        """Find the end line of a JS/TS function by brace matching."""
        brace_depth = 0
        found_open = False

        for idx in range(start_idx, len(lines)):
            line = lines[idx]
            for char in line:
                if char == "{":
                    brace_depth += 1
                    found_open = True
                elif char == "}":
                    brace_depth -= 1
                    if found_open and brace_depth == 0:
                        return idx + 1  # 1-indexed

        # If we can't find the end, return a reasonable default
        return min(start_idx + 20, len(lines))
