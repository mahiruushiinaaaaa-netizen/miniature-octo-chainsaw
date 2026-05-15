"""
scaffold_tools.py - Code scaffold and boilerplate generation.

Generates common project templates without hallucination by using
deterministic, well-tested templates.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Template Registry
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, callable] = {}


def scaffold(template: str, name: str, options: dict = None) -> dict[str, Any]:
    """Generate code scaffolds from templates."""
    options = options or {}
    template_key = template.lower().strip().replace(" ", "_").replace("-", "_")

    generator = TEMPLATES.get(template_key)
    if not generator:
        available = ", ".join(sorted(TEMPLATES.keys()))
        return {"success": False, "output": f"Unknown template: {template}. Available: {available}"}

    try:
        result = generator(name, options)
        return {"success": True, "output": result}
    except Exception as e:
        return {"success": False, "output": f"Scaffold error: {e}"}


def _register(key: str):
    """Decorator to register a template generator."""
    def decorator(func):
        TEMPLATES[key] = func
        return func
    return decorator


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

@_register("api_endpoint")
def _api_endpoint(name: str, options: dict) -> str:
    framework = options.get("framework", "express").lower()

    if framework == "express":
        return f'''// {name} API endpoint
const express = require('express');
const router = express.Router();

// GET /{name}
router.get('/', async (req, res) => {{
  try {{
    // TODO: Implement {name} list logic
    res.json({{ data: [], message: 'Success' }});
  }} catch (error) {{
    res.status(500).json({{ error: error.message }});
  }}
}});

// GET /{name}/:id
router.get('/:id', async (req, res) => {{
  try {{
    const {{ id }} = req.params;
    // TODO: Implement {name} get by id
    res.json({{ data: null, message: 'Success' }});
  }} catch (error) {{
    res.status(500).json({{ error: error.message }});
  }}
}});

// POST /{name}
router.post('/', async (req, res) => {{
  try {{
    const data = req.body;
    // TODO: Implement {name} creation
    res.status(201).json({{ data, message: 'Created' }});
  }} catch (error) {{
    res.status(400).json({{ error: error.message }});
  }}
}});

// PUT /{name}/:id
router.put('/:id', async (req, res) => {{
  try {{
    const {{ id }} = req.params;
    const data = req.body;
    // TODO: Implement {name} update
    res.json({{ data, message: 'Updated' }});
  }} catch (error) {{
    res.status(400).json({{ error: error.message }});
  }}
}});

// DELETE /{name}/:id
router.delete('/:id', async (req, res) => {{
  try {{
    const {{ id }} = req.params;
    // TODO: Implement {name} deletion
    res.json({{ message: 'Deleted' }});
  }} catch (error) {{
    res.status(500).json({{ error: error.message }});
  }}
}});

module.exports = router;
'''

    elif framework in ("fastapi", "python"):
        class_name = name.replace("-", "_").title().replace("_", "")
        return f'''"""
{name} API endpoint
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter(prefix="/{name}", tags=["{name}"])


class {class_name}Create(BaseModel):
    # TODO: Define fields
    name: str


class {class_name}Response(BaseModel):
    id: int
    name: str


@router.get("/", response_model=List[{class_name}Response])
async def list_{name.replace("-", "_")}():
    """List all {name}."""
    # TODO: Implement
    return []


@router.get("/{{item_id}}", response_model={class_name}Response)
async def get_{name.replace("-", "_")}(item_id: int):
    """Get {name} by ID."""
    # TODO: Implement
    raise HTTPException(status_code=404, detail="Not found")


@router.post("/", response_model={class_name}Response, status_code=201)
async def create_{name.replace("-", "_")}(data: {class_name}Create):
    """Create a new {name}."""
    # TODO: Implement
    return {class_name}Response(id=1, name=data.name)


@router.put("/{{item_id}}", response_model={class_name}Response)
async def update_{name.replace("-", "_")}(item_id: int, data: {class_name}Create):
    """Update {name}."""
    # TODO: Implement
    return {class_name}Response(id=item_id, name=data.name)


@router.delete("/{{item_id}}")
async def delete_{name.replace("-", "_")}(item_id: int):
    """Delete {name}."""
    # TODO: Implement
    return {{"message": "Deleted"}}
