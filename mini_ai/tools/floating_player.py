"""
floating_player.py – Ultra‑light, transparent floating music player.
Spawned by executor when media starts playing.
Runs in its own process, never blocks the CLI.
Optimized for low RAM usage and fluid transparency.
"""
from __future__ import annotations

import sys
import time
import math
import subprocess
import os
import tempfile
import json
from pathlib import Path
from typing import Optional

# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
def main():
    """Called when module is run as __main__."""
    log_file = Path(tempfile.gettempdir()) / "miniai_player_debug.log"
    try:
        title = sys.argv[1] if len(sys.argv) > 1 else "Unknown Track"
        pid_to_watch = int(sys.argv[2]) if len(sys.argv) > 2 else None
        with open(log_file, 'a') as f:
            f.write(f"[{time.ctime()}] Starting player: {title}\n")
        _run_player_window(title, pid_to_watch)
    except Exception as e:
        import traceback
        with open(log_file, 'a') as f:
            f.write(traceback.format_exc() + "\n")

# ----------------------------------------------------------------------
def _run_player_window(title: str, watch_pid: Optional[int] = None):
    try:
        import tkinter as tk
    except ImportError:
        return

    # ---------- Constants (tuned for low RAM) ----------
    BG_COLOR = "#0d0d0d"           
    ACCENT   = "#00ff88"           # Vibrant Mint
    DIM      = "#004422"           # Dark Forest Green (for default button state)
    FG2      = "#00cc66"           # Medium Green
    TEXT     = "#ccffdd"           # Light Minty White
    # ---------- Layout tweaks for Search Bar ----------
    W, H     = 300, 130           # Taller for search bar
    prog_y   = H - 45             # Move progress up
    BTN_Y    = H - 28             # Move buttons down
    SEARCH_Y = 18                 # Search at top
    TITLE_Y  = 40                 # Title below search

    BAR_H    = 2
    BARS     = 16                 # Fewer bars = less canvas objects
    MAX_BAR_H = 18
    BAR_W    = 3
    BAR_GAP  = 2
    MAX_TITLE = 32
    title_offset = 0

    # ---------- State ----------
    state = {
        "playing": True,
        "elapsed": 0.0,
        "duration": 0.0,
        "status": "playing",
        "title": title,
        "autoplay": False,
        "queue": [],
        "show_settings": False,
        "touchable": False,        # Click-through background by default
        "error": None,
        "last_update": time.time()
    }

    # ---------- Helper functions ----------
    def fmt_time(sec: float) -> str:
        s = int(sec)
        return f"{s // 60}:{s % 60:02d}"

    def send_cmd(cmd: str, **kwargs):
        try:
            cmd_file = Path(tempfile.gettempdir()) / "miniai_player_cmd.json"
            data = {"command": cmd}
            data.update(kwargs)
            with open(cmd_file, 'w') as f:
                json.dump(data, f)
        except Exception:
            pass

    def toggle_touchable(e=None):
        state["touchable"] = not state["touchable"]
        if sys.platform == "win32":
            if state["touchable"]:
                root.attributes("-transparentcolor", "") # Disable transparency
                canvas.itemconfig(bg_rect, outline=ACCENT, width=2)
            else:
                root.attributes("-transparentcolor", BG_COLOR) # Enable transparency
                canvas.itemconfig(bg_rect, outline="#004422", width=1)
        _log(f"Touchable: {state['touchable']}")

    root = tk.Tk()
    root.title("")
    root.geometry(f"{W}x{H}+100+100")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.96)

    if sys.platform == "win32":
        root.attributes("-transparentcolor", BG_COLOR)
        root.configure(bg=BG_COLOR)
    else:
        root.configure(bg="#0d0d0d")

    # Make window draggable
    drag_start = [None]
    def on_press(e):
        # Only drag if touchable OR clicking the title/handle
        if state["touchable"] or canvas.find_withtag("current"):
             if not isinstance(e.widget, tk.Entry):
                drag_start[0] = (e.x_root - root.winfo_x(), e.y_root - root.winfo_y())
    def on_drag(e):
        if drag_start[0]:
            dx, dy = drag_start[0]
            root.geometry(f"+{e.x_root - dx}+{e.y_root - dy}")
    root.bind("<ButtonPress-1>", on_press)
    root.bind("<B1-Motion>", on_drag)

    canvas_bg = BG_COLOR if sys.platform == "win32" else "#0d0d0d"
    canvas = tk.Canvas(root, width=W, height=H, bg=canvas_bg, highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    bg_rect = canvas.create_rectangle(0, 0, W-1, H-1, outline="#004422", width=1)

    # Search Bar (Improved Design)
    search_frame = tk.Frame(root, bg="#0a150a", highlightthickness=1, highlightbackground="#004422")
    search_frame.place(x=35, y=10, width=W-70, height=24)
    
    search_icon = tk.Label(search_frame, text="🔍", bg="#0a150a", fg=FG2, font=("Consolas", 8))
    search_icon.pack(side=tk.LEFT, padx=4)

    search_var = tk.StringVar()
    search_entry = tk.Entry(search_frame, textvariable=search_var, bg="#0a150a", fg=FG2,
                             insertbackground=ACCENT, borderwidth=0, font=("Consolas", 9))
    search_entry.insert(0, "Search...")
    search_entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    
    def on_search_focus_in(e):
        if search_var.get() == "Search...":
            search_entry.delete(0, tk.END)
            search_entry.config(fg=TEXT)
    def on_search_focus_out(e):
        if not search_var.get():
            search_entry.insert(0, "Search...")
            search_entry.config(fg=FG2)
            
    search_entry.bind("<FocusIn>", on_search_focus_in)
    search_entry.bind("<FocusOut>", on_search_focus_out)
    
    def on_search(e=None):
        query = search_var.get().strip()
        if query and query != "Search...":
            # If playing, paused or buffering, add to queue instead of stopping current
            if state["status"] in ("playing", "paused", "buffering"):
                send_cmd("enqueue", query=query)
            else:
                send_cmd("play", query=query)
            search_var.set("")
            root.focus()
    search_entry.bind("<Return>", on_search)

    # Close button (×)
    close_btn = canvas.create_text(
        W-14, 22, text="×", fill=DIM, font=("Consolas", 12, "bold"), tags="close"
    )
    canvas.tag_bind("close", "<Button-1>", lambda e: root.destroy())
    
    # Track title (The "Handle" for double-click)
    title_id = canvas.create_text(14, TITLE_Y, text=title, anchor="w",
                                  fill=TEXT, font=("Consolas", 9, "bold"), tags="handle")
    # Bind double-click on title to toggle interactivity
    canvas.tag_bind("handle", "<Double-Button-1>", toggle_touchable)
    
    # Waveform bars - adjusted
    total_bar_w = BARS * (BAR_W + BAR_GAP)
    bar_x0 = (W - total_bar_w) // 2
    bar_y_center = TITLE_Y + 22
    bar_ids = []
    bar_heights = [0.2] * BARS
    for i in range(BARS):
        x = bar_x0 + i * (BAR_W + BAR_GAP)
        bid = canvas.create_rectangle(x, bar_y_center, x + BAR_W, bar_y_center,
                                      fill=ACCENT, outline="", tags="bar")
        bar_ids.append(bid)

    # Progress bar
    canvas.create_rectangle(14, prog_y, W-14, prog_y + BAR_H, fill="#0a150a", outline="")
    prog_fill = canvas.create_rectangle(14, prog_y, 14, prog_y + BAR_H, fill=ACCENT, outline="")
    time_left_id = canvas.create_text(14, prog_y + 7, text="0:00", anchor="w",
                                      fill="#888888", font=("Consolas", 7))
    time_right_id = canvas.create_text(W-14, prog_y + 7, text="∞", anchor="e",
                                       fill="#888888", font=("Consolas", 7))

    # Control buttons
    btn_specs = [
        ("⏮", W//2 - 48, BTN_Y, "prev"),
        ("⏸", W//2 - 14, BTN_Y, "pause"),
        ("⏹", W//2 + 20, BTN_Y, "stop"),
        ("⏭", W//2 + 52, BTN_Y, "next"),
    ]
    btn_ids = {}
    for sym, bx, by, tag in btn_specs:
        bid = canvas.create_text(bx, by, text=sym, fill=DIM,
                                 font=("Segoe UI Symbol", 12), tags=tag)
        btn_ids[tag] = bid

    def btn_hover(tag, entering):
        canvas.itemconfig(btn_ids[tag], fill=ACCENT if entering else DIM)

    for _, _, _, tag in btn_specs:
        canvas.tag_bind(tag, "<Enter>", lambda e, t=tag: btn_hover(t, True))
        canvas.tag_bind(tag, "<Leave>", lambda e, t=tag: btn_hover(t, False))

    canvas.tag_bind("pause", "<Button-1>", lambda e: send_cmd("pause"))
    canvas.tag_bind("stop",  "<Button-1>", lambda e: (send_cmd("stop"), root.after(200, root.destroy)))
    canvas.tag_bind("next",  "<Button-1>", lambda e: send_cmd("skip"))
    canvas.tag_bind("prev",  "<Button-1>", lambda e: send_cmd("seek", position=0)) # Restart for now
    
    # Settings toggle button (⚙)
    settings_btn = canvas.create_text(
        14, 20, text="⚙", fill=DIM, font=("Consolas", 10), tags="settings_toggle"
    )
    def toggle_settings(e):
        state["show_settings"] = not state["show_settings"]
        update_settings_ui()
    
    canvas.tag_bind("settings_toggle", "<Button-1>", toggle_settings)
    canvas.tag_bind("settings_toggle", "<Enter>", lambda e: canvas.itemconfig(settings_btn, fill=ACCENT))
    canvas.tag_bind("settings_toggle", "<Leave>", lambda e: canvas.itemconfig(settings_btn, fill=DIM))

    # Settings Overlay
    settings_bg = canvas.create_rectangle(10, 35, W-10, H-10, fill="#081008", outline="#004422", state="hidden")
    autoplay_lbl = canvas.create_text(25, 55, text="Autoplay (Relevance)", fill=FG2, anchor="w", font=("Consolas", 8), state="hidden")
    autoplay_val = canvas.create_text(W-25, 55, text="OFF", fill=DIM, anchor="e", font=("Consolas", 8, "bold"), state="hidden", tags="ap_toggle")
    
    queue_lbl = canvas.create_text(25, 75, text="Queue: 0 tracks", fill=FG2, anchor="w", font=("Consolas", 8), state="hidden")

    def toggle_autoplay_cmd(e):
        send_cmd("toggle_autoplay")
    
    canvas.tag_bind("ap_toggle", "<Button-1>", toggle_autoplay_cmd)

    def update_settings_ui():
        s = "normal" if state["show_settings"] else "hidden"
        canvas.itemconfig(settings_bg, state=s)
        canvas.itemconfig(autoplay_lbl, state=s)
        canvas.itemconfig(autoplay_val, state=s)
        canvas.itemconfig(queue_lbl, state=s)
        if state["show_settings"]:
            canvas.itemconfig(autoplay_val, text="ON" if state["autoplay"] else "OFF", fill=ACCENT if state["autoplay"] else DIM)
            canvas.itemconfig(queue_lbl, text=f"Queue: {len(state['queue'])} tracks")
            canvas.lift(settings_bg)
            canvas.lift(autoplay_lbl)
            canvas.lift(autoplay_val)
            canvas.lift(queue_lbl)

    # ---------- Background updater (Threaded to prevent I/O lag) ----------
    def state_reader_thread():
        state_file = Path(tempfile.gettempdir()) / "miniai_player_state.json"
        while True:
            try:
                if state_file.exists():
                    with open(state_file, 'r') as f:
                        data = json.load(f)
                    # Update state dict (Python dict updates are thread-safe for simple assignments)
                    state["elapsed"] = data.get("elapsed", state["elapsed"])
                    state["duration"] = data.get("duration", state["duration"])
                    state["status"] = data.get("status", state["status"])
                    state["autoplay"] = data.get("autoplay", state["autoplay"])
                    state["queue"] = data.get("queue", state["queue"])
                    state["playing"] = (state["status"] == "playing")
                    if "title" in data:
                        state["title"] = data["title"]
                    if "error" in data:
                        state["error"] = data["error"]
                    state["last_update"] = time.time()
            except Exception:
                pass
            time.sleep(0.4) # Poll every 400ms in background

    import threading
    thread = threading.Thread(target=state_reader_thread, daemon=True)
    thread.start()

    # Boost process priority for zero lag
    try:
        if sys.platform == "win32":
            import ctypes
            # HIGH_PRIORITY_CLASS = 0x00000080
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00000080)
    except Exception: pass

    def update_ui():
        # Auto‑close only on fatal audio errors
        if state["error"]:
            canvas.itemconfig(title_id, text=f"❌ {state['error']}", fill="#ff5555")
            _log(f"Fatal error: {state['error']}")
            root.after(5000, root.destroy)
            return

        # Update UI elements that change slowly
        canvas.itemconfig(btn_ids["pause"], text="▶" if state["status"] == "paused" else "⏸")
        canvas.itemconfig(time_left_id, text=fmt_time(state["elapsed"]))
        if state["duration"] > 0:
            canvas.itemconfig(time_right_id, text=fmt_time(state["duration"]))
        
        if state["show_settings"]:
            update_settings_ui()
            
        root.after(500, update_ui)

    # ---------- Animation loop (fast, no I/O) ----------
    phase = 0.0
    def animate():
        nonlocal phase, bar_heights, title_offset
        # Compute target heights using deterministic sine waves
        playing = state["playing"]
        status = state["status"]
        if playing:
            phase += 0.2
        elif status == "buffering":
            phase += 0.08
        else:
            phase += 0.02

        # Smoother title scrolling
        display_title = state["title"]
        if status == "buffering":
            display_title = f"⏳ {display_title}"
        title_len = len(display_title)
        if title_len > MAX_TITLE:
            # Update scroll position every ~150ms (3 frames at 50ms)
            if int(phase * 5) % 1 != 0: # Simple way to slow down scrolling compared to animation
                pass 
            title_offset = (int(phase * 2)) % (title_len - MAX_TITLE + 1)
            clipped = display_title[title_offset:title_offset+MAX_TITLE]
        else:
            clipped = display_title
        canvas.itemconfig(title_id, text=clipped)

        # Update bar heights with smoothing
        for i in range(BARS):
            if playing:
                target = 0.3 + 0.6 * (0.5 + 0.5 * math.sin(phase + i * 0.6))
            elif status == "buffering":
                target = 0.2 + 0.1 * math.sin(phase * 4 + i)
            else:
                target = 0.05
            bar_heights[i] = bar_heights[i] * 0.85 + target * 0.15
            h = int(MAX_BAR_H * bar_heights[i])
            x = bar_x0 + i * (BAR_W + BAR_GAP)
            canvas.coords(bar_ids[i], x, bar_y_center - h//2, x + BAR_W, bar_y_center + h//2)
            color = ACCENT if playing else DIM
            canvas.itemconfig(bar_ids[i], fill=color)

        # Progress bar (interpolated from state)
        if state["duration"] > 0:
            frac = min(1.0, state["elapsed"] / state["duration"])
            canvas.coords(prog_fill, 14, prog_y, 14 + frac * (W - 28), prog_y + BAR_H)
        else:
            # No duration → idle animation
            idle = (time.time() * 0.5) % 1.0
            canvas.coords(prog_fill, 14 + idle * (W - 28), prog_y, 14 + idle * (W - 28) + 10, prog_y + BAR_H)

        root.after(50, animate)   # 20 fps – smooth enough, very cheap

    def _log(msg: str):
        try:
            log_file = Path(tempfile.gettempdir()) / "miniai_player_debug.log"
            with open(log_file, 'a') as f:
                f.write(f"[{time.ctime()}] {msg}\n")
        except: pass

    # Start both loops
    root.after(400, update_ui)
    root.after(50, animate)
    root.mainloop()

# ----------------------------------------------------------------------
# Public spawn function (same signature as before)
# ----------------------------------------------------------------------
def spawn_player(title: str, player_pid: Optional[int] = None) -> None:
    """Launch the floating player in a detached subprocess."""
    executable = sys.executable
    if os.name == "nt":
        # Use pythonw.exe to avoid console window
        if executable.endswith("python.exe"):
            executable = executable.replace("python.exe", "pythonw.exe")
        elif not executable.endswith("pythonw.exe"):
            pw = Path(executable).parent / "pythonw.exe"
            if pw.exists():
                executable = str(pw)

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
    except Exception:
        pass

if __name__ == "__main__":
    main()