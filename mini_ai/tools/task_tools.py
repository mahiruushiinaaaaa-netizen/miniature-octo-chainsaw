"""
task_tools.py – Task planning helpers.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any


def safe_name(name: str, default: str = "artifact") -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name).strip())
    return name.strip("_") or default


def task_kind(goal: str) -> str:
    text = goal.lower()

    if any(x in text for x in ("run this project", "start this project", "serve this project", "launch this project")):
        return "run_project"

    if any(x in text for x in ("install", "setup", "set up", "composer", "npm install", "pip install", "requirements")):
        return "install"

    if any(x in text for x in (
        "code", "project", "repo", "workspace", "file", "folder", "app", "website",
        "page", "ui", "bug", "fix", "refactor", "feature",
    )):
        return "code_or_files"

    if any(x in text for x in ("search web", "web search", "search the web", "internet", "look up", "research", "latest", "source", "search about", "search for", "find out", "google")):
        return "research"

    if any(x in text for x in ("write a", "draft", "document", "note", "plan", "checklist", "summary", "artifact", "preview")):
        return "artifact_or_writing"

    return "general"


def make_task_brief(goal: str, project_root: str | None = None) -> str:
    parts = [
        "Task brief",
        f"- Goal: {goal.strip()}",
        f"- Project root: {project_root or 'none'}",
        f"- Kind: {task_kind(goal)}",
        "- General workflow:",
        "  1. Understand the goal.",
        "  2. Inspect only what is needed.",
        "  3. Choose the smallest useful action.",
        "  4. Verify or report the result.",
    ]
    return "\n".join(parts)


def write_task_note(workspace: Path, title: str, content: str) -> Path:
    notes_dir = workspace / ".mini_ai_notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_name(title, "note")
    if "." not in filename:
        filename += ".md"
    path = notes_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def make_todo_markdown(title: str, items: list[Any]) -> str:
    lines = [f"# {title}", ""]
    for item in items:
        if isinstance(item, dict):
            label = str(item.get("task", item.get("label", item))).strip()
        else:
            label = str(item).strip()
        if label:
            lines.append(f"- [ ] {label}")
    return "\n".join(lines).strip() + "\n"


def compact_json(data: dict[str, Any], limit: int = 1200) -> str:
    text = json.dumps(data, ensure_ascii=False)
    return text[:limit] + ("...[truncated]" if len(text) > limit else "")