'''

    elif framework == "laravel":
        class_name = name.replace("-", "_").title().replace("_", "")
        return f'''<?php

namespace App\\Http\\Controllers;

use Illuminate\\Http\\Request;
use Illuminate\\Http\\JsonResponse;

class {class_name}Controller extends Controller
{{
    public function index(): JsonResponse
    {{
        // TODO: Implement list
        return response()->json(['data' => [], 'message' => 'Success']);
    }}

    public function show(int $id): JsonResponse
    {{
        // TODO: Implement show
        return response()->json(['data' => null, 'message' => 'Success']);
    }}

    public function store(Request $request): JsonResponse
    {{
        $validated = $request->validate([
            // TODO: Add validation rules
        ]);

        // TODO: Implement creation
        return response()->json(['data' => $validated, 'message' => 'Created'], 201);
    }}

    public function update(Request $request, int $id): JsonResponse
    {{
        $validated = $request->validate([
            // TODO: Add validation rules
        ]);

        // TODO: Implement update
        return response()->json(['data' => $validated, 'message' => 'Updated']);
    }}

    public function destroy(int $id): JsonResponse
    {{
        // TODO: Implement deletion
        return response()->json(['message' => 'Deleted']);
    }}
}}
'''
    else:
        return f"// {name} API endpoint for {framework}\n// TODO: Implement"


@_register("react_component")
def _react_component(name: str, options: dict) -> str:
    style = options.get("style", "functional")
    typescript = options.get("typescript", True)
    ext = "tsx" if typescript else "jsx"
    type_annotation = ": React.FC<Props>" if typescript else ""
    props_def = f"\ninterface Props {{\n  // TODO: Define props\n  className?: string;\n}}\n" if typescript else ""

    return f'''// {name}.{ext}
import React from 'react';
{props_def}
const {name}{type_annotation} = ({{ className }}) => {{
  return (
    <div className={{className}}>
      <h2>{name}</h2>
      {{/* TODO: Implement component */}}
    </div>
  );
}};

export default {name};
'''


@_register("python_class")
def _python_class(name: str, options: dict) -> str:
    base = options.get("base", "")
    dataclass = options.get("dataclass", False)

    class_name = name.replace("-", "_").title().replace("_", "")
    inheritance = f"({base})" if base else ""

    if dataclass:
        return f'''"""
{class_name} - {options.get("description", "TODO: Add description")}
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class {class_name}{inheritance}:
    """{class_name} data class."""

    # TODO: Define fields
    name: str = ""
    value: Optional[Any] = None

    def __post_init__(self) -> None:
        """Validate fields after initialization."""
        pass

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {{
            "name": self.name,
            "value": self.value,
        }}
'''
    else:
        return f'''"""
{class_name} - {options.get("description", "TODO: Add description")}
"""
from __future__ import annotations
from typing import Any, Optional


class {class_name}{inheritance}:
    """{class_name} class."""

    def __init__(self, name: str = "", **kwargs: Any) -> None:
        self.name = name
        self._data: dict[str, Any] = kwargs

    def __repr__(self) -> str:
        return f"{class_name}(name={{self.name!r}})"

    def process(self) -> Any:
        """TODO: Implement main logic."""
        raise NotImplementedError

    def validate(self) -> bool:
        """TODO: Implement validation."""
        return True
'''


@_register("test_file")
def _test_file(name: str, options: dict) -> str:
    framework = options.get("framework", "pytest").lower()

    if framework == "pytest":
        return f'''"""
