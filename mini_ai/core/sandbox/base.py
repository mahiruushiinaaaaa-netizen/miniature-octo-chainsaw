from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

@dataclass
class SandboxResult:
    """Standardized result from a sandbox execution."""
    success: bool
    output: str
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

class SandboxProvider(ABC):
    """Abstract base class for all sandbox providers."""
    
    @abstractmethod
    def execute(self, cmd: str, timeout: int = 600) -> SandboxResult:
        """Execute a command within the sandbox."""
        pass

    @abstractmethod
    def write_file(self, path: str, content: str) -> bool:
        """Write a file to the sandbox."""
        pass

    @abstractmethod
    def read_file(self, path: str) -> Optional[str]:
        """Read a file from the sandbox."""
        pass

    @abstractmethod
    def list_dir(self, path: str) -> List[str]:
        """List contents of a directory in the sandbox."""
        pass

    @property
    @abstractmethod
    def cwd(self) -> Path:
        """Get the current working directory of the sandbox."""
        pass
    
    @cwd.setter
    @abstractmethod
    def cwd(self, value: Path):
        """Set the current working directory of the sandbox."""
        pass

    @abstractmethod
    def close(self):
        """Clean up sandbox resources."""
        pass
