"""
git_tools.py – Structured Git tools for the agent.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

def git_init(repo_path: str) -> dict[str, Any]:
    try:
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
        return {"success": True, "output": f"Initialized git repo in {repo_path}"}
    except subprocess.CalledProcessError as e:
        return {"success": False, "output": f"Git init failed: {e.stderr.decode()}"}

def git_add(repo_path: str, paths: list[str]) -> dict[str, Any]:
    try:
        subprocess.run(["git", "add"] + paths, cwd=repo_path, check=True, capture_output=True)
        return {"success": True, "output": f"Added {len(paths)} paths to git."}
    except subprocess.CalledProcessError as e:
        return {"success": False, "output": f"Git add failed: {e.stderr.decode()}"}

def git_commit(repo_path: str, message: str) -> dict[str, Any]:
    try:
        subprocess.run(["git", "commit", "-m", message], cwd=repo_path, check=True, capture_output=True)
        return {"success": True, "output": f"Committed: {message}"}
    except subprocess.CalledProcessError as e:
        return {"success": False, "output": f"Git commit failed: {e.stderr.decode()}"}

def git_status(repo_path: str) -> dict[str, Any]:
    try:
        result = subprocess.run(["git", "status"], cwd=repo_path, check=True, capture_output=True, text=True)
        return {"success": True, "output": result.stdout}
    except subprocess.CalledProcessError as e:
        return {"success": False, "output": f"Git status failed: {e.stderr.decode()}"}
