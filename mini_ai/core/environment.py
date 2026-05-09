"""
environment.py – Comprehensive environment detection and adaptation.

Detects:
- Operating system and platform
- Available dependencies and versions
- Runtime capabilities
- Resource limits
- Shell environment
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Callable


class OSType(Enum):
    """Operating system types."""
    WINDOWS = auto()
    LINUX = auto()
    MACOS = auto()
    UNKNOWN = auto()


class ShellType(Enum):
    """Detected shell types."""
    POWERSHELL = auto()
    CMD = auto()
    BASH = auto()
    ZSH = auto()
    FISH = auto()
    UNKNOWN = auto()


@dataclass
class RuntimeEnvironment:
    """Complete runtime environment snapshot."""
    os_type: OSType
    os_version: str
    shell: ShellType
    python_version: str
    cpu_count: int
    ram_mb: Optional[int] = None
    home_dir: Path = field(default_factory=lambda: Path.home())
    temp_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()))
    is_ci: bool = False
    is_tty: bool = False
    supports_ansi: bool = False
    available_binaries: dict[str, Optional[str]] = field(default_factory=dict)
    package_managers: dict[str, bool] = field(default_factory=dict)
    
    def __post_init__(self):
        # Lazy evaluation of RAM
        if self.ram_mb is None:
            self.ram_mb = self._detect_ram()

    def _detect_ram(self) -> Optional[int]:
        """Detect available RAM in MB."""
        try:
            if self.os_type == OSType.WINDOWS:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]
                memStatus = MEMORYSTATUSEX()
                memStatus.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                if kernel32.GlobalMemoryStatusEx(ctypes.byref(memStatus)):
                    return int(memStatus.ullTotalPhys / (1024 * 1024))
            elif self.os_type in (OSType.LINUX, OSType.MACOS):
                import subprocess
                result = subprocess.run(
                    ["free", "-m"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    lines = result.stdout.strip().split("\n")
                    if len(lines) > 1:
                        parts = lines[1].split()
                        if len(parts) > 1:
                            return int(parts[1])
        except Exception:
            pass
        return None


class EnvironmentDetector:
    """Detects and analyzes the runtime environment."""
    
    def __init__(self):
        self._env: Optional[RuntimeEnvironment] = None
    
    def detect(self) -> RuntimeEnvironment:
        """Perform full environment detection."""
        if self._env is not None:
            return self._env
        
        os_type = self._detect_os()
        
        self._env = RuntimeEnvironment(
            os_type=os_type,
            os_version=self._detect_os_version(),
            shell=self._detect_shell(),
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            cpu_count=os.cpu_count() or 2,
            is_ci=self._detect_ci(),
            is_tty=sys.stdout.isatty(),
            supports_ansi=self._detect_ansi_support(),
            available_binaries=self._detect_binaries(),
            package_managers=self._detect_package_managers(),
        )
        
        return self._env
    
    def _detect_os(self) -> OSType:
        """Detect operating system."""
        system = platform.system().lower()
        if system == "windows":
            return OSType.WINDOWS
        elif system == "linux":
            return OSType.LINUX
        elif system == "darwin":
            return OSType.MACOS
        return OSType.UNKNOWN
    
    def _detect_os_version(self) -> str:
        """Detect OS version string."""
        try:
            if self._detect_os() == OSType.WINDOWS:
                return platform.version()
            return platform.platform()
        except Exception:
            return "unknown"
    
    def _detect_shell(self) -> ShellType:
        """Detect current shell."""
        shell_path = os.environ.get("SHELL", "")
        if not shell_path and os.name == "nt":
            # Windows
            parent = os.environ.get("PARENT_PROCESS", "").lower()
            if "powershell" in parent or "pwsh" in parent:
                return ShellType.POWERSHELL
            return ShellType.CMD
        
        shell_name = Path(shell_path).name.lower()
        if "zsh" in shell_name:
            return ShellType.ZSH
        elif "bash" in shell_name:
            return ShellType.BASH
        elif "fish" in shell_name:
            return ShellType.FISH
        
        return ShellType.UNKNOWN
    
    def _detect_ci(self) -> bool:
        """Detect if running in CI environment."""
        ci_env_vars = [
            "CI",
            "CONTINUOUS_INTEGRATION",
            "GITHUB_ACTIONS",
            "GITLAB_CI",
            "CIRCLECI",
            "TRAVIS",
            "JENKINS_URL",
            "BUILDKITE",
        ]
        return any(os.environ.get(var) for var in ci_env_vars)
    
    def _detect_ansi_support(self) -> bool:
        """Detect if terminal supports ANSI colors."""
        if os.environ.get("NO_COLOR"):
            return False
        if os.name != "nt":
            return sys.stdout.isatty()
        # Windows
        return bool(
            os.environ.get("WT_SESSION") or
            os.environ.get("ANSICON") or
            os.environ.get("TERM_PROGRAM") or
            os.environ.get("TERM") == "xterm-256color"
        )
    
    def _detect_binaries(self) -> dict[str, Optional[str]]:
        """Detect available binaries."""
        binaries = [
            "git",
            "python",
            "python3",
            "node",
            "npm",
            "docker",
            "llama-server",
            "llama-cli",
            "ffmpeg",
            "yt-dlp",
        ]
        
        result = {}
        for binary in binaries:
            result[binary] = shutil.which(binary)
        
        return result
    
    def _detect_package_managers(self) -> dict[str, bool]:
        """Detect available package managers."""
        managers = {
            "pip": shutil.which("pip") or shutil.which("pip3"),
            "npm": shutil.which("npm"),
            "yarn": shutil.which("yarn"),
            "pnpm": shutil.which("pnpm"),
            "composer": shutil.which("composer"),
            "cargo": shutil.which("cargo"),
            "poetry": shutil.which("poetry"),
        }
        return {k: bool(v) for k, v in managers.items()}
    
    def find_binary(
        self,
        names: list[str],
        default_paths: Optional[list[Path]] = None,
    ) -> Optional[Path]:
        """
        Find a binary by name, checking system PATH and default locations.
        
        Args:
            names: List of binary names to try
            default_paths: Additional paths to check
        
        Returns:
            Path to binary if found, None otherwise
        """
        # Check PATH first
        for name in names:
            found = shutil.which(name)
            if found:
                return Path(found)
        
        # Check default paths
        if default_paths:
            for path in default_paths:
                if path.exists():
                    return path
                # Try with .exe extension on Windows
                if self._env and self._env.os_type == OSType.WINDOWS:
                    exe_path = path.with_suffix(".exe")
                    if exe_path.exists():
                        return exe_path
        
        return None
    
    def get_config_dir(self, app_name: str = "mini_ai_cli") -> Path:
        """Get platform-appropriate config directory."""
        os_type = self._detect_os()
        
        if os_type == OSType.WINDOWS:
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
            return base / app_name
        elif os_type == OSType.MACOS:
            return Path.home() / "Library" / "Application Support" / app_name
        else:  # Linux and others
            xdg_config = os.environ.get("XDG_CONFIG_HOME")
            if xdg_config:
                return Path(xdg_config) / app_name
            return Path.home() / ".config" / app_name
    
    def get_cache_dir(self, app_name: str = "mini_ai_cli") -> Path:
        """Get platform-appropriate cache directory."""
        os_type = self._detect_os()
        
        if os_type == OSType.WINDOWS:
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
            return base / app_name / "cache"
        elif os_type == OSType.MACOS:
            return Path.home() / "Library" / "Caches" / app_name
        else:  # Linux and others
            xdg_cache = os.environ.get("XDG_CACHE_HOME")
            if xdg_cache:
                return Path(xdg_cache) / app_name
            return Path.home() / ".cache" / app_name


# Singleton detector
_detector: Optional[EnvironmentDetector] = None


def get_detector() -> EnvironmentDetector:
    """Get the global environment detector."""
    global _detector
    if _detector is None:
        _detector = EnvironmentDetector()
    return _detector


def get_environment() -> RuntimeEnvironment:
    """Get the detected runtime environment."""
    return get_detector().detect()


# Convenience exports
__all__ = [
    "OSType",
    "ShellType",
    "RuntimeEnvironment",
    "EnvironmentDetector",
    "get_detector",
    "get_environment",
]

# Fix circular import
import tempfile
