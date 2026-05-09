"""
config_manager.py – Centralized, environment-aware configuration.

Features:
- Hierarchical config sources (defaults < env vars < config file < CLI args)
- Dynamic path discovery
- Environment-specific defaults
- Type-safe access
- Validation and migration
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional, Union, get_type_hints
import tempfile

from .logger import get_logger
from .errors import ConfigurationError, ErrorContext
from .environment import get_environment, OSType

logger = get_logger("config")


# Configuration constants
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
DEFAULT_AGENT_TOKENS = 4096
DEFAULT_CTX = 8192
DEFAULT_TIMEOUT = 120


@dataclass
class ModelConfig:
    """Configuration for a model instance."""
    model_path: Optional[Path] = None
    threads: int = 4
    ctx: int = DEFAULT_CTX
    temp: float = 0.0
    seed: Optional[int] = None
    timeout: int = DEFAULT_TIMEOUT
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    agent_tokens: int = DEFAULT_AGENT_TOKENS
    role: str = "agent"
    
    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass
class AppConfig:
    """Application configuration."""
    # Paths
    models_dir: Path = field(default_factory=lambda: Path.home() / ".lmstudio" / "models")
    workspace: Path = field(default_factory=lambda: Path.cwd())
    
    # Binaries (auto-detected if None)
    llama_server_bin: Optional[Path] = None
    llama_cli_bin: Optional[Path] = None
    
    # Model configs
    agent_model: ModelConfig = field(default_factory=ModelConfig)
    ui_model: Optional[ModelConfig] = None
    analyzer_model: Optional[ModelConfig] = None
    coder_model: Optional[ModelConfig] = None
    
    # Features
    allow_run: bool = False
    use_server: bool = True
    dual_model: bool = False
    tri_model: bool = False
    sandbox_type: str = "local"  # options: "local", "venv", "docker"
    
    # UI
    compact_ui: bool = False
    verbose: bool = False
    
    # Execution
    max_steps: int = 30
    
    # Paths discovered
    _config_dir: Optional[Path] = None
    _cache_dir: Optional[Path] = None
    
    def __post_init__(self):
        # Resolve paths
        self.models_dir = Path(self.models_dir).expanduser().resolve()
        self.workspace = Path(self.workspace).expanduser().resolve()
        
        if self.llama_server_bin:
            self.llama_server_bin = Path(self.llama_server_bin).expanduser().resolve()
        if self.llama_cli_bin:
            self.llama_cli_bin = Path(self.llama_cli_bin).expanduser().resolve()
        
        # Setup model config backreferences
        if self.agent_model.model_path:
            self.agent_model.model_path = Path(self.agent_model.model_path).expanduser().resolve()


class ConfigManager:
    """Centralized configuration management."""
    
    # Environment variable prefix
    ENV_PREFIX = "MINIAI_"
    
    # Known environment variable mappings
    ENV_MAPPINGS = {
        "models_dir": "MODELS_DIR",
        "workspace": "WORKSPACE",
        "llama_server_bin": "SERVER_BIN",
        "llama_cli_bin": "CLI_BIN",
        "allow_run": "ALLOW_RUN",
        "host": "HOST",
        "port": "PORT",
        "threads": "THREADS",
        "ctx": "CTX",
        "temp": "TEMP",
    }
    
    def __init__(self):
        self._config: Optional[AppConfig] = None
        self._env = get_environment()
        self._config_file: Optional[Path] = None
    
    def load(
        self,
        cli_args: Optional[dict[str, Any]] = None,
        config_path: Optional[Path] = None,
    ) -> AppConfig:
        """
        Load configuration from all sources.
        
        Priority (low to high):
        1. Environment-specific defaults
        2. Environment variables (MINIAI_*)
        3. Config file (~/.config/mini_ai_cli/config.json)
        4. CLI arguments
        """
        # Start with defaults
        config = self._default_config()
        
        # Apply environment variables
        config = self._apply_env_vars(config)
        
        # Apply config file
        config = self._apply_config_file(config, config_path)
        
        # Apply CLI args (highest priority)
        if cli_args:
            config = self._apply_cli_args(config, cli_args)
        
        # Auto-detect missing paths
        config = self._auto_detect(config)
        
        # Validate
        self._validate(config)
        
        self._config = config
        logger.info("Configuration loaded", context={"models_dir": str(config.models_dir)})
        
        return config
    
    def _is_low_end_device(self, env) -> bool:
        """
        Detect low-end devices more accurately.
        
        Considers:
        - CPU count (<= 2 physical cores)
        - RAM amount (< 4GB)
        - CPU family (mobile/low-power indicators)
        - Total compute capacity
        """
        cpu_count = env.cpu_count
        ram_mb = env.ram_mb or 4096
        
        # Explicit low-end indicators
        is_low_core = cpu_count <= 2
        is_low_ram = ram_mb < 4096
        
        # Mobile/low-power CPU detection from CPU info
        cpu_info = getattr(env, "cpu_info", None)
        is_mobile_cpu = False
        if isinstance(cpu_info, dict):
            cpu_name = str(cpu_info.get("brand_raw", "")).lower()
            is_mobile_cpu = any(x in cpu_name for x in (
                "mobile",
                "u-series",
                "u series",
                "atom",
                "celeron",
                "pentium silver",
                "core m",
                "m3-",
                "m5-",
                "m7-",
            ))
        
        # Conservative detection: if any 2 of 3 conditions met
        low_end_score = sum([is_low_core, is_low_ram, is_mobile_cpu])
        return low_end_score >= 2
    
    def _default_config(self) -> AppConfig:
        """Create default configuration based on environment."""
        env = self._env
        
        # More accurate low-end detection
        is_low_end = self._is_low_end_device(env)
        ram_mb = env.ram_mb or 4096
        
        # Aggressive low-end optimizations
        if is_low_end:
            # For very low-end like i5-5300U:
            # - Use only 1-2 threads (not all logical cores)
            # - Minimal context window to save RAM
            # - Shorter timeouts
            # - Lower token limits
            threads = min(4, max(1, env.cpu_count - 1))
            ctx = 4096 if ram_mb > 4000 else 2048
            agent_tokens = 1024
            timeout = 180
            logger.info(
                f"Low-end device detected: threads={threads}, ctx={ctx}, "
                f"ram={ram_mb}MB, cpu_count={env.cpu_count}"
            )
        else:
            threads = max(1, min(env.cpu_count, 8))
            ctx = 8192
            agent_tokens = 2048
            timeout = DEFAULT_TIMEOUT
        
        agent_model = ModelConfig(
            threads=threads,
            ctx=ctx,
            agent_tokens=agent_tokens,
            timeout=timeout,
        )
        
        # Auto-detect models dir based on common locations
        models_dir = self._find_models_dir()
        
        return AppConfig(
            models_dir=models_dir or Path.home() / ".lmstudio" / "models",
            agent_model=agent_model,
            workspace=Path.cwd(),
        )
    
    def _find_models_dir(self) -> Optional[Path]:
        """Find models directory from common locations."""
        candidates = []
        
        # 1. Check current directory and parents (Smarter zero-config discovery)
        try:
            curr = Path.cwd()
            # Search up to 3 levels up for a 'models' folder
            for _ in range(4):
                models_cand = curr / "models"
                if models_cand.is_dir():
                    candidates.append(models_cand)
                if curr.parent == curr:
                    break
                curr = curr.parent
        except Exception:
            pass
            
        # 2. Standard LM Studio locations
        candidates.append(Path.home() / ".lmstudio" / "models")
        
        if self._env.os_type == OSType.WINDOWS:
            candidates.extend([
                Path("C:/Program Files/LM Studio/models"),
                Path("C:/Program Files (x86)/LM Studio/models"),
                Path.home() / "AppData" / "Local" / "Programs" / "LM Studio" / "models",
            ])
        
        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                return candidate
        
        return None
    
    def _apply_env_vars(self, config: AppConfig) -> AppConfig:
        """Apply environment variable overrides."""
        for key, env_key in self.ENV_MAPPINGS.items():
            env_val = os.environ.get(f"{self.ENV_PREFIX}{env_key}")
            if env_val is None:
                continue
            
            try:
                if key == "models_dir":
                    config.models_dir = Path(env_val).expanduser()
                elif key == "workspace":
                    config.workspace = Path(env_val).expanduser()
                elif key == "llama_server_bin":
                    config.llama_server_bin = Path(env_val).expanduser() if env_val else None
                elif key == "llama_cli_bin":
                    config.llama_cli_bin = Path(env_val).expanduser() if env_val else None
                elif key == "allow_run":
                    config.allow_run = env_val.lower() in ("1", "true", "yes")
                elif key == "host":
                    config.agent_model.host = env_val
                elif key == "port":
                    config.agent_model.port = int(env_val)
                elif key == "threads":
                    config.agent_model.threads = int(env_val)
                elif key == "ctx":
                    config.agent_model.ctx = int(env_val)
                elif key == "temp":
                    config.agent_model.temp = float(env_val)
            except ValueError as e:
                logger.warn(f"Invalid env var {self.ENV_PREFIX}{env_key}: {e}")
        
        return config
    
    def _apply_config_file(
        self,
        config: AppConfig,
        explicit_path: Optional[Path] = None,
    ) -> AppConfig:
        """Apply settings from config file."""
        if explicit_path:
            path = explicit_path
        else:
            # Find platform-appropriate config location
            from .environment import EnvironmentDetector
            detector = EnvironmentDetector()
            config_dir = detector.get_config_dir()
            path = config_dir / "config.json"
        
        self._config_file = path
        
        if not path.exists():
            return config
        
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            
            # Apply settings
            if "models_dir" in data:
                config.models_dir = Path(data["models_dir"]).expanduser()
            if "workspace" in data:
                config.workspace = Path(data["workspace"]).expanduser()
            if "allow_run" in data:
                config.allow_run = bool(data["allow_run"])
            if "verbose" in data:
                config.verbose = bool(data["verbose"])
            
            # Model settings
            if "model" in data:
                m = data["model"]
                if isinstance(m, dict):
                    config.agent_model.model_path = Path(m["path"]).expanduser() if m.get("path") else None
                    config.agent_model.threads = m.get("threads", config.agent_model.threads)
                    config.agent_model.ctx = m.get("ctx", config.agent_model.ctx)
                    config.agent_model.temp = m.get("temp", config.agent_model.temp)
            
            logger.debug(f"Loaded config from {path}")
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid config file {path}: {e}")
        except Exception as e:
            logger.error(f"Could not load config {path}: {e}")
        
        return config
    
    def _apply_cli_args(self, config: AppConfig, args: dict[str, Any]) -> AppConfig:
        """Apply CLI argument overrides."""
        # Path arguments
        if args.get("models_dir"):
            config.models_dir = Path(args["models_dir"]).expanduser()
        if args.get("workspace"):
            config.workspace = Path(args["workspace"]).expanduser()
        if args.get("server_bin"):
            config.llama_server_bin = Path(args["server_bin"]).expanduser()
        if args.get("cli_bin"):
            config.llama_cli_bin = Path(args["cli_bin"]).expanduser()
        
        # Boolean flags
        if "allow_run" in args:
            config.allow_run = bool(args["allow_run"])
        if "verbose" in args:
            config.verbose = bool(args["verbose"])
        if "dual_model" in args:
            config.dual_model = bool(args["dual_model"])
        
        # Model settings
        if args.get("model"):
            config.agent_model.model_path = Path(args["model"]).expanduser()
        if args.get("threads"):
            config.agent_model.threads = int(args["threads"])
        if args.get("ctx"):
            config.agent_model.ctx = int(args["ctx"])
        if args.get("temp") is not None:
            config.agent_model.temp = float(args["temp"])
        if args.get("port"):
            config.agent_model.port = int(args["port"])
        if args.get("host"):
            config.agent_model.host = args["host"]
        
        return config
    
    def _auto_detect(self, config: AppConfig) -> AppConfig:
        """Auto-detect missing binary paths."""
        from .environment import EnvironmentDetector
        detector = EnvironmentDetector()
        
        # Find llama-server - use environment-aware paths
        if not config.llama_server_bin:
            candidates = []
            
            if self._env.os_type == OSType.WINDOWS:
                # Use environment variables for WinGet paths instead of hardcoded
                localappdata = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
                candidates = [
                    Path(localappdata) / "Microsoft" / "WinGet" / "Packages" / 
                    "ggml.llamacpp_Microsoft.Winget.Source_8wekyb3d8bbwe" / "llama-server.exe",
                    Path(localappdata) / "Programs" / "llama.cpp" / "llama-server.exe",
                ]
            elif self._env.os_type == OSType.MACOS:
                candidates = [
                    Path.home() / "Applications" / "llama.cpp" / "llama-server",
                    Path("/usr/local/bin") / "llama-server",
                    Path("/opt/homebrew/bin") / "llama-server",
                ]
            elif self._env.os_type == OSType.LINUX:
                candidates = [
                    Path.home() / ".local" / "bin" / "llama-server",
                    Path("/usr/local/bin") / "llama-server",
                    Path("/usr/bin") / "llama-server",
                ]
            
            found = detector.find_binary(["llama-server", "llama-server.exe"], candidates)
            if found:
                config.llama_server_bin = found
                logger.debug(f"Auto-detected llama-server: {found}")
        
        # Find llama-cli - platform-aware
        if not config.llama_cli_bin:
            cli_names = ["llama-cli", "llama-cli.exe", "llama"]
            if self._env.os_type == OSType.WINDOWS:
                cli_names.insert(0, "llama-cli.exe")
            found = detector.find_binary(cli_names)
            if found:
                config.llama_cli_bin = found
                logger.debug(f"Auto-detected llama-cli: {found}")
        
        return config
    
    def _validate(self, config: AppConfig) -> None:
        """Validate configuration."""
        errors = []
        
        if not config.models_dir.exists():
            logger.warn(
                f"Models directory does not exist: {config.models_dir}",
                operation="config_validation",
                context={"models_dir": str(config.models_dir)},
            )
        
        # Check workspace exists
        if not config.workspace.exists():
            errors.append(f"Workspace does not exist: {config.workspace}")
        
        # Validate model path if specified
        if config.agent_model.model_path and not config.agent_model.model_path.exists():
            errors.append(f"Model file not found: {config.agent_model.model_path}")
        
        # Validate binary paths if specified
        if config.llama_server_bin and not config.llama_server_bin.exists():
            errors.append(f"Server binary not found: {config.llama_server_bin}")
        
        if errors:
            raise ConfigurationError(
                f"Configuration validation failed: {'; '.join(errors)}",
                context=ErrorContext(
                    operation="config_validation",
                    recoverable=False,
                    suggested_action="Fix configuration and restart",
                ),
            )
    
    def save(self, config: AppConfig, path: Optional[Path] = None) -> None:
        """Save configuration to file."""
        save_path = path or self._config_file
        if not save_path:
            from .environment import EnvironmentDetector
            detector = EnvironmentDetector()
            config_dir = detector.get_config_dir()
            config_dir.mkdir(parents=True, exist_ok=True)
            save_path = config_dir / "config.json"
        
        # Convert to serializable dict
        data = {
            "models_dir": str(config.models_dir),
            "workspace": str(config.workspace),
            "allow_run": config.allow_run,
            "verbose": config.verbose,
        }
        
        if config.agent_model.model_path:
            data["model"] = {
                "path": str(config.agent_model.model_path),
                "threads": config.agent_model.threads,
                "ctx": config.agent_model.ctx,
                "temp": config.agent_model.temp,
            }
        
        # Atomic write
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=str(save_path.parent),
            prefix="config_",
            suffix=".tmp",
        ) as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
            tmp_path = Path(f.name)
        
        tmp_path.replace(save_path)
        logger.info(f"Configuration saved to {save_path}")
    
    def get(self) -> AppConfig:
        """Get current configuration."""
        if self._config is None:
            self._config = self.load()
        return self._config


# Global manager
_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """Get the global config manager."""
    global _manager
    if _manager is None:
        _manager = ConfigManager()
    return _manager


def get_config(
    cli_args: Optional[dict[str, Any]] = None,
    config_path: Optional[Path] = None,
) -> AppConfig:
    """Get or load configuration."""
    return get_config_manager().load(cli_args, config_path)


__all__ = [
    "ModelConfig",
    "AppConfig",
    "ConfigManager",
    "get_config_manager",
    "get_config",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DEFAULT_AGENT_TOKENS",
    "DEFAULT_CTX",
    "DEFAULT_TIMEOUT",
]
