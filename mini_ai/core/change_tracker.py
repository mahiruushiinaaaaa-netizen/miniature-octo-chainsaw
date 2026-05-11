"""
change_tracker.py – Tracks file modifications during a session using mtime comparison.

Provides efficient file change detection without full directory tree re-scans.
Integrates with the workspace index to trigger incremental re-indexing when
enough files have been modified.

Requirements: 14.1, 14.2, 14.3, 14.5, 14.6, 14.7
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .logger import get_logger

if TYPE_CHECKING:
    from .dep_graph import DependencyGraph

logger = get_logger("change_tracker")

MAX_MODIFIED_FILES = 50
REINDEX_THRESHOLD = 20


class FileChangeTracker:
    """Tracks file modifications during a session using mtime comparison.

    Stores relative paths in the modified files list and uses os.path.getmtime()
    for mtime comparison against a cached value.
    """

    def __init__(self, root: Path | str | None = None):
        """Initialize the tracker.

        Args:
            root: Workspace root directory for computing relative paths.
                  If None, paths are stored as-is.
        """
        self._root: Path | None = Path(root) if root else None
        self._mtime_cache: dict[str, float] = {}
        self._modified_files: list[str] = []  # relative paths, max 50

    def _relative_path(self, path: Path | str) -> str:
        """Convert a path to a relative string for storage."""
        path = Path(path)
        if self._root:
            try:
                return str(path.relative_to(self._root)).replace("\\", "/")
            except ValueError:
                # Path is not under root, store as-is
                return str(path).replace("\\", "/")
        return str(path).replace("\\", "/")

    def check_file(self, path: Path | str) -> bool:
        """Compare stored mtime with disk mtime. Returns True if changed.

        If the file has no cached mtime, it is treated as new (changed).
        Updates the cache on detection of change.

        Args:
            path: Absolute or relative file path to check.

        Returns:
            True if the file's mtime differs from cached value (or is new).
        """
        rel_path = self._relative_path(path)
        abs_path = str(path)

        try:
            disk_mtime = os.path.getmtime(abs_path)
        except OSError as e:
            logger.warn(
                f"Cannot stat file for change check: {rel_path}",
                operation="check_file",
                error=e,
            )
            # If we can't read mtime, invalidate cache entry
            self._mtime_cache.pop(rel_path, None)
            return False

        cached_mtime = self._mtime_cache.get(rel_path)

        if cached_mtime is None:
            # First time seeing this file — cache it and report as changed
            self._mtime_cache[rel_path] = disk_mtime
            self._add_modified(rel_path)
            return True

        if disk_mtime != cached_mtime:
            # File changed on disk
            self._mtime_cache[rel_path] = disk_mtime
            self._add_modified(rel_path)
            return True

        return False

    def record_write(self, path: Path | str) -> None:
        """Update cache after executor writes a file.

        Should be called immediately after a successful file write to keep
        the mtime cache in sync with disk state.

        Args:
            path: The file that was written.
        """
        rel_path = self._relative_path(path)
        abs_path = str(path)

        try:
            disk_mtime = os.path.getmtime(abs_path)
            self._mtime_cache[rel_path] = disk_mtime
        except OSError as e:
            # Cache update failed — invalidate entry and log
            logger.warn(
                f"Cache update failed after write: {rel_path}",
                operation="record_write",
                error=e,
            )
            self._mtime_cache.pop(rel_path, None)

        self._add_modified(rel_path)

    def get_modified_files(self) -> list[str]:
        """Return list of modified files (max 50 most recent entries).

        Returns:
            List of relative file paths modified during this session,
            limited to the most recent 50 entries.
        """
        return list(self._modified_files[-MAX_MODIFIED_FILES:])

    def should_reindex(self) -> bool:
        """Check if enough files have been modified to trigger incremental re-index.

        Returns:
            True when more than 20 files have been modified in this session.
        """
        return len(self._modified_files) > REINDEX_THRESHOLD

    def get_files_for_reindex(self, dep_graph: "DependencyGraph") -> set[str]:
        """Get the set of files that need re-indexing.

        Returns modified files plus their direct importers (files that
        import the modified files), as determined by the dependency graph.

        Args:
            dep_graph: The workspace dependency graph for finding importers.

        Returns:
            Set of relative file paths to re-index.
        """
        files_to_reindex: set[str] = set()

        for rel_path in self._modified_files:
            files_to_reindex.add(rel_path)
            # Add direct importers from the dependency graph
            try:
                importers = dep_graph.invalidate(rel_path)
                files_to_reindex.update(importers)
            except (AttributeError, TypeError) as e:
                logger.warn(
                    f"Could not get importers for {rel_path}",
                    operation="get_files_for_reindex",
                    error=e,
                )

        return files_to_reindex

    def _add_modified(self, rel_path: str) -> None:
        """Add a file to the modified list, maintaining max 50 entries.

        If the file is already in the list, it is moved to the end
        (most recent position). If the list exceeds 50 entries,
        the oldest entry is removed.
        """
        # Remove existing entry to avoid duplicates
        if rel_path in self._modified_files:
            self._modified_files.remove(rel_path)

        self._modified_files.append(rel_path)

        # Enforce max size by trimming oldest entries
        if len(self._modified_files) > MAX_MODIFIED_FILES:
            self._modified_files = self._modified_files[-MAX_MODIFIED_FILES:]

    def invalidate(self, path: Path | str) -> None:
        """Invalidate the cache entry for a file.

        Used when a cache update fails or when a file is known to be stale.

        Args:
            path: The file path to invalidate.
        """
        rel_path = self._relative_path(path)
        self._mtime_cache.pop(rel_path, None)

    def clear(self) -> None:
        """Reset all tracking state. Useful for session boundaries."""
        self._mtime_cache.clear()
        self._modified_files.clear()
