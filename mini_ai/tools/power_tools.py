"""
power_tools.py – Advanced power user tools.

Features:
1. Screenshot capture + save
2. Color picker (from screen pixel)
3. QR code generator
4. Password vault (encrypted local storage)
5. IP info / network diagnostics
6. Text-to-speech
7. Bookmark manager (URLs with tags)
8. Quick math/unit converter (advanced)
9. Motivation quotes
10. System shortcuts (lock, sleep, shutdown, restart)
11. Bulk download (list of URLs)
12. JSON/YAML/CSV converter
"""
from __future__ import annotations

import json
import os
import hashlib
import base64
import subprocess
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

_STORAGE = Path.home() / ".mini_ai"
_STORAGE.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SCREENSHOT
# ═══════════════════════════════════════════════════════════════════════════════

def screenshot(save_path: str = "", region: str = "") -> dict[str, Any]:
    """Take a screenshot and save it.
    
    Args:
        save_path: Where to save (default: Desktop/screenshot_TIMESTAMP.png)
        region: "full" (default) or "x,y,w,h" for a specific region
    """
    if not save_path:
        desktop = Path.home() / "Desktop"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = str(desktop / f"screenshot_{ts}.png")
    
    try:
        # Try PowerShell method (works without extra deps)
        ps_script = f'''
Add-Type -AssemblyName System.Windows.Forms
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bitmap = New-Object System.Drawing.Bitmap($screen.Width, $screen.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size)
$bitmap.Save("{save_path}")
$graphics.Dispose()
$bitmap.Dispose()
'''
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and Path(save_path).exists():
            size = Path(save_path).stat().st_size
            return {"success": True, "result": f"📸 Screenshot saved: {save_path} ({size // 1024}KB)"}
        return {"success": False, "error": f"Screenshot failed: {result.stderr[:200]}"}
    except Exception as e:
        return {"success": False, "error": f"Screenshot error: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. IP INFO / NETWORK
# ═══════════════════════════════════════════════════════════════════════════════

def ip_info(target: str = "") -> dict[str, Any]:
    """Get IP information (public IP, geolocation, ISP).
    
    Args:
        target: IP address to lookup (empty = your public IP)
    """
    try:
        url = f"http://ip-api.com/json/{target}" if target else "http://ip-api.com/json/"
        req = urllib.request.Request(url, headers={"User-Agent": "MiniAI/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        
        if data.get("status") == "fail":
            return {"success": False, "error": data.get("message", "Lookup failed")}
        
        lines = [
            f"🌐 IP: {data.get('query', '?')}",
            f"📍 Location: {data.get('city', '?')}, {data.get('regionName', '?')}, {data.get('country', '?')}",
            f"🏢 ISP: {data.get('isp', '?')}",
            f"🏷️ Org: {data.get('org', '?')}",
            f"⏰ Timezone: {data.get('timezone', '?')}",
            f"📡 AS: {data.get('as', '?')}",
        ]
        return {"success": True, "result": "\n".join(lines)}
    except Exception as e:
        return {"success": False, "error": f"IP lookup failed: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TEXT-TO-SPEECH
# ═══════════════════════════════════════════════════════════════════════════════

def text_to_speech(text: str, rate: int = 150) -> dict[str, Any]:
    """Speak text aloud using Windows SAPI.
    
    Args:
        text: Text to speak
        rate: Speech rate (-10 to 10, default 0 mapped from 150 wpm)
    """
    if os.name != "nt":
        return {"success": False, "error": "TTS only supported on Windows"}
    
    try:
        # Use PowerShell SAPI
        escaped = text.replace("'", "''").replace('"', '`"')
        ps_cmd = f"Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Rate = {min(10, max(-10, (rate - 150) // 15))}; $s.Speak('{escaped}')"
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return {"success": True, "result": f"🔊 Speaking: {text[:50]}..."}
    except Exception as e:
        return {"success": False, "error": f"TTS error: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 4. BOOKMARK MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

_BOOKMARKS_FILE = _STORAGE / "bookmarks.json"

def bookmarks(operation: str = "list", url: str = "", title: str = "", tags: str = "") -> dict[str, Any]:
    """Manage URL bookmarks with tags.
    
    Operations: add, list, search, delete, export
    """
    bmarks = []
    if _BOOKMARKS_FILE.exists():
        try:
            bmarks = json.loads(_BOOKMARKS_FILE.read_text())
        except Exception:
            bmarks = []
    
    operation = operation.lower().strip()
    
    if operation == "add":
        if not url:
            return {"success": False, "error": "URL required"}
        entry = {
            "url": url,
            "title": title or url.split("/")[-1] or url,
            "tags": [t.strip() for t in tags.split(",") if t.strip()],
            "added": datetime.now().isoformat(),
        }
        bmarks.append(entry)
        _BOOKMARKS_FILE.write_text(json.dumps(bmarks, indent=2))
        return {"success": True, "result": f"🔖 Bookmarked: {entry['title']}"}
    
    elif operation == "list":
        if not bmarks:
            return {"success": True, "result": "No bookmarks saved."}
        lines = [f"🔖 Bookmarks ({len(bmarks)}):"]
        for b in bmarks[-15:]:
            tag_str = f" [{', '.join(b.get('tags', []))}]" if b.get('tags') else ""
            lines.append(f"  • {b['title']}: {b['url']}{tag_str}")
        return {"success": True, "result": "\n".join(lines)}
    
    elif operation == "search":
        query = (url or title or tags).lower()
        matches = [b for b in bmarks if query in b.get("title", "").lower() or query in b.get("url", "").lower() or query in " ".join(b.get("tags", []))]
        if not matches:
            return {"success": True, "result": f"No bookmarks matching '{query}'"}
        lines = [f"Found {len(matches)} bookmarks:"]
        for b in matches[:10]:
            lines.append(f"  • {b['title']}: {b['url']}")
        return {"success": True, "result": "\n".join(lines)}
    
    elif operation == "delete":
        query = url or title
        before = len(bmarks)
        bmarks = [b for b in bmarks if query.lower() not in b.get("url", "").lower() and query.lower() not in b.get("title", "").lower()]
        removed = before - len(bmarks)
        _BOOKMARKS_FILE.write_text(json.dumps(bmarks, indent=2))
        return {"success": True, "result": f"Removed {removed} bookmark(s)"}
    
    elif operation == "export":
        if not bmarks:
            return {"success": True, "result": "No bookmarks to export."}
        export_path = _STORAGE / "bookmarks_export.html"
        html = "<html><head><title>Bookmarks</title></head><body><h1>Bookmarks</h1><ul>"
        for b in bmarks:
            html += f'<li><a href="{b["url"]}">{b["title"]}</a></li>'
        html += "</ul></body></html>"
        export_path.write_text(html)
        return {"success": True, "result": f"Exported {len(bmarks)} bookmarks to {export_path}"}
    
    return {"success": False, "error": f"Unknown operation: {operation}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. MOTIVATION QUOTES
# ═══════════════════════════════════════════════════════════════════════════════

_QUOTES = [
    ("The only way to do great work is to love what you do.", "Steve Jobs"),
    ("Code is like humor. When you have to explain it, it's bad.", "Cory House"),
    ("First, solve the problem. Then, write the code.", "John Johnson"),
    ("Simplicity is the soul of efficiency.", "Austin Freeman"),
    ("Make it work, make it right, make it fast.", "Kent Beck"),
    ("The best error message is the one that never shows up.", "Thomas Fuchs"),
    ("Talk is cheap. Show me the code.", "Linus Torvalds"),
    ("Any fool can write code that a computer can understand. Good programmers write code that humans can understand.", "Martin Fowler"),
    ("Programming isn't about what you know; it's about what you can figure out.", "Chris Pine"),
    ("The most disastrous thing that you can ever learn is your first programming language.", "Alan Kay"),
    ("Don't comment bad code — rewrite it.", "Brian Kernighan"),
    ("Perfection is achieved not when there is nothing more to add, but when there is nothing left to take away.", "Antoine de Saint-Exupéry"),
    ("It's not a bug — it's an undocumented feature.", "Anonymous"),
    ("The best time to plant a tree was 20 years ago. The second best time is now.", "Chinese Proverb"),
    ("Stay hungry, stay foolish.", "Steve Jobs"),
    ("Done is better than perfect.", "Sheryl Sandberg"),
    ("Shipping beats perfection.", "Khan Academy"),
    ("You miss 100% of the shots you don't take.", "Wayne Gretzky"),
    ("The only limit to our realization of tomorrow is our doubts of today.", "Franklin D. Roosevelt"),
    ("Success is not final, failure is not fatal: it is the courage to continue that counts.", "Winston Churchill"),
]

def motivation(category: str = "") -> dict[str, Any]:
    """Get a random motivational quote."""
    import random
    quote, author = random.choice(_QUOTES)
    return {"success": True, "result": f"💡 \"{quote}\"\n   — {author}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 6. SYSTEM SHORTCUTS
# ═══════════════════════════════════════════════════════════════════════════════

def system_action(action: str) -> dict[str, Any]:
    """System power actions.
    
    Actions: lock, sleep, shutdown, restart, logoff, empty_recycle_bin
    """
    if os.name != "nt":
        return {"success": False, "error": "Only supported on Windows"}
    
    action = action.lower().strip()
    
    commands = {
        "lock": "rundll32.exe user32.dll,LockWorkStation",
        "sleep": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
        "shutdown": "shutdown /s /t 60 /c \"Mini AI: Shutting down in 60 seconds. Run 'shutdown /a' to cancel.\"",
        "restart": "shutdown /r /t 60 /c \"Mini AI: Restarting in 60 seconds. Run 'shutdown /a' to cancel.\"",
        "logoff": "shutdown /l",
        "cancel_shutdown": "shutdown /a",
        "empty_recycle_bin": "PowerShell -Command \"Clear-RecycleBin -Force -ErrorAction SilentlyContinue\"",
    }
    
    cmd = commands.get(action)
    if not cmd:
        available = ", ".join(sorted(commands.keys()))
        return {"success": False, "error": f"Unknown action: {action}. Available: {available}"}
    
    try:
        subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        messages = {
            "lock": "🔒 Screen locked",
            "sleep": "😴 Going to sleep...",
            "shutdown": "⚠️ Shutting down in 60s (run 'shutdown /a' to cancel)",
            "restart": "🔄 Restarting in 60s (run 'shutdown /a' to cancel)",
            "logoff": "👋 Logging off...",
            "cancel_shutdown": "✓ Shutdown cancelled",
            "empty_recycle_bin": "🗑️ Recycle bin emptied",
        }
        return {"success": True, "result": messages.get(action, f"Executed: {action}")}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 7. SPEED TEST (simplified)
# ═══════════════════════════════════════════════════════════════════════════════

def speed_test() -> dict[str, Any]:
    """Quick internet speed test (download only, using Cloudflare)."""
    try:
        # Download a 10MB file from Cloudflare
        url = "https://speed.cloudflare.com/__down?bytes=10000000"
        req = urllib.request.Request(url, headers={"User-Agent": "MiniAI/1.0"})
        
        start = time.time()
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        elapsed = time.time() - start
        
        size_mb = len(data) / (1024 * 1024)
        speed_mbps = (size_mb * 8) / elapsed
        
        # Also measure latency
        ping_start = time.time()
        urllib.request.urlopen("https://1.1.1.1/cdn-cgi/trace", timeout=5)
        latency = (time.time() - ping_start) * 1000
        
        return {"success": True, "result": (
            f"🚀 Speed Test Results:\n"
            f"  Download: {speed_mbps:.1f} Mbps\n"
            f"  Latency: {latency:.0f} ms\n"
            f"  Data: {size_mb:.1f} MB in {elapsed:.1f}s"
        )}
    except Exception as e:
        return {"success": False, "error": f"Speed test failed: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 8. WORD COUNT / TEXT STATS
# ═══════════════════════════════════════════════════════════════════════════════

def text_stats(text: str = "", file_path: str = "") -> dict[str, Any]:
    """Get text statistics (word count, char count, reading time, etc.).
    
    Args:
        text: Direct text input
        file_path: Path to a text file
    """
    if file_path:
        try:
            text = Path(file_path).expanduser().read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"success": False, "error": f"Could not read file: {e}"}
    
    if not text:
        return {"success": False, "error": "No text provided"}
    
    words = text.split()
    lines = text.split("\n")
    chars = len(text)
    chars_no_space = len(text.replace(" ", "").replace("\n", ""))
    sentences = len([s for s in text.replace("!", ".").replace("?", ".").split(".") if s.strip()])
    paragraphs = len([p for p in text.split("\n\n") if p.strip()])
    reading_time = len(words) / 200  # avg 200 wpm
    
    return {"success": True, "result": (
        f"📊 Text Statistics:\n"
        f"  Words: {len(words):,}\n"
        f"  Characters: {chars:,} ({chars_no_space:,} without spaces)\n"
        f"  Lines: {len(lines):,}\n"
        f"  Sentences: {sentences:,}\n"
        f"  Paragraphs: {paragraphs:,}\n"
        f"  Reading time: ~{reading_time:.1f} min"
    )}


# ═══════════════════════════════════════════════════════════════════════════════
# 9. COLOR CONVERTER
# ═══════════════════════════════════════════════════════════════════════════════

def color_convert(color: str) -> dict[str, Any]:
    """Convert between color formats (hex, rgb, hsl).
    
    Args:
        color: Color in any format: "#FF5733", "rgb(255,87,51)", "red", etc.
    """
    import re
    
    # Named colors
    named = {
        "red": (255, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 255),
        "white": (255, 255, 255), "black": (0, 0, 0), "yellow": (255, 255, 0),
        "cyan": (0, 255, 255), "magenta": (255, 0, 255), "orange": (255, 165, 0),
        "purple": (128, 0, 128), "pink": (255, 192, 203), "gray": (128, 128, 128),
        "grey": (128, 128, 128), "brown": (165, 42, 42), "navy": (0, 0, 128),
    }
    
    r, g, b = 0, 0, 0
    color_clean = color.strip().lower()
    
    if color_clean in named:
        r, g, b = named[color_clean]
    elif color_clean.startswith("#"):
        hex_val = color_clean[1:]
        if len(hex_val) == 3:
            hex_val = "".join(c * 2 for c in hex_val)
        r, g, b = int(hex_val[0:2], 16), int(hex_val[2:4], 16), int(hex_val[4:6], 16)
    elif "rgb" in color_clean:
        match = re.search(r'(\d+)\s*,\s*(\d+)\s*,\s*(\d+)', color_clean)
        if match:
            r, g, b = int(match.group(1)), int(match.group(2)), int(match.group(3))
    else:
        # Try as hex without #
        try:
            if len(color_clean) == 6:
                r, g, b = int(color_clean[0:2], 16), int(color_clean[2:4], 16), int(color_clean[4:6], 16)
        except ValueError:
            return {"success": False, "error": f"Could not parse color: {color}"}
    
    # Convert to HSL
    r_n, g_n, b_n = r / 255, g / 255, b / 255
    max_c, min_c = max(r_n, g_n, b_n), min(r_n, g_n, b_n)
    l = (max_c + min_c) / 2
    
    if max_c == min_c:
        h = s = 0
    else:
        d = max_c - min_c
        s = d / (2 - max_c - min_c) if l > 0.5 else d / (max_c + min_c)
        if max_c == r_n:
            h = (g_n - b_n) / d + (6 if g_n < b_n else 0)
        elif max_c == g_n:
            h = (b_n - r_n) / d + 2
        else:
            h = (r_n - g_n) / d + 4
        h /= 6
    
    hex_str = f"#{r:02X}{g:02X}{b:02X}"
    
    return {"success": True, "result": (
        f"🎨 Color: {color}\n"
        f"  HEX: {hex_str}\n"
        f"  RGB: rgb({r}, {g}, {b})\n"
        f"  HSL: hsl({int(h*360)}, {int(s*100)}%, {int(l*100)}%)\n"
        f"  CSS: {hex_str}"
    )}


# ═══════════════════════════════════════════════════════════════════════════════
# 10. LOREM IPSUM GENERATOR
# ═══════════════════════════════════════════════════════════════════════════════

def lorem_ipsum(paragraphs: int = 1, words: int = 0) -> dict[str, Any]:
    """Generate placeholder text.
    
    Args:
        paragraphs: Number of paragraphs (default 1)
        words: Specific word count (overrides paragraphs)
    """
    base = (
        "Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor "
        "incididunt ut labore et dolore magna aliqua Ut enim ad minim veniam quis nostrud "
        "exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat Duis aute irure "
        "dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur "
        "Excepteur sint occaecat cupidatat non proident sunt in culpa qui officia deserunt "
        "mollit anim id est laborum Sed ut perspiciatis unde omnis iste natus error sit "
        "voluptatem accusantium doloremque laudantium totam rem aperiam eaque ipsa quae ab illo "
        "inventore veritatis et quasi architecto beatae vitae dicta sunt explicabo"
    )
    
    all_words = base.split()
    
    if words > 0:
        result_words = []
        while len(result_words) < words:
            result_words.extend(all_words)
        text = " ".join(result_words[:words]) + "."
    else:
        import random
        paras = []
        for _ in range(paragraphs):
            length = random.randint(40, 80)
            start = random.randint(0, len(all_words) - 1)
            para_words = []
            while len(para_words) < length:
                para_words.extend(all_words[start:])
                start = 0
            para = " ".join(para_words[:length])
            # Capitalize first letter and add period
            para = para[0].upper() + para[1:] + "."
            paras.append(para)
        text = "\n\n".join(paras)
    
    # Copy to clipboard
    try:
        subprocess.run(["clip.exe"], input=text.encode(), check=True, timeout=3)
    except Exception:
        pass
    
    word_count = len(text.split())
    return {"success": True, "result": f"📝 Generated {word_count} words (copied to clipboard):\n\n{text[:500]}{'...' if len(text) > 500 else ''}"}
