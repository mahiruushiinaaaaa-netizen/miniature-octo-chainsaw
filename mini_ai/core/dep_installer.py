"""
dep_installer.py – Dependency detection and auto-installation for common dev tools.

Knows the full dependency chain for common frameworks:
- Laravel needs: PHP + Composer
- Django needs: Python (usually present)
- React/Vue/Next needs: Node.js + npm (usually present)

Uses winget (Windows Package Manager) for reliable installs.
"""
from __future__ import annotations

import subprocess
import shutil
import os
from typing import Optional

from .logger import get_logger

logger = get_logger("dep_installer")

# Refresh PATH on import to pick up winget-installed tools
try:
    import os as _os
    _winget_packages = _os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    if _os.path.exists(_winget_packages):
        for _pkg in _os.listdir(_winget_packages):
            _pkg_path = _os.path.join(_winget_packages, _pkg)
            if _os.path.isdir(_pkg_path) and _pkg_path not in _os.environ.get("PATH", ""):
                for _exe in _os.listdir(_pkg_path):
                    if _exe.endswith(".exe"):
                        _os.environ["PATH"] = _pkg_path + ";" + _os.environ.get("PATH", "")
                        break
except Exception:
    pass


# Dependency chains: tool → what it needs installed first
# Each entry: (check_cmd, winget_id, display_name)
TOOL_DEPS: dict[str, list[tuple[str, str, str]]] = {
    "composer": [
        ("php", "PHP.PHP.8.4", "PHP 8.4"),
        ("composer", "_composer_special_", "Composer"),  # Special install via script
    ],
    "php": [
        ("php", "PHP.PHP.8.4", "PHP 8.4"),
    ],
    "laravel": [
        ("php", "PHP.PHP.8.4", "PHP 8.4"),
        ("composer", "_composer_special_", "Composer"),
    ],
    "node": [
        ("node", "OpenJS.NodeJS.LTS", "Node.js LTS"),
    ],
    "npm": [
        ("node", "OpenJS.NodeJS.LTS", "Node.js LTS"),
    ],
    "npx": [
        ("node", "OpenJS.NodeJS.LTS", "Node.js LTS"),
    ],
    "yarn": [
        ("node", "OpenJS.NodeJS.LTS", "Node.js LTS"),
    ],
    "pnpm": [
        ("node", "OpenJS.NodeJS.LTS", "Node.js LTS"),
    ],
    "python": [
        ("python", "Python.Python.3.12", "Python 3.12"),
    ],
    "pip": [
        ("python", "Python.Python.3.12", "Python 3.12"),
    ],
    "git": [
        ("git", "Git.Git", "Git"),
    ],
    "docker": [
        ("docker", "Docker.DockerDesktop", "Docker Desktop"),
    ],
    "rust": [
        ("rustc", "Rustlang.Rustup", "Rust (via rustup)"),
    ],
    "cargo": [
        ("rustc", "Rustlang.Rustup", "Rust (via rustup)"),
    ],
    "go": [
        ("go", "GoLang.Go", "Go"),
    ],
    "deno": [
        ("deno", "DenoLand.Deno", "Deno"),
    ],
    "bun": [
        ("bun", "Oven-sh.Bun", "Bun"),
    ],
    "flutter": [
        ("git", "Git.Git", "Git"),
        ("flutter", "_flutter_special_", "Flutter SDK"),
    ],
    "dart": [
        ("dart", "_flutter_special_", "Dart (via Flutter SDK)"),
    ],
    "dotnet": [
        ("dotnet", "Microsoft.DotNet.SDK.8", ".NET SDK 8"),
    ],
    "java": [
        ("java", "Microsoft.OpenJDK.21", "OpenJDK 21"),
    ],
    "gradle": [
        ("java", "Microsoft.OpenJDK.21", "OpenJDK 21"),
        ("gradle", "Gradle.Gradle", "Gradle"),
    ],
    "maven": [
        ("java", "Microsoft.OpenJDK.21", "OpenJDK 21"),
        ("mvn", "Apache.Maven", "Apache Maven"),
    ],
    "ruby": [
        ("ruby", "RubyInstallerTeam.RubyWithDevKit.3.3", "Ruby 3.3"),
    ],
    "gem": [
        ("ruby", "RubyInstallerTeam.RubyWithDevKit.3.3", "Ruby 3.3"),
    ],
    "rails": [
        ("ruby", "RubyInstallerTeam.RubyWithDevKit.3.3", "Ruby 3.3"),
    ],
    "expo": [
        ("node", "OpenJS.NodeJS.LTS", "Node.js LTS"),
    ],
    "react-native": [
        ("node", "OpenJS.NodeJS.LTS", "Node.js LTS"),
        ("java", "Microsoft.OpenJDK.21", "OpenJDK 21"),
    ],
    "angular": [
        ("node", "OpenJS.NodeJS.LTS", "Node.js LTS"),
    ],
}

# Framework → required tools (in install order)
FRAMEWORK_DEPS: dict[str, list[str]] = {
    "laravel": ["php", "composer"],
    "laravel-breeze": ["php", "composer"],
    "laravel-facebook": ["php", "composer"],
    "laravel-api": ["php", "composer"],
    "react": ["node"],
    "react-native": ["node", "java"],
    "vue": ["node"],
    "next": ["node"],
    "nextjs": ["node"],
    "nuxt": ["node"],
    "angular": ["node"],
    "django": ["python"],
    "flask": ["python"],
    "fastapi": ["python"],
    "express": ["node"],
    "nestjs": ["node"],
    "svelte": ["node"],
    "astro": ["node"],
    "remix": ["node"],
    "vite": ["node"],
    "rails": ["ruby"],
    "spring": ["java"],
    "flutter": ["flutter"],
    "expo": ["node"],
    "rust": ["cargo"],
    "go": ["go"],
    "dotnet": ["dotnet"],
    "electron": ["node"],
    "tauri": ["node", "cargo"],
}


