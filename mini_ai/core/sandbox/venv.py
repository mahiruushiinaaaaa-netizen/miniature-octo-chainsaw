import subprocess
import sys
import os
from pathlib import Path
from typing import List, Optional
from .local import LocalSandbox
from .base import SandboxResult
from ..path_manager import PathManager

class VenvSandbox(LocalSandbox):
    """
    A sandbox that uses a Python Virtual Environment to isolate dependencies.
    Automatically creates and manages a venv in the workspace root.
    """
    def __init__(self, pm: PathManager, venv_name: str = ".mini_ai_venv"):
        super().__init__(pm)
        self.venv_path = pm.effective_root / venv_name
        self.venv_bin = self.venv_path / ("Scripts" if os.name == "nt" else "bin")
        self.venv_python = self.venv_bin / ("python.exe" if os.name == "nt" else "python")
        self._ensure_venv()

    def _ensure_venv(self):
        """Create the virtual environment if it doesn't exist."""
        if not self.venv_path.exists():
            try:
                # Use sys.executable to ensure we use the same python version
                subprocess.run([sys.executable, "-m", "venv", str(self.venv_path)], check=True, capture_output=True)
            except subprocess.CalledProcessError as e:
                # Fallback or log error
                pass

    def execute(self, cmd: str, timeout: int = 600) -> SandboxResult:
        """Execute a command, automatically using the venv for python/pip calls."""
        cmd_parts = cmd.split()
        if not cmd_parts:
            return super().execute(cmd, timeout)

        base_cmd = cmd_parts[0].lower()
        
        # Rewrite python and pip commands to use the venv
        if base_cmd == "python":
            cmd = f'"{self.venv_python}"' + cmd[6:]
        elif base_cmd == "pip":
            cmd = f'"{self.venv_python}" -m pip' + cmd[3:]
        
        # Add venv/bin to PATH for the execution
        env = os.environ.copy()
        env["PATH"] = str(self.venv_bin) + os.pathsep + env.get("PATH", "")
        env["VIRTUAL_ENV"] = str(self.venv_path)
        
        # We need to update run_and_stream to accept env, but for now we'll just use the modified cmd
        # and rely on the fact that python/pip are absolute paths.
        
        return super().execute(cmd, timeout)
