import os
import sys
import shlex
import subprocess
import re
from pathlib import Path
from typing import Optional, Union, Dict

from ..ui import C

class ShellSession:
    """A persistent shell session (like a terminal window)."""
    def __init__(self, cwd: Optional[Path] = None, env: Optional[Dict[str, str]] = None):
        self.cwd = cwd or Path.cwd()
        self.env = env or os.environ.copy()
        self.shell_cmd = ["cmd", "/k"] if os.name == "nt" else ["/bin/sh", "-i"]
        self.process = subprocess.Popen(
            self.shell_cmd,
            shell=False,
            cwd=self.cwd,
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        self.ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

    def execute(self, cmd: str, timeout: int = 600) -> tuple[int, str, str]:
        """Send a command to the persistent shell and wait for output."""
        # Note: Truly persistent interactive shells are complex due to prompts.
        # For now, we wrap the one-off execution but maintain CWD/Env in a 'Sandbox' way.
        return run_and_stream(cmd, cwd=self.cwd, timeout=timeout)

    def close(self):
        if self.process:
            self.process.terminate()

def run_and_stream(
    cmd: str,
    cwd: Optional[Union[str, Path]] = None,
    timeout: int = 600,
    show_output: bool = True,
    prefix: str = f"  {C.gray}│{C.reset} "
) -> tuple[int, str, str]:
    """
    Run a shell command and stream its output to stdout in real-time.
    Returns (return_code, stdout, stderr).
    """
    if cwd:
        cwd = Path(cwd)
    else:
        cwd = Path.cwd()

    # Determine if we need shell
    use_shell = any(c in cmd for c in "|&;<>\n") or os.name == "nt"
    
    if os.name == "nt":
        use_shell = True
        exec_args = cmd
    else:
        if use_shell:
            exec_args = cmd
        else:
            exec_args = shlex.split(cmd)

    process = subprocess.Popen(
        exec_args,
        shell=use_shell,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=sys.stdin,
        text=True,
        bufsize=1,
        universal_newlines=True
    )

    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text
    from rich.console import Console

    console = Console()
    stdout_buf = []
    stderr_buf = []
    
    display_text = Text()
    panel_ui = Panel(display_text, title=f"SANDBOX: [bold cyan]{cmd[:50]}[/bold cyan]", border_style="blue", expand=True)

    import threading

    def read_stream(stream, buffer, display=None, live=None):
        for line in iter(stream.readline, ''):
            if line:
                buffer.append(line)
                if display is not None and live is not None:
                    # Clean ANSI for UI
                    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                    clean_line = ansi_escape.sub('', line)
                    display.append(clean_line)
                    # Keep only the last 20 lines
                    plain = display.plain
                    lines = plain.splitlines()
                    if len(lines) > 20:
                        display.clear()
                        display.append("\n".join(lines[-20:]) + "\n")
                    live.update(panel_ui)

    try:
        with Live(panel_ui, console=console, refresh_per_second=4) as live:
            t1 = threading.Thread(target=read_stream, args=(process.stdout, stdout_buf, display_text, live))
            t2 = threading.Thread(target=read_stream, args=(process.stderr, stderr_buf, display_text, live))
            t1.start()
            t2.start()
            
            return_code = process.wait(timeout=timeout)
            t1.join()
            t2.join()
    except subprocess.TimeoutExpired:
        process.kill()
        return_code = -1
        stderr_buf.append(f"\n[Error] Command timed out after {timeout}s")
    except Exception as e:
        if process.poll() is None:
            process.kill()
        return_code = -1
        stderr_buf.append(f"\n[Error] {str(e)}")

    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    
    stdout_clean = ansi_escape.sub('', "".join(stdout_buf)).strip()
    stderr_clean = ansi_escape.sub('', "".join(stderr_buf)).strip()

    return return_code, stdout_clean, stderr_clean
