"""
project_ops.py – Project initialization, info, dependency tree, health check.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


def project_init(template: str, name: str, path: str = ".", options: str = "") -> dict[str, Any]:
    """Initialize a new project from template.

    Templates: python_package, node_app, react_app, django_app, flask_app,
               fastapi_app, express_app, cli_tool, library, monorepo, vite_app
    """
    template = template.lower().strip()
    project_dir = Path(path).expanduser().resolve() / name

    generators = {
        "python_package": _init_python_package,
        "node_app": _init_node_app,
        "flask_app": _init_flask_app,
        "fastapi_app": _init_fastapi_app,
        "express_app": _init_express_app,
        "cli_tool": _init_cli_tool,
        "library": _init_python_package,
        "django_app": _init_django_app,
        "react_app": _init_react_app,
        "vue_app": _init_vue_app,
        "nextjs_app": _init_nextjs_app,
        "nestjs_app": _init_nestjs_app,
        "fullstack_app": _init_fullstack_app,
    }

    generator = generators.get(template)
    if not generator:
        available = ", ".join(sorted(generators.keys()))
        return {"success": False, "error": f"Unknown template: '{template}'. Available: {available}"}

    try:
        if project_dir.exists():
            return {"success": False, "error": f"Directory already exists: {project_dir}"}
        project_dir.mkdir(parents=True)
        files_created = generator(project_dir, name, options)
        return {"success": True, "result": f"Created project '{name}' at {project_dir}\nFiles created: {len(files_created)}\n" + "\n".join(f"  {f}" for f in files_created)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def project_info(path: str = ".") -> dict[str, Any]:
    """Analyze project structure and provide summary."""
    root = Path(path).expanduser().resolve()
    if not root.exists():
        return {"success": False, "error": f"Path not found: {path}"}

    info = {"path": str(root), "name": root.name}

    # Detect language/framework
    if (root / "package.json").exists():
        info["language"] = "JavaScript/TypeScript"
        try:
            pkg = json.loads((root / "package.json").read_text())
            info["name"] = pkg.get("name", root.name)
            info["version"] = pkg.get("version", "unknown")
            deps = pkg.get("dependencies", {})
            if "react" in deps:
                info["framework"] = "React"
            elif "next" in deps:
                info["framework"] = "Next.js"
            elif "vue" in deps:
                info["framework"] = "Vue"
            elif "express" in deps:
                info["framework"] = "Express"
            info["dependencies"] = len(deps)
            info["dev_dependencies"] = len(pkg.get("devDependencies", {}))
        except Exception:
            pass
    elif (root / "pyproject.toml").exists() or (root / "setup.py").exists():
        info["language"] = "Python"
        if (root / "manage.py").exists():
            info["framework"] = "Django"
        elif any(root.rglob("*flask*")):
            info["framework"] = "Flask"
        elif any(root.rglob("*fastapi*")):
            info["framework"] = "FastAPI"
    elif (root / "Cargo.toml").exists():
        info["language"] = "Rust"
    elif (root / "go.mod").exists():
        info["language"] = "Go"
    elif (root / "composer.json").exists():
        info["language"] = "PHP"
        if (root / "artisan").exists():
            info["framework"] = "Laravel"

    # Count files
    all_files = [f for f in root.rglob("*") if f.is_file() and not any(p in str(f) for p in (".git", "node_modules", "__pycache__", ".venv", "vendor"))]
    info["total_files"] = len(all_files)

    # Entry points
    entry_points = []
    for name_check in ("main.py", "app.py", "index.js", "index.ts", "src/main.rs", "main.go", "manage.py"):
        if (root / name_check).exists():
            entry_points.append(name_check)
    info["entry_points"] = entry_points

    # Config files
    configs = [f.name for f in root.iterdir() if f.is_file() and f.name.startswith(".") or f.suffix in (".toml", ".yaml", ".yml", ".json", ".cfg", ".ini")]
    info["config_files"] = configs[:10]

    lines = [f"Project: {info.get('name', root.name)}"]
    for k, v in info.items():
        if k != "path":
            lines.append(f"  {k}: {v}")
    return {"success": True, "result": "\n".join(lines)}


def dependency_tree(path: str = ".", depth: int = 3) -> dict[str, Any]:
    """Show project dependency tree."""
    root = Path(path).expanduser().resolve()

    # Python
    req_file = root / "requirements.txt"
    if req_file.exists():
        deps = [line.strip() for line in req_file.read_text().splitlines() if line.strip() and not line.startswith("#")]
        return {"success": True, "result": f"Python dependencies ({len(deps)}):\n" + "\n".join(f"  {d}" for d in deps[:50])}

    # Node
    pkg_file = root / "package.json"
    if pkg_file.exists():
        try:
            pkg = json.loads(pkg_file.read_text())
            deps = pkg.get("dependencies", {})
            dev_deps = pkg.get("devDependencies", {})
            lines = [f"Dependencies ({len(deps)}):"]
            for name, ver in sorted(deps.items())[:30]:
                lines.append(f"  {name}: {ver}")
            if dev_deps:
                lines.append(f"\nDev Dependencies ({len(dev_deps)}):")
                for name, ver in sorted(dev_deps.items())[:20]:
                    lines.append(f"  {name}: {ver}")
            return {"success": True, "result": "\n".join(lines)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # Cargo
    cargo_file = root / "Cargo.toml"
    if cargo_file.exists():
        content = cargo_file.read_text()
        deps = re.findall(r'^(\w[\w-]*)\s*=', content, re.MULTILINE)
        return {"success": True, "result": f"Cargo dependencies:\n" + "\n".join(f"  {d}" for d in deps[:30])}

    return {"success": False, "error": "No dependency file found (requirements.txt, package.json, Cargo.toml)"}


def project_health(path: str = ".") -> dict[str, Any]:
    """Check project health."""
    root = Path(path).expanduser().resolve()
    issues = []
    good = []

    # README
    if (root / "README.md").exists() or (root / "readme.md").exists():
        good.append("✓ README exists")
    else:
        issues.append("✗ No README.md found")

    # .gitignore
    if (root / ".gitignore").exists():
        good.append("✓ .gitignore exists")
    else:
        issues.append("✗ No .gitignore found")

    # Tests
    has_tests = (root / "tests").exists() or (root / "test").exists() or (root / "__tests__").exists()
    if has_tests:
        good.append("✓ Test directory exists")
    else:
        issues.append("✗ No test directory found")

    # License
    if any((root / f).exists() for f in ("LICENSE", "LICENSE.md", "LICENSE.txt")):
        good.append("✓ License file exists")
    else:
        issues.append("⚠ No LICENSE file")

    # Lock file
    if any((root / f).exists() for f in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Pipfile.lock", "poetry.lock", "Cargo.lock")):
        good.append("✓ Lock file exists")
    else:
        issues.append("⚠ No lock file (dependencies not pinned)")

    # .env in git
    if (root / ".env").exists() and (root / ".git").exists():
        gitignore = (root / ".gitignore").read_text() if (root / ".gitignore").exists() else ""
        if ".env" not in gitignore:
            issues.append("✗ .env exists but not in .gitignore (security risk)")

    score = len(good) / (len(good) + len(issues)) * 100 if (good or issues) else 0
    result = f"Project Health Score: {score:.0f}%\n\n"
    if good:
        result += "Good:\n" + "\n".join(f"  {g}" for g in good) + "\n\n"
    if issues:
        result += "Issues:\n" + "\n".join(f"  {i}" for i in issues)

    return {"success": True, "result": result}


# --- Project generators ---

def _init_python_package(root: Path, name: str, options: str) -> list[str]:
    pkg_name = name.replace("-", "_").replace(" ", "_")
    files = {}
    files["pyproject.toml"] = f'''[project]
name = "{name}"
version = "0.1.0"
description = ""
requires-python = ">=3.10"

[tool.pytest.ini_options]
testpaths = ["tests"]
'''
    files[f"{pkg_name}/__init__.py"] = f'"""{ name} package."""\n__version__ = "0.1.0"\n'
    files[f"{pkg_name}/main.py"] = f'"""Main module."""\n\ndef main():\n    print("Hello from {name}")\n\nif __name__ == "__main__":\n    main()\n'
    files["tests/__init__.py"] = ""
    files["tests/test_main.py"] = f'from {pkg_name}.main import main\n\ndef test_main():\n    main()\n'
    files["README.md"] = f"# {name}\n\n## Installation\n\n```bash\npip install -e .\n```\n"
    files[".gitignore"] = "__pycache__/\n*.py[cod]\n.venv/\ndist/\n*.egg-info/\n"

    created = []
    for rel_path, content in files.items():
        fp = root / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        created.append(rel_path)
    return created


def _init_node_app(root: Path, name: str, options: str) -> list[str]:
    files = {}
    files["package.json"] = json.dumps({"name": name, "version": "1.0.0", "main": "src/index.js", "scripts": {"start": "node src/index.js", "dev": "node --watch src/index.js", "test": "echo \"no tests\""}}, indent=2)
    files["src/index.js"] = f'console.log("Hello from {name}");\n'
    files["README.md"] = f"# {name}\n\n```bash\nnpm start\n```\n"
    files[".gitignore"] = "node_modules/\n.env\n"

    created = []
    for rel_path, content in files.items():
        fp = root / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        created.append(rel_path)
    return created


def _init_flask_app(root: Path, name: str, options: str) -> list[str]:
    files = {}
    files["app.py"] = f'''from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def index():
    return jsonify({{"message": "Welcome to {name}"}})

if __name__ == "__main__":
    app.run(debug=True)
'''
    files["requirements.txt"] = "flask>=3.0\n"
    files["README.md"] = f"# {name}\n\n```bash\npip install -r requirements.txt\npython app.py\n```\n"
    files[".gitignore"] = "__pycache__/\n.venv/\n.env\n"

    created = []
    for rel_path, content in files.items():
        fp = root / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        created.append(rel_path)
    return created


def _init_fastapi_app(root: Path, name: str, options: str) -> list[str]:
    files = {}
    files["main.py"] = f'''from fastapi import FastAPI

app = FastAPI(title="{name}")

@app.get("/")
async def root():
    return {{"message": "Welcome to {name}"}}

@app.get("/health")
async def health():
    return {{"status": "ok"}}
'''
    files["requirements.txt"] = "fastapi>=0.100\nuvicorn[standard]>=0.20\n"
    files["README.md"] = f"# {name}\n\n```bash\npip install -r requirements.txt\nuvicorn main:app --reload\n```\n"
    files[".gitignore"] = "__pycache__/\n.venv/\n.env\n"

    created = []
    for rel_path, content in files.items():
        fp = root / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        created.append(rel_path)
    return created


def _init_express_app(root: Path, name: str, options: str) -> list[str]:
    files = {}
    files["package.json"] = json.dumps({"name": name, "version": "1.0.0", "main": "src/index.js", "scripts": {"start": "node src/index.js", "dev": "node --watch src/index.js"}, "dependencies": {"express": "^4.18.0", "cors": "^2.8.0"}}, indent=2)
    files["src/index.js"] = f'''const express = require("express");
const cors = require("cors");
const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());

app.get("/", (req, res) => res.json({{ message: "Welcome to {name}" }}));

app.listen(PORT, () => console.log(`{name} running on port ${{PORT}}`));
'''
    files["README.md"] = f"# {name}\n\n```bash\nnpm install\nnpm start\n```\n"
    files[".gitignore"] = "node_modules/\n.env\n"

    created = []
    for rel_path, content in files.items():
        fp = root / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        created.append(rel_path)
    return created


def _init_cli_tool(root: Path, name: str, options: str) -> list[str]:
    pkg_name = name.replace("-", "_")
    files = {}
    files["pyproject.toml"] = f'''[project]
name = "{name}"
version = "0.1.0"
scripts = {{{name} = "{pkg_name}.cli:main"}}
requires-python = ">=3.10"
'''
    files[f"{pkg_name}/__init__.py"] = ""
    files[f"{pkg_name}/cli.py"] = f'''"""CLI entry point for {name}."""
import argparse
import sys

def main():
    parser = argparse.ArgumentParser(description="{name}")
    parser.add_argument("command", nargs="?", default="help")
    args = parser.parse_args()
    print(f"{name} v0.1.0 - {{args.command}}")

if __name__ == "__main__":
    main()
'''
    files["README.md"] = f"# {name}\n\nCLI tool.\n\n```bash\npip install -e .\n{name} --help\n```\n"
    files[".gitignore"] = "__pycache__/\n.venv/\ndist/\n*.egg-info/\n"

    created = []
    for rel_path, content in files.items():
        fp = root / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        created.append(rel_path)
    return created


def _init_django_app(root: Path, name: str, options: str) -> list[str]:
    """Initialize a Django project structure."""
    pkg_name = name.replace("-", "_")
    files = {}
    files["manage.py"] = f'''#!/usr/bin/env python
"""Django management script."""
import os
import sys

def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "{pkg_name}.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)

if __name__ == "__main__":
    main()
'''
    files[f"{pkg_name}/__init__.py"] = ""
    files[f"{pkg_name}/settings.py"] = f'''"""Django settings for {name}."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = "django-insecure-change-me-in-production"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "{pkg_name}.urls"
