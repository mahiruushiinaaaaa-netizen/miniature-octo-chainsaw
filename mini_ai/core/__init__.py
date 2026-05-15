"""
core package – Production-grade infrastructure for mini_ai.

Provides:
- Environment-aware configuration management
- Structured logging and observability
- Hierarchical error handling
- Self-correction and recovery mechanisms
- Health checks and validation
"""
from __future__ import annotations

from .backend import generate, start_server, server_ready
from .config import Config, AppConfig, ModelConfig
from .config_manager import ConfigManager, get_config
from .memory import SessionMemory, PersistentMemory
from .path_manager import PathManager
from .schemas import get_schema, TOOL_SCHEMAS
from .workspace import detect_environment, EnvironmentContext
from .environment import EnvironmentDetector, get_environment, RuntimeEnvironment, OSType
from .errors import (
    MiniAIError,
    ConfigurationError,
    ValidationError,
    ExecutionError,
    ResourceNotFoundError,
    ToolExecutionError,
    RecoveryFailedError,
    NetworkError,
    ModelError,
    ErrorContext,
)
from .logger import get_logger, LogLevel, StructuredLogger
from .validators import DependencyValidator, HealthChecker, OPTIONAL_DEPS
from .recovery import RecoveryManager, RecoveryStrategy
from .metrics import (
    MetricsCollector,
    OperationMetrics,
    MetricType,
    OperationTimer,
    get_metrics_collector,
    record_metric,
)
from .micro_prompts import (
    MicroPromptTemplate,
    MicroPromptRegistry,
    PromptAssembler,
    StepMemory,
    select_grammar_for_intent,
)
from .grammars import MINIMAL_JSON_GRAMMAR
from .prompt_rewriter import PromptRewriter
from .server_manager import ServerManager, get_server_manager

__all__ = [
    # Configuration
    "ConfigManager",
    "get_config",
    "Config",
    "AppConfig",
    "ModelConfig",
    # Backend
    "generate",
    "start_server",
    "server_ready",
    # Memory
    "SessionMemory",
    "PersistentMemory",
    # Path Management
    "PathManager",
    # Schemas
    "get_schema",
    "TOOL_SCHEMAS",
    # Workspace
    "detect_environment",
    "EnvironmentContext",
    # Errors
    "MiniAIError",
    "ConfigurationError",
    "ValidationError",
    "ExecutionError",
    "ResourceNotFoundError",
    "ToolExecutionError",
    "RecoveryFailedError",
    "NetworkError",
    "ModelError",
    "ErrorContext",
    # Logging
    "get_logger",
    "LogLevel",
    "StructuredLogger",
    # Environment
    "EnvironmentDetector",
    "RuntimeEnvironment",
    "get_environment",
    "OSType",
    # Validation
    "DependencyValidator",
    "HealthChecker",
    "OPTIONAL_DEPS",
    # Recovery
    "RecoveryManager",
    "RecoveryStrategy",
    # Metrics
    "MetricsCollector",
    "OperationMetrics",
    "MetricType",
    "OperationTimer",
    "get_metrics_collector",
    "record_metric",
    # Micro Prompts
    "MicroPromptTemplate",
    "MicroPromptRegistry",
    "PromptAssembler",
    "StepMemory",
    "select_grammar_for_intent",
    # Grammars
    "MINIMAL_JSON_GRAMMAR",
    # Prompt Rewriter
    "PromptRewriter",
    # Server Manager
    "ServerManager",
    "get_server_manager",
]