Tests for {name}
"""
import pytest


class Test{name.replace("-", "_").title().replace("_", "")}:
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


@pytest.fixture
def sample_data():
    """Provide sample test data."""
    return {{
        "name": "test",
        "value": 42,
    }}
'''

    elif framework in ("jest", "vitest"):
        return f'''// {name}.test.ts
import {{ describe, it, expect, beforeEach }} from 'vitest';

describe('{name}', () => {{
  beforeEach(() => {{
    // Setup
  }});

  it('should work with basic input', () => {{
    // TODO: Implement
    expect(true).toBe(true);
  }});

  it('should handle edge cases', () => {{
    // TODO: Implement
    expect(true).toBe(true);
  }});

  it('should throw on invalid input', () => {{
    // TODO: Implement
    expect(() => {{
      throw new Error('test');
    }}).toThrow();
  }});
}});
'''
    else:
        return f"// Test file for {name} using {framework}\n// TODO: Implement"


@_register("dockerfile")
def _dockerfile(name: str, options: dict) -> str:
    lang = options.get("language", "node").lower()

    if lang == "node":
        return f'''# Dockerfile for {name}
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY . .
RUN npm run build

FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./
EXPOSE 3000
USER node
CMD ["node", "dist/index.js"]
'''

    elif lang == "python":
        return f'''# Dockerfile for {name}
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /app .
EXPOSE 8000
USER nobody
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
'''

    elif lang == "php":
        return f'''# Dockerfile for {name}
FROM php:8.3-fpm-alpine
WORKDIR /var/www/html
RUN apk add --no-cache \\
    zip unzip curl \\
    && docker-php-ext-install pdo pdo_mysql
COPY --from=composer:latest /usr/bin/composer /usr/bin/composer
COPY . .
RUN composer install --no-dev --optimize-autoloader
EXPOSE 9000
CMD ["php-fpm"]
'''
    else:
        return f"# Dockerfile for {name} ({lang})\n# TODO: Implement"


@_register("github_action")
def _github_action(name: str, options: dict) -> str:
    lang = options.get("language", "node").lower()

    if lang == "node":
        return f'''# .github/workflows/{name}.yml
name: {name}

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        node-version: [18.x, 20.x]

    steps:
      - uses: actions/checkout@v4
      - name: Use Node.js ${{{{ matrix.node-version }}}}
        uses: actions/setup-node@v4
        with:
          node-version: ${{{{ matrix.node-version }}}}
          cache: 'npm'
      - run: npm ci
      - run: npm run build --if-present
      - run: npm test
'''

    elif lang == "python":
        return f'''# .github/workflows/{name}.yml
name: {name}

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
    else:
        return f"# GitHub Action for {name} ({lang})\n# TODO: Implement"


@_register("readme")
def _readme(name: str, options: dict) -> str:
    desc = options.get("description", "A project")
    lang = options.get("language", "")

    return f'''# {name}

{desc}

## Getting Started

### Prerequisites

- TODO: List prerequisites

### Installation

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

## Testing

```bash
# TODO: Add test commands
```

## License

MIT
'''


@_register("gitignore")
def _gitignore(name: str, options: dict) -> str:
    lang = options.get("language", "node").lower()

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
.env.*.local
"""

    if lang == "node":
        return common + """
# Node
node_modules/
dist/
build/
*.log
npm-debug.log*
.npm
coverage/
"""
    elif lang == "python":
        return common + """
# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
dist/
build/
.eggs/
venv/
.venv/
*.egg
.pytest_cache/
.coverage
htmlcov/
"""
    elif lang == "php":
        return common + """
# PHP
/vendor/
composer.lock
*.cache
storage/logs/*
storage/framework/cache/*
storage/framework/sessions/*
storage/framework/views/*
"""
    else:
        return common


@_register("env_file")
def _env_file(name: str, options: dict) -> str:
    framework = options.get("framework", "generic").lower()

    if framework == "laravel":
        return f'''# {name} Environment Configuration
APP_NAME={name}
APP_ENV=local
APP_KEY=
APP_DEBUG=true
APP_URL=http://localhost

DB_CONNECTION=mysql
DB_HOST=127.0.0.1
DB_PORT=3306
DB_DATABASE={name.lower().replace("-", "_")}
DB_USERNAME=root
DB_PASSWORD=

CACHE_DRIVER=file
SESSION_DRIVER=file
QUEUE_CONNECTION=sync

MAIL_MAILER=log
'''
    elif framework in ("node", "express", "next"):
        return f'''# {name} Environment Configuration
NODE_ENV=development
PORT=3000

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/{name.lower().replace("-", "_")}

# Auth
JWT_SECRET=change-me-in-production
JWT_EXPIRES_IN=7d

# External APIs
# API_KEY=your-api-key-here
'''
    else:
        return f'''# {name} Environment Configuration
APP_NAME={name}
APP_ENV=development
APP_PORT=8000
APP_DEBUG=true

# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME={name.lower().replace("-", "_")}
DB_USER=root
DB_PASSWORD=

# Secrets (change in production)
SECRET_KEY=change-me
'''
