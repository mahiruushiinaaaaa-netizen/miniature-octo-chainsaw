"""
schemas.py – Tool schemas with validation for reliable tool calling.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ParamType = Literal["string", "list", "dict", "int", "bool", "number"]


@dataclass
class ParamSchema:
    name: str
    type: ParamType
    required: bool = True
    description: str = ""
    items_type: ParamType | None = None


@dataclass
class ToolSchema:
    name: str
    params: list[ParamSchema]
    description: str = ""

    def validate(self, args: dict[str, Any]) -> tuple[bool, str]:
        for param in self.params:
            value = args.get(param.name)
            if value is None:
                if param.required:
                    return False, f"Missing required parameter '{param.name}'"
                continue

            if not self._validate_type(value, param.type, param.items_type):
                return (
                    False,
                    f"Parameter '{param.name}' has type {type(value).__name__}, expected {param.type}",
                )

        return True, ""

    @staticmethod
    def _validate_type(value: Any, expected: ParamType, items_type: ParamType | None = None) -> bool:
        type_map = {
            "string": str,
            "int": int,
            "bool": bool,
            "number": (int, float),
            "list": list,
            "dict": dict,
        }
        expected_class = type_map.get(expected)
        if not isinstance(value, expected_class):
            return False
        if expected == "list" and items_type and value:
            item_class = type_map.get(items_type)
            if item_class and not all(isinstance(item, item_class) for item in value):
                return False
        return True


TOOL_SCHEMAS = {
    "answer": ToolSchema(
        name="answer",
        params=[ParamSchema(name="content", type="string", description="Final response text")],
    ),
    "read_files": ToolSchema(
        name="read_files",
        params=[
            ParamSchema(
                name="files",
                type="list",
                items_type="string",
                description="List of file paths to read",
            )
        ],
    ),
    "write_files": ToolSchema(
        name="write_files",
        params=[
            ParamSchema(
                name="files",
                type="list",
                description="List of {path, content} dicts to write",
            )
        ],
    ),
    "delete_path": ToolSchema(
        name="delete_path",
        params=[ParamSchema(name="path", type="string", description="Path to delete")],
    ),
    "move_path": ToolSchema(
        name="move_path",
        params=[
            ParamSchema(name="src", type="string", description="Source path"),
            ParamSchema(name="dst", type="string", description="Destination path"),
        ],
    ),
    "copy_path": ToolSchema(
        name="copy_path",
        params=[
            ParamSchema(name="src", type="string", description="Source path"),
            ParamSchema(name="dst", type="string", description="Destination path"),
        ],
    ),
    "search_files": ToolSchema(
        name="search_files",
        params=[
            ParamSchema(name="path", type="string", description="Root path to search"),
            ParamSchema(name="pattern", type="string", description="Regex pattern"),
            ParamSchema(name="include", type="string", required=False, description="File glob"),
        ],
    ),
    "list_dir": ToolSchema(
        name="list_dir",
        params=[ParamSchema(name="path", type="string", description="Directory path")],
    ),
    "make_dir": ToolSchema(
        name="make_dir",
        params=[ParamSchema(name="path", type="string", description="Directory path to create")],
    ),
    "workspace_map": ToolSchema(
        name="workspace_map",
        params=[
            ParamSchema(name="path", type="string", description="Root path"),
            ParamSchema(name="max_depth", type="int", required=False, description="Max depth"),
        ],
    ),
    "workspace_index": ToolSchema(
        name="workspace_index",
        params=[
            ParamSchema(name="path", type="string", description="Root path"),
            ParamSchema(name="goal", type="string", description="Task goal"),
        ],
    ),
    "workspace_scan": ToolSchema(
        name="workspace_scan",
        params=[
            ParamSchema(name="path", type="string", description="Root path"),
            ParamSchema(name="goal", type="string", description="Task goal"),
            ParamSchema(name="max_files", type="int", required=False),
            ParamSchema(name="max_snippets", type="int", required=False),
        ],
    ),
    "run_cmd": ToolSchema(
        name="run_cmd",
        params=[
            ParamSchema(name="command", type="string", description="Shell command to run"),
            ParamSchema(name="cwd", type="string", required=False, description="Working directory"),
        ],
    ),
    "web_search": ToolSchema(
        name="web_search",
        params=[ParamSchema(name="query", type="string", description="Search query")],
    ),
    "read_url": ToolSchema(
        name="read_url",
        params=[ParamSchema(name="url", type="string", description="URL to fetch")],
    ),
    "open_browser": ToolSchema(
        name="open_browser",
        params=[ParamSchema(name="url", type="string", description="URL to open")],
    ),
    "play_media": ToolSchema(
        name="play_media",
        params=[ParamSchema(name="query", type="string", description="Song/media query")],
    ),
    "stop_media": ToolSchema(
        name="stop_media",
        params=[],
    ),
    "media_status": ToolSchema(
        name="media_status",
        params=[],
        description="Check what media or song is currently playing",
    ),
    "enqueue_media": ToolSchema(
        name="enqueue_media",
        params=[ParamSchema(name="query", type="string", description="Song/media query to add to queue")],
    ),
    "media_next": ToolSchema(
        name="media_next",
        params=[],
        description="Skip to the next song in the queue",
    ),
    "python_execute": ToolSchema(
        name="python_execute",
        params=[ParamSchema(name="code", type="string", description="Python code to run")],
        description="Execute a Python code snippet in the current sandbox",
    ),
    "javascript_execute": ToolSchema(
        name="javascript_execute",
        params=[
            ParamSchema(name="code", type="string", description="JS/TS code to run"),
            ParamSchema(name="timeout_seconds", type="int", required=False, description="Execution timeout"),
        ],
        description="Execute a JavaScript or TypeScript code snippet using Deno",
    ),
    "batch_read_files": ToolSchema(
        name="batch_read_files",
        params=[
            ParamSchema(
                name="files",
                type="list",
                items_type="string",
                description="List of file paths to read in a single operation",
            )
        ],
        description="Read multiple files in a single batch operation for efficiency",
    ),
    "batch_delete_files": ToolSchema(
        name="batch_delete_files",
        params=[
            ParamSchema(
                name="paths",
                type="list",
                items_type="string",
                description="List of file/directory paths to delete",
            )
        ],
        description="Delete multiple files or directories in a single batch operation",
    ),
    "batch_copy_paths": ToolSchema(
        name="batch_copy_paths",
        params=[
            ParamSchema(
                name="operations",
                type="list",
                description="List of {src, dst} dicts specifying copy operations",
            )
        ],
        description="Copy multiple files or directories in a single batch operation",
    ),
    "batch_move_paths": ToolSchema(
        name="batch_move_paths",
        params=[
            ParamSchema(
                name="operations",
                type="list",
                description="List of {src, dst} dicts specifying move/rename operations",
            )
        ],
        description="Move/rename multiple files or directories in a single batch operation",
    ),
}


def get_schema(action_name: str) -> ToolSchema | None:
    return TOOL_SCHEMAS.get(action_name)


def describe_tool(action_name: str) -> str:
    schema = get_schema(action_name)
    if not schema:
        return f"Unknown tool: {action_name}"
    parts = [f"Tool: {action_name}"]
    if schema.description:
        parts.append(f"  Description: {schema.description}")
    if schema.params:
        parts.append("  Parameters:")
        for param in schema.params:
            req = "required" if param.required else "optional"
            parts.append(f"    - {param.name} ({param.type}) [{req}]")
            if param.description:
                parts.append(f"      {param.description}")
    return "\n".join(parts)
