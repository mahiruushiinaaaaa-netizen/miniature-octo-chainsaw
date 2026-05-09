import time
import threading
import re
from pathlib import Path
from typing import Dict, Callable

class FileWatcher:
    """
    A simple polling file watcher that looks for 'AI:' comments in files.
    Matches Aider's 'watch' feature without external dependencies.
    """
    def __init__(self, workspace_root: str, callback: Callable[[Path, str], None]):
        self.root = Path(workspace_root)
        self.callback = callback
        self.mtimes: Dict[str, float] = {}
        self.running = False
        self.thread = None
        
        # Regex to find AI: comments
        # Matches: # AI: make a loop, // AI: fix this, etc.
        self.ai_pattern = re.compile(r'(?:#|//|--|;)\s*AI:\s*(.*)', re.IGNORECASE)

    def scan(self):
        """Scan workspace for changes and AI comments."""
        for file_path in self.root.rglob("*"):
            if not file_path.is_file():
                continue
            if any(p.startswith(".") or p in {"node_modules", "__pycache__", "venv"} for p in file_path.parts):
                continue
            if file_path.suffix not in {".py", ".js", ".ts", ".html", ".css", ".md", ".txt"}:
                continue
                
            try:
                mtime = file_path.stat().st_mtime
                old_mtime = self.mtimes.get(str(file_path))
                
                if old_mtime is not None and mtime > old_mtime:
                    # File changed! Check for AI: comment
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    match = self.ai_pattern.search(content)
                    if match:
                        goal = match.group(1).strip()
                        if goal:
                            # Found a request!
                            self.callback(file_path, goal)
                
                self.mtimes[str(file_path)] = mtime
            except Exception:
                continue

    def _loop(self):
        while self.running:
            self.scan()
            time.sleep(1.5) # Poll every 1.5s

    def start(self):
        if self.running:
            return
        self.running = True
        # Initialize mtimes so we don't trigger on initial scan
        self.scan()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
