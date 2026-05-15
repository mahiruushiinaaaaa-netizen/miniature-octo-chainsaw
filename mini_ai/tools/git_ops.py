"""
git_ops.py – Advanced git operations tool.
Covers: branch, stash, log, blame, cherry-pick, rebase, tag, remote, status, diff, merge, reset.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any


def _check_git() -> dict[str, Any] | None:
    if not shutil.which("git"):
        return {"success": False, "error": "git is not installed. Install from https://git-scm.com/"}
    return None


def _run_git(args: list[str], cwd: str = ".", timeout: int = 30) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        output = (result.stdout + result.stderr).strip()
        if len(output) > 3000:
            output = output[:3000] + "\n...[truncated]"
        if result.returncode == 0:
            return {"success": True, "result": output or "(no output)"}
        return {"success": False, "error": output or f"git exited with code {result.returncode}"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"git command timed out after {timeout}s"}
    except FileNotFoundError:
        return {"success": False, "error": "git not found on PATH"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def git_op(operation: str, args: str = "", path: str = ".") -> dict[str, Any]:
    """Advanced git operations.

    Operations:
    - status: working tree status
    - branch: list/create/delete/switch (args: 'list', 'create <name>', 'delete <name>', 'switch <name>')
    - stash: save/pop/list/drop (args: 'save [msg]', 'pop', 'list', 'drop [index]')
    - log: commit history (args: number of commits, default 10)
    - blame: line authorship (args: file path)
    - cherry_pick: apply commit (args: commit hash)
    - rebase: rebase branch (args: target branch)
    - tag: list/create/delete (args: 'list', 'create <name> [msg]', 'delete <name>')
    - remote: list/add/remove (args: 'list', 'add <name> <url>', 'remove <name>')
    - diff_staged: show staged changes
    - merge: merge branch (args: branch name)
    - reset: reset to state (args: 'soft|mixed|hard [ref]')
    """
    check = _check_git()
    if check:
        return check

    operation = operation.lower().strip()
    cwd = str(Path(path).expanduser().resolve()) if path else "."

    if operation == "status":
        return _run_git(["status", "--short"], cwd)

    elif operation == "branch":
        sub = args.strip().split(maxsplit=1) if args.strip() else ["list"]
        cmd = sub[0].lower()
        if cmd == "list" or not cmd:
            return _run_git(["branch", "-a"], cwd)
        elif cmd == "create" and len(sub) > 1:
            name = sub[1].strip() if len(sub) > 1 else ""
            parts = name.split()
            return _run_git(["checkout", "-b", parts[0]], cwd)
        elif cmd == "delete" and len(sub) > 1:
            return _run_git(["branch", "-d", sub[1].strip()], cwd)
        elif cmd == "switch" and len(sub) > 1:
            return _run_git(["checkout", sub[1].strip()], cwd)
        else:
            return _run_git(["branch", "-a"], cwd)

    elif operation == "stash":
        sub = args.strip().split(maxsplit=1) if args.strip() else ["list"]
        cmd = sub[0].lower()
        if cmd == "save":
            msg = sub[1] if len(sub) > 1 else ""
            git_args = ["stash", "push"]
            if msg:
                git_args += ["-m", msg]
            return _run_git(git_args, cwd)
        elif cmd == "pop":
            return _run_git(["stash", "pop"], cwd)
        elif cmd == "list":
            return _run_git(["stash", "list"], cwd)
        elif cmd == "drop":
            idx = sub[1] if len(sub) > 1 else "0"
            return _run_git(["stash", "drop", f"stash@{{{idx}}}"], cwd)
        else:
            return _run_git(["stash", "list"], cwd)

    elif operation == "log":
        n = args.strip() if args.strip() else "10"
        try:
            n = str(int(n))
        except ValueError:
            n = "10"
        return _run_git(["log", f"--oneline", f"-{n}"], cwd)

    elif operation == "blame":
        if not args.strip():
            return {"success": False, "error": "blame requires a file path. Usage: operation='blame', args='path/to/file'"}
        return _run_git(["blame", "--date=short", args.strip()], cwd)

    elif operation == "cherry_pick":
        if not args.strip():
            return {"success": False, "error": "cherry_pick requires a commit hash. Usage: args='abc123'"}
        return _run_git(["cherry-pick", args.strip()], cwd)

    elif operation == "rebase":
        if not args.strip():
            return {"success": False, "error": "rebase requires a target branch. Usage: args='main'"}
        return _run_git(["rebase", args.strip()], cwd)

    elif operation == "tag":
        sub = args.strip().split(maxsplit=2) if args.strip() else ["list"]
        cmd = sub[0].lower()
        if cmd == "list" or not cmd:
            return _run_git(["tag", "-l"], cwd)
        elif cmd == "create" and len(sub) > 1:
            tag_name = sub[1]
            msg = sub[2] if len(sub) > 2 else ""
            git_args = ["tag"]
            if msg:
                git_args += ["-a", tag_name, "-m", msg]
            else:
                git_args += [tag_name]
            return _run_git(git_args, cwd)
        elif cmd == "delete" and len(sub) > 1:
            return _run_git(["tag", "-d", sub[1]], cwd)
        else:
            return _run_git(["tag", "-l"], cwd)

    elif operation == "remote":
        sub = args.strip().split(maxsplit=2) if args.strip() else ["list"]
        cmd = sub[0].lower()
        if cmd == "list" or not cmd:
            return _run_git(["remote", "-v"], cwd)
        elif cmd == "add" and len(sub) > 2:
            return _run_git(["remote", "add", sub[1], sub[2]], cwd)
        elif cmd == "remove" and len(sub) > 1:
            return _run_git(["remote", "remove", sub[1]], cwd)
        else:
            return _run_git(["remote", "-v"], cwd)

    elif operation == "diff_staged":
        return _run_git(["diff", "--cached", "--stat"], cwd)

    elif operation == "merge":
        if not args.strip():
            return {"success": False, "error": "merge requires a branch name. Usage: args='feature-branch'"}
        return _run_git(["merge", args.strip()], cwd)

    elif operation == "reset":
        parts = args.strip().split() if args.strip() else ["mixed"]
        mode = parts[0].lower() if parts else "mixed"
        if mode not in ("soft", "mixed", "hard"):
            mode = "mixed"
        ref = parts[1] if len(parts) > 1 else "HEAD~1"
        return _run_git(["reset", f"--{mode}", ref], cwd)

    else:
        return {"success": False, "error": f"Unknown git operation: '{operation}'. Available: status, branch, stash, log, blame, cherry_pick, rebase, tag, remote, diff_staged, merge, reset"}
