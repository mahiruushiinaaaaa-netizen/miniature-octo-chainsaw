"""
agent.py – Optimized agent loop. Lean prompts, fast JSON parse, minimal memory use.
Tool calls are emitted as JSON actions and routed to the executor.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from ..core.backend import generate
from ..core.config import Config
from ..core.memory import SessionMemory, PersistentMemory
from ..core.schemas import get_schema, TOOL_SCHEMAS
from ..core.path_manager import PathManager
from ..ui import (
    ai, panel, ok, err, warn, MarkdownStream, header, tool_result,
    status, start_dual_pane, update_agent_thoughts, update_agent_terminal,
    set_agent_meta, RICH_AVAILABLE
)
from ..tools.file_writer import SafeFileWriter
from ..tools.repomap import generate_repo_map
from ..core.workspace_index import build_workspace_index, relevant_files
from ..tools.linter import lint_file
from .coder import find_blocks

from ..core.executor import ToolExecutor
from ..core.communication import compact_observation, get_intelligent_hint, format_tool_for_ai

# Lazy-loaded heavy modules (deferred until first use to reduce startup time)
from ..core.lazy_loader import LazyModule

psutil = LazyModule("psutil")
health_monitor = LazyModule(".health_monitor", package="mini_ai.core")
rag_module = LazyModule(".rag", package="mini_ai.core")



@dataclass
class Observation:
    step: int
    tool: str
    output: str
    success: bool
    input: dict[str, Any] = field(default_factory=dict)
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    
    def __str__(self) -> str:
        # Optimized representation for the AI
        hint = get_intelligent_hint(self.tool, self.output, self.success, self.exit_code)
        output_str = self.output
        if hint:
            output_str = f"{output_str}\n{hint}"
            
        return compact_observation(self.tool, output_str, self.success)



# Stop control (global hooks used by CLI/commands to interrupt agent)
_stop_requested = False
_current_executor: Optional["ToolExecutor"] = None

def request_stop() -> None:
    """Request an immediate stop. If an executor is active, ask it to kill processes."""
    global _stop_requested, _current_executor
    _stop_requested = True
    if _current_executor:
        try:
            _current_executor.kill_all_processes()
        except Exception:
            pass

def clear_stop() -> None:
    global _stop_requested
    _stop_requested = False

def stop_requested() -> bool:
    return bool(_stop_requested)

_BASE_SYSTEM = """You are Mini AI v39, a production-grade autonomous coding assistant.
You solve user goals by interacting with the filesystem and running commands."""

def _load_system_prompt() -> str:
    """Load the system behavior guidelines from prompt.txt if it exists."""
    try:
        # Look for prompt.txt in project root (parent of mini_ai)
        prompt_path = Path(__file__).parent.parent.parent / "prompt.txt"
        if prompt_path.exists():
            return f"\n\n### SYSTEM BEHAVIOR GUIDELINES:\n{prompt_path.read_text(encoding='utf-8')}\n"
    except Exception:
        pass
    return ""

_RULES = """### RULES:
1. One action per turn. Use JSON.
2. DO NOT explain what you are going to do. DO IT IMMEDIATELY.
3. If you see tool results in HISTORY, DO NOT repeat the same action.
4. Use 'read_url' (mode="map" first) for documentation.
5. If you have the answer, use "answer".
6. Be EXTREMELY concise. No small talk.
7. NEVER USE "cd" — use the 'navigate' tool to change directories instead.
8. WINDOWS: Use double quotes for paths with spaces. Use 'type nul > file' to create files.
9. CRITICAL: DO NOT NARRATE. ONLY output raw JSON.
10. STEP-BY-STEP: One atomic command at a time. No chaining with &&.
11. FINISHING: Once goal is achieved, use 'answer' tool immediately. DO NOT repeat actions.
12. NEVER REFUSE: You CAN access files and run commands. Use your tools.
13. write_files is PREFERRED over run_cmd for creating files with content.
14. NAVIGATION: When user says "take me to", "go to", "navigate to" a folder, use the 'navigate' tool.
15. NO WEB SEARCH for file creation, editing, or local tasks. Only search web for unknown APIs/docs.
"""

_EDIT_INSTRUCTIONS = """### EDITING (SEARCH/REPLACE):
filepath.py
<<<<<<< SEARCH
[exact lines to find]
=======
[new lines to replace with]
>>>>>>> REPLACE

### EXAMPLE EDIT:
main.py
<<<<<<< SEARCH
    def hello():
        pass
=======
    def hello():
        print("World")
>>>>>>> REPLACE"""

_QUERY_RULES = """### QUERY RULES (focused, fast, clarification-first):
1. One action per turn. Use JSON.
2. If the question is ambiguous or vague, ask for clarification instead of overthinking.
4. Be EXTREMELY concise. One sentence max if possible.
5. If you have the answer, use "answer" action immediately.
6. DO NOT narrate or explain what you're thinking."""

