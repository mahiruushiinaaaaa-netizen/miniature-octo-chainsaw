"""
cli_v2.py – Modernized CLI entry point with health checks and observability.

New features:
- Startup health validation
- Structured logging
- Recovery mechanisms
- Environment-aware configuration
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path
from typing import Optional

# Import new core infrastructure
from .logger import get_logger, LogLevel
from .config_manager import get_config
from .environment import get_environment
from .metrics import get_metrics_collector
from .validators import HealthChecker, DependencyValidator, OPTIONAL_DEPS
from .errors import MiniAIError, ResourceNotFoundError, ErrorContext
from .recovery import RecoveryManager
# (Already imported from .environment)

# Import legacy modules (to be gradually migrated)
from .backend import server_ready, start_server
from .commands import CommandRouter
from .config import AppConfig, Config, ModelConfig, _DEFAULT_THREADS, _DEFAULT_CTX, DEFAULT_HOST, DEFAULT_PORT
from ..ui import err, ok, enable_terminal, header, help_hint, user_prompt
from ..tools.discovery import (
    auto_choose_model,
    auto_choose_ui_model,
    auto_choose_role_model,
    choose_model,
    find_llama_cli,
    find_llama_server,
)
from .settings import (
    clear_saved_models_dir,
    get_saved_models_dir,
    set_saved_models_dir,
    set_cached_model,
    clear_cached_model,
)


logger = get_logger("cli")

def _port_is_available(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
        return True
    except OSError:
        return False


def _pick_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])



def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(description="Mini AI – local AI CLI (v39)")
    
    # Model selection
    p.add_argument("--model", default=None, help="Path to GGUF model file")
    p.add_argument("--ui-model", default=None, help="Path to UI model (for dual-model mode)")
    p.add_argument("--dual-model", action="store_true", help="Enable dual-model mode")
    p.add_argument("--choose-model", action="store_true", help="Interactive model selection")
    p.add_argument("--agent-model", default=None, help="Path to Agent model")
    p.add_argument("--analyzer-model", default=None, help="Path to Analyzer model")
    p.add_argument("--coder-model", default=None, help="Path to Coder model")
    p.add_argument("--tri-model", action="store_true", help="Enable tri-model mode")
    p.add_argument("--coder-port", type=int, default=8082, help="Coder server port")
    
    # Paths
    p.add_argument("--models-dir", default=None, help="Models directory")
    p.add_argument("--workspace", default=None, help="Working directory")
    p.add_argument("--set-models-dir", default=None, help=argparse.SUPPRESS)
    p.add_argument("--clear-models-dir", action="store_true", help=argparse.SUPPRESS)
    
    # Binaries
    p.add_argument("--bin", default=None, help="Path to llama-cli binary")
    p.add_argument("--server-bin", default=None, help="Path to llama-server binary")
    
    # Model parameters
    p.add_argument("--threads", type=int, default=_DEFAULT_THREADS, help="Number of threads")
    p.add_argument("--ctx", type=int, default=_DEFAULT_CTX, help="Context size")
    p.add_argument("--temp", type=float, default=0.0, help="Temperature")
    p.add_argument("--seed", type=int, default=None, help="Random seed")
    p.add_argument("--timeout", type=int, default=120, help="Request timeout")
    
    # Network
    p.add_argument("--host", default=DEFAULT_HOST, help="Server host")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server port")
    p.add_argument("--ui-port", type=int, default=8081, help="UI server port")
    
    # Features
    p.add_argument("--allow-run", "--auto-run", action="store_true", help="Allow command execution")
    p.add_argument("--agent-tokens", type=int, default=1024, help="Max agent tokens")
    p.add_argument("--low-end", action="store_true", help="Force low-end mode optimizations")
    
    # Logging
    p.add_argument("--verbose", action="store_true", help="Verbose output")
    p.add_argument("--debug", action="store_true", help="Debug output")
    p.add_argument("--json-log", action="store_true", help="JSON logging output")
    
    # Health check only
    p.add_argument("--health-check", action="store_true", help="Run health check and exit")
    
    # Metrics export
    p.add_argument("--metrics-export", type=str, default=None, help="Export metrics to file on exit")
    p.add_argument("--metrics-format", type=str, default="json", choices=["json", "prometheus"],
                   help="Metrics export format")
    
    return p.parse_args()


def run_health_checks(config: AppConfig, server_url: Optional[str] = None) -> bool:
    """Run startup health checks."""
    logger.info("Running startup health checks...")
    
    checker = HealthChecker()
    validator = DependencyValidator()
    
    # Check dependencies
    dep_results = validator.validate_all(OPTIONAL_DEPS)
    for name, result in dep_results.items():
        if result.passed:
            logger.info(f"✓ {name}: {result.message}")
        else:
            logger.warn(f"⚠ {name}: {result.message}")
    
    # System health
    results = checker.full_health_check(config.workspace, server_url)
    
    # Log results
    for name, result in results.items():
        if result.passed:
            logger.info(f"✓ {name}: {result.message}")
        else:
            logger.warn(f"✕ {name}: {result.message}")
            if result.fix_suggestion:
                logger.info(f"  → {result.fix_suggestion}")
    
    all_passed = all(r.passed for r in results.values())
    
    if not all_passed:
        print("\n" + checker.generate_report(results))
    
    return all_passed


def build_config_v2(args: argparse.Namespace) -> Optional[AppConfig]:
    """Build configuration using new core system."""
    # Handle legacy settings commands
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
    
    env_overrides: dict[str, object] = {}
    
    if getattr(args, "agent_model", None):
        args.model = args.agent_model
        
    if args.models_dir:
        env_overrides["models_dir"] = str(Path(args.models_dir).expanduser())
    if args.workspace:
        env_overrides["workspace"] = str(Path(args.workspace).expanduser())
    if args.allow_run:
        env_overrides["allow_run"] = True
    if args.verbose:
        env_overrides["verbose"] = True
    if args.dual_model:
        env_overrides["dual_model"] = True
    if args.host != DEFAULT_HOST:
        env_overrides["host"] = args.host
    if args.port != DEFAULT_PORT:
        env_overrides["port"] = args.port
    if args.threads != _DEFAULT_THREADS:
        env_overrides["threads"] = args.threads
    if args.ctx != _DEFAULT_CTX:
        env_overrides["ctx"] = args.ctx
    if args.temp != 0.0:
        env_overrides["temp"] = args.temp

    config = get_config(env_overrides or None)

    saved_dir = get_saved_models_dir()
    if saved_dir and not args.models_dir and not os.environ.get("MINIAI_MODELS_DIR"):
        config.models_dir = saved_dir

    if args.health_check:
        if args.workspace:
            config.workspace = Path(args.workspace).expanduser().resolve()
        return config

    if not config.models_dir.exists():
        err(f"Models folder not found: {config.models_dir}")
        return None

    if args.model:
        model = Path(args.model).expanduser()
    elif args.choose_model:
        model = choose_model(config.models_dir)
    else:
        # Prioritize agent folder if using tri-model
        if getattr(args, "tri_model", False):
            model = auto_choose_role_model(config.models_dir, "agent") or auto_choose_model(config.models_dir)
        else:
            model = auto_choose_model(config.models_dir)

    if not model or not model.exists():
        logger.warn(f"Model not found: {model}. CLI will start without an active agent.")
        model = None

    cli_bin = find_llama_cli(args.bin) or config.llama_cli_bin
    server_bin = find_llama_server(args.server_bin, cli_bin) or config.llama_server_bin

    if not server_bin:
        logger.warn("llama-server not found. Auto-agent features will be disabled.")
        server_bin = None

    env = get_environment()
    is_low_end = args.low_end or (env.cpu_count <= 2 and (env.ram_mb or 4096) < 4096)

    if is_low_end:
        logger.info("Low-end mode enabled: using optimized settings")
        threads = min(2, max(1, env.cpu_count - 1))
        ctx = 512 if (env.ram_mb or 4096) > 3000 else 384
        timeout = 120
        agent_tokens = 64
    else:
        threads = max(1, args.threads)
        ctx = max(128, args.ctx)
        timeout = max(1, args.timeout)
        agent_tokens = max(80, args.agent_tokens)

    config.agent_model.model_path = model
    config.agent_model.threads = threads
    config.agent_model.ctx = ctx
    config.agent_model.temp = args.temp
    config.agent_model.seed = args.seed
    config.agent_model.timeout = timeout
    config.agent_model.host = args.host
    config.agent_model.port = args.port
    config.agent_model.agent_tokens = agent_tokens
    config.agent_model.role = "agent"
    config.llama_server_bin = server_bin
    config.llama_cli_bin = cli_bin or server_bin

    if args.workspace:
        config.workspace = Path(args.workspace).expanduser().resolve()

    if getattr(args, "dual_model", False) and not getattr(args, "tri_model", False):
        ui_model_path = args.ui_model
        if ui_model_path:
            ui_model = Path(ui_model_path).expanduser()
        else:
            ui_model = auto_choose_ui_model(config.models_dir, avoid=model)

        if ui_model and ui_model.exists():
            config.ui_model = ModelConfig(
                model_path=ui_model,
                threads=max(1, min(args.threads, 2)),
                ctx=max(512, min(args.ctx, 1024)),
                temp=args.temp,
                seed=args.seed,
                timeout=90,
                host=args.host,
                port=args.ui_port,
                agent_tokens=96,
                role="ui",
            )
            config.dual_model = True

    if getattr(args, "tri_model", False):
        config.tri_model = True
        analyzer_path = getattr(args, "analyzer_model", None)
        coder_path = getattr(args, "coder_model", None)
        
        # Discovery with role-folder priority
        analyzer_model = Path(analyzer_path).expanduser() if analyzer_path else (auto_choose_role_model(config.models_dir, "analyzer") or auto_choose_ui_model(config.models_dir, avoid=model))
        
        # Avoid both agent and analyzer models for coder if possible
        avoid_list = [model]
        if analyzer_model: avoid_list.append(analyzer_model)
        
        coder_model = Path(coder_path).expanduser() if coder_path else (auto_choose_role_model(config.models_dir, "coder") or auto_choose_model(config.models_dir, avoid=avoid_list) or model)

        if analyzer_model and analyzer_model.exists():
            config.analyzer_model = ModelConfig(
                model_path=analyzer_model,
                threads=max(1, min(args.threads, 2)),
                ctx=max(512, min(args.ctx, 2048)),
                temp=args.temp,
                seed=args.seed,
                timeout=120,
                host=args.host,
                port=args.ui_port,
                agent_tokens=256,
                role="analyzer",
            )
            config.ui_model = config.analyzer_model

        if coder_model and coder_model.exists():
            config.coder_model = ModelConfig(
                model_path=coder_model,
                threads=max(1, args.threads),
                ctx=max(1024, args.ctx),
                temp=args.temp,
                seed=args.seed,
                timeout=120,
                host=args.host,
                port=args.coder_port,
                agent_tokens=max(80, args.agent_tokens),
                role="coder",
            )
            
        if config.agent_model.model_path == analyzer_model == coder_model:
            logger.warn("Tri-model enabled but all roles share the same model file.")
            logger.info(f"→ Hint: Specialized models in '{config.models_dir}/agent|analyzer|coder' will be auto-detected.")


    return config


def repl(config: AppConfig) -> None:
    """Interactive REPL using prompt_toolkit for a premium experience."""
    header("Mini AI", f"Workspace: {config.workspace}")
    ok(f"Model: {config.agent_model.model_path.name if config.agent_model.model_path else 'none'}")
    if getattr(config, "tri_model", False):
        if config.analyzer_model:
            ok(f"Analyzer model: {config.analyzer_model.model_path.name if config.analyzer_model.model_path else 'none'}")
        if config.coder_model:
            ok(f"Coder model: {config.coder_model.model_path.name if config.coder_model.model_path else 'none'}")
    elif config.ui_model:
        ok(f"UI model: {config.ui_model.model_path.name if config.ui_model.model_path else 'none'}")
    help_hint()
    print("")
    
    legacy_config = Config.from_app_config(config, config.agent_model, role="agent")
    if getattr(config, "tri_model", False):
        legacy_config.tri_model = True
        if config.analyzer_model:
            legacy_config.analyzer_config = Config.from_app_config(config, config.analyzer_model, role="analyzer")
            legacy_config.ui_config = legacy_config.analyzer_config
        if config.coder_model:
            legacy_config.coder_config = Config.from_app_config(config, config.coder_model, role="coder")
    elif config.ui_model:
        legacy_config.ui_config = Config.from_app_config(config, config.ui_model, role="ui")
    
    router = CommandRouter(legacy_config)

    # Setup prompt_toolkit
    session = None
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
        from prompt_toolkit.styles import Style
        
        history_path = Path.home() / ".mini_ai_history"
        session = PromptSession(
            history=FileHistory(str(history_path)),
            auto_suggest=AutoSuggestFromHistory(),
        )
        HAS_PTK = True
    except ImportError:
        HAS_PTK = False

    while True:
        try:
            if session:
                command = session.prompt("you › ").strip()
            else:
                command = input("you › ").strip()
        except (EOFError, KeyboardInterrupt):
            ok("Goodbye")
            return
        
        if not command: continue

        # Handle built-in model commands
        if command.startswith("/modelsdir"):
            raw = command.split(" ", 1)[1].strip() if " " in command else ""
            if not raw:
                print(f"Current models folder: {config.models_dir}")
                continue
            chosen_dir = Path(raw.strip().strip("'\"")).expanduser()
            if not chosen_dir.exists():
                err(f"Folder not found: {chosen_dir}")
                continue
            set_saved_models_dir(chosen_dir)
            ok("Saved. Restart to apply.")
            continue
        
        if command == "/model":
            new_model = choose_model(config.models_dir)
            if new_model:
                set_cached_model(config.models_dir, new_model)
                ok(f"Model set: {new_model.name}. Restart to apply.")
            continue
        
        if not router.handle(command):
            return


def main() -> int:
    """Main entry point."""
    # Setup terminal
    enable_terminal()
    
    # Parse arguments
    args = parse_args()
    
    # Configure logging
    log_level = LogLevel.DEBUG if args.debug else (LogLevel.INFO if args.verbose else LogLevel.WARN)
    from .logger import configure_logging
    configure_logging(level=log_level, json_output=args.json_log)
    
    logger.info("Mini AI starting up", context={"version": "39.0.0"})
    
    # Log environment info
    env = get_environment()
    logger.debug(
        "Environment detected",
        context={
            "os": env.os_type.name,
            "python": env.python_version,
            "cpu_count": env.cpu_count,
            "ram_mb": env.ram_mb,
        },
    )
    
    # Build configuration
    try:
        config = build_config_v2(args)
        if not config:
            return 1
    except MiniAIError as e:
        logger.error(f"Configuration error: {e}")
        return 1
    
    # Health check only mode
    if args.health_check:
        success = run_health_checks(config)
        
        # Export metrics if requested even in health-check mode
        if args.metrics_export:
            metrics = get_metrics_collector()
            export_path = Path(args.metrics_export).expanduser()
            try:
                if args.metrics_format == "prometheus":
                    content = metrics.export_prometheus()
                    export_path.write_text(content, encoding="utf-8")
                else:
                    metrics.export_json(export_path)
                logger.info(f"Metrics exported to {export_path}")
            except Exception as e:
                logger.error(f"Failed to export metrics: {e}")
        
        return 0 if success else 1
    
    server_proc = None
    ui_proc = None
    coder_proc = None
    
    try:
        if not server_ready(config.agent_model.base_url):
            if not _port_is_available(config.agent_model.host, config.agent_model.port):
                new_port = _pick_free_port(config.agent_model.host)
                logger.warn(
                    "Requested port is busy; switching to a free port",
                    operation="server_start",
                    context={"from": config.agent_model.port, "to": new_port, "host": config.agent_model.host},
                )
                config.agent_model.port = new_port
            logger.info(f"Starting llama-server on {config.agent_model.base_url}")
            legacy_config = Config.from_app_config(config, config.agent_model, role="agent")
            server_proc = start_server(legacy_config)
            if not server_proc:
                logger.warn("Primary agent model failed to start. Local commands only.")

        server_url = config.agent_model.base_url
        if not run_health_checks(config, server_url):
            if not args.allow_run:  # In strict mode, fail on health check
                logger.error("Health checks failed. Use --allow-run to proceed anyway.")
                return 1
            logger.warn("Proceeding despite health check failures (--allow-run)")
        
        if getattr(config, "tri_model", False):
            if config.analyzer_model and not server_ready(config.analyzer_model.base_url):
                logger.info(f"Starting Analyzer llama-server on {config.analyzer_model.base_url}")
                ui_legacy = Config.from_app_config(config, config.analyzer_model, role="analyzer")
                ui_proc = start_server(ui_legacy)
                if not ui_proc:
                    logger.warn("Analyzer model failed to start.")
            
            if config.coder_model and config.coder_model.base_url != config.agent_model.base_url:
                base_urls = [config.agent_model.base_url]
                if config.analyzer_model: base_urls.append(config.analyzer_model.base_url)
                
                if config.coder_model.base_url not in base_urls:
                    if not server_ready(config.coder_model.base_url):
                        logger.info(f"Starting Coder llama-server on {config.coder_model.base_url}")
                        coder_legacy = Config.from_app_config(config, config.coder_model, role="coder")
                        coder_proc = start_server(coder_legacy)
                        if not coder_proc:
                            logger.warn("Coder model failed to start.")
        elif config.ui_model:
            if not server_ready(config.ui_model.base_url):
                logger.info(f"Starting UI llama-server on {config.ui_model.base_url}")
                ui_legacy = Config.from_app_config(config, config.ui_model, role="ui")
                ui_proc = start_server(ui_legacy)
                if not ui_proc:
                    logger.warn("UI model failed to start. Falling back to agent model.")
                    config.ui_model = None
        
        # Main loop
        if config.agent_model.model_path:
            ok(f"Agent model: {config.agent_model.model_path.name}")
        else:
            err("No agent model loaded. LLM features disabled.")
        if getattr(config, "tri_model", False):
            if config.analyzer_model:
                ok(f"Analyzer model: {config.analyzer_model.model_path.name if config.analyzer_model.model_path else 'none'}")
            if config.coder_model:
                ok(f"Coder model: {config.coder_model.model_path.name if config.coder_model.model_path else 'none'}")
        elif config.ui_model:
            ok(f"UI model: {config.ui_model.model_path.name if config.ui_model.model_path else 'none'}")
        
        repl(config)
        return 0
        
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 0
    except Exception as e:
        logger.error(f"Unexpected error: {e}", error=e)
        return 1
    finally:
        # Cleanup
        logger.info("Shutting down...")
        for proc in (server_proc, ui_proc, coder_proc):
            if proc and proc.poll() is None:
                proc.terminate()
        
        # Export metrics if requested
        if args.metrics_export:
            metrics = get_metrics_collector()
            export_path = Path(args.metrics_export).expanduser()
            try:
                if args.metrics_format == "prometheus":
                    content = metrics.export_prometheus()
                    export_path.write_text(content, encoding="utf-8")
                else:
                    metrics.export_json(export_path)
                logger.info(f"Metrics exported to {export_path}")
            except Exception as e:
                logger.error(f"Failed to export metrics: {e}")
        
        # Close loggers
        from .logger import close_all_loggers
        close_all_loggers()


if __name__ == "__main__":
    raise SystemExit(main())
