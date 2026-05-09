"""
file_writer.py – Safe, verified file writing layer.

DESIGN RULES
============
- The AI never directly writes files.
- All writes flow through SafeFileWriter.
- Every write is preceded by path validation.
- Success is only reported after verified disk write.
- Overwrite always requires explicit confirmation (or assume_yes).
- Multi-file project structures are built atomically.

FORBIDDEN outputs:
  - generated.txt
  - collapsed single-file outputs for multi-file requests

REQUIRED:
  - Actual file extensions
  - Actual project structure
  - Per-file success verification
"""
from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..core.approval import should_auto_approve
from ..ui import err, ok
from ..core.path_manager import PathManager
from ..ui.choice_ui import confirm



# ─── Result types ─────────────────────────────────────────────────────────────

@dataclass
class WriteResult:
    path: Path
    success: bool
    error: str = ""
    overwritten: bool = False
    size_bytes: int = 0

    def __str__(self) -> str:
        if self.success:
            tag = "overwritten" if self.overwritten else "created"
            return f"✓ {tag}: {self.path} ({self.size_bytes} bytes)"
        return f"✕ failed [{self.path}]: {self.error}"


@dataclass
class WriteBatch:
    results: list[WriteResult] = field(default_factory=list)

    @property
    def written(self) -> list[Path]:
        return [r.path for r in self.results if r.success]

    @property
    def failed(self) -> list[str]:
        return [str(r) for r in self.results if not r.success]

    @property
    def all_ok(self) -> bool:
        return bool(self.results) and all(r.success for r in self.results)

    def summary(self) -> str:
        lines = [str(r) for r in self.results]
        return "\n".join(lines) if lines else "(no files written)"


# ─── Forbidden filenames ───────────────────────────────────────────────────────

_FORBIDDEN_NAMES = frozenset({
    "generated.txt",
    "output.txt",
    "result.txt",
    "code.txt",
})


def _is_forbidden_filename(name: str) -> bool:
    return name.strip().lower() in _FORBIDDEN_NAMES


# ─── Multi-file project detection ─────────────────────────────────────────────

_WEB_PROJECT_TRIGGERS = (
    "html css js",
    "html, css, js",
    "website",
    "web app",
    "web application",
    "frontend",
    "dashboard",
    "calculator",
    "landing page",
    "react app",
    "vue app",
    "svelte app",
    "next.js",
    "node app",
    "node application",
    "express app",
    "full stack",
)


def detect_web_project_request(user_message: str) -> bool:
    """Return True when the user is requesting a multi-file web project."""
    text = user_message.lower()
    return any(trigger in text for trigger in _WEB_PROJECT_TRIGGERS)


def suggest_project_structure(project_type: str) -> dict[str, str]:
    """
    Return a skeleton file map for common project types.
    Keys are relative paths; values are placeholder descriptions.
    """
    pt = project_type.lower()

    if any(x in pt for x in ("react", "vite")):
        return {
            "index.html": "HTML entry point",
            "src/main.jsx": "React entry",
            "src/App.jsx": "Root component",
            "src/App.css": "Component styles",
            "src/index.css": "Global styles",
            "src/components/.gitkeep": "",
            "package.json": "npm config",
            "vite.config.js": "Vite config",
        }

    if "node" in pt or "express" in pt:
        return {
            "index.js": "Entry point",
            "routes/index.js": "Routes",
            "package.json": "npm config",
            ".env.example": "Environment template",
        }

    # Default: plain HTML/CSS/JS
    return {
        "index.html": "HTML entry",
        "style.css": "Stylesheet",
        "script.js": "JavaScript",
        "assets/": "",
    }


# ─── SafeFileWriter ───────────────────────────────────────────────────────────

