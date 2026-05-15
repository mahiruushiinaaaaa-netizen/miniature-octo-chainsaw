"""
agent_helpers.py – Utility functions extracted from agent.py.

Contains helper functions that support the agent coordinator but don't
belong in any specific domain module (retry, pipeline, prompts, etc.).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional, Union

from .config import Config


def try_quick_math(goal: str) -> Optional[str]:
    """Quick check for simple math expressions like '123+345' or 'what is 123+345?'"""
    match = re.search(r'(\d+(?:\.\d+)?)\s*([+\-*/%])\s*(\d+(?:\.\d+)?)', goal)
    if not match:
        return None
    try:
        a, op, b = float(match.group(1)), match.group(2), float(match.group(3))
        ops = {'+': a + b, '-': a - b, '*': a * b, '/': a / b if b else None, '%': a % b if b else None}
        result = ops.get(op)
        if result is None:
            return "Division by zero"
        return str(int(result)) if isinstance(result, float) and result.is_integer() else str(round(result, 2))
    except (ValueError, ZeroDivisionError):
        return None


def summarize_history(config: Config, observations: list[Union[str, object]], limit_chars: int) -> str:
    """Summarize old observations dynamically to fit within the character limit."""
    if not observations:
        return ""
    obs_strs = [str(o) for o in observations]
    if len("\n".join(obs_strs)) <= limit_chars:
        return "\n".join(obs_strs)
    keep_start = [obs_strs[0]]
    current_len = len(obs_strs[0])
    keep_end = []
    for obs in reversed(obs_strs[1:]):
        if current_len + len(obs) + 50 < limit_chars:
            keep_end.insert(0, obs)
            current_len += len(obs)
        else:
            break
    if len(keep_end) < len(obs_strs) - 1:
        return "\n".join(keep_start) + "\n... [intermediate history truncated] ...\n" + "\n".join(keep_end)
    return "\n".join(obs_strs)


def compact_text(text: str, limit: int) -> str:
    """Truncate text to fit within limit, keeping start and end."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit // 2] + "\n... [truncated] ...\n" + text[-limit // 2:]


def compute_limits(intent: str, ctx_chars: int, MAX_REPO: int, MAX_SESS: int, MAX_OBS: int):
    """Compute context size limits based on intent."""
    if intent == "EDIT":
        return int(ctx_chars * 0.05), min(int(ctx_chars * 0.05), 500), min(int(ctx_chars * 0.20), MAX_OBS), min(int(ctx_chars * 0.60), MAX_SESS), int(ctx_chars * 0.05)
    elif intent == "QUERY":
        return int(ctx_chars * 0.05), min(int(ctx_chars * 0.10), 300), min(int(ctx_chars * 0.20), MAX_OBS), min(int(ctx_chars * 0.10), 800), int(ctx_chars * 0.05)
    return int(ctx_chars * 0.05), min(int(ctx_chars * 0.15), 1000), min(int(ctx_chars * 0.30), MAX_OBS), min(int(ctx_chars * 0.40), MAX_SESS), int(ctx_chars * 0.05)


def check_prev_step_ok(step: int, observations: list) -> bool:
    """Check if the previous step succeeded."""
    if step > 1 and observations:
        last = str(observations[-1]).lower()
        return "success" in last or "exit_code=0" in last or '"success": true' in last
    return False


