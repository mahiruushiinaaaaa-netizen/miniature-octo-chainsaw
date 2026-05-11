"""
lazy_loader.py – Deferred module import proxy.

Loads modules only on first attribute access, reducing startup time and RAM usage.
Heavy modules like psutil, health_monitor, and RAG are wrapped with LazyModule
so they don't execute until actually needed.
"""
from __future__ import annotations

import importlib
import time
from typing import Any

from .logger import get_logger

logger = get_logger("lazy_loader")


class LazyModule:
    """Deferred import proxy. Loads module on first attribute access."""

    def __init__(self, module_name: str, package: str | None = None):
        # Use object.__setattr__ to avoid triggering __getattr__
        object.__setattr__(self, "_module_name", module_name)
        object.__setattr__(self, "_package", package)
        object.__setattr__(self, "_module", None)
        object.__setattr__(self, "_load_time_ms", None)
        object.__setattr__(self, "_failed", False)
        object.__setattr__(self, "_error_msg", None)

    def __getattr__(self, name: str) -> Any:
        # Skip private/dunder attributes that Python internals probe
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)

        if self._failed:
            raise AttributeError(
                f"Module '{self._module_name}' failed to import: {self._error_msg}. "
                f"Cannot access attribute '{name}'."
            )

        if self._module is None:
            self._load()

        # After load, _module could still be None if load failed
        if self._module is None:
            raise AttributeError(
                f"Module '{self._module_name}' failed to import: {self._error_msg}. "
                f"Cannot access attribute '{name}'."
            )

        return getattr(self._module, name)

    def _load(self) -> None:
        """Attempt to import the module. Track load time and handle failures."""
        module_name = self._module_name
        package = self._package

        start = time.perf_counter()
        try:
            module = importlib.import_module(module_name, package)
            load_time_ms = (time.perf_counter() - start) * 1000

            object.__setattr__(self, "_module", module)
            object.__setattr__(self, "_load_time_ms", load_time_ms)

            if load_time_ms > 200:
                logger.warn(
                    f"Slow import: {module_name} took {load_time_ms:.0f}ms",
                    operation="lazy_import",
                    duration_ms=load_time_ms,
                    context={"module": module_name},
                )
        except ImportError as e:
            load_time_ms = (time.perf_counter() - start) * 1000
            object.__setattr__(self, "_load_time_ms", load_time_ms)
            object.__setattr__(self, "_failed", True)
            object.__setattr__(self, "_error_msg", str(e))

            logger.warn(
                f"Failed to import module: {module_name} ({e})",
                operation="lazy_import",
                context={"module": module_name, "error": str(e)},
            )
        except Exception as e:
            load_time_ms = (time.perf_counter() - start) * 1000
            object.__setattr__(self, "_load_time_ms", load_time_ms)
            object.__setattr__(self, "_failed", True)
            object.__setattr__(self, "_error_msg", str(e))

            logger.warn(
                f"Unexpected error importing module: {module_name} ({e})",
                operation="lazy_import",
                context={"module": module_name, "error": str(e)},
            )

    def __repr__(self) -> str:
        if self._module is not None:
            return f"<LazyModule '{self._module_name}' (loaded in {self._load_time_ms:.0f}ms)>"
        elif self._failed:
            return f"<LazyModule '{self._module_name}' (FAILED: {self._error_msg})>"
        else:
            return f"<LazyModule '{self._module_name}' (not loaded)>"
