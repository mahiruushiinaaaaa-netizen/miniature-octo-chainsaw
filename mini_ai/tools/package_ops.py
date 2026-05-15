"""
package_ops.py – Package manager operations (npm, pip, cargo, composer, go, yarn, pnpm).
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Any


_MANAGER_COMMANDS = {
    "npm": {"install": ["install"], "uninstall": ["uninstall"], "list": ["list", "--depth=0"], "outdated": ["outdated"], "update": ["update"], "search": ["search"], "init": ["init", "-y"]},
    "pip": {"install": ["install"], "uninstall": ["uninstall", "-y"], "list": ["list"], "outdated": ["list", "--outdated"], "update": ["install", "--upgrade"], "search": ["index", "versions"], "init": []},
    "yarn": {"install": ["add"], "uninstall": ["remove"], "list": ["list", "--depth=0"], "outdated": ["outdated"], "update": ["upgrade"], "search": [], "init": ["init", "-y"]},
    "pnpm": {"install": ["add"], "uninstall": ["remove"], "list": ["list", "--depth=0"], "outdated": ["outdated"], "update": ["update"], "search": [], "init": ["init"]},
    "cargo": {"install": ["install"], "uninstall": ["uninstall"], "list": ["install", "--list"], "outdated": [], "update": ["update"], "search": ["search"], "init": ["init"]},
    "composer": {"install": ["require"], "uninstall": ["remove"], "list": ["show"], "outdated": ["outdated"], "update": ["update"], "search": ["search"], "init": ["init"]},
    "go": {"install": ["install"], "uninstall": [], "list": ["list", "-m", "all"], "outdated": [], "update": ["get", "-u"], "search": [], "init": ["mod", "init"]},
}


def package_op(manager: str, operation: str, package: str = "", options: str = "") -> dict[str, Any]:
    """Package manager operations.

    Managers: npm, pip, cargo, composer, go, yarn, pnpm
    Operations: install, uninstall, list, outdated, update, search, init
    
    Args:
        manager: Package manager name
        operation: Operation to perform
        package: Package name (for install/uninstall/update/search)
        options: Additional flags (e.g. '--save-dev', '--global')
    """
    manager = manager.lower().strip()
    operation = operation.lower().strip()

    if manager not in _MANAGER_COMMANDS:
        available = ", ".join(sorted(_MANAGER_COMMANDS.keys()))
        return {"success": False, "error": f"Unknown manager: '{manager}'. Available: {available}"}

    if not shutil.which(manager):
        hints = {
            "npm": "Install Node.js from https://nodejs.org/",
            "pip": "pip comes with Python. Try 'python -m pip'",
            "yarn": "npm install -g yarn",
            "pnpm": "npm install -g pnpm",
            "cargo": "Install Rust from https://rustup.rs/",
            "composer": "Install from https://getcomposer.org/",
            "go": "Install from https://go.dev/dl/",
        }
        hint = hints.get(manager, "")
        return {"success": False, "error": f"'{manager}' is not installed. {hint}"}

    cmd_template = _MANAGER_COMMANDS[manager].get(operation)
    if cmd_template is None:
        available = ", ".join(k for k, v in _MANAGER_COMMANDS[manager].items() if v)
        return {"success": False, "error": f"Operation '{operation}' not supported for {manager}. Available: {available}"}

    if not cmd_template:
        return {"success": False, "error": f"Operation '{operation}' is not available for {manager}"}

    # Build command
    cmd = [manager] + list(cmd_template)

    # Add package name for operations that need it
    if operation in ("install", "uninstall", "update", "search") and package:
        cmd.append(package)
    elif operation in ("install", "uninstall") and not package:
        if operation == "install" and manager in ("npm", "yarn", "pnpm", "composer"):
            pass  # bare install is valid (install from lockfile)
        else:
            return {"success": False, "error": f"'{operation}' requires a package name"}

    # Add init name for cargo/go
    if operation == "init" and package:
        cmd.append(package)

    # Add extra options
    if options:
        cmd.extend(options.split())

    # Special: pip uses python -m pip for reliability
    if manager == "pip":
        import sys
        cmd = [sys.executable, "-m", "pip"] + cmd_template
        if package:
            cmd.append(package)
        if options:
            cmd.extend(options.split())

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
        output = (result.stdout + result.stderr).strip()
        if len(output) > 3000:
            output = output[:3000] + "\n...[truncated]"
        if result.returncode == 0:
            return {"success": True, "result": output or f"{manager} {operation} completed successfully"}
        # Common error hints
        if "EACCES" in output or "permission" in output.lower():
            output += f"\n\nHint: Try with {'--user' if manager == 'pip' else 'sudo'} flag"
        return {"success": False, "error": output}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"{manager} {operation} timed out after 120s"}
    except Exception as e:
        return {"success": False, "error": str(e)}