def build_fallback_prompt(pm, repo_map, persistent_ctx, session_ctx, obs_text, goal, goal_limit, token_budget_mgr):
    """Build the full prompt for the non-micro (fallback) path."""
    blocks = [f"DIR: {pm.effective_root}"]
    if repo_map.strip():
        blocks.append(f"REPO MAP:\n{repo_map}")
    if persistent_ctx.strip():
        blocks.append(f"MEMORY:\n{persistent_ctx}")
    if session_ctx.strip():
        blocks.append(f"SESSION:\n{session_ctx}")
    if obs_text.strip():
        blocks.append(f"HISTORY:\n{obs_text}")
    blocks.append(f"USER GOAL: {compact_text(goal, goal_limit)}")
    if token_budget_mgr:
        token_budget_mgr.sections.clear()
        token_budget_mgr.add_section("GOAL", f"DIR: {pm.effective_root}\nUSER GOAL: {compact_text(goal, goal_limit)}", priority=0, mandatory=True)
        if repo_map.strip():
            token_budget_mgr.add_section("REPO_MAP", repo_map, priority=3)
        if persistent_ctx.strip():
            token_budget_mgr.add_section("MEMORY", persistent_ctx, priority=2)
        if session_ctx.strip():
            token_budget_mgr.add_section("CONTEXT", session_ctx, priority=2)
        if obs_text.strip():
            token_budget_mgr.add_section("HISTORY", obs_text, priority=1)
        try:
            return token_budget_mgr.build()
        except ValueError:
            pass
    return "\n\n".join(blocks)


def apply_rag_grounding(intent, goal, executor, pm, prompt, active_system):
    """Apply RAG grounding to enrich the prompt with workspace context."""
    try:
        if intent in ("QUERY", "EXPLORE") and goal and hasattr(executor, 'rag'):
            from .workspace_index import build_workspace_index, relevant_files
            index = build_workspace_index(pm.effective_root, use_cache=True)
            candidates = relevant_files(index, goal, limit=8)
            contents = {}
            for p in candidates:
                try:
                    contents[p] = Path(p).read_text(encoding='utf-8', errors='replace')
                except Exception:
                    continue
            if contents:
                snippets = executor.rag.retrieve_relevant_snippets(goal, contents, top_k=5)
                if snippets:
                    prompt = executor.rag.enrich_prompt(prompt, snippets)
                    if "Cite your sources" not in (active_system or ""):
                        active_system += "\nCRITICAL: Use retrieved context and ALWAYS cite source file paths in responses. If unsure, say 'I don't know'. Do not hallucinate facts."
    except Exception:
        pass
    return prompt, active_system


def handle_exhausted_empties(observations, step, executor, goal):
    """Handle the case where the model has exhausted all empty response retries."""
    from ..ui import ai, err
    if observations and step > 1:
        last_obs = str(observations[-1])
        if "success" in last_obs.lower() or "STATUS: success" in last_obs or "exit_code=0" in last_obs.lower():
            msg = "Task completed successfully. The command ran without errors."
            ai(msg)
            return msg
    err("Agent generated empty responses. Trying web search...")
    try:
        _, result = executor.execute({"action": "web_search", "query": goal}, assume_yes=True)
        snippet = result[:500] if result else "No results"
        ai(f"Web search result: {snippet}")
        return snippet
    except Exception:
        pass
    return "Failed: Model generated empty responses."


def handle_meta_commands(output, observations, step_memory, schemas):
    """Intercept /tools and /commands meta-commands from model output."""
    stripped = output.strip() if output else ""
    if ("/tools" in stripped and len(stripped) < 50) or '"/tools"' in stripped:
        observations.append("Available tools: " + ", ".join(sorted(schemas.keys())) + "\nUse: {\"action\": \"tool_name\", ...params}")
        if step_memory:
            step_memory.record_fact("Used /tools to discover available actions")
        return True
    if ("/commands" in stripped and len(stripped) < 50) or '"/commands"' in stripped:
        observations.append("Commands help:\n- run_cmd: {\"action\":\"run_cmd\",\"command\":\"<shell cmd>\"}\n- answer: {\"action\":\"answer\",\"content\":\"<response>\"}")
        if step_memory:
            step_memory.record_fact("Used /commands to see usage examples")
        return True
    return False


