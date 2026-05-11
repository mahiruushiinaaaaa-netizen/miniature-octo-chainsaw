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
    """Detect system capabilities and environment details categorized by stack."""
    # Grouped binaries to help prioritize relevance
    stacks = {
        "Core": ["git", "docker", "python", "pip"],
        "JS/Web": ["node", "npm", "npx", "yarn", "bun"],
        "PHP/Laravel": ["php", "composer", "laravel"],
        "Mobile": ["java", "javac", "adb", "react-native", "expo", "pod"]
    }
    
    binaries_results = {}
    for stack, bin_list in stacks.items():
        for b in bin_list:
            version = get_binary_version(b)
            if version != "Not found":
                binaries_results[b] = {
                    "version": version,
                    "stack": stack
                }
    
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "binaries": binaries_results,
        "cwd": os.getcwd()
    }

if __name__ == "__main__":
    import json
    print(json.dumps(inspect_environment(), indent=2))
