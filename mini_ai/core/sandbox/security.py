import os
import psutil
from typing import Dict, List, Tuple
from pathlib import Path

class ResourceMonitor:
    """Monitors resource usage of sandbox processes."""
    def __init__(self, pid: int):
        self.pid = pid
        try:
            self.process = psutil.Process(pid)
        except psutil.NoSuchProcess:
            self.process = None

    def get_usage(self) -> Dict[str, float]:
        """Returns CPU and Memory usage."""
        if not self.process or not self.process.is_running():
            return {"cpu_percent": 0.0, "memory_mb": 0.0}
        
        try:
            return {
                "cpu_percent": self.process.cpu_percent(interval=0.1),
                "memory_mb": self.process.memory_info().rss / (1024 * 1024)
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return {"cpu_percent": 0.0, "memory_mb": 0.0}

class CommandRiskScorer:
    """Ranks commands by risk level."""
    
    # High risk commands that MUST be approved
    HIGH_RISK = [
        r"rm\s+-rf", r"del\s+/s", r"format", r"rd\s+/s", r"mkfs", r"dd\s+if=",
        r"chmod\s+777", r"chown", r">/dev/", r"mv\s+.* /"
    ]
    
    # Medium risk commands that should be approved in standard mode
    MEDIUM_RISK = [
        "pip install", "npm install", "git push", "composer install",
        "rm ", "del ", "mv ", "cp "
    ]

    @classmethod
    def get_risk_score(cls, cmd: str) -> int:
        """
        Returns a risk score:
        0: Low (Safe)
        1: Medium (Needs standard approval)
        2: High (Strict approval required)
        """
        import re
        cmd_low = cmd.lower()
        
        for pattern in cls.HIGH_RISK:
            if re.search(pattern, cmd_low):
                return 2
                
        for pattern in cls.MEDIUM_RISK:
            if pattern in cmd_low:
                return 1
                
        return 0

def validate_path_safety(path: Path, root: Path) -> bool:
    """Ensures a path is within the allowed root."""
    try:
        resolved_path = path.resolve()
        resolved_root = root.resolve()
        return str(resolved_path).startswith(str(resolved_root))
    except Exception:
        return False
