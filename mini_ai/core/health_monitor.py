"""
health_monitor.py – Continuous system health reporting.

Monitors system resources and publishes periodic health status updates
to keep the AI informed about system state.
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Optional

from .logger import get_logger
from .message_protocol import MessageType, SystemMessage
from .message_queue import get_broker

logger = get_logger("health_monitor")


class HealthMonitor:
    """
    Continuous system health reporting.
    
    Monitors CPU, memory, process count, and uptime, publishing periodic
    status updates to the message broker so the AI stays informed.
    """
    
    def __init__(self, interval: int = 5):
        """
        Initialize health monitor.
        
        Args:
            interval: Update interval in seconds
        """
        self.interval = interval
        self._broker = get_broker()
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._start_time = time.time()
        self.metrics = {
            "cpu_percent": 0.0,
            "memory_mb": 0.0,
            "memory_percent": 0.0,
            "active_processes": 0,
            "uptime_seconds": 0.0,
        }
        
        logger.info(f"HealthMonitor initialized (interval={interval}s)")
    
    def start(self) -> None:
        """Start the health monitoring thread."""
        if not self._running:
            self._running = True
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                daemon=True,
                name="HealthMonitor"
            )
            self._monitor_thread.start()
            logger.info("HealthMonitor started")
    
    def stop(self) -> None:
        """Stop the health monitoring thread."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
            logger.info("HealthMonitor stopped")
    
    def _monitor_loop(self) -> None:
        """Background loop that publishes health status."""
        while self._running:
            try:
                self._update_metrics()
                self._publish_status()
                time.sleep(self.interval)
            except Exception as e:
                logger.error(f"Health monitor error: {e}", exc_info=True)
    
    def _update_metrics(self) -> None:
        """Update system metrics."""
        try:
            import psutil
            
            self.metrics = {
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "memory_mb": psutil.virtual_memory().used / 1024 / 1024,
                "memory_percent": psutil.virtual_memory().percent,
                "active_processes": len(psutil.pids()),
                "uptime_seconds": time.time() - self._start_time,
            }
        except ImportError:
            logger.debug("psutil not available, using fallback metrics")
            self.metrics["uptime_seconds"] = time.time() - self._start_time
        except Exception as e:
            logger.warning(f"Failed to update metrics: {e}")
    
    def _publish_status(self) -> None:
        """Publish health status to message broker."""
        # Determine health level
        health_level = self._determine_health_level()
        
        message = SystemMessage(
            msg_type=MessageType.STATUS,
            content=f"System health: {health_level}",
            metadata={
                "health_level": health_level,
                **self.metrics,
                "timestamp": time.time()
            },
            sender="health_monitor"
        )
        
        self._broker.publish(message)
        logger.debug(f"Published health status: {health_level}")
    
    def _determine_health_level(self) -> str:
        """
        Determine overall health level.
        
        Returns:
            "excellent", "good", "fair", or "poor"
        """
        cpu = self.metrics.get("cpu_percent", 0)
        mem = self.metrics.get("memory_percent", 0)
        
        if cpu > 80 or mem > 85:
            return "poor"
        elif cpu > 60 or mem > 75:
            return "fair"
        elif cpu > 40 or mem > 60:
            return "good"
        else:
            return "excellent"
    
    def get_metrics(self) -> dict[str, Any]:
        """
        Get current metrics.
        
        Returns:
            Dict with current system metrics
        """
        self._update_metrics()
        return self.metrics.copy()
    
    def get_health_report(self) -> str:
        """
        Get human-readable health report.
        
        Returns:
            Formatted health report
        """
        metrics = self.get_metrics()
        
        lines = [
            "System Health Report",
            "=" * 40,
            f"CPU Usage: {metrics['cpu_percent']:.1f}%",
            f"Memory: {metrics['memory_mb']:.0f}MB ({metrics['memory_percent']:.1f}%)",
            f"Active Processes: {metrics['active_processes']}",
            f"Uptime: {metrics['uptime_seconds']:.0f}s ({metrics['uptime_seconds']/3600:.1f}h)",
            f"Health Level: {self._determine_health_level().upper()}",
        ]
        
        return "\n".join(lines)
    
    def __repr__(self) -> str:
        health = self._determine_health_level()
        return (
            f"HealthMonitor(health={health}, "
            f"cpu={self.metrics.get('cpu_percent', 0):.1f}%, "
            f"mem={self.metrics.get('memory_percent', 0):.1f}%)"
        )


class HealthCheckRegistry:
    """
    Registry for custom health checks.
    
    Allows registration of custom health check functions that get
    executed as part of health monitoring.
    """
    
    def __init__(self):
        """Initialize registry."""
        self._checks: dict[str, callable] = {}
        self._results: dict[str, dict[str, Any]] = {}
        
        logger.info("HealthCheckRegistry initialized")
    
    def register(self, name: str, check_fn: callable) -> None:
        """
        Register a health check.
        
        Args:
            name: Name of the check
            check_fn: Function that returns (success: bool, message: str)
        """
        self._checks[name] = check_fn
        logger.debug(f"Registered health check: {name}")
    
    def run_all(self) -> dict[str, dict[str, Any]]:
        """
        Run all registered health checks.
        
        Returns:
            Dict of check results with success/message for each
        """
        results = {}
        
        for name, check_fn in self._checks.items():
            try:
                start = time.time()
                success, message = check_fn()
                duration_ms = (time.time() - start) * 1000
                
                results[name] = {
                    "success": success,
                    "message": message,
                    "duration_ms": duration_ms,
                }
            except Exception as e:
                results[name] = {
                    "success": False,
                    "message": str(e),
                    "error": True,
                }
        
        self._results = results
        return results
    
    def get_results(self) -> dict[str, dict[str, Any]]:
        """Get last health check results."""
        return self._results.copy()
    
    def is_healthy(self) -> bool:
        """Check if all registered checks pass."""
        return all(r.get("success", False) for r in self._results.values())
