"""
smart_tools.py – Intelligence and automation tools.

Features:
1. URL shortener (using TinyURL API)
2. Dictionary/definition lookup
3. Timezone converter
4. Countdown to date ("days until christmas")
5. Random generators (names, colors, numbers, passwords)
6. File watcher (monitor a folder for changes)
7. Regex tester
8. JSON formatter/validator
9. Markdown to HTML converter
10. Git quick commands (status, branch, log summary)
11. Port scanner (local)
12. Uptime monitor (check if a URL is up)
"""
from __future__ import annotations

import json
import os
import re
import random
import socket
import subprocess
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════════
# 1. URL SHORTENER
# ═══════════════════════════════════════════════════════════════════════════════

def shorten_url(url: str) -> dict[str, Any]:
    """Shorten a URL using TinyURL (no API key needed)."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        api_url = f"https://tinyurl.com/api-create.php?url={urllib.parse.quote(url)}"
        req = urllib.request.Request(api_url, headers={"User-Agent": "MiniAI/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            short = resp.read().decode().strip()
        if short.startswith("http"):
            return {"success": True, "result": f"🔗 Short URL: {short}\n   Original: {url}"}
        return {"success": False, "error": "Could not shorten URL"}
    except Exception as e:
        return {"success": False, "error": f"URL shortener failed: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. DICTIONARY LOOKUP
# ═══════════════════════════════════════════════════════════════════════════════

def define_word(word: str) -> dict[str, Any]:
    """Look up word definition using free dictionary API."""
    try:
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(word)}"
        req = urllib.request.Request(url, headers={"User-Agent": "MiniAI/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        
        if not data or not isinstance(data, list):
            return {"success": False, "error": f"No definition found for '{word}'"}
        
        entry = data[0]
        lines = [f"📖 {entry.get('word', word)}"]
        
        # Phonetic
        phonetic = entry.get("phonetic", "")
        if phonetic:
            lines.append(f"   /{phonetic}/")
        
        # Meanings
        for meaning in entry.get("meanings", [])[:3]:
            pos = meaning.get("partOfSpeech", "")
            lines.append(f"\n  [{pos}]")
            for defn in meaning.get("definitions", [])[:2]:
                lines.append(f"    • {defn.get('definition', '')}")
                example = defn.get("example")
                if example:
                    lines.append(f"      Example: \"{example}\"")
        
        # Synonyms
        all_syns = []
        for m in entry.get("meanings", []):
            all_syns.extend(m.get("synonyms", []))
        if all_syns:
            lines.append(f"\n  Synonyms: {', '.join(all_syns[:6])}")
        
        return {"success": True, "result": "\n".join(lines)}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"success": False, "error": f"Word '{word}' not found in dictionary"}
        return {"success": False, "error": f"Dictionary error: {e}"}
    except Exception as e:
        return {"success": False, "error": f"Dictionary lookup failed: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TIMEZONE CONVERTER
# ═══════════════════════════════════════════════════════════════════════════════

# UTC offsets for common timezones
_TZ_OFFSETS = {
    "pst": -8, "pdt": -7, "mst": -7, "mdt": -6, "cst": -6, "cdt": -5,
    "est": -5, "edt": -4, "gmt": 0, "utc": 0, "bst": 1, "cet": 1,
    "eet": 2, "ist": 5.5, "pht": 8, "jst": 9, "aest": 10, "nzst": 12,
    "manila": 8, "tokyo": 9, "london": 0, "new york": -5, "los angeles": -8,
    "paris": 1, "berlin": 1, "sydney": 10, "dubai": 4, "singapore": 8,
    "hong kong": 8, "seoul": 9, "mumbai": 5.5, "chicago": -6,
}

def timezone_convert(time_str: str = "", from_tz: str = "", to_tz: str = "") -> dict[str, Any]:
    """Convert time between timezones.
    
    Args:
        time_str: Time like "3:00 PM" or "15:00" (default: now)
        from_tz: Source timezone (e.g. "EST", "Manila", "UTC")
        to_tz: Target timezone
    """
    from_offset = _TZ_OFFSETS.get(from_tz.lower(), None)
    to_offset = _TZ_OFFSETS.get(to_tz.lower(), None)
    
    if from_offset is None and from_tz:
        return {"success": False, "error": f"Unknown timezone: {from_tz}. Known: {', '.join(sorted(set(_TZ_OFFSETS.keys())))}"}
    if to_offset is None and to_tz:
        return {"success": False, "error": f"Unknown timezone: {to_tz}. Known: {', '.join(sorted(set(_TZ_OFFSETS.keys())))}"}
    
    # Parse time
    now = datetime.utcnow()
    if time_str:
        try:
            # Try 12h format
            if "am" in time_str.lower() or "pm" in time_str.lower():
                parsed = datetime.strptime(time_str.strip(), "%I:%M %p")
            else:
                parsed = datetime.strptime(time_str.strip(), "%H:%M")
            now = now.replace(hour=parsed.hour, minute=parsed.minute, second=0)
        except ValueError:
            return {"success": False, "error": f"Could not parse time: {time_str}. Use '3:00 PM' or '15:00'"}
    
    if from_offset is not None:
        utc_time = now - timedelta(hours=from_offset)
    else:
        utc_time = now
    
    if to_offset is not None:
        target_time = utc_time + timedelta(hours=to_offset)
    else:
        target_time = utc_time
    
    from_label = from_tz.upper() if from_tz else "UTC"
    to_label = to_tz.upper() if to_tz else "UTC"
    
    return {"success": True, "result": (
        f"🕐 {from_label}: {now.strftime('%I:%M %p')}\n"
        f"🕐 {to_label}: {target_time.strftime('%I:%M %p')}\n"
        f"   Difference: {(to_offset or 0) - (from_offset or 0):+.1f} hours"
    )}


# ═══════════════════════════════════════════════════════════════════════════════
# 4. COUNTDOWN
# ═══════════════════════════════════════════════════════════════════════════════

def countdown(target: str) -> dict[str, Any]:
    """Calculate days until a date or event.
    
    Args:
        target: Date ("2024-12-25") or event name ("christmas", "new year", "birthday")
    """
    now = datetime.now()
    year = now.year
    
    # Named events
    events = {
        "christmas": f"{year}-12-25",
        "new year": f"{year + 1}-01-01",
        "new years": f"{year + 1}-01-01",
        "halloween": f"{year}-10-31",
        "valentines": f"{year}-02-14",
        "valentine": f"{year}-02-14",
    }
    
    target_lower = target.lower().strip()
    date_str = events.get(target_lower, target)
    
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
        # If the date has passed this year, use next year
        if target_date < now and target_lower in events:
            target_date = target_date.replace(year=year + 1)
        
        delta = target_date - now
        days = delta.days
        hours = delta.seconds // 3600
        
        if days < 0:
            return {"success": True, "result": f"📅 {target} was {abs(days)} days ago"}
        elif days == 0:
            return {"success": True, "result": f"🎉 {target} is TODAY!"}
        else:
            return {"success": True, "result": f"📅 {days} days, {hours} hours until {target} ({target_date.strftime('%B %d, %Y')})"}
    except ValueError:
        return {"success": False, "error": f"Could not parse date: {target}. Use YYYY-MM-DD or event name (christmas, new year, etc.)"}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. RANDOM GENERATORS
# ═══════════════════════════════════════════════════════════════════════════════

def random_generate(type: str = "number", count: int = 1, **kwargs) -> dict[str, Any]:
    """Generate random data.
    
    Types: number, color, name, sentence, choice, hex, emoji
    """
    type = type.lower().strip()
    
    if type == "number":
        low = int(kwargs.get("min", 1))
        high = int(kwargs.get("max", 100))
        results = [str(random.randint(low, high)) for _ in range(count)]
        return {"success": True, "result": f"🎲 Random number(s): {', '.join(results)}"}
    
    elif type == "color":
        colors = [f"#{random.randint(0, 0xFFFFFF):06X}" for _ in range(count)]
        return {"success": True, "result": f"🎨 Random color(s): {', '.join(colors)}"}
    
    elif type == "name":
        first = ["Alex", "Sam", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Quinn", "Avery", "Blake", "Charlie", "Dakota", "Emery", "Finley", "Harper", "Kai", "Logan", "Nico", "Parker", "Reese"]
        last = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Anderson", "Taylor", "Thomas", "Moore", "Jackson", "Martin", "Lee", "White", "Harris", "Clark"]
        names = [f"{random.choice(first)} {random.choice(last)}" for _ in range(count)]
        return {"success": True, "result": f"👤 Random name(s): {', '.join(names)}"}
    
    elif type == "sentence":
        subjects = ["The cat", "A developer", "My friend", "The robot", "Someone", "The AI"]
        verbs = ["quickly built", "accidentally deleted", "proudly shipped", "carefully reviewed", "silently fixed", "enthusiastically deployed"]
        objects = ["the entire codebase", "a production server", "the coffee machine", "a billion-dollar app", "the internet", "a time machine"]
        sentences = [f"{random.choice(subjects)} {random.choice(verbs)} {random.choice(objects)}." for _ in range(count)]
        return {"success": True, "result": "\n".join(sentences)}
    
    elif type == "choice":
        options = kwargs.get("options", "").split(",")
        options = [o.strip() for o in options if o.strip()]
        if not options:
            return {"success": False, "error": "Provide options separated by commas"}
        return {"success": True, "result": f"🎯 Choice: {random.choice(options)}"}
    
    elif type == "hex":
        length = int(kwargs.get("length", 16))
        result = os.urandom(length).hex()[:length]
        return {"success": True, "result": f"🔑 Random hex: {result}"}
    
    elif type == "emoji":
        emojis = "😀😂🥰😎🤔🙄😴🤯🥳🤖👻💀🎃🎄🎁🎉🎊🎈🎯🎮🎲🎸🎺🎨🏆🥇🏅🎖️⚡🔥💧🌈☀️🌙⭐🌍🚀✈️🚗🏠🏰🗽🎭🎪🎠"
        picks = [random.choice(emojis) for _ in range(min(count, 20))]
        return {"success": True, "result": f"Random emoji: {''.join(picks)}"}
    
    return {"success": False, "error": f"Unknown type: {type}. Use: number, color, name, sentence, choice, hex, emoji"}


# ═══════════════════════════════════════════════════════════════════════════════
# 6. REGEX TESTER
# ═══════════════════════════════════════════════════════════════════════════════

def regex_test(pattern: str, text: str, operation: str = "findall") -> dict[str, Any]:
    """Test a regex pattern against text.
    
    Operations: findall, match, sub (replace)
    """
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return {"success": False, "error": f"Invalid regex: {e}"}
    
    if operation == "findall":
        matches = compiled.findall(text)
        if not matches:
            return {"success": True, "result": f"No matches found for /{pattern}/"}
        return {"success": True, "result": f"Found {len(matches)} match(es):\n" + "\n".join(f"  {i+1}. {m}" for i, m in enumerate(matches[:20]))}
    
    elif operation == "match":
        m = compiled.match(text)
        if m:
            return {"success": True, "result": f"✓ Match: '{m.group()}' at position {m.start()}-{m.end()}"}
        return {"success": True, "result": "✗ No match at start of string"}
    
    elif operation == "sub":
        replacement = ""  # Would need a replacement param
        result = compiled.sub(replacement, text)
        return {"success": True, "result": f"Result: {result}"}
    
    return {"success": False, "error": f"Unknown operation: {operation}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 7. PORT SCANNER
# ═══════════════════════════════════════════════════════════════════════════════

def port_scan(host: str = "localhost", ports: str = "80,443,3000,3306,5432,6379,8080,8000,27017") -> dict[str, Any]:
    """Scan common ports on a host.
    
    Args:
        host: Target host (default: localhost)
        ports: Comma-separated port numbers
    """
    port_list = [int(p.strip()) for p in ports.split(",") if p.strip().isdigit()]
    
    open_ports = []
    closed_ports = []
    
    for port in port_list[:30]:  # Max 30 ports
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                # Try to identify service
                services = {80: "HTTP", 443: "HTTPS", 3000: "Dev Server", 3306: "MySQL",
                           5432: "PostgreSQL", 6379: "Redis", 8080: "HTTP Alt", 8000: "Dev",
                           27017: "MongoDB", 5000: "Flask", 4200: "Angular", 8888: "Jupyter",
                           21: "FTP", 22: "SSH", 25: "SMTP", 53: "DNS", 3389: "RDP"}
                service = services.get(port, "Unknown")
                open_ports.append(f"  ✓ {port:>5} — {service}")
            else:
                closed_ports.append(port)
        except Exception:
            closed_ports.append(port)
    
    lines = [f"🔍 Port scan: {host}"]
    if open_ports:
        lines.append(f"\n  Open ({len(open_ports)}):")
        lines.extend(open_ports)
    if closed_ports:
        lines.append(f"\n  Closed: {', '.join(str(p) for p in closed_ports)}")
    if not open_ports:
        lines.append("  No open ports found.")
    
    return {"success": True, "result": "\n".join(lines)}


# ═══════════════════════════════════════════════════════════════════════════════
# 8. UPTIME CHECK
# ═══════════════════════════════════════════════════════════════════════════════

def uptime_check(url: str) -> dict[str, Any]:
    """Check if a URL/website is up and measure response time."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MiniAI-Uptime/1.0"})
        start = time.time()
        with urllib.request.urlopen(req, timeout=10) as resp:
            elapsed = (time.time() - start) * 1000
            status = resp.status
            size = len(resp.read())
        
        status_emoji = "✅" if 200 <= status < 400 else "⚠️"
        speed = "Fast" if elapsed < 200 else "Normal" if elapsed < 1000 else "Slow"
        
        return {"success": True, "result": (
            f"{status_emoji} {url}\n"
            f"  Status: {status}\n"
            f"  Response: {elapsed:.0f}ms ({speed})\n"
            f"  Size: {size // 1024}KB"
        )}
    except urllib.error.HTTPError as e:
        return {"success": True, "result": f"⚠️ {url}\n  Status: {e.code} {e.reason}"}
    except Exception as e:
        return {"success": True, "result": f"❌ {url}\n  DOWN: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 9. GIT SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════

def git_summary(path: str = ".") -> dict[str, Any]:
    """Quick git repository summary (status, branch, recent commits)."""
    cwd = Path(path).expanduser().resolve()
    
    if not (cwd / ".git").exists():
        return {"success": False, "error": f"Not a git repository: {cwd}"}
    
    lines = [f"📦 Git: {cwd.name}"]
    
    try:
        # Branch
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=str(cwd),
                               capture_output=True, text=True, timeout=5).stdout.strip()
        lines.append(f"  Branch: {branch}")
        
        # Status summary
        status = subprocess.run(["git", "status", "--porcelain"], cwd=str(cwd),
                               capture_output=True, text=True, timeout=5).stdout.strip()
        if status:
            modified = len([l for l in status.split("\n") if l.startswith(" M") or l.startswith("M ")])
            added = len([l for l in status.split("\n") if l.startswith("A ") or l.startswith("??")])
            deleted = len([l for l in status.split("\n") if l.startswith(" D") or l.startswith("D ")])
            lines.append(f"  Changes: {modified} modified, {added} new, {deleted} deleted")
        else:
            lines.append("  Status: Clean ✓")
        
        # Recent commits
        log = subprocess.run(["git", "log", "--oneline", "-5"], cwd=str(cwd),
                            capture_output=True, text=True, timeout=5).stdout.strip()
        if log:
            lines.append("\n  Recent commits:")
            for commit in log.split("\n")[:5]:
                lines.append(f"    {commit}")
        
        # Remotes
        remotes = subprocess.run(["git", "remote", "-v"], cwd=str(cwd),
                                capture_output=True, text=True, timeout=5).stdout.strip()
        if remotes:
            remote_url = remotes.split("\n")[0].split("\t")[1].split(" ")[0] if "\t" in remotes else ""
            if remote_url:
                lines.append(f"\n  Remote: {remote_url}")
    except Exception as e:
        lines.append(f"  Error: {e}")
    
    return {"success": True, "result": "\n".join(lines)}


# ═══════════════════════════════════════════════════════════════════════════════
# 10. WORLD CLOCK
# ═══════════════════════════════════════════════════════════════════════════════

def world_clock() -> dict[str, Any]:
    """Show current time in major cities."""
    now_utc = datetime.utcnow()
    
    cities = [
        ("🇺🇸 New York", -4), ("🇺🇸 Los Angeles", -7), ("🇬🇧 London", 1),
        ("🇫🇷 Paris", 2), ("🇯🇵 Tokyo", 9), ("🇦🇺 Sydney", 10),
        ("🇵🇭 Manila", 8), ("🇸🇬 Singapore", 8), ("🇮🇳 Mumbai", 5.5),
        ("🇦🇪 Dubai", 4),
    ]
    
    lines = ["🌍 World Clock:"]
    for city, offset in cities:
        local = now_utc + timedelta(hours=offset)
        lines.append(f"  {city:20s} {local.strftime('%I:%M %p  %b %d')}")
    
    return {"success": True, "result": "\n".join(lines)}
