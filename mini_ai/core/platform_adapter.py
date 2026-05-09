"""
platform_adapter.py – OS-agnostic interface for filesystem and process operations.
Normalizes behavior between Windows, Linux, and macOS.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional, Union

from .environment import get_environment, OSType

class PlatformAdapter:
    """Adapts operations to the current platform."""
    
    def __init__(self):
        self.env = get_environment()
        self.is_windows = self.env.os_type == OSType.WINDOWS
        self.is_linux = self.env.os_type == OSType.LINUX
        self.is_macos = self.env.os_type == OSType.MACOS

    def create_file(self, path: Union[str, Path]) -> bool:
        """Create an empty file at the given path (like 'touch')."""
        path = Path(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
            return path.exists()
        except Exception:
            return False

    def create_directory(self, path: Union[str, Path]) -> bool:
        """Create a directory and its parents (like 'mkdir -p')."""
        path = Path(path)
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path.exists() and path.is_dir()
        except Exception:
            return False

    def remove_path(self, path: Union[str, Path], recursive: bool = False) -> bool:
        """Remove a file or directory."""
        path = Path(path)
        if not path.exists():
            return True
        try:
            if path.is_dir():
                if recursive:
                    shutil.rmtree(path)
                else:
                    path.rmdir()
            else:
                path.unlink()
            return not path.exists()
        except Exception:
            return False

    def copy_path(self, src: Union[str, Path], dst: Union[str, Path]) -> bool:
        """Copy a file or directory."""
        src = Path(src)
        dst = Path(dst)
        try:
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            return dst.exists()
        except Exception:
            return False

    def move_path(self, src: Union[str, Path], dst: Union[str, Path]) -> bool:
        """Move a file or directory."""
        src = Path(src)
        dst = Path(dst)
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return dst.exists() and not src.exists()
        except Exception:
            return False

    def list_directory(self, path: Union[str, Path]) -> list[str]:
        """List contents of a directory."""
        path = Path(path)
        if not path.exists() or not path.is_dir():
            return []
        try:
            return [f.name + ("/" if f.is_dir() else "") for f in path.iterdir()]
        except Exception:
            return []

    def get_shell_command(self, cmd: str) -> list[str]:
        """Convert a shell command string to a list for subprocess.run (platform-aware)."""
        if self.is_windows:
            return ["cmd", "/c", cmd]
        return ["/bin/sh", "-c", cmd]

# Singleton
_adapter = PlatformAdapter()

def get_platform_adapter() -> PlatformAdapter:
    return _adapter
