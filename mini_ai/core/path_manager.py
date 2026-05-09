"""
path_manager.py – Centralized, authoritative path resolution for mini_ai.

KEY DESIGN PRINCIPLE
====================
  workspace       = the AI assistant's own working directory (config.workspace)
  target_directory = the actual user-specified output location

These are NEVER interchangeable.

All filesystem writes must flow through PathManager.resolve_target()
so the target_directory is always derived from the user's explicit path,
never silently replaced by the workspace fallback.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


# ─── Regex patterns ────────────────────────────────────────────────────────────

# Match a Windows absolute path: C:\... or C:/...
_WIN_PATH_RE = re.compile(
    r"""
    (?:^|[\s"'(=,])          # start-of-string or whitespace / delimiters
    (
        [A-Za-z]             # drive letter
        :                    # colon
        [/\\]                # first separator
        [^\s"'<>|*?\r\n]*    # path body (no shell-special chars)
    )
    """,
    re.VERBOSE,
)

# Match a Unix/Linux/macOS absolute path: /home/..., /Users/...
_UNIX_PATH_RE = re.compile(
    r"""
    (?:^|[\s"'(=,])
    (
        /                    # must start with /
        [^\s"'<>|*?\r\n]+    # non-empty path body
    )
    """,
    re.VERBOSE,
)

# Words that typically FOLLOW a path and indicate where the path ends
_CUT_MARKERS = (
    " create ", " make ", " write ", " delete ", " remove ",
    " containing ", " with content ", " with the ", " put ",
    " add ", " build ", " implement ", " update ", " change ",
    " refactor ", " fix ", " and ", " then ",
)


# ─── Extraction helpers ────────────────────────────────────────────────────────

def _all_windows_candidates(text: str) -> list[str]:
    """Return all Windows path candidates from text, longest first."""
    raw = _WIN_PATH_RE.findall(text or "")
    cleaned: list[str] = []
    for item in raw:
        item = item.strip().strip("'\"").rstrip(".,;)\"'")
        if item:
            cleaned.append(item)
    # Deduplicate, prefer longest
    seen: set[str] = set()
    result: list[str] = []
    for c in sorted(cleaned, key=len, reverse=True):
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


def _best_existing_prefix(tail: str) -> Optional[str]:
    """
    Walk backward through whitespace-boundary splits of *tail* and return
    the longest prefix that actually exists on disk.
    """
    boundaries = [i for i, ch in enumerate(tail) if ch.isspace()]
    boundaries.append(len(tail))

    best: Optional[str] = None
    for i in boundaries:
        candidate = tail[:i].strip().strip("'\"").rstrip(".,;")
        if not candidate:
            continue
        try:
            if Path(candidate).exists():
                best = candidate
        except OSError:
            pass
    return best


def extract_windows_path(text: str) -> Optional[str]:
    """
    Extract the best Windows path from free-form text.

    Priority:
    1. Longest existing prefix on disk.
    2. Quoted path.
    3. Command-word-trimmed path (fallback for not-yet-existing targets).
    """
    match = re.search(r"[A-Za-z]:[/\\]", text)
    if not match:
        return None

    tail = text[match.start():].strip()
    if not tail:
        return None

    # 1. Quoted path
    if tail[0] in {"'", '"'}:
        quote = tail[0]
        end = tail.find(quote, 1)
        if end > 1:
            return tail[1:end].strip().replace("\\", "/")

    # 2. Longest existing prefix
    best = _best_existing_prefix(tail)
    if best:
        return best.replace("\\", "/")

    # 3. Trim at command markers (for paths that don't yet exist)
    lower_tail = " " + tail.lower()
    cut_at = len(tail)
    for marker in _CUT_MARKERS:
        pos = lower_tail.find(marker)
        if pos > 6:
            cut_at = min(cut_at, pos - 1)

    path_text = tail[:cut_at].strip().strip("'\"").rstrip(".,;")
    return path_text.replace("\\", "/") if path_text else None


def extract_unix_path(text: str) -> Optional[str]:
    """Extract the best Unix/Linux/macOS path from text."""
    matches = _UNIX_PATH_RE.findall(text or "")
    if not matches:
        return None
    # Return the longest match
    matches.sort(key=len, reverse=True)
    return matches[0].strip().strip("'\"").rstrip(".,;") or None


def extract_symbolic_path(text: str) -> Optional[str]:
    """Detect common symbolic folder names in natural language."""
    lowered = text.lower()
    # Common Windows/Unix folders
    if "downloads folder" in lowered or "my downloads" in lowered or "the downloads" in lowered:
        return "~/Downloads"
    if "documents folder" in lowered or "my documents" in lowered:
        return "~/Documents"
    if "desktop folder" in lowered or "my desktop" in lowered:
        return "~/Desktop"
    if "pictures folder" in lowered or "my pictures" in lowered:
        return "~/Pictures"
    if "videos folder" in lowered or "my videos" in lowered:
        return "~/Videos"
    return None


def extract_user_path(text: str) -> Optional[str]:
    """Platform-aware path extraction; prefers Windows paths on Windows text."""
    win = extract_windows_path(text)
    if win:
        return win
    
    unix = extract_unix_path(text)
    if unix:
        return unix
    
    return extract_symbolic_path(text)


# ─── PathManager ──────────────────────────────────────────────────────────────

class PathManager:
    """
    Single source of truth for path resolution across the agent session.

    Usage
    -----
    pm = PathManager(config.workspace)
    pm.set_target_from_goal(user_goal)        # call once per task

    # In execute():
    path = pm.resolve_target(action_path)     # ALWAYS use this, never normalize()
    """

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace.expanduser().resolve()
        self._target_directory: Optional[Path] = None
        self._path_cache: dict[str, Path] = {}

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def workspace(self) -> Path:
        return self._workspace

    @property
    def target_directory(self) -> Optional[Path]:
        return self._target_directory

    @property
    def effective_root(self) -> Path:
        """The directory to use as base for relative paths."""
        return self._target_directory if self._target_directory else self._workspace

    # ── Target extraction ─────────────────────────────────────────────────────

    def set_target_from_goal(self, goal: str) -> Optional[Path]:
        """
        Parse the user goal and set target_directory if an explicit path is found.
        Returns the resolved target or None.
        """
        raw = extract_user_path(goal)
        if not raw:
            return None

        path = self._normalize_raw(raw)
        if path:
            self._target_directory = path
            self._log_target_set(raw, path)
            return path
        return None

    def set_target(self, path: Path) -> None:
        """Explicitly set the target directory (e.g. from project_root discovery)."""
        resolved = path.expanduser().resolve()
        self._target_directory = resolved
        print(f"[TARGET DIRECTORY] {resolved}", flush=True)

    def clear_target(self) -> None:
        self._target_directory = None

    # ── Core resolution ───────────────────────────────────────────────────────

    def resolve_target(self, path_text: str) -> Path:
        """
        Resolve an action's path field.

        Rules (in priority order):
        1. Absolute path → use exactly as-is (forward/backslash normalized).
        2. Relative path + target_directory exists → join with target_directory.
        3. Relative path + no target_directory → join with workspace.

        NEVER silently ignores an explicit user path.
        """
        if path_text in self._path_cache:
            return self._path_cache[path_text]

        cleaned = path_text.strip().strip("'\"")
        if not cleaned:
            result = self.effective_root
        else:
            p = Path(cleaned.replace("\\", "/"))
            if p.is_absolute():
                result = p.expanduser()
            else:
                result = (self.effective_root / p)

        self._path_cache[path_text] = result
        return result

    def resolve_workspace_only(self, path_text: str) -> Path:
        """
        Resolve relative to workspace only (for agent-internal files,
        notes, indexes, artifacts — NOT user output files).
        """
        cleaned = path_text.strip().strip("'\"")
        p = Path(cleaned.replace("\\", "/"))
        if p.is_absolute():
            return p.expanduser()
        return self._workspace / p

    # ── Validation ────────────────────────────────────────────────────────────

    def validate_write_path(self, path: Path) -> tuple[bool, str]:
        """
        Safety check before writing a file.
        Returns (ok, reason).
        """
        try:
            resolved = path.resolve()
        except OSError as exc:
            return False, f"Cannot resolve path: {exc}"

        # Block writes into the assistant's own source directory
        agent_src = Path(__file__).resolve().parent
        try:
            resolved.relative_to(agent_src)
            return False, f"Refusing to write into agent source directory: {resolved}"
        except ValueError:
            pass

        return True, ""

    def validate_read_path(self, path: Path) -> tuple[bool, str]:
        """Check a path is safe to read (exists, is a file)."""
        if not path.exists():
            return False, f"Path does not exist: {path}"
        if not path.is_file():
            return False, f"Not a file: {path}"
        return True, ""

    # ── Debug logging ─────────────────────────────────────────────────────────

    def log_state(self) -> None:
        print(f"[WORKSPACE]        {self._workspace}", flush=True)
        print(f"[TARGET DIRECTORY] {self._target_directory or '(none – using workspace)'}", flush=True)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _normalize_raw(self, raw: str) -> Optional[Path]:
        cleaned = raw.strip().strip("'\"")
        if not cleaned:
            return None
        try:
            return Path(cleaned.replace("\\", "/")).expanduser()
        except OSError:
            return None

    def _log_target_set(self, raw: str, resolved: Path) -> None:
        print(f"[TARGET DIRECTORY] Detected from goal: '{raw}' -> {resolved}", flush=True)
