"""
archive_tools.py – Archive creation/extraction and code scaffolding tools.
"""
from __future__ import annotations

import os
import shutil
import tarfile
import zipfile
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Archive Tool
# ---------------------------------------------------------------------------

def archive_op(operation: str, path_str: str, files: list[str] | None = None,
               destination: str | None = None, fmt: str | None = None) -> dict[str, Any]:
    """Create, extract, or list archive contents.
    
    Supports: zip, tar, tar.gz, tar.bz2
    """
    operation = operation.lower().strip()
    path = Path(path_str)
    
    if operation == "create":
        return _archive_create(path, files or [], fmt)
    elif operation == "extract":
        return _archive_extract(path, destination)
    elif operation == "list":
        return _archive_list(path)
    else:
        return {"success": False, "error": f"Unknown operation: {operation}. Use: create, extract, list"}


def _archive_create(output_path: Path, files: list[str], fmt: str | None) -> dict[str, Any]:
    """Create an archive from a list of files."""
    if not files:
        return {"success": False, "error": "No files specified for archive creation"}
    
    # Auto-detect format from extension
    if fmt is None:
        suffix = "".join(output_path.suffixes).lower()
        if suffix in (".tar.gz", ".tgz"):
            fmt = "tar.gz"
        elif suffix in (".tar.bz2", ".tbz2"):
            fmt = "tar.bz2"
        elif suffix == ".tar":
            fmt = "tar"
        else:
            fmt = "zip"
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        added = []
        if fmt == "zip":
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in files:
                    p = Path(f)
                    if p.is_file():
                        zf.write(p, p.name)
                        added.append(p.name)
                    elif p.is_dir():
                        for child in p.rglob("*"):
                            if child.is_file():
                                arcname = str(child.relative_to(p.parent))
                                zf.write(child, arcname)
                                added.append(arcname)
        else:
            mode = "w:gz" if fmt == "tar.gz" else "w:bz2" if fmt == "tar.bz2" else "w"
            with tarfile.open(output_path, mode) as tf:
                for f in files:
                    p = Path(f)
                    if p.exists():
                        tf.add(p, arcname=p.name)
                        added.append(p.name)
        
        size = output_path.stat().st_size
        return {
            "success": True,
            "result": f"Created {fmt} archive: {output_path}\nFiles: {len(added)}\nSize: {size} bytes",
            "files_added": len(added),
        }
    except Exception as e:
        return {"success": False, "error": f"Archive creation failed: {e}"}