TEMPLATES = [{{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {{"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]}},
}}]

DATABASES = {{
    "default": {{
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }}
}}

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
'''
    files[f"{pkg_name}/urls.py"] = f'''from django.contrib import admin
from django.urls import path
from . import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.index, name="index"),
]
'''
    files[f"{pkg_name}/views.py"] = f'''from django.http import JsonResponse

def index(request):
    return JsonResponse({{"message": "Welcome to {name}", "status": "ok"}})
'''
    files[f"{pkg_name}/wsgi.py"] = f'''import os
from django.core.wsgi import get_wsgi_application
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "{pkg_name}.settings")
application = get_wsgi_application()
'''
    files["requirements.txt"] = "django>=5.0\n"
    files["README.md"] = f"# {name}\n\nDjango project.\n\n```bash\npip install -r requirements.txt\npython manage.py runserver\n```\n"
    files[".gitignore"] = "__pycache__/\n*.py[cod]\n.venv/\ndb.sqlite3\n.env\n"

    created = []
    for rel_path, content in files.items():
        fp = root / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        created.append(rel_path)
    return created


def _init_react_app(root: Path, name: str, options: str) -> list[str]:
    """Initialize a React app with Vite (modern approach)."""
    files = {}
    files["package.json"] = json.dumps({
        "name": name,
        "private": True,
        "version": "0.1.0",
        "type": "module",
        "scripts": {
            "dev": "vite",
            "build": "vite build",
            "preview": "vite preview"
        },
        "dependencies": {
            "react": "^18.3.0",
            "react-dom": "^18.3.0"
        },
        "devDependencies": {
            "@vitejs/plugin-react": "^4.3.0",
            "vite": "^5.4.0"
        }
    }, indent=2)
    files["vite.config.js"] = '''import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
});
'''
    files["index.html"] = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{name}</title>
</head>
<body>
  <div id="root"></div>
  <script type="module" src="/src/main.jsx"></script>
</body>
</html>
'''
    files["src/main.jsx"] = '''import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
'''
    files["src/App.jsx"] = f'''function App() {{
  return (
    <div style={{{{ padding: "2rem", fontFamily: "system-ui" }}}}>
      <h1>{name}</h1>
      <p>Edit src/App.jsx and save to reload.</p>
    </div>
  );
}}

export default App;
'''
    files[".gitignore"] = "node_modules/\ndist/\n.env\n"
    files["README.md"] = f"# {name}\n\nReact + Vite app.\n\n```bash\nnpm install\nnpm run dev\n```\n"

    created = []
    for rel_path, content in files.items():
        fp = root / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        created.append(rel_path)
    return created


