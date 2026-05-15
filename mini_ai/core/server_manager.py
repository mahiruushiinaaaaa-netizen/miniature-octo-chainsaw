"""
server_manager.py – Auto-manages AI model server lifecycle.

Handles:
- Auto-starting Ollama and/or llama-server when AI generation is needed
- Auto-stopping servers after idle timeout (default 3 minutes) to save RAM
- Restarting servers on-demand when new input arrives
- Tracking last activity time for idle detection

This saves ~2-3GB RAM when the user isn't actively using AI features.
"""
from __future__ import annotations

import subprocess
import shutil
import threading
import time
from pathlib import Path
from typing import Optional

from .logger import get_logger

logger = get_logger("server_manager")


class ServerManager:
    """Manages AI server lifecycle with auto-start/stop based on activity.
    
    Starts servers on first use, stops them after idle_timeout seconds
    of inactivity. Restarts automatically when needed again.
    """

    def __init__(
        self,
        idle_timeout: int = 1800,  # 30 minutes default (was 3 min — too aggressive)
        ollama_model: str = "qwen2.5:0.5b",
    ) -> None:
        self._idle_timeout = idle_timeout
        self._ollama_model = ollama_model
        self._last_activity: float = 0
        self._llama_proc: Optional[subprocess.Popen] = None
        self._llama_config = None  # Set when llama-server is started
        self._ollama_running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._shutdown = False
        self._lock = threading.Lock()

    def start_monitoring(self) -> None:
        """Start the background idle monitor thread."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._shutdown = False
        self._monitor_thread = threading.Thread(
            target=self._idle_monitor, daemon=True, name="server-idle-monitor"
        )
        self._monitor_thread.start()

    def stop_monitoring(self) -> None:
        """Stop the idle monitor and shut down all servers."""
        self._shutdown = True
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        self.stop_all()

    def touch(self) -> None:
        """Record activity — resets the idle timer."""
        self._last_activity = time.time()

    def ensure_ollama(self) -> bool:
        """Ensure Ollama is running. Starts it if needed.
        
        Returns True if Ollama is available, False otherwise.
        """
        with self._lock:
            self.touch()
            
            # Check if already running
            if self._check_ollama():
                self._ollama_running = True
                return True
            
            # Try to start Ollama
            return self._start_ollama()

    def ensure_llama_server(self, config) -> bool:
        """Ensure llama-server is running. Starts it if needed.
        
        Returns True if server is ready, False otherwise.
        """
        with self._lock:
            self.touch()
            
            from .backend import server_ready
            if self._llama_proc and self._llama_proc.poll() is None:
                if server_ready(config.base_url):
                    return True
            
            # Need to start it
            return self._start_llama_server(config)

    def stop_all(self) -> None:
        """Stop all managed servers."""
        with self._lock:
            self._stop_llama_server()
            self._stop_ollama()

    def _idle_monitor(self) -> None:
        """Background thread that stops servers after idle timeout."""
        while not self._shutdown:
            time.sleep(10)  # Check every 10 seconds
            
            if self._last_activity == 0:
                continue
            
            idle_seconds = time.time() - self._last_activity
            if idle_seconds > self._idle_timeout:
                with self._lock:
                    if self._ollama_running or self._llama_proc:
                        logger.info(
                            f"Idle for {idle_seconds:.0f}s, stopping AI servers to save RAM",
                            operation="idle_shutdown",
                        )
                        self._stop_llama_server()
                        self._stop_ollama()

    def _check_ollama(self) -> bool:
        """Check if Ollama is responding."""
        import urllib.request
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:11434/api/tags", method="GET"
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _start_ollama(self) -> bool:
        """Start the Ollama service."""
        # First check if it's already running (might be a Windows service)
        if self._check_ollama():
            self._ollama_running = True
            return True
        
        try:
            import subprocess
            # On Windows, try starting Ollama app directly
            # Ollama on Windows installs to AppData
            import os
            ollama_paths = [
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Ollama\ollama.exe"),
                "ollama",  # If in PATH
            ]
            
            ollama_exe = None
            for path in ollama_paths:
                if path == "ollama" and shutil.which("ollama"):
                    ollama_exe = "ollama"
                    break
                elif os.path.exists(path):
                    ollama_exe = path
                    break
            
            if not ollama_exe:
                logger.debug("Ollama executable not found")
                return False
            
            # Start ollama serve in background
            proc = subprocess.Popen(
                [ollama_exe, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            
            # Wait for it to be ready (max 20 seconds)
            deadline = time.time() + 20
            while time.time() < deadline:
                if self._check_ollama():
                    self._ollama_running = True
                    logger.info("Ollama started successfully", operation="ollama_start")
                    return True
                time.sleep(0.5)
            
            # Check one more time — might already be running as service
            if self._check_ollama():
                self._ollama_running = True
                return True
            
            proc.kill()
            logger.debug("Ollama failed to start within timeout")
            return False
            
        except FileNotFoundError:
            logger.debug("Ollama binary not found in PATH")
            return False
        except Exception as e:
            logger.debug(f"Failed to start Ollama: {e}")
            return False

    def _stop_ollama(self) -> None:
        """Stop Ollama to free RAM."""
        if not self._ollama_running:
            return
        try:
            # Ollama can be stopped via its API or by killing the process
            # The cleanest way is to just let it idle-unload models
            # But to actually free RAM, we need to stop the service
            subprocess.run(
                ["taskkill", "/f", "/im", "ollama_llama_server.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            subprocess.run(
                ["taskkill", "/f", "/im", "ollama.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            self._ollama_running = False
            logger.info("Ollama stopped to save RAM", operation="ollama_stop")
        except Exception as e:
            logger.debug(f"Failed to stop Ollama: {e}")

    def _start_llama_server(self, config) -> bool:
        """Start llama-server with the given config."""
        from .backend import start_server, server_ready
        
        self._llama_config = config
        self._llama_proc = start_server(config)
        
        if self._llama_proc and server_ready(config.base_url):
            logger.info("llama-server started", operation="llama_start")
            return True
        return False

    def _stop_llama_server(self) -> None:
        """Stop llama-server to free RAM."""
        if self._llama_proc:
            try:
                self._llama_proc.kill()
                self._llama_proc.wait(timeout=5)
            except Exception:
                pass
            self._llama_proc = None
            logger.info("llama-server stopped to save RAM", operation="llama_stop")


# Global singleton
_server_manager: Optional[ServerManager] = None


def get_server_manager(idle_timeout: int = 180) -> ServerManager:
    """Get or create the global ServerManager singleton."""
    global _server_manager
    if _server_manager is None:
        _server_manager = ServerManager(idle_timeout=idle_timeout)
        _server_manager.start_monitoring()
    return _server_manager
