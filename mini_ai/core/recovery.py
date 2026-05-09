"""
recovery.py – Self-correction and error recovery system.

Implements:
- Automatic retry with backoff
- Recovery strategies per error category
- Fallback mechanisms
- State preservation and rollback
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import wraps
from typing import Any, Callable, Optional, TypeVar, Union
from contextlib import contextmanager

from .logger import get_logger
from .errors import (
    MiniAIError,
    ErrorContext,
    RecoveryFailedError,
    NetworkError,
    ResourceNotFoundError,
    ExecutionError,
    classify_error,
)

logger = get_logger("recovery")

T = TypeVar("T")


class RecoveryStrategy(Enum):
    """Strategies for error recovery."""
    IMMEDIATE_RETRY = auto()  # Retry immediately
    EXPONENTIAL_BACKOFF = auto()  # Retry with increasing delay
    FALLBACK = auto()  # Use alternative approach
    SKIP = auto()  # Skip and continue
    ABORT = auto()  # Stop execution


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,)
    on_retry: Optional[Callable[[int, Exception], None]] = None


@dataclass
class RecoveryResult:
    """Result of a recovery attempt."""
    success: bool
    result: Any = None
    attempts: int = 0
    total_duration: float = 0.0
    strategy_used: RecoveryStrategy = RecoveryStrategy.ABORT
    error: Optional[str] = None


class RecoveryManager:
    """Manages error recovery and self-correction."""
    
    # Default strategies per error category
    DEFAULT_STRATEGIES: dict[str, RecoveryStrategy] = {
        "network": RecoveryStrategy.EXPONENTIAL_BACKOFF,
        "timeout": RecoveryStrategy.EXPONENTIAL_BACKOFF,
        "resource_not_found": RecoveryStrategy.FALLBACK,
        "execution": RecoveryStrategy.IMMEDIATE_RETRY,
        "tool_execution": RecoveryStrategy.IMMEDIATE_RETRY,
        "model": RecoveryStrategy.FALLBACK,
        "parse": RecoveryStrategy.IMMEDIATE_RETRY,
        "validation": RecoveryStrategy.ABORT,
        "permission": RecoveryStrategy.ABORT,
        "unknown": RecoveryStrategy.ABORT,
    }
    
    def __init__(self):
        self._strategies: dict[str, RecoveryStrategy] = dict(self.DEFAULT_STRATEGIES)
        self._fallbacks: dict[str, Callable[[], Any]] = {}
        self._attempt_history: list[dict[str, Any]] = []
    
    def set_strategy(self, category: str, strategy: RecoveryStrategy) -> None:
        """Set recovery strategy for an error category."""
        self._strategies[category] = strategy
    
    def register_fallback(
        self,
        category: str,
        fallback_func: Callable[[], Any],
    ) -> None:
        """Register a fallback function for a category."""
        self._fallbacks[category] = fallback_func
    
    def attempt_recovery(
        self,
        error: Exception,
        operation: str,
        context: Optional[dict[str, Any]] = None,
        retry: Optional[Callable[[], Any]] = None,
        max_attempts: int = 3,
    ) -> RecoveryResult:
        """
        Attempt to recover from an error.
        
        Args:
            error: The exception that occurred
            operation: Description of the operation that failed
            context: Additional context for recovery
        
        Returns:
            RecoveryResult with outcome details
        """
        category, recoverable, suggestion = classify_error(error)
        strategy = self._strategies.get(category, RecoveryStrategy.ABORT)
        
        logger.warn(
            f"Attempting recovery for {category} error in {operation}",
            operation="recovery",
            context={"category": category, "strategy": strategy.name, "recoverable": recoverable},
        )
        
        if not recoverable or strategy == RecoveryStrategy.ABORT:
            return RecoveryResult(
                success=False,
                attempts=0,
                strategy_used=strategy,
                error=f"Not recoverable: {error}",
            )
        
        start_time = time.perf_counter()
        
        try:
            if strategy == RecoveryStrategy.FALLBACK:
                return self._try_fallback(category, operation, start_time)
            
            elif strategy == RecoveryStrategy.SKIP:
                return RecoveryResult(
                    success=True,
                    result=None,
                    attempts=0,
                    total_duration=time.perf_counter() - start_time,
                    strategy_used=strategy,
                )
            
            else:  # Retry strategies
                return self._try_retry(
                    error,
                    operation,
                    strategy,
                    start_time,
                    context,
                    retry,
                    max_attempts,
                )
        
        except Exception as e:
            return RecoveryResult(
                success=False,
                attempts=1,
                total_duration=time.perf_counter() - start_time,
                strategy_used=strategy,
                error=f"Recovery failed: {e}",
            )
    
    def _try_fallback(
        self,
        category: str,
        operation: str,
        start_time: float,
    ) -> RecoveryResult:
        """Try fallback recovery."""
        fallback = self._fallbacks.get(category)
        
        if not fallback:
            # Try general fallback
            fallback = self._fallbacks.get("general")
        
        if fallback:
            try:
                result = fallback()
                return RecoveryResult(
                    success=True,
                    result=result,
                    attempts=1,
                    total_duration=time.perf_counter() - start_time,
                    strategy_used=RecoveryStrategy.FALLBACK,
                )
            except Exception as e:
                return RecoveryResult(
                    success=False,
                    attempts=1,
                    total_duration=time.perf_counter() - start_time,
                    strategy_used=RecoveryStrategy.FALLBACK,
                    error=f"Fallback failed: {e}",
                )
        
        return RecoveryResult(
            success=False,
            attempts=0,
            total_duration=time.perf_counter() - start_time,
            strategy_used=RecoveryStrategy.FALLBACK,
            error="No fallback registered",
        )
    
    def _try_retry(
        self,
        error: Exception,
        operation: str,
        strategy: RecoveryStrategy,
        start_time: float,
        context: Optional[dict[str, Any]],
        retry: Optional[Callable[[], Any]],
        max_attempts: int,
    ) -> RecoveryResult:
        """Try retry recovery with appropriate backoff."""
        if retry is None:
            return RecoveryResult(
                success=False,
                attempts=0,
                total_duration=time.perf_counter() - start_time,
                strategy_used=strategy,
                error=f"Retry requested for {operation} but no retry callable was provided",
            )

        attempts = 0
        last_error: Exception = error
        for attempt in range(1, max(1, max_attempts) + 1):
            attempts = attempt
            try:
                result = retry()
                return RecoveryResult(
                    success=True,
                    result=result,
                    attempts=attempts,
                    total_duration=time.perf_counter() - start_time,
                    strategy_used=strategy,
                )
            except Exception as exc:
                last_error = exc
                if attempt >= max_attempts:
                    break
                if strategy == RecoveryStrategy.EXPONENTIAL_BACKOFF:
                    delay = min(30.0, 1.0 * (2.0 ** (attempt - 1)))
                    time.sleep(delay)

        return RecoveryResult(
            success=False,
            attempts=attempts,
            total_duration=time.perf_counter() - start_time,
            strategy_used=strategy,
            error=f"Retry failed for {operation}: {last_error}",
        )
    
    def record_attempt(self, operation: str, success: bool, details: dict[str, Any]) -> None:
        """Record a recovery attempt for learning."""
        self._attempt_history.append({
            "timestamp": time.time(),
            "operation": operation,
            "success": success,
            **details,
        })
        
        # Keep only last 100 attempts
        self._attempt_history = self._attempt_history[-100:]


def with_retry(
    config: Optional[RetryConfig] = None,
    fallback: Optional[Callable[[], T]] = None,
) -> Callable:
    """
    Decorator for automatic retry with recovery.
    
    Args:
        config: Retry configuration
        fallback: Optional fallback function if all retries fail
    
    Returns:
        Decorated function
    """
    cfg = config or RetryConfig()
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_error: Optional[Exception] = None
            
            for attempt in range(1, cfg.max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                
                except cfg.retryable_exceptions as e:
                    last_error = e
                    
                    if attempt < cfg.max_attempts:
                        # Calculate delay
                        if cfg.exponential_base > 0:
                            delay = min(
                                cfg.base_delay * (cfg.exponential_base ** (attempt - 1)),
                                cfg.max_delay,
                            )
                        else:
                            delay = cfg.base_delay
                        
                        logger.warn(
                            f"Attempt {attempt}/{cfg.max_attempts} failed: {e}. Retrying in {delay:.1f}s...",
                            operation=func.__name__,
                            context={"attempt": attempt, "delay": delay},
                        )
                        
                        if cfg.on_retry:
                            cfg.on_retry(attempt, e)
                        
                        time.sleep(delay)
                    
                    else:
                        logger.error(
                            f"All {cfg.max_attempts} attempts failed",
                            operation=func.__name__,
                            error=e,
                        )
            
            # All retries exhausted
            if fallback:
                logger.info("Using fallback", operation=func.__name__)
                return fallback()
            
            # Re-raise the last error
            if last_error:
                raise last_error
            
            # Should never reach here
            raise RuntimeError("Unexpected end of retry loop")
        
        return wrapper
    return decorator


@contextmanager
def recovery_context(
    operation: str,
    manager: Optional[RecoveryManager] = None,
    on_failure: Optional[Callable[[Exception], None]] = None,
):
    """
    Context manager for operations that may need recovery.
    
    Usage:
        with recovery_context("file_read") as rc:
            data = read_file()
    """
    mgr = manager or RecoveryManager()
    start_time = time.perf_counter()
    
    try:
        yield mgr
        mgr.record_attempt(operation, True, {"duration": time.perf_counter() - start_time})
    
    except Exception as e:
        duration = time.perf_counter() - start_time
        
        # Attempt recovery
        result = mgr.attempt_recovery(e, operation)
        
        mgr.record_attempt(operation, result.success, {
            "duration": duration,
            "recovery_attempts": result.attempts,
            "strategy": result.strategy_used.name,
        })
        
        if not result.success:
            if on_failure:
                on_failure(e)
            
            raise RecoveryFailedError(
                f"Recovery failed for {operation}",
                original_error=e if isinstance(e, MiniAIError) else None,
                recovery_attempts=result.attempts,
                context=ErrorContext(
                    operation=operation,
                    recoverable=False,
                    suggested_action="Manual intervention required",
                ),
            ) from e


# Convenience function for simple retries
def retry_operation(
    operation: Callable[[], T],
    max_attempts: int = 3,
    delay: float = 1.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> T:
    """Simple retry wrapper for an operation."""
    last_error: Optional[Exception] = None
    
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except exceptions as e:
            last_error = e
            if attempt < max_attempts:
                logger.warn(f"Attempt {attempt} failed, retrying in {delay}s...")
                time.sleep(delay)
    
    if last_error:
        raise last_error
    raise RuntimeError("Unexpected end of retry")


__all__ = [
    "RecoveryStrategy",
    "RetryConfig",
    "RecoveryResult",
    "RecoveryManager",
    "with_retry",
    "recovery_context",
    "retry_operation",
]
