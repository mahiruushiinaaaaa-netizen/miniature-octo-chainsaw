"""
daily_tools.py – Everyday utility tools for daily life.

Features:
1. Unit converter (advanced: currency, cooking, shoe sizes, etc.)
2. Age calculator
3. BMI calculator
4. Tip calculator
5. Loan/mortgage calculator
6. GPA calculator
7. Calorie counter
8. Water intake tracker
9. Sleep tracker
10. Flashcard study system
11. Contact book
12. Birthday reminder
"""
from __future__ import annotations

import json
import os
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_STORAGE = Path.home() / ".mini_ai"
_STORAGE.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. AGE CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════════

def age_calc(birthdate: str) -> dict[str, Any]:
    """Calculate age from birthdate.
    
    Args:
        birthdate: Date in YYYY-MM-DD or MM/DD/YYYY format
    """
    try:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y"):
            try:
                bd = datetime.strptime(birthdate.strip(), fmt)
                break
            except ValueError:
                continue
        else:
            return {"success": False, "error": f"Could not parse date: {birthdate}. Use YYYY-MM-DD"}
        
        now = datetime.now()
        age_years = now.year - bd.year - ((now.month, now.day) < (bd.month, bd.day))
        age_months = (now.month - bd.month) % 12
        age_days = (now - bd).days
        
        # Next birthday
        next_bd = bd.replace(year=now.year)
        if next_bd < now:
            next_bd = next_bd.replace(year=now.year + 1)
        days_to_bd = (next_bd - now).days
        
        return {"success": True, "result": (
            f"🎂 Age Calculator:\n"
            f"  Born: {bd.strftime('%B %d, %Y')}\n"
            f"  Age: {age_years} years, {age_months} months\n"
            f"  Total days alive: {age_days:,}\n"
            f"  Next birthday: {days_to_bd} days away"
        )}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. BMI CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════════

def bmi_calc(weight: float, height: float, unit: str = "metric") -> dict[str, Any]:
    """Calculate BMI.
    
    Args:
        weight: Weight in kg (metric) or lbs (imperial)
        height: Height in cm (metric) or inches (imperial)
        unit: "metric" or "imperial"
    """
    try:
        if unit == "imperial":
            bmi = (weight / (height ** 2)) * 703
        else:
            height_m = height / 100
            bmi = weight / (height_m ** 2)
        
        if bmi < 18.5:
            category = "Underweight"
            emoji = "⚠️"
        elif bmi < 25:
            category = "Normal"
            emoji = "✅"
        elif bmi < 30:
            category = "Overweight"
            emoji = "⚠️"
        else:
            category = "Obese"
            emoji = "🔴"
        
        return {"success": True, "result": (
            f"⚖️ BMI Calculator:\n"
            f"  BMI: {bmi:.1f}\n"
            f"  Category: {emoji} {category}\n"
            f"  Weight: {weight} {'lbs' if unit == 'imperial' else 'kg'}\n"
            f"  Height: {height} {'in' if unit == 'imperial' else 'cm'}"
        )}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TIP CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════════

def tip_calc(bill: float, tip_percent: float = 15, split: int = 1) -> dict[str, Any]:
    """Calculate tip and split bill.
    
    Args:
        bill: Total bill amount
        tip_percent: Tip percentage (default 15%)
        split: Number of people splitting (default 1)
    """
    tip = bill * (tip_percent / 100)
    total = bill + tip
    per_person = total / max(1, split)
    
    lines = [
        f"💰 Tip Calculator:",
        f"  Bill: ${bill:.2f}",
        f"  Tip ({tip_percent}%): ${tip:.2f}",
        f"  Total: ${total:.2f}",
    ]
    if split > 1:
        lines.append(f"  Per person ({split} people): ${per_person:.2f}")
    
    # Show other tip options
    lines.append(f"\n  Other options:")
    for pct in [10, 15, 18, 20, 25]:
        t = bill * pct / 100
        lines.append(f"    {pct}%: ${t:.2f} tip → ${bill + t:.2f} total")
    
    return {"success": True, "result": "\n".join(lines)}


