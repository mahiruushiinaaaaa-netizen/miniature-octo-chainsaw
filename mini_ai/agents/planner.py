from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..core.backend import generate
from ..core.config import Config
from ..ui import ok, status
from ..tools.task_tools import task_kind


@dataclass
class Task:
    id: str
    title: str
    description: str
    dependencies: List[str] = field(default_factory=list)
    status: str = "pending"  # pending, running, completed, failed
    result: Optional[str] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class TaskGraph:
    goal: str
    kind: str
    tasks: Dict[str, Task]
    constraints: List[str] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)
    complexity: str = "medium"

    def get_ready_tasks(self) -> List[Task]:
        """Return tasks whose dependencies are all completed."""
        ready = []
        for task in self.tasks.values():
            if task.status == "pending":
                if all(self.tasks.get(dep) and self.tasks[dep].status == "completed" for dep in task.dependencies):
                    ready.append(task)
        return ready

    def is_complete(self) -> bool:
        return all(t.status == "completed" for t in self.tasks.values())

    def has_failed(self) -> bool:
        return any(t.status == "failed" for t in self.tasks.values())


@dataclass
class Plan:
    goal: str
    kind: str
    graph: TaskGraph
    complexity: str


def parse_plan_response(text: str) -> Plan | None:
    """Parse the model's JSON plan response into a TaskGraph."""
    import json
    import re
    try:
        # Extract JSON
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        data = json.loads(match.group(0))

        goal = str(data.get("goal", "")).strip()
        kind = str(data.get("kind", "general")).strip()
        complexity = str(data.get("complexity", "medium")).strip()

        tasks = {}
        for task_raw in data.get("tasks", []):
            if isinstance(task_raw, dict):
                t_id = str(task_raw.get("id", "")).strip()
                if not t_id: continue
                
                tasks[t_id] = Task(
                    id=t_id,
                    title=str(task_raw.get("title", "")).strip(),
                    description=str(task_raw.get("description", "")).strip(),
                    dependencies=list(task_raw.get("dependencies", [])),
                    tags=list(task_raw.get("tags", []))
                )

        constraints = [str(c).strip() for c in data.get("constraints", [])]
        success_criteria = [str(s).strip() for s in data.get("success_criteria", [])]

        graph = TaskGraph(
            goal=goal,
            kind=kind,
            tasks=tasks,
            constraints=constraints,
            success_criteria=success_criteria,
            complexity=complexity
        )

        return Plan(
            goal=goal,
            kind=kind,
            graph=graph,
            complexity=complexity
        )
    except Exception:
        return None


def create_plan(config: Config, goal: str, env_context: Optional[str] = None) -> Plan | None:
    """Break down a goal into a structured TaskGraph with dependencies."""
    status("Planning: analyzing goal and dependencies...")

    kind = task_kind(goal)

    prompt = (
        f"Break down this goal into a structured task graph with explicit dependencies.\n\n"
        f"Goal: {goal}\n"
        f"Type: {kind}\n"
        f"Current Environment:\n{env_context or 'Unknown'}\n\n"
        f"IMPORTANT: For any task that depends on external facts, APIs, or other files, add the tag 'requires_citation' and include a verification subtask.\n"
        f"Return ONLY valid JSON (no markdown):\n"
        f'{{\n'
        f'  "goal": "{goal}",\n'
        f'  "kind": "{kind}",\n'
        f'  "complexity": "low|medium|high",\n'
        f'  "tasks": [\n'
        f'    {{\n'
        f'      "id": "task_1",\n'
        f'      "title": "Task title",\n'
        f'      "description": "What to do",\n'
        f'      "dependencies": [],\n'
        f'      "tags": ["tag1"]\n'
        f'    }},\n'
        f'    {{\n'
        f'      "id": "task_2",\n'
        f'      "title": "Dependent Task",\n'
        f'      "description": "This runs after task_1",\n'
        f'      "dependencies": ["task_1"],\n'
        f'      "tags": ["tag2"]\n'
        f'    }}\n'
        f'  ],\n'
        f'  "constraints": ["constraint1", ...],\n'
        f'  "success_criteria": ["must do X", ...]\n'
        f'}}\n'
    )

    try:
        output = generate(
            config,
            prompt,
            max_tokens=1500,
            system_text=(
                "You are an orchestration expert. Break complex goals into a dependency graph of SMALL, ATOMIC tasks. "
                "CRITICAL: Check the 'Current Environment' provided. "
                "1. DO NOT create tasks for installing software that is already present. "
                "2. DO NOT create 'check' or 'verify' tasks for software already listed in the environment (e.g. if Node.js is found, don't create a task to check Node.js). "
                "3. Move directly to the first productive step that isn't already satisfied. "
                "Prefer many small steps over few large ones. Return only valid JSON."
            ),
            use_cache=False,
        )
        if not output:
            return None

        plan = parse_plan_response(output)
        if plan:
            ok(f"Plan: {len(plan.graph.tasks)} tasks ({plan.complexity} complexity)")
            return plan
        return None
    except Exception:
        return None


def format_plan(plan: Plan) -> str:
    """Format a plan for display, showing dependencies."""
    lines = [
        f"Goal: {plan.goal}",
        f"Type: {plan.kind}",
        f"Complexity: {plan.complexity}",
        "",
        "Tasks:",
    ]
    for task in plan.graph.tasks.values():
        dep_str = f" [Depends on: {', '.join(task.dependencies)}]" if task.dependencies else ""
        tags_str = f" ({', '.join(task.tags)})" if task.tags else ""
        lines.append(f"  • {task.id}: {task.title}{tags_str}{dep_str}")
        if task.description:
            lines.append(f"    {task.description}")

    if plan.graph.constraints:
        lines.append("")
        lines.append("Constraints:")
        for c in plan.graph.constraints:
            lines.append(f"  - {c}")

    if plan.graph.success_criteria:
        lines.append("")
        lines.append("Success Criteria:")
        for s in plan.graph.success_criteria:
            lines.append(f"  ✓ {s}")

    return "\n".join(lines)
