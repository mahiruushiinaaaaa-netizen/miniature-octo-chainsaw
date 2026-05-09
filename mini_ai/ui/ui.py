"""
ui.py – Premium terminal UI using Rich.
Supports streaming, panels, syntax highlighting, and interactive diffs.
"""
from __future__ import annotations

import os
import difflib
from dataclasses import dataclass
from typing import Any, Optional, Union
from pathlib import Path

try:
    from rich.console import Console, RenderableType
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.live import Live
    from rich.status import Status
    from rich.syntax import Syntax
    from rich.theme import Theme
    from rich.table import Table
    from rich.logging import RichHandler
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# ─── Colors & Theme ───────────────────────────────────────────────────────────
class C:
    purple = "#BD93F9"
    cyan = "#8BE9FD"
    green = "#50FA7B"
    red = "#FF5555"
    yellow = "#F1FA8C"
    muted = "#6272A4"

    # ANSI escape codes for choice_ui and raw terminal operations
    bold = "\033[1m"
    reset = "\033[0m"
    gray = "\033[90m"
    bg_soft = "\033[48;5;236m"
    
    # ANSI colors for raw terminal
    a_green = "\033[32m"
    a_red = "\033[31m"
    a_yellow = "\033[33m"
    a_cyan = "\033[36m"
    a_purple = "\033[35m"

# ─── State ────────────────────────────────────────────────────────────────────
@dataclass
class UIState:
    compact: bool = False
    raw: bool = False

STATE = UIState()
console = Console() if RICH_AVAILABLE else None

def term_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80

# ─── Components ───────────────────────────────────────────────────────────────

def ok(message: str) -> None:
    if RICH_AVAILABLE:
        console.print(f"[bold {C.green}]✓[/bold {C.green}] {message}")
    else:
        print(f"✓ {message}")

def err(message: str) -> None:
    if RICH_AVAILABLE:
        console.print(f"[bold {C.red}]✕[/bold {C.red}] {message}")
    else:
        print(f"✕ {message}")

def warn(message: str) -> None:
    if RICH_AVAILABLE:
        console.print(f"[bold {C.yellow}]![/bold {C.yellow}] {message}")
    else:
        print(f"! {message}")

def status(message: str) -> Union[Optional[Status], Any]:
    """Return a context manager for status updates."""
    if RICH_AVAILABLE:
        return console.status(f"[muted]✦ {message}...[/muted]")
    
    class FakeStatus:
        def __enter__(self):
            print(f"✦ {message}...", end="\r", flush=True)
            return self
        def __exit__(self, *args):
            print(" " * (term_width() - 1) + "\r", end="", flush=True)

    return FakeStatus()

def header(title: str, subtitle: Optional[str] = None) -> None:
    if not RICH_AVAILABLE:
        print(f"\n=== {title} ===")
        if subtitle: print(subtitle)
        return

    text = f"[bold {C.purple}]{title}[/bold {C.purple}]"
    if subtitle:
        text += f" [muted]· {subtitle}[/muted]"
    console.print(Panel(text, border_style=C.purple))

def bubble(label: str, text: str, color: str = C.purple) -> None:
    if not RICH_AVAILABLE:
        print(f"\n[{label}] {text}")
        return
    console.print(f"\n[bold {color}]{label}[/bold {color}]")
    console.print(Markdown(str(text)))
    console.print("")

def panel(label: str, text: str, accent: str = C.cyan) -> None:
    if not RICH_AVAILABLE:
        print(f"\n--- {label} ---\n{text}")
        return
    console.print(Panel(Markdown(str(text)), title=f"[bold {accent}]{label}[/bold {accent}]", border_style=accent))

def ai(text: str) -> None:
    bubble("AI", text)

def task_header(index: int, total: int, role: str, title: str, description: str) -> None:
    """Beautiful header for a specific orchestration task."""
    if not RICH_AVAILABLE:
        print(f"\nTASK {index}/{total} [{role.upper()}] {title}")
        print(description)
        return
    
    table = Table.grid(expand=True)
    table.add_column(style=C.purple, justify="left", width=15)
    table.add_column(style="white")
    
    table.add_row(f"TASK {index}/{total}", f"[bold white]{title}[/bold white]")
    table.add_row(f"ROLE", f"[muted]{role.upper()}[/muted]")
    
    console.print("\n")
    console.print(Panel(
        table,
        subtitle=f"[muted]{description}[/muted]",
        border_style=C.purple,
        padding=(1, 2)
    ))

