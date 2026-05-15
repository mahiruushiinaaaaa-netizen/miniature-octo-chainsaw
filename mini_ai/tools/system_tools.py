"""
system_tools.py - System information, process management, clipboard,
environment variables, file metadata, screenshots, and timers.
"""
from __future__ import annotations

import hashlib
import os
import platform
import shutil
import signal
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def system_info(query: str) -> dict[str, Any]:
    """Get system information based on query type."""
    query = query.lower().strip()

    if query == "all":
        parts = []
        for q in ["cpu", "memory", "disk", "network", "env"]:
            result = system_info(q)
            if result.get("success"):
                parts.append(result["result"])
        return {"success": True, "result": "\n\n".join(parts)}

    elif query == "cpu":
        info = [
            f"Platform: {platform.system()} {platform.release()}",
            f"Machine: {platform.machine()}",
            f"Processor: {platform.processor()}",
            f"CPU Count: {os.cpu_count()}",
            f"Architecture: {platform.architecture()[0]}",
        ]
        return {"success": True, "result": "\n".join(info)}

    elif query == "memory":
        try:
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["wmic", "OS", "get", "FreePhysicalMemory,TotalVisibleMemorySize", "/Value"],
                    capture_output=True, text=True, timeout=5
                )
                lines = result.stdout.strip().split("\n")
                info = {}
                for line in lines:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        info[k] = v
                total_kb = int(info.get("TotalVisibleMemorySize", 0))
                free_kb = int(info.get("FreePhysicalMemory", 0))
                total_gb = total_kb / 1024 / 1024
                free_gb = free_kb / 1024 / 1024
                used_gb = total_gb - free_gb
                return {"success": True, "result": f"Memory:\n  Total: {total_gb:.1f} GB\n  Used: {used_gb:.1f} GB\n  Free: {free_gb:.1f} GB\n  Usage: {(used_gb/total_gb)*100:.0f}%"}
            else:
                result = subprocess.run(["free", "-h"], capture_output=True, text=True, timeout=5)
                return {"success": True, "result": f"Memory:\n{result.stdout}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif query == "disk":
        try:
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["wmic", "logicaldisk", "get", "size,freespace,caption", "/format:list"],
                    capture_output=True, text=True, timeout=5
                )
                return {"success": True, "result": f"Disk:\n{result.stdout.strip()}"}
            else:
                result = subprocess.run(["df", "-h"], capture_output=True, text=True, timeout=5)
                return {"success": True, "result": f"Disk:\n{result.stdout}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif query == "network":
        try:
            if platform.system() == "Windows":
                result = subprocess.run(["ipconfig"], capture_output=True, text=True, timeout=5)
                # Extract just the key info
                lines = result.stdout.split("\n")
                relevant = [l for l in lines if any(k in l for k in ["IPv4", "Subnet", "Gateway", "adapter"])]
                return {"success": True, "result": "Network:\n" + "\n".join(relevant[:20])}
            else:
                result = subprocess.run(["ip", "addr"], capture_output=True, text=True, timeout=5)
                return {"success": True, "result": f"Network:\n{result.stdout[:2000]}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif query == "processes":
        try:
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["tasklist", "/FO", "TABLE", "/NH"],
                    capture_output=True, text=True, timeout=5
                )
                lines = result.stdout.strip().split("\n")[:30]
                return {"success": True, "result": "Top processes:\n" + "\n".join(lines)}
            else:
                result = subprocess.run(
                    ["ps", "aux", "--sort=-pcpu"],
                    capture_output=True, text=True, timeout=5
                )
                lines = result.stdout.strip().split("\n")[:20]
                return {"success": True, "result": "\n".join(lines)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif query == "env":
        # Show key environment variables (not secrets)
        safe_vars = ["PATH", "HOME", "USERPROFILE", "COMPUTERNAME", "USERNAME",
                     "OS", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS",
                     "TEMP", "TMP", "LANG", "SHELL", "TERM"]
        info = []
        for var in safe_vars:
            val = os.environ.get(var)
            if val:
                # Truncate PATH
                if var == "PATH":
                    val = val[:200] + "..." if len(val) > 200 else val
                info.append(f"  {var}={val}")
        return {"success": True, "result": "Environment:\n" + "\n".join(info)}

    elif query == "ports":
        try:
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["netstat", "-an"],
                    capture_output=True, text=True, timeout=5
                )
                lines = result.stdout.strip().split("\n")
                listening = [l for l in lines if "LISTENING" in l][:20]
                return {"success": True, "result": "Listening ports:\n" + "\n".join(listening)}
            else:
                result = subprocess.run(
                    ["ss", "-tlnp"],
                    capture_output=True, text=True, timeout=5
                )
                return {"success": True, "result": f"Listening ports:\n{result.stdout[:2000]}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    else:
        return {"success": False, "error": f"Unknown query: {query}. Use: all, cpu, memory, disk, network, processes, env, ports"}


def env_var(operation: str, name: str = "", value: str = "") -> dict[str, Any]:
    """Manage environment variables for the current session."""
    operation = operation.lower().strip()

    if operation == "get":
        if not name:
            return {"success": False, "error": "Variable name required"}
        val = os.environ.get(name)
        if val is None:
            return {"success": False, "error": f"Variable '{name}' not set"}
        return {"success": True, "result": f"{name}={val}"}

    elif operation == "set":
        if not name:
            return {"success": False, "error": "Variable name required"}
        os.environ[name] = value
        return {"success": True, "result": f"Set {name}={value}"}

    elif operation == "unset":
        if not name:
            return {"success": False, "error": "Variable name required"}
        if name in os.environ:
            del os.environ[name]
            return {"success": True, "result": f"Unset {name}"}
        return {"success": False, "error": f"Variable '{name}' not set"}

    elif operation == "list":
        items = sorted(os.environ.items())
        lines = [f"{k}={v[:100]}" for k, v in items[:50]]
        return {"success": True, "result": "\n".join(lines), "count": len(items)}

    else:
        return {"success": False, "error": f"Unknown operation: {operation}. Use: get, set, list, unset"}


def process_manage(operation: str, target: str = "", signal_name: str = "term") -> dict[str, Any]:
    """Manage system processes."""
    operation = operation.lower().strip()

    if operation == "list":
        try:
            if platform.system() == "Windows":
                filter_arg = []
                if target:
                    filter_arg = ["/FI", f"IMAGENAME eq {target}*"]
                result = subprocess.run(
                    ["tasklist", "/FO", "TABLE"] + filter_arg,
                    capture_output=True, text=True, timeout=5
                )
                return {"success": True, "result": result.stdout[:3000]}
            else:
                cmd = ["ps", "aux"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if target:
                    lines = [l for l in result.stdout.split("\n") if target.lower() in l.lower()]
                    return {"success": True, "result": "\n".join(lines[:30])}
                return {"success": True, "result": result.stdout[:3000]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif operation == "kill":
        if not target:
            return {"success": False, "error": "Target (PID or process name) required"}
        try:
            if platform.system() == "Windows":
                # Try as PID first
                try:
                    pid = int(target)
                    result = subprocess.run(
                        ["taskkill", "/PID", str(pid), "/F"],
                        capture_output=True, text=True, timeout=5
                    )
                except ValueError:
                    result = subprocess.run(
                        ["taskkill", "/IM", target, "/F"],
                        capture_output=True, text=True, timeout=5
                    )
                return {"success": result.returncode == 0, "result": result.stdout + result.stderr}
            else:
                try:
                    pid = int(target)
                    sig = {"term": signal.SIGTERM, "kill": signal.SIGKILL, "int": signal.SIGINT}.get(signal_name, signal.SIGTERM)
                    os.kill(pid, sig)
                    return {"success": True, "result": f"Sent {signal_name} to PID {pid}"}
                except ValueError:
                    result = subprocess.run(["pkill", "-f", target], capture_output=True, text=True, timeout=5)
                    return {"success": result.returncode == 0, "result": result.stdout + result.stderr}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif operation == "start_bg":
        if not target:
            return {"success": False, "error": "Command required"}
        try:
            if platform.system() == "Windows":
                proc = subprocess.Popen(
                    target, shell=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:
                proc = subprocess.Popen(
                    target, shell=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
            return {"success": True, "result": f"Started background process: PID {proc.pid}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif operation == "status":
        if not target:
            return {"success": False, "error": "PID required"}
        try:
            pid = int(target)
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "TABLE"],
                    capture_output=True, text=True, timeout=5
                )
                running = str(pid) in result.stdout
                return {"success": True, "result": f"PID {pid}: {'running' if running else 'not found'}\n{result.stdout.strip()}"}
            else:
                os.kill(pid, 0)  # Check if process exists
                return {"success": True, "result": f"PID {pid}: running"}
        except (ProcessLookupError, OSError):
            return {"success": True, "result": f"PID {target}: not running"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    else:
        return {"success": False, "error": f"Unknown operation: {operation}. Use: list, kill, start_bg, status"}


def clipboard_op(operation: str, content: str = "") -> dict[str, Any]:
    """Copy to or paste from system clipboard."""
    operation = operation.lower().strip()

    if operation == "copy":
        if not content:
            return {"success": False, "error": "Content required for copy"}
        try:
            if platform.system() == "Windows":
                proc = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
                proc.communicate(content.encode("utf-16le"))
                return {"success": True, "result": f"Copied {len(content)} chars to clipboard"}
            elif platform.system() == "Darwin":
                proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                proc.communicate(content.encode("utf-8"))
                return {"success": True, "result": f"Copied {len(content)} chars to clipboard"}
            else:
                proc = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
                proc.communicate(content.encode("utf-8"))
                return {"success": True, "result": f"Copied {len(content)} chars to clipboard"}
        except Exception as e:
            return {"success": False, "error": f"Clipboard copy failed: {e}"}

    elif operation == "paste":
        try:
            if platform.system() == "Windows":
                result = subprocess.run(
                    ["powershell", "-command", "Get-Clipboard"],
                    capture_output=True, text=True, timeout=5
                )
                return {"success": True, "result": result.stdout}
            elif platform.system() == "Darwin":
                result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
                return {"success": True, "result": result.stdout}
            else:
                result = subprocess.run(
                    ["xclip", "-selection", "clipboard", "-o"],
                    capture_output=True, text=True, timeout=5
                )
                return {"success": True, "result": result.stdout}
        except Exception as e:
            return {"success": False, "error": f"Clipboard paste failed: {e}"}

    else:
        return {"success": False, "error": f"Unknown operation: {operation}. Use: copy, paste"}


def file_info(path_str: str, detail: str = "basic") -> dict[str, Any]:
    """Get detailed file metadata."""
    path = Path(path_str)
    if not path.exists():
        return {"success": False, "error": f"Path not found: {path_str}"}

    try:
        stat = path.stat()
        info = {
            "path": str(path.resolve()),
            "name": path.name,
            "type": "directory" if path.is_dir() else "file",
            "size": stat.st_size,
            "size_human": _human_size(stat.st_size),
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
        }

        if detail in ("full", "hash"):
            info["extension"] = path.suffix
            info["parent"] = str(path.parent)

            if path.is_file():
                # MIME type detection
                import mimetypes
                mime, _ = mimetypes.guess_type(str(path))
                info["mime_type"] = mime or "unknown"

                # Line count for text files
                if mime and mime.startswith("text") or path.suffix in (".py", ".js", ".ts", ".json", ".md", ".txt", ".html", ".css"):
                    try:
                        info["lines"] = sum(1 for _ in open(path, "r", encoding="utf-8", errors="replace"))
                    except Exception:
                        pass

            if path.is_dir():
                items = list(path.iterdir())
                info["items"] = len(items)
                info["files"] = sum(1 for i in items if i.is_file())
                info["dirs"] = sum(1 for i in items if i.is_dir())

        if detail == "hash" and path.is_file():
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            info["sha256"] = h.hexdigest()

        # Format output
        lines = [f"File Info: {path_str}"]
        for k, v in info.items():
            lines.append(f"  {k}: {v}")

        return {"success": True, "result": "\n".join(lines)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def diff_files(file1: str, file2: str, fmt: str = "unified") -> dict[str, Any]:
    """Compare two files and show differences."""
    p1 = Path(file1)
    p2 = Path(file2)

    if not p1.exists():
        return {"success": False, "error": f"File not found: {file1}"}
    if not p2.exists():
        return {"success": False, "error": f"File not found: {file2}"}

    try:
        lines1 = p1.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        lines2 = p2.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)

        import difflib

        if fmt == "summary":
            matcher = difflib.SequenceMatcher(None, lines1, lines2)
            ratio = matcher.ratio()
            ops = matcher.get_opcodes()
            changes = sum(1 for op, *_ in ops if op != "equal")
            return {"success": True, "result": f"Similarity: {ratio*100:.1f}%\nChanges: {changes} blocks\nFile 1: {len(lines1)} lines\nFile 2: {len(lines2)} lines"}

        elif fmt == "context":
            diff = difflib.context_diff(lines1, lines2, fromfile=file1, tofile=file2)
        else:
            diff = difflib.unified_diff(lines1, lines2, fromfile=file1, tofile=file2)

        result = "".join(diff)
        if not result:
            return {"success": True, "result": "Files are identical"}
        return {"success": True, "result": result[:5000]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def screenshot(output_path: str, region: str = "full") -> dict[str, Any]:
    """Take a screenshot."""
    try:
        if platform.system() == "Windows":
            # Use PowerShell to take screenshot
            ps_script = f'''
Add-Type -AssemblyName System.Windows.Forms
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bitmap = New-Object System.Drawing.Bitmap($screen.Width, $screen.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size)
$bitmap.Save("{output_path}")
$graphics.Dispose()
$bitmap.Dispose()
'''
            result = subprocess.run(
                ["powershell", "-command", ps_script],
                capture_output=True, text=True, timeout=10
            )
            if Path(output_path).exists():
                return {"success": True, "result": f"Screenshot saved to: {output_path}"}
            return {"success": False, "error": f"Screenshot failed: {result.stderr}"}
        else:
            # Try scrot or import (ImageMagick)
            for cmd in [["scrot", output_path], ["import", "-window", "root", output_path]]:
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        return {"success": True, "result": f"Screenshot saved to: {output_path}"}
                except FileNotFoundError:
                    continue
            return {"success": False, "error": "No screenshot tool available (install scrot or imagemagick)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _human_size(size: int) -> str:
    """Convert bytes to human-readable size."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"
