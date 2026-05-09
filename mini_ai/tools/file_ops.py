"""
file_ops.py – File operation helpers used by legacy command paths.

NOTE: All new write operations should go through file_writer.SafeFileWriter.
      These functions are kept for backwards-compatibility with /read, /edit, /make.
"""
from __future__ import annotations

from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..core.config import Config

from .code_utils import extract_python_code
from ..ui import err, ok
from .file_writer import detect_web_project_request



def clean_path(path_text: str) -> Path:
    return Path(path_text.strip().strip("'\"")).expanduser()


def read_file_command(path_text: str) -> None:
    path = clean_path(path_text)
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        ok("File read")
        print("\n" + content + "\n")
    except FileNotFoundError:
        err(f"File not found: {path}")
    except OSError as exc:
        err(f"Could not read file: {exc}")


def filename_for(description: str) -> str:
    """Infer a sensible filename from a natural-language description."""
    lowered = description.lower()
    if "calculator" in lowered:
        return "calculator.py"
    if "snake" in lowered:
        return "snake_game.py"
    if "game" in lowered:
        return "game.py"
    if "todo" in lowered or "to-do" in lowered:
        return "todo.py"
    if "website" in lowered or "html" in lowered:
        return "index.html"
    if "python" in lowered or "script" in lowered:
        return "main.py"
    return "main.py"


def make_file(config: Config, folder_text: str, description: str) -> None:
    folder = clean_path(folder_text)
    folder.mkdir(parents=True, exist_ok=True)

    target = folder / filename_for(description)
    prompt = (
        "Create the full file contents for this request. "
        "Return only file contents. No Markdown. No explanation.\n\n"
        f"Request: {description}\n"
    f"Target file: {target}\n"
    )
    from ..core.backend import generate
    content = generate(config, prompt, max_tokens=1200)
    if not content:
        return

    if target.suffix == ".py":
        content = extract_python_code(content)
        try:
            compile(content, str(target), "exec")
        except SyntaxError as exc:
            err(f"Generated Python syntax error: {exc}")
            print(content)
            return

    target.write_text(content, encoding="utf-8")
    ok(f"Created {target}")


def edit_file(config: Config, path_text: str) -> None:
    path = clean_path(path_text)
    if not path.exists():
        err(f"File not found: {path}")
        return

    source = path.read_text(encoding="utf-8", errors="replace")
    prompt = (
        "Improve this file. Return the complete improved file only. "
        "No Markdown fences.\n\n"
        + source
    )
    from ..core.backend import generate
    content = generate(config, prompt, max_tokens=1400)
    if not content:
        return

    print("\n" + content + "\n")
    answer = input("Apply changes? (y/N)> ").strip().lower()
    if answer != "y":
        print("Cancelled")
        return

    backup = path.with_suffix(path.suffix + ".bak")
    backup.write_text(source, encoding="utf-8")
    path.write_text(extract_python_code(content), encoding="utf-8")
    ok(f"File saved. Backup: {backup}")


def is_probably_text(obj) -> bool:
    """Heuristic: determine whether `obj` (path/str/bytes) is probably text.

    Accepts a `pathlib.Path`, file path string, or raw bytes. Returns True
    if the extension suggests text or if the first chunk contains no NUL
    bytes. Falls back to True on errors to avoid blocking common flows.
    """
    try:
        # Raw bytes/bytearray
        if isinstance(obj, (bytes, bytearray)):
            sample = bytes(obj[:512])
            return b"\x00" not in sample

        # Path or string
        p = Path(obj)
        ext = p.suffix.lower()
        text_exts = {
            ".txt",
            ".md",
            ".py",
            ".json",
            ".yaml",
            ".yml",
            ".html",
            ".htm",
            ".csv",
            ".ini",
            ".cfg",
        }
        if ext in text_exts:
            return True

        # Try reading a small sample and look for NUL bytes
        if p.exists() and p.is_file():
            with p.open("rb") as fh:
                sample = fh.read(512)
            return b"\x00" not in sample

        # Default to True (conservative) when unsure
        return True
    except Exception:
        return True
