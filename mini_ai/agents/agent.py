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
from ..ui import ai, panel, ok, err, warn, MarkdownStream, header, tool_result
from ..tools.file_writer import SafeFileWriter
from ..tools.repomap import generate_repo_map
from ..tools.linter import lint_file
from .coder import find_blocks

from ..core.executor import ToolExecutor


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
        # For small models, we keep the string representation compact but informative
        res = f"TURN {self.step} | TOOL: {self.tool}\n"
        if not self.success:
            res += "STATUS: FAILED\n"
        res += f"OUTPUT: {self.output}"
        return res


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

_RULES = """### RULES:
1. One action per turn. Use JSON.
2. DO NOT explain what you are going to do. DO IT IMMEDIATELY.
3. If you see tool results in HISTORY, DO NOT repeat the same search.
4. Use 'read_url' (mode="map" first) for documentation.
5. If you have the answer, use "answer".
6. Be EXTREMELY concise. No small talk.
7. WINDOWS: ALWAYS use double quotes for absolute paths or paths with spaces.
8. WINDOWS: Use 'type nul > file' instead of 'touch' for creating files.
9. CRITICAL: DO NOT NARRATE. DO NOT say "I will", "Let's", or "Running a command". ONLY output the raw JSON.
10. STEP-BY-STEP: BREAK DOWN COMPLEX STEPS. Instead of one giant command with many operators (&&, |), do one atomic step at a time.
    For example: instead of (mkdir x && cd x && npm install), do (mkdir x) then wait for result, then (cd x), etc.
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
3. Answer directly. No lengthy reasoning.
4. Be EXTREMELY concise. One sentence max if possible.
5. If you have the answer, use "answer" action immediately.
6. DO NOT narrate or explain what you're thinking."""

