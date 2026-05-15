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
    p.add_argument("--copix", action="store_true", help="Use CopixTUI (Copilot/Codex-style interface)")
    p.add_argument("--ollama", action="store_true", help="Use Ollama backend (no llama-server needed)")
    p.add_argument("--ollama-model", type=str, default="", help="Ollama model for agent tasks (selected at startup if empty)")
    p.add_argument("--ollama-fast", type=str, default="", help="Ollama fast model for intent/chat (selected at startup if empty)")
    p.add_argument("--pick-model", action="store_true", help="Force model re-selection (ignore saved config)")
    p.add_argument("-c", "--command", type=str, default=None, help="Execute a command non-interactively and exit")
    
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
    config.gpu_layers = getattr(args, 'gpu_layers', 0)
    
    # Ollama is the ONLY backend — always enabled
    config.use_ollama = True
    config.ollama_model = getattr(args, 'ollama_model', '') or getattr(config, 'ollama_model', '')
    config.ollama_fast_model = getattr(args, 'ollama_fast', '') or getattr(config, 'ollama_fast_model', '')

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


def repl(config: AppConfig, use_copix: bool = False) -> None:
    """Interactive REPL using prompt_toolkit or CopixTUI for a premium experience."""
    
    # Enable CopixTUI if requested
    if use_copix:
        from ..ui import CopixTUI
        model_name = config.agent_model.model_path.name if config.agent_model.model_path else "Mini AI"
        copix = CopixTUI(model_name=model_name)
        copix.render()  # Render initial header
    else:
        # Old UI header
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
    
    # Enable CopixTUI if requested
    legacy_config.use_copix = use_copix
    
    # Propagate Ollama settings to legacy config
    if getattr(config, 'use_ollama', False):
        legacy_config.use_ollama = True
        legacy_config.ollama_model = getattr(config, 'ollama_model', 'sorc/qwen3.5-claude-4.6-opus-q4:2b')
        legacy_config.ollama_fast_model = getattr(config, 'ollama_fast_model', 'qwen2.5:0.5b')
    
    router = CommandRouter(legacy_config)

    # Setup prompt_toolkit — only if stdin is a real terminal
    session = None
    HAS_PTK = False
    if sys.stdin.isatty():
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
        except (ImportError, Exception):
            HAS_PTK = False

    # Use CopixTUI for input if enabled
    use_copix_input = getattr(router, 'copix', None) is not None
    
    while True:
        try:
            if use_copix_input:
                # Use CopixTUI elegant prompt
                command = router.copix.get_input()
            elif session:
                try:
                    command = session.prompt("you › ").strip()
                except Exception:
                    # Fall back to plain input if prompt_toolkit fails (e.g., piped stdin)
                    session = None
                    command = input("you › ").strip()
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