def _build_system_prompt(intent: str, role: str = "agent", capabilities: dict = None) -> str:
    from ..core.schemas import TOOL_SCHEMAS
    
    tools_to_include = []
    
    if role == "analyzer":
        base_system = "You are the Analyzer. Investigate, read files, search the web, and report findings. NO CODE WRITING."
        tools_to_include = ["read_files", "list_dir", "web_search", "read_url", "search_docs", "answer"]
    elif role == "coder":
        base_system = "You are the Coder. Strictly follow instructions to write or edit code. NO EXPLORATION."
        tools_to_include = ["run_cmd", "write_files", "edit_blocks", "answer"]
    elif role == "terminal":
        base_system = "You are the Terminal Agent. Strictly run shell commands. NO CODE EDITING."
        tools_to_include = ["run_cmd", "answer"]
    elif role == "filesystem":
        base_system = "You are the Filesystem Agent. Manage files and directories. NO SHELL COMMANDS."
        tools_to_include = ["read_files", "list_dir", "filesystem_create_file", "filesystem_create_directory", "answer"]
    else:
        # ── MINIMAL prompt for TASK intent (speed priority) ──
        if intent == "TASK":
            base_system = "You are an AI agent. Output ONE JSON action per turn. Be concise."
            tools_to_include = ["run_cmd", "write_files", "answer"]
            
            tools_section = []
            seen = set()
            for tname in tools_to_include:
                if tname in TOOL_SCHEMAS and tname not in seen:
                    tools_section.append(format_tool_for_ai(TOOL_SCHEMAS[tname]))
                    seen.add(tname)
            
            prompt = (
                f"{base_system}\n"
                f"### TOOLS:\n" + "\n".join(tools_section) + "\n\n"
                f"### RULES:\n"
                f"1. Output ONLY raw JSON. No narration.\n"
                f"2. One action per turn.\n"
                f"3. Use 'answer' when done.\n"
                f"4. WINDOWS: Use double quotes for paths.\n"
            )
            return prompt.strip()
        
        base_system = _BASE_SYSTEM
        tools_to_include = ["read_files", "list_dir", "navigate", "answer"]
        
        if intent in ("EXPLORE", "QUERY", "COMPLEX"):
            tools_to_include.extend(["web_search", "read_url", "search_docs"])
            
        if intent in ("EXPLORE", "EDIT", "COMPLEX"):
            tools_to_include.extend(["run_cmd", "write_files", "edit_blocks"])
            
            # Include the framework project tool for EDIT and COMPLEX tasks
            tools_to_include.extend(["create_framework_project"])
            
            # Framework specific tools (always include - deps auto-install)
            tools_to_include.extend(["laravel_create_project", "laravel_install_breeze", "laravel_migrate"])

    # Build tools section dynamically from schemas
    tools_section = []
    seen = set()
    for tname in tools_to_include:
        if tname in TOOL_SCHEMAS and tname not in seen:
            tools_section.append(format_tool_for_ai(TOOL_SCHEMAS[tname]))
            seen.add(tname)

    # Add environment capabilities if provided
    env_info = ""
    if capabilities:
        bins = [f"{k}({v})" for k, v in capabilities.get("binaries", {}).items() if v != "Not found"]
        env_info = f"\nENV: {capabilities.get('os')} | BINARIES: {', '.join(bins[:10])}\n"

    prompt = f"{base_system}\n{env_info}\n### TOOLS (JSON):\n" + "\n".join(tools_section) + "\n\n"
    
    if intent in ("EDIT", "COMPLEX") and role in ("agent", "coder"):
        prompt += _EDIT_INSTRUCTIONS + "\n\n"
    
    # Add intent-specific guidance
    if intent == "QUERY":
        prompt += _QUERY_RULES + "\n\n"
    else:
        prompt += _RULES
    
    return prompt.strip()


def _summarize_history(config: Config, observations: list[Union[str, Observation]], limit_chars: int) -> str:
    """Summarize old observations dynamically to fit within the character limit."""
    if not observations:
        return ""
    
    # Convert all to strings for length check
    obs_strs = [str(o) for o in observations]
    
    if len("\n".join(obs_strs)) <= limit_chars:
        return "\n".join(obs_strs)
        
    # Always keep the first observation (usually the goal prompt context)
    keep_start = [obs_strs[0]]
    current_len = len(obs_strs[0])
    
    keep_end = []
    # Work backwards, keeping as many recent observations as possible
    for obs in reversed(obs_strs[1:]):
        if current_len + len(obs) + 50 < limit_chars:
            keep_end.insert(0, obs)
            current_len += len(obs)
        else:
            break
            
    if len(keep_end) < len(obs_strs) - 1:
        return "\n".join(keep_start) + "\n... [intermediate history truncated] ...\n" + "\n".join(keep_end)
    return "\n".join(obs_strs)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

