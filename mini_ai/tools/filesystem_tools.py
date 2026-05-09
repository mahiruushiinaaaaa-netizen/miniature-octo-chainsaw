"""
filesystem_tools.py – Structured filesystem tools for the agent.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Union
from ..core.platform_adapter import get_platform_adapter

adapter = get_platform_adapter()

def create_file(path: str) -> dict[str, Any]:
    success = adapter.create_file(path)
    return {
        "success": success,
        "output": f"Created file: {path}" if success else f"Failed to create file: {path}",
        "path": path
    }

def create_directory(path: str) -> dict[str, Any]:
    success = adapter.create_directory(path)
    return {
        "success": success,
        "output": f"Created directory: {path}" if success else f"Failed to create directory: {path}",
        "path": path
    }

def delete_path(path: str, recursive: bool = False) -> dict[str, Any]:
    success = adapter.remove_path(path, recursive=recursive)
    return {
        "success": success,
        "output": f"Deleted: {path}" if success else f"Failed to delete: {path}",
        "path": path
    }

def move_path(src: str, dst: str) -> dict[str, Any]:
    success = adapter.move_path(src, dst)
    return {
        "success": success,
        "output": f"Moved {src} to {dst}" if success else f"Failed to move {src} to {dst}",
        "src": src,
        "dst": dst
    }

def copy_path(src: str, dst: str) -> dict[str, Any]:
    success = adapter.copy_path(src, dst)
    return {
        "success": success,
        "output": f"Copied {src} to {dst}" if success else f"Failed to copy {src} to {dst}",
        "src": src,
        "dst": dst
    }

def list_directory(path: str) -> dict[str, Any]:
    items = adapter.list_directory(path)
    return {
        "success": True,
        "output": "\n".join(items) if items else "(empty or not found)",
        "items": items,
        "path": path
    }
