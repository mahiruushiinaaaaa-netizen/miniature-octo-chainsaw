"""
test_ops.py – Test running and coverage tools.
Auto-detects test framework from project config files.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


_FRAMEWORK_DETECTION = {
    "pytest": ["pyproject.toml", "pytest.ini", "setup.cfg", "conftest.py"],
    "jest": ["jest.config.js", "jest.config.ts", "jest.config.mjs"],
    "vitest": ["vitest.config.ts", "vitest.config.js"],
    "phpunit": ["phpunit.xml", "phpunit.xml.dist"],
    "cargo": ["Cargo.toml"],
    "go": ["go.mod"],
    "mocha": [".mocharc.yml", ".mocharc.json"],
}

_FRAMEWORK_COMMANDS = {
    "pytest": {"run": ["pytest", "-v"], "coverage": ["pytest", "--cov", "--cov-report=term-missing"], "failed": ["pytest", "--lf", "-v"]},
    "jest": {"run": ["npx", "jest"], "coverage": ["npx", "jest", "--coverage"], "failed": ["npx", "jest", "--onlyFailures"]},
    "vitest": {"run": ["npx", "vitest", "run"], "coverage": ["npx", "vitest", "run", "--coverage"], "failed": ["npx", "vitest", "run", "--reporter=verbose"]},
    "phpunit": {"run": ["php", "vendor/bin/phpunit"], "coverage": ["php", "vendor/bin/phpunit", "--coverage-text"], "failed": ["php", "vendor/bin/phpunit", "--filter"]},
    "cargo": {"run": ["cargo", "test"], "coverage": ["cargo", "test"], "failed": ["cargo", "test"]},
    "go": {"run": ["go", "test", "./..."], "coverage": ["go", "test", "-cover", "./..."], "failed": ["go", "test", "-run", ""]},
    "mocha": {"run": ["npx", "mocha"], "coverage": ["npx", "nyc", "mocha"], "failed": ["npx", "mocha", "--grep"]},
}


def test_op(operation: str, path: str = ".", framework: str = "", options: str = "") -> dict[str, Any]:
    """Test running and coverage.

    Operations:
    - run: run all tests (auto-detect framework)
    - coverage: run with coverage report
    - list: list test files
    - failed: re-run only failed tests

    Args:
        operation: run, coverage, list, failed
        path: project root path
        framework: force framework (pytest, jest, vitest, phpunit, cargo, go, mocha)
        options: extra flags to pass
    """
    operation = operation.lower().strip()
    project_root = Path(path).expanduser().resolve()

    if not project_root.exists():
        return {"success": False, "error": f"Path not found: {path}"}

    # Detect framework
    fw = framework.lower().strip() if framework else _detect_framework(project_root)
    if not fw:
        return {"success": False, "error": "Could not detect test framework. Specify with framework parameter. Supported: pytest, jest, vitest, phpunit, cargo, go, mocha"}

    if operation == "list":
        return _list_tests(project_root, fw)

    if operation in ("run", "coverage", "failed"):
        return _run_tests(project_root, fw, operation, options)

    return {"success": False, "error": f"Unknown operation: '{operation}'. Available: run, coverage, list, failed"}


def _detect_framework(root: Path) -> str:
    """Auto-detect test framework from config files."""
    for fw, config_files in _FRAMEWORK_DETECTION.items():
        for cf in config_files:
            if (root / cf).exists():
                # Extra check: for pyproject.toml, verify it has pytest config
                if cf == "pyproject.toml":
                    try:
                        content = (root / cf).read_text(encoding="utf-8")
                        if "pytest" in content or "tool.pytest" in content:
                            return "pytest"
                    except Exception:
                        pass
                elif cf == "Cargo.toml":
                    return "cargo"
                else:
                    return fw

    # Fallback: check for test directories
    if (root / "tests").exists() or (root / "test").exists():
        if any(root.rglob("*.py")):
            return "pytest"
    if (root / "__tests__").exists() or (root / "test").exists():
        if (root / "package.json").exists():
            return "jest"

    return ""


def _run_tests(root: Path, framework: str, operation: str, options: str) -> dict[str, Any]:
    """Run tests with the detected framework."""
    commands = _FRAMEWORK_COMMANDS.get(framework)
    if not commands:
        return {"success": False, "error": f"Unsupported framework: {framework}"}

    cmd_template = commands.get(operation, commands["run"])
    if not cmd_template:
        cmd_template = commands["run"]

    # Check command availability
    base_cmd = cmd_template[0]
    if base_cmd not in ("npx",) and not shutil.which(base_cmd):
        return {"success": False, "error": f"'{base_cmd}' not found. Install the test framework first."}

    cmd = list(cmd_template)
    if options:
        cmd.extend(options.split())

    try:
        result = subprocess.run(
            cmd, cwd=str(root),
            capture_output=True, text=True, timeout=120
        )
        output = (result.stdout + result.stderr).strip()
        if len(output) > 3000:
            output = output[:3000] + "\n...[truncated]"

        # Parse results
        summary = _parse_test_output(output, framework)
        if summary:
            output = f"{summary}\n\n{output}"

        return {
            "success": result.returncode == 0,
            "result" if result.returncode == 0 else "error": output or "Tests completed (no output)"
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Tests timed out after 120s"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _list_tests(root: Path, framework: str) -> dict[str, Any]:
    """List test files for the framework."""
    patterns = {
        "pytest": ["test_*.py", "*_test.py"],
        "jest": ["*.test.js", "*.test.ts", "*.spec.js", "*.spec.ts"],
        "vitest": ["*.test.ts", "*.test.js", "*.spec.ts"],
        "phpunit": ["*Test.php"],
        "cargo": ["*.rs"],  # tests are inline in Rust
        "go": ["*_test.go"],
        "mocha": ["*.test.js", "*.spec.js"],
    }

    globs = patterns.get(framework, ["test_*.*"])
    test_files = []

    for pattern in globs:
        for f in root.rglob(pattern):
            if "__pycache__" not in str(f) and "node_modules" not in str(f) and ".venv" not in str(f):
                test_files.append(str(f.relative_to(root)))

    if not test_files:
        return {"success": True, "result": f"No test files found for {framework}"}

    test_files.sort()
    return {"success": True, "result": f"Test files ({len(test_files)}):\n" + "\n".join(f"  {f}" for f in test_files[:50])}


def _parse_test_output(output: str, framework: str) -> str:
    """Extract pass/fail summary from test output."""
    if framework == "pytest":
        match = re.search(r'(\d+) passed', output)
        failed = re.search(r'(\d+) failed', output)
        if match or failed:
            parts = []
            if match:
                parts.append(f"{match.group(1)} passed")
            if failed:
                parts.append(f"{failed.group(1)} failed")
            return f"Summary: {', '.join(parts)}"
    elif framework in ("jest", "vitest"):
        match = re.search(r'Tests:\s+(.+)', output)
        if match:
            return f"Summary: {match.group(1)}"
    return ""
