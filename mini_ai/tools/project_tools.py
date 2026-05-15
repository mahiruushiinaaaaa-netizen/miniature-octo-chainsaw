"""
project_tools.py – Project initialization and configuration management.

Covers: project scaffolding for various frameworks, .env management,
config file operations (JSON, YAML, TOML, INI), dependency file generation.
"""
from __future__ import annotations

import configparser
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


def project_init(template: str, name: str, path: str = ".", options: str = "") -> dict[str, Any]:
    """Initialize a new project from a template.
    
    Templates: python, node, react, vue, next, express, flask, fastapi, django,
               rust, go, dotnet_console, dotnet_webapi, vite, svelte, angular
    """
    target = Path(path) / name
    template = template.lower().strip()
    
    creators = {
        "python": _init_python,
        "node": _init_node,
        "react": _init_react,
        "vue": _init_vue,
        "next": _init_next,
        "express": _init_express,
        "flask": _init_flask,
        "fastapi": _init_fastapi,
        "django": _init_django,
        "rust": _init_rust,
        "go": _init_go,
        "vite": _init_vite,
        "svelte": _init_svelte,
        "angular": _init_angular,
    }
    
    creator = creators.get(template)
    if not creator:
        available = ", ".join(sorted(creators.keys()))
        return {"success": False, "error": f"Unknown template: {template}. Available: {available}"}
    
    return creator(name, str(target), options)