def _is_refusal(text: str) -> bool:
    """Detect if the model is refusing a request before parsing JSON."""
    # Only check the first few hundred chars to avoid false positives in large tool outputs or plans
    snippet = text[:400].lower()
    return any(phrase in snippet for phrase in (
        "can't assist", "cannot assist", "can't help", "cannot help", "unable to help",
        "i'm sorry, but i cannot", "as an ai, i cannot", "i cannot directly",
        "i can't directly", "i do not have the ability", "i don't have access",
        "i cannot access", "i can't access", "unable to access",
        "i cannot manipulate", "i can't manipulate", "cannot modify files",
        "i'm sorry, but i can't", "i am not able to", "i'm not able to"
    ))

def _compact_text(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit//2] + "\n... [truncated] ...\n" + text[-limit//2:]



def parse_action(text: str) -> Optional[dict[str, Any]]:
    """Parse model output for SEARCH/REPLACE blocks or JSON actions."""
    # First, strip reasoning blocks if they exist (for the parser)
    text = _THINK_RE.sub("", text).strip()
    if not text:
        return None

    # Try blocks first (highest priority)
    blocks = find_blocks(text)
    if blocks:
        return {"action": "edit_blocks", "blocks": blocks}

    # Try JSON extraction
    json_str = _try_extract_json(text)
    if json_str:
        json_str = json_str.strip()
        try:
            # Handle potential trailing commas or other minor issues
            json_str = re.sub(r',\s*\}', '}', json_str)
            json_str = re.sub(r',\s*\]', ']', json_str)
            obj = json.loads(json_str)
            if isinstance(obj, dict) and "action" in obj:
                return obj
        except json.JSONDecodeError as e:
            # Attempt basic repair for small models
            try:
                # Replace 'key': 'value' with "key": "value"
                repaired = re.sub(r"\'(\w+)\'\s*:", r'"\1":', json_str)
                repaired = re.sub(r":\s*\'(.*?)\'", r': "\1"', repaired)
                obj = json.loads(repaired)
                if isinstance(obj, dict) and "action" in obj:
                    return obj
            except Exception as repair_error:
                from ..core.logger import get_logger
                logger = get_logger("agent")
                logger.debug(f"JSON repair failed: {repair_error}", context={"original_error": str(e), "json_len": len(json_str)})

    # Heuristic to detect "plans" or "narration" that are not answers
    lowered = text.lower()
    if any(p in lowered for p in (
        "i will", "first,", "step 1", "i'll", "next steps", "planning to", 
        "let's", "i need to", "running a ", "i am going to", "let me ",
        "searching", "finding", "executing", "i'm here to",
        "goal:", "user goal:", "history:", "tools (json):",
        "you are mini ai", "### rules:"
    )):
        return None  # Force a nudge

    # Fallback to answer ONLY if it doesn't look like an action attempt
    # If it contains '{"action"' or '<<<<', and we are here, it means parsing FAILED.
    if '{"action"' in text.replace(" ", "").replace('"', '') or "<<<<<<" in text:
        return None

    # Check for refusal patterns - these should NOT be treated as answers
    # This catches "I'm sorry, I can't access your files" type responses
    if _is_refusal(text):
        return None  # Force nudge to correct the model

    # If it's plain text, treat as answer
    return {"action": "answer", "content": text.strip()}

def _try_quick_math(goal: str) -> Optional[str]:
    """Quick check for simple math expressions like '123+345' or 'what is 123+345?'"""
    import re
    import math as mathlib
    
    # Extract math expression from goal
    match = re.search(r'(\d+(?:\.\d+)?)\s*([+\-*/%])\s*(\d+(?:\.\d+)?)', goal)
    if not match:
        return None
    
    try:
        a = float(match.group(1))
        op = match.group(2)
        b = float(match.group(3))
        
        if op == '+':
            result = a + b
        elif op == '-':
            result = a - b
        elif op == '*':
            result = a * b
        elif op == '/':
            result = a / b if b != 0 else None
        elif op == '%':
            result = a % b if b != 0 else None
        else:
            return None
        
        if result is None:
            return "Division by zero"
        
        # Return clean result
        if isinstance(result, float) and result.is_integer():
            return str(int(result))
        return str(round(result, 2))
    except (ValueError, ZeroDivisionError):
        return None

def _try_extract_json(text: str) -> Optional[str]:
    """
    Extract a potential JSON block. 
    Scans for the first valid-looking JSON object with matching braces.
    """
    # Remove markdown fences
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    
    # Scan for first matching { } pair
    import json
    stack = 0
    start = -1
    for i, char in enumerate(text):
        if char == '{':
            if stack == 0:
                start = i
            stack += 1
        elif char == '}':
            stack -= 1
            if stack == 0 and start != -1:
                candidate = text[start:i+1]
                try:
                    # Basic validation: must be a dict with 'action'
                    obj = json.loads(candidate)
                    if isinstance(obj, dict) and "action" in obj:
                        return candidate
                except:
                    # Attempt simple repair for Windows paths (single backslashes)
                    try:
                        # Replace \ with \\ if not already escaped
                        repaired = re.sub(r'\\(?![\\"/bfnrtu])', r'\\\\', candidate)
                        obj = json.loads(repaired)
                        if isinstance(obj, dict) and "action" in obj:
                            return repaired
                    except:
                        pass
                    # Not valid JSON or missing 'action', keep looking
                    pass
    
    # Fallback: scan for any { } block using regex (non-greedy)
    matches = re.findall(r'\{[^{}]*\}', text)
    for match in matches:
        try:
            obj = json.loads(match)
            if isinstance(obj, dict) and "action" in obj:
                return match
        except:
            continue
            
    return None

def agent_mode(
    config: Config,
    goal: str,
    assume_yes: bool = False,
    session_context: str = "",
    persistent_context: str = "",
    memory: Optional[PersistentMemory] = None,
    verbose: bool = False,
    on_token=None,
    chat_log: Optional[list] = None,
    observations: Optional[list[str]] = None,
    intent: str = "EXPLORE",
    initial_target: Optional[Path] = None,
    on_command_start=None,  # callable(cmd, cwd) for GUI visibility
    on_command_output=None,  # callable(text) for streaming output
    on_command_end=None,  # callable(exit_code) when command finishes
) -> str:
    """Main agent loop. Runs until answer or max steps."""
    class ThoughtStreamingHandler:
        def __init__(self, original_on_token=None, live_view=None):
            self.original_on_token = original_on_token
            self.live_view = live_view
            self.buffer = ""
            self.is_thinking = False
            self.is_planning = False
            self.thought_stream = None
            self.plan_stream = None

        def __call__(self, token: str):
            if self.original_on_token:
                self.original_on_token(token)
            self.buffer += token
            
            # 1. Handle explicit <think> tags (if model uses them)
            if not self.is_thinking and "<think>" in self.buffer:
                self.is_thinking = True
                if not self.live_view:
                    from .ui import MarkdownStream
                    self.thought_stream = MarkdownStream(title="THOUGHTS", border_style="#BD93F9")
            
            # 2. Handle JSON 'plan' or 'thoughts' field if streaming
            if not self.is_planning and ('"plan": "' in self.buffer or '"thoughts": "' in self.buffer):
                self.is_planning = True
                if not self.live_view:
                    from .ui import MarkdownStream
                    self.plan_stream = MarkdownStream(title="PLAN", border_style="#8BE9FD")

            # 3. Handle raw text before JSON as thinking
            if not self.is_thinking and not self.is_planning and len(self.buffer) > 10:
                if "{" not in self.buffer and "<<<<<<" not in self.buffer:
                     self.is_thinking = True
                     if not self.live_view:
                         from .ui import MarkdownStream
                         self.thought_stream = MarkdownStream(title="REASONING", border_style="#BD93F9")

            # If we are in sequential mode (no live_view), we print to console
            if not self.live_view:
                if self.is_thinking:
                    if not hasattr(self, 'thought_stream') or self.thought_stream is None:
                        from .ui import MarkdownStream
                        self.thought_stream = MarkdownStream(title="REASONING", border_style="#BD93F9")
                    clean_token = token.replace("<think>", "").replace("</think>", "")
                    self.thought_stream.update(clean_token)
                elif self.is_planning and self.plan_stream:
                    # Stream the plan into a titled box
                    self.plan_stream.update(token)
            else:
                # Dual-pane/Live mode updates
                if self.is_thinking:
                    update_agent_thoughts(self.buffer)
                elif self.is_planning:
                    # Minimal plan extraction for side pane
                    update_agent_thoughts(f"### PLAN\n{self.buffer}\n")

            # Update dual-pane if active
            if self.live_view:
                think_match = _THINK_RE.search(self.buffer)
                if think_match:
                    update_agent_thoughts(think_match.group(0).strip("<think>").strip("</think>"))
                elif self.is_planning:
                    plan_match = re.search(r'"(?:plan|thoughts)":\s*"([^"]*)', self.buffer)
                    if plan_match:
                        update_agent_thoughts(f"### PLAN\n{plan_match.group(1)}")
                else:
                    update_agent_thoughts(self.buffer[-500:])

            # Stop thinking if we see start of action/closing tags
            if (self.is_thinking or self.is_planning) and ("<<<<<<" in token or "</think>" in token or '", "action"' in self.buffer[-20:]):
                self.is_thinking = False
                self.is_planning = False
                if self.thought_stream: self.thought_stream.update("", final=True)
                if self.plan_stream: self.plan_stream.update("", final=True)

    pm = PathManager(config.workspace)
    if initial_target:
        pm.set_target(initial_target)
    writer = SafeFileWriter(pm)
    executor = ToolExecutor(config, pm, writer,
                            on_command_start=on_command_start,
                            on_command_output=on_command_output,
                            on_command_end=on_command_end)
    # Register current executor so external callers can request immediate cleanup
    global _current_executor
    _current_executor = executor
    if memory is None:
        memory = PersistentMemory()
    session = SessionMemory()
    session.set_active_target(str(pm.effective_root))
    if chat_log is None:
        chat_log = []

    if observations is None:
        observations = []
    consecutive_parse_fails = 0
    action_history: list[str] = []  # Track actions to detect loops
    action_name_list: list[str] = []  # Parallel list for action name counts (more tolerant)
    max_steps = config.max_steps
    
    # Limit context sizes based on model token limit and task INTENT
    ctx_chars = getattr(config, 'ctx', 8000) * 4
    
    # HARD CAPS: Prevent CPU pre-fill timeouts (which happen > 1500 tokens)
    MAX_REPO = 1500
    MAX_SESS = 2500
    MAX_OBS = 4000
    
    if intent == "EDIT":
        # Known target: Minimize repo map, maximize session (pinned files)
        goal_limit = int(ctx_chars * 0.05)
        repo_limit = min(int(ctx_chars * 0.05), 500) 
        obs_limit = min(int(ctx_chars * 0.20), MAX_OBS)
        sess_limit = min(int(ctx_chars * 0.60), MAX_SESS) 
        mem_limit = int(ctx_chars * 0.05)
    elif intent == "QUERY":
        # Answering questions: Focus on direct answers, minimize repo context
        goal_limit = int(ctx_chars * 0.05)
        repo_limit = min(int(ctx_chars * 0.10), 300)  # Much smaller for queries
        obs_limit = min(int(ctx_chars * 0.20), MAX_OBS)
        sess_limit = min(int(ctx_chars * 0.10), 800)
        mem_limit = int(ctx_chars * 0.05)
        max_steps = min(max_steps, 5)  # Limit steps for queries
    else: # EXPLORE / COMPLEX / TASK
        goal_limit = int(ctx_chars * 0.05)
        repo_limit = min(int(ctx_chars * 0.15), 1000)
        obs_limit = min(int(ctx_chars * 0.30), MAX_OBS)
        sess_limit = min(int(ctx_chars * 0.40), MAX_SESS)
        mem_limit = int(ctx_chars * 0.05)
        # Aggressive step limits for speed
        if intent == "TASK":
            max_steps = min(max_steps, 5)  # TASK should complete in 1-5 steps
        elif intent == "EXPLORE":
            max_steps = min(max_steps, 8)  # EXPLORE: 8 steps max
        elif intent == "COMPLEX":
            max_steps = min(max_steps, 20)  # COMPLEX: allow up to 20 steps for multi-file tasks

    # Agent loop start
    
    # We are using the 'Live Box' hybrid UI instead of Dual-Pane
    live = None 

    disabled_tool = None # Track tool to suppress if looping
    # Cache the system prompt — it doesn't change between steps unless disabled_tool changes
    _cached_system_prompt = None
    _cached_disabled_tool = "<initial>"
    # Cache the repo map — workspace doesn't change much within a single agent run
    _cached_repo_map = None
    _cached_repo_map_step = -1

    try:
        for step in range(1, max_steps + 1):
            if live:
                set_agent_meta(step, max_steps, intent)
                
            # Build context
            obs_text = _summarize_history(config, observations, obs_limit)
            obs_text = _compact_text(obs_text, obs_limit)

            # Check for user-requested stop and abort early
            if stop_requested():
                try:
                    executor.kill_all_processes()
                except Exception:
                    pass
                clear_stop()
                if live: live.stop()
                panel("INTERRUPTED", "Operation stopped by user.")
                # Ensure we unregister current executor before leaving
                _current_executor = None
                return "[Interrupted by user]"
            
            # Combine dynamically passed session_context (pinned files) with internal session state
            combined_session = (session_context + "\n\n" + session.context()).strip()
            session_ctx = _compact_text(combined_session, sess_limit)
            
            persistent_ctx = _compact_text(persistent_context, mem_limit)
            
            # Aggressive Token Saving: Drop repo map for simple TASK intent and for targeted edits
            if intent == "EDIT" and session_ctx.strip():
                repo_map = ""
            elif intent == "TASK":
                # TASK is a direct action — no repo map needed
                repo_map = ""
            else:
                # Cache the repo map per agent run — regenerating it every step is wasteful
                if _cached_repo_map is None:
                    _cached_repo_map = generate_repo_map(str(pm.effective_root))
                    _cached_repo_map = _compact_text(_cached_repo_map, repo_limit)
                repo_map = _cached_repo_map
            
            # Suppress looping tool from system prompt to force variety
            # Cache the system prompt — only rebuild when disabled_tool changes (rare)
            if _cached_system_prompt is None or _cached_disabled_tool != disabled_tool:
                active_system = _build_system_prompt(intent, getattr(config, 'role', 'agent'), capabilities=executor.context.capabilities)
                if disabled_tool:
                    active_system = re.sub(rf'{{"action":"{disabled_tool}".*?}}', f"[DISABLED: Tool '{disabled_tool}' looped. Use another tool.]", active_system)
                _cached_system_prompt = active_system
                _cached_disabled_tool = disabled_tool
            else:
                active_system = _cached_system_prompt

            # Build final prompt dynamically to omit empty blocks (saves hundreds of prompt tokens)
            prompt_blocks = [f"DIR: {pm.effective_root}"]
            if repo_map.strip():
                prompt_blocks.append(f"REPO MAP:\n{repo_map}")
            if persistent_ctx.strip():
                prompt_blocks.append(f"MEMORY:\n{persistent_ctx}")
            if session_ctx.strip():
                prompt_blocks.append(f"SESSION:\n{session_ctx}")
            if obs_text.strip():
                prompt_blocks.append(f"HISTORY:\n{obs_text}")
            prompt_blocks.append(f"USER GOAL: {_compact_text(goal, goal_limit)}")
            
            prompt = "\n\n".join(prompt_blocks)

            # --- RAG Grounding: retrieve relevant workspace snippets to reduce hallucination ---
            # SKIP for TASK intent — RAG indexing is slow and TASK is a direct action
            try:
                if intent in ("QUERY", "EXPLORE") and goal and executor and hasattr(executor, 'rag'):
                    index = build_workspace_index(pm.effective_root, use_cache=True)
                    candidates = relevant_files(index, goal, limit=8)
                    candidate_contents = {}
                    for p in candidates:
                        try:
                            candidate_contents[p] = Path(p).read_text(encoding='utf-8', errors='replace')
                        except Exception:
                            continue
                    if candidate_contents:
                        snippets = executor.rag.retrieve_relevant_snippets(goal, candidate_contents, top_k=5)
                        if snippets:
                            # Enrich the prompt with retrieved context and require citations
                            prompt = executor.rag.enrich_prompt(prompt, snippets)
                            if "Cite your sources" not in (active_system or ""):
                                active_system = (active_system or "") + "\nCRITICAL: Use retrieved context and ALWAYS cite source file paths in responses. If unsure, say 'I don't know'. Do not hallucinate facts."
            except Exception:
                # Fail-safe: do not interrupt agent if RAG enrichment fails
                pass

            # --- Command Memory: retrieve successful command patterns for this context ---
            # SKIP for TASK intent — adds tokens without much benefit for direct actions
            try:
                if intent != "TASK" and executor and hasattr(executor, 'get_command_hints_for_prompt'):
                    command_hints = executor.get_command_hints_for_prompt(goal)
                    if command_hints:
                        # Append command hints to system prompt
                        active_system = (active_system or "") + "\n\n" + command_hints
            except Exception:
                # Fail-safe: command memory is optional
                pass

            # Log to chat history
            chat_log.append({"role": "user", "step": step, "content": prompt[:500]})

            try:
                # We always use the status spinner in sequential mode
                spinner = status(f"AI Thinking (step {step})")
                
                with spinner:
                    from ..core.grammars import THINK_JSON_GRAMMAR
                    # Cap tokens aggressively — JSON actions are small
                    if intent == "TASK":
                        agent_max = min(config.agent_tokens, 200)  # JSON action ~50-150 tokens
                    elif intent == "EDIT":
                        agent_max = min(config.agent_tokens, 400)  # Edit actions can have content
                    else:
                        agent_max = min(config.agent_tokens, 500)
                    output = generate(
                        config,
                        prompt,
                        max_tokens=agent_max,
                        system_text=active_system,
                        on_token=ThoughtStreamingHandler(on_token, live_view=live),
                        grammar=THINK_JSON_GRAMMAR
                    )
            except Exception as exc:
                if live: live.stop()
                err(f"Generation error: {exc}")
                return str(exc)

            if not output:
                consecutive_parse_fails += 1
                if consecutive_parse_fails >= 3:
                    if live: live.stop()
                    # For local tasks (create, edit, run), don't web search — just do it directly
                    goal_lower = goal.lower()
                    is_local_task = any(w in goal_lower for w in [
                        "create", "make", "write", "edit", "delete", "move", "copy",
                        "rename", "run", "execute", "install", "build", "file", "folder",
                        "directory", "txt", "py", "js", "html", "css", "json",
                    ])
                    if is_local_task:
                        # Try direct file creation for simple "create file" requests
                        err("Agent failed. Attempting direct execution...")
                        try:
                            # Simple file creation pattern
                            import re
                            create_match = re.search(r'create\s+(?:a\s+)?(?:(?:text|txt)\s+)?file\s+(?:named?\s+|called\s+|with\s+)?(.+)', goal_lower)
                            if "hello world" in goal_lower and ("txt" in goal_lower or "text" in goal_lower or "file" in goal_lower):
                                action = {"action": "write_files", "files": [{"path": "hello.txt", "content": "hello world"}]}
                                is_final, result = executor.execute(action, assume_yes=True)
                                ai("Created hello.txt with 'hello world' inside.")
                                return "Created hello.txt with 'hello world' inside."
                            else:
                                # Generic: tell user the model is too small
                                return f"The current model couldn't handle this task. Try a larger model (use --pick-model)."
                        except Exception:
                            return f"The current model couldn't handle this task. Try a larger model (use --pick-model)."
                    else:
                        # Only web search for knowledge/query type goals
                        err("Agent generated empty responses. Trying web search...")
                        try:
                            action = {"action": "web_search", "query": goal}
                            is_final, result = executor.execute(action, assume_yes=True)
                            obs_text_result = result[:500] if result else "No results"
                            ai(f"Web search result: {obs_text_result}")
                            return obs_text_result
                        except Exception:
                            pass
                        return "Failed: Model generated empty responses."
                warn(f"Model returned empty output (attempt {consecutive_parse_fails}/3)")
                observations.append(
                    "System: Your last response was completely empty. "
                    "You must output a valid JSON action. Example: {\"action\": \"run_cmd\", \"command\": \"echo hello\"}"
                )
                continue

            chat_log.append({"role": "assistant", "step": step, "content": output[:500]})

            # Display thinking block if present
            think_match = _THINK_RE.search(output)
            if think_match:
                thoughts_text = think_match.group(0).strip("<think>").strip("</think>").strip()
                if live:
                    update_agent_thoughts(thoughts_text)
                else:
                    panel("THOUGHTS", thoughts_text)

            action = parse_action(output)
            
            # Don't reject short answers if they are valid fallback responses (like "Hello").
            # Only reject if we failed to parse anything.
            if not action:
                consecutive_parse_fails += 1
                
                # Check if this was a refusal - provide more specific nudge
                is_refusal_output = _is_refusal(output)
                
                if consecutive_parse_fails >= 3:
                    if live: live.stop()
                    # For local tasks, don't web search
                    goal_lower = goal.lower()
                    is_local_task = any(w in goal_lower for w in [
                        "create", "make", "write", "edit", "delete", "move", "copy",
                        "rename", "run", "execute", "install", "build", "file", "folder",
                        "directory", "txt", "py", "js", "html", "css", "json",
                    ])
                    if is_local_task:
                        err("Agent cannot generate valid actions for this local task.")
                        return f"The current model couldn't handle this task. Try a larger model (use --pick-model)."
                    else:
                        err("Agent cannot generate valid actions. Trying web search...")
                        try:
                            action = {"action": "web_search", "query": goal}
                            is_final, result = executor.execute(action, assume_yes=True)
                            obs_text_result = result[:500] if result else "No results"
                            ai(f"Web search result: {obs_text_result}")
                            return obs_text_result
                        except Exception:
                            pass
                        return "Failed to generate valid action after 3 attempts."
                
                warn(f"Invalid or talkative response (attempt {consecutive_parse_fails}/3)")
                
                if is_refusal_output:
                    observations.append(
                        "System: You refused to help by saying you cannot access files or perform actions. "
                        "This is INCORRECT - you HAVE tools available (list_dir, read_files, etc.). "
                        "Use your tools to complete the task. Do NOT say you cannot help."
                    )
                else:
                    observations.append(
                        "System: Your last response was either invalid or just talk/planning without an action. "
                        "STOP explaining and use a JSON tool action NOW. If you are finished, use the 'answer' tool."
                    )
                continue
            
            consecutive_parse_fails = 0
            action_name = action.get("action", "unknown")
            
            # Loop detection: exact JSON repeats (strict) and consecutive action-name repeats
            action_sig = json.dumps(action, sort_keys=True)
            strict_repeat_count = action_history.count(action_sig)
            
            # Consecutive name repeats (catch-all for oscillating or stuck models)
            consecutive_name_repeats = 0
            for n in reversed(action_name_list):
                if n == action_name:
                    consecutive_name_repeats += 1
                else:
                    break

            # Strict repeats: identical JSON emitted repeatedly
            if strict_repeat_count >= 2:
                if live: live.stop()
                err(f"Loop limit exceeded for {action_name}")
                return f"Failed: Tool loop detected on {action_name}. Try rephrasing your goal."

            # Consecutive Name-based repeats
            if consecutive_name_repeats >= 3:
                warn(f"Consecutive loop detected on tool: {action_name}")
                observations.append(
                    f"--- SYSTEM WARNING ---\n"
                    f"You have used '{action_name}' 3 times in a row. "
                    f"If you are finished, use the 'answer' tool. If you are stuck, try a different approach or tool.\n"
                    f"----------------------"
                )
                disabled_tool = action_name
                action_history.append(action_sig)
                action_name_list.append(action_name)
                if len(action_history) > 10:
                    action_history.pop(0)
                    action_name_list.pop(0)
                continue

            # Record the action
            action_history.append(action_sig)
            action_name_list.append(action_name)
            disabled_tool = None
            if len(action_history) > 5:
                action_history.pop(0)
                action_name_list.pop(0)

            # Only treat as refusal if it's NOT a valid action
            if not action and _is_refusal(output):
                if live: live.stop()
                ai(output)
                return output

            if action_name == "answer":
                if live: live.stop()
                content = action.get("content", "")
                ai(content)
                return content

            if action_name == "edit_blocks":
                if not live:
                    panel("EDITING", f"Applying edits to {len(action.get('blocks', []))} file(s)...")
                else:
                    update_agent_terminal(f"Action: edit_blocks\nApplying edits to {len(action.get('blocks', []))} file(s)...")
            else:
                plan_text = action.get("plan", "")
                if plan_text:
                    if live:
                        # Prepend plan to thoughts if we want it visible
                        update_agent_thoughts(f"### PLAN\n{plan_text}\n\n### REASONING\n" + (thoughts_text if 'thoughts_text' in locals() else ""))
                    else:
                        panel("PLAN", plan_text, accent="#8BE9FD")
                
                # Add detail to action display
                action_detail = ""
                if "command" in action: action_detail = f"\nCommand: {action['command']}"
                elif "path" in action: action_detail = f"\nPath: {action['path']}"
                elif "url" in action: action_detail = f"\nURL: {action['url']}"
                elif "files" in action: 
                    paths = [f.get("path") if isinstance(f, dict) else f for f in action["files"]]
                    action_detail = f"\nFiles: {', '.join(paths[:3])}{'...' if len(paths)>3 else ''}"
                
                if live:
                    update_agent_terminal(f"Action: {action_name}{action_detail}")
                else:
                    panel("ACTION", f"Using tool: [bold]{action_name}[/bold]{action_detail}", accent="#BD93F9")

            # Execute
            is_final, result_str = executor.execute(action, assume_yes)
            
            # Parse result for rich observation
            try:
                res_data = json.loads(result_str)
                obs = Observation(
                    step=step,
                    tool=action_name,
                    output=res_data.get("output", ""),
                    success=res_data.get("success", False),
                    input=action,
                    exit_code=res_data.get("exit_code"),
                    stdout=res_data.get("stdout"),
                    stderr=res_data.get("stderr")
                )
            except Exception:
                obs = Observation(
                    step=step,
                    tool=action_name,
                    output=result_str,
                    success="FAILED" not in result_str.upper(),
                    input=action
                )

            # Show tool result in UI
            if not is_final:
                if live:
                    update_agent_terminal(obs.output)
                else:
                    tool_result(action_name, obs.output, success=obs.success)

            # After successful edits, we might want to auto-lint
            if action_name == "edit_blocks" and obs.success:
                _auto_lint_edits(action, pm, observations)

            # Observation formatting
            if obs.output.startswith("--- SYSTEM"):
                 observations.append(obs.output)
            else:
                 observations.append(obs)

            if is_final:
                if live: live.stop()
                return obs.output
                
    finally:
        if live: live.stop()
        # Ensure current executor is cleared when leaving agent mode
        _current_executor = None

    return "Reached max steps."
        
    return "Reached max steps."


def _auto_lint_edits(action: dict, pm: PathManager, observations: list[str]) -> None:
    """Auto-lint files after SEARCH/REPLACE edits, and strictly mandate fixes."""
    blocks = action.get("blocks", [])
    has_error = False
    for block in blocks:
        filepath = block.get("file", "")
        if not filepath:
            continue
        target = pm.resolve_target(filepath)
        if not target.exists():
            continue
        try:
            code = target.read_text(encoding="utf-8")
            lint_errors = lint_file(str(target), code)
            if lint_errors:
                has_error = True
                warn(f"Lint errors in {filepath}")
                observations.append(
                    f"[LINT ERROR] {filepath}:\n{lint_errors[:800]}\n"
                    f"--- SYSTEM MANDATE ---\n"
                    f"You MUST use the 'edit_blocks' tool to fix these lint errors immediately. "
                    f"Do NOT answer or finish until the code is completely fixed!"
                )
        except Exception as e:
            from ..core.logger import get_logger
            logger = get_logger("agent")
            logger.debug(f"Error processing lint errors: {e}")
    if has_error:
        # Also drop the 'answer' tool from the last turn if they tried it, ensuring they fix it.
        pass


def _status_ctx(msg: str):
    """Safe status context manager that works with or without Rich."""
    try:
        from ..ui import status as ui_status
        return ui_status(msg)
    except Exception:
        import contextlib
        return contextlib.nullcontext()