def environment_table(caps: dict) -> None:
    """Display environment capabilities in a clean table."""
    if not RICH_AVAILABLE:
        print(f"OS: {caps.get('os')} {caps.get('os_release')}")
        return
    
    table = Table(border_style=C.muted, box=None, padding=(0, 2))
    table.add_column("Capability", style=C.cyan)
    table.add_column("Status/Version", style="white")
    
    table.add_row("OS", f"{caps.get('os')} {caps.get('os_release')}")
    
    bins = caps.get("binaries", {})
    for name, version in bins.items():
        if version != "Not found":
            table.add_row(name.capitalize(), version)
            
    console.print(Panel(table, title="[bold]Environment Inspection[/bold]", border_style=C.muted))

def tool_result(tool_name: str, output: str, success: bool = True) -> None:
    if not RICH_AVAILABLE:
        icon = "✓" if success else "✕"
        print(f"\n{icon} {tool_name.upper()} RESULT:\n{output[:500]}")
        return
    
    accent = C.green if success else C.red
    content = output.strip()
    if not content:
        ok(f"{tool_name} completed successfully.")
        return
    
    # Premium rendering: Use Syntax if it looks like code, otherwise just text
    renderable: Any = content
    if any(content.startswith(x) for x in ("{", "[", "import ", "def ", "class ")):
        try:
            renderable = Syntax(content, "python", theme="monokai", background_color="default")
        except: pass

    # Compact output if too long but keep it readable
    if len(content) > 1500:
        content = content[:700] + "\n\n... [intermediate output truncated] ...\n\n" + content[-700:]
        renderable = content
        
    console.print(Panel(
        renderable, 
        title=f"[bold {accent}]{tool_name.upper()} OUTPUT[/bold {accent}]", 
        border_style=accent,
        padding=(0, 1)
    ))

class MarkdownStream:
    """Live streaming markdown renderer."""
    def __init__(self):
        self.text = ""
        self.live = None
        self._live_started = False

    def update(self, chunk: str, final: bool = False):
        if not RICH_AVAILABLE:
            print(chunk, end="", flush=True)
            return

        self.text += chunk
        if not self._live_started:
            self.live = Live(Markdown(self.text), console=console, refresh_per_second=10)
            self.live.start()
            self._live_started = True
        
        self.live.update(Markdown(self.text))
        
        if final:
            if self.live:
                self.live.stop()
            self._live_started = False
            self.text = "" 

def confirm_diff(filepath: str, old_content: str, new_content: str) -> bool:
    """Show a beautiful diff and ask for confirmation."""
    if not RICH_AVAILABLE:
        print(f"\nApply changes to {filepath}? (y/n)")
        return input("> ").lower().startswith("y")

    diff = list(difflib.unified_diff(
        old_content.splitlines(),
        new_content.splitlines(),
        fromfile="original",
        tofile="proposed",
        lineterm=""
    ))
    
    if not diff:
        return True

    diff_text = "\n".join(diff)
    console.print(Panel(
        Syntax(diff_text, "diff", theme="monokai", line_numbers=True),
        title=f"[bold {C.yellow}]Proposed Changes: {filepath}[/bold {C.yellow}]",
        border_style=C.yellow
    ))
    
    ans = console.input(f"[bold {C.cyan}]Apply changes? (y/n) [y]: [/bold {C.cyan}]")
    return not ans or ans.lower().startswith("y")

def user_prompt() -> str:
    return "you › "

def help_hint() -> None:
    if RICH_AVAILABLE:
        console.print(f"[muted]Type naturally. /help commands · /watch · /undo · /test[/muted]")
    else:
        print("Type naturally. /help for commands.")

def set_compact(enabled: bool) -> None:
    STATE.compact = enabled

def set_raw(enabled: bool) -> None:
    STATE.raw = enabled

def enable_terminal() -> None:
    """Enable ANSI support and other terminal features."""
    if os.name == "nt":
        os.system("")

def clear_line() -> None:
    """Clear the current terminal line."""
    if RICH_AVAILABLE:
        console.print("\r", end="")
    else:
        print("\r" + " " * (term_width() - 1) + "\r", end="", flush=True)