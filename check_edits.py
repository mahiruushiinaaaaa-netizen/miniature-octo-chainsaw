#!/usr/bin/env python3
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]

# Quick syntax check
errors = []
for p in [
    root / 'mini_ai/core/backend.py',
    root / 'mini_ai/core/rag.py',
    root / 'mini_ai/agents/agent.py',
    root / 'mini_ai/agents/reviewer.py',
    root / 'mini_ai/agents/orchestrator.py',
    root / 'mini_ai/agents/planner.py',
]:
    if not p.exists():
        continue
    try:
        compile(p.read_text(), str(p), 'exec')
        print(f'✓ {p.name}')
    except SyntaxError as e:
        errors.append((p.name, str(e)))
        print(f'✗ {p.name}: {e}')

if errors:
    print(f'\n{len(errors)} syntax errors found')
    sys.exit(1)
else:
    print(f'\n✓ All files syntax OK')
    sys.exit(0)