def env_file_manage(operation: str, path: str = ".env", key: str = "", value: str = "") -> dict[str, Any]:
    """Manage .env files.
    
    Operations: read, set, unset, list, create, validate
    """
    env_path = Path(path)
    op = operation.lower().strip()
    
    if op == "create":
        if env_path.exists():
            return {"success": False, "error": f"{path} already exists"}
        env_path.write_text("# Environment Variables\n", encoding="utf-8")
        return {"success": True, "result": f"Created {path}"}
    
    if op == "read":
        if not env_path.exists():
            return {"success": False, "error": f"{path} not found"}
        content = env_path.read_text(encoding="utf-8")
        # Mask sensitive values
        masked = re.sub(r"((?:PASSWORD|SECRET|KEY|TOKEN|API_KEY)\s*=\s*)(.+)", r"\1****", content, flags=re.IGNORECASE)
        return {"success": True, "result": masked}
    
    if op == "list":
        if not env_path.exists():
            return {"success": False, "error": f"{path} not found"}
        content = env_path.read_text(encoding="utf-8")
        keys = []
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k = line.split("=", 1)[0].strip()
                keys.append(k)
        return {"success": True, "result": "\n".join(keys) if keys else "(empty)"}
    
    if op == "set":
        if not key:
            return {"success": False, "error": "Key name required"}
        
        lines = []
        found = False
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines):
                if line.strip().startswith(f"{key}=") or line.strip().startswith(f"{key} ="):
                    lines[i] = f"{key}={value}"
                    found = True
                    break
        
        if not found:
            lines.append(f"{key}={value}")
        
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"success": True, "result": f"Set {key} in {path}"}
    
    if op == "unset":
        if not key:
            return {"success": False, "error": "Key name required"}
        if not env_path.exists():
            return {"success": False, "error": f"{path} not found"}
        
        lines = env_path.read_text(encoding="utf-8").splitlines()
        new_lines = [l for l in lines if not l.strip().startswith(f"{key}=") and not l.strip().startswith(f"{key} =")]
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return {"success": True, "result": f"Removed {key} from {path}"}
    
    if op == "validate":
        if not env_path.exists():
            return {"success": False, "error": f"{path} not found"}
        content = env_path.read_text(encoding="utf-8")
        issues = []
        for i, line in enumerate(content.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                issues.append(f"Line {i}: Missing '=' separator")
            elif line.startswith("="):
                issues.append(f"Line {i}: Empty key name")
        
        if issues:
            return {"success": False, "error": "Validation issues:\n" + "\n".join(issues)}
        return {"success": True, "result": "Valid .env file"}
    
    return {"success": False, "error": f"Unknown operation: {op}"}


def config_file(operation: str, path: str, key: str = "", value: str = "", format: str = "auto") -> dict[str, Any]:
    """Read/write configuration files (JSON, TOML, INI, YAML).
    
    Operations: read, get, set, delete, keys
    """
    file_path = Path(path)
    op = operation.lower().strip()
    
    # Auto-detect format
    if format == "auto":
        ext = file_path.suffix.lower()
        format_map = {".json": "json", ".toml": "toml", ".ini": "ini", ".cfg": "ini", ".yaml": "yaml", ".yml": "yaml"}
        format = format_map.get(ext, "json")
    
    if op == "read":
        if not file_path.exists():
            return {"success": False, "error": f"File not found: {path}"}
        content = file_path.read_text(encoding="utf-8")
        if len(content) > 5000:
            content = content[:5000] + "\n...[truncated]"
        return {"success": True, "result": content}
    
    if format == "json":
        return _config_json(op, file_path, key, value)
    elif format == "ini":
        return _config_ini(op, file_path, key, value)
    else:
        # For TOML/YAML, just read/write as text
        return _config_text(op, file_path, key, value)


def dependency_check(path: str = ".") -> dict[str, Any]:
    """Check project dependencies and their status.
    
    Auto-detects package.json, requirements.txt, Cargo.toml, go.mod, etc.
    """
    target = Path(path)
    results = []
    
    # Check package.json
    pkg_json = target / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            deps = data.get("dependencies", {})
            dev_deps = data.get("devDependencies", {})
            results.append(f"Node.js (package.json):")
            results.append(f"  Dependencies: {len(deps)}")
            results.append(f"  Dev dependencies: {len(dev_deps)}")
            for name, ver in list(deps.items())[:10]:
                results.append(f"    {name}: {ver}")
        except Exception:
            pass
    
    # Check requirements.txt
    req_txt = target / "requirements.txt"
    if req_txt.exists():
        try:
            lines = [l.strip() for l in req_txt.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
            results.append(f"\nPython (requirements.txt):")
            results.append(f"  Packages: {len(lines)}")
            for line in lines[:15]:
                results.append(f"    {line}")
        except Exception:
            pass
    
    # Check pyproject.toml
    pyproject = target / "pyproject.toml"
    if pyproject.exists():
        try:
            content = pyproject.read_text(encoding="utf-8")
            deps_match = re.findall(r'^\s*"?([a-zA-Z][\w.-]+)"?\s*[>=<]', content, re.MULTILINE)
            results.append(f"\nPython (pyproject.toml):")
            results.append(f"  Dependencies found: {len(deps_match)}")
        except Exception:
            pass
    
    # Check Cargo.toml
    cargo = target / "Cargo.toml"
    if cargo.exists():
        try:
            content = cargo.read_text(encoding="utf-8")
            deps_section = re.findall(r'(\w[\w-]+)\s*=', content)
            results.append(f"\nRust (Cargo.toml): found")
        except Exception:
            pass
    
    # Check go.mod
    gomod = target / "go.mod"
    if gomod.exists():
        try:
            content = gomod.read_text(encoding="utf-8")
            requires = re.findall(r"require\s+\(([^)]+)\)", content, re.DOTALL)
            results.append(f"\nGo (go.mod): found")
        except Exception:
            pass
    
    # Check composer.json
    composer = target / "composer.json"
    if composer.exists():
        try:
            data = json.loads(composer.read_text(encoding="utf-8"))
            deps = data.get("require", {})
            results.append(f"\nPHP (composer.json):")
            results.append(f"  Dependencies: {len(deps)}")
        except Exception:
            pass
    
    if not results:
        return {"success": True, "result": "No dependency files found in this directory"}
    
    return {"success": True, "result": "\n".join(results)}


# --- Project Initializers ---

def _init_python(name: str, path: str, options: str) -> dict[str, Any]:
    """Initialize a Python project."""
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    
    (target / name.replace("-", "_")).mkdir(exist_ok=True)
    (target / name.replace("-", "_") / "__init__.py").write_text('"""' + name + ' package."""\n', encoding="utf-8")
    (target / "tests").mkdir(exist_ok=True)
    (target / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (target / "README.md").write_text(f"# {name}\n\n## Installation\n\n```bash\npip install -e .\n```\n", encoding="utf-8")
    (target / "requirements.txt").write_text("", encoding="utf-8")
    (target / ".gitignore").write_text("__pycache__/\n*.pyc\n.venv/\ndist/\n*.egg-info/\n.env\n", encoding="utf-8")
    (target / "pyproject.toml").write_text(f'[project]\nname = "{name}"\nversion = "0.1.0"\nrequires-python = ">=3.9"\n\n[build-system]\nrequires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"\n', encoding="utf-8")
    
    return {"success": True, "result": f"Created Python project at {path}"}


def _init_node(name: str, path: str, options: str) -> dict[str, Any]:
    """Initialize a Node.js project."""
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    
    pkg = {"name": name, "version": "1.0.0", "main": "index.js", "scripts": {"start": "node index.js", "test": "echo \"Error: no test specified\" && exit 1"}}
    (target / "package.json").write_text(json.dumps(pkg, indent=2), encoding="utf-8")
    (target / "index.js").write_text('console.log("Hello from ' + name + '");\n', encoding="utf-8")
    (target / ".gitignore").write_text("node_modules/\n.env\ndist/\n", encoding="utf-8")
    (target / "README.md").write_text(f"# {name}\n\n## Setup\n\n```bash\nnpm install\nnpm start\n```\n", encoding="utf-8")
    
    return {"success": True, "result": f"Created Node.js project at {path}"}


def _init_react(name: str, path: str, options: str) -> dict[str, Any]:
    """Initialize React project via create-react-app or vite."""
    try:
        result = subprocess.run(["npx", "create-vite@latest", name, "--template", "react"], cwd=str(Path(path).parent), capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            return {"success": True, "result": f"Created React project at {path}"}
        return {"success": False, "error": result.stderr.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _init_vue(name: str, path: str, options: str) -> dict[str, Any]:
    try:
        result = subprocess.run(["npx", "create-vite@latest", name, "--template", "vue"], cwd=str(Path(path).parent), capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            return {"success": True, "result": f"Created Vue project at {path}"}
        return {"success": False, "error": result.stderr.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _init_next(name: str, path: str, options: str) -> dict[str, Any]:
    try:
        result = subprocess.run(["npx", "create-next-app@latest", name, "--use-npm", "--ts"], cwd=str(Path(path).parent), capture_output=True, text=True, timeout=180)
        if result.returncode == 0:
            return {"success": True, "result": f"Created Next.js project at {path}"}
        return {"success": False, "error": result.stderr.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _init_express(name: str, path: str, options: str) -> dict[str, Any]:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    pkg = {"name": name, "version": "1.0.0", "main": "index.js", "scripts": {"start": "node index.js", "dev": "nodemon index.js"}, "dependencies": {"express": "^4.18.0"}}
    (target / "package.json").write_text(json.dumps(pkg, indent=2), encoding="utf-8")
    (target / "index.js").write_text("const express = require('express');\nconst app = express();\nconst PORT = process.env.PORT || 3000;\n\napp.use(express.json());\n\napp.get('/', (req, res) => res.json({ message: 'Hello World' }));\n\napp.listen(PORT, () => console.log(`Server running on port ${PORT}`));\n", encoding="utf-8")
    (target / ".gitignore").write_text("node_modules/\n.env\n", encoding="utf-8")
    return {"success": True, "result": f"Created Express project at {path}. Run: npm install"}


def _init_flask(name: str, path: str, options: str) -> dict[str, Any]:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    (target / "app.py").write_text("from flask import Flask, jsonify\n\napp = Flask(__name__)\n\n@app.route('/')\ndef index():\n    return jsonify({'message': 'Hello World'})\n\nif __name__ == '__main__':\n    app.run(debug=True)\n", encoding="utf-8")
    (target / "requirements.txt").write_text("flask>=3.0\n", encoding="utf-8")
    (target / ".gitignore").write_text("__pycache__/\n.venv/\n.env\n", encoding="utf-8")
    return {"success": True, "result": f"Created Flask project at {path}. Run: pip install -r requirements.txt"}


def _init_fastapi(name: str, path: str, options: str) -> dict[str, Any]:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    (target / "main.py").write_text("from fastapi import FastAPI\n\napp = FastAPI()\n\n@app.get('/')\nasync def root():\n    return {'message': 'Hello World'}\n", encoding="utf-8")
    (target / "requirements.txt").write_text("fastapi>=0.100\nuvicorn[standard]>=0.20\n", encoding="utf-8")
    (target / ".gitignore").write_text("__pycache__/\n.venv/\n.env\n", encoding="utf-8")
    return {"success": True, "result": f"Created FastAPI project at {path}. Run: pip install -r requirements.txt && uvicorn main:app --reload"}


def _init_django(name: str, path: str, options: str) -> dict[str, Any]:
    try:
        result = subprocess.run(["django-admin", "startproject", name, path], capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return {"success": True, "result": f"Created Django project at {path}"}
        return {"success": False, "error": result.stderr.strip() or "django-admin failed. Install Django first: pip install django"}
    except FileNotFoundError:
        return {"success": False, "error": "Django not installed. Run: pip install django"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _init_rust(name: str, path: str, options: str) -> dict[str, Any]:
    try:
        result = subprocess.run(["cargo", "new", name], cwd=str(Path(path).parent), capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return {"success": True, "result": f"Created Rust project at {path}"}
        return {"success": False, "error": result.stderr.strip()}
    except FileNotFoundError:
        return {"success": False, "error": "Cargo not installed. Install Rust: https://rustup.rs"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _init_go(name: str, path: str, options: str) -> dict[str, Any]:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    (target / "main.go").write_text(f'package main\n\nimport "fmt"\n\nfunc main() {{\n\tfmt.Println("Hello from {name}")\n}}\n', encoding="utf-8")
    try:
        subprocess.run(["go", "mod", "init", name], cwd=str(target), capture_output=True, text=True, timeout=10)
    except Exception:
        pass
    return {"success": True, "result": f"Created Go project at {path}"}


def _init_vite(name: str, path: str, options: str) -> dict[str, Any]:
    try:
        template = options or "vanilla-ts"
        result = subprocess.run(["npx", "create-vite@latest", name, "--template", template], cwd=str(Path(path).parent), capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            return {"success": True, "result": f"Created Vite project at {path}"}
        return {"success": False, "error": result.stderr.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _init_svelte(name: str, path: str, options: str) -> dict[str, Any]:
    try:
        result = subprocess.run(["npx", "create-vite@latest", name, "--template", "svelte-ts"], cwd=str(Path(path).parent), capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            return {"success": True, "result": f"Created Svelte project at {path}"}
        return {"success": False, "error": result.stderr.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _init_angular(name: str, path: str, options: str) -> dict[str, Any]:
    try:
        result = subprocess.run(["npx", "@angular/cli", "new", name, "--skip-install"], cwd=str(Path(path).parent), capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            return {"success": True, "result": f"Created Angular project at {path}"}
        return {"success": False, "error": result.stderr.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


# --- Config file helpers ---

def _config_json(op: str, file_path: Path, key: str, value: str) -> dict[str, Any]:
    if op == "get":
        if not file_path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}
        data = json.loads(file_path.read_text(encoding="utf-8"))
        # Navigate dot-notation key
        parts = key.split(".") if key else []
        current = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                current = current[int(part)]
            else:
                return {"success": False, "error": f"Key not found: {key}"}
        return {"success": True, "result": json.dumps(current, indent=2) if isinstance(current, (dict, list)) else str(current)}
    
    elif op == "set":
        data = {}
        if file_path.exists():
            data = json.loads(file_path.read_text(encoding="utf-8"))
        # Set nested key
        parts = key.split(".")
        current = data
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        # Try to parse value as JSON
        try:
            current[parts[-1]] = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            current[parts[-1]] = value
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return {"success": True, "result": f"Set {key} = {value}"}
    
    elif op == "delete":
        if not file_path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}
        data = json.loads(file_path.read_text(encoding="utf-8"))
        parts = key.split(".")
        current = data
        for part in parts[:-1]:
            current = current.get(part, {})
        if parts[-1] in current:
            del current[parts[-1]]
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return {"success": True, "result": f"Deleted key: {key}"}
    
    elif op == "keys":
        if not file_path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}
        data = json.loads(file_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {"success": True, "result": "\n".join(data.keys())}
        return {"success": True, "result": f"Root is {type(data).__name__}, not a dict"}
    
    return {"success": False, "error": f"Unknown operation: {op}"}


def _config_ini(op: str, file_path: Path, key: str, value: str) -> dict[str, Any]:
    config = configparser.ConfigParser()
    if file_path.exists():
        config.read(str(file_path), encoding="utf-8")
    
    if op == "get":
        # key format: section.key
        parts = key.split(".", 1)
        if len(parts) == 2:
            return {"success": True, "result": config.get(parts[0], parts[1], fallback="(not found)")}
        elif len(parts) == 1:
            if config.has_section(parts[0]):
                items = dict(config.items(parts[0]))
                return {"success": True, "result": json.dumps(items, indent=2)}
        return {"success": False, "error": "Key format: section.key"}
    
    elif op == "set":
        parts = key.split(".", 1)
        if len(parts) != 2:
            return {"success": False, "error": "Key format: section.key"}
        if not config.has_section(parts[0]):
            config.add_section(parts[0])
        config.set(parts[0], parts[1], value)
        with open(file_path, "w", encoding="utf-8") as f:
            config.write(f)
        return {"success": True, "result": f"Set [{parts[0]}] {parts[1]} = {value}"}
    
    elif op == "keys":
        sections = config.sections()
        return {"success": True, "result": "\n".join(sections) if sections else "(empty)"}
    
    return {"success": False, "error": f"Unknown operation: {op}"}


def _config_text(op: str, file_path: Path, key: str, value: str) -> dict[str, Any]:
    """Generic text-based config operations."""
    if op == "get":
        if not file_path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}
        content = file_path.read_text(encoding="utf-8")
        # Search for key = value pattern
        pattern = re.compile(rf"^{re.escape(key)}\s*[=:]\s*(.+)$", re.MULTILINE)
        match = pattern.search(content)
        if match:
            return {"success": True, "result": match.group(1).strip()}
        return {"success": False, "error": f"Key not found: {key}"}
    
    elif op == "set":
        content = ""
        if file_path.exists():
            content = file_path.read_text(encoding="utf-8")
        pattern = re.compile(rf"^({re.escape(key)}\s*[=:]\s*)(.+)$", re.MULTILINE)
        if pattern.search(content):
            content = pattern.sub(rf"\g<1>{value}", content)
        else:
            content += f"\n{key} = {value}\n"
        file_path.write_text(content, encoding="utf-8")
        return {"success": True, "result": f"Set {key} = {value}"}
    
    return {"success": False, "error": f"Unknown operation: {op}"}
