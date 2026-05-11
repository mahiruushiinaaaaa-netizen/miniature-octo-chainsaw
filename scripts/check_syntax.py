import ast
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
errors = []
for p in root.rglob('*.py'):
    try:
        src = p.read_text(encoding='utf-8')
        ast.parse(src)
    except Exception as e:
        errors.append((str(p.relative_to(root)), str(e)))

if not errors:
    print('OK')
    sys.exit(0)

print('SYNTAX ERRORS:')
for f, e in errors:
    print(f"- {f}: {e}")
sys.exit(2)
