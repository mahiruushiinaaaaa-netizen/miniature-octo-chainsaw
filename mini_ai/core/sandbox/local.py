from pathlib import Path
from typing import List, Optional
from .base import SandboxProvider, SandboxResult
from .session import PersistentShellSession
from ..path_manager import PathManager
import shutil
import os

class LocalSandbox(SandboxProvider):
    """
    A local sandbox that executes commands in a persistent stateful shell.
    Maintains CWD and environment across calls.
    """
    def __init__(self, pm: PathManager):
        self.pm = pm
        self._session = PersistentShellSession(cwd=pm.effective_root)

    def execute(self, cmd: str, timeout: int = 600) -> SandboxResult:
        # Use the persistent session
        return self._session.execute(cmd, timeout)

    def write_file(self, path: str, content: str) -> bool:
        target = self.pm.resolve_target(path)
        ok, reason = self.pm.validate_write_path(target)
        if not ok:
            return False
        
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return True
        except Exception:
            return False

    def read_file(self, path: str) -> Optional[str]:
        target = self.pm.resolve_target(path)
        if not target.exists() or not target.is_file():
            return None
        try:
            return target.read_text(encoding="utf-8")
        except Exception:
            return None

    def list_dir(self, path: str) -> List[str]:
        target = self.pm.resolve_target(path)
        if not target.exists() or not target.is_dir():
            return []
        try:
            return [f.name for f in target.iterdir()]
        except Exception:
            return []

    @property
    def cwd(self) -> Path:
        return self._session.cwd
    
    @cwd.setter
    def cwd(self, value: Path):
        if value != self._session.cwd:
            # Sync the shell's CWD
            self._session.execute(f'cd "{value}"')

    def close(self):
        """Clean up session."""
        if self._session:
            self._session.close()
