"""
life_tools.py – Personal life management tools.

Features:
1. Weather lookup (wttr.in API, no key needed)
2. Quick translate (MyMemory API, free)
3. Email draft generator
4. Pomodoro timer
5. Habit tracker
6. Expense tracker
7. Daily planner / schedule
8. Quick API tester
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_STORAGE = Path.home() / ".mini_ai"
_STORAGE.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. WEATHER
# ═══════════════════════════════════════════════════════════════════════════════

def weather(location: str = "", units: str = "metric") -> dict[str, Any]:
    """Get current weather using wttr.in (no API key needed).
    
    Args:
        location: City name or empty for auto-detect by IP
        units: "metric" or "imperial"
    """
    try:
        loc = urllib.parse.quote(location) if location else ""
        url = f"https://wttr.in/{loc}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        
        current = data.get("current_condition", [{}])[0]
        area = data.get("nearest_area", [{}])[0]
        
        city = area.get("areaName", [{}])[0].get("value", "Unknown")
        country = area.get("country", [{}])[0].get("value", "")
        
        if units == "imperial":
            temp = current.get("temp_F", "?")
            feels = current.get("FeelsLikeF", "?")
            unit = "°F"
        else:
            temp = current.get("temp_C", "?")
            feels = current.get("FeelsLikeC", "?")
            unit = "°C"
        
        desc = current.get("weatherDesc", [{}])[0].get("value", "Unknown")
        humidity = current.get("humidity", "?")
        wind_kmph = current.get("windspeedKmph", "?")
        
        # Forecast
        forecast_lines = []
        for day in data.get("weather", [])[:3]:
            date = day.get("date", "")
            max_t = day.get("maxtempC" if units == "metric" else "maxtempF", "?")
            min_t = day.get("mintempC" if units == "metric" else "mintempF", "?")
            desc_f = day.get("hourly", [{}])[4].get("weatherDesc", [{}])[0].get("value", "") if day.get("hourly") else ""
            forecast_lines.append(f"  {date}: {min_t}-{max_t}{unit} {desc_f}")
        
        result = (
            f"📍 {city}, {country}\n"
            f"🌡️  {temp}{unit} (feels like {feels}{unit})\n"
            f"☁️  {desc}\n"
            f"💧 Humidity: {humidity}%\n"
            f"💨 Wind: {wind_kmph} km/h\n"
        )
        if forecast_lines:
            result += f"\n📅 Forecast:\n" + "\n".join(forecast_lines)
        
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": f"Weather lookup failed: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TRANSLATE
# ═══════════════════════════════════════════════════════════════════════════════

def translate(text: str, to_lang: str = "en", from_lang: str = "auto") -> dict[str, Any]:
    """Translate text using MyMemory API (free, no key needed).
    
    Args:
        text: Text to translate
        to_lang: Target language code (en, es, fr, de, ja, ko, zh, etc.)
        from_lang: Source language code or "auto"
    """
    # Language name → code mapping
    lang_map = {
        "english": "en", "spanish": "es", "french": "fr", "german": "de",
        "italian": "it", "portuguese": "pt", "japanese": "ja", "korean": "ko",
        "chinese": "zh-CN", "russian": "ru", "arabic": "ar", "hindi": "hi",
        "dutch": "nl", "swedish": "sv", "norwegian": "no", "danish": "da",
        "finnish": "fi", "polish": "pl", "turkish": "tr", "thai": "th",
        "vietnamese": "vi", "indonesian": "id", "tagalog": "tl", "filipino": "tl",
        "malay": "ms", "czech": "cs", "greek": "el", "hebrew": "he",
        "hungarian": "hu", "romanian": "ro", "ukrainian": "uk",
    }
    
    to_lang = lang_map.get(to_lang.lower(), to_lang.lower())
    from_lang = lang_map.get(from_lang.lower(), from_lang.lower()) if from_lang != "auto" else "auto"
    
    if from_lang == "auto":
        from_lang = "en" if not any(ord(c) > 127 for c in text) else "auto"
    
    try:
        encoded = urllib.parse.quote(text)
        url = f"https://api.mymemory.translated.net/get?q={encoded}&langpair={from_lang}|{to_lang}"
        req = urllib.request.Request(url, headers={"User-Agent": "MiniAI/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        
        translated = data.get("responseData", {}).get("translatedText", "")
        if not translated:
            return {"success": False, "error": "Translation returned empty result"}
        
        return {"success": True, "result": f"🌐 {from_lang} → {to_lang}\n\n{translated}"}
    except Exception as e:
        return {"success": False, "error": f"Translation failed: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. EMAIL DRAFT
# ═══════════════════════════════════════════════════════════════════════════════

def email_draft(to: str, subject: str, body: str = "", tone: str = "professional") -> dict[str, Any]:
    """Generate an email draft.
    
    Args:
        to: Recipient name or email
        subject: Email subject
        body: Key points to include (optional)
        tone: "professional", "casual", "formal", "friendly"
    """
    greetings = {
        "professional": f"Dear {to},",
        "casual": f"Hey {to},",
        "formal": f"Dear Mr./Ms. {to},",
        "friendly": f"Hi {to}!",
    }
    
    closings = {
        "professional": "Best regards,",
        "casual": "Cheers,",
        "formal": "Sincerely,",
        "friendly": "Talk soon,",
    }
    
    greeting = greetings.get(tone, greetings["professional"])
    closing = closings.get(tone, closings["professional"])
    
    if body:
        content = body
    else:
        content = f"I am writing to you regarding {subject}.\n\n[Your message here]"
    
    draft = f"Subject: {subject}\nTo: {to}\n\n{greeting}\n\n{content}\n\n{closing}\n[Your Name]"
    
    # Also copy to clipboard on Windows
    try:
        import subprocess
        subprocess.run(["clip.exe"], input=draft.encode(), check=True, timeout=3)
    except Exception:
        pass
    
    return {"success": True, "result": f"📧 Email draft (copied to clipboard):\n\n{draft}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 4. POMODORO TIMER
# ═══════════════════════════════════════════════════════════════════════════════

_POMODORO_FILE = _STORAGE / "pomodoro.json"

def pomodoro(operation: str = "start", work_min: int = 25, break_min: int = 5) -> dict[str, Any]:
    """Pomodoro timer (25min work, 5min break).
    
    Operations: start, status, stop, stats
    """
    operation = operation.lower().strip()
    
    # Load state
    state = {}
    if _POMODORO_FILE.exists():
        try:
            state = json.loads(_POMODORO_FILE.read_text())
        except Exception:
            state = {}
    
    if operation == "start":
        state = {
            "started": time.time(),
            "work_min": work_min,
            "break_min": break_min,
            "phase": "work",
            "sessions_today": state.get("sessions_today", 0),
            "date": datetime.now().strftime("%Y-%m-%d"),
        }
        # Reset counter if new day
        if state.get("date") != datetime.now().strftime("%Y-%m-%d"):
            state["sessions_today"] = 0
        _POMODORO_FILE.write_text(json.dumps(state))
        return {"success": True, "result": f"🍅 Pomodoro started! {work_min}min work session.\nFocus time — no distractions!"}
    
    elif operation == "status":
        if not state or "started" not in state:
            return {"success": True, "result": "No active pomodoro. Use 'start' to begin."}
        
        elapsed = time.time() - state["started"]
        phase = state.get("phase", "work")
        duration = state["work_min"] * 60 if phase == "work" else state["break_min"] * 60
        remaining = max(0, duration - elapsed)
        
        if remaining <= 0:
            if phase == "work":
                state["phase"] = "break"
                state["started"] = time.time()
                state["sessions_today"] = state.get("sessions_today", 0) + 1
                _POMODORO_FILE.write_text(json.dumps(state))
                return {"success": True, "result": f"🎉 Work session complete! Take a {state['break_min']}min break.\nSessions today: {state['sessions_today']}"}
            else:
                state["phase"] = "idle"
                _POMODORO_FILE.write_text(json.dumps(state))
                return {"success": True, "result": f"☕ Break over! Ready for another session?\nSessions today: {state.get('sessions_today', 0)}"}
        
        mins, secs = divmod(int(remaining), 60)
        emoji = "🍅" if phase == "work" else "☕"
        return {"success": True, "result": f"{emoji} {phase.title()}: {mins}m {secs}s remaining\nSessions today: {state.get('sessions_today', 0)}"}
    
    elif operation == "stop":
        _POMODORO_FILE.write_text("{}")
        return {"success": True, "result": "Pomodoro stopped."}
    
    elif operation == "stats":
        sessions = state.get("sessions_today", 0)
        total_min = sessions * state.get("work_min", 25)
        return {"success": True, "result": f"🍅 Today: {sessions} sessions ({total_min} min focused)"}
    
    return {"success": False, "error": f"Unknown operation: {operation}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. HABIT TRACKER
# ═══════════════════════════════════════════════════════════════════════════════

_HABITS_FILE = _STORAGE / "habits.json"

def habit_tracker(operation: str = "list", habit: str = "", note: str = "") -> dict[str, Any]:
    """Track daily habits.
    
    Operations:
        log: Log a habit for today (habit param required)
        list: Show today's habits
        week: Show this week's habit summary
        add: Add a new habit to track
        remove: Remove a habit
    """
    habits = {}
    if _HABITS_FILE.exists():
        try:
            habits = json.loads(_HABITS_FILE.read_text())
        except Exception:
            habits = {}
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    if operation == "log":
        if not habit:
            return {"success": False, "error": "Specify which habit to log"}
        if "entries" not in habits:
            habits["entries"] = {}
        if today not in habits["entries"]:
            habits["entries"][today] = []
        
        entry = {"habit": habit, "time": datetime.now().strftime("%H:%M"), "note": note}
        habits["entries"][today].append(entry)
        _HABITS_FILE.write_text(json.dumps(habits, indent=2))
        
        count = sum(1 for e in habits["entries"][today] if e["habit"] == habit)
        return {"success": True, "result": f"✓ Logged: {habit} ({count}x today)"}
    
    elif operation == "list":
        entries = habits.get("entries", {}).get(today, [])
        if not entries:
            return {"success": True, "result": "No habits logged today yet."}
        lines = [f"Today's habits ({today}):"]
        for e in entries:
            lines.append(f"  ✓ {e['habit']} at {e['time']}" + (f" — {e['note']}" if e.get('note') else ""))
        return {"success": True, "result": "\n".join(lines)}
    
    elif operation == "week":
        lines = ["This week's habits:"]
        for i in range(7):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            day_name = (datetime.now() - timedelta(days=i)).strftime("%a")
            entries = habits.get("entries", {}).get(date, [])
            habit_names = set(e["habit"] for e in entries)
            if entries:
                lines.append(f"  {day_name} {date}: {', '.join(habit_names)} ({len(entries)} total)")
            else:
                lines.append(f"  {day_name} {date}: —")
        return {"success": True, "result": "\n".join(lines)}
    
    elif operation == "add":
        if not habit:
            return {"success": False, "error": "Specify habit name to add"}
        if "tracked" not in habits:
            habits["tracked"] = []
        if habit not in habits["tracked"]:
            habits["tracked"].append(habit)
            _HABITS_FILE.write_text(json.dumps(habits, indent=2))
        return {"success": True, "result": f"Added habit: {habit}\nTracked: {', '.join(habits['tracked'])}"}
    
    elif operation == "remove":
        if "tracked" in habits and habit in habits["tracked"]:
            habits["tracked"].remove(habit)
            _HABITS_FILE.write_text(json.dumps(habits, indent=2))
        return {"success": True, "result": f"Removed habit: {habit}"}
    
    return {"success": False, "error": f"Unknown operation: {operation}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 6. EXPENSE TRACKER
# ═══════════════════════════════════════════════════════════════════════════════

_EXPENSES_FILE = _STORAGE / "expenses.json"

def expense_tracker(operation: str = "summary", amount: float = 0, category: str = "", description: str = "") -> dict[str, Any]:
    """Track expenses.
    
    Operations:
        add: Add an expense (amount + category required)
        summary: Show this month's spending summary
        today: Show today's expenses
        categories: Show spending by category
    """
    expenses = []
    if _EXPENSES_FILE.exists():
        try:
            expenses = json.loads(_EXPENSES_FILE.read_text())
        except Exception:
            expenses = []
    
    today = datetime.now().strftime("%Y-%m-%d")
    this_month = datetime.now().strftime("%Y-%m")
    
    if operation == "add":
        if amount <= 0:
            return {"success": False, "error": "Specify amount > 0"}
        if not category:
            category = "other"
        
        entry = {
            "date": today,
            "amount": amount,
            "category": category.lower(),
            "description": description or category,
            "time": datetime.now().strftime("%H:%M"),
        }
        expenses.append(entry)
        _EXPENSES_FILE.write_text(json.dumps(expenses, indent=2))
        
        # Calculate today's total
        today_total = sum(e["amount"] for e in expenses if e["date"] == today)
        return {"success": True, "result": f"💰 Added: ${amount:.2f} ({category})\nToday's total: ${today_total:.2f}"}
    
    elif operation == "today":
        today_expenses = [e for e in expenses if e["date"] == today]
        if not today_expenses:
            return {"success": True, "result": "No expenses today."}
        total = sum(e["amount"] for e in today_expenses)
        lines = [f"Today's expenses (${total:.2f}):"]
        for e in today_expenses:
            lines.append(f"  ${e['amount']:.2f} — {e['description']} [{e['category']}]")
        return {"success": True, "result": "\n".join(lines)}
    
    elif operation == "summary":
        month_expenses = [e for e in expenses if e["date"].startswith(this_month)]
        if not month_expenses:
            return {"success": True, "result": "No expenses this month."}
        total = sum(e["amount"] for e in month_expenses)
        by_cat = {}
        for e in month_expenses:
            by_cat[e["category"]] = by_cat.get(e["category"], 0) + e["amount"]
        
        lines = [f"📊 {this_month} Summary: ${total:.2f} total"]
        for cat, amt in sorted(by_cat.items(), key=lambda x: x[1], reverse=True):
            pct = (amt / total * 100) if total > 0 else 0
            lines.append(f"  {cat:12s}  ${amt:>8.2f}  ({pct:.0f}%)")
        return {"success": True, "result": "\n".join(lines)}
    
    elif operation == "categories":
        all_cats = set(e["category"] for e in expenses)
        return {"success": True, "result": f"Categories: {', '.join(sorted(all_cats)) or 'none yet'}"}
    
    return {"success": False, "error": f"Unknown operation: {operation}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 7. DAILY PLANNER
# ═══════════════════════════════════════════════════════════════════════════════

_PLANNER_FILE = _STORAGE / "planner.json"

def daily_planner(operation: str = "show", task: str = "", time_slot: str = "", priority: str = "normal") -> dict[str, Any]:
    """Daily planner / schedule manager.
    
    Operations:
        show: Show today's plan
        add: Add a task (task + optional time_slot)
        done: Mark a task as done
        clear: Clear today's plan
        tomorrow: Show/plan for tomorrow
    """
    planner = {}
    if _PLANNER_FILE.exists():
        try:
            planner = json.loads(_PLANNER_FILE.read_text())
        except Exception:
            planner = {}
    
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    target_date = tomorrow if operation == "tomorrow" else today
    
    if operation in ("show", "tomorrow"):
        tasks = planner.get(target_date, [])
        if not tasks:
            day_label = "Today" if target_date == today else "Tomorrow"
            return {"success": True, "result": f"{day_label}'s plan is empty. Add tasks with operation='add'."}
        
        lines = [f"📋 Plan for {target_date}:"]
        for i, t in enumerate(tasks, 1):
            status = "✓" if t.get("done") else "○"
            time_str = f" [{t['time']}]" if t.get("time") else ""
            pri = " ⚡" if t.get("priority") == "high" else ""
            lines.append(f"  {status} {i}. {t['task']}{time_str}{pri}")
        
        done_count = sum(1 for t in tasks if t.get("done"))
        lines.append(f"\n  Progress: {done_count}/{len(tasks)} done")
        return {"success": True, "result": "\n".join(lines)}
    
    elif operation == "add":
        if not task:
            return {"success": False, "error": "Specify task to add"}
        if target_date not in planner:
            planner[target_date] = []
        
        entry = {"task": task, "time": time_slot, "priority": priority, "done": False}
        planner[target_date].append(entry)
        _PLANNER_FILE.write_text(json.dumps(planner, indent=2))
        return {"success": True, "result": f"Added to plan: {task}" + (f" at {time_slot}" if time_slot else "")}
    
    elif operation == "done":
        tasks = planner.get(today, [])
        if not task:
            return {"success": False, "error": "Specify which task to mark done (by number or name)"}
        
        # Try by number
        if task.isdigit():
            idx = int(task) - 1
            if 0 <= idx < len(tasks):
                tasks[idx]["done"] = True
                _PLANNER_FILE.write_text(json.dumps(planner, indent=2))
                return {"success": True, "result": f"✓ Done: {tasks[idx]['task']}"}
        
        # Try by name match
        for t in tasks:
            if task.lower() in t["task"].lower():
                t["done"] = True
                _PLANNER_FILE.write_text(json.dumps(planner, indent=2))
                return {"success": True, "result": f"✓ Done: {t['task']}"}
        
        return {"success": False, "error": f"Task not found: {task}"}
    
    elif operation == "clear":
        planner[today] = []
        _PLANNER_FILE.write_text(json.dumps(planner, indent=2))
        return {"success": True, "result": "Today's plan cleared."}
    
    return {"success": False, "error": f"Unknown operation: {operation}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 8. API TESTER
# ═══════════════════════════════════════════════════════════════════════════════

def api_test(url: str, method: str = "GET", headers: str = "", body: str = "") -> dict[str, Any]:
    """Quick API endpoint tester.
    
    Args:
        url: Full URL to test
        method: GET, POST, PUT, DELETE
        headers: JSON string of headers (optional)
        body: Request body for POST/PUT (optional)
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    
    method = method.upper()
    
    # Parse headers
    req_headers = {"User-Agent": "MiniAI-APITester/1.0", "Accept": "application/json"}
    if headers:
        try:
            extra = json.loads(headers)
            req_headers.update(extra)
        except Exception:
            pass
    
    try:
        data = body.encode() if body else None
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        
        start = time.time()
        with urllib.request.urlopen(req, timeout=15) as resp:
            elapsed = (time.time() - start) * 1000
            status = resp.status
            resp_headers = dict(resp.headers)
            resp_body = resp.read().decode("utf-8", errors="replace")
        
        # Try to pretty-print JSON
        try:
            parsed = json.loads(resp_body)
            resp_body = json.dumps(parsed, indent=2)[:2000]
        except Exception:
            resp_body = resp_body[:2000]
        
        lines = [
            f"✓ {method} {url}",
            f"  Status: {status} ({elapsed:.0f}ms)",
            f"  Content-Type: {resp_headers.get('Content-Type', 'unknown')}",
            f"\nResponse:\n{resp_body}",
        ]
        return {"success": True, "result": "\n".join(lines)}
    
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode()[:500]
        except Exception:
            pass
        return {"success": False, "error": f"HTTP {e.code}: {e.reason}\n{body_text}"}
    except Exception as e:
        return {"success": False, "error": f"Request failed: {e}"}
