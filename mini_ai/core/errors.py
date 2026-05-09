"""
errors.py – Hierarchical error system with recovery context.

Design principles:
- Every error has a clear category and recovery hint
- Errors carry context for automated recovery
- Error hierarchy maps to recovery strategies
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ErrorContext:
    """Context for error recovery and debugging."""
    operation: str = ""
    resource: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    recoverable: bool = False
    suggested_action: str = ""


class MiniAIError(Exception):
    """Base exception for all mini_ai errors."""
    
    def __init__(
        self,
        message: str,
        context: Optional[ErrorContext] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.context = context or ErrorContext()
        self.cause = cause
        self.category = self._get_category()
    
    def _get_category(self) -> str:
        return "general"
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.__class__.__name__,
            "category": self.category,
            "message": self.message,
            "operation": self.context.operation,
            "resource": self.context.resource,
            "recoverable": self.context.recoverable,
            "suggested_action": self.context.suggested_action,
            "cause": str(self.cause) if self.cause else None,
        }
    
    def __str__(self) -> str:
        parts = [f"[{self.category}] {self.message}"]
        if self.context.operation:
            parts.append(f"  Operation: {self.context.operation}")
        if self.context.resource:
            parts.append(f"  Resource: {self.context.resource}")
        if self.context.suggested_action:
            parts.append(f"  Suggestion: {self.context.suggested_action}")
        return "\n".join(parts)


class ConfigurationError(MiniAIError):
    """Configuration-related errors."""
    
    def _get_category(self) -> str:
        return "configuration"


class ValidationError(MiniAIError):
    """Input validation errors."""
    
    def _get_category(self) -> str:
        return "validation"


class ResourceNotFoundError(MiniAIError):
    """Missing files, models, or binaries."""
    
    def _get_category(self) -> str:
        return "resource_not_found"


class ExecutionError(MiniAIError):
    """Tool or command execution failures."""
    
    def __init__(
        self,
        message: str,
        exit_code: Optional[int] = None,
        stdout: str = "",
        stderr: str = "",
        context: Optional[ErrorContext] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(message, context, cause)
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
    
    def _get_category(self) -> str:
        return "execution"
    
    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "exit_code": self.exit_code,
            "stdout": self.stdout[:500] if self.stdout else None,
            "stderr": self.stderr[:500] if self.stderr else None,
        })
        return base


class ToolExecutionError(ExecutionError):
    """Specific tool execution failures with retry guidance."""
    
    def __init__(
        self,
        message: str,
        tool_name: str = "",
        retryable: bool = False,
        max_retries: int = 3,
        **kwargs,
    ):
        super().__init__(message, **kwargs)
        self.tool_name = tool_name
        self.retryable = retryable
        self.max_retries = max_retries
    
    def _get_category(self) -> str:
        return "tool_execution"


class RecoveryFailedError(MiniAIError):
    """Error recovery itself failed."""
    
    def __init__(
        self,
        message: str,
        original_error: Optional[MiniAIError] = None,
        recovery_attempts: int = 0,
        **kwargs,
    ):
        super().__init__(message, **kwargs)
        self.original_error = original_error
        self.recovery_attempts = recovery_attempts
    
    def _get_category(self) -> str:
        return "recovery_failed"


class NetworkError(MiniAIError):
    """Network-related failures."""
    
    def __init__(
        self,
        message: str,
        url: str = "",
        status_code: Optional[int] = None,
        **kwargs,
    ):
        super().__init__(message, **kwargs)
        self.url = url
        self.status_code = status_code
    
    def _get_category(self) -> str:
        return "network"


class ModelError(MiniAIError):
    """LLM/model-related errors."""
    
    def __init__(
        self,
        message: str,
        model_name: str = "",
        **kwargs,
    ):
        super().__init__(message, **kwargs)
        self.model_name = model_name
    
    def _get_category(self) -> str:
        return "model"


def classify_error(exc: Exception) -> tuple[str, bool, str]:
    """
    Classify an exception and suggest recovery action.
    
    Returns:
        (category, is_recoverable, suggested_action)
    """
    if isinstance(exc, MiniAIError):
        return (
            exc.category,
            exc.context.recoverable,
            exc.context.suggested_action,
        )
    
    # Classify standard exceptions
    error_map = {
        "FileNotFoundError": ("resource_not_found", True, "Check path and try again"),
        "PermissionError": ("permission", False, "Check file permissions"),
        "TimeoutError": ("timeout", True, "Retry with longer timeout"),
        "ConnectionError": ("network", True, "Check network and retry"),
        "OSError": ("os", True, "Check system resources"),
        "ValueError": ("validation", True, "Check input format"),
        "KeyError": ("validation", True, "Check dictionary keys"),
        "IndexError": ("validation", True, "Check list bounds"),
        "JSONDecodeError": ("parse", True, "Check JSON format"),
    }
    
    exc_type = type(exc).__name__
    return error_map.get(exc_type, ("unknown", False, "Manual intervention required"))
