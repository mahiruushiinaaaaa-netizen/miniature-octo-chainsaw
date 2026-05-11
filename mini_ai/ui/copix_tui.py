"""
copix_tui.py – Copilot/Codex-inspired Terminal UI for Mini AI.

A minimalist, professional "tech-noir" interface with:
- Slim header with model status
- Elegant prompt with ❯ symbol
- Markdown rendering with syntax highlighting
- Subtle generation spinner
- Muted metadata footer
- Auto-dimming of previous messages

Color Palette:
- Primary: #0078d4 (Microsoft Blue)
- Accent: #a371f7 (Copilot Purple)
- Dark background with subtle grays
"""
from __future__ import annotations

import time
import re
from typing import Optional, Iterator, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime

try:
    from rich.console import Console, Group, RenderableType
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.syntax import Syntax
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.text import Text
    from rich.layout import Layout
    from rich.align import Align
    from rich.rule import Rule
    from rich.style import Style
    from rich.theme import Theme
    from rich.padding import Padding
    from rich.progress import Progress, SpinnerColumn, TextColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("Warning: rich library required for CopixTUI")


# ─── Terminal Capability Detection ────────────────────────────────────────────
import os
import sys

def _detect_terminal_capabilities():
    """Detect terminal capabilities for proper fallback handling."""
    caps = {
        "unicode": True,
        "colors": True,
        "box_drawing": True,
        "is_legacy_cmd": False,
    }
    
    # Windows detection
    if sys.platform == "win32":
        # Check if running in Windows Terminal (modern)
        in_wt = "WT_SESSION" in os.environ
        in_vscode = "TERM_PROGRAM" in os.environ or os.environ.get("TERM") == "xterm-256color"
        
        # Check if it's legacy cmd.exe (not Windows Terminal, not VS Code, not ConEmu, etc)
        if not in_wt and not in_vscode and not os.environ.get("ANSICON"):
            # Likely legacy cmd.exe or PowerShell console host
            caps["unicode"] = False
            caps["colors"] = False  # cmd has limited ANSI support
            caps["box_drawing"] = False
            caps["is_legacy_cmd"] = True
    
    return caps

TERMINAL_CAPS = _detect_terminal_capabilities()


# ─── ASCII Fallbacks for Legacy Terminals ─────────────────────────────────────
class _Symbols:
    """Symbol set that adapts to terminal capabilities."""
    
    @classmethod
    def prompt(cls):
        return ">" if TERMINAL_CAPS["is_legacy_cmd"] else "❯"
    
    @classmethod
    def live_indicator(cls):
        return "*" if TERMINAL_CAPS["is_legacy_cmd"] else "●"
    
    @classmethod
    def model_indicator(cls):
        return ">" if TERMINAL_CAPS["is_legacy_cmd"] else "◉"
    
    @classmethod
    def header_top(cls, width: int) -> str:
        if TERMINAL_CAPS["is_legacy_cmd"]:
            return "+" + "-" * (width - 2) + "+"
        return "╭" + "─" * (width - 2) + "╮"
    
    @classmethod
    def header_bottom(cls, width: int) -> str:
        if TERMINAL_CAPS["is_legacy_cmd"]:
            return "+" + "-" * (width - 2) + "+"
        return "╰" + "─" * (width - 2) + "╯"
    
    @classmethod
    def success(cls):
        return "OK" if TERMINAL_CAPS["is_legacy_cmd"] else "✓"
    
    @classmethod
    def bullet(cls):
        return "*" if TERMINAL_CAPS["is_legacy_cmd"] else "·"