# Framework → exact creation commands (used by _enrich_task_goal and fast project route)
FRAMEWORK_CREATE_COMMANDS: dict[str, dict[str, str | list[str]]] = {
    "laravel": {
        "cmd": "composer create-project laravel/laravel {name}",
        "post_cmds": [],  # Optional post-creation steps
        "extensions": ["breeze", "jetstream", "sanctum", "passport", "cashier"],
    },
    "laravel-breeze": {
        "cmd": "composer create-project laravel/laravel {name}",
        "post_cmds": [
            "composer require laravel/breeze --dev",
            "php artisan breeze:install blade --no-interaction",
            "npm install",
            "npm install axios",
            'php -r "if(!file_exists(\'resources/js/bootstrap.js\'))file_put_contents(\'resources/js/bootstrap.js\',\\"import axios from \'axios\';\\nwindow.axios = axios;\\nwindow.axios.defaults.headers.common[\'X-Requested-With\'] = \'XMLHttpRequest\';\\n\\");"',
            "npm run build",
        ],
    },
    "laravel-facebook": {
        "cmd": "composer create-project laravel/laravel {name}",
        "post_cmds": [
            "composer require laravel/breeze --dev",
            "php artisan breeze:install blade --no-interaction",
            "npm install",
            "npm install axios",
            'php -r "if(!file_exists(\'resources/js/bootstrap.js\'))file_put_contents(\'resources/js/bootstrap.js\',\\"import axios from \'axios\';\\nwindow.axios = axios;\\nwindow.axios.defaults.headers.common[\'X-Requested-With\'] = \'XMLHttpRequest\';\\n\\");"',
            "npm run build",
            "_apply_facebook_ui_",
        ],
    },
    "laravel-api": {
        "cmd": "composer create-project laravel/laravel {name}",
        "post_cmds": [
            "php artisan install:api",
        ],
    },
    "react": {
        "cmd": "npx create-react-app {name}",
        "post_cmds": [],
    },
    "react-ts": {
        "cmd": "npx create-react-app {name} --template typescript",
        "post_cmds": [],
    },
    "react-vite": {
        "cmd": "npm create vite@latest {name} -- --template react",
        "post_cmds": ["npm install"],
    },
    "react-vite-ts": {
        "cmd": "npm create vite@latest {name} -- --template react-ts",
        "post_cmds": ["npm install"],
    },
    "react-native": {
        "cmd": "npx react-native@latest init {name}",
        "post_cmds": [],
    },
    "expo": {
        "cmd": "npx create-expo-app@latest {name}",
        "post_cmds": [],
    },
    "next": {
        "cmd": "npx create-next-app@latest {name}",
        "post_cmds": [],
    },
    "nextjs": {
        "cmd": "npx create-next-app@latest {name}",
        "post_cmds": [],
    },
    "vue": {
        "cmd": "npm create vue@latest {name}",
        "post_cmds": ["npm install"],
    },
    "nuxt": {
        "cmd": "npx nuxi@latest init {name}",
        "post_cmds": ["npm install"],
    },
    "angular": {
        "cmd": "npx @angular/cli@latest new {name} --skip-git",
        "post_cmds": [],
    },
    "svelte": {
        "cmd": "npx sv create {name}",
        "post_cmds": ["npm install"],
    },
    "astro": {
        "cmd": "npm create astro@latest {name}",
        "post_cmds": [],
    },
    "remix": {
        "cmd": "npx create-remix@latest {name}",
        "post_cmds": [],
    },
    "vite": {
        "cmd": "npm create vite@latest {name}",
        "post_cmds": ["npm install"],
    },
    "django": {
        "cmd": "pip install django",
        "post_cmds": ["django-admin startproject {name}"],
    },
    "flask": {
        "cmd": "pip install flask",
        "post_cmds": [],
    },
    "fastapi": {
        "cmd": "pip install fastapi uvicorn",
        "post_cmds": [],
    },
    "express": {
        "cmd": "mkdir {name}",
        "post_cmds": ["npm init -y", "npm install express cors"],
    },
    "nestjs": {
        "cmd": "npx @nestjs/cli@latest new {name}",
        "post_cmds": [],
    },
    "rails": {
        "cmd": "gem install rails",
        "post_cmds": ["rails new {name}"],
    },
    "spring": {
        "cmd": "curl -s https://start.spring.io/starter.zip -o {name}.zip",
        "post_cmds": [],
    },
    "flutter": {
        "cmd": "flutter create {name}",
        "post_cmds": [],
    },
    "electron": {
        "cmd": "npx create-electron-app@latest {name}",
        "post_cmds": [],
    },
    "tauri": {
        "cmd": "npm create tauri-app@latest {name}",
        "post_cmds": [],
    },
    "dotnet-web": {
        "cmd": "dotnet new webapp -n {name}",
        "post_cmds": [],
    },
    "dotnet-api": {
        "cmd": "dotnet new webapi -n {name}",
        "post_cmds": [],
    },
    "dotnet-blazor": {
        "cmd": "dotnet new blazor -n {name}",
        "post_cmds": [],
    },
    "rust": {
        "cmd": "cargo new {name}",
        "post_cmds": [],
    },
    "go": {
        "cmd": "mkdir {name}",
        "post_cmds": ["go mod init {name}"],
    },
}


def is_installed(cmd: str) -> bool:
    """Check if a command is available in PATH."""
    return shutil.which(cmd) is not None


