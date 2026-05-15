"""
docker_tools.py – Docker container and image management tools.

Covers: container lifecycle, image management, compose, volumes, networks, logs.
All operations use subprocess to call docker CLI.
"""
from __future__ import annotations

import json
import subprocess
from typing import Any


def _run_docker(args: list[str], timeout: int = 60) -> dict[str, Any]:
    """Run a docker command and return structured result."""
    try:
        result = subprocess.run(
            ["docker"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            output = result.stdout.strip() or "Done"
            if len(output) > 8000:
                output = output[:8000] + "\n...[truncated]"
            return {"success": True, "result": output}
        else:
            return {"success": False, "error": result.stderr.strip() or result.stdout.strip()}
    except FileNotFoundError:
        return {"success": False, "error": "Docker is not installed or not in PATH"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Docker command timed out ({timeout}s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def docker_container(operation: str, target: str = "", options: str = "") -> dict[str, Any]:
    """Manage Docker containers.
    
    Operations: list, run, stop, start, restart, remove, logs, inspect, exec, stats
    """
    op = operation.lower().strip()
    
    if op == "list":
        return _run_docker(["ps", "-a", "--format", "table {{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}"])
    elif op == "run":
        if not target:
            return {"success": False, "error": "Image name required"}
        args = ["run", "-d"]
        if options:
            args.extend(options.split())
        args.append(target)
        return _run_docker(args)
    elif op == "stop":
        if not target:
            return {"success": False, "error": "Container name/ID required"}
        return _run_docker(["stop", target])
    elif op == "start":
        if not target:
            return {"success": False, "error": "Container name/ID required"}
        return _run_docker(["start", target])
    elif op == "restart":
        if not target:
            return {"success": False, "error": "Container name/ID required"}
        return _run_docker(["restart", target])
    elif op == "remove":
        if not target:
            return {"success": False, "error": "Container name/ID required"}
        return _run_docker(["rm", "-f", target])
    elif op == "logs":
        if not target:
            return {"success": False, "error": "Container name/ID required"}
        return _run_docker(["logs", "--tail", "50", target])
    elif op == "inspect":
        if not target:
            return {"success": False, "error": "Container name/ID required"}
        return _run_docker(["inspect", target])
    elif op == "exec":
        if not target or not options:
            return {"success": False, "error": "Container and command required (target=container, options=command)"}
        return _run_docker(["exec", target] + options.split())
    elif op == "stats":
        return _run_docker(["stats", "--no-stream", "--format", "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"])
    
    return {"success": False, "error": f"Unknown operation: {op}. Use: list, run, stop, start, restart, remove, logs, inspect, exec, stats"}


def docker_image(operation: str, target: str = "", options: str = "") -> dict[str, Any]:
    """Manage Docker images.
    
    Operations: list, pull, build, remove, tag, inspect, prune
    """
    op = operation.lower().strip()
    
    if op == "list":
        return _run_docker(["images", "--format", "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}"])
    elif op == "pull":
        if not target:
            return {"success": False, "error": "Image name required"}
        return _run_docker(["pull", target], timeout=120)
    elif op == "build":
        args = ["build"]
        if options:
            args.extend(options.split())
        args.extend(["-t", target or "app:latest", "."])
        return _run_docker(args, timeout=300)
    elif op == "remove":
        if not target:
            return {"success": False, "error": "Image name/ID required"}
        return _run_docker(["rmi", target])
    elif op == "tag":
        if not target or not options:
            return {"success": False, "error": "Source image and new tag required (target=source, options=new_tag)"}
        return _run_docker(["tag", target, options])
    elif op == "inspect":
        if not target:
            return {"success": False, "error": "Image name/ID required"}
        return _run_docker(["inspect", target])
    elif op == "prune":
        return _run_docker(["image", "prune", "-f"])
    
    return {"success": False, "error": f"Unknown operation: {op}. Use: list, pull, build, remove, tag, inspect, prune"}


def docker_compose(operation: str, service: str = "", options: str = "", cwd: str = ".") -> dict[str, Any]:
    """Manage Docker Compose.
    
    Operations: up, down, ps, logs, build, restart, exec, pull
    """
    op = operation.lower().strip()
    
    # Try docker compose (v2) first, fall back to docker-compose
    base_cmd = ["docker", "compose"]
    
    if op == "up":
        args = base_cmd + ["up", "-d"]
        if service:
            args.append(service)
    elif op == "down":
        args = base_cmd + ["down"]
    elif op == "ps":
        args = base_cmd + ["ps"]
    elif op == "logs":
        args = base_cmd + ["logs", "--tail", "50"]
        if service:
            args.append(service)
    elif op == "build":
        args = base_cmd + ["build"]
        if service:
            args.append(service)
    elif op == "restart":
        args = base_cmd + ["restart"]
        if service:
            args.append(service)
    elif op == "pull":
        args = base_cmd + ["pull"]
    else:
        return {"success": False, "error": f"Unknown operation: {op}. Use: up, down, ps, logs, build, restart, pull"}
    
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            return {"success": True, "result": result.stdout.strip() or "Done"}
        return {"success": False, "error": result.stderr.strip() or result.stdout.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def docker_volume(operation: str, name: str = "") -> dict[str, Any]:
    """Manage Docker volumes. Operations: list, create, remove, inspect, prune."""
    op = operation.lower().strip()
    if op == "list":
        return _run_docker(["volume", "ls"])
    elif op == "create":
        if not name:
            return {"success": False, "error": "Volume name required"}
        return _run_docker(["volume", "create", name])
    elif op == "remove":
        if not name:
            return {"success": False, "error": "Volume name required"}
        return _run_docker(["volume", "rm", name])
    elif op == "inspect":
        if not name:
            return {"success": False, "error": "Volume name required"}
        return _run_docker(["volume", "inspect", name])
    elif op == "prune":
        return _run_docker(["volume", "prune", "-f"])
    return {"success": False, "error": f"Unknown operation: {op}"}


def docker_network(operation: str, name: str = "", options: str = "") -> dict[str, Any]:
    """Manage Docker networks. Operations: list, create, remove, inspect, connect, disconnect."""
    op = operation.lower().strip()
    if op == "list":
        return _run_docker(["network", "ls"])
    elif op == "create":
        if not name:
            return {"success": False, "error": "Network name required"}
        return _run_docker(["network", "create", name])
    elif op == "remove":
        if not name:
            return {"success": False, "error": "Network name required"}
        return _run_docker(["network", "rm", name])
    elif op == "inspect":
        if not name:
            return {"success": False, "error": "Network name required"}
        return _run_docker(["network", "inspect", name])
    elif op == "connect":
        if not name or not options:
            return {"success": False, "error": "Network name and container required"}
        return _run_docker(["network", "connect", name, options])
    elif op == "disconnect":
        if not name or not options:
            return {"success": False, "error": "Network name and container required"}
        return _run_docker(["network", "disconnect", name, options])
    return {"success": False, "error": f"Unknown operation: {op}"}
