"""
communication.py – Utilities for optimizing AI-System communication.
Focuses on intelligent feedback, concise prompts, and tool discovery.
"""
from __future__ import annotations
import json
import re
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .schemas import ToolSchema

def format_tool_for_ai(schema: ToolSchema) -> str:
    """Format a tool schema into a concise JSON example for the system prompt."""
    params = {}
    for p in schema.params:
        if p.type == "string":
            val = f"<{p.name}>"
        elif p.type == "list":
            val = [f"<{p.name}_item>"]
        elif p.type == "dict":
            val = {"key": "value"}
        elif p.type == "int":
            val = 0
        elif p.type == "bool":
            val = False
        else:
            val = None
        params[p.name] = val
    
    example = {"plan": "Reason for action", "action": schema.name, **params}
    return json.dumps(example)

def get_intelligent_hint(tool: str, output: str, success: bool, exit_code: int | None = None) -> str | None:
    """Provide specific, actionable hints based on common failure patterns."""
    if success:
        return None
    
    out_low = output.lower()
    
    if tool == "run_cmd":
        if exit_code == 127 or "not recognized" in out_low or "command not found" in out_low:
             cmd = output.split("'")[1] if "'" in output else "command"
             if "touch" in out_low:
                 return "HINT: 'touch' is not native on Windows. Use 'type nul > file' instead."
             return f"HINT: Binary '{cmd}' not found. Check environment or install it."
        
        if "syntax of the command is incorrect" in out_low:
             if "-p" in out_low:
                 return "HINT: 'mkdir -p' is not supported on Windows. Use 'mkdir' without '-p' (it creates parent dirs by default on Windows)."
             if '"' not in output:
                 return "HINT: Possible quoting error. On Windows, ALWAYS use DOUBLE QUOTES for paths with spaces."
        
        if "already exists" in out_low and "mkdir" in out_low:
             if '"' not in output:
                 return "HINT: 'already exists' often means you missed double quotes around a path with spaces. Windows is splitting the path into multiple arguments."
        
        if "permission denied" in out_low:
             return "HINT: Permission denied. Try a different directory or check file attributes."
             
        if "no such file or directory" in out_low:
             return "HINT: Path does not exist. Use 'list_dir' or 'workspace_map' to verify paths."
        
        if "too many arguments to \"create-project\"" in out_low:
             return "HINT: Use 'composer create-project laravel/laravel <dir>' then install dependencies separately."


    if tool == "edit_blocks":
        if "Failed to match SEARCH block" in output:
             return "HINT: The SEARCH block MUST match the file content EXACTLY, including indentation and newlines."

    if tool == "read_files":
        if "not found" in out_low:
             return "HINT: File not found. Double check the path relative to the workspace root."

    return None

def compact_observation(tool: str, output: str, success: bool, limit: int = 2000) -> str:
    """Compact and structure the observation for the AI."""
    status = "SUCCESS" if success else "FAILED"
    
    # Extract only the most relevant part of large outputs
    if len(output) > limit:
        # If it's a log, keep the end
        if any(x in tool for x in ("run_cmd", "web_search", "read_url")):
            output = output[:limit//4] + "\n... [intermediate output truncated] ...\n" + output[-limit//2:]
        elif any(x in tool for x in ("list_dir", "workspace_map", "workspace_index")):
            # For lists, keep the first 30 lines
            lines = output.split("\n")
            if len(lines) > 30:
                output = "\n".join(lines[:30]) + f"\n... [truncated, {len(lines)-30} more items hidden]"
            else:
                output = output[:limit] + "\n... [truncated]"
        else:
            output = output[:limit] + "\n... [truncated]"
            
    res = f"TOOL: {tool} | STATUS: {status}\nOUTPUT: {output}"
    return res.strip()