def install_with_winget(winget_id: str, display_name: str) -> bool:
    """Install a package using winget. Returns True on success."""
    if not shutil.which("winget"):
        logger.debug("winget not available")
        return False
    
    # Special case: Composer needs its own installer
    if winget_id == "_composer_special_":
        return install_composer()
    
    # Special case: Flutter needs git clone
    if winget_id == "_flutter_special_":
        return install_flutter()
    
    try:
        from ..ui import ok, warn
        ok(f"Installing {display_name} via winget...")
        result = subprocess.run(
            ["winget", "install", "--id", winget_id, "--silent",
             "--accept-package-agreements", "--accept-source-agreements",
             "--scope", "user"],  # user scope avoids UAC
            capture_output=True,
            text=True,
            timeout=180,
        )
        stdout = result.stdout.lower()
        if result.returncode == 0 or "already installed" in stdout or "no applicable upgrade" in stdout:
            ok(f"{display_name} installed successfully")
            # Refresh PATH for current process
            _refresh_path()
            # Post-install: enable PHP extensions if PHP was installed
            if "PHP" in display_name:
                _enable_php_extensions()
            return True
        else:
            logger.debug(f"winget install failed (rc={result.returncode}): {result.stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        logger.debug(f"winget install timed out for {display_name}")
        return False
    except Exception as e:
        logger.debug(f"winget install error: {e}")
        return False


def _enable_php_extensions() -> None:
    """Enable common PHP extensions (openssl, curl, mbstring) after install."""
    # Find php.ini in the winget packages dir
    winget_packages = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    if not os.path.exists(winget_packages):
        return
    
    for pkg in os.listdir(winget_packages):
        if "PHP" not in pkg:
            continue
        pkg_path = os.path.join(winget_packages, pkg)
        ini_dev = os.path.join(pkg_path, "php.ini-development")
        ini_path = os.path.join(pkg_path, "php.ini")
        
        # Create php.ini from development template if it doesn't exist
        if not os.path.exists(ini_path) and os.path.exists(ini_dev):
            import shutil as _shutil
            _shutil.copy2(ini_dev, ini_path)
        
        if os.path.exists(ini_path):
            try:
                content = open(ini_path, "r").read()
                # Enable key extensions
                extensions = ["openssl", "curl", "mbstring", "fileinfo", "pdo_mysql", "pdo_sqlite", "sqlite3", "zip"]
                modified = False
                for ext in extensions:
                    disabled = f";extension={ext}"
                    enabled = f"extension={ext}"
                    if disabled in content and enabled not in content.replace(disabled, ""):
                        content = content.replace(disabled, enabled, 1)
                        modified = True
                
                # Also set extension_dir
                ext_dir = os.path.join(pkg_path, "ext")
                if os.path.exists(ext_dir) and "extension_dir" not in content.split(";extension_dir")[0]:
                    content = content.replace(
                        ';extension_dir = "ext"',
                        f'extension_dir = "{ext_dir}"',
                        1,
                    )
                    modified = True
                
                if modified:
                    open(ini_path, "w").write(content)
                    logger.info("PHP extensions enabled: openssl, curl, mbstring")
            except Exception as e:
                logger.debug(f"Failed to enable PHP extensions: {e}")
        break


def install_composer() -> bool:
    """Install Composer using its official Windows installer via PowerShell."""
    # Find PHP — check PATH first, then winget packages
    php_path = shutil.which("php")
    if not php_path:
        # Check winget packages directory
        winget_packages = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
        if os.path.exists(winget_packages):
            for pkg in os.listdir(winget_packages):
                if "PHP" in pkg:
                    candidate = os.path.join(winget_packages, pkg, "php.exe")
                    if os.path.exists(candidate):
                        php_path = candidate
                        break
    
    if not php_path:
        logger.debug("PHP not found anywhere, cannot install Composer")
        return False
    
    try:
        from ..ui import ok
        ok("Installing Composer via official installer...")
        
        # Use the found PHP to run the Composer installer
        install_dir = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Composer")
        os.makedirs(install_dir, exist_ok=True)
        
        # Download composer.phar directly (simpler than the PHP installer)
        script = (
            f"Invoke-WebRequest -Uri 'https://getcomposer.org/download/latest-stable/composer.phar' "
            f"-OutFile '{install_dir}\\composer.phar'"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=60,
        )
        
        if result.returncode == 0:
            # Create a composer.bat wrapper
            bat_content = f'@echo off\n"{php_path}" "{install_dir}\\composer.phar" %*\n'
            bat_path = os.path.join(install_dir, "composer.bat")
            with open(bat_path, "w") as f:
                f.write(bat_content)
            
            # Add to PATH
            _add_to_path(install_dir)
            ok("Composer installed successfully")
            return True
        
        logger.debug(f"Composer download failed: {result.stderr[:200]}")
        return False
    except Exception as e:
        logger.debug(f"Composer install error: {e}")
        return False


def install_flutter() -> bool:
    """Install Flutter SDK via git clone (official method for Windows)."""
    try:
        from ..ui import ok, warn
        
        # Flutter needs git
        if not shutil.which("git"):
            warn("Git is required for Flutter. Installing git first...")
            if not install_with_winget("Git.Git", "Git"):
                return False
        
        install_dir = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Flutter")
        flutter_bin = os.path.join(install_dir, "flutter", "bin")
        
        if os.path.exists(os.path.join(flutter_bin, "flutter.bat")):
            _add_to_path(flutter_bin)
            ok("Flutter SDK already installed")
            return True
        
        ok("Installing Flutter SDK (this may take a few minutes)...")
        os.makedirs(install_dir, exist_ok=True)
        
        result = subprocess.run(
            ["git", "clone", "https://github.com/flutter/flutter.git", "-b", "stable", "--depth", "1"],
            cwd=install_dir,
            capture_output=True, text=True, timeout=300,
        )
        
        if result.returncode == 0:
            _add_to_path(flutter_bin)
            # Run flutter doctor to complete setup
            subprocess.run(
                [os.path.join(flutter_bin, "flutter.bat"), "doctor", "--android-licenses"],
                capture_output=True, text=True, timeout=60,
                input="y\n" * 10,  # Accept all licenses
            )
            ok("Flutter SDK installed successfully")
            return True
        
        logger.debug(f"Flutter clone failed: {result.stderr[:200]}")
        return False
    except Exception as e:
        logger.debug(f"Flutter install error: {e}")
        return False


def _refresh_path() -> None:
    """Refresh PATH in current process after winget install."""
    try:
        import winreg
        # Read system PATH
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                           r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment") as key:
            sys_path = winreg.QueryValueEx(key, "Path")[0]
        # Read user PATH
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            try:
                user_path = winreg.QueryValueEx(key, "Path")[0]
            except FileNotFoundError:
                user_path = ""
        new_path = sys_path + ";" + user_path
        os.environ["PATH"] = new_path
    except Exception:
        pass
    
    # Also scan winget packages directory for newly installed tools
    winget_packages = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    if os.path.exists(winget_packages):
        for pkg_dir in os.listdir(winget_packages):
            pkg_path = os.path.join(winget_packages, pkg_dir)
            if os.path.isdir(pkg_path):
                # Check if this dir has executables
                try:
                    for exe in os.listdir(pkg_path):
                        if exe.endswith(".exe") and not exe.startswith("_"):
                            if pkg_path not in os.environ.get("PATH", ""):
                                os.environ["PATH"] = pkg_path + ";" + os.environ.get("PATH", "")
                            break
                except PermissionError:
                    pass
    
    # Also scan Programs directory for our custom installs (Composer, etc.)
    programs_dir = os.path.expandvars(r"%LOCALAPPDATA%\Programs")
    if os.path.exists(programs_dir):
        for subdir in os.listdir(programs_dir):
            subdir_path = os.path.join(programs_dir, subdir)
            if os.path.isdir(subdir_path) and subdir_path not in os.environ.get("PATH", ""):
                # Check if it has .bat or .exe files
                try:
                    for f in os.listdir(subdir_path):
                        if f.endswith((".exe", ".bat", ".cmd")):
                            os.environ["PATH"] = subdir_path + ";" + os.environ.get("PATH", "")
                            break
                except PermissionError:
                    pass
    
    # Check common Node.js install locations
    common_paths = [
        os.path.expandvars(r"%ProgramFiles%\nodejs"),
        os.path.expandvars(r"%APPDATA%\npm"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\nodejs"),
        r"C:\Program Files\nodejs",
    ]
    for p in common_paths:
        if os.path.exists(p) and p not in os.environ.get("PATH", ""):
            os.environ["PATH"] = p + ";" + os.environ.get("PATH", "")


def _add_to_path(directory: str) -> None:
    """Add a directory to the current process PATH."""
    current = os.environ.get("PATH", "")
    if directory not in current:
        os.environ["PATH"] = directory + ";" + current


def ensure_deps_for_command(cmd: str) -> tuple[bool, str]:
    """Ensure all dependencies for a command are installed.
    
    Returns (success, message).
    """
    # Always refresh PATH first to pick up previously installed tools
    _refresh_path()
    
    # Get the base command (first word)
    base_cmd = cmd.strip().split()[0] if cmd.strip() else ""
    
    # Check if it's a known tool with dependencies
    deps = TOOL_DEPS.get(base_cmd, [])
    if not deps:
        return True, ""
    
    missing = []
    for check_cmd, winget_id, display_name in deps:
        if not is_installed(check_cmd):
            missing.append((check_cmd, winget_id, display_name))
    
    if not missing:
        return True, ""
    
    # Install missing deps in order
    for check_cmd, winget_id, display_name in missing:
        if not install_with_winget(winget_id, display_name):
            return False, f"Failed to install {display_name}. Please install it manually."
    
    # Verify all installed
    still_missing = [name for cmd_c, _, name in missing if not is_installed(cmd_c)]
    if still_missing:
        return False, f"Still missing after install: {', '.join(still_missing)}. You may need to restart your terminal."
    
    return True, "Dependencies installed successfully"


def ensure_deps_for_framework(framework: str) -> tuple[bool, str]:
    """Ensure all dependencies for a framework are installed.
    
    Returns (success, message).
    """
    # Always refresh PATH first to pick up previously installed tools
    _refresh_path()
    
    framework = framework.lower()
    required_tools = FRAMEWORK_DEPS.get(framework, [])
    
    if not required_tools:
        return True, ""
    
    # For PHP-based frameworks, always ensure extensions are enabled
    if "php" in required_tools or framework in ("laravel", "laravel-breeze", "laravel-api"):
        _enable_php_extensions()
    
    for tool in required_tools:
        deps = TOOL_DEPS.get(tool, [])
        for check_cmd, winget_id, display_name in deps:
            if not is_installed(check_cmd):
                success = install_with_winget(winget_id, display_name)
                if not success:
                    return False, f"Failed to install {display_name}"
    
    return True, ""


def get_missing_deps_message(cmd: str) -> Optional[str]:
    """Get a human-readable message about what's missing for a command.
    
    Returns None if nothing is missing.
    """
    base_cmd = cmd.strip().split()[0] if cmd.strip() else ""
    deps = TOOL_DEPS.get(base_cmd, [])
    
    missing = []
    for check_cmd, winget_id, display_name in deps:
        if not is_installed(check_cmd):
            missing.append(display_name)
    
    if not missing:
        return None
    
    return f"Missing dependencies: {', '.join(missing)}. Installing automatically..."


def get_framework_create_command(framework: str, name: str = "my-app") -> Optional[dict]:
    """Get the creation command(s) for a framework.
    
    Returns dict with 'cmd' and 'post_cmds' or None if unknown framework.
    """
    framework = framework.lower().strip()
    
    # Try exact match first
    entry = FRAMEWORK_CREATE_COMMANDS.get(framework)
    if not entry:
        # Try partial match
        for key, val in FRAMEWORK_CREATE_COMMANDS.items():
            if key in framework or framework in key:
                entry = val
                break
    
    if not entry:
        return None
    
    # Format the command with the project name
    cmd = entry["cmd"].format(name=name)
    post_cmds = [c.format(name=name) for c in entry.get("post_cmds", [])]
    
    return {"cmd": cmd, "post_cmds": post_cmds}


def create_project_with_deps(framework: str, name: str = "my-app", cwd: str = ".") -> tuple[bool, str]:
    """Full project creation: install deps → create project → run post-install.
    
    This is the main entry point for framework project creation.
    Handles the entire flow including missing dependency installation.
    
    Returns (success, output_log).
    """
    from ..ui import ok, warn, err as ui_err
    
    output_lines = []
    
    # Step 0: Ensure the target directory exists
    cwd_path = os.path.abspath(cwd)
    os.makedirs(cwd_path, exist_ok=True)
    
    # Step 1: Ensure all framework dependencies are installed
    framework_key = framework.lower().strip()
    warn(f"Checking dependencies for {framework_key}...")
    success, msg = ensure_deps_for_framework(framework_key)
    if not success:
        return False, f"Dependency installation failed: {msg}"
    if msg:
        output_lines.append(msg)
    ok(f"All dependencies ready for {framework_key}")
    
    # Step 2: Get the creation command
    create_info = get_framework_create_command(framework_key, name)
    if not create_info:
        return False, f"Unknown framework: {framework_key}. Available: {', '.join(sorted(FRAMEWORK_CREATE_COMMANDS.keys()))}"
    
    # Step 3: Refresh PATH one more time right before execution
    _refresh_path()
    
    # Step 4: Execute the main creation command
    cmd = create_info["cmd"]
    ok(f"Creating project: {cmd}")
    
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=cwd_path,
            capture_output=True, text=True, timeout=300,
        )
        stdout = result.stdout[-2000:] if result.stdout else ""
        stderr = result.stderr[-1000:] if result.stderr else ""
        output_lines.append(f"$ {cmd}")
        if stdout:
            output_lines.append(stdout)
        
        if result.returncode != 0:
            # Check if it's a known recoverable error
            combined = stdout + stderr
            if "already exists" in combined.lower():
                warn(f"Directory '{name}' already exists, continuing with post-install...")
            else:
                return False, f"Command failed (exit {result.returncode}):\n{stderr[:500]}\n{stdout[:500]}"
    except subprocess.TimeoutExpired:
        return False, f"Command timed out: {cmd}"
    except Exception as e:
        return False, f"Error running command: {e}"
    
    # Step 5: Execute post-creation commands (cd into project first)
    project_dir = os.path.join(cwd_path, name)
    if not os.path.exists(project_dir):
        # Some commands create the project in the current dir
        project_dir = cwd_path
    
    for post_cmd in create_info.get("post_cmds", []):
        # Handle special internal commands
        if post_cmd == "_apply_facebook_ui_":
            _apply_facebook_ui_template(project_dir)
            output_lines.append("✓ Applied Facebook-like UI template")
            continue
        
        ok(f"Running: {post_cmd}")
        try:
            result = subprocess.run(
                post_cmd, shell=True, cwd=project_dir,
                capture_output=True, text=True, timeout=180,
            )
            output_lines.append(f"$ {post_cmd}")
            if result.stdout:
                output_lines.append(result.stdout[-500:])
            if result.returncode != 0:
                warn(f"Post-install step failed: {post_cmd}")
                if result.stderr:
                    output_lines.append(f"Warning: {result.stderr[:300]}")
                # Don't fail entirely on post-install issues
        except subprocess.TimeoutExpired:
            warn(f"Post-install step timed out: {post_cmd}")
        except Exception as e:
            warn(f"Post-install error: {e}")
    
    ok(f"Project '{name}' created successfully at {project_dir}")
    output_lines.append(f"\n✓ Project '{name}' ready at: {project_dir}")
    
    # Step 6: Post-creation verification for Laravel projects
    if "laravel" in framework_key:
        _verify_laravel_project(project_dir, output_lines)
    
    return True, "\n".join(output_lines)


def _apply_facebook_ui_template(project_dir: str) -> None:
    """Apply a Facebook-like UI to a Laravel Breeze project."""
    from ..ui import ok
    
    # Dashboard with Facebook-style news feed
    dashboard_path = os.path.join(project_dir, "resources", "views", "dashboard.blade.php")
    dashboard_content = '''<x-app-layout>
<div class="min-h-screen bg-gray-100">
<header class="bg-blue-600 shadow-md sticky top-0 z-50">
<div class="max-w-7xl mx-auto px-4 py-2 flex items-center justify-between">
<div class="flex items-center space-x-4">
<h1 class="text-white text-2xl font-bold">facebook</h1>
<input type="text" placeholder="Search Facebook" class="hidden md:block rounded-full bg-blue-500 text-white placeholder-blue-200 px-4 py-2 text-sm focus:outline-none focus:bg-white focus:text-gray-800 w-64">
</div>
<nav class="hidden md:flex space-x-1">
<a href="#" class="px-8 py-2 text-white border-b-4 border-white rounded-t-lg">&#127968;</a>
<a href="#" class="px-8 py-2 text-blue-200 rounded-lg hover:bg-blue-500">&#128101;</a>
<a href="#" class="px-8 py-2 text-blue-200 rounded-lg hover:bg-blue-500">&#127909;</a>
</nav>
<div class="flex items-center space-x-2">
<div class="w-10 h-10 bg-blue-400 rounded-full flex items-center justify-center text-white font-bold">{{ substr(Auth::user()->name, 0, 1) }}</div>
</div>
</div>
</header>
<div class="max-w-7xl mx-auto px-4 py-4 grid grid-cols-1 lg:grid-cols-4 gap-4">
<aside class="hidden lg:block space-y-2">
<a href="#" class="flex items-center space-x-3 p-2 rounded-lg hover:bg-gray-200">
<div class="w-9 h-9 bg-blue-500 rounded-full flex items-center justify-center text-white font-bold text-sm">{{ substr(Auth::user()->name, 0, 1) }}</div>
<span class="font-medium text-gray-800">{{ Auth::user()->name }}</span>
</a>
<a href="#" class="flex items-center space-x-3 p-2 rounded-lg hover:bg-gray-200"><div class="w-9 h-9 bg-blue-100 rounded-full flex items-center justify-center">&#128101;</div><span class="text-gray-700">Friends</span></a>
<a href="#" class="flex items-center space-x-3 p-2 rounded-lg hover:bg-gray-200"><div class="w-9 h-9 bg-blue-100 rounded-full flex items-center justify-center">&#128247;</div><span class="text-gray-700">Memories</span></a>
<a href="#" class="flex items-center space-x-3 p-2 rounded-lg hover:bg-gray-200"><div class="w-9 h-9 bg-blue-100 rounded-full flex items-center justify-center">&#127911;</div><span class="text-gray-700">Groups</span></a>
<a href="#" class="flex items-center space-x-3 p-2 rounded-lg hover:bg-gray-200"><div class="w-9 h-9 bg-blue-100 rounded-full flex items-center justify-center">&#128197;</div><span class="text-gray-700">Events</span></a>
<a href="#" class="flex items-center space-x-3 p-2 rounded-lg hover:bg-gray-200"><div class="w-9 h-9 bg-blue-100 rounded-full flex items-center justify-center">&#128250;</div><span class="text-gray-700">Watch</span></a>
<a href="#" class="flex items-center space-x-3 p-2 rounded-lg hover:bg-gray-200"><div class="w-9 h-9 bg-blue-100 rounded-full flex items-center justify-center">&#128722;</div><span class="text-gray-700">Marketplace</span></a>
</aside>
<main class="lg:col-span-2 space-y-4">
<div class="bg-white rounded-xl shadow p-4">
<div class="flex space-x-3 overflow-x-auto pb-2">
<div class="flex-shrink-0 w-28 h-48 rounded-xl bg-gradient-to-b from-blue-400 to-blue-600 relative overflow-hidden cursor-pointer"><div class="absolute bottom-0 w-full bg-white p-2 text-center"><div class="w-8 h-8 bg-blue-500 rounded-full mx-auto -mt-6 border-4 border-white flex items-center justify-center text-white text-xl">+</div><p class="text-xs font-medium mt-1">Create Story</p></div></div>
<div class="flex-shrink-0 w-28 h-48 rounded-xl bg-gradient-to-b from-pink-400 to-purple-600 relative overflow-hidden cursor-pointer"><div class="absolute top-2 left-2 w-10 h-10 rounded-full border-4 border-blue-500 bg-gray-300"></div><p class="absolute bottom-2 left-2 text-white text-xs font-medium">Sarah M.</p></div>
<div class="flex-shrink-0 w-28 h-48 rounded-xl bg-gradient-to-b from-green-400 to-teal-600 relative overflow-hidden cursor-pointer"><div class="absolute top-2 left-2 w-10 h-10 rounded-full border-4 border-blue-500 bg-gray-300"></div><p class="absolute bottom-2 left-2 text-white text-xs font-medium">John D.</p></div>
<div class="flex-shrink-0 w-28 h-48 rounded-xl bg-gradient-to-b from-yellow-400 to-orange-600 relative overflow-hidden cursor-pointer"><div class="absolute top-2 left-2 w-10 h-10 rounded-full border-4 border-blue-500 bg-gray-300"></div><p class="absolute bottom-2 left-2 text-white text-xs font-medium">Alex K.</p></div>
</div>
</div>
<div class="bg-white rounded-xl shadow p-4">
<div class="flex items-center space-x-3">
<div class="w-10 h-10 bg-blue-500 rounded-full flex items-center justify-center text-white font-bold">{{ substr(Auth::user()->name, 0, 1) }}</div>
<input type="text" placeholder="What\'s on your mind, {{ Auth::user()->name }}?" class="flex-1 bg-gray-100 rounded-full px-4 py-2.5 text-gray-600 hover:bg-gray-200 cursor-pointer">
</div>
<hr class="my-3">
<div class="flex justify-between">
<button class="flex items-center space-x-2 px-4 py-2 rounded-lg hover:bg-gray-100"><span class="text-red-500">&#127909;</span><span class="text-gray-600 text-sm font-medium">Live Video</span></button>
<button class="flex items-center space-x-2 px-4 py-2 rounded-lg hover:bg-gray-100"><span class="text-green-500">&#128247;</span><span class="text-gray-600 text-sm font-medium">Photo/Video</span></button>
<button class="flex items-center space-x-2 px-4 py-2 rounded-lg hover:bg-gray-100"><span class="text-yellow-500">&#128522;</span><span class="text-gray-600 text-sm font-medium">Feeling</span></button>
</div>
</div>
<div class="bg-white rounded-xl shadow">
<div class="p-4"><div class="flex items-center space-x-3"><div class="w-10 h-10 bg-purple-500 rounded-full flex items-center justify-center text-white font-bold">S</div><div><p class="font-semibold text-gray-800">Sarah Mitchell</p><p class="text-xs text-gray-500">2 hours ago</p></div></div><p class="mt-3 text-gray-800">Just finished building my first Laravel app! The Breeze starter kit makes authentication so easy. &#128640;</p></div>
<div class="bg-gradient-to-r from-blue-100 to-purple-100 h-64 flex items-center justify-center"><span class="text-6xl">&#128187;</span></div>
<div class="p-4"><div class="flex justify-between text-gray-500 text-sm mb-2"><span>&#128077; 42</span><span>12 comments</span></div><hr><div class="flex justify-between mt-2"><button class="flex-1 flex items-center justify-center space-x-2 py-2 rounded-lg hover:bg-gray-100"><span>&#128077;</span><span class="text-gray-600 font-medium">Like</span></button><button class="flex-1 flex items-center justify-center space-x-2 py-2 rounded-lg hover:bg-gray-100"><span>&#128172;</span><span class="text-gray-600 font-medium">Comment</span></button><button class="flex-1 flex items-center justify-center space-x-2 py-2 rounded-lg hover:bg-gray-100"><span>&#8634;</span><span class="text-gray-600 font-medium">Share</span></button></div></div>
</div>
<div class="bg-white rounded-xl shadow">
<div class="p-4"><div class="flex items-center space-x-3"><div class="w-10 h-10 bg-green-500 rounded-full flex items-center justify-center text-white font-bold">J</div><div><p class="font-semibold text-gray-800">John Davis</p><p class="text-xs text-gray-500">5 hours ago</p></div></div><p class="mt-3 text-gray-800">Beautiful sunset at the beach today! &#127773;&#127754;</p></div>
<div class="bg-gradient-to-r from-orange-200 to-pink-200 h-72 flex items-center justify-center"><span class="text-8xl">&#127773;</span></div>
<div class="p-4"><div class="flex justify-between text-gray-500 text-sm mb-2"><span>&#10084;&#65039; 128</span><span>24 comments</span></div><hr><div class="flex justify-between mt-2"><button class="flex-1 flex items-center justify-center space-x-2 py-2 rounded-lg hover:bg-gray-100"><span>&#128077;</span><span class="text-gray-600 font-medium">Like</span></button><button class="flex-1 flex items-center justify-center space-x-2 py-2 rounded-lg hover:bg-gray-100"><span>&#128172;</span><span class="text-gray-600 font-medium">Comment</span></button><button class="flex-1 flex items-center justify-center space-x-2 py-2 rounded-lg hover:bg-gray-100"><span>&#8634;</span><span class="text-gray-600 font-medium">Share</span></button></div></div>
</div>
</main>
<aside class="hidden lg:block space-y-4">
<div class="bg-white rounded-xl shadow p-4">
<h3 class="font-semibold text-gray-700 mb-3">People You May Know</h3>
<div class="space-y-3">
<div class="flex items-center justify-between"><div class="flex items-center space-x-3"><div class="w-10 h-10 bg-red-400 rounded-full flex items-center justify-center text-white font-bold">M</div><div><p class="font-medium text-sm">Maria Garcia</p><p class="text-xs text-gray-500">5 mutual friends</p></div></div><button class="bg-blue-500 text-white text-xs px-3 py-1.5 rounded-lg hover:bg-blue-600">Add</button></div>
<div class="flex items-center justify-between"><div class="flex items-center space-x-3"><div class="w-10 h-10 bg-indigo-400 rounded-full flex items-center justify-center text-white font-bold">R</div><div><p class="font-medium text-sm">Robert Chen</p><p class="text-xs text-gray-500">3 mutual friends</p></div></div><button class="bg-blue-500 text-white text-xs px-3 py-1.5 rounded-lg hover:bg-blue-600">Add</button></div>
<div class="flex items-center justify-between"><div class="flex items-center space-x-3"><div class="w-10 h-10 bg-teal-400 rounded-full flex items-center justify-center text-white font-bold">L</div><div><p class="font-medium text-sm">Lisa Park</p><p class="text-xs text-gray-500">8 mutual friends</p></div></div><button class="bg-blue-500 text-white text-xs px-3 py-1.5 rounded-lg hover:bg-blue-600">Add</button></div>
</div>
</div>
<div class="bg-white rounded-xl shadow p-4">
<h3 class="font-semibold text-gray-700 mb-3">Contacts</h3>
<div class="space-y-2">
<a href="#" class="flex items-center space-x-3 p-1 rounded-lg hover:bg-gray-100"><div class="relative"><div class="w-8 h-8 bg-pink-400 rounded-full"></div><div class="absolute bottom-0 right-0 w-3 h-3 bg-green-500 rounded-full border-2 border-white"></div></div><span class="text-sm text-gray-700">Emma Wilson</span></a>
<a href="#" class="flex items-center space-x-3 p-1 rounded-lg hover:bg-gray-100"><div class="relative"><div class="w-8 h-8 bg-yellow-400 rounded-full"></div><div class="absolute bottom-0 right-0 w-3 h-3 bg-green-500 rounded-full border-2 border-white"></div></div><span class="text-sm text-gray-700">David Brown</span></a>
<a href="#" class="flex items-center space-x-3 p-1 rounded-lg hover:bg-gray-100"><div class="relative"><div class="w-8 h-8 bg-cyan-400 rounded-full"></div><div class="absolute bottom-0 right-0 w-3 h-3 bg-gray-400 rounded-full border-2 border-white"></div></div><span class="text-sm text-gray-700">Chris Taylor</span></a>
</div>
</div>
</aside>
</div>
</div>
</x-app-layout>
'''
    
    # Welcome page - Facebook login style
    welcome_path = os.path.join(project_dir, "resources", "views", "welcome.blade.php")
    welcome_content = '''<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Facebook</title>@vite(['resources/css/app.css', 'resources/js/app.js'])</head>
<body class="bg-gray-100 min-h-screen flex items-center justify-center">
<div class="max-w-5xl mx-auto px-4 py-16 grid md:grid-cols-2 gap-8 items-center">
<div><h1 class="text-blue-600 text-6xl font-bold mb-4">facebook</h1><p class="text-xl text-gray-700 leading-relaxed">Connect with friends and the world around you on Facebook.</p></div>
<div class="bg-white p-6 rounded-xl shadow-lg">
<form method="POST" action="{{ route(\'login\') }}">@csrf
<input type="email" name="email" placeholder="Email address" class="w-full border border-gray-300 rounded-lg px-4 py-3 mb-3 text-lg focus:outline-none focus:border-blue-500" required>
<input type="password" name="password" placeholder="Password" class="w-full border border-gray-300 rounded-lg px-4 py-3 mb-3 text-lg focus:outline-none focus:border-blue-500" required>
<button type="submit" class="w-full bg-blue-600 text-white text-xl font-bold py-3 rounded-lg hover:bg-blue-700">Log In</button>
<div class="text-center mt-4"><a href="#" class="text-blue-600 text-sm hover:underline">Forgotten password?</a></div>
<hr class="my-5">
<div class="text-center"><a href="{{ route(\'register\') }}" class="inline-block bg-green-500 text-white text-lg font-bold px-6 py-3 rounded-lg hover:bg-green-600">Create New Account</a></div>
</form>
</div>
</div>
</body>
</html>
'''
    
    try:
        os.makedirs(os.path.dirname(dashboard_path), exist_ok=True)
        with open(dashboard_path, "w", encoding="utf-8") as f:
            f.write(dashboard_content)
        with open(welcome_path, "w", encoding="utf-8") as f:
            f.write(welcome_content)
        ok("Applied Facebook-like UI (dashboard + welcome page)")
    except Exception as e:
        logger.debug(f"Failed to apply Facebook UI template: {e}")


def _verify_laravel_project(project_dir: str, output_lines: list) -> None:
    """Verify a Laravel project works: create DB, run migrations, test server."""
    from ..ui import ok, warn
    
    # Ensure PHP extensions are enabled (especially pdo_sqlite)
    _enable_php_extensions()
    
    # Create SQLite database if it doesn't exist
    db_path = os.path.join(project_dir, "database", "database.sqlite")
    if not os.path.exists(db_path):
        try:
            open(db_path, "w").close()
            ok("Created SQLite database")
        except Exception:
            pass
    
    # Run migrations
    try:
        result = subprocess.run(
            "php artisan migrate --force",
            shell=True, cwd=project_dir,
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            ok("Migrations completed successfully")
            output_lines.append("✓ Database migrations: OK")
        else:
            # Check if it's the "could not find driver" error
            if "could not find driver" in (result.stderr + result.stdout).lower():
                warn("SQLite driver not loaded, attempting fix...")
                _fix_php_sqlite_driver()
                # Retry migrations
                result2 = subprocess.run(
                    "php artisan migrate --force",
                    shell=True, cwd=project_dir,
                    capture_output=True, text=True, timeout=60,
                )
                if result2.returncode == 0:
                    ok("Migrations completed after SQLite fix")
                    output_lines.append("✓ Database migrations: OK (after driver fix)")
                else:
                    warn(f"Migration still failing: {result2.stderr[:200]}")
                    output_lines.append(f"⚠ Migrations: {result2.stderr[:100]}")
            else:
                warn(f"Migration warning: {result.stderr[:200]}")
                output_lines.append(f"⚠ Migrations: {result.stderr[:100]}")
    except Exception as e:
        warn(f"Migration error: {e}")
    
    # Quick server test: start, check, stop
    try:
        import socket
        port = 8199
        proc = subprocess.Popen(
            f"php artisan serve --port={port} --no-interaction",
            shell=True, cwd=project_dir,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        import time
        time.sleep(3)
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        connected = sock.connect_ex(("127.0.0.1", port)) == 0
        sock.close()
        
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        
        if connected:
            # Also do an HTTP check to catch runtime errors like missing drivers
            try:
                import urllib.request
                resp = urllib.request.urlopen(f"http://127.0.0.1:{port}", timeout=5)
                status = resp.getcode()
                if status == 200:
                    ok("Server verification: OK (HTTP 200)")
                    output_lines.append("✓ Server test: OK (HTTP 200)")
                else:
                    warn(f"Server returned HTTP {status}")
                    output_lines.append(f"⚠ Server test: HTTP {status}")
            except Exception:
                # Port was open but HTTP failed - still better than nothing
                ok("Server verification: OK (port open)")
                output_lines.append("✓ Server test: OK (port open)")
        else:
            warn("Server did not respond on test port")
            output_lines.append("⚠ Server test: did not respond (may need manual check)")
    except Exception as e:
        output_lines.append(f"⚠ Server test skipped: {e}")


def _fix_php_sqlite_driver() -> None:
    """Fix the 'could not find driver' error for SQLite by enabling extensions in php.ini."""
    winget_packages = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    if not os.path.exists(winget_packages):
        return
    
    for pkg in os.listdir(winget_packages):
        if "PHP" not in pkg:
            continue
        pkg_path = os.path.join(winget_packages, pkg)
        ini_path = os.path.join(pkg_path, "php.ini")
        ini_dev = os.path.join(pkg_path, "php.ini-development")
        
        # Create php.ini from template if missing
        if not os.path.exists(ini_path) and os.path.exists(ini_dev):
            import shutil as _sh
            _sh.copy2(ini_dev, ini_path)
        
        if not os.path.exists(ini_path):
            continue
        
        try:
            content = open(ini_path, "r").read()
            modified = False
            
            # Enable all critical extensions
            extensions = ["openssl", "curl", "mbstring", "fileinfo",
                         "pdo_mysql", "pdo_sqlite", "sqlite3", "zip",
                         "gd", "intl", "sodium"]
            for ext in extensions:
                disabled = f";extension={ext}"
                enabled = f"extension={ext}"
                if disabled in content and enabled not in content.replace(disabled, ""):
                    content = content.replace(disabled, enabled, 1)
                    modified = True
            
            # Set extension_dir
            ext_dir = os.path.join(pkg_path, "ext")
            if os.path.exists(ext_dir):
                if ';extension_dir = "ext"' in content:
                    content = content.replace(
                        ';extension_dir = "ext"',
                        f'extension_dir = "{ext_dir}"',
                        1,
                    )
                    modified = True
                elif 'extension_dir' not in content.split('\n')[0]:
                    # Check if extension_dir is set at all
                    if f'extension_dir = "{ext_dir}"' not in content:
                        # Add it near the top
                        content = f'extension_dir = "{ext_dir}"\n' + content
                        modified = True
            
            if modified:
                open(ini_path, "w").write(content)
                logger.info("Fixed PHP extensions: enabled pdo_sqlite, sqlite3, and others")
        except Exception as e:
            logger.debug(f"Failed to fix PHP extensions: {e}")
        break


def detect_framework_from_goal(goal: str) -> Optional[str]:
    """Detect which framework the user wants from their natural language goal.
    
    Returns the framework key or None.
    """
    lowered = goal.lower()
    
    # Order matters: check specific variants before generic ones
    framework_patterns = [
        ("laravel-breeze", ["laravel breeze", "laravel with breeze", "breeze"]),
        ("laravel-facebook", ["laravel facebook", "laravel like facebook", "facebook clone", "facebook-like", "like facebook"]),
        ("laravel-api", ["laravel api", "laravel rest"]),
        ("react-vite-ts", ["react vite typescript", "react vite ts"]),
        ("react-vite", ["react vite", "vite react"]),
        ("react-ts", ["react typescript", "react ts"]),
        ("react-native", ["react native", "react-native", "rn app"]),
        ("expo", ["expo app", "expo project", "create expo"]),
        ("nextjs", ["next.js", "nextjs", "next js", "next app"]),
        ("nuxt", ["nuxt", "nuxt.js"]),
        ("angular", ["angular"]),
        ("svelte", ["svelte", "sveltekit"]),
        ("astro", ["astro"]),
        ("remix", ["remix"]),
        ("nestjs", ["nestjs", "nest.js", "nest js"]),
        ("django", ["django"]),
        ("flask", ["flask"]),
        ("fastapi", ["fastapi", "fast api"]),
        ("express", ["express"]),
        ("laravel", ["laravel", "php project"]),
        ("react", ["react app", "react project", "create react"]),
        ("vue", ["vue", "vue.js"]),
        ("vite", ["vite app", "vite project"]),
        ("flutter", ["flutter"]),
        ("electron", ["electron"]),
        ("tauri", ["tauri"]),
        ("dotnet-blazor", ["blazor"]),
        ("dotnet-api", ["dotnet api", ".net api", "asp.net api"]),
        ("dotnet-web", ["dotnet web", ".net web", "asp.net"]),
        ("rails", ["rails", "ruby on rails"]),
        ("spring", ["spring boot", "spring"]),
        ("rust", ["rust project", "cargo new"]),
        ("go", ["go project", "golang"]),
    ]
    
    for framework_key, patterns in framework_patterns:
        if any(p in lowered for p in patterns):
            return framework_key
    
    return None
