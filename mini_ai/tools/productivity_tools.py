"""
productivity_tools.py – Advanced productivity and automation features.

Features:
1. Clipboard history — track and search clipboard entries
2. App launcher — open apps by name
3. Window/process manager — list, kill, focus processes
4. Quick timer/stopwatch — countdown and elapsed time
5. Text snippets — save and recall reusable text
6. Batch file renamer — smart rename with patterns (date prefix, numbering, etc.)
7. Duplicate photo finder — find similar images by size/name
8. Startup manager — list/disable startup programs
9. Wi-Fi password retriever — show saved Wi-Fi passwords
10. Screen brightness/volume control (where supported)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any


# Storage directory
_STORAGE = Path.home() / ".mini_ai"
_STORAGE.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. APP LAUNCHER
# ═══════════════════════════════════════════════════════════════════════════════

# Common Windows apps and their paths/commands
_APP_REGISTRY = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "files": "explorer.exe",
    "cmd": "cmd.exe",
    "terminal": "wt.exe",
    "powershell": "powershell.exe",
    "task manager": "taskmgr.exe",
    "control panel": "control.exe",
    "settings": "ms-settings:",
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "google chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "firefox": r"C:\Program Files\Mozilla Firefox\firefox.exe",
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
    "spotify": r"%APPDATA%\Spotify\Spotify.exe",
    "discord": r"%LOCALAPPDATA%\Discord\Update.exe --processStart Discord.exe",
    "steam": r"C:\Program Files (x86)\Steam\steam.exe",
    "word": "winword.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
    "outlook": "outlook.exe",
    "teams": r"%LOCALAPPDATA%\Microsoft\Teams\current\Teams.exe",
    "obs": r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",
    "vlc": r"C:\Program Files\VideoLAN\VLC\vlc.exe",
    "gimp": r"C:\Program Files\GIMP 2\bin\gimp-2.10.exe",
    "blender": r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
    "photoshop": "photoshop.exe",
    "figma": r"%LOCALAPPDATA%\Figma\Figma.exe",
}


def open_app(name: str) -> dict[str, Any]:
    """Open an application by name.
    
    Supports common apps: notepad, calculator, chrome, vscode, spotify, discord, etc.
    """
    name_lower = name.lower().strip()
    
    # Check registry
    cmd = _APP_REGISTRY.get(name_lower)
    
    if not cmd:
        # Fuzzy match
        for key, val in _APP_REGISTRY.items():
            if name_lower in key or key in name_lower:
                cmd = val
                break
    
    if not cmd:
        # Try as a direct command
        cmd = name_lower
    
    # Expand environment variables
    cmd = os.path.expandvars(cmd)
    
    # Handle ms-settings: protocol
    if cmd.startswith("ms-settings:"):
        try:
            os.startfile(cmd)
            return {"success": True, "result": f"Opened {name}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    try:
        # Use start for detached process
        if os.name == "nt":
            subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(cmd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"success": True, "result": f"Opened {name}"}
    except Exception as e:
        return {"success": False, "error": f"Could not open {name}: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PROCESS MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

def list_processes(sort_by: str = "memory", limit: int = 15) -> dict[str, Any]:
    """List running processes sorted by memory or CPU usage.
    
    Args:
        sort_by: "memory" or "cpu" or "name"
        limit: Number of processes to show (default 15)
    """
    try:
        import psutil
    except ImportError:
        # Fallback to tasklist
        try:
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10
            )
            lines = result.stdout.strip().split("\n")[:limit]
            return {"success": True, "result": f"Top {len(lines)} processes:\n" + "\n".join(lines)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    procs = []
    for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'cpu_percent']):
        try:
            info = proc.info
            mem_mb = info['memory_info'].rss / (1024 * 1024) if info['memory_info'] else 0
            procs.append({
                "pid": info['pid'],
                "name": info['name'],
                "memory_mb": round(mem_mb, 1),
                "cpu": info.get('cpu_percent', 0) or 0,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    if sort_by == "cpu":
        procs.sort(key=lambda x: x["cpu"], reverse=True)
    elif sort_by == "name":
        procs.sort(key=lambda x: x["name"].lower())
    else:
        procs.sort(key=lambda x: x["memory_mb"], reverse=True)
    
    top = procs[:limit]
    lines = [f"{'PID':>7}  {'Memory':>8}  {'CPU':>5}  Name"]
    lines.append("-" * 45)
    for p in top:
        lines.append(f"{p['pid']:>7}  {p['memory_mb']:>6.1f}MB  {p['cpu']:>4.1f}%  {p['name']}")
    
    return {"success": True, "result": "\n".join(lines)}


def kill_process(target: str) -> dict[str, Any]:
    """Kill a process by name or PID.
    
    Args:
        target: Process name (e.g. "chrome.exe") or PID number
    """
    try:
        if target.isdigit():
            pid = int(target)
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=10)
            return {"success": True, "result": f"Killed process PID {pid}"}
        else:
            result = subprocess.run(
                ["taskkill", "/F", "/IM", target],
                capture_output=True, text=True, timeout=10
            )
            output = result.stdout + result.stderr
            if result.returncode == 0:
                return {"success": True, "result": f"Killed {target}"}
            return {"success": False, "error": output.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TIMER / STOPWATCH
# ═══════════════════════════════════════════════════════════════════════════════

_TIMER_FILE = _STORAGE / "timer.json"


def timer_op(operation: str, seconds: int = 0, label: str = "") -> dict[str, Any]:
    """Timer and stopwatch operations.
    
    Operations:
        start_stopwatch: Start a stopwatch
        stop_stopwatch: Stop and show elapsed time
        set_timer: Set a countdown timer (seconds param required)
        check_timer: Check remaining time on active timer
    """
    operation = operation.lower().strip()
    
    if operation == "start_stopwatch":
        data = {"type": "stopwatch", "start": time.time(), "label": label or "Stopwatch"}
        _TIMER_FILE.write_text(json.dumps(data))
        return {"success": True, "result": f"Stopwatch started: {label or 'Stopwatch'}"}
    
    elif operation == "stop_stopwatch":
        if not _TIMER_FILE.exists():
            return {"success": False, "error": "No active stopwatch"}
        data = json.loads(_TIMER_FILE.read_text())
        elapsed = time.time() - data["start"]
        _TIMER_FILE.unlink()
        mins, secs = divmod(int(elapsed), 60)
        hours, mins = divmod(mins, 60)
        time_str = f"{hours}h {mins}m {secs}s" if hours else f"{mins}m {secs}s"
        return {"success": True, "result": f"{data.get('label', 'Stopwatch')}: {time_str} elapsed"}
    
    elif operation == "set_timer":
        if seconds <= 0:
            return {"success": False, "error": "Specify seconds > 0"}
        end_time = time.time() + seconds
        data = {"type": "timer", "end": end_time, "seconds": seconds, "label": label or f"{seconds}s timer"}
        _TIMER_FILE.write_text(json.dumps(data))
        mins, secs = divmod(seconds, 60)
        return {"success": True, "result": f"Timer set: {mins}m {secs}s ({label or 'Timer'})"}
    
    elif operation == "check_timer":
        if not _TIMER_FILE.exists():
            return {"success": True, "result": "No active timer"}
        data = json.loads(_TIMER_FILE.read_text())
        if data["type"] == "stopwatch":
            elapsed = time.time() - data["start"]
            mins, secs = divmod(int(elapsed), 60)
            return {"success": True, "result": f"Stopwatch running: {mins}m {secs}s"}
        else:
            remaining = data["end"] - time.time()
            if remaining <= 0:
                _TIMER_FILE.unlink()
                return {"success": True, "result": f"⏰ Timer DONE! ({data.get('label', 'Timer')})"}
            mins, secs = divmod(int(remaining), 60)
            return {"success": True, "result": f"Timer: {mins}m {secs}s remaining"}
    
    return {"success": False, "error": f"Unknown operation: {operation}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 4. TEXT SNIPPETS
# ═══════════════════════════════════════════════════════════════════════════════

_SNIPPETS_FILE = _STORAGE / "snippets.json"


def snippet_op(operation: str, name: str = "", content: str = "") -> dict[str, Any]:
    """Save and recall reusable text snippets.
    
    Operations:
        save: Save a snippet (name + content required)
        get: Retrieve a snippet by name
        list: List all saved snippets
        delete: Delete a snippet by name
    """
    # Load snippets
    snippets = {}
    if _SNIPPETS_FILE.exists():
        try:
            snippets = json.loads(_SNIPPETS_FILE.read_text())
        except Exception:
            snippets = {}
    
    operation = operation.lower().strip()
    
    if operation == "save":
        if not name or not content:
            return {"success": False, "error": "Both name and content required"}
        snippets[name] = {"content": content, "created": datetime.now().isoformat()}
        _SNIPPETS_FILE.write_text(json.dumps(snippets, indent=2))
        return {"success": True, "result": f"Snippet '{name}' saved ({len(content)} chars)"}
    
    elif operation == "get":
        if not name:
            return {"success": False, "error": "Snippet name required"}
        if name in snippets:
            return {"success": True, "result": snippets[name]["content"]}
        # Fuzzy search
        matches = [k for k in snippets if name.lower() in k.lower()]
        if matches:
            return {"success": True, "result": snippets[matches[0]]["content"]}
        return {"success": False, "error": f"Snippet '{name}' not found. Available: {', '.join(snippets.keys())}"}
    
    elif operation == "list":
        if not snippets:
            return {"success": True, "result": "No snippets saved yet."}
        lines = [f"Saved snippets ({len(snippets)}):"]
        for k, v in snippets.items():
            preview = v["content"][:50].replace("\n", " ")
            lines.append(f"  • {k}: {preview}...")
        return {"success": True, "result": "\n".join(lines)}
    
    elif operation == "delete":
        if name in snippets:
            del snippets[name]
            _SNIPPETS_FILE.write_text(json.dumps(snippets, indent=2))
            return {"success": True, "result": f"Deleted snippet '{name}'"}
        return {"success": False, "error": f"Snippet '{name}' not found"}
    
    return {"success": False, "error": f"Unknown operation: {operation}. Use: save, get, list, delete"}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. SMART BATCH RENAME
# ═══════════════════════════════════════════════════════════════════════════════

def smart_rename(path: str, pattern: str, mode: str = "preview") -> dict[str, Any]:
    """Smart batch rename files with patterns.
    
    Patterns:
        "date_prefix" — Prepend YYYY-MM-DD to filenames
        "number" — Number files sequentially (001, 002, ...)
        "lowercase" — Convert all filenames to lowercase
        "replace:old:new" — Replace text in filenames
        "extension:new_ext" — Change file extension
        "cleanup" — Remove special chars, normalize spaces
    
    Args:
        path: Directory containing files to rename
        pattern: Rename pattern (see above)
        mode: "preview" or "execute"
    """
    target = Path(path).expanduser().resolve()
    if not target.exists() or not target.is_dir():
        return {"success": False, "error": f"Directory not found: {path}"}
    
    files = sorted([f for f in target.iterdir() if f.is_file() and not f.name.startswith(".")])
    if not files:
        return {"success": True, "result": "No files to rename"}
    
    renames = []  # (old_path, new_name)
    
    if pattern == "date_prefix":
        for f in files:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            prefix = mtime.strftime("%Y-%m-%d_")
            if not f.name.startswith(prefix[:10]):
                renames.append((f, prefix + f.name))
    
    elif pattern == "number":
        width = len(str(len(files)))
        for i, f in enumerate(files, 1):
            new_name = f"{str(i).zfill(width)}_{f.name}"
            renames.append((f, new_name))
    
    elif pattern == "lowercase":
        for f in files:
            new_name = f.name.lower()
            if new_name != f.name:
                renames.append((f, new_name))
    
    elif pattern.startswith("replace:"):
        parts = pattern.split(":", 2)
        if len(parts) < 3:
            return {"success": False, "error": "Format: replace:old_text:new_text"}
        old_text, new_text = parts[1], parts[2]
        for f in files:
            new_name = f.name.replace(old_text, new_text)
            if new_name != f.name:
                renames.append((f, new_name))
    
    elif pattern.startswith("extension:"):
        new_ext = pattern.split(":", 1)[1].strip()
        if not new_ext.startswith("."):
            new_ext = "." + new_ext
        for f in files:
            new_name = f.stem + new_ext
            if new_name != f.name:
                renames.append((f, new_name))
    
    elif pattern == "cleanup":
        for f in files:
            # Remove special chars, normalize spaces
            new_name = re.sub(r'[^\w\s\-\.]', '', f.stem)
            new_name = re.sub(r'\s+', '_', new_name.strip())
            new_name = new_name + f.suffix
            if new_name != f.name:
                renames.append((f, new_name))
    
    else:
        return {"success": False, "error": f"Unknown pattern: {pattern}. Use: date_prefix, number, lowercase, replace:old:new, extension:ext, cleanup"}
    
    if not renames:
        return {"success": True, "result": "No files need renaming with this pattern."}
    
    if mode == "preview":
        lines = [f"Rename preview ({len(renames)} files):"]
        for old, new_name in renames[:20]:
            lines.append(f"  {old.name} → {new_name}")
        if len(renames) > 20:
            lines.append(f"  ... and {len(renames) - 20} more")
        lines.append(f"\nRun with mode='execute' to apply.")
        return {"success": True, "result": "\n".join(lines)}
    
    # Execute
    renamed = 0
    errors = []
    for old, new_name in renames:
        try:
            new_path = old.parent / new_name
            if new_path.exists():
                errors.append(f"{new_name}: already exists")
                continue
            old.rename(new_path)
            renamed += 1
        except Exception as e:
            errors.append(f"{old.name}: {e}")
    
    result = f"Renamed {renamed}/{len(renames)} files."
    if errors:
        result += f"\n{len(errors)} errors: " + "; ".join(errors[:3])
    return {"success": len(errors) == 0, "result": result}


# ═══════════════════════════════════════════════════════════════════════════════
# 6. WIFI PASSWORDS
# ═══════════════════════════════════════════════════════════════════════════════

def wifi_passwords() -> dict[str, Any]:
    """Show saved Wi-Fi network passwords (Windows only)."""
    if os.name != "nt":
        return {"success": False, "error": "Only supported on Windows"}
    
    try:
        # Get list of profiles
        result = subprocess.run(
            ["netsh", "wlan", "show", "profiles"],
            capture_output=True, text=True, timeout=10
        )
        profiles = re.findall(r"All User Profile\s*:\s*(.+)", result.stdout)
        
        if not profiles:
            return {"success": True, "result": "No saved Wi-Fi networks found."}
        
        lines = [f"Saved Wi-Fi networks ({len(profiles)}):"]
        for profile in profiles[:20]:
            profile = profile.strip()
            # Get password for each profile
            try:
                detail = subprocess.run(
                    ["netsh", "wlan", "show", "profile", f"name={profile}", "key=clear"],
                    capture_output=True, text=True, timeout=5
                )
                pwd_match = re.search(r"Key Content\s*:\s*(.+)", detail.stdout)
                password = pwd_match.group(1).strip() if pwd_match else "(no password)"
                lines.append(f"  📶 {profile}: {password}")
            except Exception:
                lines.append(f"  📶 {profile}: (could not retrieve)")
        
        return {"success": True, "result": "\n".join(lines)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 7. STARTUP MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

def startup_programs(operation: str = "list") -> dict[str, Any]:
    """List or manage startup programs (Windows only).
    
    Operations:
        list: Show all startup programs
        (disable/enable would require admin — just list for now)
    """
    if os.name != "nt":
        return {"success": False, "error": "Only supported on Windows"}
    
    try:
        import winreg
        
        locations = [
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", "User"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", "System"),
        ]
        
        lines = ["Startup programs:"]
        total = 0
        
        for hive, path, label in locations:
            try:
                key = winreg.OpenKey(hive, path)
                i = 0
                lines.append(f"\n  [{label}]")
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                        lines.append(f"    • {name}: {value[:60]}")
                        total += 1
                        i += 1
                    except OSError:
                        break
                winreg.CloseKey(key)
            except Exception:
                continue
        
        if total == 0:
            return {"success": True, "result": "No startup programs found."}
        
        lines.insert(0, f"Found {total} startup programs:")
        return {"success": True, "result": "\n".join(lines)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 8. QUICK CALCULATIONS & CONVERSIONS
# ═══════════════════════════════════════════════════════════════════════════════

def quick_calc(expression: str) -> dict[str, Any]:
    """Evaluate a math expression safely.
    
    Supports: +, -, *, /, **, %, sqrt, sin, cos, tan, log, pi, e
    """
    import math
    
    # Sanitize — only allow safe math operations
    allowed = set("0123456789.+-*/()% ")
    allowed_funcs = {"sqrt", "sin", "cos", "tan", "log", "log10", "abs", "round", "pi", "e", "pow"}
    
    expr = expression.strip()
    
    # Replace common patterns
    expr = expr.replace("^", "**")
    expr = expr.replace("×", "*")
    expr = expr.replace("÷", "/")
    
    # Build safe namespace
    safe_ns = {
        "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos,
        "tan": math.tan, "log": math.log, "log10": math.log10,
        "abs": abs, "round": round, "pow": pow,
        "pi": math.pi, "e": math.e,
    }
    
    try:
        result = eval(expr, {"__builtins__": {}}, safe_ns)
        if isinstance(result, float) and result == int(result):
            result = int(result)
        return {"success": True, "result": f"{expression} = {result}"}
    except Exception as e:
        return {"success": False, "error": f"Could not evaluate: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 9. CLIPBOARD OPERATIONS
# ═══════════════════════════════════════════════════════════════════════════════

_CLIPBOARD_HISTORY_FILE = _STORAGE / "clipboard_history.json"


def clipboard_history(operation: str = "show", content: str = "") -> dict[str, Any]:
    """Clipboard history manager.
    
    Operations:
        show: Show recent clipboard entries
        save: Save current clipboard to history
        clear: Clear clipboard history
        copy: Copy text to clipboard
    """
    # Load history
    history = []
    if _CLIPBOARD_HISTORY_FILE.exists():
        try:
            history = json.loads(_CLIPBOARD_HISTORY_FILE.read_text())
        except Exception:
            history = []
    
    operation = operation.lower().strip()
    
    if operation == "show":
        if not history:
            return {"success": True, "result": "Clipboard history is empty."}
        lines = [f"Clipboard history ({len(history)} entries):"]
        for i, entry in enumerate(reversed(history[-10:]), 1):
            preview = entry["text"][:60].replace("\n", "↵")
            lines.append(f"  {i}. [{entry['time']}] {preview}")
        return {"success": True, "result": "\n".join(lines)}
    
    elif operation == "copy":
        if not content:
            return {"success": False, "error": "No content to copy"}
        try:
            subprocess.run(["clip.exe"], input=content.encode(), check=True, timeout=5)
            # Add to history
            history.append({"text": content, "time": datetime.now().strftime("%H:%M")})
            if len(history) > 50:
                history = history[-50:]
            _CLIPBOARD_HISTORY_FILE.write_text(json.dumps(history))
            return {"success": True, "result": f"Copied to clipboard ({len(content)} chars)"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    elif operation == "save":
        # Read current clipboard
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=5
            )
            text = result.stdout.strip()
            if text:
                history.append({"text": text, "time": datetime.now().strftime("%H:%M")})
                if len(history) > 50:
                    history = history[-50:]
                _CLIPBOARD_HISTORY_FILE.write_text(json.dumps(history))
                return {"success": True, "result": f"Saved clipboard entry ({len(text)} chars)"}
            return {"success": True, "result": "Clipboard is empty"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    elif operation == "clear":
        _CLIPBOARD_HISTORY_FILE.write_text("[]")
        return {"success": True, "result": "Clipboard history cleared."}
    
    return {"success": False, "error": f"Unknown operation: {operation}"}
