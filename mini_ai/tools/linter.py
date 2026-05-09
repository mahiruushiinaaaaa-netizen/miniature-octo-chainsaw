import traceback
import subprocess
from pathlib import Path
from typing import Optional

def lint_python_compile(file_path: str, code: str) -> Optional[str]:
    """Check python code for syntax errors using built-in compile."""
    try:
        compile(code, file_path, "exec")
        return None
    except Exception as err:
        tb_lines = traceback.format_exception(type(err), err, err.__traceback__)
        
        # Filter out the internal traceback lines from compile()
        filtered_tb = []
        for line in tb_lines:
            if "lint_python_compile" in line or "compile(code, file_path" in line:
                continue
            filtered_tb.append(line)
            
        res = "".join(filtered_tb)
        return f"Syntax/Compile Error in {file_path}:\n{res}"

def lint_flake8(file_path: str) -> Optional[str]:
    """Run flake8 for fatal errors if installed."""
    fatal = "E9,F821,F823,F831,F406,F407,F701,F702,F704,F706"
    try:
        result = subprocess.run(
            ["flake8", f"--select={fatal}", "--isolated", file_path],
            capture_output=True,
            text=True,
            check=False
        )
        errors = result.stdout + result.stderr
        if errors.strip():
            return f"Flake8 Errors in {file_path}:\n{errors}"
    except (FileNotFoundError, OSError):
        pass # flake8 not installed or not found in PATH
    return None

def lint_file(file_path: str, code: str) -> Optional[str]:
    """
    Route to appropriate linter based on extension.
    Returns a string containing errors, or None if the file is clean.
    """
    path = Path(file_path)
    ext = path.suffix.lower()
    
    if ext == ".py":
        errors = []
        compile_err = lint_python_compile(file_path, code)
        if compile_err:
            errors.append(compile_err)
            
        flake8_err = lint_flake8(file_path)
        if flake8_err:
            errors.append(flake8_err)
            
        if errors:
            return "\n".join(errors)
            
    return None
