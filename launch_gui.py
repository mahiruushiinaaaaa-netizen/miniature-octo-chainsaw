"""
launch_gui.py – GUI launcher for Mini AI.
"""
import sys
from pathlib import Path

# Add the root to sys.path if running as a script
root = Path(__file__).parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

try:
    from mini_ai.ui.gui import main
    if __name__ == "__main__":
        main()
except ImportError as e:
    print(f"Error loading GUI: {e}")
    print("Ensure you are in the project root and the 'mini_ai' package is intact.")
    sys.exit(1)