class SafeFileWriter:
    """
    Controls all file system writes.

    The AI model code MUST NOT write files directly —
    every write must go through this class.
    """

    def __init__(self, path_manager: PathManager) -> None:
        self._pm = path_manager

    # ── Single file ───────────────────────────────────────────────────────────

    def write_file(
        self,
        path: Path,
        content: str,
        *,
        assume_yes: bool = False,
        allow_overwrite: bool = True,
    ) -> WriteResult:
        """Write a single file with full safety checks."""

        # Forbidden filename check
        if _is_forbidden_filename(path.name):
            return WriteResult(
                path=path,
                success=False,
                error=(
                    f"Forbidden filename '{path.name}'. "
                    "The system must never create generated.txt or similar collapsed output files. "
                    "Use the actual intended filename with the correct extension."
                ),
            )

        # Validate path is safe to write
        ok_write, reason = self._pm.validate_write_path(path)
        if not ok_write:
            return WriteResult(path=path, success=False, error=reason)

        # Overwrite check
        overwritten = False
        if path.exists():
            if not allow_overwrite:
                return WriteResult(path=path, success=False, error="overwrite not allowed")
            if not self._confirm_overwrite(path, assume_yes):
                return WriteResult(path=path, success=False, error="overwrite cancelled by user")
            overwritten = True

        # Create parent dirs
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return WriteResult(path=path, success=False, error=f"mkdir failed: {exc}")

        # Write
        try:
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return WriteResult(path=path, success=False, error=f"write failed: {exc}")

        # Verify
        if not path.exists():
            return WriteResult(path=path, success=False, error="file missing after write (disk error?)")

        size = path.stat().st_size
        ok(f"Wrote {path}")
        return WriteResult(path=path, success=True, overwritten=overwritten, size_bytes=size)

    # ── Batch write ───────────────────────────────────────────────────────────

    def write_batch(
        self,
        files: list[dict],
        *,
        assume_yes: bool = False,
    ) -> WriteBatch:
        """
        Write multiple files from a list of {"path": ..., "content": ...} dicts.
        Paths are resolved through PathManager.
        """
        batch = WriteBatch()

        if not files:
            return batch

        if len(files) == 1:
            item = files[0]
            if not isinstance(item, dict):
                batch.results.append(
                    WriteResult(path=Path("?"), success=False, error="invalid file item (not a dict)")
                )
                return batch

            path_text = str(item.get("path", "")).strip()
            content = str(item.get("content", ""))

            if not path_text:
                batch.results.append(
                    WriteResult(path=Path("?"), success=False, error="missing 'path' in file item")
                )
                return batch

            path = self._pm.resolve_target(path_text)
            result = self.write_file(path, content, assume_yes=assume_yes)
            batch.results.append(result)
            return batch

        return self._write_batch_atomic(files, assume_yes=assume_yes)

    def _write_batch_atomic(self, files: list[dict], *, assume_yes: bool) -> WriteBatch:
        batch = WriteBatch()
        prepared: list[tuple[Path, str, bool]] = []

        for index, item in enumerate(files):
            if not isinstance(item, dict):
                batch.results.append(
                    WriteResult(path=Path("?"), success=False, error="invalid file item (not a dict)")
                )
                for _ in files[index + 1:]:
                    batch.results.append(
                        WriteResult(path=Path("?"), success=False, error="batch aborted")
                    )
                return batch

            path_text = str(item.get("path", "")).strip()
            content = str(item.get("content", ""))

            if not path_text:
                batch.results.append(
                    WriteResult(path=Path("?"), success=False, error="missing 'path' in file item")
                )
                for _ in files[index + 1:]:
                    batch.results.append(
                        WriteResult(path=Path("?"), success=False, error="batch aborted")
                    )
                return batch

            if _is_forbidden_filename(Path(path_text).name):
                batch.results.append(
                    WriteResult(
                        path=Path(path_text),
                        success=False,
                        error=(
                            f"Forbidden filename '{Path(path_text).name}'. "
                            "Use the actual intended filename with the correct extension."
                        ),
                    )
                )
                for _ in files[index + 1:]:
                    batch.results.append(
                        WriteResult(path=Path("?"), success=False, error="batch aborted")
                    )
                return batch

            path = self._pm.resolve_target(path_text)
            ok_write, reason = self._pm.validate_write_path(path)
            if not ok_write:
                batch.results.append(WriteResult(path=path, success=False, error=reason))
                for _ in files[index + 1:]:
                    batch.results.append(
                        WriteResult(path=Path("?"), success=False, error="batch aborted")
                    )
                return batch

            overwritten = False
            if path.exists():
                if path.is_dir():
                    batch.results.append(
                        WriteResult(path=path, success=False, error="path is a directory")
                    )
                    for _ in files[index + 1:]:
                        batch.results.append(
                            WriteResult(path=Path("?"), success=False, error="batch aborted")
                        )
                    return batch
                if not self._confirm_overwrite(path, assume_yes):
                    batch.results.append(
                        WriteResult(path=path, success=False, error="overwrite cancelled by user")
                    )
                    for _ in files[index + 1:]:
                        batch.results.append(
                            WriteResult(path=Path("?"), success=False, error="batch aborted")
                        )
                    return batch
                overwritten = True

            prepared.append((path, content, overwritten))

        temp_entries: list[tuple[Path, Path, bool]] = []
        for path, content, overwritten in prepared:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    "w",
                    encoding="utf-8",
                    delete=False,
                    dir=str(path.parent),
                    prefix=".mini_ai_tmp_",
                    suffix=".tmp",
                ) as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                    temp_path = Path(handle.name)
                temp_entries.append((path, temp_path, overwritten))
            except Exception as exc:
                for _, temp_path, _ in temp_entries:
                    temp_path.unlink(missing_ok=True)
                batch.results.append(
                    WriteResult(path=path, success=False, error=f"temp write failed: {exc}")
                )
                return batch

        backups: list[Path] = []
        moved: list[tuple[Path, Path | None, bool]] = []
        try:
            for path, temp_path, overwritten in temp_entries:
                backup_path = None
                if path.exists():
                    backup_handle = tempfile.NamedTemporaryFile(
                        "wb",
                        delete=False,
                        dir=str(path.parent),
                        prefix=".mini_ai_bak_",
                        suffix=".bak",
                    )
                    backup_path = Path(backup_handle.name)
                    backup_handle.close()
                    shutil.copy2(str(path), str(backup_path))
                    backups.append(backup_path)

                temp_path.replace(path)
                moved.append((path, backup_path, overwritten))

            for path, backup_path, _ in moved:
                if backup_path and backup_path.exists():
                    backup_path.unlink(missing_ok=True)

            for path, _, overwritten in moved:
                size = path.stat().st_size if path.exists() else 0
                ok(f"Wrote {path}")
                batch.results.append(
                    WriteResult(path=path, success=True, overwritten=overwritten, size_bytes=size)
                )

            return batch
        except Exception as exc:
            for path, backup_path, _ in reversed(moved):
                try:
                    if backup_path and backup_path.exists():
                        backup_path.replace(path)
                    else:
                        if path.exists():
                            path.unlink()
                except Exception:
                    pass
            for _, temp_path, _ in temp_entries:
                temp_path.unlink(missing_ok=True)
            for backup_path in backups:
                backup_path.unlink(missing_ok=True)
            for path, _, _ in prepared:
                batch.results.append(
                    WriteResult(path=path, success=False, error=f"batch commit failed: {exc}")
                )
            return batch

    # ── Directory creation ────────────────────────────────────────────────────

    def make_dir(self, path: Path) -> tuple[bool, str]:
        """Create a directory (and parents) safely."""
        try:
            path.mkdir(parents=True, exist_ok=True)
            ok(f"Created directory {path}")
            return True, str(path)
        except OSError as exc:
            err(f"mkdir failed: {exc}")
            return False, str(exc)

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _confirm_overwrite(path: Path, assume_yes: bool) -> bool:
        if should_auto_approve(destructive=True, assume_yes=assume_yes):
            print(f"[AUTO] Overwriting {path}", flush=True)
            return True
        return confirm(f"Overwrite {path}?")