def _init_vue_app(root: Path, name: str, options: str) -> list[str]:
    """Initialize a Vue 3 app with Vite."""
    files = {}
    files["package.json"] = json.dumps({
        "name": name,
        "private": True,
        "version": "0.1.0",
        "type": "module",
        "scripts": {
            "dev": "vite",
            "build": "vite build",
            "preview": "vite preview"
        },
        "dependencies": {
            "vue": "^3.4.0"
        },
        "devDependencies": {
            "@vitejs/plugin-vue": "^5.0.0",
            "vite": "^5.4.0"
        }
    }, indent=2)
    files["vite.config.js"] = '''import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
});
'''
    files["index.html"] = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{name}</title>
</head>
<body>
  <div id="app"></div>
  <script type="module" src="/src/main.js"></script>
</body>
</html>
'''
    files["src/main.js"] = '''import { createApp } from "vue";
import App from "./App.vue";

createApp(App).mount("#app");
'''
    files["src/App.vue"] = f'''<template>
  <div class="app">
    <h1>{name}</h1>
    <p>Edit src/App.vue and save to reload.</p>
  </div>
</template>

<script setup>
// Component logic here
</script>

<style scoped>
.app {{
  padding: 2rem;
  font-family: system-ui;
}}
</style>
'''
    files[".gitignore"] = "node_modules/\ndist/\n.env\n"
    files["README.md"] = f"# {name}\n\nVue 3 + Vite app.\n\n```bash\nnpm install\nnpm run dev\n```\n"

    created = []
    for rel_path, content in files.items():
        fp = root / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        created.append(rel_path)
    return created


def _init_nextjs_app(root: Path, name: str, options: str) -> list[str]:
    """Initialize a Next.js app structure."""
    files = {}
    files["package.json"] = json.dumps({
        "name": name,
        "version": "0.1.0",
        "private": True,
        "scripts": {
            "dev": "next dev",
            "build": "next build",
            "start": "next start",
            "lint": "next lint"
        },
        "dependencies": {
            "next": "^14.2.0",
            "react": "^18.3.0",
            "react-dom": "^18.3.0"
        }
    }, indent=2)
    files["next.config.js"] = '''/** @type {import("next").NextConfig} */
