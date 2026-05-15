"""
assistant_tools.py – Personal assistant features for file organization,
system maintenance, and productivity automation.

SAFETY RULES:
- NEVER move files inside project directories (detected by .git, package.json, etc.)
- NEVER move system files or hidden files
- Always preview changes before executing
- Support undo via a move log
"""
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any


# Project markers — if ANY of these exist in a directory, it's a project root
PROJECT_MARKERS = {
    ".git", "package.json", "composer.json", "Cargo.toml", "go.mod",
    "pyproject.toml", "setup.py", "Makefile", "CMakeLists.txt",
    "pubspec.yaml", "build.gradle", "pom.xml", ".sln", ".csproj",
    "Gemfile", "mix.exs", "deno.json", "bun.lockb",
    "artisan",  # Laravel
    "manage.py",  # Django
}

# Directories that should NEVER be touched
PROTECTED_DIRS = {
    "Windows", "Program Files", "Program Files (x86)", "ProgramData",
    "System Volume Information", "$Recycle.Bin", "Recovery",
    ".git", "node_modules", "vendor", "__pycache__", ".venv", "venv",
    ".idea", ".vscode", ".vs", "dist", "build", "target", "out",
}

# File extension → category mapping for organization
FILE_CATEGORIES = {
    # Documents
    ".pdf": "Documents", ".doc": "Documents", ".docx": "Documents",
    ".xls": "Documents", ".xlsx": "Documents", ".ppt": "Documents",
    ".pptx": "Documents", ".odt": "Documents", ".ods": "Documents",
    ".txt": "Documents", ".rtf": "Documents", ".csv": "Documents",
    # Images
    ".jpg": "Images", ".jpeg": "Images", ".png": "Images",
    ".gif": "Images", ".bmp": "Images", ".svg": "Images",
    ".webp": "Images", ".ico": "Images", ".tiff": "Images",
    ".raw": "Images", ".heic": "Images",
    # Videos
    ".mp4": "Videos", ".mkv": "Videos", ".avi": "Videos",
    ".mov": "Videos", ".wmv": "Videos", ".flv": "Videos",
    ".webm": "Videos", ".m4v": "Videos",
    # Music/Audio
    ".mp3": "Music", ".flac": "Music", ".wav": "Music",
    ".aac": "Music", ".ogg": "Music", ".wma": "Music",
    ".m4a": "Music", ".opus": "Music",
    # Archives
    ".zip": "Archives", ".rar": "Archives", ".7z": "Archives",
    ".tar": "Archives", ".gz": "Archives", ".bz2": "Archives",
    ".xz": "Archives",
    # Installers/Executables
    ".exe": "Installers", ".msi": "Installers", ".dmg": "Installers",
    ".deb": "Installers", ".rpm": "Installers", ".appimage": "Installers",
    # Code (don't move these by default — they might be project files)
    ".py": "Code", ".js": "Code", ".ts": "Code", ".jsx": "Code",
    ".tsx": "Code", ".html": "Code", ".css": "Code", ".php": "Code",
    ".java": "Code", ".c": "Code", ".cpp": "Code", ".rs": "Code",
    ".go": "Code", ".rb": "Code", ".swift": "Code", ".kt": "Code",
    # Design
    ".psd": "Design", ".ai": "Design", ".sketch": "Design",
    ".fig": "Design", ".xd": "Design",
    # 3D/CAD
    ".blend": "3D", ".obj": "3D", ".fbx": "3D", ".stl": "3D",
    ".glb": "3D", ".gltf": "3D",
    # Fonts
    ".ttf": "Fonts", ".otf": "Fonts", ".woff": "Fonts", ".woff2": "Fonts",
    # Torrents
    ".torrent": "Torrents",
    # Ebooks
    ".epub": "Ebooks", ".mobi": "Ebooks", ".azw3": "Ebooks",
}

# Move log for undo support
_MOVE_LOG_FILE = Path.home() / ".mini_ai" / "file_moves.json"


def _is_inside_project(file_path: Path) -> bool:
    """Check if a file is inside a project directory (should not be moved)."""
    # Walk up the directory tree looking for project markers
    current = file_path.parent
    for _ in range(10):  # Max 10 levels up
        if not current or current == current.parent:
            break
        # Check for project markers in this directory
        for marker in PROJECT_MARKERS:
            if (current / marker).exists():
                return True
        current = current.parent
    return False


