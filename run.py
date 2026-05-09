"""
run.py – Application entry point.
Uses modernized CLI v2 with health checks and observability.
"""
import sys

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

# Use the new modernized CLI
from mini_ai.core.cli_v2 import main

if __name__ == "__main__":
    raise SystemExit(main())

