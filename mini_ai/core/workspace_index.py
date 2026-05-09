"""
workspace_index.py – Fast workspace indexing with caching.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .environment import EnvironmentDetector

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
        from .logger import get_logger
        logger = get_logger("workspace_index")
        logger.debug(f"Failed to load cache from {cache}: {e}")
    
    legacy = root / ".mini_ai_workspace.json"
    try:
        if legacy.exists():
            data = json.loads(legacy.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("root") == str(root):
                if time.time() - float(data.get("created_at", 0)) < 600:
                    return data
    except Exception as e:
        from .logger import get_logger
        logger = get_logger("workspace_index")
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
