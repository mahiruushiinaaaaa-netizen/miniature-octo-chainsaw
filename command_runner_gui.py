"""
command_runner_gui.py – Command Runner entry point (Legacy/Shortcut).
Redirects to mini_ai.ui.command_runner.
"""
import sys
from pathlib import Path

# Add the root to sys.path if running as a script
root = Path(__file__).parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from mini_ai.ui.command_runner import main

if __name__ == "__main__":
    main()
