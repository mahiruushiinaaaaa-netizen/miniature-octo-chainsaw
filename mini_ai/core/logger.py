"""
logger.py – Structured logging with observability.

Replaces ad-hoc print() statements with:
- Structured JSON logging for machine parsing
- Human-readable console output
- Log level control
- Context propagation
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from pathlib import Path
from typing import Any, Optional, Callable
from contextvars import ContextVar
import threading


class LogLevel(IntEnum):
    """Log levels matching standard logging."""
    DEBUG = 10
    INFO = 20
    WARN = 30
    ERROR = 40
    CRITICAL = 50


@dataclass
class LogEntry:
    """A structured log entry."""
    timestamp: float
    level: str
    message: str
    module: str
    operation: str
    duration_ms: Optional[float] = None
    context: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


# Context for tracking operations across async boundaries
_log_context: ContextVar[dict[str, Any]] = ContextVar("log_context", default={})


class StructuredLogger:
    """Production-grade structured logger."""
    
    def __init__(
        self,
        name: str,
        level: LogLevel = LogLevel.INFO,
        json_output: bool = False,
        file_path: Optional[Path] = None,
    ):
        self.name = name
        self.level = level
        self.json_output = json_output
        self.file_path = file_path
        self._lock = threading.Lock()
        self._file_handle: Optional[Any] = None
        
        if file_path:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_handle = open(file_path, "a", encoding="utf-8")
    
    def _should_log(self, level: LogLevel) -> bool:
        return level >= self.level
    
    def _emit(self, entry: LogEntry) -> None:
        """Emit log entry to all outputs."""
        with self._lock:
            # Console output (human-readable)
            if not self.json_output:
                self._console_output(entry)
            else:
                self._json_output(entry)
            
            # File output
            if self._file_handle:
                self._file_handle.write(json.dumps(asdict(entry)) + "\n")
                self._file_handle.flush()
    
    def _console_output(self, entry: LogEntry) -> None:
        """Human-readable console output with colors."""
        level_colors = {
            "DEBUG": "\033[90m",     # gray
            "INFO": "\033[32m",      # green
            "WARN": "\033[33m",      # yellow
            "ERROR": "\033[31m",     # red
            "CRITICAL": "\033[35m",  # magenta
        }
        reset = "\033[0m"
        
        # Check if ANSI is supported
        # Windows: colors work in Windows Terminal (WT_SESSION), modern conhost, or with ANSICON
        # Unix: colors work in any TTY
        is_windows = sys.platform.startswith("win")
        is_tty = sys.stderr.isatty()
        has_windows_color = is_windows and (
            "WT_SESSION" in os.environ or  # Windows Terminal
            "ANSICON" in os.environ or      # ANSICON installed
            "TERM_PROGRAM" in os.environ or  # VS Code, JetBrains, etc
            os.environ.get("TERM") == "xterm-256color"
        )
        use_color = is_tty and (not is_windows or has_windows_color)
        
        if use_color:
            color = level_colors.get(entry.level, "")
            level_str = f"{color}{entry.level:8}{reset}"
        else:
            level_str = f"{entry.level:8}"
        
        ts = time.strftime("%H:%M:%S", time.localtime(entry.timestamp))
        
        # Build message
        parts = [f"[{ts}] {level_str} [{entry.module}] {entry.message}"]
        
        if entry.operation:
            parts.append(f"  op: {entry.operation}")
        
        if entry.duration_ms is not None:
            parts.append(f"  duration: {entry.duration_ms:.1f}ms")
        
        if entry.context:
            for k, v in entry.context.items():
                parts.append(f"  {k}: {v}")
        
        if entry.error:
            parts.append(f"  error: {entry.error}")
        
        output = sys.stdout if entry.level in ("DEBUG", "INFO") else sys.stderr
        try:
            print("\n".join(parts), file=output, flush=True)
        except UnicodeEncodeError:
            # Fallback for legacy Windows consoles (cp1252 etc)
            # Encode with 'replace' and decode back to strip/replace problematic chars
            encoding = getattr(output, 'encoding', 'utf-8') or 'utf-8'
            safe_parts = [p.encode(encoding, errors="replace").decode(encoding) for p in parts]
            print("\n".join(safe_parts), file=output, flush=True)
    
    def _json_output(self, entry: LogEntry) -> None:
        """JSON output for machine parsing."""
        print(json.dumps(asdict(entry)), flush=True)
    
    def _log(
        self,
        level: LogLevel,
        message: str,
        operation: str = "",
        context: Optional[dict[str, Any]] = None,
        duration_ms: Optional[float] = None,
        error: Optional[Exception] = None,
    ) -> None:
        if not self._should_log(level):
            return
        
        # Merge with context vars
        ctx = dict(_log_context.get())
        ctx.update(context or {})
        
        entry = LogEntry(
            timestamp=time.time(),
            level=level.name,
            message=message,
            module=self.name,
            operation=operation,
            duration_ms=duration_ms,
            context=ctx,
            error=str(error) if error else None,
        )
        
        self._emit(entry)
    
    # Public API
    def debug(self, message: str, **kwargs) -> None:
        self._log(LogLevel.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs) -> None:
        self._log(LogLevel.INFO, message, **kwargs)
    
    def warn(self, message: str, **kwargs) -> None:
        self._log(LogLevel.WARN, message, **kwargs)
    
    def error(self, message: str, **kwargs) -> None:
        self._log(LogLevel.ERROR, message, **kwargs)
    
    def critical(self, message: str, **kwargs) -> None:
        self._log(LogLevel.CRITICAL, message, **kwargs)
    
    def operation(self, name: str) -> "OperationContext":
        """Context manager for timing operations."""
        return OperationContext(self, name)
    
    def close(self) -> None:
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None


class OperationContext:
    """Context manager for operation timing and context."""
    
    def __init__(self, logger: StructuredLogger, operation: str):
        self.logger = logger
        self.operation = operation
        self.start_time: Optional[float] = None
        self.success: Optional[bool] = None
    
    def __enter__(self) -> "OperationContext":
        self.start_time = time.perf_counter()
        self.logger.debug(f"Starting: {self.operation}", operation=self.operation)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        duration = (time.perf_counter() - self.start_time) * 1000 if self.start_time else None
        
        if exc_val:
            self.success = False
            self.logger.error(
                f"Failed: {self.operation}",
                operation=self.operation,
                duration_ms=duration,
                error=exc_val,
            )
        else:
            self.success = True
            self.logger.info(
                f"Completed: {self.operation}",
                operation=self.operation,
                duration_ms=duration,
            )
    
    def add_context(self, **kwargs) -> None:
        """Add context to the current operation."""
        ctx = _log_context.get()
        ctx.update(kwargs)
        _log_context.set(ctx)


# Global logger registry
_loggers: dict[str, StructuredLogger] = {}
_registry_lock = threading.Lock()


def get_logger(
    name: str,
    level: Optional[LogLevel] = None,
    json_output: bool = False,
    file_path: Optional[Path] = None,
) -> StructuredLogger:
    """Get or create a logger instance."""
    with _registry_lock:
        if name not in _loggers:
            effective_level = level or LogLevel.INFO
            _loggers[name] = StructuredLogger(
                name=name,
                level=effective_level,
                json_output=json_output,
                file_path=file_path,
            )
        return _loggers[name]


def configure_logging(
    level: LogLevel = LogLevel.INFO,
    json_output: bool = False,
    log_dir: Optional[Path] = None,
) -> None:
    """Configure global logging defaults."""
    global _default_level, _default_json, _default_log_dir
    _default_level = level
    _default_json = json_output
    _default_log_dir = log_dir


def close_all_loggers() -> None:
    """Close all logger file handles."""
    with _registry_lock:
        for logger in _loggers.values():
            logger.close()
        _loggers.clear()
