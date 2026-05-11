"""
batch.py – Parallel file operations with thread pooling.

Provides concurrent batch read and write operations for multi-file tasks,
using ThreadPoolExecutor to maximize I/O throughput on laptop hardware.

Key design decisions:
- MAX_BATCH_SIZE=50 prevents resource exhaustion on constrained systems
- MAX_WORKERS=4 balances parallelism with thread overhead on typical laptops
- Per-file failure isolation: one bad file never aborts the entire batch
- Duration tracking for performance monitoring
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .path_manager import PathManager
    from ..tools.file_writer import SafeFileWriter


# ─── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class FileResult:
    """Result of a single file operation in a batch."""
    path: str
    success: bool
    content: str | None = None  # For reads
    error: str | None = None    # For failures
    size: int = 0


@dataclass
class BatchResult:
    """Aggregated result of a batch file operation."""
    succeeded: list[FileResult] = field(default_factory=list)
    failed: list[FileResult] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def summary(self) -> str:
        return f"{len(self.succeeded)} ok, {len(self.failed)} failed in {self.duration_ms:.0f}ms"

    @property
    def total(self) -> int:
        return len(self.succeeded) + len(self.failed)


# ─── Batch Executor ───────────────────────────────────────────────────────────


class BatchExecutor:
    """
    Parallel file operations with thread pooling.

    Usage:
        executor = BatchExecutor()
        result = executor.batch_read(["file1.py", "file2.py"], path_manager)
        result = executor.batch_write([{"path": "out.py", "content": "..."}], writer)
    """

    MAX_BATCH_SIZE = 50
    MAX_WORKERS = 4

    def batch_read(self, paths: list[str], pm: "PathManager") -> BatchResult:
        """
        Read files concurrently. Returns per-file results.

        Each file is read independently — a failure on one file does not
        affect the others. Results are consolidated into a BatchResult
        with succeeded/failed lists.

        Args:
            paths: List of file path strings to read.
            pm: PathManager instance for path resolution and validation.

        Returns:
            BatchResult with per-file content or error information.

        Raises:
            ValueError: If batch size exceeds MAX_BATCH_SIZE.
        """
        if len(paths) > self.MAX_BATCH_SIZE:
            raise ValueError(
                f"Batch size {len(paths)} exceeds maximum of {self.MAX_BATCH_SIZE}. "
                f"Split into smaller batches."
            )

        result = BatchResult()
        start = time.perf_counter()

        if not paths:
            result.duration_ms = 0.0
            return result

        def _read_one(path_text: str) -> FileResult:
            """Read a single file, returning FileResult."""
            try:
                resolved = pm.resolve_target(path_text)
                ok_read, reason = pm.validate_read_path(resolved)
                if not ok_read:
                    return FileResult(
                        path=path_text,
                        success=False,
                        error=reason,
                    )
                content = resolved.read_text(encoding="utf-8")
                size = resolved.stat().st_size
                return FileResult(
                    path=path_text,
                    success=True,
                    content=content,
                    size=size,
                )
            except Exception as exc:
                return FileResult(
                    path=path_text,
                    success=False,
                    error=str(exc),
                )

        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as pool:
            futures = {pool.submit(_read_one, p): p for p in paths}
            for future in as_completed(futures):
                file_result = future.result()
                if file_result.success:
                    result.succeeded.append(file_result)
                else:
                    result.failed.append(file_result)

        result.duration_ms = (time.perf_counter() - start) * 1000
        return result

    def batch_write(self, files: list[dict], writer: "SafeFileWriter") -> BatchResult:
        """
        Write files concurrently. Returns per-file status.

        Each file write is handled independently — a failure on one file
        does not abort the others. Uses SafeFileWriter.write_file for
        each individual write to maintain safety checks.

        Args:
            files: List of dicts with "path" and "content" keys.
            writer: SafeFileWriter instance for safe file writing.

        Returns:
            BatchResult with per-file success/failure status.

        Raises:
            ValueError: If batch size exceeds MAX_BATCH_SIZE.
        """
        if len(files) > self.MAX_BATCH_SIZE:
            raise ValueError(
                f"Batch size {len(files)} exceeds maximum of {self.MAX_BATCH_SIZE}. "
                f"Split into smaller batches."
            )

        result = BatchResult()
        start = time.perf_counter()

        if not files:
            result.duration_ms = 0.0
            return result

        def _write_one(file_item: dict) -> FileResult:
            """Write a single file, returning FileResult."""
            try:
                if not isinstance(file_item, dict):
                    return FileResult(
                        path="?",
                        success=False,
                        error="Invalid file item (not a dict)",
                    )

                path_text = str(file_item.get("path", "")).strip()
                content = str(file_item.get("content", ""))

                if not path_text:
                    return FileResult(
                        path="?",
                        success=False,
                        error="Missing 'path' in file item",
                    )

                # Resolve path through the writer's path manager
                resolved = writer._pm.resolve_target(path_text)

                # Use SafeFileWriter for the actual write (with safety checks)
                write_result = writer.write_file(
                    resolved, content, assume_yes=True, allow_overwrite=True
                )

                if write_result.success:
                    return FileResult(
                        path=path_text,
                        success=True,
                        size=write_result.size_bytes,
                    )
                else:
                    return FileResult(
                        path=path_text,
                        success=False,
                        error=write_result.error,
                    )
            except Exception as exc:
                path_text = str(file_item.get("path", "?")) if isinstance(file_item, dict) else "?"
                return FileResult(
                    path=path_text,
                    success=False,
                    error=str(exc),
                )

        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as pool:
            futures = {pool.submit(_write_one, f): f for f in files}
            for future in as_completed(futures):
                file_result = future.result()
                if file_result.success:
                    result.succeeded.append(file_result)
                else:
                    result.failed.append(file_result)

        result.duration_ms = (time.perf_counter() - start) * 1000
        return result