# ─── Color Palette ────────────────────────────────────────────────────────────
class CopixColors:
    """Copilot/Codex inspired color palette."""
    # Primary colors
    MS_BLUE = "#0078d4"      # Microsoft Blue
    COPILOT_PURPLE = "#a371f7"  # Copilot Purple
    
    # Dark theme
    BG_DARK = "#0d1117"      # GitHub dark bg
    BG_PANEL = "#161b22"     # Slightly lighter panel bg
    BORDER = "#30363d"       # Subtle borders
    
    # Text colors
    TEXT_PRIMARY = "#c9d1d9"     # Main text
    TEXT_SECONDARY = "#8b949e"  # Muted/dim text
    TEXT_DIM = "#6e7681"        # Very dim (previous messages)
    
    # Accents
    SUCCESS = "#3fb950"    # Green
    WARNING = "#d29922"    # Yellow/orange
    ERROR = "#f85149"      # Red
    
    # Prompt
    PROMPT_BLUE = "#58a6ff"  # Cyan-blue for prompt


# ─── Theme Configuration ─────────────────────────────────────────────────────
COPIX_THEME = Theme({
    "info": f"bold {CopixColors.MS_BLUE}",
    "success": f"bold {CopixColors.SUCCESS}",
    "warning": f"bold {CopixColors.WARNING}",
    "error": f"bold {CopixColors.ERROR}",
    "muted": CopixColors.TEXT_SECONDARY,
    "dim": CopixColors.TEXT_DIM,
    "prompt": f"bold {CopixColors.PROMPT_BLUE}",
    "code": CopixColors.COPILOT_PURPLE,
})


# ─── Message Container ───────────────────────────────────────────────────────
@dataclass
class Message:
    """A single message in the conversation."""
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_current: bool = False


