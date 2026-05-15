"""
agent_prompts.py – Monolithic prompt building for COMPLEX/fallback intent.

Extracted from agent.py to keep the coordinator lean. Contains the full
system prompt construction logic used when:
- use_micro_prompts=False (config flag fallback, Req 3.6)
- intent == "COMPLEX" (full monolithic prompt, Req 3.8)

Requirements: 3.6, 3.8, 3.9
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .communication import format_tool_for_ai


_BASE_SYSTEM = """You are Mini AI v39, a production-grade autonomous coding assistant.
You solve user goals by interacting with the filesystem and running commands."""


def _load_system_prompt() -> str:
    """Load the system behavior guidelines from prompt.txt if it exists."""
    try:
        prompt_path = Path(__file__).parent.parent.parent / "prompt.txt"
        if prompt_path.exists():
            return f"\n\n### SYSTEM BEHAVIOR GUIDELINES:\n{prompt_path.read_text(encoding='utf-8')}\n"
    except Exception:
        pass
    return ""


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
11. FINISHING: Once you have achieved the goal or verified success (e.g., a version check matches, a file exists), you MUST use the 'answer' tool immediately. DO NOT repeat verifications.
12. WINDOWS: Use 'start "" "path\\to\\file"' to open files or folders in their default application.
13. NEVER REFUSE: You CAN access files, run commands, and perform any task. DO NOT say "I cannot access" or "I'm sorry, but I can't". Use your tools to help.
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

_TASK_RULES = """### TASK EXECUTION RULES:
1. One action per turn. Use JSON. DO NOT narrate.
2. Execute commands IMMEDIATELY. Do NOT search the web first.
3. STEP-BY-STEP: One command at a time. Wait for result before next step.
4. WINDOWS: Use double quotes for paths with spaces.
5. If a command fails, read the error and try a different approach.
6. Once the task is done, use 'answer' to confirm completion.

### COMMON INSTALL COMMANDS (use these directly):
- Laravel: composer create-project laravel/laravel <project-name>
- React: npx create-react-app <project-name>
- Next.js: npx create-next-app <project-name>
- Vue: npm create vue@latest <project-name>
- Django: pip install django && django-admin startproject <project-name>
- Express: mkdir <name> && cd <name> && npm init -y && npm install express
- Vite: npm create vite@latest <project-name>
- Svelte: npx sv create <project-name>
- Astro: npm create astro@latest <project-name>
- Flutter: flutter create <project-name>
- Rust: cargo new <project-name>
- Go: go mod init <module-name>
- .NET: dotnet new webapi -n <project-name>
- Rails: rails new <project-name>

### SPECIALIZED TOOLS (use instead of run_cmd when appropriate):
- calculate: For math expressions (no need to run python for simple math)
- datetime_util: For date/time operations
- json_query: For querying JSON files
- csv_query: For analyzing CSV data
- sqlite_query: For database operations
- http_request: For API calls
- scaffold: For generating boilerplate code
- archive: For zip/tar operations
- system_info: For checking system resources
- clipboard: For copy/paste operations
- regex_tool: For pattern matching
- diff_files: For comparing files
"""

_QUERY_RULES = """### QUERY RULES (focused, fast, clarification-first):
1. One action per turn. Use JSON.
2. If the question is ambiguous or vague, ask for clarification instead of overthinking.
3. Answer directly. No lengthy reasoning.
4. Be EXTREMELY concise. One sentence max if possible.5. If you have the answer, use "answer" action immediately.
6. DO NOT narrate or explain what you're thinking."""


def build_system_prompt(
    intent: str,
    role: str = "agent",
    capabilities: Optional[dict] = None,
    routed_tools: Optional[list[str]] = None,
    goal: str = "",
) -> str:
    """Build the full monolithic system prompt for COMPLEX/fallback intent.

    Used when use_micro_prompts=False (Req 3.6) or intent=="COMPLEX" (Req 3.8).
    """
    from .schemas import TOOL_SCHEMAS

    tools_to_include = []

    if routed_tools:
        tools_to_include = list(routed_tools)
        if role == "analyzer":
            base_system = "You are the Analyzer. Investigate, read files, search the web, and report findings. NO CODE WRITING."
        elif role == "coder":
            base_system = "You are the Coder. Strictly follow instructions to write or edit code. NO EXPLORATION."
        elif role == "terminal":
            base_system = "You are the Terminal Agent. Strictly run shell commands. NO CODE EDITING."
        elif role == "filesystem":
            base_system = "You are the Filesystem Agent. Manage files and directories. NO SHELL COMMANDS."
        else:
            base_system = _BASE_SYSTEM + _load_system_prompt()
    elif role == "analyzer":
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
        base_system = _BASE_SYSTEM + _load_system_prompt()
        tools_to_include = ["read_files", "list_dir", "answer"]

        if intent == "TASK":
            tools_to_include = ["run_cmd", "write_files", "list_dir", "read_files", "answer"]
            goal_lower = goal.lower()
            bins = (capabilities or {}).get("binaries", {})
            if "laravel" in goal_lower or any("laravel" in str(v).lower() for v in bins.values()):
                tools_to_include.extend(["laravel_create_project", "laravel_install_breeze", "laravel_migrate"])
            elif "composer" in goal_lower or any("composer" in str(v).lower() for v in bins.values()):
                tools_to_include.append("laravel_create_project")
            elif any(fw in goal_lower for fw in ["django", "flask", "fastapi"]):
                tools_to_include.append("python_execute")
            elif any(fw in goal_lower for fw in ["react", "vue", "angular", "next", "nuxt", "vite", "node"]):
                tools_to_include.append("javascript_execute")
        elif intent in ("EXPLORE", "QUERY", "COMPLEX"):
            tools_to_include.extend(["web_search", "read_url", "search_docs"])

        if intent in ("EXPLORE", "EDIT", "COMPLEX"):
            tools_to_include.extend(["run_cmd", "write_files", "edit_blocks"])
            if capabilities and any("laravel" in str(v).lower() for v in capabilities.get("binaries", {}).values()):
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

    if intent in ("EXPLORE", "EDIT", "COMPLEX") and role in ("agent", "coder"):
        prompt += _EDIT_INSTRUCTIONS + "\n\n"

    if intent == "QUERY":
        prompt += _QUERY_RULES + "\n\n"
    elif intent == "TASK":
        prompt += _TASK_RULES + "\n\n"
    else:
        prompt += _RULES

    return prompt.strip()