def _is_protected(path: Path) -> bool:
    """Check if a path is in a protected directory."""
    parts = set(path.parts)
    return bool(parts & PROTECTED_DIRS)


def _log_moves(moves: list[dict]) -> None:
    """Log file moves for undo support."""
    _MOVE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Load existing log
    existing = []
    if _MOVE_LOG_FILE.exists():
        try:
            existing = json.loads(_MOVE_LOG_FILE.read_text())
        except Exception:
            existing = []
    
    # Append new moves with timestamp
    entry = {
        "timestamp": datetime.now().isoformat(),
        "moves": moves,
    }
    existing.append(entry)
    
    # Keep only last 50 operations
    if len(existing) > 50:
        existing = existing[-50:]
    
    _MOVE_LOG_FILE.write_text(json.dumps(existing, indent=2))


def organize_files(path: str, mode: str = "preview", categories: str = "") -> dict[str, Any]:
    """Organize files in a directory by type/extension.
    
    SAFE: Never moves files inside project directories.
    
    Args:
        path: Directory to organize (e.g. Downloads, Desktop)
        mode: "preview" (show plan) or "execute" (actually move files)
        categories: Comma-separated categories to organize (empty = all)
                   Options: Documents, Images, Videos, Music, Archives, Installers, Code, Design
    
    Returns:
        Plan or execution result.
    """
    target = Path(path).expanduser().resolve()
    
    if not target.exists() or not target.is_dir():
        return {"success": False, "error": f"Directory not found: {path}"}
    
    # Safety: don't organize inside project directories
    if _is_inside_project(target / "dummy"):
        return {"success": False, "error": f"Cannot organize inside a project directory ({target}). Only organize loose file directories like Downloads or Desktop."}
    
    # Filter categories if specified
    allowed_categories = set()
    if categories.strip():
        allowed_categories = {c.strip().title() for c in categories.split(",")}
    
    # Scan files (only top-level, not recursive into subdirs)
    plan: dict[str, list[tuple[str, str]]] = {}  # category → [(src_name, dst_path)]
    skipped = []
    
    for item in target.iterdir():
        if not item.is_file():
            continue
        if item.name.startswith("."):
            continue  # Skip hidden files
        
        ext = item.suffix.lower()
        category = FILE_CATEGORIES.get(ext)
        
        if not category:
            skipped.append(item.name)
            continue
        
        if allowed_categories and category not in allowed_categories:
            continue
        
        # Safety: don't move files that are inside a project
        if _is_inside_project(item):
            skipped.append(f"{item.name} (inside project)")
            continue
        
        # Don't move code files by default (too risky)
        if category == "Code" and "Code" not in allowed_categories:
            skipped.append(f"{item.name} (code file, use categories='Code' to include)")
            continue
        
        dst_dir = target / category
        dst_path = dst_dir / item.name
        
        if category not in plan:
            plan[category] = []
        plan[category].append((item.name, str(dst_path)))
    
    if not plan:
        return {"success": True, "result": f"No files to organize in {target.name}.\nSkipped: {len(skipped)} files (hidden, code, or unknown type)"}
    
    # Preview mode
    if mode == "preview":
        lines = [f"Organization plan for {target.name}/:", ""]
        total = 0
        for cat, files in sorted(plan.items()):
            lines.append(f"  📁 {cat}/ ({len(files)} files)")
            for name, _ in files[:5]:
                lines.append(f"      {name}")
            if len(files) > 5:
                lines.append(f"      ... and {len(files) - 5} more")
            total += len(files)
        lines.append(f"\n  Total: {total} files to organize")
        if skipped:
            lines.append(f"  Skipped: {len(skipped)} files")
        lines.append(f"\n  Run with mode='execute' to apply.")
        return {"success": True, "result": "\n".join(lines)}
    
    # Execute mode
    moves_log = []
    moved = 0
    errors = []
    
    for cat, files in plan.items():
        dst_dir = target / cat
        dst_dir.mkdir(exist_ok=True)
        
        for name, dst_path in files:
            src = target / name
            dst = Path(dst_path)
            
            # Handle name conflicts
            if dst.exists():
                stem = dst.stem
                suffix = dst.suffix
                counter = 1
                while dst.exists():
                    dst = dst.parent / f"{stem}_{counter}{suffix}"
                    counter += 1
            
            try:
                shutil.move(str(src), str(dst))
                moves_log.append({"src": str(src), "dst": str(dst)})
                moved += 1
            except Exception as e:
                errors.append(f"{name}: {e}")
    
    # Log for undo
    if moves_log:
        _log_moves(moves_log)
    
    result = f"Organized {moved} files into {len(plan)} categories in {target.name}/."
    if errors:
        result += f"\n{len(errors)} errors: " + "; ".join(errors[:3])
    
    return {"success": len(errors) == 0, "result": result}


