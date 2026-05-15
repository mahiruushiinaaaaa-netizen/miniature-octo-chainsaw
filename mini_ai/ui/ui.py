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
    from rich.text import Text
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

def flow(label: str) -> None:
    """Display a dim flow label showing which model/route handled the request."""
    # Try each output method with full exception protection
    if RICH_AVAILABLE:
        for symbol in ("⟡ ", "> ", ""):
            try:
                console.print(f"[{C.muted}]{symbol}{label}[/{C.muted}]")
                return
            except Exception:
                continue
    # Fallback to stdlib print with ASCII-safe encoding
    try:
        print(f"  [{label}]")
    except UnicodeEncodeError:
        try:
            print(f"  [{label.encode('ascii', 'replace').decode('ascii')}]")
        except Exception:
            pass

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
    """Live streaming markdown renderer with reduced flicker."""
    def __init__(self, title: str = "THOUGHTS", border_style: str = C.purple):
        self.text = ""
        self.title = title
        self.border_style = border_style
        self.live = None
        self._live_started = False
        self._last_update = 0
        self._update_interval = 0.05  # Min 50ms between updates

    def update(self, chunk: str, final: bool = False):
        if not RICH_AVAILABLE:
            print(chunk, end="", flush=True)
            return

        self.text += chunk
        
        # Buffer updates to reduce flicker
        import time
        now = time.time()
        should_update = final or (now - self._last_update > self._update_interval)
        
        if not self._live_started:
            # Use a panel for streaming in sequential mode
            self.live = Live(
                Panel(Text(self.text), title=f"[bold {self.border_style}]{self.title}[/bold {self.border_style}]", border_style=self.border_style),
                console=console, refresh_per_second=4, transient=False
            )
            self.live.start()
            self._live_started = True
            self._last_update = now
        elif should_update:
            self.live.update(Panel(
                Markdown(self.text) if final else Text(self.text),
                title=f"[bold {self.border_style}]{self.title}[/bold {self.border_style}]",
                border_style=self.border_style
            ))
            self._last_update = now
        
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

# ─── Live Box UI (Agent Mode) ────────────────────────────────────────────────

class LiveTerminalBox:
    """A standalone live-updating panel for terminal command execution."""
    def __init__(self, command: str):
        self.command = command
        self.output = ""
        self.live = None
        self._last_update = 0

    def __enter__(self):
        if not RICH_AVAILABLE: return self
        self.live = Live(self._render(), console=console, refresh_per_second=4, transient=False)
        self.live.start()
        return self

    def __exit__(self, *args):
        if self.live:
            # Final render with full content
            self.live.update(self._render())
            self.live.stop()

    def append(self, text: str):
        self.output += text
        import time
        now = time.time()
        # Throttle UI updates to 10fps
        if self.live and now - self._last_update > 0.1:
            self.live.update(self._render())
            self._last_update = now

    def _render(self):
        # Keep output window sane
        display_output = self.output
        if len(display_output) > 2000:
            display_output = "... [truncated] ...\n" + display_output[-1800:]
            
        return Panel(
            Text.from_ansi(display_output),
            title=f"[bold {C.green}]TERMINAL EXECUTION[/bold {C.green}]",
            subtitle=f"[dim]{self.command[:80]}[/dim]",
            border_style=C.green
        )

# ─── Real-time thought/terminal display ────────────────────────────────────
_thought_buffer: str = ""
_terminal_buffer: str = ""

def update_agent_thoughts(text: str) -> None:
    """Display agent thinking/reasoning in real-time."""
    global _thought_buffer
    _thought_buffer = text
    if RICH_AVAILABLE and text.strip():
        # Render as a subtle panel - non-live to avoid conflicts with CopixTUI
        console.print(Panel(
            Markdown(text[:2000]),  # Limit length
            title=f"[bold {C.purple}]THINKING[/bold {C.purple}]",
            border_style=C.purple,
            subtitle=f"[dim]{len(text)} chars[/dim]"
        ))
    elif text.strip():
        print(f"\n[THINKING] {text[:200]}...\n")

def update_agent_terminal(text: str) -> None:
    """Display terminal command in real-time."""
    global _terminal_buffer
    _terminal_buffer = text
    if RICH_AVAILABLE and text.strip():
        console.print(Panel(
            Text(text[:2000]),
            title=f"[bold {C.green}]TERMINAL[/bold {C.green}]",
            border_style=C.green
        ))
    elif text.strip():
        print(f"\n[TERMINAL] {text[:200]}...\n")

def append_agent_terminal(text: str) -> None:
    """Append to terminal output."""
    global _terminal_buffer
    _terminal_buffer += text

def get_thought_buffer() -> str:
    """Get current thought buffer for CopixTUI integration."""
    return _thought_buffer

def get_terminal_buffer() -> str:
    """Get current terminal buffer for CopixTUI integration."""
    return _terminal_buffer

def clear_buffers() -> None:
    """Clear thought and terminal buffers."""
    global _thought_buffer, _terminal_buffer
    _thought_buffer = ""
    _terminal_buffer = ""

# Legacy no-ops for compatibility
def start_dual_pane(): return None
def set_agent_meta(step, total, role): pass
def get_agent_layout(): return None