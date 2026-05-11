"""
mini_ai/ui/gui.py – Full-featured GUI for Mini AI v39.
Dark theme, real-time streaming, settings panel, memory viewer.
Runs the agent in a background thread so the UI never freezes.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font, messagebox, scrolledtext, ttk
from typing import Any

from .ui import RICH_AVAILABLE
from ..core.backend import server_ready, start_server, generate
from ..agents.agent import agent_mode
from ..core.cli import build_config, parse_args
from ..core.memory import PersistentMemory
from ..core.settings import save_settings
from ..core.path_manager import PathManager
from .sandbox_ide import SandboxIDE

# ── Colour palette (dark theme) ────────────────────────────────────────────────
BG       = "#0f1117"     # window background
BG2      = "#1a1d27"     # panel / sidebar
BG3      = "#22263a"     # input area
ACCENT   = "#5b8dee"     # primary accent blue
ACCENT2  = "#3fcf8e"     # secondary accent green
WARN     = "#f2994a"     # warning amber
ERR_COL  = "#eb5757"     # error red
FG       = "#e2e8f0"     # primary text
FG2      = "#94a3b8"     # secondary / dim text
FG3      = "#475569"     # very dim
BUBBLE_AI  = "#1e2640"   # AI message bubble
BUBBLE_USR = "#1a2e1a"   # user message bubble
BORDER   = "#2d3352"     # border colour

FONT_MONO  = ("Consolas", 10)
FONT_BODY  = ("Segoe UI", 10)
FONT_BOLD  = ("Segoe UI", 10, "bold")
FONT_H1    = ("Segoe UI", 13, "bold")
FONT_SMALL = ("Segoe UI", 9)


# ── Tkinter helpers ────────────────────────────────────────────────────────────

def _style_ttk(root: tk.Tk) -> None:
    """Apply dark theme to ttk widgets."""
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", background=BG2, foreground=FG, bordercolor=BORDER,
                    troughcolor=BG, focuscolor=ACCENT, lightcolor=BG2, darkcolor=BG2)
    style.configure("TFrame", background=BG2)
    style.configure("TLabel", background=BG2, foreground=FG)
    style.configure("TButton", background=BG3, foreground=FG, bordercolor=BORDER,
                    relief="flat", padding=(8, 4))
    style.map("TButton",
              background=[("active", ACCENT), ("pressed", "#3d6bbf")],
              foreground=[("active", "#fff")])
    style.configure("Accent.TButton", background=ACCENT, foreground="#fff", padding=(10, 5))
    style.map("Accent.TButton", background=[("active", "#3d6bbf")])
    style.configure("TEntry", fieldbackground=BG3, foreground=FG, bordercolor=BORDER,
                    insertcolor=FG, padding=6)
    style.configure("TScrollbar", background=BG3, troughcolor=BG2, bordercolor=BG2,
                    arrowcolor=FG2)
    style.configure("TNotebook", background=BG, tabmargins=[0, 0, 0, 0])
    style.configure("TNotebook.Tab", background=BG2, foreground=FG2, padding=(12, 6))
    style.map("TNotebook.Tab",
              background=[("selected", BG3)],
              foreground=[("selected", FG)])
    style.configure("TLabelframe", background=BG2, foreground=FG2, bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=BG2, foreground=FG2)
    style.configure("TCombobox", fieldbackground=BG3, foreground=FG, background=BG3,
                    arrowcolor=FG2, bordercolor=BORDER)
    style.configure("TCheckbutton", background=BG2, foreground=FG)
    style.map("TCheckbutton", background=[("active", BG2)])
    style.configure("TScale", background=BG2, troughcolor=BG3)
    style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=BG3)


# ── Main application window ────────────────────────────────────────────────────

class MiniAIApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Mini AI v39")
        self.geometry("1080x720")
        self.minsize(700, 500)
        self.configure(bg=BG)

        # State
        self._busy = False
        self._token_queue: queue.Queue[str | None] = queue.Queue()
        self._config = None
        self._server_proc = None
        self._memory = None
        self._chat_history: list[dict] = []  # [{role, content}]
        self._workspace = Path.cwd()
        self._pm = PathManager(self._workspace)
        self._autopilot = False
        # Command output batching for flicker-free updates
        self._cmd_output_buffer: list[str] = []
        self._cmd_output_pending = False

        _style_ttk(self)
        self._build_layout()
        self._bind_keys()
        self.after(100, self._drain_tokens)
        self.after(200, self._try_load_config)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self):
        # Root pane: sidebar | main
        pane = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg=BG,
                              sashwidth=4, sashrelief="flat")
        pane.pack(fill=tk.BOTH, expand=True)

        # ── Sidebar ──────────────────────────────────────────────────────────
        sidebar = tk.Frame(pane, bg=BG2, width=220)
        sidebar.pack_propagate(False)
        pane.add(sidebar, minsize=160)

        # Logo/title
        logo_frame = tk.Frame(sidebar, bg=BG2)
        logo_frame.pack(fill=tk.X, padx=12, pady=(16, 8))
        tk.Label(logo_frame, text="✦ Mini AI", font=FONT_H1,
                 bg=BG2, fg=ACCENT).pack(side=tk.LEFT)
        tk.Label(logo_frame, text="v39", font=FONT_SMALL,
                 bg=BG2, fg=FG3).pack(side=tk.LEFT, padx=(4, 0), pady=(4, 0))

        # Status indicator
        self._status_dot = tk.Label(sidebar, text="●  Offline",
                                    font=FONT_SMALL, bg=BG2, fg=ERR_COL)
        self._status_dot.pack(anchor=tk.W, padx=14, pady=(0, 12))

        ttk.Separator(sidebar, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=4)

        # Nav buttons
        def nav_btn(text, icon, cmd):
            f = tk.Frame(sidebar, bg=BG2)
            f.pack(fill=tk.X, padx=8, pady=2)
            b = tk.Label(f, text=f"  {icon}  {text}", font=FONT_BODY,
                         bg=BG2, fg=FG2, anchor=tk.W, cursor="hand2", pady=6)
            b.pack(fill=tk.X)
            b.bind("<Button-1>", lambda e, c=cmd: c())
            b.bind("<Enter>", lambda e, w=b: w.configure(bg=BG3, fg=FG))
            b.bind("<Leave>", lambda e, w=b: w.configure(bg=BG2, fg=FG2))
            return b

        nav_btn("Chat", "💬", lambda: self._show_tab("chat"))
        nav_btn("Sandbox IDE", "💻", lambda: self._show_tab("ide"))
        nav_btn("Settings", "⚙", lambda: self._show_tab("settings"))
        nav_btn("Memory", "🧠", lambda: self._show_tab("memory"))
        nav_btn("Commands", "⚡", lambda: self._show_tab("commands"))

        ttk.Separator(sidebar, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=8)

        # Workspace display
        tk.Label(sidebar, text="WORKSPACE", font=("Segoe UI", 8), bg=BG2, fg=FG3).pack(anchor=tk.W, padx=14)
        self._ws_label = tk.Label(sidebar, text=str(self._workspace.name),
                                   font=FONT_SMALL, bg=BG2, fg=FG2, wraplength=180, anchor=tk.W)
        self._ws_label.pack(anchor=tk.W, padx=14, pady=(2, 4))
        change_label = tk.Label(
            sidebar,
            text="Change →",
            font=FONT_SMALL,
            bg=BG2,
            fg=ACCENT,
            cursor="hand2",
        )
        change_label.pack(anchor=tk.W, padx=14)
        change_label.bind("<Button-1>", self._browse_workspace)

        ttk.Separator(sidebar, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=8)

        # Autopilot toggle
        self._autopilot_var = tk.BooleanVar(value=False)
        ap_frame = tk.Frame(sidebar, bg=BG2)
        ap_frame.pack(fill=tk.X, padx=10, pady=4)
        tk.Label(ap_frame, text="Autopilot", font=FONT_BODY, bg=BG2, fg=FG2).pack(side=tk.LEFT)
        ttk.Checkbutton(ap_frame, variable=self._autopilot_var,
                        command=self._toggle_autopilot).pack(side=tk.RIGHT)

        # Model name
        self._model_label = tk.Label(sidebar, text="No model loaded",
                                      font=FONT_SMALL, bg=BG2, fg=FG3,
                                      wraplength=180, anchor=tk.W)
        self._model_label.pack(anchor=tk.W, padx=14, pady=(12, 4))

        # Bottom: clear chat
        tk.Frame(sidebar, bg=BG2).pack(fill=tk.BOTH, expand=True)
        ttk.Button(sidebar, text="Clear Chat", command=self._clear_chat).pack(
            fill=tk.X, padx=10, pady=10)

        # ── Main area (notebook) ──────────────────────────────────────────────
        main = tk.Frame(pane, bg=BG)
        pane.add(main, minsize=400)

        self._notebook = ttk.Notebook(main)
        self._notebook.pack(fill=tk.BOTH, expand=True)

        self._tab_chat = self._build_chat_tab()
        self._tab_ide = self._build_ide_tab()
        self._tab_settings = self._build_settings_tab()
        self._tab_memory = self._build_memory_tab()
        self._tab_commands = self._build_commands_tab()

        self._notebook.add(self._tab_chat, text="  💬 Chat  ")
        self._notebook.add(self._tab_ide, text="  💻 Sandbox IDE  ")
        self._notebook.add(self._tab_settings, text="  ⚙ Settings  ")
        self._notebook.add(self._tab_memory, text="  🧠 Memory  ")
        self._notebook.add(self._tab_commands, text="  ⚡ Run Command  ")

    def _show_tab(self, name: str):
        mapping = {"chat": 0, "ide": 1, "settings": 2, "memory": 3, "commands": 4}
        if name in mapping:
            self._notebook.select(mapping[name])

    # ── Chat tab ──────────────────────────────────────────────────────────────

    def _build_chat_tab(self) -> tk.Frame:
        frame = tk.Frame(self._notebook, bg=BG)

        # Message area
        msg_frame = tk.Frame(frame, bg=BG)
        msg_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        self._chat_text = tk.Text(
            msg_frame, bg=BG, fg=FG, font=FONT_BODY,
            wrap=tk.WORD, state=tk.DISABLED, cursor="arrow",
            padx=20, pady=16, relief="flat", borderwidth=0,
            spacing1=2, spacing2=2, spacing3=8,
            insertbackground=FG,
        )
        self._chat_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(msg_frame, command=self._chat_text.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._chat_text.configure(yscrollcommand=sb.set)

        # Configure text tags
        self._chat_text.tag_configure("user_label", foreground=ACCENT2, font=FONT_BOLD)
        self._chat_text.tag_configure("ai_label", foreground=ACCENT, font=FONT_BOLD)
        self._chat_text.tag_configure("user_msg", foreground=FG, lmargin1=8, lmargin2=8)
        self._chat_text.tag_configure("ai_msg", foreground=FG, lmargin1=8, lmargin2=8)
        self._chat_text.tag_configure("system_msg", foreground=FG3, font=FONT_SMALL,
                                       lmargin1=8, lmargin2=8)
        self._chat_text.tag_configure("error_msg", foreground=ERR_COL, font=FONT_SMALL,
                                       lmargin1=8, lmargin2=8)
        self._chat_text.tag_configure("thinking", foreground=FG3, font=("Segoe UI", 9, "italic"),
                                       lmargin1=8, lmargin2=8)

        # ── Live Command Execution Panel ─────────────────────────────────────
        self._cmd_panel = tk.Frame(frame, bg=BG2, height=200)
        self._cmd_panel.pack(fill=tk.X, padx=0, pady=0)
        self._cmd_panel.pack_propagate(False)
        self._cmd_panel_visible = False

        # Collapsible header
        cmd_header = tk.Frame(self._cmd_panel, bg=BG2)
        cmd_header.pack(fill=tk.X, padx=8, pady=(4, 0))

        self._cmd_status_label = tk.Label(cmd_header, text="⚡ Command: Idle",
                                           font=FONT_SMALL, bg=BG2, fg=FG2, anchor=tk.W)
        self._cmd_status_label.pack(side=tk.LEFT)

        self._cmd_time_label = tk.Label(cmd_header, text="", font=FONT_SMALL, bg=BG2, fg=FG3)
        self._cmd_time_label.pack(side=tk.RIGHT)

        # Command output area
        self._cmd_output_text = scrolledtext.ScrolledText(
            self._cmd_panel, bg=BG, fg=FG, font=FONT_MONO,
            wrap=tk.WORD, relief="flat", padx=8, pady=4,
            height=8, state=tk.DISABLED
        )
        self._cmd_output_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(2, 4))

        # Hide by default
        self._cmd_panel.pack_forget()

        # Progress indicator label (shown during operations)
        self._progress_label = tk.Label(frame, text="", font=FONT_SMALL,
                                        bg=BG, fg=ACCENT, anchor=tk.W)
        self._progress_label.pack(fill=tk.X, padx=12, pady=(2, 0))

        # Separator
        sep = tk.Frame(frame, bg=BORDER, height=1)
        sep.pack(fill=tk.X)

        # Input area
        input_frame = tk.Frame(frame, bg=BG3, pady=10)
        input_frame.pack(fill=tk.X)

        # Progress bar (shows during generation)
        self._progress = ttk.Progressbar(frame, mode="indeterminate",
                                          style="Horizontal.TProgressbar")
        # Not packed by default — shown when busy

        inner = tk.Frame(input_frame, bg=BG3)
        inner.pack(fill=tk.X, padx=12)

        self._input = tk.Text(inner, bg=BG3, fg=FG, font=FONT_BODY,
                               height=3, wrap=tk.WORD, relief="flat",
                               borderwidth=0, insertbackground=FG,
                               padx=8, pady=6)
        self._input.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._input.configure(highlightbackground=BORDER, highlightcolor=ACCENT,
                               highlightthickness=1)

        btn_col = tk.Frame(inner, bg=BG3)
        btn_col.pack(side=tk.RIGHT, padx=(8, 0))

        self._send_btn = ttk.Button(btn_col, text="Send  ↵", style="Accent.TButton",
                                     command=self._on_send, width=10)
        self._send_btn.pack(pady=(0, 4))

        self._stop_btn = ttk.Button(btn_col, text="Stop  ■",
                                     command=self._on_stop, width=10, state=tk.DISABLED)
        self._stop_btn.pack()

        # Hint
        tk.Label(input_frame, text="Shift+Enter for new line  ·  Enter to send",
                 font=FONT_SMALL, bg=BG3, fg=FG3).pack(pady=(4, 0))

        return frame

    # ── Settings tab ──────────────────────────────────────────────────────────

    def _build_settings_tab(self) -> tk.Frame:
        frame = tk.Frame(self._notebook, bg=BG2)
        canvas = tk.Canvas(frame, bg=BG2, highlightthickness=0)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg=BG2)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _resize(e):
            canvas.itemconfig(win, width=e.width)
        canvas.bind("<Configure>", _resize)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        def section(title):
            tk.Label(inner, text=title, font=FONT_H1, bg=BG2, fg=FG).pack(
                anchor=tk.W, padx=20, pady=(20, 6))
            tk.Frame(inner, bg=BORDER, height=1).pack(fill=tk.X, padx=20, pady=(0, 10))

        def row(label, widget_fn, hint=""):
            r = tk.Frame(inner, bg=BG2)
            r.pack(fill=tk.X, padx=20, pady=4)
            tk.Label(r, text=label, font=FONT_BODY, bg=BG2, fg=FG, width=20, anchor=tk.W).pack(side=tk.LEFT)
            w = widget_fn(r)
            w.pack(side=tk.LEFT, padx=(8, 0))
            if hint:
                tk.Label(r, text=hint, font=FONT_SMALL, bg=BG2, fg=FG3).pack(side=tk.LEFT, padx=(8, 0))
            return w

        section("Server / Model")

        self._models_dir_var = tk.StringVar(value=str(Path.home() / ".lmstudio" / "models"))
        def make_dir_entry(parent):
            f = tk.Frame(parent, bg=BG2)
            e = ttk.Entry(f, textvariable=self._models_dir_var, width=36)
            e.pack(side=tk.LEFT)
            ttk.Button(f, text="Browse", command=self._browse_models_dir).pack(side=tk.LEFT, padx=(4, 0))
            return f
        row("Models folder", make_dir_entry)

        self._host_var = tk.StringVar(value="127.0.0.1")
        row("Server host", lambda p: ttk.Entry(p, textvariable=self._host_var, width=20), "")

        self._port_var = tk.StringVar(value="8080")
        row("Server port", lambda p: ttk.Entry(p, textvariable=self._port_var, width=8), "")

        section("Performance")

        self._threads_var = tk.IntVar(value=max(1, min((os.cpu_count() or 2), 4)))
        def make_thread_slider(parent):
            f = tk.Frame(parent, bg=BG2)
            lbl = tk.Label(f, textvariable=self._threads_var, font=FONT_BODY,
                           bg=BG2, fg=ACCENT, width=3)
            lbl.pack(side=tk.LEFT)
            s = ttk.Scale(f, from_=1, to=max(1, (os.cpu_count() or 2)),
                          orient=tk.HORIZONTAL, length=160,
                          variable=self._threads_var, command=lambda v: self._threads_var.set(int(float(v))))
            s.pack(side=tk.LEFT, padx=(4, 0))
            return f
        row("CPU Threads", make_thread_slider, "lower = less heat/lag")

        self._ctx_var = tk.IntVar(value=1024)
        ctx_options = [512, 1024, 2048, 4096]
        def make_ctx_combo(parent):
            c = ttk.Combobox(parent, textvariable=self._ctx_var, values=ctx_options, width=8, state="readonly")
            return c
        row("Context size", make_ctx_combo, "tokens (lower = faster)")

        self._temp_var = tk.DoubleVar(value=0.0)
        def make_temp_slider(parent):
            f = tk.Frame(parent, bg=BG2)
            lbl_v = tk.StringVar(value="0.00")
            lbl = tk.Label(f, textvariable=lbl_v, font=FONT_BODY, bg=BG2, fg=ACCENT, width=5)
            lbl.pack(side=tk.LEFT)
            def upd(v):
                self._temp_var.set(round(float(v), 2))
                lbl_v.set(f"{float(v):.2f}")
            s = ttk.Scale(f, from_=0.0, to=1.5, orient=tk.HORIZONTAL, length=160,
                          variable=self._temp_var, command=upd)
            s.pack(side=tk.LEFT, padx=(4, 0))
            return f
        row("Temperature", make_temp_slider, "0=deterministic")

        self._agent_tokens_var = tk.IntVar(value=128)
        toks_options = [64, 128, 256, 512]
        def make_toks_combo(parent):
            return ttk.Combobox(parent, textvariable=self._agent_tokens_var,
                                values=toks_options, width=8, state="readonly")
        row("Agent max tokens", make_toks_combo, "per step")

        section("Behaviour")

        self._allow_run_var = tk.BooleanVar(value=False)
        row("Allow run_cmd", lambda p: ttk.Checkbutton(p, variable=self._allow_run_var),
            "let agent execute shell commands")

        ttk.Button(inner, text="  Apply & Restart Server  ",
                   style="Accent.TButton", command=self._apply_settings).pack(
            anchor=tk.W, padx=20, pady=(20, 4))
        ttk.Button(inner, text="  Save Settings  ",
                   command=self._save_settings_to_disk).pack(anchor=tk.W, padx=20, pady=(0, 20))

        return frame

    def _build_ide_tab(self) -> tk.Frame:
        """Construct the Sandbox IDE tab."""
        # Note: SandboxIDE requires _pm and _config. 
        # Since _config is loaded asynchronously, we'll handle its injection later or pass it as None.
        self.ide = SandboxIDE(self._notebook, self._config, self._pm)
        return self.ide

    # ── Memory tab ────────────────────────────────────────────────────────────

    def _build_memory_tab(self) -> tk.Frame:
        frame = tk.Frame(self._notebook, bg=BG2)

        top = tk.Frame(frame, bg=BG2)
        top.pack(fill=tk.X, padx=16, pady=10)
        tk.Label(top, text="Persistent Memory", font=FONT_H1, bg=BG2, fg=FG).pack(side=tk.LEFT)
        ttk.Button(top, text="Refresh", command=self._refresh_memory).pack(side=tk.RIGHT)
        ttk.Button(top, text="Clear All", command=self._clear_memory).pack(side=tk.RIGHT, padx=(0, 8))

        self._memory_text = scrolledtext.ScrolledText(
            frame, bg=BG, fg=FG2, font=FONT_MONO,
            wrap=tk.WORD, relief="flat", padx=16, pady=12,
            state=tk.DISABLED,
        )
        self._memory_text.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        return frame

    # ── Commands tab ──────────────────────────────────────────────────────────

    def _build_commands_tab(self) -> tk.Frame:
        frame = tk.Frame(self._notebook, bg=BG2)

        # Command runner
        top = tk.Frame(frame, bg=BG2)
        top.pack(fill=tk.X, padx=16, pady=10)
        tk.Label(top, text="Command Runner", font=FONT_H1, bg=BG2, fg=FG).pack(side=tk.LEFT)

        cwd_f = tk.Frame(frame, bg=BG2)
        cwd_f.pack(fill=tk.X, padx=16, pady=4)
        tk.Label(cwd_f, text="Folder:", font=FONT_BODY, bg=BG2, fg=FG2, width=8, anchor=tk.W).pack(side=tk.LEFT)
        self._cmd_cwd_var = tk.StringVar(value=str(Path.cwd()))
        ttk.Entry(cwd_f, textvariable=self._cmd_cwd_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        ttk.Button(cwd_f, text="Browse", command=self._cmd_browse).pack(side=tk.LEFT, padx=(6, 0))

        cmd_f = tk.Frame(frame, bg=BG2)
        cmd_f.pack(fill=tk.X, padx=16, pady=4)
        tk.Label(cmd_f, text="Command:", font=FONT_BODY, bg=BG2, fg=FG2, width=8, anchor=tk.W).pack(side=tk.LEFT)
        self._cmd_var = tk.StringVar()
        cmd_entry = ttk.Entry(cmd_f, textvariable=self._cmd_var)
        cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        cmd_entry.bind("<Return>", lambda e: self._cmd_run())
        self._cmd_run_btn = ttk.Button(cmd_f, text="Run ▶", style="Accent.TButton", command=self._cmd_run)
        self._cmd_run_btn.pack(side=tk.LEFT, padx=(6, 0))
        self._cmd_stop_btn = ttk.Button(cmd_f, text="Stop ■", command=self._cmd_stop, state=tk.DISABLED)
        self._cmd_stop_btn.pack(side=tk.LEFT, padx=(4, 0))

        self._cmd_status = tk.StringVar(value="Ready.")
        tk.Label(frame, textvariable=self._cmd_status, font=FONT_SMALL, bg=BG2, fg=FG3).pack(
            anchor=tk.W, padx=16)

        self._cmd_output = scrolledtext.ScrolledText(
            frame, bg=BG, fg=FG, font=FONT_MONO,
            wrap=tk.WORD, relief="flat", padx=12, pady=8,
        )
        self._cmd_output.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 4))

        confirm_f = tk.Frame(frame, bg=BG2)
        confirm_f.pack(fill=tk.X, padx=16, pady=(0, 10))
        tk.Label(confirm_f, text="Confirm:", font=FONT_BODY, bg=BG2, fg=FG2).pack(side=tk.LEFT)
        self._yes_btn = ttk.Button(confirm_f, text="Yes (←)", command=lambda: self._cmd_send("y\n"), state=tk.DISABLED)
        self._yes_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._no_btn = ttk.Button(confirm_f, text="No (→)", command=lambda: self._cmd_send("n\n"), state=tk.DISABLED)
        self._no_btn.pack(side=tk.LEFT, padx=(4, 0))

        self.bind("<Left>", lambda e: self._yes_btn.invoke() if self._cmd_proc else None)
        self.bind("<Right>", lambda e: self._no_btn.invoke() if self._cmd_proc else None)

        self._cmd_proc = None
        self._cmd_queue: queue.Queue[str | None] = queue.Queue()
        self.after(100, self._drain_cmd_queue)

        return frame

    # ── Keyboard bindings ─────────────────────────────────────────────────────

    def _bind_keys(self):
        self._input.bind("<Return>", self._on_enter)
        self._input.bind("<Shift-Return>", lambda e: None)  # allow newline

    def _on_enter(self, event):
        if not event.state & 0x1:  # no Shift held
            self._on_send()
            return "break"

    # ── Config loading ────────────────────────────────────────────────────────

    def _try_load_config(self):
        """Try to load config using CLI defaults without blocking."""
        threading.Thread(target=self._load_config_bg, daemon=True).start()

    def _load_config_bg(self):
        try:
            # Use current settings vars
            class FakeArgs:
                model = None
                ui_model = None
                dual_model = False
                choose_model = False
                models_dir = None
                set_models_dir = None
                clear_models_dir = False
                bin = None
                server_bin = None
                threads = self._threads_var.get() if hasattr(self, '_threads_var') else 4
                ctx = self._ctx_var.get() if hasattr(self, '_ctx_var') else 1024
                temp = self._temp_var.get() if hasattr(self, '_temp_var') else 0.0
                seed = None
                timeout = 120
                host = self._host_var.get() if hasattr(self, '_host_var') else "127.0.0.1"
                port = int(self._port_var.get()) if hasattr(self, '_port_var') else 8080
                ui_port = 8081
                allow_run = self._allow_run_var.get() if hasattr(self, '_allow_run_var') else False
                workspace = str(self._workspace)
                agent_tokens = self._agent_tokens_var.get() if hasattr(self, '_agent_tokens_var') else 128

            config = build_config(FakeArgs())
            if not config:
                # Allow app to continue without model - user can change dir and settings
                self._config = None
                self._memory = PersistentMemory()
                self.after(0, lambda: self._set_status("No model found — configure in Settings", warn=True))
                self.after(0, lambda: self._append_system("No model loaded. You can still change workspace and configure settings."))
                return

            self._config = config

            if not server_ready(config.base_url):
                self.after(0, lambda: self._set_status("Starting server...", warn=True))
                proc = start_server(config)
                if proc:
                    self._server_proc = proc
                else:
                    self.after(0, lambda: self._set_status("Server failed to start", error=True))
                    return

            self._memory = PersistentMemory()
            name = config.model.name[:40]
            self.after(0, lambda: self._on_config_loaded(name))

        except Exception as exc:
            msg = str(exc)
            self.after(0, lambda m=msg: self._set_status(f"Load error: {m}", error=True))

    def _on_config_loaded(self, model_name: str):
        self._model_label.configure(text=f"Model: {model_name}", fg=FG2)
        if hasattr(self, 'ide'):
            self.ide.config = self._config
        self._set_status("Ready", ok=True)
        self._append_system("Mini AI ready. Type a message to start.")

    def _apply_settings(self):
        self._append_system("Applying settings and restarting server...")
        if self._server_proc:
            try:
                self._server_proc.terminate()
            except Exception:
                pass
            self._server_proc = None
        self._config = None
        self._set_status("Reloading...", warn=True)
        self.after(500, self._try_load_config)

    def _save_settings_to_disk(self):
        save_settings({
            "models_dir": self._models_dir_var.get(),
            "threads": self._threads_var.get(),
            "ctx": self._ctx_var.get(),
            "temp": self._temp_var.get(),
            "agent_tokens": self._agent_tokens_var.get(),
        })
        self._append_system("Settings saved.")

    # ── Chat logic ────────────────────────────────────────────────────────────

    def _on_send(self):
        if self._busy:
            return
        text = self._input.get("1.0", tk.END).strip()
        if not text:
            return
        # Slash command: toggle autopilot from chat input.
        if text.startswith("/"):
            if self._handle_slash_command(text):
                self._input.delete("1.0", tk.END)
                return
        self._input.delete("1.0", tk.END)
        self._append_user(text)
        self._chat_history.append({"role": "user", "content": text})
        self._start_generation(text)

    def _handle_slash_command(self, command: str) -> bool:
        parts = command.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in {"/autopilot", "/auto"}:
            self._autopilot_var.set(True)
            self._autopilot = True
            self._append_system("Autopilot ON")
            if arg:
                self._append_user(arg)
                self._chat_history.append({"role": "user", "content": arg})
                self._start_generation(arg)
            return True

        if cmd in {"/ask", "/manual"}:
            self._autopilot_var.set(False)
            self._autopilot = False
            self._append_system("Autopilot OFF")
            return True

        if cmd == "/help":
            self._append_system("Commands: /autopilot [task], /ask")
            return True

        return False

    def _on_stop(self):
        self._busy = False
        self._stop_btn.configure(state=tk.DISABLED)
        self._send_btn.configure(state=tk.NORMAL)
        self._progress.stop()
        self._progress.pack_forget()
        self._append_system("[Stopped by user]")

    def _start_generation(self, goal: str):
        if not self._config:
            self._append_error("Server not ready. Check Settings tab.")
            return

        self._busy = True
        self._send_btn.configure(state=tk.DISABLED)
        self._stop_btn.configure(state=tk.NORMAL)
        self._progress.pack(fill=tk.X, padx=0, pady=0, before=self._tab_chat.winfo_children()[-1])
        self._progress.start(12)
        self._set_status("Thinking...", warn=True)
        self._set_progress_label("Thinking...")

        # Start AI label placeholder
        self._append_ai_start()

        threading.Thread(target=self._run_agent_bg, args=(goal,), daemon=True).start()

    def _run_agent_bg(self, goal: str):
        try:
            result = agent_mode(
                self._config,
                goal,
                assume_yes=self._autopilot_var.get(),
                persistent_context=self._memory.context_for(goal) if self._memory else "",
                memory=self._memory,
                on_token=self._on_token_cb,
                on_command_start=self._on_command_start_cb,
                on_command_output=self._on_command_output_cb,
                on_command_end=self._on_command_end_cb,
            )
            if self._memory:
                self._memory.add_event(f"Task: {goal}\nResult: {result[:300]}")
        except Exception as exc:
            result = f"Error: {exc}"
        finally:
            self._token_queue.put(None)  # signal done

    def _on_token_cb(self, token: str):
        """Called from background thread — queue token for UI thread."""
        if self._busy:
            self._token_queue.put(token)

    def _on_command_start_cb(self, cmd: str, cwd: str):
        """Called from background thread when command starts — queue for UI."""
        # Use a tuple to identify this as a command start event
        self._token_queue.put(("cmd_start", cmd, cwd))

    def _on_command_output_cb(self, text: str):
        """Called from background thread with command output — queue for UI."""
        self._token_queue.put(("cmd_output", text))

    def _on_command_end_cb(self, exit_code: int):
        """Called from background thread when command ends — queue for UI."""
        self._token_queue.put(("cmd_end", exit_code))

    def _drain_tokens(self):
        """Drain token queue on UI thread — updates chat text live."""
        try:
            while True:
                token = self._token_queue.get_nowait()
                if token is None:
                    # Done
                    self._on_generation_done()
                elif isinstance(token, tuple):
                    # Command event (cmd_start, cmd_output, cmd_end)
                    event_type = token[0]
                    if event_type == "cmd_start":
                        _, cmd, cwd = token
                        self._show_cmd_panel(cmd, cwd)
                        self._set_progress_label(f"Running: {cmd[:40]}{'...' if len(cmd) > 40 else ''}")
                    elif event_type == "cmd_output":
                        _, text = token
                        self._append_cmd_output(text)
                    elif event_type == "cmd_end":
                        _, exit_code = token
                        self._hide_cmd_panel(exit_code)
                        self._set_progress_label("")
                else:
                    # Regular token
                    self._append_token(token)
        except queue.Empty:
            pass
        self.after(50, self._drain_tokens)

    def _on_generation_done(self):
        self._busy = False
        self._send_btn.configure(state=tk.NORMAL)
        self._stop_btn.configure(state=tk.DISABLED)
        self._progress.stop()
        self._progress.pack_forget()
        self._set_status("Ready", ok=True)
        self._set_progress_label("")
        self._hide_cmd_panel()
        # Finalize AI message
        self._chat_text.configure(state=tk.NORMAL)
        self._chat_text.insert(tk.END, "\n")
        self._chat_text.configure(state=tk.DISABLED)
        self._chat_text.see(tk.END)

    # ── Text helpers ──────────────────────────────────────────────────────────

    def _append_user(self, text: str):
        self._chat_text.configure(state=tk.NORMAL)
        self._chat_text.insert(tk.END, "\n")
        self._chat_text.insert(tk.END, "  You\n", "user_label")
        self._chat_text.insert(tk.END, f"  {text}\n", "user_msg")
        self._chat_text.configure(state=tk.DISABLED)
        self._chat_text.see(tk.END)

    def _append_ai_start(self):
        self._chat_text.configure(state=tk.NORMAL)
        self._chat_text.insert(tk.END, "\n")
        self._chat_text.insert(tk.END, "  Mini AI\n", "ai_label")
        self._chat_text.insert(tk.END, "  ", "ai_msg")
        self._chat_text.configure(state=tk.DISABLED)
        self._chat_text.see(tk.END)
        self._ai_stream_pos = self._chat_text.index(tk.END)

    def _append_token(self, token: str):
        self._chat_text.configure(state=tk.NORMAL)
        # Strip think tags from display
        clean = token.replace("<think>", "").replace("</think>", "")
        self._chat_text.insert(tk.END, clean, "ai_msg")
        self._chat_text.configure(state=tk.DISABLED)
        self._chat_text.see(tk.END)

    def _append_system(self, text: str):
        self._chat_text.configure(state=tk.NORMAL)
        self._chat_text.insert(tk.END, f"\n  ℹ  {text}\n", "system_msg")
        self._chat_text.configure(state=tk.DISABLED)
        self._chat_text.see(tk.END)

    def _append_error(self, text: str):
        self._chat_text.configure(state=tk.NORMAL)
        self._chat_text.insert(tk.END, f"\n  ✕  {text}\n", "error_msg")
        self._chat_text.configure(state=tk.DISABLED)
        self._chat_text.see(tk.END)

    def _clear_chat(self):
        self._chat_text.configure(state=tk.NORMAL)
        self._chat_text.delete("1.0", tk.END)
        self._chat_text.configure(state=tk.DISABLED)
        self._chat_history.clear()
        self._append_system("Chat cleared.")

    # ── Live Command Panel Helpers ───────────────────────────────────────────

    def _show_cmd_panel(self, command: str = "", cwd: str = ""):
        """Show the live command execution panel."""
        self._cmd_panel_visible = True
        # Use idle scheduling to prevent layout thrashing
        self.after_idle(lambda: self._cmd_panel.pack(
            fill=tk.X, padx=0, pady=(4, 0),
            before=self._progress_label.master.winfo_children()[2] if len(self._progress_label.master.winfo_children()) > 2 else None
        ))
        # Batch clear and initial content
        self._cmd_output_buffer = []
        self._cmd_output_pending = False
        self._cmd_output_text.configure(state=tk.NORMAL)
        self._cmd_output_text.delete("1.0", tk.END)
        if command:
            self._cmd_output_text.insert(tk.END, f"$ {command}\n")
            if cwd:
                self._cmd_output_text.insert(tk.END, f"[cwd] {cwd}\n\n")
        self._cmd_output_text.configure(state=tk.DISABLED)
        self._cmd_status_label.configure(text=f"⚡ Running: {command[:50]}{'...' if len(command) > 50 else ''}", fg=ACCENT)
        self._cmd_start_time = time.time()
        self._update_cmd_time()

    def _hide_cmd_panel(self, exit_code: int = 0):
        """Hide the live command execution panel."""
        self._cmd_panel_visible = False
        # Flush any pending output before hiding
        self._flush_cmd_output()
        self._cmd_panel.pack_forget()
        self._cmd_status_label.configure(text="⚡ Command: Idle", fg=FG2)
        self._cmd_time_label.configure(text=f"Exit code: {exit_code}")

    def _append_cmd_output(self, text: str):
        """Append output to the command panel with batching to prevent flicker."""
        self._cmd_output_buffer.append(text)
        if not self._cmd_output_pending:
            self._cmd_output_pending = True
            # Batch updates at 50ms intervals for smoother rendering
            self.after(50, self._flush_cmd_output)

    def _flush_cmd_output(self):
        """Flush batched command output to the text widget."""
        if not self._cmd_output_buffer:
            self._cmd_output_pending = False
            return

        # Concatenate all pending text
        combined = "".join(self._cmd_output_buffer)
        self._cmd_output_buffer = []
        self._cmd_output_pending = False

        # Single configure/insert/see/configure cycle for efficiency
        self._cmd_output_text.configure(state=tk.NORMAL)
        self._cmd_output_text.insert(tk.END, combined)
        # Limit scrollback to prevent memory bloat (keep last 5000 chars)
        content = self._cmd_output_text.get("1.0", tk.END)
        if len(content) > 10000:
            self._cmd_output_text.delete("1.0", f"1.0 + {len(content) - 5000}c")
        self._cmd_output_text.see(tk.END)
        self._cmd_output_text.configure(state=tk.DISABLED)

    def _update_cmd_time(self):
        """Update elapsed time display for running command."""
        if self._cmd_panel_visible and hasattr(self, '_cmd_start_time'):
            elapsed = time.time() - self._cmd_start_time
            self._cmd_time_label.configure(text=f"{elapsed:.1f}s")
            self.after(500, self._update_cmd_time)

    def _set_progress_label(self, text: str):
        """Set the progress indicator label (thinking, reading, running)."""
        if text:
            self._progress_label.configure(text=f"⏳ {text}")
        else:
            self._progress_label.configure(text="")

    # ── Status bar ────────────────────────────────────────────────────────────

    def _set_status(self, msg: str, ok: bool = False, warn: bool = False, error: bool = False):
        col = ACCENT2 if ok else (WARN if warn else (ERR_COL if error else FG2))
        dot = "●  "
        self._status_dot.configure(text=dot + msg, fg=col)

    # ── Memory tab ────────────────────────────────────────────────────────────

    def _refresh_memory(self):
        if not self._memory:
            return
        self._memory_text.configure(state=tk.NORMAL)
        self._memory_text.delete("1.0", tk.END)
        self._memory_text.insert(tk.END, self._memory.display() if hasattr(self._memory, "display")
                                  else json.dumps(self._memory.data, indent=2))
        self._memory_text.configure(state=tk.DISABLED)

    def _clear_memory(self):
        if self._memory and messagebox.askyesno("Clear Memory", "Clear all persistent memory?"):
            self._memory.forget_all()
            self._refresh_memory()
            self._append_system("Memory cleared.")

    # ── Command runner ────────────────────────────────────────────────────────

    def _cmd_browse(self):
        d = filedialog.askdirectory(initialdir=self._cmd_cwd_var.get())
        if d:
            self._cmd_cwd_var.set(d)

    def _cmd_run(self):
        cmd = self._cmd_var.get().strip()
        if not cmd:
            return
        if self._cmd_proc and self._cmd_proc.poll() is None:
            messagebox.showinfo("Running", "A command is already running.")
            return
        cwd = Path(self._cmd_cwd_var.get()).expanduser()
        self._cmd_output.delete("1.0", tk.END)
        self._cmd_status.set(f"Running: {cmd}")
        self._cmd_run_btn.configure(state=tk.DISABLED)
        self._cmd_stop_btn.configure(state=tk.NORMAL)
        self._yes_btn.configure(state=tk.NORMAL)
        self._no_btn.configure(state=tk.NORMAL)
        self._cmd_proc = subprocess.Popen(
            cmd, shell=True, cwd=str(cwd),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE, text=True, bufsize=1,
        )
        threading.Thread(target=self._cmd_read_output, daemon=True).start()

    def _cmd_read_output(self):
        try:
            for line in self._cmd_proc.stdout:
                self._cmd_queue.put(line)
        except Exception:
            pass
        self._cmd_queue.put(None)

    def _drain_cmd_queue(self):
        try:
            while True:
                item = self._cmd_queue.get_nowait()
                if item is None:
                    rc = self._cmd_proc.returncode if self._cmd_proc else "?"
                    self._cmd_status.set(f"Done (exit {rc})")
                    self._cmd_run_btn.configure(state=tk.NORMAL)
                    self._cmd_stop_btn.configure(state=tk.DISABLED)
                    self._yes_btn.configure(state=tk.DISABLED)
                    self._no_btn.configure(state=tk.DISABLED)
                else:
                    self._cmd_output.insert(tk.END, item)
                    self._cmd_output.see(tk.END)
        except queue.Empty:
            pass
        self.after(100, self._drain_cmd_queue)

    def _cmd_stop(self):
        if self._cmd_proc and self._cmd_proc.poll() is None:
            self._cmd_proc.terminate()
            self._cmd_status.set("Stopped.")
        self._cmd_run_btn.configure(state=tk.NORMAL)
        self._cmd_stop_btn.configure(state=tk.DISABLED)

    def _cmd_send(self, text: str):
        if self._cmd_proc and self._cmd_proc.poll() is None and self._cmd_proc.stdin:
            self._cmd_proc.stdin.write(text)
            self._cmd_proc.stdin.flush()
            self._cmd_output.insert(tk.END, text)

    # ── Misc ──────────────────────────────────────────────────────────────────

    def _browse_workspace(self, *args):
        d = filedialog.askdirectory(initialdir=str(self._workspace))
        if d:
            self._workspace = Path(d)
            self._ws_label.configure(text=self._workspace.name)
            self._pm = PathManager(self._workspace)
            if self._config:
                self._config.workspace = self._workspace
            if hasattr(self, 'ide'):
                self.ide.pm = self._pm
                self.ide._refresh_explorer()
            # Try to reload config in case the new workspace has models
            self.after(100, self._try_load_config)

    def _browse_models_dir(self):
        d = filedialog.askdirectory(initialdir=self._models_dir_var.get())
        if d:
            self._models_dir_var.set(d)

    def _toggle_autopilot(self):
        self._autopilot = self._autopilot_var.get()
        label = "Autopilot ON" if self._autopilot else "Autopilot OFF"
        self._append_system(label)

    def on_close(self):
        if hasattr(self, 'ide'):
            self.ide.close()
        if self._server_proc:
            try:
                self._server_proc.terminate()
            except Exception:
                pass
        self.destroy()


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    app = MiniAIApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
