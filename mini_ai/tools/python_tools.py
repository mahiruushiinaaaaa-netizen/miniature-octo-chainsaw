"""
python_tools.py – Structured Python tools for the agent.
"""
from __future__ import annotations

from typing import Any
from .code_utils import run_python_code

def execute_python(code: str) -> dict[str, Any]:
    success, output = run_python_code(code)
    return {
        "success": success,
        "output": output
    }
