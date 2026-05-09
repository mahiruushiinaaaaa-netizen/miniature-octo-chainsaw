"""
config.py – Application configuration with environment-aware defaults.

This module re-exports from the new core configuration system.
Maintains backward compatibility with existing code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config_manager import ModelConfig as _ModelConfig, AppConfig as _AppConfig

# Re-export from core for backward compatibility
from .config_manager import (
    ModelConfig,
    AppConfig,
    ConfigManager,
    get_config_manager,
    get_config,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_AGENT_TOKENS,
    DEFAULT_CTX,
    DEFAULT_TIMEOUT,
)
from .environment import get_environment, OSType
from .logger import get_logger

logger = get_logger("config")


# Legacy compatibility - Config class with flat structure expected by backend.py
@dataclass
class Config:
    """Legacy Config class for backward compatibility with backend.py and other modules."""
    model: Path | None = None
    models_dir: Path = field(default_factory=lambda: Path.home() / ".lmstudio" / "models")
    cli_bin: Path | None = None
    server_bin: Path | None = None
    threads: int = 4
    ctx: int = 8192
    temp: float = 0.0
    seed: int | None = None
    timeout: int = 120
    host: str = "127.0.0.1"
    port: int = 8080
    use_server: bool = True
    allow_run: bool = False
    workspace: Path = field(default_factory=lambda: Path.cwd())
    agent_tokens: int = 4096
    role: str = "agent"
    dual_model: bool = False
    tri_model: bool = False
    compact_ui: bool = False
    verbose: bool = False
    max_steps: int = 30
    ui_config: Config | None = None  # For dual-model mode
    analyzer_config: Config | None = None # For tri-model
    coder_config: Config | None = None # For tri-model
    sandbox_type: str = "local" # options: "local", "venv", "docker"
    
    def __post_init__(self):
        """Resolve paths after initialization."""
        if self.model:
            self.model = Path(self.model).expanduser().resolve()
        self.models_dir = Path(self.models_dir).expanduser().resolve()
        self.workspace = Path(self.workspace).expanduser().resolve()
        if self.cli_bin:
            self.cli_bin = Path(self.cli_bin).expanduser().resolve()
        if self.server_bin:
            self.server_bin = Path(self.server_bin).expanduser().resolve()
    
    @property
    def base_url(self) -> str:
        """Get base URL for the server."""
        return f"http://{self.host}:{self.port}"

    @classmethod
    def from_app_config(cls, app: AppConfig, model: ModelConfig, *, role: str) -> "Config":
        return cls(
            model=model.model_path,
            models_dir=app.models_dir,
            cli_bin=app.llama_cli_bin or app.llama_server_bin,
            server_bin=app.llama_server_bin,
            threads=model.threads,
            ctx=model.ctx,
            temp=model.temp,
            seed=model.seed,
            timeout=model.timeout,
            host=model.host,
            port=model.port,
            use_server=app.use_server,
            allow_run=app.allow_run,
            workspace=app.workspace,
            agent_tokens=model.agent_tokens,
            role=role,
            dual_model=app.dual_model,
            compact_ui=app.compact_ui,
            verbose=app.verbose,
            max_steps=app.max_steps,
        )

# Deprecated: These are now auto-detected via environment detector
# Kept for backward compatibility
DEFAULT_MODELS_DIR = Path.home() / ".lmstudio" / "models"

# Legacy candidates lists (now dynamically discovered)
LMSTUDIO_CLI_CANDIDATES: list[Path] = []
LLAMA_SERVER_CANDIDATES: list[Path] = []

# Compute defaults dynamically based on environment
def _compute_defaults() -> tuple[int, int, int]:
    """
    Compute default settings based on runtime environment.
    Optimized for low-end devices like Intel Core i5-5300U (2C/4T, mobile).
    """
    env = get_environment()
    cpu_count = env.cpu_count
    ram_mb = env.ram_mb or 4096
    
    # Improved low-end detection: considers CPU count, RAM, and CPU type
    is_low_core = cpu_count <= 2
    is_low_ram = ram_mb < 4096
    
    # Check for mobile/low-power CPU indicators
    is_mobile_cpu = False
    try:
        import cpuinfo
        cpu_name = cpuinfo.get_cpu_info().get("brand_raw", "").lower()
        is_mobile_cpu = any(x in cpu_name for x in [
            "mobile", "u-series", "u series", "atom", "celeron",
            "pentium silver", "core m", "m3-", "m5-", "m7-",
        ])
    except ImportError:
        pass
    
    # Conservative: low-end if 2 of 3 conditions met
    is_low_end = sum([is_low_core, is_low_ram, is_mobile_cpu]) >= 2
    
    if is_low_end:
        threads = min(4, max(1, cpu_count - 1))
        ctx = 4096 if ram_mb > 4000 else 2048
        agent_tokens = 1024
        logger.info(
            f"Low-end device detected: threads={threads}, ctx={ctx}, "
            f"tokens={agent_tokens}, cpu_count={cpu_count}, ram={ram_mb}MB"
        )
    else:
        threads = max(1, min(cpu_count, 8))
        ctx = 8192
        agent_tokens = 2048
    
    return threads, ctx, agent_tokens


# Trigger computation on module load
_DEFAULT_THREADS, _DEFAULT_CTX, _DEFAULT_AGENT_TOKENS = _compute_defaults()

logger.debug(
    f"Configuration defaults computed: threads={_DEFAULT_THREADS}, "
    f"ctx={_DEFAULT_CTX}, tokens={_DEFAULT_AGENT_TOKENS}"
)


# Legacy compatibility re-exports
__all__ = [
    "Config",
    "AppConfig",
    "ModelConfig",
    "ConfigManager",
    "get_config_manager",
    "get_config",
    "DEFAULT_MODELS_DIR",
    "LMSTUDIO_CLI_CANDIDATES",
    "LLAMA_SERVER_CANDIDATES",
    "_DEFAULT_THREADS",
    "_DEFAULT_CTX",
    "_DEFAULT_AGENT_TOKENS",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DEFAULT_AGENT_TOKENS",
    "DEFAULT_CTX",
    "DEFAULT_TIMEOUT",
]