def _archive_extract(archive_path: Path, destination: str | None) -> dict[str, Any]:
    """Extract an archive."""
    if not archive_path.exists():
        return {"success": False, "error": f"Archive not found: {archive_path}"}
    
    dest = Path(destination) if destination else archive_path.parent / archive_path.stem
    dest.mkdir(parents=True, exist_ok=True)
    
    try:
        suffix = "".join(archive_path.suffixes).lower()
        extracted = 0
        
        if suffix in (".zip",):
            with zipfile.ZipFile(archive_path, "r") as zf:
                # Security: check for path traversal
                for name in zf.namelist():
                    if name.startswith("/") or ".." in name:
                        return {"success": False, "error": f"Unsafe path in archive: {name}"}
                zf.extractall(dest)
                extracted = len(zf.namelist())
        elif suffix in (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz"):
            with tarfile.open(archive_path, "r:*") as tf:
                # Security: check for path traversal
                for member in tf.getmembers():
                    if member.name.startswith("/") or ".." in member.name:
                        return {"success": False, "error": f"Unsafe path in archive: {member.name}"}
                tf.extractall(dest, filter="data")
                extracted = len(tf.getmembers())
        else:
            return {"success": False, "error": f"Unsupported archive format: {suffix}"}
        
        return {
            "success": True,
            "result": f"Extracted {extracted} items to: {dest}",
            "destination": str(dest),
            "items": extracted,
        }
    except Exception as e:
        return {"success": False, "error": f"Extraction failed: {e}"}


def _archive_list(archive_path: Path) -> dict[str, Any]:
    """List archive contents."""
    if not archive_path.exists():
        return {"success": False, "error": f"Archive not found: {archive_path}"}
    
    try:
        suffix = "".join(archive_path.suffixes).lower()
        items = []
        
        if suffix in (".zip",):
            with zipfile.ZipFile(archive_path, "r") as zf:
                for info in zf.infolist():
                    items.append(f"{'D' if info.is_dir() else 'F'} {info.file_size:>10} {info.filename}")
        elif suffix in (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz"):
            with tarfile.open(archive_path, "r:*") as tf:
                for member in tf.getmembers():
                    kind = "D" if member.isdir() else "F"
                    items.append(f"{kind} {member.size:>10} {member.name}")
        else:
            return {"success": False, "error": f"Unsupported format: {suffix}"}
        
        header = f"Archive: {archive_path.name} ({len(items)} items)\n{'='*50}"
        return {"success": True, "result": header + "\n" + "\n".join(items[:100])}
    except Exception as e:
        return {"success": False, "error": f"List failed: {e}"}


# ---------------------------------------------------------------------------
# Scaffold Tool
# ---------------------------------------------------------------------------

_TEMPLATES: dict[str, callable] = {}


def scaffold(template: str, name: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generate code scaffolds and boilerplate."""
    template = template.lower().strip()
    options = options or {}
    
    generators = {
        "api_endpoint": _scaffold_api_endpoint,
        "react_component": _scaffold_react_component,
        "python_class": _scaffold_python_class,
        "test_file": _scaffold_test_file,
        "dockerfile": _scaffold_dockerfile,
        "github_action": _scaffold_github_action,
        "readme": _scaffold_readme,
        "gitignore": _scaffold_gitignore,
        "env_file": _scaffold_env_file,
        "express_app": _scaffold_express_app,
        "flask_app": _scaffold_flask_app,
        "fastapi_app": _scaffold_fastapi_app,
    }
    
    generator = generators.get(template)
    if not generator:
        available = ", ".join(sorted(generators.keys()))
        return {"success": False, "error": f"Unknown template: {template}. Available: {available}"}
    
    try:
        content = generator(name, options)
        return {"success": True, "result": content, "template": template, "name": name}
    except Exception as e:
        return {"success": False, "error": f"Scaffold generation failed: {e}"}


def _scaffold_api_endpoint(name: str, options: dict) -> str:
    framework = options.get("framework", "express")
    if framework == "express":
        return f'''const express = require('express');
const router = express.Router();

// GET /{name}
router.get('/', async (req, res) => {{
  try {{
    // TODO: Implement list {name}
    res.json({{ data: [], message: 'List {name}' }});
  }} catch (error) {{
    res.status(500).json({{ error: error.message }});
  }}
}});

// GET /{name}/:id
router.get('/:id', async (req, res) => {{
  try {{
    const {{ id }} = req.params;
    // TODO: Implement get {name} by id
    res.json({{ data: null, message: `Get {name} ${{id}}` }});
  }} catch (error) {{
    res.status(500).json({{ error: error.message }});
  }}
}});

// POST /{name}
router.post('/', async (req, res) => {{
  try {{
    const data = req.body;
    // TODO: Implement create {name}
    res.status(201).json({{ data, message: '{name} created' }});
  }} catch (error) {{
    res.status(500).json({{ error: error.message }});
  }}
}});

// PUT /{name}/:id
router.put('/:id', async (req, res) => {{
  try {{
    const {{ id }} = req.params;
    const data = req.body;
    // TODO: Implement update {name}
    res.json({{ data, message: `{name} ${{id}} updated` }});
  }} catch (error) {{
    res.status(500).json({{ error: error.message }});
  }}
}});

// DELETE /{name}/:id
router.delete('/:id', async (req, res) => {{
  try {{
    const {{ id }} = req.params;
    // TODO: Implement delete {name}
    res.json({{ message: `{name} ${{id}} deleted` }});
  }} catch (error) {{
    res.status(500).json({{ error: error.message }});
  }}
}});

module.exports = router;
'''
    elif framework == "fastapi":
        class_name = name.title().replace("_", "").replace("-", "")
        return f'''from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/{name}", tags=["{name}"])


class {class_name}Create(BaseModel):
    name: str
    # TODO: Add fields


class {class_name}Response(BaseModel):
    id: int
    name: str


@router.get("/")
async def list_{name}():
    """List all {name}."""
    return {{"data": []}}


@router.get("/{{item_id}}")
async def get_{name}(item_id: int):
    """Get {name} by ID."""
    # TODO: Implement
    raise HTTPException(status_code=404, detail="{name} not found")


@router.post("/", status_code=201)
async def create_{name}(item: {class_name}Create):
    """Create a new {name}."""
    return {{"data": item.dict(), "message": "Created"}}


@router.put("/{{item_id}}")
async def update_{name}(item_id: int, item: {class_name}Create):
    """Update {name}."""
    return {{"data": item.dict(), "message": "Updated"}}


@router.delete("/{{item_id}}")
async def delete_{name}(item_id: int):
    """Delete {name}."""
    return {{"message": "Deleted"}}
'''
    return f"// API endpoint scaffold for: {name}"


def _scaffold_react_component(name: str, options: dict) -> str:
    use_ts = options.get("typescript", True)
    ext = "tsx" if use_ts else "jsx"
    props_type = f"\ninterface {name}Props {{\n  // TODO: Define props\n}}\n" if use_ts else ""
    props_param = f": {name}Props" if use_ts else ""
    return f'''{props_type}
export default function {name}(props{props_param}) {{
  return (
    <div className="{name.lower()}">
      <h2>{name}</h2>
      {{/* TODO: Implement component */}}
    </div>
  );
}}
'''


def _scaffold_python_class(name: str, options: dict) -> str:
    base = options.get("base", "")
    inherit = f"({base})" if base else ""
    return f'''"""
{name} module.
"""
from __future__ import annotations

from typing import Any, Optional


class {name}{inherit}:
    """{name} class.
    
    TODO: Add description.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialize {name}."""
        super().__init__(**kwargs) if {bool(base)} else None
        # TODO: Initialize attributes

    def __repr__(self) -> str:
        return f"{name}()"

    # TODO: Add methods
'''


def _scaffold_test_file(name: str, options: dict) -> str:
    framework = options.get("framework", "pytest")
    if framework == "pytest":
        return f'''"""Tests for {name}."""
import pytest


class Test{name.title().replace("_", "")}:
    """Test suite for {name}."""

    def setup_method(self):
        """Set up test fixtures."""
        pass

    def test_basic(self):
        """Test basic functionality."""
        # TODO: Implement
        assert True

    def test_edge_case(self):
        """Test edge cases."""
        # TODO: Implement
        assert True

    def test_error_handling(self):
        """Test error handling."""
        # TODO: Implement
        with pytest.raises(Exception):
            pass
'''
    elif framework == "jest":
        return f'''describe('{name}', () => {{
  beforeEach(() => {{
    // Setup
  }});

  it('should work correctly', () => {{
    // TODO: Implement
    expect(true).toBe(true);
  }});

  it('should handle edge cases', () => {{
    // TODO: Implement
    expect(true).toBe(true);
  }});

  it('should handle errors', () => {{
    // TODO: Implement
    expect(() => {{}}).not.toThrow();
  }});
}});
'''
    return f"// Test scaffold for: {name}"


def _scaffold_dockerfile(name: str, options: dict) -> str:
    lang = options.get("language", "python")
    if lang == "python":
        return f'''FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "-m", "{name}"]
'''
    elif lang in ("node", "javascript", "typescript"):
        return f'''FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm ci --only=production

COPY . .

EXPOSE 3000

CMD ["node", "src/index.js"]
'''
    return f"# Dockerfile for {name}"


def _scaffold_github_action(name: str, options: dict) -> str:
    lang = options.get("language", "python")
    if lang == "python":
        return f'''name: {name}

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]

    steps:
      - uses: actions/checkout@v4
      - name: Set up Python ${{{{ matrix.python-version }}}}
        uses: actions/setup-python@v5
        with:
          python-version: ${{{{ matrix.python-version }}}}
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest
      - name: Run tests
        run: pytest
'''
    return f"# GitHub Action: {name}"


def _scaffold_readme(name: str, options: dict) -> str:
    return f'''# {name}

## Overview
TODO: Describe the project.

## Installation
```bash
# TODO: Add installation steps
```

## Usage
```bash
# TODO: Add usage examples
```

## Development
```bash
# TODO: Add development setup
```

## License
MIT
'''


def _scaffold_gitignore(name: str, options: dict) -> str:
    lang = options.get("language", "python")
    common = """# OS
.DS_Store
Thumbs.db
*.swp
*.swo

# IDE
.idea/
.vscode/
*.sublime-*

# Environment
.env
.env.local
"""
    if lang == "python":
        return common + """
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
.venv/
env/
dist/
build/
*.egg-info/
.pytest_cache/
.mypy_cache/
.ruff_cache/
htmlcov/
.coverage
"""
    elif lang in ("node", "javascript", "typescript"):
        return common + """
# Node
node_modules/
dist/
build/
.next/
.nuxt/
coverage/
*.log
npm-debug.log*
yarn-debug.log*
"""
    elif lang == "php":
        return common + """
# PHP
vendor/
.phpunit.result.cache
storage/*.key
"""
    return common


def _scaffold_env_file(name: str, options: dict) -> str:
    return f'''# {name} Environment Variables
# Copy this to .env and fill in values

# App
APP_NAME={name}
APP_ENV=development
APP_PORT=3000
APP_SECRET=change-me-in-production

# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME={name.lower().replace("-", "_")}
DB_USER=
DB_PASSWORD=

# External APIs
# API_KEY=
# API_SECRET=
'''


def _scaffold_express_app(name: str, options: dict) -> str:
    return f'''const express = require('express');
const cors = require('cors');

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(cors());
app.use(express.json());

// Routes
app.get('/', (req, res) => {{
  res.json({{ message: 'Welcome to {name}' }});
}});

// Error handling
app.use((err, req, res, next) => {{
  console.error(err.stack);
  res.status(500).json({{ error: 'Something went wrong' }});
}});

app.listen(PORT, () => {{
  console.log(`{name} running on port ${{PORT}}`);
}});

module.exports = app;
'''


def _scaffold_flask_app(name: str, options: dict) -> str:
    return f'''"""
{name} - Flask Application
"""
from flask import Flask, jsonify, request

app = Flask(__name__)


@app.route("/")
def index():
    return jsonify({{"message": "Welcome to {name}"}})


@app.errorhandler(404)
def not_found(e):
    return jsonify({{"error": "Not found"}}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({{"error": "Internal server error"}}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
'''


def _scaffold_fastapi_app(name: str, options: dict) -> str:
    return f'''"""
{name} - FastAPI Application
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="{name}", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {{"message": "Welcome to {name}"}}


@app.get("/health")
async def health():
    return {{"status": "healthy"}}
'''
