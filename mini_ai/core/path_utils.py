"""
path_utils.py – Lightweight path helpers (backwards-compatible shim).

The main path logic now lives in path_manager.PathManager.
This module is kept for backwards compatibility and re-exports
the most commonly used functions.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .path_manager import (
    extract_user_path,
    extract_windows_path,
    PathManager,
)


def normalize_user_path(path_text: Optional[str]) -> Optional[Path]:
    """Normalize a raw path string into a Path, or return None."""
    if not path_text:
        return None
    cleaned = path_text.strip().strip("'\"")
    if not cleaned:
        return None
    try:
        return Path(cleaned.replace("\\", "/")).expanduser()
    except OSError:
        return None


def resolve_workspace(user_text: str, fallback: "str | Path") -> Path:
    """
    Use the exact path from the user if one is detectable.
    Otherwise fall back safely to *fallback*.

    This function is kept for backwards compatibility.
    New code should use PathManager.set_target_from_goal() instead.
    """
    detected = extract_windows_path(user_text)
    if detected:
        path = normalize_user_path(detected)
        if path:
            return path
    return Path(fallback).expanduser()


SYSTEM_PATH_RULES = """
CRITICAL PATH RULES — Read before every action:

1. If the user provides a filesystem path:
   - ALWAYS use that EXACT path.
   - NEVER invent, shorten, rewrite, or relocate it.
   - NEVER fallback to the workspace default.

2. target_directory ≠ workspace.
   - target_directory = the user's explicit output location.
   - workspace = the AI assistant's own directory.
   - Save all generated files into target_directory.

3. SUPPORTED PATHS:
   - Absolute paths (C:\\..., /home/...)
   - Home-relative paths (~/Downloads, ~/Desktop)
   - Relative paths (resolved against target_directory)

4. NEVER create generated.txt, output.txt, or any collapsed file.
   - Preserve actual file extensions.
   - Preserve actual project structure.

5. For multi-file projects (website / dashboard / React app etc):
   - Generate the full directory structure.
   - index.html + style.css + script.js + assets/ etc.
   - NOT a single collapsed file.

6. You do NOT control filesystem writes.
   - The SYSTEM validates paths and writes files.
   - You emit JSON tool calls with correct paths and content.
   - Report success ONLY after the system confirms the write.
"""