def _warmup_ollama_models(config) -> None:
    """Force Ollama to load models into RAM. Pull if not available."""
    import json
    import urllib.request
    
    ollama_url = "http://127.0.0.1:11434"
    models_to_warm = [config.ollama_model, config.ollama_fast_model]
    
    for model in models_to_warm:
        if not model:
            continue
        try:
            payload = {
                "model": model,
                "prompt": "hi",
                "stream": False,
                "keep_alive": "30m",  # Keep loaded for 30 minutes
                "options": {"num_predict": 1},
            }
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{ollama_url}/api/generate",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode())
                if result.get("error"):
                    raise RuntimeError(result["error"])
            ok(f"Loaded: {model}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Model not pulled — ask to pull it
                print(f"  Model '{model}' not found locally.")
                ans = input(f"  Pull '{model}' from Ollama? (y/n): ").strip().lower()
                if ans in ("y", "yes", ""):
                    print(f"  Pulling {model}... (this may take a few minutes)")
                    try:
                        pull_payload = json.dumps({"name": model, "stream": False}).encode()
                        pull_req = urllib.request.Request(
                            f"{ollama_url}/api/pull",
                            data=pull_payload,
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(pull_req, timeout=600) as pull_resp:
                            pull_resp.read()
                        ok(f"Pulled and loaded: {model}")
                    except Exception as pe:
                        err(f"Pull failed: {pe}")
                else:
                    err(f"Skipped: {model}")
            else:
                err(f"Failed to load {model}: {e}")
        except Exception as e:
            err(f"Failed to load {model}: {e}")


def _select_ollama_models(config, force_pick: bool = False) -> tuple[str, str]:
    """Query Ollama for available models and let user pick main + fast model.
    
    Saves selection to .mini_ai_models.json so it doesn't ask every time.
    Looks for config in order:
      1. MINI_AI_MODELS env var (path to .mini_ai_models.json)
      2. ~/.mini_ai_models.json (user home)
      3. <workspace>/.mini_ai_models.json (project dir)
    """
    import json
    import urllib.request
    from pathlib import Path
    import os
    
    # Check saved config — search multiple locations
    save_file = None
    search_paths = []
    
    # 1. Environment variable
    env_path = os.environ.get("MINI_AI_MODELS")
    if env_path:
        search_paths.append(Path(env_path))
    
    # 2. User home directory
    search_paths.append(Path.home() / ".mini_ai_models.json")
    
    # 3. Workspace directory
    search_paths.append(Path(config.workspace) / ".mini_ai_models.json")
    
    if not force_pick:
        for candidate in search_paths:
            if candidate.exists():
                try:
                    # Use utf-8-sig to tolerate BOM from PowerShell-written files
                    saved = json.loads(candidate.read_text(encoding='utf-8-sig'))
                    if saved.get("main") and saved.get("fast"):
                        return saved["main"], saved["fast"]
                except Exception:
                    pass
    
    # Use the first writable location for saving
    if env_path:
        save_file = Path(env_path)
    else:
        save_file = Path.home() / ".mini_ai_models.json"
    
    # Query Ollama for available models
    models = []
    for attempt in range(3):
        try:
            req = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
            if models:
                break
        except Exception:
            pass
        import time
        time.sleep(1)  # Wait for Ollama to be fully ready
    
    if not models:
        err("No models found in Ollama. Pull a model first: ollama pull qwen2.5:0.5b")
        return "", ""
    
    print("\n┌─────────────────────────────────────┐")
    print("│     Mini AI — Model Selection       │")
    print("└─────────────────────────────────────┘\n")
    
    # Show available models
    print("Available models:")
    for i, m in enumerate(models, 1):
        print(f"  {i}. {m}")
    print()
    
    # Select main model
    main_model = ""
    while not main_model:
        try:
            choice = input("Select MAIN model (for coding/agent tasks) [number]: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                main_model = models[idx]
            else:
                print("  Invalid choice.")
        except (ValueError, EOFError):
            if len(models) == 1:
                main_model = models[0]
            else:
                print("  Enter a number.")
    
    # Select fast model
    fast_model = ""
    while not fast_model:
        try:
            choice = input("Select FAST model (for intent/chat, pick smallest) [number]: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                fast_model = models[idx]
            else:
                print("  Invalid choice.")
        except (ValueError, EOFError):
            # Default to smallest available or same as main
            fast_model = models[-1] if len(models) > 1 else main_model
    
    # Save selection
    try:
        save_file.write_text(json.dumps({"main": main_model, "fast": fast_model}, indent=2))
    except Exception:
        pass
    
    print()
    return main_model, fast_model


def main() -> int:
    """Main entry point."""
    # Setup terminal
    enable_terminal()
    
    # Parse arguments
    args = parse_args()
    
    # Configure logging
    # When using CopixTUI, force WARN level to prevent UI overlap
    use_copix = getattr(args, 'copix', False)
    if use_copix and not args.debug and not args.verbose:
        log_level = LogLevel.WARN  # Suppress INFO logs for clean UI
    else:
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
    
    # Store metrics config locally for safe access in finally block
    _metrics_export = getattr(args, 'metrics_export', None)
    _metrics_format = getattr(args, 'metrics_format', 'json')
    
    try:
        # ── Ollama startup with model selection ──
        from .server_manager import get_server_manager
        from .backend import ollama_available
        mgr = get_server_manager(getattr(config, 'idle_timeout', 180))
        
        if not mgr.ensure_ollama():
            # Double-check directly — ensure_ollama might fail to start but Ollama could already be running
            import urllib.request as _ur
            try:
                _req = _ur.Request("http://127.0.0.1:11434/api/tags", method="GET")
                with _ur.urlopen(_req, timeout=3) as _resp:
                    if _resp.status != 200:
                        err("Ollama is not running. Install from https://ollama.com and start it.")
                        return 1
            except Exception:
                err("Ollama is not running. Install from https://ollama.com and start it.")
                return 1
        
        # Query available models and let user choose if not configured
        if args.pick_model or not config.ollama_model or not config.ollama_fast_model:
            if args.pick_model:
                # Clear saved config to force fresh selection
                config.ollama_model = ""
                config.ollama_fast_model = ""
            config.ollama_model, config.ollama_fast_model = _select_ollama_models(config, force_pick=args.pick_model)
            if not config.ollama_model:
                err("No models selected. Exiting.")
                return 1
        
        ok(f"Main model: {config.ollama_model}")
        ok(f"Fast model: {config.ollama_fast_model}")
        
        # Warm up models (force Ollama to load them into RAM)
        _warmup_ollama_models(config)

        server_url = "http://127.0.0.1:11434"
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
    except Exception as e:
        logger.error(f"Server startup error: {e}")
        if not args.allow_run:
            return 1
        logger.warn("Proceeding despite server startup error (--allow-run)")
        
    # Main loop
    try:
        if config.agent_model.model_path:
            ok(f"Agent model: {config.agent_model.model_path.name}")
        else:
            err("No agent model loaded. LLM features disabled.")
            
        # Sandbox status
        sb_type = config.sandbox_type.upper()
        ok(f"Sandbox: {sb_type} (Isolation: {'Active' if sb_type != 'LOCAL' else 'Host-Level'})")

        if getattr(config, "tri_model", False):
            if config.analyzer_model:
                ok(f"Analyzer model: {config.analyzer_model.model_path.name if config.analyzer_model.model_path else 'none'}")
            if config.coder_model:
                ok(f"Coder model: {config.coder_model.model_path.name if config.coder_model.model_path else 'none'}")
        elif config.ui_model:
            ok(f"UI model: {config.ui_model.model_path.name if config.ui_model.model_path else 'none'}")
        
        # Non-interactive mode: execute a single command and exit
        if args.command:
            legacy_config = Config.from_app_config(config, config.agent_model, role="agent")
            if getattr(config, 'use_ollama', False):
                legacy_config.use_ollama = True
                legacy_config.ollama_model = getattr(config, 'ollama_model', '')
                legacy_config.ollama_fast_model = getattr(config, 'ollama_fast_model', 'qwen2.5:0.5b')
            legacy_config.use_copix = False
            
            # For complex tasks (multi-step), use the orchestrator
            # which decomposes into small steps and feeds them 1-by-1 to the main model
            goal = args.command
            lowered = goal.lower()
            is_complex = (
                len(goal.split()) > 10 or
                any(kw in lowered for kw in ["create", "build", "make", "setup", "implement",
                                             "with", "then", "also", "and", "customize"])
            )
            
            if is_complex:
                from .commands import CommandRouter
                router = CommandRouter(legacy_config)
                # Use orchestrator mode for complex tasks
                router.use_orchestrator = True
                router.run_agent(goal)
            else:
                from .commands import CommandRouter
                router = CommandRouter(legacy_config)
                router.handle(goal)
            return 0

        repl(config, use_copix=use_copix)
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
        
        # Export metrics if requested (uses local variables set before try block)
        if _metrics_export:
            metrics = get_metrics_collector()
            export_path = Path(_metrics_export).expanduser()
            try:
                if _metrics_format == "prometheus":
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
