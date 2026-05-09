"""
metrics.py – Metrics collection and observability for mini_ai.

Provides:
- Operation timing and counters
- Performance metrics
- Usage analytics
- Export capabilities (JSON, Prometheus format)
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from pathlib import Path
from typing import Any, Optional
from contextvars import ContextVar
import threading

from .logger import get_logger

logger = get_logger("metrics")


class MetricType(Enum):
    """Types of metrics."""
    COUNTER = auto()
    GAUGE = auto()
    HISTOGRAM = auto()
    TIMER = auto()


@dataclass
class MetricValue:
    """A single metric value with metadata."""
    name: str
    value: float
    metric_type: MetricType
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    unit: str = ""


@dataclass
class OperationMetrics:
    """Metrics for a specific operation type."""
    count: int = 0
    total_duration_ms: float = 0.0
    errors: int = 0
    min_duration_ms: float = float("inf")
    max_duration_ms: float = 0.0
    
    def record(self, duration_ms: float, success: bool = True) -> None:
        """Record an operation execution."""
        self.count += 1
        self.total_duration_ms += duration_ms
        self.min_duration_ms = min(self.min_duration_ms, duration_ms)
        self.max_duration_ms = max(self.max_duration_ms, duration_ms)
        if not success:
            self.errors += 1
    
    @property
    def avg_duration_ms(self) -> float:
        """Calculate average duration."""
        return self.total_duration_ms / self.count if self.count > 0 else 0.0
    
    @property
    def error_rate(self) -> float:
        """Calculate error rate."""
        return self.errors / self.count if self.count > 0 else 0.0
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "count": self.count,
            "total_duration_ms": self.total_duration_ms,
            "avg_duration_ms": self.avg_duration_ms,
            "min_duration_ms": self.min_duration_ms if self.min_duration_ms != float("inf") else 0,
            "max_duration_ms": self.max_duration_ms,
            "errors": self.errors,
            "error_rate": self.error_rate,
        }


class MetricsCollector:
    """Collects and manages application metrics."""
    
    def __init__(self):
        self._counters: dict[str, int] = defaultdict(int)
        self._gauges: dict[str, float] = {}
        self._operation_metrics: dict[str, OperationMetrics] = defaultdict(OperationMetrics)
        self._lock = threading.Lock()
        self._session_start = time.time()
    
    def increment(self, name: str, value: int = 1, labels: Optional[dict[str, str]] = None) -> None:
        """Increment a counter metric."""
        with self._lock:
            key = self._make_key(name, labels)
            self._counters[key] += value
    
    def gauge(self, name: str, value: float, labels: Optional[dict[str, str]] = None) -> None:
        """Set a gauge metric."""
        with self._lock:
            key = self._make_key(name, labels)
            self._gauges[key] = value
    
    def record_operation(
        self,
        operation: str,
        duration_ms: float,
        success: bool = True,
        labels: Optional[dict[str, str]] = None,
    ) -> None:
        """Record operation execution metrics."""
        with self._lock:
            key = self._make_key(operation, labels)
            self._operation_metrics[key].record(duration_ms, success)
            
            # Also increment total operations counter
            self._counters["total_operations"] += 1
            if not success:
                self._counters["total_errors"] += 1
    
    def time_operation(self, operation: str, labels: Optional[dict[str, str]] = None):
        """Context manager for timing operations."""
        return OperationTimer(self, operation, labels)
    
    def get_counter(self, name: str, labels: Optional[dict[str, str]] = None) -> int:
        """Get current counter value."""
        with self._lock:
            key = self._make_key(name, labels)
            return self._counters[key]
    
    def get_gauge(self, name: str, labels: Optional[dict[str, str]] = None) -> Optional[float]:
        """Get current gauge value."""
        with self._lock:
            key = self._make_key(name, labels)
            return self._gauges.get(key)
    
    def get_operation_metrics(self, operation: str) -> Optional[OperationMetrics]:
        """Get metrics for a specific operation."""
        with self._lock:
            return self._operation_metrics.get(operation)
    
    def get_all_metrics(self) -> dict[str, Any]:
        """Get all metrics as a dictionary."""
        with self._lock:
            return {
                "session_duration_seconds": time.time() - self._session_start,
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "operations": {
                    name: metrics.to_dict()
                    for name, metrics in self._operation_metrics.items()
                },
            }
    
    def export_json(self, path: Path) -> None:
        """Export metrics to JSON file."""
        data = self.get_all_metrics()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        logger.debug(f"Metrics exported to {path}")
    
    def export_prometheus(self) -> str:
        """Export metrics in Prometheus text format."""
        lines = []
        
        with self._lock:
            # Counters
            for key, value in self._counters.items():
                name, labels = self._parse_key(key)
                lines.append(f"# TYPE {name} counter")
                label_str = self._format_labels(labels)
                lines.append(f"{name}{label_str} {value}")
            
            # Gauges
            for key, value in self._gauges.items():
                name, labels = self._parse_key(key)
                lines.append(f"# TYPE {name} gauge")
                label_str = self._format_labels(labels)
                lines.append(f"{name}{label_str} {value}")
            
            # Operation metrics as histograms
            for key, metrics in self._operation_metrics.items():
                name, labels = self._parse_key(key)
                lines.append(f"# TYPE {name}_duration_ms histogram")
                label_str = self._format_labels(labels)
                lines.append(f'{name}_count{label_str} {metrics.count}')
                lines.append(f'{name}_sum{label_str} {metrics.total_duration_ms}')
        
        return "\n".join(lines)
    
    def _make_key(self, name: str, labels: Optional[dict[str, str]]) -> str:
        """Create a key from name and labels."""
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"
    
    def _parse_key(self, key: str) -> tuple[str, dict[str, str]]:
        """Parse a key into name and labels."""
        if "{" not in key:
            return key, {}
        name, labels_str = key.split("{", 1)
        labels_str = labels_str.rstrip("}")
        labels = {}
        for part in labels_str.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                labels[k] = v
        return name, labels
    
    def _format_labels(self, labels: dict[str, str]) -> str:
        """Format labels for Prometheus output."""
        if not labels:
            return ""
        return "{" + ",".join(f'{k}="{v}"' for k, v in sorted(labels.items())) + "}"
    
    def reset(self) -> None:
        """Reset all metrics."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._operation_metrics.clear()
            self._session_start = time.time()


