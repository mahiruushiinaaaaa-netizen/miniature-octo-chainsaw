"""
Test suite for executor.py - ToolExecutor and batch operations
"""
import sys
import os
import json
import tempfile
import shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest
from pathlib import Path


class TestToolExecutor(unittest.TestCase):
    """Tests for ToolExecutor batch operations."""

    def setUp(self):
        """Create a temporary directory for test files."""
        self.test_dir = Path(tempfile.mkdtemp())
        self.config = None
        self.pm = None
        self.writer = None
        self.executor = None

    def tearDown(self):
        """Clean up temporary directory."""
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_executor(self):
        """Helper to create a ToolExecutor instance."""
        from mini_ai.core.config import Config
        from mini_ai.core.path_manager import PathManager
        from mini_ai.tools.file_writer import SafeFileWriter
        from mini_ai.core.executor import ToolExecutor

        self.config = Config(
            workspace=self.test_dir,
            allow_run=False,
            server_bin=None,
            cli_bin=None,
        )
        self.pm = PathManager(self.config)
        self.writer = SafeFileWriter(self.pm)
        self.executor = ToolExecutor(self.config, self.pm, self.writer)
        return self.executor

    def test_batch_read_files_success(self):
        """Test batch_read_files with existing files."""
        executor = self._create_executor()

        # Create test files
        file1 = self.test_dir / "file1.txt"
        file2 = self.test_dir / "file2.txt"
        file1.write_text("Content of file 1")
        file2.write_text("Content of file 2")

        action = {
            "action": "batch_read_files",
            "files": [str(file1), str(file2)]
        }

        is_final, result_json = executor.execute(action, assume_yes=True)
        result = json.loads(result_json)

        self.assertFalse(is_final)
        self.assertTrue(result["success"])
        self.assertEqual(len(result.get("read", [])), 2)
        self.assertEqual(len(result.get("failed", [])), 0)
        self.assertIn("Content of file 1", result["output"])
        self.assertIn("Content of file 2", result["output"])
        self.assertIn("2 succeeded", result.get("summary", ""))

    def test_batch_read_files_with_missing(self):
        """Test batch_read_files with some missing files."""
        executor = self._create_executor()

        # Create one test file
        file1 = self.test_dir / "file1.txt"
        file1.write_text("Content of file 1")

        action = {
            "action": "batch_read_files",
            "files": [str(file1), str(self.test_dir / "missing.txt")]
        }

        is_final, result_json = executor.execute(action, assume_yes=True)
        result = json.loads(result_json)

        self.assertTrue(result["success"])  # Still success even with partial failure
        self.assertEqual(len(result.get("read", [])), 1)
        self.assertEqual(len(result.get("failed", [])), 1)

    def test_batch_read_files_empty_list(self):
        """Test batch_read_files with empty file list."""
        executor = self._create_executor()

        action = {
            "action": "batch_read_files",
            "files": []
        }

        is_final, result_json = executor.execute(action, assume_yes=True)
        result = json.loads(result_json)

        self.assertFalse(result["success"])
        self.assertIn("No files specified", result["output"])

    def test_batch_delete_files_success(self):
        """Test batch_delete_files with existing files."""
        executor = self._create_executor()

        # Create test files
        file1 = self.test_dir / "file1.txt"
        file2 = self.test_dir / "file2.txt"
        file1.write_text("Content")
        file2.write_text("Content")

        action = {
            "action": "batch_delete_files",
            "paths": [str(file1), str(file2)]
        }

        is_final, result_json = executor.execute(action, assume_yes=True)
        result = json.loads(result_json)

        self.assertFalse(is_final)
        self.assertTrue(result["success"])
        self.assertEqual(len(result.get("deleted", [])), 2)
        self.assertFalse(file1.exists())
        self.assertFalse(file2.exists())

    def test_batch_delete_files_with_directories(self):
        """Test batch_delete_files with directories."""
        executor = self._create_executor()

        # Create test directory with files
        dir1 = self.test_dir / "testdir"
        dir1.mkdir()
        (dir1 / "file.txt").write_text("Content")

        action = {
            "action": "batch_delete_files",
            "paths": [str(dir1)]
        }

        is_final, result_json = executor.execute(action, assume_yes=True)
        result = json.loads(result_json)

        self.assertTrue(result["success"])
        self.assertEqual(len(result.get("deleted", [])), 1)
        self.assertFalse(dir1.exists())

    def test_batch_copy_paths_success(self):
        """Test batch_copy_paths with valid operations."""
        executor = self._create_executor()

        # Create source file
        src = self.test_dir / "source.txt"
        src.write_text("Source content")
        dst = self.test_dir / "dest.txt"

        action = {
            "action": "batch_copy_paths",
            "operations": [{"src": str(src), "dst": str(dst)}]
        }

        is_final, result_json = executor.execute(action, assume_yes=True)
        result = json.loads(result_json)

        self.assertTrue(result["success"])
        self.assertEqual(len(result.get("copied", [])), 1)
        self.assertTrue(dst.exists())
        self.assertEqual(dst.read_text(), "Source content")

    def test_batch_move_paths_success(self):
        """Test batch_move_paths with valid operations."""
        executor = self._create_executor()

        # Create source file
        src = self.test_dir / "source.txt"
        src.write_text("Source content")
        dst = self.test_dir / "dest.txt"

        action = {
            "action": "batch_move_paths",
            "operations": [{"src": str(src), "dst": str(dst)}]
        }

        is_final, result_json = executor.execute(action, assume_yes=True)
        result = json.loads(result_json)

        self.assertTrue(result["success"])
        self.assertEqual(len(result.get("moved", [])), 1)
        self.assertTrue(dst.exists())
        self.assertFalse(src.exists())