def undo_organize() -> dict[str, Any]:
    """Undo the last file organization operation."""
    if not _MOVE_LOG_FILE.exists():
        return {"success": False, "error": "No move history found. Nothing to undo."}
    
    try:
        log = json.loads(_MOVE_LOG_FILE.read_text())
    except Exception:
        return {"success": False, "error": "Could not read move history."}
    
    if not log:
        return {"success": False, "error": "Move history is empty."}
    
    # Get the last operation
    last_op = log.pop()
    moves = last_op.get("moves", [])
    
    if not moves:
        return {"success": False, "error": "Last operation has no moves to undo."}
    
    undone = 0
    errors = []
    
    for move in reversed(moves):
        src = Path(move["dst"])  # Current location
        dst = Path(move["src"])  # Original location
        
        if not src.exists():
            errors.append(f"File not found: {src.name}")
            continue
        
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            undone += 1
        except Exception as e:
            errors.append(f"{src.name}: {e}")
    
    # Save updated log
    _MOVE_LOG_FILE.write_text(json.dumps(log, indent=2))
    
    # Clean up empty category directories
    timestamp = last_op.get("timestamp", "unknown")
    result = f"Undone {undone}/{len(moves)} moves from {timestamp}."
    if errors:
        result += f"\n{len(errors)} errors: " + "; ".join(errors[:3])
    
    return {"success": len(errors) == 0, "result": result}


def smart_cleanup(path: str, mode: str = "preview") -> dict[str, Any]:
    """Smart cleanup: find and optionally remove temp files, empty dirs, duplicates.
    
    Args:
        path: Directory to clean
        mode: "preview" (show what would be cleaned) or "execute" (actually clean)
    """
    target = Path(path).expanduser().resolve()
    
    if not target.exists() or not target.is_dir():
        return {"success": False, "error": f"Directory not found: {path}"}
    
    # Safety check
    if _is_inside_project(target / "dummy"):
        return {"success": False, "error": "Cannot clean inside a project directory. Use project-specific tools instead."}
    
    findings = {
        "empty_dirs": [],
        "temp_files": [],
        "thumbs_db": [],
        "ds_store": [],
        "zone_identifier": [],
    }
    
    temp_patterns = {".tmp", ".temp", ".bak", ".old", ".swp", ".swo"}
    
    for item in target.rglob("*"):
        if any(p in str(item) for p in PROTECTED_DIRS):
            continue
        
        if item.is_dir():
            try:
                if not any(item.iterdir()):
                    findings["empty_dirs"].append(str(item.relative_to(target)))
            except PermissionError:
                pass
        elif item.is_file():
            name_lower = item.name.lower()
            if item.suffix.lower() in temp_patterns:
                findings["temp_files"].append(str(item.relative_to(target)))
            elif name_lower == "thumbs.db":
                findings["thumbs_db"].append(str(item.relative_to(target)))
            elif name_lower == ".ds_store":
                findings["ds_store"].append(str(item.relative_to(target)))
            elif ":zone.identifier" in name_lower or name_lower.endswith(".identifier"):
                findings["zone_identifier"].append(str(item.relative_to(target)))
    
    total = sum(len(v) for v in findings.values())
    
    if total == 0:
        return {"success": True, "result": f"Directory is clean! No junk files found in {target.name}/"}
    
    if mode == "preview":
        lines = [f"Cleanup plan for {target.name}/ ({total} items):"]
        for category, items in findings.items():
            if items:
                label = category.replace("_", " ").title()
                lines.append(f"\n  {label} ({len(items)}):")
                for item in items[:5]:
                    lines.append(f"    {item}")
                if len(items) > 5:
                    lines.append(f"    ... and {len(items) - 5} more")
        lines.append(f"\n  Run with mode='execute' to clean up.")
        return {"success": True, "result": "\n".join(lines)}
    
    # Execute cleanup
    removed = 0
    errors = []
    
    for category, items in findings.items():
        for rel_path in items:
            full_path = target / rel_path
            try:
                if full_path.is_dir():
                    full_path.rmdir()
                elif full_path.is_file():
                    full_path.unlink()
                removed += 1
            except Exception as e:
                errors.append(f"{rel_path}: {e}")
    
    result = f"Cleaned {removed}/{total} items from {target.name}/."
    if errors:
        result += f"\n{len(errors)} errors."
    
    return {"success": True, "result": result}


