import subprocess
from pathlib import Path
from typing import Tuple

def create_laravel_project(name: str, cwd: Path) -> Tuple[bool, str]:
    """Create a new Laravel project."""
    cmd = f"composer create-project laravel/laravel {name}"
    try:
        result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)

def install_breeze(project_path: Path, stack: str = "blade") -> Tuple[bool, str]:
    """Install Laravel Breeze."""
    # 1. Require breeze
    # 2. Run breeze:install
    # 3. npm install && npm run build
    
    commands = [
        "composer require laravel/breeze --dev",
        f"php artisan breeze:install {stack} --no-interaction",
        "npm install",
        "npm run build"
    ]
    
    total_output = ""
    for cmd in commands:
        try:
            result = subprocess.run(cmd, shell=True, cwd=project_path, capture_output=True, text=True)
            total_output += f"\n--- Running: {cmd} ---\n{result.stdout}{result.stderr}"
            if result.returncode != 0:
                return False, total_output
        except Exception as e:
            return False, total_output + f"\nError: {str(e)}"
            
    return True, total_output

def run_migrations(project_path: Path) -> Tuple[bool, str]:
    """Run Laravel migrations."""
    cmd = "php artisan migrate --force"
    try:
        result = subprocess.run(cmd, shell=True, cwd=project_path, capture_output=True, text=True)
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)
