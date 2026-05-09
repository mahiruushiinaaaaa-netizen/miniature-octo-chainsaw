import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
from pathlib import Path
import threading
import queue
import time
import os
from typing import Optional, Dict

from ..core.sandbox import LocalSandbox, VenvSandbox, SandboxProvider
from ..core.sandbox.security import ResourceMonitor, CommandRiskScorer
from ..core.path_manager import PathManager
from .ui import BG, BG2, BG3, ACCENT, ACCENT2, FG, FG2, FG3, ERR_COL, WARN, FONT_BODY, FONT_MONO, FONT_BOLD, FONT_SMALL

class SandboxIDE(tk.Frame):
    """
    A dedicated IDE-like interface for managing and interacting with the Mini-AI Sandbox.
    Features: File explorer, stateful terminal, resource monitor, and multi-provider selection.
    """
    def __init__(self, parent, config, pm: PathManager):
        super().__init__(parent, bg=BG)
        self.config = config
        self.pm = pm
        self.sandbox: Optional[SandboxProvider] = None
        
        # State
        self._current_file: Optional[Path] = None
        self._terminal_queue: queue.Queue[str] = queue.Queue()
        self._is_monitoring = False
        
        self._build_layout()
        self._init_sandbox()
        self._start_monitoring()

    def _build_layout(self):
        # Top toolbar
        toolbar = tk.Frame(self, bg=BG2, height=40)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        
        tk.Label(toolbar, text="Sandbox Type:", font=FONT_SMALL, bg=BG2, fg=FG2).pack(side=tk.LEFT, padx=(10, 5))
        self.sb_type_var = tk.StringVar(value="local")
        sb_combo = ttk.Combobox(toolbar, textvariable=self.sb_type_var, values=["local", "venv", "docker"], width=10, state="readonly")
        sb_combo.pack(side=tk.LEFT, padx=5)
        sb_combo.bind("<<ComboboxSelected>>", self._on_sandbox_change)
        
        ttk.Button(toolbar, text="↻ Refresh Explorer", command=self._refresh_explorer).pack(side=tk.LEFT, padx=10)
        self.status_label = tk.Label(toolbar, text="Status: Ready", font=FONT_SMALL, bg=BG2, fg=ACCENT2)
        self.status_label.pack(side=tk.RIGHT, padx=10)

        # Main horizontal pane
        self.main_pane = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg=BG, sashwidth=4, sashrelief="flat")
        self.main_pane.pack(fill=tk.BOTH, expand=True)

        # 1. Left Sidebar: File Explorer
        explorer_frame = tk.Frame(self.main_pane, bg=BG2, width=200)
        self.main_pane.add(explorer_frame, minsize=150)
        
        tk.Label(explorer_frame, text="EXPLORER", font=FONT_SMALL, bg=BG2, fg=FG3).pack(anchor=tk.W, padx=10, pady=5)
        self.tree = ttk.Treeview(explorer_frame, show="tree", selectmode="browse")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.tree.bind("<Double-1>", self._on_tree_double_click)

        # 2. Center & Bottom: Editor and Terminal
        center_pane = tk.PanedWindow(self.main_pane, orient=tk.VERTICAL, bg=BG, sashwidth=4, sashrelief="flat")
        self.main_pane.add(center_pane, minsize=400)

        # Editor
        editor_frame = tk.Frame(center_pane, bg=BG)
        center_pane.add(editor_frame, minsize=200)
        
        editor_header = tk.Frame(editor_frame, bg=BG3, height=30)
        editor_header.pack(side=tk.TOP, fill=tk.X)
        self.file_label = tk.Label(editor_header, text="No file open", font=FONT_SMALL, bg=BG3, fg=FG2)
        self.file_label.pack(side=tk.LEFT, padx=10)
        
        self.save_btn = ttk.Button(editor_header, text="Save", command=self._save_current_file, state=tk.DISABLED)
        self.save_btn.pack(side=tk.RIGHT, padx=5)

        self.editor = scrolledtext.ScrolledText(editor_frame, bg=BG, fg=FG, font=FONT_MONO, undo=True, relief="flat")
        self.editor.pack(fill=tk.BOTH, expand=True)

        # Terminal
        terminal_frame = tk.Frame(center_pane, bg=BG)
        center_pane.add(terminal_frame, minsize=150)
        
        tk.Label(terminal_frame, text="TERMINAL", font=FONT_SMALL, bg=BG2, fg=FG3).pack(side=tk.TOP, fill=tk.X)
        
        self.terminal_output = scrolledtext.ScrolledText(terminal_frame, bg="#000000", fg="#00FF00", font=FONT_MONO, relief="flat", padx=10, pady=10)
        self.terminal_output.pack(fill=tk.BOTH, expand=True)
        self.terminal_output.configure(state=tk.DISABLED)

        terminal_input_frame = tk.Frame(terminal_frame, bg="#000000")
        terminal_input_frame.pack(side=tk.BOTTOM, fill=tk.X)
        tk.Label(terminal_input_frame, text="> ", bg="#000000", fg="#00FF00", font=FONT_MONO).pack(side=tk.LEFT)
        self.terminal_input = tk.Entry(terminal_input_frame, bg="#000000", fg="#FFFFFF", font=FONT_MONO, insertbackground="#FFFFFF", relief="flat")
        self.terminal_input.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.terminal_input.bind("<Return>", self._on_terminal_return)

        # 3. Right Sidebar: Info & Resource usage
        info_frame = tk.Frame(self.main_pane, bg=BG2, width=200)
        self.main_pane.add(info_frame, minsize=150)
        
        tk.Label(info_frame, text="RESOURCES", font=FONT_SMALL, bg=BG2, fg=FG3).pack(anchor=tk.W, padx=10, pady=5)
        
        self.cpu_label = tk.Label(info_frame, text="CPU: 0.0%", font=FONT_BODY, bg=BG2, fg=FG2)
        self.cpu_label.pack(anchor=tk.W, padx=15)
        
        self.mem_label = tk.Label(info_frame, text="MEM: 0.0 MB", font=FONT_BODY, bg=BG2, fg=FG2)
        self.mem_label.pack(anchor=tk.W, padx=15)
        
        tk.Label(info_frame, text="SANDBOX INFO", font=FONT_SMALL, bg=BG2, fg=FG3).pack(anchor=tk.W, padx=10, pady=(20, 5))
        self.cwd_label = tk.Label(info_frame, text="CWD: ...", font=FONT_SMALL, bg=BG2, fg=FG3, wraplength=180, justify=tk.LEFT)
        self.cwd_label.pack(anchor=tk.W, padx=15)

    def _init_sandbox(self):
        sb_type = self.sb_type_var.get()
        if sb_type == "venv":
            self.sandbox = VenvSandbox(self.pm)
        else:
            self.sandbox = LocalSandbox(self.pm)
        
        self._refresh_explorer()
        self._update_cwd_label()
        self._append_terminal(f"Initialized {sb_type} sandbox.\n")

    def _on_sandbox_change(self, event=None):
        if self.sandbox:
            self.sandbox.close()
        self._init_sandbox()

    def _refresh_explorer(self):
        # Clear tree
        for i in self.tree.get_children():
            self.tree.delete(i)
        
        root_path = self.pm.effective_root
        self._populate_tree("", root_path)

    def _populate_tree(self, parent_node, path: Path):
        try:
            items = sorted(list(path.iterdir()), key=lambda x: (not x.is_dir(), x.name.lower()))
            for item in items:
                if item.name.startswith(".") and item.name != ".gitignore":
                    continue
                if item.name == "__pycache__":
                    continue
                
                node_id = str(item.absolute())
                text = item.name + ("/" if item.is_dir() else "")
                self.tree.insert(parent_node, "end", iid=node_id, text=text, open=False)
                
                if item.is_dir():
                    # Just add a dummy child to show the '+' sign if needed, 
                    # or populate lazily. For now, let's do it simply.
                    pass 
        except Exception:
            pass

    def _on_tree_double_click(self, event):
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return
        
        path = Path(item_id)
        if path.is_file():
            self._open_file(path)
        elif path.is_dir():
            # Toggle expand
            if self.tree.item(item_id, "open"):
                self.tree.item(item_id, open=False)
            else:
                # Populate on demand if empty
                if not self.tree.get_children(item_id):
                    self._populate_tree(item_id, path)
                self.tree.item(item_id, open=True)

    def _open_file(self, path: Path):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            self.editor.delete("1.0", tk.END)
            self.editor.insert("1.0", content)
            self._current_file = path
            self.file_label.configure(text=path.name, fg=FG)
            self.save_btn.configure(state=tk.NORMAL)
        except Exception as e:
            messagebox.showerror("Error", f"Could not open file: {e}")

    def _save_current_file(self):
        if not self._current_file:
            return
        try:
            content = self.editor.get("1.0", tk.END)
            self._current_file.write_text(content, encoding="utf-8")
            self.status_label.configure(text=f"Status: Saved {self._current_file.name}", fg=ACCENT2)
            self.after(2000, lambda: self.status_label.configure(text="Status: Ready", fg=ACCENT2))
        except Exception as e:
            messagebox.showerror("Error", f"Could not save file: {e}")

    def _on_terminal_return(self, event):
        cmd = self.terminal_input.get().strip()
        self.terminal_input.delete(0, tk.END)
        if not cmd:
            return
        
        self._append_terminal(f"> {cmd}\n")
        threading.Thread(target=self._run_cmd_bg, args=(cmd,), daemon=True).start()

    def _run_cmd_bg(self, cmd: str):
        if not self.sandbox:
            self._terminal_queue.put("Error: Sandbox not initialized.\n")
            return
        
        res = self.sandbox.execute(cmd)
        self._terminal_queue.put(res.output + "\n")
        self.after(0, self._update_cwd_label)

    def _append_terminal(self, text: str):
        self.terminal_output.configure(state=tk.NORMAL)
        self.terminal_output.insert(tk.END, text)
        self.terminal_output.see(tk.END)
        self.terminal_output.configure(state=tk.DISABLED)

    def _update_cwd_label(self):
        if self.sandbox:
            cwd = self.sandbox.cwd
            self.cwd_label.configure(text=f"CWD: {cwd}")

    def _start_monitoring(self):
        self._is_monitoring = True
        threading.Thread(target=self._monitor_loop, daemon=True).start()
        self.after(100, self._drain_terminal_queue)

    def _monitor_loop(self):
        while self._is_monitoring:
            if self.sandbox and hasattr(self.sandbox, "_session") and self.sandbox._session:
                pid = self.sandbox._session._process.pid
                monitor = ResourceMonitor(pid)
                usage = monitor.get_usage()
                self.after(0, lambda u=usage: self._update_resource_labels(u))
            time.sleep(2)

    def _update_resource_labels(self, usage):
        self.cpu_label.configure(text=f"CPU: {usage['cpu_percent']:.1f}%")
        self.mem_label.configure(text=f"MEM: {usage['memory_mb']:.1f} MB")

    def _drain_terminal_queue(self):
        try:
            while True:
                text = self._terminal_queue.get_nowait()
                self._append_terminal(text)
        except queue.Empty:
            pass
        self.after(100, self._drain_terminal_queue)

    def close(self):
        self._is_monitoring = False
        if self.sandbox:
            self.sandbox.close()
