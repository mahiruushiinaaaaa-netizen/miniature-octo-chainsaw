"""
package_tools.py – Universal package manager operations.

Covers: npm, pip, cargo, composer, go, dotnet, gem, yarn, pnpm, bun.
Auto-detects available package managers and provides unified interface.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


def _run_pkg(args: list[str], cwd: str = ".", timeout: int = 120) -> dict[str, Any]:
    """Run a package manager command."""
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout.strip()
        if result.returncode == 0:
            if len(output) > 5000:
                output = output[:5000] + "\n...[truncated]"
            return {"success": True, "result": output or "Done"}
        else:
            error = result.stderr.strip() or output
            return {"success": False, "error": error[:3000]}
    except FileNotFoundError:
        return {"success": False, "error": f"Command not found: {args[0]}"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Command timed out ({timeout}s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def npm_tool(operation: str, package: str = "", flags: str = "", cwd: str = ".") -> dict[str, Any]:
    """NPM package manager operations.
    
    Operations: install, uninstall, update, list, init, run, audit, outdated, info
    """
    op = operation.lower().strip()
    
    if op == "install":
        args = ["npm", "install"]
        if package:
            args.append(package)
        if flags:
            args.extend(flags.split())
        return _run_pkg(args, cwd, timeout=180)
    elif op == "uninstall":
        if not package:
            return {"success": False, "error": "Package name required"}
        return _run_pkg(["npm", "uninstall", package], cwd)
    elif op == "update":
        args = ["npm", "update"]
        if package:
            args.append(package)
        return _run_pkg(args, cwd, timeout=180)
    elif op == "list":
        return _run_pkg(["npm", "list", "--depth=0"], cwd)
    elif op == "init":
        return _run_pkg(["npm", "init", "-y"], cwd)
    elif op == "run":
        if not package:
            return {"success": False, "error": "Script name required"}
        return _run_pkg(["npm", "run", package], cwd, timeout=60)
    elif op == "audit":
        return _run_pkg(["npm", "audit"], cwd)
    elif op == "outdated":
        return _run_pkg(["npm", "outdated"], cwd)
    elif op == "info":
        if not package:
            return {"success": False, "error": "Package name required"}
        return _run_pkg(["npm", "info", package], cwd)
    
    return {"success": False, "error": f"Unknown operation: {op}"}


def pip_tool(operation: str, package: str = "", flags: str = "", cwd: str = ".") -> dict[str, Any]:
    """Pip package manager operations.
    
    Operations: install, uninstall, list, freeze, show, search, upgrade, check
    """
    op = operation.lower().strip()
    pip_cmd = "pip"
    
    if op == "install":
        args = [pip_cmd, "install"]
        if package:
            args.append(package)
        if flags:
            args.extend(flags.split())
        return _run_pkg(args, cwd, timeout=180)
    elif op == "uninstall":
        if not package:
            return {"success": False, "error": "Package name required"}
        return _run_pkg([pip_cmd, "uninstall", "-y", package], cwd)
    elif op == "list":
        return _run_pkg([pip_cmd, "list"], cwd)
    elif op == "freeze":
        return _run_pkg([pip_cmd, "freeze"], cwd)
    elif op == "show":
        if not package:
            return {"success": False, "error": "Package name required"}
        return _run_pkg([pip_cmd, "show", package], cwd)
    elif op == "upgrade":
        if not package:
            return {"success": False, "error": "Package name required"}
        return _run_pkg([pip_cmd, "install", "--upgrade", package], cwd, timeout=180)
    elif op == "check":
        return _run_pkg([pip_cmd, "check"], cwd)
    
    return {"success": False, "error": f"Unknown operation: {op}"}


def cargo_tool(operation: str, package: str = "", flags: str = "", cwd: str = ".") -> dict[str, Any]:
    """Cargo (Rust) package manager operations.
    
    Operations: build, run, test, new, add, remove, update, check, clippy, doc
    """
    op = operation.lower().strip()
    
    if op == "build":
        args = ["cargo", "build"]
        if flags:
            args.extend(flags.split())
        return _run_pkg(args, cwd, timeout=300)
    elif op == "run":
        args = ["cargo", "run"]
        if flags:
            args.extend(flags.split())
        return _run_pkg(args, cwd, timeout=60)
    elif op == "test":
        return _run_pkg(["cargo", "test"], cwd, timeout=120)
    elif op == "new":
        if not package:
            return {"success": False, "error": "Project name required"}
        return _run_pkg(["cargo", "new", package], cwd)
    elif op == "add":
        if not package:
            return {"success": False, "error": "Crate name required"}
        return _run_pkg(["cargo", "add", package], cwd)
    elif op == "remove":
        if not package:
            return {"success": False, "error": "Crate name required"}
        return _run_pkg(["cargo", "remove", package], cwd)
    elif op == "update":
        return _run_pkg(["cargo", "update"], cwd)
    elif op == "check":
        return _run_pkg(["cargo", "check"], cwd)
    elif op == "clippy":
        return _run_pkg(["cargo", "clippy"], cwd)
    elif op == "doc":
        return _run_pkg(["cargo", "doc", "--open"], cwd)
    
    return {"success": False, "error": f"Unknown operation: {op}"}


def composer_tool(operation: str, package: str = "", flags: str = "", cwd: str = ".") -> dict[str, Any]:
    """Composer (PHP) package manager operations.
    
    Operations: install, require, remove, update, dump-autoload, show, init
    """
    op = operation.lower().strip()
    
    if op == "install":
        return _run_pkg(["composer", "install"], cwd, timeout=180)
    elif op == "require":
        if not package:
            return {"success": False, "error": "Package name required"}
        args = ["composer", "require", package]
        if flags:
            args.extend(flags.split())
        return _run_pkg(args, cwd, timeout=180)
    elif op == "remove":
        if not package:
            return {"success": False, "error": "Package name required"}
        return _run_pkg(["composer", "remove", package], cwd)
    elif op == "update":
        args = ["composer", "update"]
        if package:
            args.append(package)
        return _run_pkg(args, cwd, timeout=180)
    elif op == "dump-autoload":
        return _run_pkg(["composer", "dump-autoload"], cwd)
    elif op == "show":
        args = ["composer", "show"]
        if package:
            args.append(package)
        return _run_pkg(args, cwd)
    elif op == "init":
        return _run_pkg(["composer", "init", "--no-interaction"], cwd)
    
    return {"success": False, "error": f"Unknown operation: {op}"}


def go_tool(operation: str, package: str = "", flags: str = "", cwd: str = ".") -> dict[str, Any]:
    """Go module/package operations.
    
    Operations: mod_init, get, build, run, test, tidy, fmt, vet, list
    """
    op = operation.lower().strip()
    
    if op == "mod_init":
        if not package:
            return {"success": False, "error": "Module name required"}
        return _run_pkg(["go", "mod", "init", package], cwd)
    elif op == "get":
        if not package:
            return {"success": False, "error": "Package path required"}
        return _run_pkg(["go", "get", package], cwd)
    elif op == "build":
        args = ["go", "build"]
        if flags:
            args.extend(flags.split())
        else:
            args.append("./...")
        return _run_pkg(args, cwd, timeout=120)
    elif op == "run":
        if not package:
            package = "."
        return _run_pkg(["go", "run", package], cwd, timeout=30)
    elif op == "test":
        return _run_pkg(["go", "test", "./..."], cwd, timeout=120)
    elif op == "tidy":
        return _run_pkg(["go", "mod", "tidy"], cwd)
    elif op == "fmt":
        return _run_pkg(["go", "fmt", "./..."], cwd)
    elif op == "vet":
        return _run_pkg(["go", "vet", "./..."], cwd)
    elif op == "list":
        return _run_pkg(["go", "list", "./..."], cwd)
    
    return {"success": False, "error": f"Unknown operation: {op}"}


def dotnet_tool(operation: str, package: str = "", flags: str = "", cwd: str = ".") -> dict[str, Any]:
    """.NET CLI operations.
    
    Operations: new, build, run, test, add_package, remove_package, restore, publish
    """
    op = operation.lower().strip()
    
    if op == "new":
        if not package:
            return {"success": False, "error": "Template name required (e.g. console, webapi, mvc)"}
        args = ["dotnet", "new", package]
        if flags:
            args.extend(flags.split())
        return _run_pkg(args, cwd)
    elif op == "build":
        return _run_pkg(["dotnet", "build"], cwd, timeout=120)
    elif op == "run":
        return _run_pkg(["dotnet", "run"], cwd, timeout=30)
    elif op == "test":
        return _run_pkg(["dotnet", "test"], cwd, timeout=120)
    elif op == "add_package":
        if not package:
            return {"success": False, "error": "Package name required"}
        return _run_pkg(["dotnet", "add", "package", package], cwd)
    elif op == "remove_package":
        if not package:
            return {"success": False, "error": "Package name required"}
        return _run_pkg(["dotnet", "remove", "package", package], cwd)
    elif op == "restore":
        return _run_pkg(["dotnet", "restore"], cwd)
    elif op == "publish":
        args = ["dotnet", "publish"]
        if flags:
            args.extend(flags.split())
        return _run_pkg(args, cwd, timeout=120)
    
    return {"success": False, "error": f"Unknown operation: {op}"}
