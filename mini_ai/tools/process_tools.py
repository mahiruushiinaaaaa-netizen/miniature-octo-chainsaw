"""
process_tools.py – Structured process tools for the agent.
"""
from __future__ import annotations

import subprocess
from typing import Any
from ..core.platform_adapter import get_platform_adapter

adapter = get_platform_adapter()

def run_command(command: str, cwd: str = ".") -> dict[str, Any]:
    try:
        # Use platform adapter to normalize command
        full_cmd = adapter.get_shell_command(command)
        result = subprocess.run(
            full_cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300
        )
        return {
            "success": result.returncode == 0,
            "output": result.stdout + result.stderr,
            "exit_code": result.returncode
        }
    except Exception as e:
        return {
            "success": False,
            "output": str(e)
        }
