"""
orchestrator.py – High-level agent orchestration.
Coordinates planning, execution, and review phases.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional, List, Dict

from .agent import agent_mode
from .task_result import TaskResult
from ..core.config import Config
from ..core.memory import PersistentMemory, SessionMemory
from ..core.workspace import detect_environment
from ..ui import header, panel, ok, err, warn, status, ai, task_header, environment_table
from ..core.workspace import format_environment
from .planner import create_plan, format_plan, Task, TaskGraph
from .reviewer import review_final_output
from .reviewer import review_final_output, format_review
def _route_task(task: Task) -> str:
    """Heuristically determine the best expert role for a given task."""
    tags = [t.lower() for t in task.tags]
    desc = task.description.lower()
    
    if any(t in tags for t in ["code", "edit", "write", "implementation", "coder"]):
        return "coder"
    if any(t in tags for t in ["terminal", "shell", "run", "command", "process", "npm", "pip", "composer", "artisan"]):
        return "terminal"
    if any(t in tags for t in ["file", "dir", "folder", "list", "read", "create", "filesystem"]):
        return "filesystem"
    if any(t in tags for t in ["data", "json", "csv", "parse", "transform", "analyze"]):
        return "data"
    if any(t in tags for t in ["api", "http", "request", "endpoint", "rest", "fetch"]):
        return "api"
    if any(t in tags for t in ["system", "admin", "process", "service", "deploy", "docker"]):
        return "admin"
    
    # Heuristics on description
    if any(x in desc for x in ["implement", "write code", "edit file", "fix bug", "refactor"]):
        return "coder"
    if any(x in desc for x in ["run command", "install", "setup", "start", "migrate", "build", "deploy"]):
        return "terminal"
    if any(x in desc for x in ["create folder", "list directory", "read contents"]):
        return "filesystem"
    if any(x in desc for x in ["parse json", "analyze csv", "transform data", "query data"]):
        return "data"
    if any(x in desc for x in ["call api", "http request", "fetch url", "rest api"]):
        return "api"
    if any(x in desc for x in ["system info", "kill process", "manage service", "check port"]):
        return "admin"
        
    return "agent"


# ---------------------------------------------------------------------------
# Role → ToolRouter task type mapping
# Requirements: 11.1, 11.2, 11.7
# ---------------------------------------------------------------------------

_ROLE_TO_TASK_TYPE: dict[str, str] = {
    "coder": "code_editing",
    "terminal": "default",
    "filesystem": "exploration",
    "agent": "default",
    "data": "data_processing",
    "api": "web_api",
    "admin": "system_admin",
}


def _role_to_task_type(role: str) -> str:
    """Map an orchestrator role to a ToolRouter task type.

    Returns one of: "code_editing", "exploration", "default".
    Falls back to "default" for unrecognized roles (Requirement 11.7).
    """
    return _ROLE_TO_TASK_TYPE.get(role, "default")


def orchestrated_agent_mode(
    config: Config,
    goal: str,
    assume_yes: bool = False,
    memory: Optional[PersistentMemory] = None,
    verbose: bool = False,
    on_token=None,
    initial_target: Optional[Path] = None,
) -> str:
    """Orchestrated agent with TaskGraph execution and dynamic routing."""
    if memory is None: memory = PersistentMemory()
    
    header("ORCHESTRATOR", f"Goal: {goal[:60]}...")
    
    # Phase 1: Understanding & Planning
    panel("PLANNING", f"Analyzing environment and creating task graph for: [bold]{goal}[/bold]")
    
    status("Scanning environment")
    from ..core.environment_inspector import inspect_environment
    caps = inspect_environment()
    env_context = f"OS: {caps.get('os')} {caps.get('os_release')}\nBinaries: {caps.get('binaries')}"
    environment_table(caps, goal=goal)
    ok("Environment inspected.")
    
    plan = create_plan(config, goal, env_context=env_context)
    if not plan:
        err("Failed to create plan")
        return "Planning failed."
    
    ai(f"I've created a {len(plan.graph.tasks)}-task graph to achieve this goal.")
    panel("PLAN OVERVIEW", format_plan(plan), accent="green")
    
    # Phase 2: Execution
    graph = plan.graph
    completed_count = 0
    total_tasks = len(graph.tasks)

    while not graph.is_complete() and not graph.has_failed():
        ready_tasks = graph.get_ready_tasks()
        if not ready_tasks:
            err("Dependency deadlock detected. Cannot proceed.")
            break
            
        for task in ready_tasks:
            task.status = "running"
            role = _route_task(task)
            task_header(completed_count + 1, total_tasks, role, task.title, task.description)
            
            step_context = (
                f"Progress: {completed_count}/{total_tasks} tasks completed\n"
                f"Current task: {task.title} ({task.id})\n{task.description}\n"
                f"\nEnvironment:\n{env_context}"
            )
            
            # Temporary override of role in config for this turn
            current_config = config
            if hasattr(config, "copy"):
                 current_config = config.copy()
            
            # Inject detected role
            setattr(current_config, "role", role)
            
            success = False
            max_retries = 2
            retry_count = 0
            
            while retry_count <= max_retries:
                if retry_count > 0:
                    warn(f"Retrying task {task.id} (Attempt {retry_count + 1}/{max_retries + 1})...")

                if getattr(config, 'tri_model', False) and getattr(config, 'analyzer_config', None) and getattr(config, 'coder_config', None):
                    # --- Tri-Model Collaborative Pipeline ---
                    panel("ANALYZER", f"Building Context Brief for: {task.id}")
                    analysis_raw = agent_mode(
                        config.analyzer_config,
                        f"Analyze requirements for Task {task.id}: {task.title}. {task.description}\nProject Context:\n{step_context}" + (f"\nPREVIOUS FAILURE: Task failed before. Review and adjust strategy." if retry_count > 0 else ""),
                        assume_yes=assume_yes,
                        persistent_context=memory.context_for(goal),
                        memory=memory,
                        verbose=verbose,
                        intent="QUERY",
                        initial_target=initial_target
                    )
                    analysis_context = TaskResult.from_json(analysis_raw).output
                    
                    panel("CODER", f"Executing implementation for: {task.id}")
                    coder_raw = agent_mode(
                        config.coder_config,
                        f"Execute Task {task.id}: {task.title}. {task.description}\n\nContext Brief from Analyzer:\n{analysis_context}",
                        assume_yes=assume_yes,
                        session_context=step_context,
                        persistent_context=memory.context_for(goal),
                        memory=memory,
                        verbose=verbose,
                        on_token=on_token,
                        intent="EDIT",
                        initial_target=initial_target
                    )
                    coder_result = TaskResult.from_json(coder_raw)
                    result = coder_result.output
                    
                    panel("ANALYZER REVIEW", f"Reviewing task {task.id} execution...")
                    review_out = agent_mode(
                        config.analyzer_config,
                        f"Review the following execution for Task {task.id}:\n{result}\nGoal was: {task.description}",
                        assume_yes=assume_yes,
                        persistent_context=memory.context_for(goal),
                        memory=memory,
                        verbose=verbose,
                        intent="QUERY",
                        initial_target=initial_target
                    )

                    # Convert analyzer review into a structured ReviewResult using reviewer
                    review = review_final_output(config, task.title, result, step_context, require_citations=True)
                    panel("REVIEW RESULT", format_review(review), accent="yellow")

                    # Success only if reviewer accepts and confidence is high
                    success = review.is_acceptable and review.confidence >= 0.6 and len(review.issues) == 0
                else:
                    # --- Standard Pipeline with Dynamic Routing ---
                    result = agent_mode(
                        current_config,
                        f"Task {task.id}: {task.title}. {task.description}" + (f"\nPREVIOUS FAILURE: Task failed before. Review and fix." if retry_count > 0 else ""),
                        assume_yes=assume_yes,
                        session_context=step_context,
                        persistent_context=memory.context_for(goal),
                        memory=memory,
                        verbose=verbose,
                        on_token=on_token,
                        intent="TASK",
                        initial_target=initial_target
                    )
                    # Parse structured TaskResult JSON — no string pattern matching
                    task_result = TaskResult.from_json(result)
                    success = task_result.success
                    result = task_result.output
                
                if success:
                    break
                else:
                    retry_count += 1
            
            if success:
                task.status = "completed"
                task.result = result
                completed_count += 1
                ok(f"Task {task.id} completed successfully.")
            else:
                task.status = "failed"
                err(f"Task {task.id} failed after {max_retries + 1} attempts. Aborting orchestration.")
                break
    
    # Phase 3: Final Review
    panel("FINAL REVIEW", "Verifying overall project state...")
    review = review_final_output(config, goal, "Plan execution complete.", env_context)
    
    if review.is_acceptable:
        ok("Project state verified and acceptable.")
    else:
        err("Review found issues with the final output.")
    
    return "Orchestration complete."