def _build_system_prompt(intent: str, role: str = "agent", capabilities: dict = None) -> str:
    tools = []
    
    if role == "analyzer":
        base_system = "You are the Analyzer. You investigate, read files, search the web, and report findings. You DO NOT write code."
        tools.append('{"plan":"Reason for action","action":"read_files","files":["/path/to/file"]}')
        tools.append('{"plan":"Reason for action","action":"list_dir","path":"/path"}')
        tools.append('{"plan":"Reason for action","action":"web_search","query":"search term"}')
        tools.append('{"plan":"Reason for action","action":"read_url","url":"https://site.com", "mode":"full"}')
        tools.append('{"plan":"Reason for action","action":"search_docs","query":"how to use hooks"}')
        tools.append('{"plan":"Reason for action","action":"answer","content":"final response"}')
    elif role == "coder":
        base_system = "You are the Coder. You strictly follow instructions to write or edit code. You DO NOT search the web or explore. You ONLY write code."
        tools.append('{"plan":"Reason for action","action":"run_cmd","command":"shell command"}')
        tools.append('{"plan":"Reason for action","action":"write_files","files":[{"path":"...","content":"..."}]}')
        tools.append('{"plan":"Reason for action","action":"answer","content":"final response"}')
    elif role == "terminal":
        base_system = "You are the Terminal Agent. You strictly run shell commands and manage processes. You DO NOT edit code or write files."
        tools.append('{"plan":"Reason for action","action":"run_cmd","command":"shell command"}')
        tools.append('{"plan":"Reason for action","action":"answer","content":"final response"}')
    elif role == "filesystem":
        base_system = "You are the Filesystem Agent. You manage files and directories. You DO NOT run general shell commands."
        tools.append('{"plan":"Reason for action","action":"read_files","files":["/path/to/file"]}')
        tools.append('{"plan":"Reason for action","action":"list_dir","path":"/path"}')
        tools.append('{"plan":"Reason for action","action":"filesystem_create_file","path":"file.txt"}')
        tools.append('{"plan":"Reason for action","action":"filesystem_create_directory","path":"folder"}')
        tools.append('{"plan":"Reason for action","action":"answer","content":"final response"}')
    else:
        base_system = _BASE_SYSTEM
        tools.append('{"plan":"Reason for action","action":"read_files","files":["/path/to/file"]}')
        tools.append('{"plan":"Reason for action","action":"list_dir","path":"/path"}')
        
        if intent in ("EXPLORE", "QUERY", "COMPLEX", "TASK"):
            tools.append('{"plan":"Reason for action","action":"web_search","query":"search term"}')
            tools.append('{"plan":"Reason for action","action":"read_url","url":"https://site.com", "mode":"full"}')
            tools.append('{"plan":"Reason for action","action":"search_docs","query":"how to use hooks"}')
            
        if intent in ("EXPLORE", "EDIT", "COMPLEX", "TASK"):
            tools.append('{"plan":"Reason for action","action":"run_cmd","command":"shell command"}')
            tools.append('{"plan":"Reason for action","action":"write_files","files":[{"path":"...","content":"..."}]}')
            tools.append('{"plan":"Reason for action","action":"edit_blocks","blocks":[{"file":"...","search":"...","replace":"..."}]}')
            
            # Framework specific tools
            if capabilities and any("laravel" in str(v).lower() for v in capabilities.get("binaries", {}).values()):
                tools.append('{"plan":"Reason for action","action":"laravel_create_project","name":"my-app"}')
                tools.append('{"plan":"Reason for action","action":"laravel_install_breeze","path":".", "stack":"blade"}')
                tools.append('{"plan":"Reason for action","action":"laravel_migrate","path":"."}')

        tools.append('{"plan":"Reason for action","action":"answer","content":"final response"}')
    
    # Add environment capabilities if provided
    env_info = ""
    if capabilities:
        env_info = "\n### ENVIRONMENT CAPABILITIES:\n"
        env_info += f"OS: {capabilities.get('os')} {capabilities.get('os_release')}\n"
        env_info += "Binaries: " + ", ".join([f"{k} ({v})" for k, v in capabilities.get("binaries", {}).items() if v != "Not found"])
        env_info += "\n"

    prompt = base_system + env_info + "\n### TOOLS (JSON):\n" + "\n".join(tools) + "\n\n"
    
    if intent in ("EXPLORE", "EDIT", "COMPLEX", "TASK") and role in ("agent", "coder"):
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
    lowered = text.lower()
    return any(phrase in lowered for phrase in (
        "can't assist", "cannot assist", "can't help", "cannot help", "unable to help"
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
) -> str:
    """Main agent loop. Runs until answer or max steps."""
    class ThoughtStreamingHandler:
        def __init__(self, original_on_token=None):
            self.original_on_token = original_on_token
            self.buffer = ""
            self.is_thinking = False
            self.thought_stream = None

        def __call__(self, token: str):
            if self.original_on_token:
                self.original_on_token(token)
            self.buffer += token
            
            # Start thinking panel if we see text before an action
            if not self.is_thinking and len(self.buffer) > 2:
                if "{" not in self.buffer and "<<<<<<" not in self.buffer:
                    self.is_thinking = True
                    from .ui import MarkdownStream, panel
                    panel("THOUGHTS", "")
                    self.thought_stream = MarkdownStream()
            
            if self.is_thinking:
                # Stop thinking if we see start of action
                if "{" in token or "<<<<<<" in token:
                    self.is_thinking = False
                    if self.thought_stream:
                        self.thought_stream.update("", final=True)
                elif self.thought_stream:
                    self.thought_stream.update(token)

    pm = PathManager(config.workspace)
    if initial_target:
        pm.set_target(initial_target)
    writer = SafeFileWriter(pm)
    executor = ToolExecutor(config, pm, writer)
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
    MAX_OBS = 2000
    
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

    header("AGENT MODE", f"Goal: {goal[:60]}... [Tier: {intent}]")
    
    disabled_tool = None # Track tool to suppress if looping

    for step in range(1, max_steps + 1):
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
            panel("INTERRUPTED", "Operation stopped by user.")
            # Ensure we unregister current executor before leaving
            _current_executor = None
            return "[Interrupted by user]"
        
        # Combine dynamically passed session_context (pinned files) with internal session state
        combined_session = (session_context + "\n\n" + session.context()).strip()
        session_ctx = _compact_text(combined_session, sess_limit)
        
        persistent_ctx = _compact_text(persistent_context, mem_limit)
        
        # Aggressive Token Saving: Drop repo map completely if we are doing a targeted edit and already have pinned files.
        if intent == "EDIT" and session_ctx.strip():
            repo_map = ""
        else:
            repo_map = generate_repo_map(str(pm.effective_root))
            repo_map = _compact_text(repo_map, repo_limit)
        
        # Suppress looping tool from system prompt to force variety
        active_system = _build_system_prompt(intent, getattr(config, 'role', 'agent'), capabilities=executor.context.capabilities)
        if disabled_tool:
            active_system = re.sub(rf'{{"action":"{disabled_tool}".*?}}', f"[DISABLED: Tool '{disabled_tool}' looped. Use another tool.]", active_system)

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

        # Log to chat history
        chat_log.append({"role": "user", "step": step, "content": prompt[:500]})

        try:
            with ok.__class__ and _status_ctx(f"Thinking (step {step})"):
                from ..core.grammars import THINK_JSON_GRAMMAR
                output = generate(
                    config,
                    prompt,
                    max_tokens=config.agent_tokens,
                    system_text=active_system,
                    on_token=ThoughtStreamingHandler(on_token),
                    grammar=THINK_JSON_GRAMMAR
                )
        except Exception as exc:
            err(f"Generation error: {exc}")
            return str(exc)

        if not output:
            consecutive_parse_fails += 1
            if consecutive_parse_fails >= 3:
                # Try web search as fallback when stuck
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
            panel("THOUGHTS", think_match.group(0).strip("<think>").strip("</think>").strip())

        action = parse_action(output)
        
        # Don't reject short answers if they are valid fallback responses (like "Hello").
        # Only reject if we failed to parse anything.
        if not action:
            consecutive_parse_fails += 1
            if consecutive_parse_fails >= 3:
                # Try web search as fallback when stuck on invalid actions
                err("Agent cannot generate valid actions. Trying web search...")
                try:
                    action = {"action": "web_search", "query": goal}
                    is_final, result = executor.execute(action, assume_yes=True)
                    obs_text_result = result[:500] if result else "No results"
                    ai(f"Web search result: {obs_text_result}")
                    return obs_text_result
                except Exception:
                    pass
                return "Failed to generate valid action after 3 attempts. Could not find solution via web search."
            
            warn(f"Invalid or talkative response (attempt {consecutive_parse_fails}/3)")
            observations.append(
                "System: Your last response was either invalid or just talk/planning without an action. "
                "STOP explaining and use a JSON tool action NOW. If you are finished, use the 'answer' tool."
            )
            continue
        
        consecutive_parse_fails = 0
        action_name = action.get("action", "unknown")
        
        # Loop detection: exact JSON repeats (strict) and action-name repeats (tolerant)
        action_sig = json.dumps(action, sort_keys=True)
        strict_repeat_count = action_history.count(action_sig)
        name_repeat_count = action_name_list.count(action_name)

        # Strict repeats: identical JSON emitted repeatedly
        if strict_repeat_count >= 2:
            err(f"Loop limit exceeded for {action_name}")
            return f"Failed: Tool loop detected on {action_name}. Try rephrasing your goal."

        # Name-based repeats: same tool being attempted repeatedly with minor variations
        if name_repeat_count >= 2:
            warn(f"Looping on tool name: {action_name} (attempt {name_repeat_count + 1})")
            observations.append(
                f"--- SYSTEM WARNING ---\n"
                f"It looks like you're repeatedly trying to use '{action_name}'.\n"
                f"Stop repeating the same action and either use the HISTORY output or pick a different tool.\n"
                f"----------------------"
            )
            disabled_tool = action_name
            # record this slightly-different attempt and skip execution once
            action_history.append(action_sig)
            action_name_list.append(action_name)
            if len(action_history) > 5:
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

        if _is_refusal(output):
            ai(output)
            return output

        if action_name == "answer":
            content = action.get("content", "")
            ai(content)
            return content

        if action_name == "edit_blocks":
            panel("EDITING", f"Applying edits to {len(action.get('blocks', []))} file(s)...")
        else:
            plan_text = action.get("plan", "")
            if plan_text:
                panel("PLAN", plan_text, accent="#8BE9FD")
            
            # Add detail to action display
            action_detail = ""
            if "command" in action: action_detail = f"\n[muted]Command:[/muted] `{action['command']}`"
            elif "path" in action: action_detail = f"\n[muted]Path:[/muted] `{action['path']}`"
            elif "url" in action: action_detail = f"\n[muted]URL:[/muted] `{action['url']}`"
            elif "files" in action: 
                paths = [f.get("path") if isinstance(f, dict) else f for f in action["files"]]
                action_detail = f"\n[muted]Files:[/muted] {', '.join(paths[:3])}{'...' if len(paths)>3 else ''}"
            
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

        # Show tool result in UI for user visibility
        if not is_final:
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
            return obs.output
        
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
