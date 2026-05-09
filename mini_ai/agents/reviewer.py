"""
reviewer.py – Self-reflection and output evaluation.
Verifies agent outputs and detects issues before returning to user.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ..core.backend import generate
from ..core.config import Config
from ..ui import ok, err, warn



@dataclass
class ReviewResult:
    is_acceptable: bool
    issues: list[str]
    warnings: list[str]
    confidence: float
    suggestions: list[str]


def review_final_output(config: Config, goal: str, output: str, context: str = "") -> ReviewResult:
    """
    Review agent output for quality, correctness, and goal alignment.
    Returns whether output is acceptable and what issues were found.
    """
    prompt = (
        f"Review this AI agent output for quality, correctness, and goal alignment.\n\n"
        f"Original Goal: {goal}\n\n"
        f"Agent Output:\n{output[:2000]}\n\n"
        f"Context:\n{context[:1000]}\n\n"
        f"Return ONLY valid JSON (no markdown):\n"
        f'{{\n'
        f'  "is_acceptable": true/false,\n'
        f'  "issues": ["critical issue 1", ...],\n'
        f'  "warnings": ["potential issue 1", ...],\n'
        f'  "confidence": 0.0-1.0,\n'
        f'  "suggestions": ["improvement 1", ...]\n'
        f'}}\n'
    )

    try:
        response = generate(
            config,
            prompt,
            max_tokens=600,
            system_text=(
                "You are a quality reviewer. Evaluate outputs critically. "
                "Find issues, hallucinations, incomplete work, or misalignment with goals. "
                "Be honest and specific. Return only valid JSON."
            ),
            use_cache=False,
        )
        if not response:
            return ReviewResult(
                is_acceptable=True,
                issues=[],
                warnings=[],
                confidence=0.5,
                suggestions=[],
            )

        data = _parse_review_json(response)
        return ReviewResult(
            is_acceptable=bool(data.get("is_acceptable", True)),
            issues=list(data.get("issues", [])),
            warnings=list(data.get("warnings", [])),
            confidence=float(data.get("confidence", 0.5)),
            suggestions=list(data.get("suggestions", [])),
        )
    except Exception as exc:
        err(f"Review failed: {exc}")
        return ReviewResult(
            is_acceptable=True,
            issues=[],
            warnings=[],
            confidence=0.0,
            suggestions=[],
        )


def verify_file_operations(outputs: dict[str, Any]) -> ReviewResult:
    """Verify file write operations actually succeeded."""
    issues = []
    warnings = []

    written = outputs.get("written", [])
    failed = outputs.get("failed", [])

    if failed:
        issues.append(f"Failed to write {len(failed)} file(s): {', '.join(failed[:3])}")

    if not written:
        warnings.append("No files were written")

    if written and failed:
        warnings.append(f"Partial success: {len(written)}/{len(written) + len(failed)} files written")

    return ReviewResult(
        is_acceptable=len(failed) == 0,
        issues=issues,
        warnings=warnings,
        confidence=1.0 if not failed else 0.5,
        suggestions=["Check disk space" if failed else ""],
    )


def check_goal_completion(config: Config, goal: str, completed_tasks: list[str]) -> ReviewResult:
    """Check if completed tasks actually address the goal."""
    prompt = (
        f"Does this list of completed tasks fully address the goal?\n\n"
        f"Goal: {goal}\n\n"
        f"Completed tasks:\n" + "\n".join(f"- {t}" for t in completed_tasks[:10]) +
        f"\n\nReturn only: {{\n"
        f'  "is_acceptable": true/false,\n'
        f'  "issues": ["unmet requirement"],\n'
        f'  "confidence": 0.0-1.0,\n'
        f'  "suggestions": ["next step"]\n'
        f"}}\n"
    )

    try:
        response = generate(
            config,
            prompt,
            max_tokens=300,
            system_text="You are a goal verification expert. Be strict. Return only JSON.",
            use_cache=False,
        )
        if not response:
            return ReviewResult(is_acceptable=True, issues=[], warnings=[], confidence=0.5, suggestions=[])

        data = _parse_review_json(response)
        return ReviewResult(
            is_acceptable=bool(data.get("is_acceptable", True)),
            issues=list(data.get("issues", [])),
            warnings=[],
            confidence=float(data.get("confidence", 0.5)),
            suggestions=list(data.get("suggestions", [])),
        )
    except Exception:
        return ReviewResult(is_acceptable=True, issues=[], warnings=[], confidence=0.0, suggestions=[])


def _parse_review_json(text: str) -> dict[str, Any]:
    """Extract JSON from review response."""
    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except Exception:
        pass
    return {}


def format_review(result: ReviewResult) -> str:
    """Format review results for display."""
    status = "✓ ACCEPTABLE" if result.is_acceptable else "✕ ISSUES FOUND"
    lines = [f"{status} (confidence: {result.confidence:.0%})"]

    if result.issues:
        lines.append("")
        lines.append("Issues:")
        for issue in result.issues:
            lines.append(f"  ✕ {issue}")

    if result.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warn in result.warnings:
            lines.append(f"  ⚠ {warn}")

    if result.suggestions:
        lines.append("")
        lines.append("Suggestions:")
        for sugg in result.suggestions:
            if sugg.strip():
                lines.append(f"  → {sugg}")

    return "\n".join(lines)