class OperationTimer:
    """Context manager for timing operations."""
    
    def __init__(
        self,
        collector: MetricsCollector,
        operation: str,
        labels: Optional[dict[str, str]] = None,
    ):
        self.collector = collector
        self.operation = operation
        self.labels = labels
        self.start_time: Optional[float] = None
        self.success = False
    
    def __enter__(self) -> OperationTimer:
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.start_time is None:
            return
        
        duration_ms = (time.perf_counter() - self.start_time) * 1000
        self.success = exc_type is None
        
        self.collector.record_operation(
            self.operation,
            duration_ms,
            self.success,
            self.labels,
        )
        
        # Log slow operations
        if duration_ms > 5000:  # 5 seconds
            logger.warn(
                f"Slow operation detected: {self.operation} took {duration_ms:.1f}ms",
                context={"operation": self.operation, "duration_ms": duration_ms},
            )


# Global metrics collector
_global_collector: Optional[MetricsCollector] = None
_lock = threading.Lock()


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector."""
    global _global_collector
    with _lock:
        if _global_collector is None:
            _global_collector = MetricsCollector()
        return _global_collector


def record_metric(
    metric_type: MetricType,
    name: str,
    value: float,
    labels: Optional[dict[str, str]] = None,
) -> None:
    """Record a metric to the global collector."""
    collector = get_metrics_collector()
    
    if metric_type == MetricType.COUNTER:
        collector.increment(name, int(value), labels)
    elif metric_type == MetricType.GAUGE:
        collector.gauge(name, value, labels)


__all__ = [
    "MetricsCollector",
    "OperationMetrics",
    "MetricType",
    "OperationTimer",
    "get_metrics_collector",
    "record_metric",
]
