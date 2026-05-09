from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

from ..ui import err, ok, C


def extract_code_block(text: str, language: str | None = None) -> str:
    if language:
        pattern = rf"```(?:{re.escape(language)})?\s*(.*?)```"
    else:
        pattern = r"```(?:[a-zA-Z0-9_+-]+)?\s*(.*?)```"
    match = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else text.strip()


def extract_python_code(text: str) -> str:
    return extract_code_block(text, "python")


def run_python_code(code: str, timeout: int = 30) -> tuple[bool, str]:
    code = extract_python_code(code)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
        handle.write(code)
        path = Path(handle.name)

    try:
        from .proc import run_and_stream
        return_code, output = run_and_stream(
            f'"{sys.executable}" "{path}"',
            timeout=timeout,
            show_output=True,
            prefix=f"  {C.purple}│{C.reset} "
        )
        if return_code == 0:
            ok("Code executed")
        else:
            err(f"Code exited with {return_code}")
        return return_code == 0, output
    except Exception as e:
        err(f"Execution error: {str(e)}")
        return False, f"[Error] {str(e)}"
    finally:
        path.unlink(missing_ok=True)