class TestToolSchemas(unittest.TestCase):
    """Tests for tool schema validation."""

    def test_batch_read_files_schema(self):
        """Test batch_read_files schema validation."""
        from mini_ai.core.schemas import get_schema

        schema = get_schema("batch_read_files")
        self.assertIsNotNone(schema)

        # Valid action
        valid = {"files": ["file1.txt", "file2.txt"]}
        ok, reason = schema.validate(valid)
        self.assertTrue(ok, f"Should be valid: {reason}")

        # Missing required param
        invalid = {}
        ok, reason = schema.validate(invalid)
        self.assertFalse(ok)  # files is required

    def test_batch_delete_files_schema(self):
        """Test batch_delete_files schema validation."""
        from mini_ai.core.schemas import get_schema

        schema = get_schema("batch_delete_files")
        self.assertIsNotNone(schema)

        valid = {"paths": ["file1.txt", "dir1"]}
        ok, reason = schema.validate(valid)
        self.assertTrue(ok, f"Should be valid: {reason}")

    def test_batch_copy_paths_schema(self):
        """Test batch_copy_paths schema validation."""
        from mini_ai.core.schemas import get_schema

        schema = get_schema("batch_copy_paths")
        self.assertIsNotNone(schema)

        valid = {"operations": [{"src": "a.txt", "dst": "b.txt"}]}
        ok, reason = schema.validate(valid)
        self.assertTrue(ok, f"Should be valid: {reason}")

    def test_batch_move_paths_schema(self):
        """Test batch_move_paths schema validation."""
        from mini_ai.core.schemas import get_schema

        schema = get_schema("batch_move_paths")
        self.assertIsNotNone(schema)

        valid = {"operations": [{"src": "a.txt", "dst": "b.txt"}]}
        ok, reason = schema.validate(valid)
        self.assertTrue(ok, f"Should be valid: {reason}")


class TestExecutorBasicTools(unittest.TestCase):
    """Tests for basic ToolExecutor functionality."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_executor(self):
        from mini_ai.core.config import Config
        from mini_ai.core.path_manager import PathManager
        from mini_ai.tools.file_writer import SafeFileWriter
        from mini_ai.core.executor import ToolExecutor

        config = Config(
            workspace=self.test_dir,
            allow_run=False,
            server_bin=None,
            cli_bin=None,
        )
        pm = PathManager(config)
        writer = SafeFileWriter(pm)
        return ToolExecutor(config, pm, writer)

    def test_result_truncation(self):
        """Test that result() truncates long outputs."""
        executor = self._create_executor()

        long_output = "x" * 3000
        result_json = executor.result(True, long_output)
        result = json.loads(result_json)

        self.assertTrue(result["success"])
        self.assertIn("truncated", result["output"])
        self.assertLess(len(result["output"]), 2500)

    def test_to_json_safe(self):
        """Test _to_json_safe handles Path objects."""
        executor = self._create_executor()

        path_value = Path("/test/path")
        safe_value = executor._to_json_safe(path_value)
        self.assertEqual(safe_value, "/test/path")

        dict_with_path = {"key": Path("/test")}
        safe_dict = executor._to_json_safe(dict_with_path)
        self.assertEqual(safe_dict["key"], "/test")

    def test_tool_answer(self):
        """Test tool_answer returns final result."""
        executor = self._create_executor()

        action = {"action": "answer", "content": "Test answer"}
        is_final, result_json = executor.execute(action, assume_yes=True)
        result = json.loads(result_json)

        self.assertTrue(is_final)
        self.assertTrue(result["success"])
        self.assertIn("Test answer", result["output"])


if __name__ == "__main__":
    unittest.main()
