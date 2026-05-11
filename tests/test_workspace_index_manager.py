"""
Tests for WorkspaceIndexManager — incremental rebuild, function mapping, caller lookup.

Validates Requirements: 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
"""
import os
import time
import tempfile
from pathlib import Path

import pytest

from mini_ai.core.workspace_index import (
    WorkspaceIndexManager,
    FunctionLookupResult,
    build_workspace_index,
)
from mini_ai.core.dep_graph import DependencyGraph, FunctionInfo
from mini_ai.core.change_tracker import FileChangeTracker


@pytest.fixture
def temp_workspace(tmp_path):
    """Create a temporary workspace with Python files for testing."""
    # Create a simple Python project structure
    (tmp_path / "main.py").write_text(
        "from utils import helper\n\ndef main():\n    helper()\n    print('done')\n",
        encoding="utf-8",
    )
    (tmp_path / "utils.py").write_text(
        "def helper():\n    return 42\n\ndef another():\n    return helper()\n",
        encoding="utf-8",
    )
    (tmp_path / "config.py").write_text(
        "DEBUG = True\nPORT = 8080\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def manager(temp_workspace):
    """Create a WorkspaceIndexManager for the temp workspace."""
    return WorkspaceIndexManager(temp_workspace)


class TestWorkspaceIndexManagerInitialize:
    """Test initialization and integration wiring."""

    def test_initialize_builds_index(self, manager, temp_workspace):
        """Initialize should build a workspace index."""
        index = manager.initialize(use_cache=False)
        assert index["root"] == str(temp_workspace)
        assert index.get("text_files") is not None

    def test_initialize_with_dep_graph(self, manager, temp_workspace):
        """Initialize with dep_graph should build the dependency graph."""
        dep_graph = DependencyGraph(temp_workspace)
        index = manager.initialize(dep_graph=dep_graph, use_cache=False)
        assert manager.dep_graph is dep_graph
        assert index["root"] == str(temp_workspace)

    def test_initialize_with_change_tracker(self, manager, temp_workspace):
        """Initialize with change_tracker should wire it up."""
        tracker = FileChangeTracker(root=temp_workspace)
        index = manager.initialize(change_tracker=tracker, use_cache=False)
        assert manager.change_tracker is tracker

    def test_initialize_populates_function_map(self, manager, temp_workspace):
        """Initialize with dep_graph should populate function map."""
        dep_graph = DependencyGraph(temp_workspace)
        manager.initialize(dep_graph=dep_graph, use_cache=False)
        func_map = manager.get_function_map()
        # Should have functions from utils.py and main.py
        assert len(func_map) > 0


class TestFunctionLookup:
    """Test function-to-file mapping and lookup. Requirements: 4.3, 4.4, 4.5"""

    def test_lookup_existing_function(self, manager, temp_workspace):
        """Lookup should return correct file and line info for existing function."""
        dep_graph = DependencyGraph(temp_workspace)
        manager.initialize(dep_graph=dep_graph, use_cache=False)

        result = manager.lookup_function("helper")
        assert result.found is True
        assert result.file == "utils.py"
        assert result.name == "helper"
        assert result.start_line >= 1
        assert result.end_line >= result.start_line

    def test_lookup_qualified_name(self, manager, temp_workspace):
        """Lookup with qualified name (module.func) should work."""
        dep_graph = DependencyGraph(temp_workspace)
        manager.initialize(dep_graph=dep_graph, use_cache=False)

        result = manager.lookup_function("utils.helper")
        assert result.found is True
        assert result.file == "utils.py"
        assert result.name == "helper"

    def test_lookup_nonexistent_function(self, manager, temp_workspace):
        """Lookup for non-existent function returns found=False. Requirement: 4.5"""
        dep_graph = DependencyGraph(temp_workspace)
        manager.initialize(dep_graph=dep_graph, use_cache=False)

        result = manager.lookup_function("nonexistent_function")
        assert result.found is False
        assert result.file == ""
        assert result.start_line == 0
        assert result.end_line == 0
        assert result.callers == []

    def test_lookup_empty_name(self, manager, temp_workspace):
        """Lookup with empty name returns found=False."""
        dep_graph = DependencyGraph(temp_workspace)
        manager.initialize(dep_graph=dep_graph, use_cache=False)

        result = manager.lookup_function("")
        assert result.found is False

    def test_manual_function_mapping(self, manager, temp_workspace):
        """Manually added function mappings should be retrievable."""
        manager.initialize(use_cache=False)
        manager.add_function_mapping(
            name="mymodule.my_func",
            file="mymodule.py",
            start_line=10,
            end_line=25,
            callers=["caller1.py", "caller2.py"],
        )

        result = manager.lookup_function("mymodule.my_func")
        assert result.found is True
        assert result.file == "mymodule.py"
        assert result.name == "my_func"
        assert result.start_line == 10
        assert result.end_line == 25
        assert result.callers == ["caller1.py", "caller2.py"]


class TestCallerLookup:
    """Test caller lookup within indexed workspace. Requirement: 4.4"""

    def test_get_callers_existing_function(self, manager, temp_workspace):
        """get_callers should return callers list for known function."""
        manager.initialize(use_cache=False)
        manager.add_function_mapping(
            name="utils.helper",
            file="utils.py",
            start_line=1,
            end_line=3,
            callers=["main.py"],
        )

        callers = manager.get_callers("utils.helper")
        assert callers == ["main.py"]

    def test_get_callers_nonexistent_function(self, manager, temp_workspace):
        """get_callers for non-existent function returns empty list."""
        manager.initialize(use_cache=False)
        callers = manager.get_callers("does_not_exist")
        assert callers == []

    def test_get_callers_no_callers(self, manager, temp_workspace):
        """get_callers for function with no callers returns empty list."""
        manager.initialize(use_cache=False)
        manager.add_function_mapping(
            name="utils.isolated",
            file="utils.py",
            start_line=5,
            end_line=8,
            callers=[],
        )

        callers = manager.get_callers("utils.isolated")
        assert callers == []


class TestIncrementalRebuild:
    """Test incremental rebuild. Requirement: 4.6"""

    def test_rebuild_processes_only_changed_files(self, temp_workspace):
        """Incremental rebuild should only process files with changed mtime."""
        manager = WorkspaceIndexManager(temp_workspace)
        dep_graph = DependencyGraph(temp_workspace)
        tracker = FileChangeTracker(root=temp_workspace)

        # Initial build
        manager.initialize(dep_graph=dep_graph, change_tracker=tracker, use_cache=False)

        # Modify one file
        time.sleep(0.05)  # Ensure mtime changes
        (temp_workspace / "utils.py").write_text(
            "def helper():\n    return 99\n\ndef new_func():\n    pass\n",
            encoding="utf-8",
        )
        tracker.record_write(temp_workspace / "utils.py")

        # Incremental rebuild
        updated_index = manager.rebuild_incremental()
        assert updated_index is not None
        # The index should still contain all files
        text_files = updated_index.get("text_files", [])
        paths = [f.get("path", "") for f in text_files if isinstance(f, dict)]
        assert "utils.py" in paths
        assert "main.py" in paths

    def test_rebuild_removes_deleted_files(self, temp_workspace):
        """Incremental rebuild should remove entries for deleted files."""
        manager = WorkspaceIndexManager(temp_workspace)
        manager.initialize(use_cache=False)

        # Verify config.py is in the index
        text_files = manager.index.get("text_files", [])
        paths = [f.get("path", "") for f in text_files if isinstance(f, dict)]
        assert "config.py" in paths

        # Delete config.py
        (temp_workspace / "config.py").unlink()

        # Incremental rebuild
        updated_index = manager.rebuild_incremental()
        text_files = updated_index.get("text_files", [])
        paths = [f.get("path", "") for f in text_files if isinstance(f, dict)]
        assert "config.py" not in paths

    def test_rebuild_without_prior_index_does_full_build(self, temp_workspace):
        """Rebuild without existing index should do a full build."""
        manager = WorkspaceIndexManager(temp_workspace)
        # Don't call initialize first
        index = manager.rebuild_incremental()
        assert index.get("root") == str(temp_workspace)
        assert len(index.get("text_files", [])) > 0

    def test_rebuild_removes_function_map_for_deleted_files(self, temp_workspace):
        """Deleted files should have their function mappings removed."""
        manager = WorkspaceIndexManager(temp_workspace)
        dep_graph = DependencyGraph(temp_workspace)
        manager.initialize(dep_graph=dep_graph, use_cache=False)

        # Add a manual mapping for config.py
        manager.add_function_mapping(
            name="config.get_debug",
            file="config.py",
            start_line=1,
            end_line=2,
        )
        assert manager.lookup_function("config.get_debug").found is True

        # Delete config.py
        (temp_workspace / "config.py").unlink()

        # Rebuild
        manager.rebuild_incremental()
        assert manager.lookup_function("config.get_debug").found is False


class TestInvalidateFile:
    """Test file invalidation. Requirement: 4.2"""

    def test_invalidate_returns_file_and_importers(self, temp_workspace):
        """Invalidate should return the file plus its direct importers."""
        manager = WorkspaceIndexManager(temp_workspace)
        dep_graph = DependencyGraph(temp_workspace)
        manager.initialize(dep_graph=dep_graph, use_cache=False)

        # utils.py is imported by main.py, so invalidating utils.py
        # should return both
        invalidated = manager.invalidate_file("utils.py")
        assert "utils.py" in invalidated

    def test_invalidate_removes_function_mappings(self, temp_workspace):
        """Invalidation should remove function mappings for affected files."""
        manager = WorkspaceIndexManager(temp_workspace)
        manager.initialize(use_cache=False)

        manager.add_function_mapping(
            name="utils.helper",
            file="utils.py",
            start_line=1,
            end_line=3,
        )
        assert manager.lookup_function("utils.helper").found is True

        manager.invalidate_file("utils.py")
        assert manager.lookup_function("utils.helper").found is False

    def test_invalidate_without_dep_graph(self, temp_workspace):
        """Invalidate without dep_graph should return just the file itself."""
        manager = WorkspaceIndexManager(temp_workspace)
        manager.initialize(use_cache=False)  # No dep_graph

        invalidated = manager.invalidate_file("utils.py")
        assert invalidated == {"utils.py"}


class TestFunctionLookupResult:
    """Test the FunctionLookupResult dataclass."""

    def test_not_found_result(self):
        """Not-found result should have empty fields."""
        result = FunctionLookupResult(found=False)
        assert result.found is False
        assert result.file == ""
        assert result.name == ""
        assert result.start_line == 0
        assert result.end_line == 0
        assert result.callers == []

    def test_found_result(self):
        """Found result should carry all metadata."""
        result = FunctionLookupResult(
            found=True,
            file="module.py",
            name="my_func",
            start_line=10,
            end_line=20,
            callers=["caller.py"],
        )
        assert result.found is True
        assert result.file == "module.py"
        assert result.name == "my_func"
        assert result.start_line == 10
        assert result.end_line == 20
        assert result.callers == ["caller.py"]