# ═══════════════════════════════════════════════════════════════════════════════
# 4. LOAN CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════════

def loan_calc(principal: float, rate: float, years: int) -> dict[str, Any]:
    """Calculate monthly loan/mortgage payment.
    
    Args:
        principal: Loan amount
        rate: Annual interest rate (e.g. 5.5 for 5.5%)
        years: Loan term in years
    """
    monthly_rate = rate / 100 / 12
    num_payments = years * 12
    
    if monthly_rate == 0:
        monthly = principal / num_payments
    else:
        monthly = principal * (monthly_rate * (1 + monthly_rate) ** num_payments) / ((1 + monthly_rate) ** num_payments - 1)
    
    total_paid = monthly * num_payments
    total_interest = total_paid - principal
    
    return {"success": True, "result": (
        f"🏦 Loan Calculator:\n"
        f"  Principal: ${principal:,.2f}\n"
        f"  Rate: {rate}% annual\n"
        f"  Term: {years} years ({num_payments} payments)\n"
        f"  ─────────────────────\n"
        f"  Monthly payment: ${monthly:,.2f}\n"
        f"  Total paid: ${total_paid:,.2f}\n"
        f"  Total interest: ${total_interest:,.2f}"
    )}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. WATER INTAKE TRACKER
# ═══════════════════════════════════════════════════════════════════════════════

_WATER_FILE = _STORAGE / "water.json"