def file_summary(path: str) -> dict[str, Any]:
    """Get a summary of files in a directory (counts by type, sizes, dates).
    
    Useful for understanding what's in a directory before organizing.
    """
    target = Path(path).expanduser().resolve()
    
    if not target.exists() or not target.is_dir():
        return {"success": False, "error": f"Directory not found: {path}"}
    
    categories: dict[str, dict] = {}
    total_size = 0
    total_files = 0
    oldest = None
    newest = None
    
    for item in target.iterdir():
        if not item.is_file() or item.name.startswith("."):
            continue
        
        total_files += 1
        size = item.stat().st_size
        total_size += size
        mtime = item.stat().st_mtime
        
        if oldest is None or mtime < oldest:
            oldest = mtime
        if newest is None or mtime > newest:
            newest = mtime
        
        ext = item.suffix.lower()
        cat = FILE_CATEGORIES.get(ext, "Other")
        
        if cat not in categories:
            categories[cat] = {"count": 0, "size": 0}
        categories[cat]["count"] += 1
        categories[cat]["size"] += size
    
    # Format output
    lines = [f"Summary of {target.name}/ ({total_files} files, {_human_size(total_size)}):"]
    
    if oldest:
        lines.append(f"  Oldest: {datetime.fromtimestamp(oldest).strftime('%Y-%m-%d')}")
    if newest:
        lines.append(f"  Newest: {datetime.fromtimestamp(newest).strftime('%Y-%m-%d')}")
    
    lines.append("")
    for cat, info in sorted(categories.items(), key=lambda x: x[1]["size"], reverse=True):
        lines.append(f"  {cat:12s}  {info['count']:4d} files  {_human_size(info['size']):>10s}")
    
    # Count subdirectories
    subdirs = [d for d in target.iterdir() if d.is_dir() and not d.name.startswith(".")]
    if subdirs:
        lines.append(f"\n  Subdirectories: {len(subdirs)}")
        for d in subdirs[:10]:
            lines.append(f"    📁 {d.name}/")
    
    return {"success": True, "result": "\n".join(lines)}


def schedule_reminder(message: str, minutes: int = 0, time_str: str = "") -> dict[str, Any]:
    """Set a reminder (writes to a reminders file for the agent to check).
    
    Args:
        message: Reminder text
        minutes: Minutes from now (0 = immediate note)
        time_str: Specific time like "3:00 PM" or "15:00"
    """
    reminders_file = Path.home() / ".mini_ai" / "reminders.json"
    reminders_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Load existing
    reminders = []
    if reminders_file.exists():
        try:
            reminders = json.loads(reminders_file.read_text())
        except Exception:
            reminders = []
    
    # Calculate trigger time
    now = datetime.now()
    if minutes > 0:
        trigger = now.timestamp() + (minutes * 60)
        trigger_str = datetime.fromtimestamp(trigger).strftime("%I:%M %p")
    elif time_str:
        trigger_str = time_str
        trigger = now.timestamp()  # Simplified — just store the string
    else:
        trigger_str = "Now"
        trigger = now.timestamp()
    
    reminder = {
        "message": message,
        "created": now.isoformat(),
        "trigger_time": trigger_str,
        "trigger_ts": trigger,
        "done": False,
    }
    reminders.append(reminder)
    reminders_file.write_text(json.dumps(reminders, indent=2))
    
    return {"success": True, "result": f"Reminder set: '{message}' at {trigger_str}"}


