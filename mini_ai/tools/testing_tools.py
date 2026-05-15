"""
testing_tools.py – Testing, benchmarking, and quality assurance tools.

Covers: test runners, code coverage, benchmarking, assertions, mocking helpers.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


def run_tests(framework: str = "auto", path: str = ".", args: str = "", timeout: int = 120) -> dict[str, Any]:
    """Run tests using the appropriate framework.
    
    Frameworks: auto, pytest, jest, vitest, mocha, phpunit, go, cargo, dotnet
    """
    fw = framework.lower().strip()
    
    if fw == "auto":
        fw = _detect_test_framework(path)
    
    commands = {
        "pytest": ["python", "-m", "pytest", "--tb=short", "-q"],
        "jest": ["npx", "jest", "--no-coverage"],
        "vitest": ["npx", "vitest", "run"],
        "mocha": ["npx", "mocha"],
        "phpunit": ["php", "vendor/bin/phpunit"],
        "go": ["go", "test", "./..."],
        "cargo": ["cargo", "test"],
        "dotnet": ["dotnet", "test"],
        "unittest": ["python", "-m", "unittest", "discover"],
    }
    
    cmd = commands.get(fw)
    if not cmd:
        return {"success": False, "error": f"Unknown framework: {fw}. Supported: {', '.join(commands.keys())}"}
    
    if args:
        cmd.extend(args.split())
    
    try:
        result = subprocess.run(cmd, cwd=path, capture_output=True, text=True, timeout=timeout)
        output = result.stdout + "\n" + result.stderr
        if len(output) > 5000:
            output = output[:5000] + "\n...[truncated]"
        
        return {
            "success": result.returncode == 0,
            "result": output.strip(),
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Tests timed out after {timeout}s"}
    except FileNotFoundError:
        return {"success": False, "error": f"Test runner '{cmd[0]}' not found. Install it first."}
    except Exception as e:
        return {"success": False, "error": str(e)}


def test_coverage(framework: str = "auto", path: str = ".", args: str = "") -> dict[str, Any]:
    """Run tests with coverage reporting.
    
    Frameworks: pytest, jest, vitest, go, cargo
    """
    fw = framework.lower().strip()
    if fw == "auto":
        fw = _detect_test_framework(path)
    
    commands = {
        "pytest": ["python", "-m", "pytest", "--cov", "--cov-report=term-missing", "-q"],
        "jest": ["npx", "jest", "--coverage"],
        "vitest": ["npx", "vitest", "run", "--coverage"],
        "go": ["go", "test", "-cover", "./..."],
        "cargo": ["cargo", "tarpaulin", "--out", "stdout"],
    }
    
    cmd = commands.get(fw)
    if not cmd:
        return {"success": False, "error": f"Coverage not supported for: {fw}"}
    
    if args:
        cmd.extend(args.split())
    
    try:
        result = subprocess.run(cmd, cwd=path, capture_output=True, text=True, timeout=180)
        output = result.stdout + "\n" + result.stderr
        if len(output) > 5000:
            output = output[:5000] + "\n...[truncated]"
        return {"success": result.returncode == 0, "result": output.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def benchmark(command: str, iterations: int = 5, warmup: int = 1, cwd: str = ".") -> dict[str, Any]:
    """Benchmark a command by running it multiple times and reporting stats."""
    if iterations < 1 or iterations > 100:
        return {"success": False, "error": "Iterations must be 1-100"}
    
    # Warmup
    for _ in range(warmup):
        subprocess.run(command, shell=True, cwd=cwd, capture_output=True, timeout=60)
    
    times = []
    for i in range(iterations):
        start = time.perf_counter()
        try:
            r = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, timeout=60)
            elapsed = time.perf_counter() - start
            times.append(elapsed)
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Command timed out on iteration {i+1}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    avg = sum(times) / len(times)
    min_t = min(times)
    max_t = max(times)
    
    lines = [
        f"Benchmark: {command}",
        f"  Iterations: {iterations} (warmup: {warmup})",
        f"  Average: {avg*1000:.1f}ms",
        f"  Min: {min_t*1000:.1f}ms",
        f"  Max: {max_t*1000:.1f}ms",
        f"  Total: {sum(times)*1000:.1f}ms",
    ]
    
    return {"success": True, "result": "\n".join(lines)}


def lint_check(path: str = ".", tool: str = "auto", fix: bool = False) -> dict[str, Any]:
    """Run linting on code. Auto-detects the appropriate linter.
    
    Tools: auto, eslint, prettier, ruff, black, flake8, mypy, rubocop, clippy
    """
    t = tool.lower().strip()
    
    if t == "auto":
        t = _detect_linter(path)
    
    commands = {
        "eslint": ["npx", "eslint", ".", "--ext", ".js,.ts,.jsx,.tsx"],
        "prettier": ["npx", "prettier", "--check", "."],
        "ruff": ["ruff", "check", path],
        "black": ["black", "--check", path],
        "flake8": ["flake8", path],
        "mypy": ["mypy", path],
        "rubocop": ["rubocop", path],
        "clippy": ["cargo", "clippy"],
    }
    
    if fix:
        fix_commands = {
            "eslint": ["npx", "eslint", ".", "--fix", "--ext", ".js,.ts,.jsx,.tsx"],
            "prettier": ["npx", "prettier", "--write", "."],
            "ruff": ["ruff", "check", "--fix", path],
            "black": ["black", path],
        }
        cmd = fix_commands.get(t, commands.get(t))
    else:
        cmd = commands.get(t)
    
    if not cmd:
        return {"success": False, "error": f"Unknown linter: {t}"}
    
    try:
        result = subprocess.run(cmd, cwd=path if os.path.isdir(path) else ".",
                                capture_output=True, text=True, timeout=60)
        output = result.stdout + "\n" + result.stderr
        if len(output) > 5000:
            output = output[:5000] + "\n...[truncated]"
        return {"success": result.returncode == 0, "result": output.strip()}
    except FileNotFoundError:
        return {"success": False, "error": f"Linter '{cmd[0]}' not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def type_check(path: str = ".", tool: str = "auto") -> dict[str, Any]:
    """Run type checking. Auto-detects TypeScript/Python type checker."""
    t = tool.lower().strip()
    
    if t == "auto":
        if Path(path, "tsconfig.json").exists() or any(Path(path).glob("**/*.ts")):
            t = "tsc"
        elif Path(path, "pyproject.toml").exists() or any(Path(path).glob("**/*.py")):
            t = "mypy"
        else:
            t = "tsc"
    
    commands = {
        "tsc": ["npx", "tsc", "--noEmit"],
        "mypy": ["mypy", path],
        "pyright": ["pyright", path],
    }
    
    cmd = commands.get(t)
    if not cmd:
        return {"success": False, "error": f"Unknown type checker: {t}"}
    
    try:
        result = subprocess.run(cmd, cwd=path if os.path.isdir(path) else ".",
                                capture_output=True, text=True, timeout=60)
        output = result.stdout + "\n" + result.stderr
        if len(output) > 5000:
            output = output[:5000] + "\n...[truncated]"
        return {"success": result.returncode == 0, "result": output.strip()}
    except FileNotFoundError:
        return {"success": False, "error": f"Type checker '{cmd[0]}' not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _detect_test_framework(path: str) -> str:
    """Auto-detect the test framework from project files."""
    p = Path(path)
    if (p / "pytest.ini").exists() or (p / "pyproject.toml").exists():
        return "pytest"
    if (p / "jest.config.js").exists() or (p / "jest.config.ts").exists():
        return "jest"
    if (p / "vitest.config.ts").exists() or (p / "vitest.config.js").exists():
        return "vitest"
    if (p / "phpunit.xml").exists() or (p / "phpunit.xml.dist").exists():
        return "phpunit"
    if (p / "Cargo.toml").exists():
        return "cargo"
    if (p / "go.mod").exists():
        return "go"
    if (p / "package.json").exists():
        return "jest"
    return "pytest"


def _detect_linter(path: str) -> str:
    """Auto-detect the linter from project files."""
    p = Path(path)
    if (p / ".eslintrc.js").exists() or (p / ".eslintrc.json").exists() or (p / "eslint.config.js").exists():
        return "eslint"
    if (p / "ruff.toml").exists() or (p / "pyproject.toml").exists():
        return "ruff"
    if (p / "Cargo.toml").exists():
        return "clippy"
    if (p / "package.json").exists():
        return "eslint"
    return "ruff"