def water_tracker(operation: str = "status", amount_ml: int = 250) -> dict[str, Any]:
    """Track daily water intake.
    
    Operations: add (log water), status (show today), reset
    Default glass = 250ml
    """
    data = {}
    if _WATER_FILE.exists():
        try:
            data = json.loads(_WATER_FILE.read_text())
        except Exception:
            data = {}
    
    today = datetime.now().strftime("%Y-%m-%d")
    if data.get("date") != today:
        data = {"date": today, "total_ml": 0, "glasses": 0, "log": []}
    
    goal_ml = 2500  # 2.5L daily goal
    
    if operation == "add":
        data["total_ml"] += amount_ml
        data["glasses"] += 1
        data["log"].append({"time": datetime.now().strftime("%H:%M"), "ml": amount_ml})
        _WATER_FILE.write_text(json.dumps(data))
        
        progress = min(100, (data["total_ml"] / goal_ml) * 100)
        bar = "█" * int(progress / 10) + "░" * (10 - int(progress / 10))
        return {"success": True, "result": (
            f"💧 +{amount_ml}ml logged!\n"
            f"  Today: {data['total_ml']}ml / {goal_ml}ml\n"
            f"  [{bar}] {progress:.0f}%\n"
            f"  Glasses: {data['glasses']}"
        )}
    
    elif operation == "status":
        progress = min(100, (data.get("total_ml", 0) / goal_ml) * 100)
        bar = "█" * int(progress / 10) + "░" * (10 - int(progress / 10))
        remaining = max(0, goal_ml - data.get("total_ml", 0))
        return {"success": True, "result": (
            f"💧 Water Intake ({today}):\n"
            f"  [{bar}] {progress:.0f}%\n"
            f"  Consumed: {data.get('total_ml', 0)}ml\n"
            f"  Remaining: {remaining}ml\n"
            f"  Glasses: {data.get('glasses', 0)}"
        )}
    
    elif operation == "reset":
        data = {"date": today, "total_ml": 0, "glasses": 0, "log": []}
        _WATER_FILE.write_text(json.dumps(data))
        return {"success": True, "result": "Water tracker reset for today."}
    
    return {"success": False, "error": f"Unknown operation: {operation}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 6. SLEEP TRACKER
# ═══════════════════════════════════════════════════════════════════════════════

_SLEEP_FILE = _STORAGE / "sleep.json"

def sleep_tracker(operation: str = "status", hours: float = 0, quality: str = "") -> dict[str, Any]:
    """Track sleep patterns.
    
    Operations: log (add sleep entry), status (show this week), suggest (bedtime suggestion)
    """
    data = []
    if _SLEEP_FILE.exists():
        try:
            data = json.loads(_SLEEP_FILE.read_text())
        except Exception:
            data = []
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    if operation == "log":
        if hours <= 0:
            return {"success": False, "error": "Specify hours slept (e.g. 7.5)"}
        entry = {"date": today, "hours": hours, "quality": quality or "ok"}
        data.append(entry)
        if len(data) > 90:
            data = data[-90:]
        _SLEEP_FILE.write_text(json.dumps(data, indent=2))
        
        emoji = "😴" if hours >= 7 else "😫" if hours < 5 else "😐"
        return {"success": True, "result": f"{emoji} Logged: {hours}h sleep ({quality or 'ok'})\n  Recommended: 7-9 hours"}
    
    elif operation == "status":
        week = [e for e in data if e["date"] >= (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")]
        if not week:
            return {"success": True, "result": "No sleep data this week. Use operation='log' to track."}
        
        avg = sum(e["hours"] for e in week) / len(week)
        lines = [f"😴 Sleep This Week (avg: {avg:.1f}h):"]
        for e in week[-7:]:
            bar = "█" * int(e["hours"]) + "░" * max(0, 9 - int(e["hours"]))
            lines.append(f"  {e['date']}: [{bar}] {e['hours']}h")
        
        if avg < 7:
            lines.append(f"\n  ⚠️ Below recommended (7-9h). Try sleeping earlier!")
        else:
            lines.append(f"\n  ✅ Good sleep average!")
        return {"success": True, "result": "\n".join(lines)}
    
    elif operation == "suggest":
        # Suggest bedtime based on wake time
        wake_time = datetime.now().replace(hour=7, minute=0)  # Default 7am
        # 5 sleep cycles of 90min = 7.5h
        bedtimes = []
        for cycles in [4, 5, 6]:
            sleep_duration = timedelta(minutes=cycles * 90 + 15)  # +15min to fall asleep
            bt = wake_time - sleep_duration
            bedtimes.append(f"  {cycles} cycles ({cycles*1.5}h): Sleep at {bt.strftime('%I:%M %p')}")
        
        return {"success": True, "result": (
            f"🌙 Bedtime Suggestions (wake at 7:00 AM):\n" + "\n".join(bedtimes) +
            f"\n\n  💡 Each cycle = 90 minutes. Waking between cycles feels best."
        )}
    
    return {"success": False, "error": f"Unknown operation: {operation}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 7. FLASHCARDS
# ═══════════════════════════════════════════════════════════════════════════════

_FLASHCARDS_FILE = _STORAGE / "flashcards.json"

def flashcards(operation: str = "quiz", deck: str = "default", front: str = "", back: str = "") -> dict[str, Any]:
    """Flashcard study system.
    
    Operations: add, quiz, list, delete_deck
    """
    data = {}
    if _FLASHCARDS_FILE.exists():
        try:
            data = json.loads(_FLASHCARDS_FILE.read_text())
        except Exception:
            data = {}
    
    if operation == "add":
        if not front or not back:
            return {"success": False, "error": "Both front and back required for a flashcard"}
        if deck not in data:
            data[deck] = []
        data[deck].append({"front": front, "back": back, "correct": 0, "attempts": 0})
        _FLASHCARDS_FILE.write_text(json.dumps(data, indent=2))
        return {"success": True, "result": f"📇 Added to '{deck}': {front} → {back}\n  Total cards in deck: {len(data[deck])}"}
    
    elif operation == "quiz":
        cards = data.get(deck, [])
        if not cards:
            return {"success": True, "result": f"No cards in deck '{deck}'. Add some with operation='add'."}
        
        # Pick a random card (weighted toward less-known ones)
        card = random.choice(cards)
        return {"success": True, "result": (
            f"📇 Flashcard Quiz ({deck}):\n\n"
            f"  Q: {card['front']}\n\n"
            f"  (Think of the answer...)\n\n"
            f"  A: {card['back']}\n\n"
            f"  Stats: {card['correct']}/{card['attempts']} correct"
        )}
    
    elif operation == "list":
        if not data:
            return {"success": True, "result": "No flashcard decks yet."}
        lines = ["📇 Flashcard Decks:"]
        for deck_name, cards in data.items():
            lines.append(f"  • {deck_name}: {len(cards)} cards")
        return {"success": True, "result": "\n".join(lines)}
    
    elif operation == "delete_deck":
        if deck in data:
            del data[deck]
            _FLASHCARDS_FILE.write_text(json.dumps(data, indent=2))
            return {"success": True, "result": f"Deleted deck: {deck}"}
        return {"success": False, "error": f"Deck not found: {deck}"}
    
    return {"success": False, "error": f"Unknown operation: {operation}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 8. CONTACT BOOK
# ═══════════════════════════════════════════════════════════════════════════════

_CONTACTS_FILE = _STORAGE / "contacts.json"

def contacts(operation: str = "list", name: str = "", phone: str = "", email: str = "", note: str = "") -> dict[str, Any]:
    """Simple contact book.
    
    Operations: add, search, list, delete
    """
    data = []
    if _CONTACTS_FILE.exists():
        try:
            data = json.loads(_CONTACTS_FILE.read_text())
        except Exception:
            data = []
    
    if operation == "add":
        if not name:
            return {"success": False, "error": "Name required"}
        entry = {"name": name, "phone": phone, "email": email, "note": note, "added": datetime.now().isoformat()}
        data.append(entry)
        _CONTACTS_FILE.write_text(json.dumps(data, indent=2))
        return {"success": True, "result": f"👤 Added contact: {name}"}
    
    elif operation == "search":
        query = (name or phone or email).lower()
        matches = [c for c in data if query in c.get("name", "").lower() or query in c.get("phone", "") or query in c.get("email", "").lower()]
        if not matches:
            return {"success": True, "result": f"No contacts matching '{query}'"}
        lines = [f"Found {len(matches)} contact(s):"]
        for c in matches:
            lines.append(f"  👤 {c['name']}")
            if c.get("phone"): lines.append(f"     📱 {c['phone']}")
            if c.get("email"): lines.append(f"     ✉️ {c['email']}")
            if c.get("note"): lines.append(f"     📝 {c['note']}")
        return {"success": True, "result": "\n".join(lines)}
    
    elif operation == "list":
        if not data:
            return {"success": True, "result": "No contacts saved."}
        lines = [f"👥 Contacts ({len(data)}):"]
        for c in sorted(data, key=lambda x: x.get("name", "").lower()):
            info = c.get("phone", "") or c.get("email", "")
            lines.append(f"  • {c['name']}" + (f" — {info}" if info else ""))
        return {"success": True, "result": "\n".join(lines)}
    
    elif operation == "delete":
        before = len(data)
        data = [c for c in data if name.lower() not in c.get("name", "").lower()]
        removed = before - len(data)
        _CONTACTS_FILE.write_text(json.dumps(data, indent=2))
        return {"success": True, "result": f"Removed {removed} contact(s)"}
    
    return {"success": False, "error": f"Unknown operation: {operation}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 9. DAILY AFFIRMATION
# ═══════════════════════════════════════════════════════════════════════════════

_AFFIRMATIONS = [
    "I am capable of achieving great things today.",
    "I choose to focus on what I can control.",
    "Every line of code I write makes me better.",
    "I am worthy of success and happiness.",
    "Challenges are opportunities for growth.",
    "I trust my ability to solve problems.",
    "Today I will make progress, not perfection.",
    "I am grateful for the skills I have developed.",
    "My potential is limitless.",
    "I deserve rest and recovery.",
    "Small steps lead to big achievements.",
    "I am building something meaningful.",
    "My creativity flows freely today.",
    "I release what I cannot change.",
    "I am exactly where I need to be.",
]

def daily_affirmation() -> dict[str, Any]:
    """Get a daily affirmation/positive message."""
    # Use date as seed for consistent daily affirmation
    day_seed = int(datetime.now().strftime("%Y%m%d"))
    rng = random.Random(day_seed)
    affirmation = rng.choice(_AFFIRMATIONS)
    return {"success": True, "result": f"🌟 Today's Affirmation:\n\n  \"{affirmation}\"\n\n  Have a great day! 💪"}