# ─── Copix TUI Manager ─────────────────────────────────────────────────────────
class CopixTUI:
    """
    Copilot/Codex-inspired Terminal UI Manager.
    
    Handles the complete UI lifecycle:
    - Header with model status
    - Conversation display with auto-dimming
    - Input handling with elegant prompt
    - Generation state with spinner
    - Footer with technical metadata
    """
    
    def __init__(
        self,
        model_name: str = "Qwen 3",
        console: Optional[Console] = None,
        max_history: int = 50
    ):
        if not RICH_AVAILABLE:
            raise RuntimeError("rich library is required for CopixTUI")
        
        self.model_name = model_name
        self.console = console or Console(
            theme=COPIX_THEME,
            color_system="truecolor",
            width=120,
            height=40
        )
        
        self.messages: List[Message] = []
        self.max_history = max_history
        self.current_generation: Optional[Live] = None
        self._last_metadata: Dict[str, Any] = {}
        
        # UI state
        self._header_height = 3
        self._footer_height = 2
        
    def _maybe_panel(self, content: RenderableType, **kwargs) -> RenderableType:
        """Return Panel for modern terminals, plain text for legacy cmd.exe."""
        if TERMINAL_CAPS["is_legacy_cmd"]:
            # For cmd.exe, just return the content without panel borders
            if isinstance(content, Text):
                return content
            return Text(str(content))
        return Panel(content, **kwargs)
    
    # ─── Header ─────────────────────────────────────────────────────────────────
    def _render_header(self) -> RenderableType:
        """Render the slim top header bar."""
        # Model name with styling
        model_text = Text()
        model_text.append(_Symbols.model_indicator() + " ", style=f"bold {CopixColors.SUCCESS}")  # Live indicator
        model_text.append(self.model_name, style=f"bold {CopixColors.TEXT_PRIMARY}")
        
        # Status indicator
        status = Text(f"  {_Symbols.live_indicator()} LIVE", style=f"bold {CopixColors.SUCCESS}")
        
        # Combine in header layout
        header_content = Text()
        header_content.append("  ")  # Left padding
        header_content.append(model_text)
        header_content.append(status)
        
        # For cmd.exe, render simple line instead of Panel
        if TERMINAL_CAPS["is_legacy_cmd"]:
            return header_content
        
        return Panel(
            header_content,
            border_style=CopixColors.BORDER,
            padding=(0, 1),
            height=self._header_height
        )
    
    # ─── Footer ─────────────────────────────────────────────────────────────────
    def _render_footer(self) -> RenderableType:
        """Render the technical metadata footer."""
        if not self._last_metadata:
            footer_text = Text("  Ready", style=CopixColors.TEXT_DIM)
        else:
            # Format metadata
            duration = self._last_metadata.get("duration_ms", 0)
            tokens_sec = self._last_metadata.get("tokens_per_sec", 0)
            length = self._last_metadata.get("content_length", 0)
            
            footer_text = Text()
            footer_text.append(f"  {_Symbols.success()} ", style=CopixColors.SUCCESS)
            footer_text.append(f"{duration/1000:.2f}s", style=CopixColors.TEXT_SECONDARY)
            footer_text.append(f" {_Symbols.bullet()} ", style=CopixColors.TEXT_DIM)
            footer_text.append(f"{tokens_sec:.1f} tok/s", style=CopixColors.TEXT_SECONDARY)
            footer_text.append(f" {_Symbols.bullet()} ", style=CopixColors.TEXT_DIM)
            footer_text.append(f"{length} chars", style=CopixColors.TEXT_SECONDARY)
        
        # For cmd.exe, render simple line instead of Panel
        if TERMINAL_CAPS["is_legacy_cmd"]:
            return footer_text
        
        return Panel(
            footer_text,
            border_style=CopixColors.BORDER,
            padding=(0, 1),
            height=self._footer_height
        )
    
    # ─── Message Rendering ────────────────────────────────────────────────────
    def _render_message(self, msg: Message, index: int) -> RenderableType:
        """Render a single message with appropriate styling."""
        is_current = msg.is_current or index == len(self.messages) - 1
        
        if msg.role == "user":
            return self._render_user_message(msg, is_current)
        elif msg.role == "assistant":
            return self._render_assistant_message(msg, is_current)
        else:
            return self._render_system_message(msg)
    
    def _render_user_message(self, msg: Message, is_current: bool) -> RenderableType:
        """Render user input with elegant prompt symbol."""
        # Dim previous messages
        color = CopixColors.PROMPT_BLUE if is_current else CopixColors.TEXT_DIM
        dim_style = "" if is_current else "dim"
        
        # Use prompt symbol (elegant, minimal, with ASCII fallback for cmd)
        prompt = Text(_Symbols.prompt() + " ", style=f"bold {color}")
        
        # User content
        content_style = "" if is_current else "dim"
        content_text = Text(msg.content, style=content_style)
        
        # Combine
        full_text = Text()
        full_text.append("  ")  # Left indent
        full_text.append(prompt)
        full_text.append(content_text)
        
        return Padding(full_text, (1, 0, 0, 0))
    
    def _render_assistant_message(self, msg: Message, is_current: bool) -> RenderableType:
        """Render AI response in rounded panel with markdown support."""
        content = msg.content
        
        # Check if content has code blocks
        if "```" in content:
            # Extract and render with syntax highlighting
            renderable = self._render_code_content(content)
        else:
            # Standard markdown
            renderable = Markdown(content)
        
        # For cmd.exe, render without panel borders
        if TERMINAL_CAPS["is_legacy_cmd"]:
            if isinstance(renderable, (Markdown, Syntax)):
                return Text(content)  # Convert to plain text for cmd
            return renderable
        
        # Border color based on current status
        border = CopixColors.MS_BLUE if is_current else CopixColors.BORDER
        
        return Panel(
            renderable,
            border_style=border,
            padding=(1, 2),
            title="[dim]assistant[/dim]" if not is_current else "",
            title_align="right"
        )
    
    def _render_code_content(self, content: str) -> Group:
        """Render content with code blocks highlighted."""
        parts: List[RenderableType] = []
        
        # Split by code blocks
        pattern = r'```(\w+)?\n(.*?)```'
        last_end = 0
        
        for match in re.finditer(pattern, content, re.DOTALL):
            # Text before code block
            if match.start() > last_end:
                text_before = content[last_end:match.start()]
                if text_before.strip():
                    parts.append(Markdown(text_before))
            
            # Code block
            lang = match.group(1) or "text"
            code = match.group(2)
            
            # Auto-detect language if not specified
            if lang == "text":
                lang = self._detect_language(code)
            
            syntax = Syntax(
                code,
                lang,
                theme="monokai",
                background_color=CopixColors.BG_PANEL,
                line_numbers=True,
                padding=(1, 2)
            )
            parts.append(syntax)
            
            last_end = match.end()
        
        # Remaining text
        if last_end < len(content):
            text_after = content[last_end:]
            if text_after.strip():
                parts.append(Markdown(text_after))
        
        return Group(*parts) if parts else Markdown(content)
    
    def _detect_language(self, code: str) -> str:
        """Auto-detect programming language from code snippet."""
        # Simple heuristics
        if "import " in code and ("def " in code or "class " in code):
            return "python"
        if "function" in code or "const " in code or "let " in code:
            return "javascript"
        if "SELECT " in code.upper() and "FROM " in code.upper():
            return "sql"
        if "<!DOCTYPE" in code or "<html" in code:
            return "html"
        if "{" in code and "}" in code and ";" in code:
            return "javascript"  # Assume JS for brace-heavy code
        return "text"
    
    def _render_system_message(self, msg: Message) -> RenderableType:
        """Render system messages (muted)."""
        return Text(msg.content, style=f"dim {CopixColors.TEXT_SECONDARY}")
    
    # ─── Generation State ───────────────────────────────────────────────────────
    def start_generation(self, hint: str = "Generating"):
        """Start the generation spinner."""
        # Mark previous assistant message as not current
        for msg in self.messages:
            msg.is_current = False
        
        # Create spinner
        spinner_text = Text()
        spinner_text.append(f"{hint} ", style=CopixColors.TEXT_SECONDARY)
        
        self.spinner = Spinner(
            "dots",
            text=spinner_text,
            style=CopixColors.MS_BLUE
        )
        
        # For cmd.exe, use simple text output instead of Live/Panel
        if TERMINAL_CAPS["is_legacy_cmd"]:
            self.console.print(f"{hint}...")
            return
        
        # Start live display
        self.current_generation = Live(
            Panel(
                self.spinner,
                border_style=CopixColors.MS_BLUE,
                padding=(1, 2)
            ),
            console=self.console,
            refresh_per_second=10,
            transient=False
        )
        self.current_generation.start()
        self._generation_start = time.time()
    
    def update_generation(self, token: str):
        """Update generation with streaming token."""
        if hasattr(self, '_streaming_buffer'):
            self._streaming_buffer += token
        else:
            self._streaming_buffer = token
    
    def end_generation(self, final_content: str, metadata: Optional[Dict] = None):
        """End generation and add to messages."""
        if self.current_generation:
            self.current_generation.stop()
            self.current_generation = None
        
        # Calculate duration
        if hasattr(self, '_generation_start'):
            duration_ms = (time.time() - self._generation_start) * 1000
            if metadata:
                metadata['duration_ms'] = duration_ms
        
        # Store metadata for footer
        if metadata:
            self._last_metadata = metadata
        
        # Add message
        self.add_message("assistant", final_content, is_current=True)
        
        # Clear buffer
        if hasattr(self, '_streaming_buffer'):
            delattr(self, '_streaming_buffer')
    
    # ─── Public API ─────────────────────────────────────────────────────────────
    def add_message(self, role: str, content: str, is_current: bool = False):
        """Add a message to the conversation."""
        # Mark all previous messages as not current
        if is_current:
            for msg in self.messages:
                msg.is_current = False
        
        msg = Message(
            role=role,
            content=content,
            is_current=is_current
        )
        self.messages.append(msg)
        
        # Trim history
        if len(self.messages) > self.max_history:
            self.messages = self.messages[-self.max_history:]
    
    def render(self):
        """Render the complete UI."""
        self.console.clear()
        
        # Header
        self.console.print(self._render_header())
        
        # Messages
        for i, msg in enumerate(self.messages):
            self.console.print(self._render_message(msg, i))
        
        # Generation spinner (if active)
        if self.current_generation:
            pass  # Already being rendered by Live
        
        # Footer
        self.console.print(self._render_footer())
    
    def get_input(self, prompt: str = "") -> str:
        """Get user input with elegant prompt."""
        # Render prompt
        prompt_text = Text()
        prompt_text.append(f"  {_Symbols.prompt()} ", style=f"bold {CopixColors.PROMPT_BLUE}")
        if prompt:
            prompt_text.append(prompt, style=CopixColors.TEXT_SECONDARY)
        
        self.console.print(prompt_text, end="")
        
        try:
            user_input = input()
            self.add_message("user", user_input)
            return user_input
        except (EOFError, KeyboardInterrupt):
            return ""
    
    def print_error(self, message: str):
        """Print an error message."""
        error_text = Text()
        error_text.append("  ✗ ", style=f"bold {CopixColors.ERROR}")
        error_text.append(message, style=CopixColors.TEXT_PRIMARY)
        self.console.print(error_text)
    
    def print_success(self, message: str):
        """Print a success message."""
        success_text = Text()
        success_text.append("  ✓ ", style=f"bold {CopixColors.SUCCESS}")
        success_text.append(message, style=CopixColors.TEXT_PRIMARY)
        self.console.print(success_text)
    
    def print_info(self, message: str):
        """Print an info message (muted)."""
        self.console.print(Text(f"  ℹ {message}", style=CopixColors.TEXT_SECONDARY))


