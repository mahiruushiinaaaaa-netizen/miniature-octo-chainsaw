"""
prompt_templates.py – Structured prompts for different agent roles and phases.
Better prompts = better agent behavior.
"""
from __future__ import annotations


def system_prompt_planner() -> str:
    """System prompt for the planning phase."""
    return (
        "You are an expert project planner and task analyzer.\n"
        "Your job is to break complex goals into clear, sequential, achievable steps.\n"
        "\n"
        "Rules:\n"
        "1. Each step must be concrete and actionable.\n"
        "2. Identify blockers and dependencies.\n"
        "3. Estimate complexity (low/medium/high).\n"
        "4. List constraints and success criteria.\n"
        "5. Prefer small steps over giant ones.\n"
        "\n"
        "Return ONLY valid JSON (no markdown)."
    )


def system_prompt_executor() -> str:
    """System prompt for the execution phase."""
    return (
        "You are an autonomous coding agent with access to filesystem, terminal, and code tools.\n"
        "Execute ONE tool per turn. Use exact paths. Never invent paths.\n"
        "\n"
        "Rules:\n"
        "1. Understand the goal completely before acting.\n"
        "2. Inspect before modifying.\n"
        "3. Use the smallest useful action.\n"
        "4. Verify after important operations.\n"
        "5. Return 'answer' when done (never refuse safe, legal tasks).\n"
        "\n"
        "Tools: answer | read_files | write_files | run_cmd | search_files | workspace_scan | web_search | ...\n"
        "Return ONLY valid JSON tool calls. Example: {\"action\":\"read_files\",\"files\":[\"/path\"]}"
    )


def system_prompt_reviewer() -> str:
    """System prompt for the review phase."""
    return (
        "You are a quality assurance and verification expert.\n"
        "Your job is to critically evaluate agent outputs.\n"
        "\n"
        "Questions to ask:\n"
        "1. Does this solve the goal?\n"
        "2. Are there bugs or issues?\n"
        "3. Is anything incomplete or hallucinated?\n"
        "4. Could this break in production?\n"
        "5. Does it match requirements?\n"
        "\n"
        "Be honest, specific, and strict.\n"
        "Return ONLY valid JSON (no markdown)."
    )


def prompt_plan_goal(goal: str, env_info: str = "") -> str:
    """Prompt to generate a plan for a goal."""
    return (
        f"Break down this goal into a clear, actionable plan.\n\n"
        f"Goal: {goal}\n"
        f"{env_info}\n\n"
        f"Return ONLY valid JSON (no markdown):\n"
        f'{{\n'
        f'  "goal": "{goal}",\n'
        f'  "kind": "task_type",\n'
        f'  "complexity": "low|medium|high",\n'
        f'  "steps": [\n'
        f'    {{"title": "Step title", "description": "What to do", "tags": ["tag1"]}},\n'
        f'    ...\n'
        f'  ],\n'
        f'  "constraints": ["constraint1"],\n'
        f'  "success_criteria": ["criteria1"]\n'
        f'}}\n'
    )


def prompt_execute_step(
    step_title: str, step_description: str, context: str, recent_history: str
) -> str:
    """Prompt to execute a single step."""
    return (
        f"Execute this step:\n\n"
        f"Step: {step_title}\n"
        f"Description: {step_description}\n\n"
        f"Context:\n{context}\n\n"
        f"Recent history:\n{recent_history}\n\n"
        f"Choose ONE tool and return ONLY valid JSON:\n"
        f'Example: {{"action":"read_files","files":["path"]}}'
    )


def prompt_review_output(goal: str, output: str, context: str = "") -> str:
    """Prompt to review final output."""
    return (
        f"Review this output for quality and goal alignment.\n\n"
        f"Original Goal: {goal}\n\n"
        f"Output:\n{output[:2000]}\n\n"
        f"Context:\n{context[:500]}\n\n"
        f"Return ONLY valid JSON (no markdown):\n"
        f'{{\n'
        f'  "is_acceptable": true/false,\n'
        f'  "issues": ["issue1"],\n'
        f'  "warnings": ["warning1"],\n'
        f'  "confidence": 0.0-1.0,\n'
        f'  "suggestions": ["next step"]\n'
        f'}}\n'
    )


def format_environment_context(env_info: str) -> str:
    """Format environment context for inclusion in prompts."""
    return f"\n--- Environment ---\n{env_info}\n---"


def format_memory_context(strategies: list[str], patterns: list[str]) -> str:
    """Format memory context for inclusion in prompts."""
    lines = ["--- Learned Patterns ---"]
    if strategies:
        lines.append("Successful strategies:")
        for s in strategies[:3]:
            lines.append(f"  • {s}")
    if patterns:
        lines.append("Code style conventions:")
        for p in patterns[:3]:
            lines.append(f"  • {p}")
    return "\n".join(lines)
