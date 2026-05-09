"""
cli.py – CLI entry point. Tuned for low-end devices.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .backend import server_ready, start_server
from .commands import CommandRouter
from .config import Config, DEFAULT_MODELS_DIR
from ..ui import err, ok, enable_terminal, header, help_hint, user_prompt
from ..tools.discovery import auto_choose_model, auto_choose_ui_model, choose_model, find_llama_cli, find_llama_server
from .settings import (clear_saved_models_dir, get_saved_models_dir,
                        set_saved_models_dir, set_cached_model, clear_cached_model)


_CPU = os.cpu_count() or 2


def enable_terminal_updates() -> None:
    enable_terminal()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Mini AI – local AI CLI (v39)")
    p.add_argument("--model", default=None)
    p.add_argument("--ui-model", default=None)
    p.add_argument("--dual-model", action="store_true")
    p.add_argument("--choose-model", action="store_true")
    p.add_argument("--agent-model", default=None)
    p.add_argument("--analyzer-model", default=None)
    p.add_argument("--coder-model", default=None)
    p.add_argument("--tri-model", action="store_true")
    p.add_argument("--coder-port", type=int, default=8082)
    p.add_argument("--models-dir", default=None)
    p.add_argument("--set-models-dir", default=None, help=argparse.SUPPRESS)
    p.add_argument("--clear-models-dir", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--bin", default=None)
    p.add_argument("--server-bin", default=None)
    # Low-end friendly defaults
    p.add_argument("--threads", type=int, default=max(1, min(_CPU, 4)))
    p.add_argument("--ctx", type=int, default=1024)
    p.add_argument("--temp", type=float, default=0.0)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--ui-port", type=int, default=8081)
    p.add_argument("--allow-run", action="store_true")
    p.add_argument("--workspace", default=os.getcwd())
    p.add_argument("--agent-tokens", type=int, default=128)
    return p.parse_args()


def build_config(args) -> Config | None:
    if getattr(args, "clear_models_dir", False):
        clear_saved_models_dir()
        print("[OK] Cleared saved models folder.")

    if getattr(args, "set_models_dir", None):
        chosen_dir = Path(args.set_models_dir).expanduser()
        if not chosen_dir.exists() or not chosen_dir.is_dir():
            err(f"Models folder not found: {chosen_dir}")
            return None
        set_saved_models_dir(chosen_dir)
        print(f"[OK] Saved models folder: {chosen_dir}")

    saved_dir = get_saved_models_dir()
    models_dir = (
        Path(args.models_dir).expanduser() if getattr(args, "models_dir", None)
        else (saved_dir or DEFAULT_MODELS_DIR)
    )

    if getattr(args, "agent_model", None):
        args.model = args.agent_model

    if getattr(args, "model", None):
        model = Path(args.model).expanduser()
    elif getattr(args, "choose_model", False):
        model = choose_model(models_dir)
    else:
        model = auto_choose_model(models_dir)

    if not model:
        return None
    if not model.exists():
        err(f"Model not found: {model}")
        return None

    cli_bin = find_llama_cli(getattr(args, "bin", None))
    server_bin = find_llama_server(getattr(args, "server_bin", None), cli_bin)

    if not server_bin:
        err("llama-server not found. Pass --server-bin explicitly.")
        return None

    cfg = Config(
        model=model,
        models_dir=models_dir,
        cli_bin=cli_bin or server_bin,
        server_bin=server_bin,
        threads=max(1, getattr(args, "threads", 4)),
        ctx=max(128, getattr(args, "ctx", 1024)),
        temp=getattr(args, "temp", 0.0),
        seed=getattr(args, "seed", None),
        timeout=max(1, getattr(args, "timeout", 120)),
        host=getattr(args, "host", "127.0.0.1"),
        port=getattr(args, "port", 8080),
        use_server=True,
        allow_run=getattr(args, "allow_run", False),
        workspace=Path(getattr(args, "workspace", os.getcwd())).expanduser().resolve(),
        agent_tokens=max(80, getattr(args, "agent_tokens", 128)),
        role="agent",
    )

    if getattr(args, "dual_model", False) and not getattr(args, "tri_model", False):
        ui_model_path = getattr(args, "ui_model", None)
        if ui_model_path:
            ui_model = Path(ui_model_path).expanduser()
        else:
            ui_model = auto_choose_ui_model(models_dir, avoid=model)

        if ui_model and ui_model.exists():
            cfg.ui_config = Config(
                model=ui_model,
                models_dir=models_dir,
                cli_bin=cli_bin or server_bin,
                server_bin=server_bin,
                threads=max(1, min(getattr(args, "threads", 4), 2)),
                ctx=max(512, min(getattr(args, "ctx", 1024), 1024)),
                temp=getattr(args, "temp", 0.0),
                seed=getattr(args, "seed", None),
                timeout=90,
                host=getattr(args, "host", "127.0.0.1"),
                port=getattr(args, "ui_port", 8081),
                use_server=True,
                allow_run=getattr(args, "allow_run", False),
                workspace=Path(getattr(args, "workspace", os.getcwd())).expanduser().resolve(),
                agent_tokens=96,
                role="ui",
            )
            
    if getattr(args, "tri_model", False):
        cfg.tri_model = True
        analyzer_path = getattr(args, "analyzer_model", None)
        coder_path = getattr(args, "coder_model", None)
        
        analyzer_model = Path(analyzer_path).expanduser() if analyzer_path else auto_choose_ui_model(models_dir, avoid=model)
        coder_model = Path(coder_path).expanduser() if coder_path else (auto_choose_model(models_dir, avoid=model) or model)

        if analyzer_model and analyzer_model.exists():
            cfg.analyzer_config = Config(
                model=analyzer_model,
                models_dir=models_dir,
                cli_bin=cli_bin or server_bin,
                server_bin=server_bin,
                threads=max(1, min(getattr(args, "threads", 4), 2)),
                ctx=max(512, min(getattr(args, "ctx", 1024), 2048)),
                temp=getattr(args, "temp", 0.0),
                seed=getattr(args, "seed", None),
                timeout=120,
                host=getattr(args, "host", "127.0.0.1"),
                port=getattr(args, "ui_port", 8081),
                use_server=True,
                allow_run=getattr(args, "allow_run", False),
                workspace=Path(getattr(args, "workspace", os.getcwd())).expanduser().resolve(),
                agent_tokens=256,
                role="analyzer",
            )
            cfg.ui_config = cfg.analyzer_config

        if coder_model and coder_model.exists():
            cfg.coder_config = Config(
                model=coder_model,
                models_dir=models_dir,
                cli_bin=cli_bin or server_bin,
                server_bin=server_bin,
                threads=max(1, getattr(args, "threads", 4)),
                ctx=max(1024, getattr(args, "ctx", 1024)),
                temp=getattr(args, "temp", 0.0),
                seed=getattr(args, "seed", None),
                timeout=120,
                host=getattr(args, "host", "127.0.0.1"),
                port=getattr(args, "coder_port", 8082),
                use_server=True,
                allow_run=getattr(args, "allow_run", False),
                workspace=Path(getattr(args, "workspace", os.getcwd())).expanduser().resolve(),
                agent_tokens=max(80, getattr(args, "agent_tokens", 512)),
                role="coder",
            )

    return cfg


def repl(config: Config) -> None:
    header("Mini AI", f"Workspace: {config.workspace}")
    print(f"Model: {config.model.name}")
    if config.tri_model:
        if config.analyzer_config:
            print(f"Analyzer model: {config.analyzer_config.model.name}")
        if config.coder_config:
            print(f"Coder model: {config.coder_config.model.name}")
    elif config.ui_config:
        print(f"UI model: {config.ui_config.model.name}")
    help_hint()
    print("")

    router = CommandRouter(config)
    while True:
        try:
            try:
                from prompt_toolkit import PromptSession
                from prompt_toolkit.history import InMemoryHistory
                from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
                
                # Attach session to router to persist history across turns
                if not hasattr(router, "prompt_session"):
                    router.prompt_session = PromptSession(
                        history=InMemoryHistory(),
                        auto_suggest=AutoSuggestFromHistory(),
                    )
                command = router.prompt_session.prompt(user_prompt()).strip()
            except ImportError:
                # Fallback for lowest-end PCs missing prompt_toolkit
                command = input(user_prompt()).strip()
                
        except (EOFError, KeyboardInterrupt):
            print("\n[OK] Goodbye")
            return

        if command.startswith("/modelsdir") or command.startswith("/_models"):
            raw = command.split(" ", 1)[1].strip() if " " in command else ""
            if not raw:
                print(f"Current models folder: {config.models_dir}")
                continue
            chosen_dir = Path(raw.strip().strip("'\"")).expanduser()
            if not chosen_dir.exists():
                print(f"[ERR] Folder not found: {chosen_dir}")
                continue
            set_saved_models_dir(chosen_dir)
            print(f"[OK] Saved. Restart to apply.")
            continue

        if command == "/_clearmodels":
            clear_saved_models_dir()
            clear_cached_model()
            print("[OK] Cleared. Restart to apply.")
            continue

        if command in ("/_pickmodel", "/model"):
            new_model = choose_model(config.models_dir)
            if new_model:
                set_cached_model(config.models_dir, new_model)
                print(f"[OK] Model set: {new_model.name}. Restart to apply.")
            continue

        if not router.handle(command):
            return


def main() -> int:
    enable_terminal_updates()
    args = parse_args()
    config = build_config(args)
    if not config:
        return 1

    server_proc = None
    ui_proc = None
    coder_proc = None

    if not server_ready(config.base_url):
        server_proc = start_server(config)
        if not server_proc:
            return 1

    if config.tri_model:
        if config.analyzer_config and config.analyzer_config.base_url != config.base_url:
            if not server_ready(config.analyzer_config.base_url):
                ui_proc = start_server(config.analyzer_config)
                if not ui_proc:
                    print("[WARN] Analyzer model failed.")
        
        if config.coder_config and config.coder_config.base_url != config.base_url:
            # Handle same port fallback
            base_urls = [config.base_url]
            if config.analyzer_config: base_urls.append(config.analyzer_config.base_url)
            
            if config.coder_config.base_url not in base_urls:
                if not server_ready(config.coder_config.base_url):
                    coder_proc = start_server(config.coder_config)
                    if not coder_proc:
                        print("[WARN] Coder model failed.")

    elif config.ui_config and config.ui_config.base_url != config.base_url:
        if not server_ready(config.ui_config.base_url):
            ui_proc = start_server(config.ui_config)
            if not ui_proc:
                print("[WARN] UI model failed. Falling back to agent model.")
                config.ui_config = None

    try:
        ok(f"Agent model: {config.model.name}")
        if config.tri_model:
            if config.analyzer_config:
                ok(f"Analyzer model: {config.analyzer_config.model.name}")
            if config.coder_config:
                ok(f"Coder model: {config.coder_config.model.name}")
        elif config.ui_config:
            ok(f"UI model:    {config.ui_config.model.name}")
        repl(config)
        return 0
    finally:
        for proc in (server_proc, ui_proc, coder_proc):
            if proc and proc.poll() is None:
                proc.terminate()
