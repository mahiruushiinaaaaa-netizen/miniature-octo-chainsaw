"""
workspace_index.py – Fast workspace indexing with caching.

Supports incremental rebuild via DependencyGraph and FileChangeTracker integration,
function-to-file mapping with line numbers, and caller lookup.

Requirements: 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .environment import EnvironmentDetector
from .logger import get_logger

if TYPE_CHECKING:
    from .dep_graph import DependencyGraph, FunctionInfo
    from .change_tracker import FileChangeTracker

logger = get_logger("workspace_index")

IGNORE_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env",
    "node_modules", "vendor", "dist", "build", ".next", ".nuxt",
    ".cache", ".idea", ".vscode",
}

IGNORE_PATH_FRAGMENTS = {
    "storage/framework",
    "bootstrap/cache",
}

TEXT_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".scss",
    ".json", ".md", ".txt", ".yml", ".yaml", ".toml", ".ini", ".env",
    ".php", ".vue", ".svelte", ".java", ".cs", ".cpp", ".c", ".h",
    ".hpp", ".go", ".rs", ".rb", ".sh", ".bat", ".ps1", ".sql", ".xml",
}

CACHE_DIR = EnvironmentDetector().get_cache_dir() / "workspace_index"


@dataclass
class FileInfo:
    path: str
    size: int
    suffix: str
    mtime: float = 0.0
    tokens: list[str] | None = None
    score: int = 0


_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_SIGNAL_RE = re.compile(
    r"^\s*(?:def|class|function|interface|type|export\s+function|export\s+class)\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.MULTILINE,
)
_STOPWORDS = {
    "function", "return", "import", "from", "class", "def", "const", "let", "var",
    "true", "false", "none", "null", "void", "public", "private", "protected",
    "string", "number", "boolean", "object", "list", "dict",
}


def is_text_file(path: Path) -> bool:
    if path.name in {".env", ".env.example", ".gitignore", "Dockerfile", "Makefile"}:
        return True
    return path.suffix.lower() in TEXT_SUFFIXES or path.name.endswith(".blade.php")


def should_skip(path: Path) -> bool:
    parts = [p.lower() for p in path.parts]
    if any(part in IGNORE_DIRS for part in parts):
        return True
    normalized = "/".join(parts)
    return any(fragment in normalized for fragment in IGNORE_PATH_FRAGMENTS)


def _extract_tokens(path: Path, *, max_chars: int = 6000, max_tokens: int = 32) -> list[str]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    head = raw[:max_chars]
    tokens: list[str] = []
    for match in _SIGNAL_RE.findall(head):
        name = match.strip()
        if name and name.lower() not in _STOPWORDS:
            tokens.append(name)
        if len(tokens) >= max_tokens:
            return tokens

    for name in _TOKEN_RE.findall(head):
        lowered = name.lower()
        if lowered in _STOPWORDS:
            continue
        if name not in tokens:
            tokens.append(name)
        if len(tokens) >= max_tokens:
            break

    return tokens


def _entry_points(files: list[str]) -> list[str]:
    candidates = {
        "main.py", "app.py", "run.py", "cli.py", "server.py", "__main__.py",
        "index.js", "index.ts", "main.js", "main.ts",
        "index.html", "src/main.jsx", "src/main.tsx",
    }
    found = [f for f in files if f in candidates]
    return found[:10]


def load_cache(root: Path) -> dict[str, Any] | None:
    cache = _cache_path(root)
    try:
        if cache.exists():
            data = json.loads(cache.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("root") == str(root):
                if time.time() - float(data.get("created_at", 0)) < 600:
                    return data
    except Exception as e:
        logger.debug(f"Failed to load cache from {cache}: {e}")
    
    legacy = root / ".mini_ai_workspace.json"
    try:
        if legacy.exists():
            data = json.loads(legacy.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("root") == str(root):
                if time.time() - float(data.get("created_at", 0)) < 600:
                    return data
    except Exception as e:
        logger.debug(f"Failed to load legacy cache from {legacy}: {e}")
    return None


def save_cache(root: Path, data: dict[str, Any]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache = _cache_path(root)
        payload = json.dumps(data, indent=2, ensure_ascii=False)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=str(CACHE_DIR),
            prefix="workspace_",
            suffix=".tmp",
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            tmp_path = Path(handle.name)
        tmp_path.replace(cache)
    except Exception:
        pass


def _cache_path(root: Path) -> Path:
    digest = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:12]
    return CACHE_DIR / f"workspace_{digest}.json"


def detect_stack(root: Path, files: list[str]) -> list[str]:
    names = set(files)
    stack: list[str] = []
    if "artisan" in names and "composer.json" in names:
        stack.append("Laravel/PHP")
    if "package.json" in names:
        stack.append("Node/Web")
    if "manage.py" in names:
        stack.append("Django/Python")
    if "requirements.txt" in names or "pyproject.toml" in names:
        stack.append("Python")
    if "vite.config.js" in names or "vite.config.ts" in names:
        stack.append("Vite")
    return stack


def keywords_from_goal(goal: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9_/-]+", goal.lower())
    stop = {"the", "and", "for", "with", "this", "that", "please", "project", "app", "make", "create", "add"}
    return [w for w in words if len(w) > 2 and w not in stop][:30]


def _goal_extensions(goal: str) -> set[str]:
    text = goal.lower()
    exts: set[str] = set()
    if any(x in text for x in ("frontend", "ui", "website", "page", "landing", "design")):
        exts.update({".html", ".css", ".js", ".ts", ".jsx", ".tsx"})
    if any(x in text for x in ("backend", "server", "api")):
        exts.update({".py", ".js", ".ts", ".go", ".java", ".cs"})
    if "python" in text or "py" in text:
        exts.add(".py")
    if "css" in text or "style" in text:
        exts.add(".css")
    if "html" in text:
        exts.add(".html")
    if "javascript" in text or "js" in text:
        exts.add(".js")
    if "typescript" in text or "ts" in text:
        exts.add(".ts")
    return exts


def score_file(
    rel: str,
    goal: str,
    stack: list[str],
    *,
    tokens: list[str] | None = None,
    suffix: str = "",
    size: int = 0,
    mtime: float = 0.0,
) -> int:
    rel_l = rel.lower()
    score = 0
    goal_keywords = keywords_from_goal(goal)
    goal_exts = _goal_extensions(goal)
    token_set = {t.lower() for t in (tokens or [])}

    for kw in goal_keywords:
        if kw in rel_l:
            score += 12
        if kw in token_set:
            score += 10

    high_value = {
        "routes/web.php": 80, "resources/views/welcome.blade.php": 85,
        "resources/css/app.css": 70, "resources/js/app.js": 55,
        "package.json": 60, "vite.config.js": 40, "composer.json": 55,
        "src/app": 50, "src/main": 45, "src/components": 45,
        "app.py": 50, "main.py": 45, "manage.py": 45,
    }
    for marker, points in high_value.items():
        if marker in rel_l:
            score += points

    if suffix and suffix in goal_exts:
        score += 18
    if any(ep in rel_l for ep in ("main.py", "app.py", "run.py", "index.js", "index.html")):
        score += 18

    if any(word in rel_l for word in ("test", "spec", ".bak", ".log", "lock")):
        score -= 20
    if "welcome.blade.php" in rel_l and any(x in goal.lower() for x in ("landing", "page", "design", "blog")):
        score += 80
    if "css" in rel_l and any(x in goal.lower() for x in ("design", "ui", "style", "landing")):
        score += 45
    if "route" in rel_l and any(x in goal.lower() for x in ("page", "landing", "route")):
        score += 35

    if size > 400_000:
        score -= 8
    if mtime:
        age_days = max(0.0, (time.time() - mtime) / 86400.0)
        if age_days <= 7:
            score += 6
    return score


def build_workspace_index(
    root: Path,
    *,
    max_files: int = 800,
    max_depth: int = 8,
    use_cache: bool = True,
) -> dict[str, Any]:
    if use_cache:
        cached = load_cache(root)
        if cached:
            return cached

    all_paths: list[str] = []
    text_files: list[FileInfo] = []
    root_depth = len(root.parts)
    count = 0

    for child in sorted(root.rglob("*"), key=lambda p: (len(p.parts), str(p).lower())):
        if count >= max_files:
            break
        if should_skip(child):
            continue
        depth = len(child.parts) - root_depth
        if depth > max_depth:
            continue
        rel = str(child.relative_to(root)).replace("\\", "/")
        if child.is_dir():
            all_paths.append(rel + "/")
        else:
            stat = child.stat()
            size = stat.st_size
            all_paths.append(f"{rel} ({size} bytes)")
            if is_text_file(child) and size <= 500_000:
                tokens = []
                if size <= 120_000:
                    tokens = _extract_tokens(child)
                text_files.append(
                    FileInfo(
                        path=rel,
                        size=size,
                        suffix=child.suffix.lower(),
                        mtime=stat.st_mtime,
                        tokens=tokens or None,
                    )
                )
        count += 1

    plain_files = [line.split(" (", 1)[0].rstrip("/") for line in all_paths]
    stack = detect_stack(root, plain_files)
    entry_points = _entry_points(plain_files)
    data = {
        "root": str(root),
        "created_at": time.time(),
        "files_listed": count,
        "stack": stack,
        "entry_points": entry_points,
        "tree": all_paths[:250],
        "text_files": [item.__dict__ for item in text_files[:500]],
    }
    save_cache(root, data)
    return data


def relevant_files(index: dict[str, Any], goal: str, limit: int = 10) -> list[str]:
    root = Path(str(index.get("root", ".")))
    stack = list(index.get("stack", []))
    scored: list[tuple[int, str]] = []
    for raw in index.get("text_files", []):
        if not isinstance(raw, dict):
            continue
        rel = str(raw.get("path", ""))
        if not rel:
            continue
        s = score_file(
            rel,
            goal,
            stack,
            tokens=list(raw.get("tokens", []) or []),
            suffix=str(raw.get("suffix", "")),
            size=int(raw.get("size", 0)),
            mtime=float(raw.get("mtime", 0.0)),
        )
        if s > 0:
            scored.append((s, str(root / rel).replace("\\", "/")))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in scored[:limit]]


def compact_index_summary(index: dict[str, Any], goal: str = "") -> str:
    stack = ", ".join(index.get("stack", [])) or "unknown"
    relevant = relevant_files(index, goal, limit=10) if goal else []
    tree = index.get("tree", [])[:80]
    entry_points = index.get("entry_points", [])
    lines = [
        f"Root: {index.get('root')}",
        f"Files listed: {index.get('files_listed')}",
        f"Stack: {stack}",
    ]
    if entry_points:
        lines.append("Entry points:")
        lines.extend(f"- {item}" for item in entry_points[:10])
    if relevant:
        lines.append("Relevant files:")
        lines.extend(f"- {path}" for path in relevant)
    lines.append("Compact tree:")
    lines.extend(f"- {item}" for item in tree[:80])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Incremental Workspace Index with DependencyGraph & FileChangeTracker
# Requirements: 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
# ---------------------------------------------------------------------------


@dataclass
class FunctionLookupResult:
    """Result of a function lookup in the workspace index.

    When `found` is False, the function was not in the index.
    """
    found: bool
    file: str = ""
    name: str = ""
    start_line: int = 0
    end_line: int = 0
    callers: list[str] = field(default_factory=list)


class WorkspaceIndexManager:
    """Manages workspace index with incremental rebuild support.

    Integrates DependencyGraph for import-based invalidation and
    FileChangeTracker for mtime-based change detection. Stores
    function-to-file mappings with line numbers and supports caller lookup.

    Requirements: 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
    """

    def __init__(self, root: Path):
        self._root = root
        self._index: dict[str, Any] = {}
        self._dep_graph: "DependencyGraph | None" = None
        self._change_tracker: "FileChangeTracker | None" = None
        # function_name -> {file, name, start_line, end_line, callers}
        self._function_map: dict[str, dict[str, Any]] = {}

    @property
    def index(self) -> dict[str, Any]:
        """The current workspace index data."""
        return self._index

    @property
    def dep_graph(self) -> "DependencyGraph | None":
        """The integrated dependency graph."""
        return self._dep_graph

    @property
    def change_tracker(self) -> "FileChangeTracker | None":
        """The integrated file change tracker."""
        return self._change_tracker

    def initialize(
        self,
        dep_graph: "DependencyGraph | None" = None,
        change_tracker: "FileChangeTracker | None" = None,
        *,
        use_cache: bool = True,
        max_files: int = 800,
        max_depth: int = 8,
    ) -> dict[str, Any]:
        """Build or load the workspace index and wire up integrations.

        Args:
            dep_graph: Optional DependencyGraph instance to integrate.
            change_tracker: Optional FileChangeTracker instance to integrate.
            use_cache: Whether to use cached index data.
            max_files: Maximum files to index.
            max_depth: Maximum directory depth.

        Returns:
            The workspace index dict.
        """
        self._dep_graph = dep_graph
        self._change_tracker = change_tracker

        # Build or load the base index
        self._index = build_workspace_index(
            self._root,
            max_files=max_files,
            max_depth=max_depth,
            use_cache=use_cache,
        )

        # Build dependency graph from index if provided
        if self._dep_graph is not None:
            self._dep_graph.build_from_index(self._index)
            self._sync_function_map_from_graph()

        return self._index

    def rebuild_incremental(self) -> dict[str, Any]:
        """Rebuild the index incrementally, processing only changed files.

        Uses the FileChangeTracker to identify files with changed mtime,
        removes entries for deleted files, and re-indexes only the affected
        files plus their direct importers (via DependencyGraph).

        Requirements: 4.6 — processes only changed-mtime files, removes deleted entries.

        Returns:
            The updated workspace index dict.
        """
        if not self._index:
            # No existing index — do a full build
            return self.initialize(
                dep_graph=self._dep_graph,
                change_tracker=self._change_tracker,
                use_cache=False,
            )

        root = Path(self._index.get("root", str(self._root)))
        text_files: list[dict[str, Any]] = list(self._index.get("text_files", []))

        # Determine which files need re-indexing
        files_to_reindex: set[str] = set()

        if self._change_tracker is not None and self._dep_graph is not None:
            # Use change tracker + dep graph for smart invalidation
            files_to_reindex = self._change_tracker.get_files_for_reindex(self._dep_graph)
        elif self._change_tracker is not None:
            # Just use modified files list
            files_to_reindex = set(self._change_tracker.get_modified_files())
        else:
            # Scan all indexed files for mtime changes
            files_to_reindex = self._detect_changed_files(root, text_files)

        # Remove entries for deleted files
        deleted_files = self._find_deleted_files(root, text_files)
        if deleted_files:
            text_files = [
                f for f in text_files
                if isinstance(f, dict) and f.get("path", "") not in deleted_files
            ]
            # Remove from function map
            for func_key in list(self._function_map.keys()):
                info = self._function_map[func_key]
                if info.get("file", "") in deleted_files:
                    del self._function_map[func_key]

        # Re-index changed files
        updated_entries: dict[str, dict[str, Any]] = {}
        for rel_path in files_to_reindex:
            full_path = root / rel_path
            if not full_path.exists() or not full_path.is_file():
                continue
            if not is_text_file(full_path):
                continue

            try:
                stat = full_path.stat()
            except OSError as e:
                logger.warn(
                    f"Cannot stat file during incremental rebuild: {rel_path}",
                    operation="rebuild_incremental",
                    error=e,
                )
                continue

            size = stat.st_size
            if size > 500_000:
                continue

            tokens = []
            if size <= 120_000:
                tokens = _extract_tokens(full_path)

            updated_entries[rel_path] = {
                "path": rel_path,
                "size": size,
                "suffix": full_path.suffix.lower(),
                "mtime": stat.st_mtime,
                "tokens": tokens or None,
            }

        # Merge updated entries into text_files list
        existing_paths = {
            f.get("path", ""): i
            for i, f in enumerate(text_files)
            if isinstance(f, dict)
        }

        for rel_path, entry in updated_entries.items():
            if rel_path in existing_paths:
                text_files[existing_paths[rel_path]] = entry
            else:
                text_files.append(entry)

        # Update the index
        self._index["text_files"] = text_files
        self._index["created_at"] = time.time()

        # Rebuild dependency graph with updated index
        if self._dep_graph is not None:
            self._dep_graph.build_from_index(self._index)
            self._sync_function_map_from_graph()

        # Save updated cache
        save_cache(root, self._index)

        return self._index

    def lookup_function(self, name: str) -> FunctionLookupResult:
        """Look up a function by name in the workspace index.

        Searches both qualified names (module.func) and unqualified names.
        Returns file path, line range, and callers within the indexed workspace.

        Requirements: 4.3, 4.4, 4.5

        Args:
            name: Function name to look up (qualified or unqualified).

        Returns:
            FunctionLookupResult with found=True if function exists,
            or found=False with empty fields if not found.
        """
        if not name:
            return FunctionLookupResult(found=False)

        # Try exact match in function map first
        if name in self._function_map:
            info = self._function_map[name]
            return FunctionLookupResult(
                found=True,
                file=info.get("file", ""),
                name=info.get("name", name),
                start_line=info.get("start_line", 0),
                end_line=info.get("end_line", 0),
                callers=list(info.get("callers", [])),
            )

        # Try unqualified name search
        for key, info in self._function_map.items():
            if info.get("name", "") == name:
                return FunctionLookupResult(
                    found=True,
                    file=info.get("file", ""),
                    name=info.get("name", name),
                    start_line=info.get("start_line", 0),
                    end_line=info.get("end_line", 0),
                    callers=list(info.get("callers", [])),
                )

        # Also try the dependency graph directly if available
        if self._dep_graph is not None:
            func_info = self._dep_graph.get_function_info(name)
            if func_info is not None:
                return FunctionLookupResult(
                    found=True,
                    file=func_info.file,
                    name=func_info.name,
                    start_line=func_info.start_line,
                    end_line=func_info.end_line,
                    callers=list(func_info.callers),
                )

        # Function not found — return empty result with indication
        return FunctionLookupResult(found=False)

    def get_callers(self, function_name: str) -> list[str]:
        """Get list of callers for a function within the indexed workspace.

        Requirements: 4.4

        Args:
            function_name: The function name to find callers for.

        Returns:
            List of caller identifiers (file paths or qualified function names).
            Empty list if function not found or has no callers.
        """
        result = self.lookup_function(function_name)
        if not result.found:
            return []
        return result.callers

    def add_function_mapping(
        self,
        name: str,
        file: str,
        start_line: int,
        end_line: int,
        callers: list[str] | None = None,
    ) -> None:
        """Manually add or update a function-to-file mapping.

        Requirements: 4.3

        Args:
            name: Qualified function name (e.g., "module.func_name").
            file: Relative file path containing the function.
            start_line: Starting line number of the function.
            end_line: Ending line number of the function.
            callers: Optional list of caller identifiers.
        """
        self._function_map[name] = {
            "file": file,
            "name": name.split(".")[-1] if "." in name else name,
            "start_line": start_line,
            "end_line": end_line,
            "callers": callers or [],
        }

    def invalidate_file(self, rel_path: str) -> set[str]:
        """Invalidate cache for a file and its direct dependents.

        Requirements: 4.2

        Args:
            rel_path: Relative path of the changed file.

        Returns:
            Set of files that were invalidated (changed file + direct importers).
        """
        invalidated: set[str] = {rel_path}

        if self._dep_graph is not None:
            invalidated = self._dep_graph.invalidate(rel_path)

        # Remove stale function mappings for invalidated files
        for func_key in list(self._function_map.keys()):
            info = self._function_map[func_key]
            if info.get("file", "") in invalidated:
                del self._function_map[func_key]

        return invalidated

    def get_function_map(self) -> dict[str, dict[str, Any]]:
        """Return the current function-to-file mapping.

        Returns:
            Dict mapping qualified function names to their metadata
            (file, name, start_line, end_line, callers).
        """
        return dict(self._function_map)

    # --- Private helpers ---

    def _sync_function_map_from_graph(self) -> None:
        """Sync function map from the dependency graph's function registry."""
        if self._dep_graph is None:
            return

        self._function_map.clear()

        # Access the dep graph's internal function store
        # The DependencyGraph stores functions as FunctionInfo dataclasses
        for key, func_info in self._dep_graph._functions.items():
            self._function_map[key] = {
                "file": func_info.file,
                "name": func_info.name,
                "start_line": func_info.start_line,
                "end_line": func_info.end_line,
                "callers": list(func_info.callers),
            }

    def _detect_changed_files(
        self, root: Path, text_files: list[dict[str, Any]]
    ) -> set[str]:
        """Detect files with changed mtime by comparing index vs disk."""
        changed: set[str] = set()

        for entry in text_files:
            if not isinstance(entry, dict):
                continue
            rel_path = entry.get("path", "")
            if not rel_path:
                continue

            cached_mtime = entry.get("mtime", 0.0)
            full_path = root / rel_path

            try:
                disk_mtime = os.path.getmtime(str(full_path))
            except OSError:
                # File may have been deleted — will be caught by _find_deleted_files
                continue

            if disk_mtime != cached_mtime:
                changed.add(rel_path)

        return changed

    def _find_deleted_files(
        self, root: Path, text_files: list[dict[str, Any]]
    ) -> set[str]:
        """Find files that are in the index but no longer exist on disk."""
        deleted: set[str] = set()

        for entry in text_files:
            if not isinstance(entry, dict):
                continue
            rel_path = entry.get("path", "")
            if not rel_path:
                continue

            full_path = root / rel_path
            if not full_path.exists():
                deleted.add(rel_path)

        return deleted