const nextConfig = {};
module.exports = nextConfig;
'''
    files["app/layout.js"] = f'''export const metadata = {{
  title: "{name}",
  description: "Created with Next.js",
}};

export default function RootLayout({{ children }}) {{
  return (
    <html lang="en">
      <body>{{children}}</body>
    </html>
  );
}}
'''
    files["app/page.js"] = f'''export default function Home() {{
  return (
    <main style={{{{ padding: "2rem", fontFamily: "system-ui" }}}}>
      <h1>{name}</h1>
      <p>Get started by editing app/page.js</p>
    </main>
  );
}}
'''
    files["public/.gitkeep"] = ""
    files[".gitignore"] = "node_modules/\n.next/\nout/\n.env\n"
    files["README.md"] = f"# {name}\n\nNext.js app.\n\n```bash\nnpm install\nnpm run dev\n```\n"

    created = []
    for rel_path, content in files.items():
        fp = root / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        created.append(rel_path)
    return created


def _init_nestjs_app(root: Path, name: str, options: str) -> list[str]:
    """Initialize a NestJS app structure."""
    files = {}
    files["package.json"] = json.dumps({
        "name": name,
        "version": "0.1.0",
        "private": True,
        "scripts": {
            "start": "nest start",
            "start:dev": "nest start --watch",
            "build": "nest build",
            "test": "jest"
        },
        "dependencies": {
            "@nestjs/common": "^10.0.0",
            "@nestjs/core": "^10.0.0",
            "@nestjs/platform-express": "^10.0.0",
            "reflect-metadata": "^0.2.0",
            "rxjs": "^7.8.0"
        },
        "devDependencies": {
            "@nestjs/cli": "^10.0.0",
            "@nestjs/testing": "^10.0.0",
            "typescript": "^5.3.0",
            "ts-node": "^10.9.0"
        }
    }, indent=2)
    files["tsconfig.json"] = json.dumps({
        "compilerOptions": {
            "module": "commonjs",
            "declaration": True,
            "removeComments": True,
            "emitDecoratorMetadata": True,
            "experimentalDecorators": True,
            "target": "ES2021",
            "outDir": "./dist",
            "baseUrl": "./",
            "strict": True
        }
    }, indent=2)
    files["src/main.ts"] = f'''import {{ NestFactory }} from "@nestjs/core";