# ─── Convenience Functions ─────────────────────────────────────────────────────
_copix_instance: Optional[CopixTUI] = None

def get_copix(model_name: str = "Qwen 3") -> CopixTUI:
    """Get or create the global CopixTUI instance."""
    global _copix_instance
    if _copix_instance is None:
        _copix_instance = CopixTUI(model_name=model_name)
    return _copix_instance


def copix_header(model: str):
    """Print Copix-style header."""
    copix = get_copix(model)
    copix.console.print(copix._render_header())


def copix_input(prompt: str = "") -> str:
    """Get input with Copix-style prompt."""
    return get_copix().get_input(prompt)


def copix_response(content: str, metadata: Optional[Dict] = None):
    """Display AI response in Copix style."""
    copix = get_copix()
    copix.end_generation(content, metadata)
    copix.render()


def copix_error(message: str):
    """Print error in Copix style."""
    get_copix().print_error(message)


def copix_success(message: str):
    """Print success in Copix style."""
    get_copix().print_success(message)


def copix_info(message: str):
    """Print info in Copix style."""
    get_copix().print_info(message)


# ─── Demo ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Demo the UI
    copix = CopixTUI(model_name="Qwen 3")
    
    # Header
    copix.render()
    
    # Simulate conversation
    copix.add_message("user", "Write a Python function to calculate fibonacci numbers")
    copix.render()
    
    # Simulate generation
    copix.start_generation("Thinking")
    time.sleep(1)
    
    response = '''Here's a Python function to calculate Fibonacci numbers:

```python
def fibonacci(n):
    """Calculate the nth Fibonacci number."""
    if n <= 0:
        return 0
    elif n == 1:
        return 1
    else:
        a, b = 0, 1
        for _ in range(2, n + 1):
            a, b = b, a + b
        return b

# Example usage
for i in range(10):
    print(f"F({i}) = {fibonacci(i)}")
```

This uses an iterative approach for O(n) time complexity and O(1) space.'''
    
    copix.end_generation(response, {
        "duration_ms": 1250,
        "tokens_per_sec": 45.2,
        "content_length": len(response)
    })
    copix.render()
    
    # Get user input
    user_input = copix.get_input()
    print(f"You said: {user_input}")
