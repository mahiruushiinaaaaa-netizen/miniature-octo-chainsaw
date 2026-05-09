"""
environment.py – Workspace environment discovery and context gathering.
Detects tech stack, structure, dependencies, and conventions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class EnvironmentContext:
    root: Path
    stack: list[str]
    frameworks: list[str]
    languages: list[str]
    package_managers: list[str]
    has_git: bool
    has_docker: bool
    has_tests: bool
    main_entry: str | None
    config_files: list[str]
    conventions: dict[str, Any]


def detect_environment(root: Path) -> EnvironmentContext:
    """Scan workspace and detect environment, tech stack, and conventions."""
    stack = []
    frameworks = []
    languages = []
    package_managers = []
    config_files = []
    has_git = False
    has_docker = False
    has_tests = False
    main_entry = None

    try:
        files = {f.name for f in root.rglob("*") if f.is_file()} if root.exists() else set()
    except Exception:
        files = set()

    # Detect version control
    has_git = (root / ".git").exists()

    # Detect containerization
    has_docker = "Dockerfile" in files or "docker-compose.yml" in files or "docker-compose.yaml" in files

    # Detect testing
    has_tests = any(
        f in files for f in {"pytest.ini", "test_*.py", "tests/", ".test", "jest.config.js"}
    ) or any("__test__" in str(f) for f in (root.rglob("*.py") if root.exists() else []))

    # Python detection
    if "pyproject.toml" in files or "setup.py" in files or "requirements.txt" in files:
        stack.append("Python")
        languages.append("Python")
        package_managers.append("pip/poetry")
        config_files.extend([f for f in files if f in {"pyproject.toml", "setup.py", "setup.cfg"}])
        if "manage.py" in files:
            frameworks.append("Django")
        if "app.py" in files or "main.py" in files:
            main_entry = next((f for f in ["app.py", "main.py"] if f in files), None)

    # Node/JS detection
    if "package.json" in files:
        stack.append("Node.js")
        languages.append("JavaScript/TypeScript")
        package_managers.append("npm/yarn/pnpm")
        config_files.append("package.json")
        
        try:
            pkg = Path(root / "package.json").read_text()
            if "react" in pkg.lower():
                frameworks.append("React")
            if "vue" in pkg.lower():
                frameworks.append("Vue")
            if "svelte" in pkg.lower():
                frameworks.append("Svelte")
            if "express" in pkg.lower():
                frameworks.append("Express")
            if "next" in pkg.lower():
                frameworks.append("Next.js")
            if "vite" in pkg.lower():
                frameworks.append("Vite")
        except Exception:
            pass

        if "index.js" in files or "src/main.js" in files or "src/index.jsx" in files:
            main_entry = next((f for f in ["index.js", "src/main.js", "src/index.jsx"] if f in files), None)

    # PHP detection
    if "composer.json" in files:
        stack.append("PHP")
        languages.append("PHP")
        package_managers.append("Composer")
        config_files.append("composer.json")
        if "artisan" in files:
            frameworks.append("Laravel")
        if "index.php" in files:
            main_entry = "index.php"

    # Ruby detection
    if "Gemfile" in files:
        stack.append("Ruby")
        languages.append("Ruby")
        package_managers.append("Bundler")
        config_files.append("Gemfile")
        if "rails" in str(files).lower():
            frameworks.append("Rails")

    # Go detection
    if "go.mod" in files:
        stack.append("Go")
        languages.append("Go")
        package_managers.append("go modules")

    # Rust detection
    if "Cargo.toml" in files:
        stack.append("Rust")
        languages.append("Rust")
        package_managers.append("Cargo")

    # Detect config conventions
    conventions = _detect_conventions(root, files)

    return EnvironmentContext(
        root=root,
        stack=list(set(stack)),
        frameworks=list(set(frameworks)),
        languages=list(set(languages)),
        package_managers=list(set(package_managers)),
        has_git=has_git,
        has_docker=has_docker,
        has_tests=has_tests,
        main_entry=main_entry,
        config_files=config_files,
        conventions=conventions,
    )


def _detect_conventions(root: Path, files: set[str]) -> dict[str, Any]:
    """Detect code style and naming conventions."""
    conventions = {
        "uses_camel_case": False,
        "uses_snake_case": False,
        "uses_kebab_case": False,
        "indent_size": 2,
        "preferred_quotes": "double",
        "has_eslint": False,
        "has_prettier": False,
        "has_black": False,
    }

    # Check linters/formatters
    conventions["has_eslint"] = ".eslintrc" in files or ".eslintrc.json" in files or ".eslintrc.js" in files
    conventions["has_prettier"] = ".prettierrc" in files or "prettier.config.js" in files
    conventions["has_black"] = "pyproject.toml" in files  # often has black config

    # Detect indentation by sampling a file
    try:
        sample_file = next((f for f in root.rglob("*") if f.suffix in {".py", ".js", ".ts"}), None)
        if sample_file and sample_file.is_file():
            content = sample_file.read_text(errors="replace")[:5000]
            if "    " in content:
                conventions["indent_size"] = 4
            elif "\t" in content:
                conventions["indent_size"] = "tab"
    except Exception:
        pass

    # Detect naming conventions in filenames
    filenames = list(files)
    camel_count = len([f for f in filenames if re.match(r"[a-z]+[A-Z]", f)])
    snake_count = len([f for f in filenames if "_" in f and f.islower()])
    kebab_count = len([f for f in filenames if "-" in f])

    if camel_count > snake_count and camel_count > kebab_count:
        conventions["uses_camel_case"] = True
    elif snake_count > camel_count and snake_count > kebab_count:
        conventions["uses_snake_case"] = True
    elif kebab_count > camel_count and kebab_count > snake_count:
        conventions["uses_kebab_case"] = True

    return conventions


def format_environment(env: EnvironmentContext) -> str:
    """Format environment context for display and prompts."""
    lines = [
        f"Root: {env.root}",
        f"Stack: {', '.join(env.stack) or 'unknown'}",
    ]

    if env.frameworks:
        lines.append(f"Frameworks: {', '.join(env.frameworks)}")
    if env.languages:
        lines.append(f"Languages: {', '.join(env.languages)}")
    if env.package_managers:
        lines.append(f"Package Managers: {', '.join(env.package_managers)}")

    lines.append("")
    lines.append("Environment:")
    if env.has_git:
        lines.append("  ✓ Git repository")
    if env.has_docker:
        lines.append("  ✓ Docker setup")
    if env.has_tests:
        lines.append("  ✓ Tests present")
    if env.main_entry:
        lines.append(f"  • Entry point: {env.main_entry}")

    if env.config_files:
        lines.append(f"  • Config files: {', '.join(env.config_files)}")

    lines.append("")
    lines.append("Conventions:")
    if env.conventions["has_eslint"]:
        lines.append("  • ESLint configured")
    if env.conventions["has_prettier"]:
        lines.append("  • Prettier configured")
    if env.conventions["uses_camel_case"]:
        lines.append("  • camelCase naming")
    elif env.conventions["uses_snake_case"]:
        lines.append("  • snake_case naming")
    elif env.conventions["uses_kebab_case"]:
        lines.append("  • kebab-case naming")

    return "\n".join(lines)
