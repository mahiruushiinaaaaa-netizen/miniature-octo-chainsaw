import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from .base import SandboxResult

class PersistentShellSession:
    """
    Manages a long-running shell process (cmd.exe or bash) and allows 
    executing multiple commands within the same environment/session.
    """
    def __init__(self, cwd: Path, env: Optional[Dict[str, str]] = None):
        self._cwd = cwd
        self._env = env or os.environ.copy()
        self._is_windows = os.name == "nt"
        
        # Unique session token to avoid collision with command output
        import uuid
        self._token = uuid.uuid4().hex[:8]
        
        # Shell setup
        if self._is_windows:
            self._shell_cmd = ["cmd.exe", "/Q", "/K", "echo off"]
            self._sentinel_tmpl = f"echo __EXIT_CODE_{self._token}__ %errorlevel% & echo __CWD_{self._token}__ %cd% & echo __FINISH_{self._token}__"
        else:
            self._shell_cmd = ["/bin/bash", "--noprofile", "--norc", "-i"]
            self._sentinel_tmpl = f"echo __EXIT_CODE_{self._token}__ $? ; echo __CWD_{self._token}__ $(pwd) ; echo __FINISH_{self._token}__"

        self._process = subprocess.Popen(
            self._shell_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self._cwd),
            env=self._env,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        self._stdout_buffer: List[str] = []
        self._stderr_buffer: List[str] = []
        self._finish_event = threading.Event()
        self._last_exit_code = 0
        self._last_cwd = self._cwd

        # Start output reader threads
        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()
        self._on_output = None

    def _read_stdout(self):
        """Continuously read stdout and look for sentinels."""
        exit_code_re = re.compile(rf"__EXIT_CODE_{self._token}__\s+(-?\d+)")
        cwd_re = re.compile(rf"__CWD_{self._token}__\s+(.*)")
        finish_marker = f"__FINISH_{self._token}__"

        for line in iter(self._process.stdout.readline, ''):
            if f"__EXIT_CODE_{self._token}__" in line:
                match = exit_code_re.search(line)
                if match:
                    self._last_exit_code = int(match.group(1))
            elif f"__CWD_{self._token}__" in line:
                match = cwd_re.search(line)
                if match:
                    self._last_cwd = Path(match.group(1).strip())
            elif finish_marker in line:
                self._finish_event.set()
            else:
                self._stdout_buffer.append(line)
                if self._on_output:
                    self._on_output(line)

    def _read_stderr(self):
        """Continuously read stderr."""
        for line in iter(self._process.stderr.readline, ''):
            self._stderr_buffer.append(line)
            if self._on_output:
                self._on_output(line)

    def execute(self, cmd: str, timeout: int = 600, on_output=None) -> SandboxResult:
        """Execute a command in the persistent shell."""
        self._on_output = on_output
        if self._process.poll() is not None:
            return SandboxResult(success=False, output="Shell process terminated unexpectedly.", exit_code=-1)

        # Clear state
        self._stdout_buffer.clear()
        self._stderr_buffer.clear()
        self._finish_event.clear()

        # Send command + sentinel
        full_cmd = f"{cmd}\n{self._sentinel_tmpl}\n"
        try:
            self._process.stdin.write(full_cmd)
            self._process.stdin.flush()
        except OSError as e:
            return SandboxResult(success=False, output=f"Failed to write to shell: {e}", exit_code=-1)

        # Wait for completion
        if not self._finish_event.wait(timeout=timeout):
            return SandboxResult(
                success=False, 
                output=f"Command timed out after {timeout}s", 
                exit_code=-1,
                stdout="".join(self._stdout_buffer)
            )

        # Success!
        stdout = "".join(self._stdout_buffer)
        stderr = "".join(self._stderr_buffer)
        output = stdout + ("\n" + stderr if stderr else "")
        
        # Update session CWD
        self._cwd = self._last_cwd

        return SandboxResult(
            success=(self._last_exit_code == 0),
            output=output,
            exit_code=self._last_exit_code,
            stdout=stdout,
            stderr=stderr,
            metadata={"cwd": str(self._cwd)}
        )

    @property
    def cwd(self) -> Path:
        return self._cwd

    def close(self):
        """Terminate the shell process."""
        if self._process:
            try:
                self._process.stdin.write("exit\n")
                self._process.stdin.flush()
                self._process.terminate()
                self._process.wait(timeout=2)
            except:
                try: self._process.kill()
                except: pass
