"""
Test suite for commands.py - CommandRouter and ChatHistory
"""
import sys
import os
import tempfile
import shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest
from pathlib import Path


class TestChatHistory(unittest.TestCase):
    """Tests for ChatHistory class."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_chat_history_append(self):
        """Test appending to chat history."""
        from mini_ai.core.commands import ChatHistory

        history = ChatHistory(self.test_dir)
        history.append("USER", "Hello")
        history.append("ASSISTANT", "Hi there")

        # Check file was created and contains entries
        self.assertTrue(history.path.exists())
        content = history.path.read_text(encoding="utf-8")
        self.assertIn("USER", content)
        self.assertIn("Hello", content)
        self.assertIn("ASSISTANT", content)
        self.assertIn("Hi there", content)

    def test_chat_history_clear(self):
        """Test clearing chat history."""
        from mini_ai.core.commands import ChatHistory

        history = ChatHistory(self.test_dir)
        history.append("USER", "Hello")
        self.assertTrue(history.path.exists())

        history.clear()
        self.assertFalse(history.path.exists())


class TestCommandRouterBasic(unittest.TestCase):
    """Tests for CommandRouter basic functionality."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_router(self, allow_run=False):
        """Helper to create a CommandRouter instance."""
        from mini_ai.core.config import Config
        from mini_ai.core.commands import CommandRouter

        config = Config(
            workspace=self.test_dir,
            allow_run=allow_run,
            llama_server_bin=None,
            llama_cli_bin=None,
        )
        return CommandRouter(config)

    def test_handle_empty_command(self):
        """Test handling empty command."""
        router = self._create_router()
        result = router.handle("")
        self.assertTrue(result)  # Empty command returns True (continue)

    def test_handle_quit_commands(self):
        """Test quit commands."""
        router = self._create_router()

        self.assertFalse(router.handle("/quit"))
        self.assertFalse(router.handle("/exit"))
        self.assertFalse(router.handle("exit"))

    def test_handle_help_command(self):
        """Test /help command."""
        router = self._create_router()
        result = router.handle("/help")
        self.assertTrue(result)  # Continue after help

    def test_handle_clear_command(self):
        """Test /clear command."""
        router = self._create_router()
        # Add some history first
        router.chat_history.append("USER", "Test")
        self.assertTrue(router.chat_history.path.exists())

        result = router.handle("/clear")
        self.assertTrue(result)
        # History should be cleared
        self.assertFalse(router.chat_history.path.exists())

    def test_handle_add_command(self):
        """Test /add command."""
        router = self._create_router()

        # Create a test file
        test_file = self.test_dir / "test.py"
        test_file.write_text("print('hello')")

        result = router.handle(f"/add {test_file}")
        self.assertTrue(result)
        self.assertIn(str(test_file), router.added_files)

    def test_handle_drop_command(self):
        """Test /drop command."""
        router = self._create_router()

        # Add then drop
        test_file = self.test_dir / "test.py"
        router.added_files.add(str(test_file))

        result = router.handle("/drop")
        self.assertTrue(result)
        self.assertEqual(len(router.added_files), 0)

    def test_handle_compact_command(self):
        """Test /compact and /raw commands."""
        router = self._create_router()

        result = router.handle("/compact")
        self.assertTrue(result)

        result = router.handle("/raw")
        self.assertTrue(result)

    def test_handle_verbose_command(self):
        """Test /verbose command."""
        router = self._create_router()
        self.assertFalse(router.verbose)

        result = router.handle("/verbose")
        self.assertTrue(result)
        self.assertTrue(router.verbose)

        result = router.handle("/verbose")
        self.assertFalse(router.verbose)

    def test_handle_orchestrator_command(self):
        """Test /orchestrator command."""
        router = self._create_router()
        self.assertFalse(router.use_orchestrator)

        result = router.handle("/orchestrator")
        self.assertTrue(result)
        self.assertTrue(router.use_orchestrator)

    def test_handle_shell_disabled(self):
        """Test !shell command when disabled."""
        router = self._create_router(allow_run=False)
        result = router.handle("!echo hello")
        self.assertTrue(result)  # Continue, but command not run

    def test_added_files_tracking(self):
        """Test that added_files set tracks files correctly."""
        router = self._create_router()

        file1 = self.test_dir / "file1.py"
        file2 = self.test_dir / "file2.py"
        file1.write_text("content")
        file2.write_text("content")

        router.handle(f"/add {file1}")
        router.handle(f"/add {file2}")

        self.assertEqual(len(router.added_files), 2)
        self.assertIn(str(file1), router.added_files)
        self.assertIn(str(file2), router.added_files)

    def test_last_goal_tracking(self):
        """Test that last_goal is tracked."""
        router = self._create_router()

        # Mock run_agent to avoid actual execution
        original_run_agent = router.run_agent
        router.run_agent = lambda cmd: setattr(router, 'last_goal', cmd)

        router.handle("create a function")
        self.assertEqual(router.last_goal, "create a function")


class TestCommandRouterFileOps(unittest.TestCase):
    """Tests for CommandRouter file operations."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_router(self, allow_run=False):
        from mini_ai.core.config import Config
        from mini_ai.core.commands import CommandRouter

        config = Config(
            workspace=self.test_dir,
            allow_run=allow_run,
            llama_server_bin=None,
            llama_cli_bin=None,
        )
        return CommandRouter(config)

    def test_handle_lint_existing_file(self):
        """Test /lint on existing Python file."""
        router = self._create_router()

        test_file = self.test_dir / "test.py"
        test_file.write_text("x = 1\n")  # Valid Python

        result = router.handle(f"/lint {test_file}")
        self.assertTrue(result)

    def test_handle_lint_nonexistent_file(self):
        """Test /lint on non-existent file."""
        router = self._create_router()

        result = router.handle("/lint nonexistent.py")
        self.assertTrue(result)  # Continue even if file not found

    def test_handle_read_command(self):
        """Test /read command."""
        router = self._create_router()

        test_file = self.test_dir / "test.txt"
        test_file.write_text("Hello World")

        result = router.handle(f"/read {test_file}")
        self.assertTrue(result)

    def test_handle_ls_command(self):
        """Test /ls command."""
        router = self._create_router()

        # Create some files
        (self.test_dir / "file1.txt").write_text("content")
        (self.test_dir / "file2.txt").write_text("content")

        result = router.handle("/ls")
        self.assertTrue(result)

    def test_handle_map_command(self):
        """Test /map command."""
        router = self._create_router()

        # Create some structure
        subdir = self.test_dir / "subdir"
        subdir.mkdir()
        (subdir / "file.txt").write_text("content")

        result = router.handle("/map")
        self.assertTrue(result)


class TestCommandRouterSlashParsing(unittest.TestCase):
    """Tests for slash command parsing."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_router(self):
        from mini_ai.core.config import Config
        from mini_ai.core.commands import CommandRouter

        config = Config(
            workspace=self.test_dir,
            allow_run=False,
            llama_server_bin=None,
            llama_cli_bin=None,
        )
        return CommandRouter(config)

    def test_handle_unknown_slash_command(self):
        """Test unknown slash command."""
        router = self._create_router()

        result = router.handle("/unknown_command")
        self.assertTrue(result)  # Continue, but show unknown message

    def test_handle_slash_command_with_args(self):
        """Test slash command with arguments."""
        router = self._create_router()

        # Test with various argument patterns
        test_file = self.test_dir / "test.py"
        test_file.write_text("print('hello')")

        result = router.handle(f"/add {test_file} extra args")
        self.assertTrue(result)
        # Only first valid file should be added


if __name__ == "__main__":
    unittest.main()
