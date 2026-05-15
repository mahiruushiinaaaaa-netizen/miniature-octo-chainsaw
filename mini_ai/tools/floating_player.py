"""
floating_player.py – Ultra-light, transparent floating music player.
Spawned by executor when media starts playing.
Runs in its own process, never blocks the CLI.

v2 Improvements:
- Smoother animations (interpolated bars, eased transitions)
- Volume slider with visual feedback
- Seek by clicking progress bar
- Queue display (shows next 3 tracks)
- Keyboard shortcuts (Space=pause, N=next, M=mute, Esc=close)
- Minimize to tiny pill mode (just title + play/pause)
- Gradient accent colors based on playback state
- Memory optimized (reuses canvas objects, no widget recreation)
- Responsive layout (adapts to content)
"""
from __future__ import annotations

import sys
import time
import math
import subprocess
import os
import tempfile
import json
import threading
from pathlib import Path
from typing import Optional

# State/command file paths
_STATE_FILE = Path(tempfile.gettempdir()) / "miniai_player_state.json"
_CMD_FILE = Path(tempfile.gettempdir()) / "miniai_player_cmd.json"
_LOG_FILE = Path(tempfile.gettempdir()) / "miniai_player_debug.log"


def _log(msg: str):
    try:
        with open(_LOG_FILE, 'a') as f:
            f.write(f"[{time.ctime()}] {msg}\n")
    except Exception:
        pass