def check_reminders() -> dict[str, Any]:
    """Check for pending reminders."""
    reminders_file = Path.home() / ".mini_ai" / "reminders.json"
    
    if not reminders_file.exists():
        return {"success": True, "result": "No reminders set."}
    
    try:
        reminders = json.loads(reminders_file.read_text())
    except Exception:
        return {"success": True, "result": "No reminders."}
    
    pending = [r for r in reminders if not r.get("done")]
    
    if not pending:
        return {"success": True, "result": "No pending reminders."}
    
    now = time.time()
    due = []
    upcoming = []
    
    for r in pending:
        if r.get("trigger_ts", 0) <= now:
            due.append(r)
        else:
            upcoming.append(r)
    
    lines = []
    if due:
        lines.append(f"🔔 Due reminders ({len(due)}):")
        for r in due:
            lines.append(f"  • {r['message']} (set at {r.get('trigger_time', '?')})")
    if upcoming:
        lines.append(f"\n⏰ Upcoming ({len(upcoming)}):")
        for r in upcoming:
            lines.append(f"  • {r['message']} at {r.get('trigger_time', '?')}")
    
    return {"success": True, "result": "\n".join(lines)}


def quick_note(content: str, title: str = "") -> dict[str, Any]:
    """Save a quick note to the notes file.
    
    Args:
        content: Note content
        title: Optional title/tag
    """
    notes_dir = Path.home() / ".mini_ai" / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    
    # Use date-based filename
    today = datetime.now().strftime("%Y-%m-%d")
    notes_file = notes_dir / f"{today}.md"
    
    timestamp = datetime.now().strftime("%H:%M")
    header = f"## {title}" if title else f"## Note"
    entry = f"\n{header} ({timestamp})\n{content}\n"
    
    # Append to today's notes
    with open(notes_file, "a", encoding="utf-8") as f:
        f.write(entry)
    
    return {"success": True, "result": f"Note saved to {notes_file.name}"}


def list_notes(days: int = 7) -> dict[str, Any]:
    """List recent notes."""
    notes_dir = Path.home() / ".mini_ai" / "notes"
    
    if not notes_dir.exists():
        return {"success": True, "result": "No notes yet."}
    
    files = sorted(notes_dir.glob("*.md"), reverse=True)[:days]
    
    if not files:
        return {"success": True, "result": "No notes found."}
    
    lines = [f"Recent notes ({len(files)} days):"]
    for f in files:
        content = f.read_text(encoding="utf-8")
        preview = content[:200].replace("\n", " ").strip()
        lines.append(f"\n  📝 {f.stem}: {preview}...")
    
    return {"success": True, "result": "\n".join(lines)}


def system_health() -> dict[str, Any]:
    """Quick system health check: disk space, memory, uptime."""
    import platform
    
    lines = [f"System: {platform.system()} {platform.release()}"]
    
    # Disk space
    try:
        if os.name == "nt":
            import ctypes
            free_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                "C:\\", None, None, ctypes.pointer(free_bytes)
            )
            free_gb = free_bytes.value / (1024**3)
            lines.append(f"  Disk (C:): {free_gb:.1f} GB free")
        else:
            stat = os.statvfs("/")
            free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
            lines.append(f"  Disk: {free_gb:.1f} GB free")
    except Exception:
        pass
    
    # Memory (try psutil, fallback to basic)
    try:
        import psutil
        mem = psutil.virtual_memory()
        lines.append(f"  RAM: {mem.available / (1024**3):.1f} GB free / {mem.total / (1024**3):.1f} GB total ({mem.percent}% used)")
        cpu = psutil.cpu_percent(interval=0.1)
        lines.append(f"  CPU: {cpu}% used")
    except ImportError:
        pass
    
    # Python version
    import sys
    lines.append(f"  Python: {sys.version.split()[0]}")
    
    # Disk space warning
    try:
        if free_gb < 5:
            lines.append("\n  ⚠️ LOW DISK SPACE! Consider cleaning up.")
    except Exception:
        pass
    
    return {"success": True, "result": "\n".join(lines)}


def _human_size(size: int) -> str:
    """Convert bytes to human-readable size."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"