import {{ AppModule }} from "./app.module";

async function bootstrap() {{
  const app = await NestFactory.create(AppModule);
  await app.listen(3000);
  console.log("{name} running on http://localhost:3000");
}}
bootstrap();
'''
    files["src/app.module.ts"] = '''import { Module } from "@nestjs/common";
import { AppController } from "./app.controller";
import { AppService } from "./app.service";

@Module({
  imports: [],
  controllers: [AppController],
  providers: [AppService],
})
export class AppModule {}
'''
    files["src/app.controller.ts"] = '''import { Controller, Get } from "@nestjs/common";
import { AppService } from "./app.service";

@Controller()
export class AppController {
  constructor(private readonly appService: AppService) {}

  @Get()
  getHello(): string {
    return this.appService.getHello();
  }
}
'''
    files["src/app.service.ts"] = f'''import {{ Injectable }} from "@nestjs/common";

@Injectable()
export class AppService {{
  getHello(): string {{
    return "Hello from {name}!";
  }}
}}
'''
    files[".gitignore"] = "node_modules/\ndist/\n.env\n"
    files["README.md"] = f"# {name}\n\nNestJS app.\n\n```bash\nnpm install\nnpm run start:dev\n```\n"

    created = []
    for rel_path, content in files.items():
        fp = root / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        created.append(rel_path)
    return created


def _init_fullstack_app(root: Path, name: str, options: str) -> list[str]:
    """Initialize a fullstack app (Express backend + React frontend)."""
    files = {}
    # Root package.json
    files["package.json"] = json.dumps({
        "name": name,
        "private": True,
        "scripts": {
            "dev": "concurrently \"npm run dev:server\" \"npm run dev:client\"",
            "dev:server": "node --watch server/index.js",
            "dev:client": "cd client && npm run dev",
            "build": "cd client && npm run build"
        },
        "dependencies": {
            "express": "^4.18.0",
            "cors": "^2.8.0",
            "concurrently": "^8.2.0"
        }
    }, indent=2)
    # Server
    files["server/index.js"] = f'''const express = require("express");
