import subprocess
import shutil
import platform
import os
from typing import Dict, Any

def get_binary_version(binary: str) -> str:
    """Get the version of a binary if it exists."""
    if not shutil.which(binary):
        return "Not found"
    
    try:
        # Most binaries support --version
        cmd = [binary, "--version"]
        if binary == "php":
            cmd = [binary, "-v"]
        
        # Use shell=True on Windows for .cmd/.bat files like npm/composer
        is_windows = os.name == "nt"
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            timeout=5, 
            shell=is_windows
        )
        if result.returncode == 0:
            # Return first line of output
            return (result.stdout or result.stderr).splitlines()[0].strip()
        return f"Unknown ({result.returncode})"
    except Exception as e:
        return f"Error: {str(e)[:30]}"

def inspect_environment() -> Dict[str, Any]:
    """Detect system capabilities and environment details."""
    binaries = ["php", "composer", "node", "npm", "git", "python", "pip"]
    results = {
        "os": platform.system(),
        "os_release": platform.release(),
        "binaries": {b: get_binary_version(b) for b in binaries},
        "cwd": os.getcwd()
    }
    
    # Check for Laravel installer specifically
    laravel_path = shutil.which("laravel")
    results["binaries"]["laravel"] = "Found" if laravel_path else "Not found"
    
    return results

if __name__ == "__main__":
    import json
    print(json.dumps(inspect_environment(), indent=2))
