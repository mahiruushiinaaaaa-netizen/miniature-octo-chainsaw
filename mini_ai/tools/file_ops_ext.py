"""
file_ops_ext.py – Advanced file operations.
Find duplicates, bulk rename, tree view, disk usage, find large files, compare directories.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any


def file_op_ext(operation: str, path: str, options: str = "") -> dict[str, Any]:
    """Advanced file operations.

    Operations:
    - find_duplicates: find duplicate files by content hash
    - bulk_rename: rename files with pattern (options: 'pattern replacement')
    - tree: directory tree visualization (options: max depth, default 3)
    - disk_usage: directory size analysis
    - find_large: find largest files (options: count, default 10)
    - compare_dirs: compare two directories (options: second directory path)
    """
    operation = operation.lower().strip()
    target = Path(path).expanduser().resolve()

    if not target.exists():
        return {"success": False, "error": f"Path not found: {path}"}

    if operation == "find_duplicates":
        return _find_duplicates(target)
    elif operation == "bulk_rename":
        return _bulk_rename(target, options)
    elif operation == "tree":
        return _tree(target, options)
    elif operation == "disk_usage":
        return _disk_usage(target)
    elif operation == "find_large":
        return _find_large(target, options)
    elif operation == "compare_dirs":
        return _compare_dirs(target, options)
    else:
        return {"success": False, "error": f"Unknown operation: '{operation}'. Available: find_duplicates, bulk_rename, tree, disk_usage, find_large, compare_dirs"}


def _find_duplicates(path: Path) -> dict[str, Any]:
    """Find duplicate files by SHA256 hash."""
    if not path.is_dir():
        return {"success": False, "error": "find_duplicates requires a directory"}

    hashes: dict[str, list[str]] = {}
    file_count = 0

    for f in path.rglob("*"):
        if not f.is_file() or f.stat().st_size == 0:
            continue
        if any(p in str(f) for p in ("__pycache__", "node_modules", ".git", ".venv")):
            continue
        file_count += 1
        if file_count > 5000:
            break

        try:
            h = hashlib.sha256()
            with open(f, "rb") as fh:
                for chunk in iter(lambda: fh.read(8192), b""):
                    h.update(chunk)
            digest = h.hexdigest()
            rel = str(f.relative_to(path))
            if digest not in hashes:
                hashes[digest] = []
            hashes[digest].append(rel)
        except (PermissionError, OSError):
            continue

    duplicates = {k: v for k, v in hashes.items() if len(v) > 1}

    if not duplicates:
        return {"success": True, "result": f"No duplicates found (scanned {file_count} files)"}

    results = [f"Found {len(duplicates)} sets of duplicates:"]
    for i, (_, files) in enumerate(duplicates.items()):
        if i >= 20:
            results.append(f"  ... and {len(duplicates) - 20} more sets")
            break
        results.append(f"\n  Set {i+1} ({len(files)} copies):")
        for f in files[:5]:
            results.append(f"    {f}")

    return {"success": True, "result": "\n".join(results)}


def _bulk_rename(path: Path, options: str) -> dict[str, Any]:
    """Rename files matching a pattern. Options: 'search_pattern replacement'."""
    if not options.strip():
        return {"success": False, "error": "bulk_rename requires options: 'search_pattern replacement'\nExample: options='old_prefix new_prefix'"}

    parts = options.strip().split(maxsplit=1)
    if len(parts) < 2:
        return {"success": False, "error": "Need both search pattern and replacement. Example: 'old_ new_'"}

    search, replacement = parts[0], parts[1]

    # Preview mode - show what would be renamed
    target_dir = path if path.is_dir() else path.parent
    renames = []

    for f in sorted(target_dir.iterdir()):
        if not f.is_file():
            continue
        new_name = re.sub(search, replacement, f.name)
        if new_name != f.name:
            renames.append((f, f.parent / new_name))

    if not renames:
        return {"success": True, "result": f"No files match pattern '{search}' in {target_dir}"}

    # Execute renames
    renamed = []
    errors = []
    for old, new in renames:
        try:
            old.rename(new)
            renamed.append(f"  {old.name} → {new.name}")
        except Exception as e:
            errors.append(f"  {old.name}: {e}")

    result = f"Renamed {len(renamed)} files:\n" + "\n".join(renamed[:30])
    if errors:
        result += f"\n\nErrors ({len(errors)}):\n" + "\n".join(errors[:10])

    return {"success": len(errors) == 0, "result": result}


def _tree(path: Path, options: str = "") -> dict[str, Any]:
    """Directory tree visualization."""
    max_depth = 3
    if options.strip().isdigit():
        max_depth = int(options.strip())

    lines = [str(path.name) + "/"]
    _build_tree(path, "", max_depth, 0, lines)

    if len(lines) > 100:
        lines = lines[:100]
        lines.append("... (truncated)")

    return {"success": True, "result": "\n".join(lines)}


def _build_tree(path: Path, prefix: str, max_depth: int, depth: int, lines: list):
    """Recursively build tree lines."""
    if depth >= max_depth:
        return

    try:
        items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except PermissionError:
        return

    # Filter hidden and common ignore dirs
    items = [i for i in items if not i.name.startswith(".") and i.name not in ("node_modules", "__pycache__", ".git", ".venv", "vendor")]

    for i, item in enumerate(items):
        if len(lines) > 100:
            return
        is_last = i == len(items) - 1
        connector = "└── " if is_last else "├── "
        suffix = "/" if item.is_dir() else ""
        lines.append(f"{prefix}{connector}{item.name}{suffix}")

        if item.is_dir():
            extension = "    " if is_last else "│   "
            _build_tree(item, prefix + extension, max_depth, depth + 1, lines)


def _disk_usage(path: Path) -> dict[str, Any]:
    """Analyze directory size."""
    if not path.is_dir():
        size = path.stat().st_size
        return {"success": True, "result": f"{path.name}: {_human_size(size)}"}

    dir_sizes: dict[str, int] = {}
    total = 0

    for item in path.iterdir():
        if item.name in (".git", "node_modules", "__pycache__", ".venv"):
            continue
        try:
            if item.is_file():
                total += item.stat().st_size
            elif item.is_dir():
                size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                dir_sizes[item.name] = size
                total += size
        except (PermissionError, OSError):
            continue

    # Sort by size
    sorted_dirs = sorted(dir_sizes.items(), key=lambda x: x[1], reverse=True)

    lines = [f"Total: {_human_size(total)}", ""]
    for name, size in sorted_dirs[:20]:
        pct = (size / total * 100) if total > 0 else 0
        bar = "█" * int(pct / 5)
        lines.append(f"  {_human_size(size):>10}  {pct:5.1f}%  {bar}  {name}/")

    return {"success": True, "result": "\n".join(lines)}


def _find_large(path: Path, options: str = "") -> dict[str, Any]:
    """Find largest files."""
    count = 10
    if options.strip().isdigit():
        count = int(options.strip())

    files_with_size = []
    for f in path.rglob("*"):
        if not f.is_file():
            continue
        if any(p in str(f) for p in (".git", "node_modules", "__pycache__", ".venv")):
            continue
        try:
            files_with_size.append((f, f.stat().st_size))
        except (PermissionError, OSError):
            continue

    files_with_size.sort(key=lambda x: x[1], reverse=True)
    top = files_with_size[:count]

    if not top:
        return {"success": True, "result": "No files found"}

    lines = [f"Top {len(top)} largest files:"]
    for f, size in top:
        rel = str(f.relative_to(path)) if f.is_relative_to(path) else str(f)
        lines.append(f"  {_human_size(size):>10}  {rel}")

    return {"success": True, "result": "\n".join(lines)}


def _compare_dirs(dir1: Path, options: str) -> dict[str, Any]:
    """Compare two directories."""
    if not options.strip():
        return {"success": False, "error": "compare_dirs requires second directory in options"}

    dir2 = Path(options.strip()).expanduser().resolve()
    if not dir2.exists():
        return {"success": False, "error": f"Second directory not found: {options}"}
    if not dir1.is_dir() or not dir2.is_dir():
        return {"success": False, "error": "Both paths must be directories"}

    files1 = {str(f.relative_to(dir1)) for f in dir1.rglob("*") if f.is_file()}
    files2 = {str(f.relative_to(dir2)) for f in dir2.rglob("*") if f.is_file()}

    only_in_1 = files1 - files2
    only_in_2 = files2 - files1
    common = files1 & files2

    results = [f"Comparing: {dir1.name}/ vs {dir2.name}/", f"  Common files: {len(common)}", f"  Only in {dir1.name}: {len(only_in_1)}", f"  Only in {dir2.name}: {len(only_in_2)}"]

    if only_in_1:
        results.append(f"\nOnly in {dir1.name}:")
        for f in sorted(only_in_1)[:15]:
            results.append(f"  + {f}")
    if only_in_2:
        results.append(f"\nOnly in {dir2.name}:")
        for f in sorted(only_in_2)[:15]:
            results.append(f"  + {f}")

    return {"success": True, "result": "\n".join(results)}


def _human_size(size: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"
