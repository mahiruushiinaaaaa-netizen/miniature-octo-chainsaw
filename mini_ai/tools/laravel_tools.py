import subprocess
import os
from pathlib import Path
from typing import Tuple

def _ensure_path():
    """Ensure PHP, Composer, and Node are in PATH for this process."""
    try:
        from ..core.dep_installer import _refresh_path
        _refresh_path()
    except Exception:
        pass

def create_laravel_project(name: str, cwd: Path) -> Tuple[bool, str]:
    """Create a new Laravel project."""
    _ensure_path()
    cmd = f"composer create-project laravel/laravel {name}"
    try:
        result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=300, env=os.environ)
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "Command timed out (5 min limit)"
    except Exception as e:
        return False, str(e)

def install_breeze(project_path: Path, stack: str = "blade") -> Tuple[bool, str]:
    """Install Laravel Breeze."""
    _ensure_path()
    
    commands = [
        "composer require laravel/breeze --dev",
        f"php artisan breeze:install {stack} --no-interaction",
        "npm install",
        "npm run build"
    ]
    
    total_output = ""
    for cmd in commands:
        try:
            result = subprocess.run(cmd, shell=True, cwd=project_path, capture_output=True, text=True, timeout=180, env=os.environ)
            total_output += f"\n--- Running: {cmd} ---\n{result.stdout}{result.stderr}"
            if result.returncode != 0:
                return False, total_output
        except subprocess.TimeoutExpired:
            total_output += f"\n--- {cmd} timed out ---"
            return False, total_output
        except Exception as e:
            return False, total_output + f"\nError: {str(e)}"
            
    return True, total_output

def run_migrations(project_path: Path) -> Tuple[bool, str]:
    """Run Laravel migrations."""
    _ensure_path()
    cmd = "php artisan migrate --force"
    try:
        result = subprocess.run(cmd, shell=True, cwd=project_path, capture_output=True, text=True, timeout=60, env=os.environ)
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)