const cors = require("cors");
const app = express();
const PORT = process.env.PORT || 3001;

app.use(cors());
app.use(express.json());

app.get("/api/health", (req, res) => {{
  res.json({{ status: "ok", name: "{name}" }});
}});

app.listen(PORT, () => console.log(`Server running on port ${{PORT}}`));
'''
    # Client (minimal React)
    files["client/package.json"] = json.dumps({
        "name": f"{name}-client",
        "private": True,
        "type": "module",
        "scripts": {"dev": "vite", "build": "vite build"},
        "dependencies": {"react": "^18.3.0", "react-dom": "^18.3.0"},
        "devDependencies": {"@vitejs/plugin-react": "^4.3.0", "vite": "^5.4.0"}
    }, indent=2)
    files["client/index.html"] = f'''<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8" /><title>{name}</title></head>
<body><div id="root"></div><script type="module" src="/src/main.jsx"></script></body>
</html>
'''
    files["client/src/main.jsx"] = '''import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
ReactDOM.createRoot(document.getElementById("root")).render(<App />);
'''
    files["client/src/App.jsx"] = f'''import {{ useState, useEffect }} from "react";

function App() {{
  const [health, setHealth] = useState(null);
  useEffect(() => {{
    fetch("http://localhost:3001/api/health")
      .then(r => r.json())
      .then(setHealth)
      .catch(console.error);
  }}, []);

  return (
    <div style={{{{ padding: "2rem", fontFamily: "system-ui" }}}}>
      <h1>{name}</h1>
      <p>Server status: {{health ? health.status : "loading..."}}</p>
    </div>
  );
}}
export default App;
'''
    files[".gitignore"] = "node_modules/\ndist/\n.env\nclient/node_modules/\n"
    files["README.md"] = f"# {name}\n\nFullstack app (Express + React).\n\n```bash\nnpm install\ncd client && npm install && cd ..\nnpm run dev\n```\n"

    created = []
    for rel_path, content in files.items():
        fp = root / rel_path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        created.append(rel_path)
    return created
