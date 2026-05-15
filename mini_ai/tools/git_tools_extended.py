"""
git_tools_extended.py – Comprehensive Git operations beyond basic init/add/commit.

Covers: branch, checkout, merge, log, diff, stash, tag, remote, status, reset,
cherry-pick, rebase, blame, and more.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


def _run_git(args: list[str], cwd: str = ".") -> dict[str, Any]:
    """Run a git command and return structured result."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return {"success": True, "result": result.stdout.strip() or "Done"}
        else:
            return {"success": False, "error": result.stderr.strip() or result.stdout.strip()}
    except FileNotFoundError:
        return {"success": False, "error": "Git is not installed or not in PATH"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Git command timed out (30s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def git_status(cwd: str = ".") -> dict[str, Any]:
    """Get git status (short format)."""
    return _run_git(["status", "--short", "--branch"], cwd)


def git_log(cwd: str = ".", count: int = 10, oneline: bool = True) -> dict[str, Any]:
    """Get git log."""
    args = ["log", f"-{count}"]
    if oneline:
        args.append("--oneline")
    args.append("--decorate")
    return _run_git(args, cwd)


def git_diff(cwd: str = ".", target: str = "", staged: bool = False) -> dict[str, Any]:
    """Show git diff."""
    args = ["diff"]
    if staged:
        args.append("--staged")
    if target:
        args.append(target)
    result = _run_git(args, cwd)
    # Truncate large diffs
    if result.get("success") and len(result.get("result", "")) > 5000:
        result["result"] = result["result"][:5000] + "\n...[truncated]"
    return result


def git_branch(cwd: str = ".", operation: str = "list", name: str = "") -> dict[str, Any]:
    """Manage git branches. Operations: list, create, delete, rename, current."""
    if operation == "list":
        return _run_git(["branch", "-a"], cwd)
    elif operation == "create":
        if not name:
            return {"success": False, "error": "Branch name required"}
        return _run_git(["branch", name], cwd)
    elif operation == "delete":
        if not name:
            return {"success": False, "error": "Branch name required"}
        return _run_git(["branch", "-d", name], cwd)
    elif operation == "rename":
        if not name:
            return {"success": False, "error": "New branch name required"}
        return _run_git(["branch", "-m", name], cwd)
    elif operation == "current":
        return _run_git(["branch", "--show-current"], cwd)
    return {"success": False, "error": f"Unknown branch operation: {operation}"}


def git_checkout(cwd: str = ".", target: str = "", create: bool = False) -> dict[str, Any]:
    """Checkout a branch or file."""
    if not target:
        return {"success": False, "error": "Target branch/file required"}
    args = ["checkout"]
    if create:
        args.append("-b")
    args.append(target)
    return _run_git(args, cwd)


def git_merge(cwd: str = ".", branch: str = "", no_ff: bool = False) -> dict[str, Any]:
    """Merge a branch into current."""
    if not branch:
        return {"success": False, "error": "Branch name required"}
    args = ["merge"]
    if no_ff:
        args.append("--no-ff")
    args.append(branch)
    return _run_git(args, cwd)


def git_stash(cwd: str = ".", operation: str = "push", message: str = "") -> dict[str, Any]:
    """Manage git stash. Operations: push, pop, list, drop, apply."""
    if operation == "push":
        args = ["stash", "push"]
        if message:
            args.extend(["-m", message])
        return _run_git(args, cwd)
    elif operation == "pop":
        return _run_git(["stash", "pop"], cwd)
    elif operation == "list":
        return _run_git(["stash", "list"], cwd)
    elif operation == "drop":
        return _run_git(["stash", "drop"], cwd)
    elif operation == "apply":
        return _run_git(["stash", "apply"], cwd)
    return {"success": False, "error": f"Unknown stash operation: {operation}"}


def git_tag(cwd: str = ".", operation: str = "list", name: str = "", message: str = "") -> dict[str, Any]:
    """Manage git tags. Operations: list, create, delete."""
    if operation == "list":
        return _run_git(["tag", "-l"], cwd)
    elif operation == "create":
        if not name:
            return {"success": False, "error": "Tag name required"}
        args = ["tag"]
        if message:
            args.extend(["-a", name, "-m", message])
        else:
            args.append(name)
        return _run_git(args, cwd)
    elif operation == "delete":
        if not name:
            return {"success": False, "error": "Tag name required"}
        return _run_git(["tag", "-d", name], cwd)
    return {"success": False, "error": f"Unknown tag operation: {operation}"}


def git_remote(cwd: str = ".", operation: str = "list", name: str = "", url: str = "") -> dict[str, Any]:
    """Manage git remotes. Operations: list, add, remove, get_url."""
    if operation == "list":
        return _run_git(["remote", "-v"], cwd)
    elif operation == "add":
        if not name or not url:
            return {"success": False, "error": "Remote name and URL required"}
        return _run_git(["remote", "add", name, url], cwd)
    elif operation == "remove":
        if not name:
            return {"success": False, "error": "Remote name required"}
        return _run_git(["remote", "remove", name], cwd)
    elif operation == "get_url":
        if not name:
            name = "origin"
        return _run_git(["remote", "get-url", name], cwd)
    return {"success": False, "error": f"Unknown remote operation: {operation}"}


def git_reset(cwd: str = ".", target: str = "HEAD", mode: str = "mixed") -> dict[str, Any]:
    """Reset git state. Modes: soft, mixed, hard."""
    if mode not in ("soft", "mixed", "hard"):
        return {"success": False, "error": f"Invalid mode: {mode}. Use soft/mixed/hard"}
    return _run_git(["reset", f"--{mode}", target], cwd)


def git_cherry_pick(cwd: str = ".", commit: str = "") -> dict[str, Any]:
    """Cherry-pick a commit."""
    if not commit:
        return {"success": False, "error": "Commit hash required"}
    return _run_git(["cherry-pick", commit], cwd)


def git_blame(cwd: str = ".", file: str = "") -> dict[str, Any]:
    """Show git blame for a file."""
    if not file:
        return {"success": False, "error": "File path required"}
    result = _run_git(["blame", "--line-porcelain", file], cwd)
    # Simplify blame output
    if result.get("success") and len(result.get("result", "")) > 5000:
        # Fall back to short format
        result = _run_git(["blame", file], cwd)
        if len(result.get("result", "")) > 5000:
            result["result"] = result["result"][:5000] + "\n...[truncated]"
    return result


def git_clone(url: str = "", destination: str = "", cwd: str = ".") -> dict[str, Any]:
    """Clone a git repository."""
    if not url:
        return {"success": False, "error": "Repository URL required"}
    args = ["clone", url]
    if destination:
        args.append(destination)
    return _run_git(args, cwd)


def git_pull(cwd: str = ".", remote: str = "origin", branch: str = "") -> dict[str, Any]:
    """Pull from remote."""
    args = ["pull", remote]
    if branch:
        args.append(branch)
    return _run_git(args, cwd)


def git_push(cwd: str = ".", remote: str = "origin", branch: str = "", set_upstream: bool = False) -> dict[str, Any]:
    """Push to remote."""
    args = ["push"]
    if set_upstream:
        args.append("-u")
    args.append(remote)
    if branch:
        args.append(branch)
    return _run_git(args, cwd)
