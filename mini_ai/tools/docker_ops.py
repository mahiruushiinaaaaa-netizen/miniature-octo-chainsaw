"""
docker_ops.py – Docker container and image management tool.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Any


def _check_docker() -> dict[str, Any] | None:
    if not shutil.which("docker"):
        return {"success": False, "error": "docker is not installed. Install from https://docs.docker.com/get-docker/"}
    return None


def _run_docker(args: list[str], timeout: int = 60) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["docker"] + args,
            capture_output=True, text=True, timeout=timeout
        )
        output = (result.stdout + result.stderr).strip()
        if len(output) > 3000:
            output = output[:3000] + "\n...[truncated]"
        if result.returncode == 0:
            return {"success": True, "result": output or "(no output)"}
        return {"success": False, "error": output or f"docker exited with code {result.returncode}"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"docker command timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def docker_op(operation: str, target: str = "", options: str = "") -> dict[str, Any]:
    """Docker container and image management.

    Operations:
    - ps: list containers (target: 'all' for stopped too)
    - images: list images
    - run: run container (target: image name, options: extra flags)
    - stop: stop container (target: container id/name)
    - rm: remove container (target: container id/name)
    - logs: view logs (target: container id/name, options: '--tail 50')
    - build: build image (target: path to Dockerfile dir, options: '-t name:tag')
    - compose_up: docker-compose up (target: compose file path)
    - compose_down: docker-compose down
    - exec: run command in container (target: container, options: command)
    - pull: pull image (target: image name)
    - inspect: inspect container/image (target: id/name)
    """
    check = _check_docker()
    if check:
        return check

    operation = operation.lower().strip()

    if operation == "ps":
        args = ["ps"]
        if target.lower() == "all":
            args.append("-a")
        args.append("--format")
        args.append("table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}")
        return _run_docker(args)

    elif operation == "images":
        return _run_docker(["images", "--format", "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}"])

    elif operation == "run":
        if not target:
            return {"success": False, "error": "run requires an image name. Usage: target='nginx:latest'"}
        args = ["run", "-d"]
        if options:
            args.extend(options.split())
        args.append(target)
        return _run_docker(args)

    elif operation == "stop":
        if not target:
            return {"success": False, "error": "stop requires a container id/name"}
        return _run_docker(["stop", target])

    elif operation == "rm":
        if not target:
            return {"success": False, "error": "rm requires a container id/name"}
        return _run_docker(["rm", "-f", target])

    elif operation == "logs":
        if not target:
            return {"success": False, "error": "logs requires a container id/name"}
        args = ["logs"]
        if options:
            args.extend(options.split())
        else:
            args.extend(["--tail", "50"])
        args.append(target)
        return _run_docker(args)

    elif operation == "build":
        args = ["build"]
        if options:
            args.extend(options.split())
        args.append(target or ".")
        return _run_docker(args, timeout=300)

    elif operation == "compose_up":
        compose_cmd = "docker-compose" if shutil.which("docker-compose") else "docker"
        if compose_cmd == "docker":
            args = ["compose"]
        else:
            args = []
        if target:
            args.extend(["-f", target])
        args.extend(["up", "-d"])
        if compose_cmd == "docker":
            return _run_docker(args, timeout=120)
        try:
            result = subprocess.run([compose_cmd] + args, capture_output=True, text=True, timeout=120)
            output = (result.stdout + result.stderr).strip()
            return {"success": result.returncode == 0, "result" if result.returncode == 0 else "error": output[:3000]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif operation == "compose_down":
        compose_cmd = "docker-compose" if shutil.which("docker-compose") else "docker"
        if compose_cmd == "docker":
            args = ["compose", "down"]
        else:
            args = ["down"]
        if compose_cmd == "docker":
            return _run_docker(args)
        try:
            result = subprocess.run([compose_cmd] + args, capture_output=True, text=True, timeout=30)
            output = (result.stdout + result.stderr).strip()
            return {"success": result.returncode == 0, "result" if result.returncode == 0 else "error": output[:3000]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif operation == "exec":
        if not target:
            return {"success": False, "error": "exec requires a container id/name"}
        if not options:
            return {"success": False, "error": "exec requires a command in options. Usage: options='ls -la'"}
        args = ["exec", target] + options.split()
        return _run_docker(args)

    elif operation == "pull":
        if not target:
            return {"success": False, "error": "pull requires an image name. Usage: target='python:3.12'"}
        return _run_docker(["pull", target], timeout=120)

    elif operation == "inspect":
        if not target:
            return {"success": False, "error": "inspect requires a container/image id or name"}
        return _run_docker(["inspect", "--format", "{{json .}}", target])

    else:
        return {"success": False, "error": f"Unknown docker operation: '{operation}'. Available: ps, images, run, stop, rm, logs, build, compose_up, compose_down, exec, pull, inspect"}
