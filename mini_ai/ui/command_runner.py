from __future__ import annotations

import queue
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


class CommandRunnerGUI:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Mini AI Command Runner")
        self.root.geometry("900x600")

        self.process: subprocess.Popen[str] | None = None
        self.queue: queue.Queue[str | None] = queue.Queue()
        self.started = 0.0

        self.cwd_var = tk.StringVar(value=str(Path.cwd()))
        self.command_var = tk.StringVar()

        self.build_ui()
        self.root.after(100, self.drain_queue)

    def build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        cwd_row = ttk.Frame(main)
        cwd_row.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(cwd_row, text="Folder:").pack(side=tk.LEFT)
        ttk.Entry(cwd_row, textvariable=self.cwd_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Button(cwd_row, text="Browse", command=self.browse).pack(side=tk.LEFT)

        cmd_row = ttk.Frame(main)
        cmd_row.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(cmd_row, text="Command:").pack(side=tk.LEFT)
        entry = ttk.Entry(cmd_row, textvariable=self.command_var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        entry.bind("<Return>", lambda _event: self.start())

        self.start_button = ttk.Button(cmd_row, text="Run", command=self.start)
        self.start_button.pack(side=tk.LEFT, padx=(0, 6))

        self.stop_button = ttk.Button(cmd_row, text="Stop", command=self.stop, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(main, textvariable=self.status_var).pack(anchor=tk.W, pady=(0, 6))

        self.output = tk.Text(main, wrap=tk.WORD)
        self.output.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(self.output, command=self.output.yview)
        self.output.configure(yscrollcommand=scrollbar.set)

        self.confirm_row = ttk.Frame(main)
        self.confirm_row.pack(fill=tk.X, pady=(6, 0))

        ttk.Label(self.confirm_row, text="Confirmation:").pack(side=tk.LEFT)
        self.yes_btn = ttk.Button(self.confirm_row, text="Yes (Left)", command=lambda: self.send_input("y\n"), state=tk.DISABLED)
        self.yes_btn.pack(side=tk.LEFT, padx=6)
        self.no_btn = ttk.Button(self.confirm_row, text="No (Right)", command=lambda: self.send_input("n\n"), state=tk.DISABLED)
        self.no_btn.pack(side=tk.LEFT)

        self.root.bind("<Left>", lambda _: self.yes_btn.invoke() if self.process else None)
        self.root.bind("<Right>", lambda _: self.no_btn.invoke() if self.process else None)

    def send_input(self, text: str) -> None:
        if self.process and self.process.poll() is None and self.process.stdin:
            self.process.stdin.write(text)
            self.process.stdin.flush()
            self.append(text)

    def browse(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.cwd_var.get() or str(Path.cwd()))
        if selected:
            self.cwd_var.set(selected)

    def append(self, text: str) -> None:
        self.output.insert(tk.END, text)
        self.output.see(tk.END)

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            messagebox.showinfo("Command running", "A command is already running.")
            return

        command = self.command_var.get().strip()
        cwd = Path(self.cwd_var.get()).expanduser()

        if not command:
            messagebox.showwarning("Missing command", "Enter a command first.")
            return

        try:
            cwd.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Folder error", str(exc))
            return

        self.output.delete("1.0", tk.END)
        self.append(f"$ {command}\n")
        self.append(f"[cwd] {cwd}\n\n")

        self.started = time.time()
        self.status_var.set("Running...")
        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.yes_btn.configure(state=tk.NORMAL)
        self.no_btn.configure(state=tk.NORMAL)

        try:
            self.process = subprocess.Popen(
                command,
                shell=True,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            self.status_var.set("Failed to start.")
            self.append(f"\n[error] {exc}\n")
            self.start_button.configure(state=tk.NORMAL)
            self.stop_button.configure(state=tk.DISABLED)
            return

        threading.Thread(target=self.reader, daemon=True).start()

    def reader(self) -> None:
        assert self.process is not None
        assert self.process.stdout is not None

        for line in self.process.stdout:
            self.queue.put(line)

        code = self.process.wait()
        elapsed = time.time() - self.started
        self.queue.put(f"\n[done] exit code {code}, {elapsed:.1f}s\n")
        self.queue.put(None)

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.append("\n[stopping]\n")

    def drain_queue(self) -> None:
        while True:
            try:
                item = self.queue.get_nowait()
            except queue.Empty:
                break

            if item is None:
                self.status_var.set("Done.")
                self.start_button.configure(state=tk.NORMAL)
                self.stop_button.configure(state=tk.DISABLED)
                self.yes_btn.configure(state=tk.DISABLED)
                self.no_btn.configure(state=tk.DISABLED)
            else:
                self.append(item)

        if self.process and self.process.poll() is None:
            elapsed = time.time() - self.started
            self.status_var.set(f"Running... {elapsed:.0f}s elapsed")

        self.root.after(100, self.drain_queue)

    def run(self) -> None:
        self.root.mainloop()


def main():
    CommandRunnerGUI().run()


if __name__ == "__main__":
    main()