def handle_loop(looped_tool, disabled_tool, tool_disabler, loop_detector, executor, action_params, observations, goal):
    """Handle loop detection recovery. Returns a bail message or None to continue."""
    from ..ui import warn
    if disabled_tool:
        last_obs = str(observations[-1]) if observations else ""
        if "not recognized" in last_obs or "not found" in last_obs:
            failed_cmd = action_params.get("command", "").split()[0] if action_params.get("command") else looped_tool
            return f"I couldn't complete this task because '{failed_cmd}' is not available on your system."
        return f"I got stuck in a loop trying to use '{looped_tool}'. Please try rephrasing your request."
    warn(f"Loop detected on tool: {looped_tool}")
    tool_disabler.record_failure(looped_tool)
    tool_disabler.record_failure(looped_tool)
    tool_disabler.record_failure(looped_tool)
    last_obs = str(observations[-1]) if observations else ""
    if looped_tool == "run_cmd" and ("not recognized" in last_obs or "not found" in last_obs or "command not found" in last_obs):
        failed_cmd = action_params.get("command", "").split()[0] if action_params.get("command") else ""
        try:
            _, search_result = executor.execute({"action": "web_search", "query": f"install {failed_cmd} windows command line"}, assume_yes=True)
            hint = f"'{failed_cmd}' is NOT installed. Install it first:\n{(search_result or '')[:400]}"
        except Exception:
            hint = f"'{failed_cmd}' is not installed. Use 'answer' to tell the user."
        tool_disabler.re_enable_tool(looped_tool)
        loop_detector.reset()
    else:
        hint = f"STOP using '{looped_tool}'. Use 'answer' to report the issue."
    observations.append(f"--- SYSTEM: {hint} ---")
    return None


def display_action(action: dict, action_name: str, live) -> None:
    """Display the current action in the UI."""
    from ..ui import panel
    if action_name == "edit_blocks":
        panel("EDITING", f"Applying edits to {len(action.get('blocks', []))} file(s)...")
    else:
        detail = ""
        if "command" in action:
            detail = f"\nCommand: {action['command']}"
        elif "path" in action:
            detail = f"\nPath: {action['path']}"
        elif "url" in action:
            detail = f"\nURL: {action['url']}"
        panel("ACTION", f"Using tool: {action_name}{detail}", accent="#BD93F9")


def try_auto_install(action_name, action, is_final, result_str, executor, assume_yes, step_memory, observations):
    """Try to auto-install missing dependencies when a command fails."""
    from ..ui import warn, ok
    if action_name != "run_cmd" or is_final:
        return result_str, is_final
    try:
        res = json.loads(result_str)
        output_check = res.get("output", "")
        if not res.get("success", True) and ("not recognized" in output_check or "not found" in output_check or "command not found" in output_check):
            cmd_str = action.get("command", "")
            first_cmd = cmd_str.split("&&")[0].strip().split()[0] if cmd_str else ""
            if first_cmd:
                from .dep_installer import ensure_deps_for_command, get_missing_deps_message, _refresh_path
                msg = get_missing_deps_message(first_cmd)
                if msg:
                    warn(msg)
                    success, install_msg = ensure_deps_for_command(first_cmd)
                    if success:
                        ok("Dependencies installed. Retrying...")
                        _refresh_path()
                        return executor.execute(action, assume_yes)
                    else:
                        bail = f"I tried to auto-install dependencies but failed. Please install '{first_cmd}' manually."
                        observations.append(f"SYSTEM: {bail}")
                        return f"__BAIL__{bail}", is_final
    except (json.JSONDecodeError, KeyError):
        pass
    return result_str, is_final


def build_observation(step, action_name, action, result_str, observation_cls):
    """Build an Observation from executor result."""
    try:
        res = json.loads(result_str)
        return observation_cls(step=step, tool=action_name, output=res.get("output", ""), success=res.get("success", False), input=action, exit_code=res.get("exit_code"), stdout=res.get("stdout"), stderr=res.get("stderr"))
    except Exception:
        return observation_cls(step=step, tool=action_name, output=result_str, success="FAILED" not in result_str.upper(), input=action)


# Legacy aliases for backward compatibility
_try_quick_math = try_quick_math
_summarize_history = summarize_history
_compact_text = compact_text