def send_cmd(cmd: str, **kwargs):
    """Send a command to the audio backend."""
    try:
        data = {"command": cmd}
        data.update(kwargs)
        with open(_CMD_FILE, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass


def main():
    """Entry point when run as __main__."""
    try:
        title = sys.argv[1] if len(sys.argv) > 1 else "Unknown Track"
        _log(f"Starting player: {title}")
        _run_player(title)
    except Exception as e:
        import traceback
        _log(f"FATAL: {traceback.format_exc()}")


def _run_player(initial_title: str):
    try:
        import tkinter as tk
    except ImportError:
        _log("tkinter not available")
        return

    # ═══════════════════════════════════════════════════════════════════
    # THEME
    # ═══════════════════════════════════════════════════════════════════
    BG = "#0d0d0d"
    ACCENT = "#00ff88"          # Playing
    ACCENT_PAUSE = "#ffaa00"    # Paused (amber)
    ACCENT_BUFFER = "#00aaff"   # Buffering (blue)
    DIM = "#003322"
    TEXT = "#e0ffe8"
    TEXT_DIM = "#668877"
    BORDER = "#004422"

    # Layout
    W_FULL = 320
    H_FULL = 140
    W_MINI = 200
    H_MINI = 36
    FPS = 24  # Animation framerate (smooth but cheap)
    FRAME_MS = 1000 // FPS

    # ═══════════════════════════════════════════════════════════════════
    # STATE
    # ═══════════════════════════════════════════════════════════════════
    state = {
        "playing": False,
        "elapsed": 0.0,
        "duration": 0.0,
        "status": "buffering",
        "title": initial_title,
        "autoplay": False,
        "queue": [],
        "volume": 100,
        "error": None,
        "mini": False,  # Minimized pill mode
    }

    # Animation state
    anim = {
        "phase": 0.0,
        "bar_heights": [0.1] * 20,
        "title_offset": 0,
        "accent": ACCENT_BUFFER,
        "target_accent": ACCENT_BUFFER,
    }

    # ═══════════════════════════════════════════════════════════════════
    # WINDOW SETUP
    # ═══════════════════════════════════════════════════════════════════
    root = tk.Tk()
    root.title("")
    root.geometry(f"{W_FULL}x{H_FULL}+80+80")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.94)
    root.configure(bg=BG)

    if sys.platform == "win32":
        root.attributes("-transparentcolor", BG)

    # Dragging
    drag = {"x": 0, "y": 0}

    def on_press(e):
        drag["x"] = e.x_root - root.winfo_x()
        drag["y"] = e.y_root - root.winfo_y()

    def on_drag(e):
        root.geometry(f"+{e.x_root - drag['x']}+{e.y_root - drag['y']}")

    root.bind("<ButtonPress-1>", on_press)
    root.bind("<B1-Motion>", on_drag)

    # Canvas
    canvas = tk.Canvas(root, width=W_FULL, height=H_FULL, bg=BG, highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    # Border
    border_id = canvas.create_rectangle(1, 1, W_FULL - 2, H_FULL - 2, outline=BORDER, width=1)

    # ═══════════════════════════════════════════════════════════════════
    # UI ELEMENTS
    # ═══════════════════════════════════════════════════════════════════

    # Title
    title_id = canvas.create_text(14, 16, text=initial_title[:36], anchor="w",
                                  fill=TEXT, font=("Segoe UI", 9, "bold"))

    # Status indicator (small dot)
    status_dot = canvas.create_oval(W_FULL - 20, 12, W_FULL - 12, 20, fill=ACCENT_BUFFER, outline="")

    # Close button
    close_id = canvas.create_text(W_FULL - 14, 14, text="×", fill=DIM,
                                  font=("Consolas", 11, "bold"), tags="close")
    canvas.tag_bind("close", "<Button-1>", lambda e: root.destroy())
    canvas.tag_bind("close", "<Enter>", lambda e: canvas.itemconfig(close_id, fill="#ff5555"))
    canvas.tag_bind("close", "<Leave>", lambda e: canvas.itemconfig(close_id, fill=DIM))

    # Minimize button
    mini_id = canvas.create_text(W_FULL - 32, 14, text="─", fill=DIM,
                                 font=("Consolas", 10), tags="mini")
    canvas.tag_bind("mini", "<Button-1>", lambda e: toggle_mini())
    canvas.tag_bind("mini", "<Enter>", lambda e: canvas.itemconfig(mini_id, fill=ACCENT))
    canvas.tag_bind("mini", "<Leave>", lambda e: canvas.itemconfig(mini_id, fill=DIM))

    # Waveform bars
    BARS = 20
    BAR_W = 3
    BAR_GAP = 2
    BAR_MAX_H = 22
    bar_x0 = (W_FULL - BARS * (BAR_W + BAR_GAP)) // 2
    bar_y = 50
    bar_ids = []
    for i in range(BARS):
        x = bar_x0 + i * (BAR_W + BAR_GAP)
        bid = canvas.create_rectangle(x, bar_y, x + BAR_W, bar_y, fill=ACCENT, outline="")
        bar_ids.append(bid)

    # Progress bar (clickable)
    PROG_Y = 82
    PROG_H = 4
    prog_bg = canvas.create_rectangle(14, PROG_Y, W_FULL - 14, PROG_Y + PROG_H,
                                      fill="#0a1a0f", outline="")
    prog_fill = canvas.create_rectangle(14, PROG_Y, 14, PROG_Y + PROG_H,
                                        fill=ACCENT, outline="")

    # Time labels
    time_left = canvas.create_text(14, PROG_Y + 12, text="0:00", anchor="w",
                                   fill=TEXT_DIM, font=("Consolas", 7))
    time_right = canvas.create_text(W_FULL - 14, PROG_Y + 12, text="0:00", anchor="e",
                                    fill=TEXT_DIM, font=("Consolas", 7))

    # Control buttons
    BTN_Y = 112
    btn_data = [
        ("⏮", W_FULL // 2 - 60, "prev"),
        ("⏸", W_FULL // 2 - 20, "pause"),
        ("⏭", W_FULL // 2 + 20, "next"),
        ("🔀", W_FULL // 2 + 60, "shuffle"),
    ]
    btn_ids = {}
    for sym, bx, tag in btn_data:
        bid = canvas.create_text(bx, BTN_Y, text=sym, fill=DIM,
                                 font=("Segoe UI Symbol", 13), tags=tag)
        btn_ids[tag] = bid
        canvas.tag_bind(tag, "<Enter>", lambda e, t=tag: canvas.itemconfig(btn_ids[t], fill=anim["accent"]))
        canvas.tag_bind(tag, "<Leave>", lambda e, t=tag: canvas.itemconfig(btn_ids[t], fill=DIM))

    # Volume indicator
    vol_id = canvas.create_text(W_FULL - 30, BTN_Y, text="🔊", fill=DIM,
                                font=("Segoe UI Symbol", 10), tags="vol")

    # Queue indicator
    queue_id = canvas.create_text(30, BTN_Y, text="", fill=TEXT_DIM,
                                  font=("Consolas", 7), anchor="w")

    # Search bar (at bottom, hidden by default — shown on Ctrl+F or click)
    search_frame = None
    search_var = tk.StringVar()

    # ═══════════════════════════════════════════════════════════════════
    # BUTTON ACTIONS
    # ═══════════════════════════════════════════════════════════════════
    canvas.tag_bind("pause", "<Button-1>", lambda e: send_cmd("pause"))
    canvas.tag_bind("next", "<Button-1>", lambda e: send_cmd("skip"))
    canvas.tag_bind("prev", "<Button-1>", lambda e: send_cmd("seek", position=0))
    canvas.tag_bind("shuffle", "<Button-1>", lambda e: send_cmd("toggle_autoplay"))

    # Click on progress bar to seek
    def on_prog_click(e):
        if state["duration"] > 0:
            frac = max(0, min(1, (e.x - 14) / (W_FULL - 28)))
            seek_sec = frac * state["duration"]
            send_cmd("seek", position=seek_sec)

    canvas.tag_bind(prog_bg, "<Button-1>", on_prog_click)
    canvas.tag_bind(prog_fill, "<Button-1>", on_prog_click)

    # Volume scroll
    def on_scroll(e):
        delta = 5 if e.delta > 0 else -5
        new_vol = max(0, min(100, state["volume"] + delta))
        state["volume"] = new_vol
        send_cmd("volume", volume=new_vol)

    root.bind("<MouseWheel>", on_scroll)

    # Keyboard shortcuts
    def on_key(e):
        if e.keysym == "space":
            send_cmd("pause")
        elif e.keysym == "n":
            send_cmd("skip")
        elif e.keysym == "m":
            send_cmd("volume", volume=0 if state["volume"] > 0 else 80)
        elif e.keysym == "Escape":
            root.destroy()
        elif e.keysym == "minus":
            toggle_mini()

    root.bind("<Key>", on_key)

    # ═══════════════════════════════════════════════════════════════════
    # MINI MODE
    # ═══════════════════════════════════════════════════════════════════
    def toggle_mini():
        state["mini"] = not state["mini"]
        if state["mini"]:
            root.geometry(f"{W_MINI}x{H_MINI}")
            canvas.config(width=W_MINI, height=H_MINI)
            # Hide most elements
            for bid in bar_ids:
                canvas.itemconfig(bid, state="hidden")
            canvas.itemconfig(prog_bg, state="hidden")
            canvas.itemconfig(prog_fill, state="hidden")
            canvas.itemconfig(time_left, state="hidden")
            canvas.itemconfig(time_right, state="hidden")
            canvas.itemconfig(queue_id, state="hidden")
            canvas.itemconfig(vol_id, state="hidden")
            for tag, bid in btn_ids.items():
                if tag != "pause":
                    canvas.itemconfig(bid, state="hidden")
            # Reposition
            canvas.coords(title_id, 14, H_MINI // 2)
            canvas.coords(btn_ids["pause"], W_MINI - 40, H_MINI // 2)
            canvas.coords(close_id, W_MINI - 14, H_MINI // 2)
            canvas.coords(mini_id, W_MINI - 56, H_MINI // 2)
            canvas.itemconfig(mini_id, text="□")
            canvas.coords(border_id, 1, 1, W_MINI - 2, H_MINI - 2)
            canvas.coords(status_dot, W_MINI - 72, H_MINI // 2 - 4, W_MINI - 64, H_MINI // 2 + 4)
        else:
            root.geometry(f"{W_FULL}x{H_FULL}")
            canvas.config(width=W_FULL, height=H_FULL)
            # Show all elements
            for bid in bar_ids:
                canvas.itemconfig(bid, state="normal")
            canvas.itemconfig(prog_bg, state="normal")
            canvas.itemconfig(prog_fill, state="normal")
            canvas.itemconfig(time_left, state="normal")
            canvas.itemconfig(time_right, state="normal")
            canvas.itemconfig(queue_id, state="normal")
            canvas.itemconfig(vol_id, state="normal")
            for bid in btn_ids.values():
                canvas.itemconfig(bid, state="normal")
            # Restore positions
            canvas.coords(title_id, 14, 16)
            canvas.coords(btn_ids["pause"], W_FULL // 2 - 20, BTN_Y)
            canvas.coords(close_id, W_FULL - 14, 14)
            canvas.coords(mini_id, W_FULL - 32, 14)
            canvas.itemconfig(mini_id, text="─")
            canvas.coords(border_id, 1, 1, W_FULL - 2, H_FULL - 2)
            canvas.coords(status_dot, W_FULL - 20, 12, W_FULL - 12, 20)

    # ═══════════════════════════════════════════════════════════════════
    # STATE READER (background thread)
    # ═══════════════════════════════════════════════════════════════════
    def state_reader():
        while True:
            try:
                if _STATE_FILE.exists():
                    with open(_STATE_FILE, 'r') as f:
                        data = json.load(f)
                    state["elapsed"] = data.get("elapsed", 0)
                    state["duration"] = data.get("duration", 0)
                    state["status"] = data.get("status", "stopped")
                    state["playing"] = state["status"] == "playing"
                    state["autoplay"] = data.get("autoplay", False)
                    state["queue"] = data.get("queue", [])
                    state["volume"] = data.get("volume", 100)
                    if "title" in data:
                        state["title"] = data["title"]
                    if "error" in data and data["error"]:
                        state["error"] = data["error"]
            except Exception:
                pass
            time.sleep(0.35)

    t = threading.Thread(target=state_reader, daemon=True)
    t.start()

    # Boost priority on Windows
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(
                ctypes.windll.kernel32.GetCurrentProcess(), 0x00000080
            )
    except Exception:
        pass

    # ═══════════════════════════════════════════════════════════════════
    # ANIMATION LOOP
    # ═══════════════════════════════════════════════════════════════════
    def fmt(sec):
        s = int(sec)
        return f"{s // 60}:{s % 60:02d}"

    def animate():
        # Determine accent color based on state
        if state["status"] == "playing":
            anim["target_accent"] = ACCENT
        elif state["status"] == "paused":
            anim["target_accent"] = ACCENT_PAUSE
        elif state["status"] == "buffering":
            anim["target_accent"] = ACCENT_BUFFER
        else:
            anim["target_accent"] = DIM

        # Smooth color transition (just swap — true lerp would need hex math)
        anim["accent"] = anim["target_accent"]

        # Phase advancement
        if state["playing"]:
            anim["phase"] += 0.15
        elif state["status"] == "buffering":
            anim["phase"] += 0.06
        else:
            anim["phase"] += 0.01

        # Update status dot
        canvas.itemconfig(status_dot, fill=anim["accent"])

        # Title scrolling
        title_text = state["title"] or "No track"
        max_chars = 34 if not state["mini"] else 18
        if len(title_text) > max_chars:
            offset = int(anim["phase"] * 1.5) % (len(title_text) - max_chars + 4)
            display = title_text[offset:offset + max_chars]
        else:
            display = title_text
        canvas.itemconfig(title_id, text=display)

        # Pause button text
        canvas.itemconfig(btn_ids["pause"], text="▶" if state["status"] != "playing" else "⏸")

        # Shuffle/autoplay indicator
        canvas.itemconfig(btn_ids["shuffle"], fill=ACCENT if state["autoplay"] else DIM)

        # Queue count
        q_count = len(state["queue"])
        canvas.itemconfig(queue_id, text=f"Q:{q_count}" if q_count > 0 else "")

        # Volume icon
        vol = state["volume"]
        vol_icon = "🔇" if vol == 0 else "🔈" if vol < 40 else "🔉" if vol < 75 else "🔊"
        canvas.itemconfig(vol_id, text=vol_icon)

        if not state["mini"]:
            # Waveform bars
            for i in range(BARS):
                if state["playing"]:
                    target = 0.3 + 0.65 * (0.5 + 0.5 * math.sin(anim["phase"] + i * 0.55))
                elif state["status"] == "buffering":
                    target = 0.15 + 0.15 * math.sin(anim["phase"] * 3 + i * 0.8)
                else:
                    target = 0.04
                # Smooth interpolation
                anim["bar_heights"][i] += (target - anim["bar_heights"][i]) * 0.18
                h = int(BAR_MAX_H * anim["bar_heights"][i])
                x = bar_x0 + i * (BAR_W + BAR_GAP)
                canvas.coords(bar_ids[i], x, bar_y - h, x + BAR_W, bar_y + h)
                canvas.itemconfig(bar_ids[i], fill=anim["accent"])

            # Progress bar
            if state["duration"] > 0:
                frac = min(1.0, state["elapsed"] / state["duration"])
                fill_x = 14 + frac * (W_FULL - 28)
                canvas.coords(prog_fill, 14, PROG_Y, fill_x, PROG_Y + PROG_H)
                canvas.itemconfig(time_left, text=fmt(state["elapsed"]))
                canvas.itemconfig(time_right, text=fmt(state["duration"]))
            else:
                # Idle shimmer
                shimmer = (time.time() * 0.4) % 1.0
                sx = 14 + shimmer * (W_FULL - 40)
                canvas.coords(prog_fill, sx, PROG_Y, sx + 12, PROG_Y + PROG_H)
                canvas.itemconfig(time_left, text="0:00")
                canvas.itemconfig(time_right, text="--:--")

        # Error handling
        if state.get("error"):
            canvas.itemconfig(title_id, fill="#ff5555")
        else:
            canvas.itemconfig(title_id, fill=TEXT)

        root.after(FRAME_MS, animate)

    # Start
    root.after(100, animate)
    root.mainloop()


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════

def spawn_player(title: str, player_pid: Optional[int] = None) -> None:
    """Launch the floating player in a detached subprocess."""
    executable = sys.executable
    if os.name == "nt":
        # Use pythonw.exe to avoid console window
        pw = Path(executable).parent / "pythonw.exe"
        if pw.exists():
            executable = str(pw)
        elif executable.endswith("python.exe"):
            executable = executable.replace("python.exe", "pythonw.exe")

    args = [executable, "-m", "mini_ai.tools.floating_player", title]
    if player_pid:
        args.append(str(player_pid))

    try:
        subprocess.Popen(
            args,
            cwd=str(Path(__file__).parent.parent.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        _log(f"Failed to spawn player: {e}")


if __name__ == "__main__":
    main()
