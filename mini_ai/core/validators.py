"""
validators.py – Dependency validation and health checks.

Validates:
- Required and optional dependencies
- Version compatibility
- External tool availability
- System resources
- Network connectivity
"""
from __future__ import annotations

import importlib
import importlib.metadata
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Any
from packaging import version

from .logger import get_logger
from .errors import ValidationError, ResourceNotFoundError, ErrorContext
from .environment import get_environment, EnvironmentDetector, OSType

logger = get_logger("validators")


@dataclass
class DependencySpec:
    """Specification for a dependency."""
    name: str
    min_version: Optional[str] = None
    max_version: Optional[str] = None
    optional: bool = False
    reason: str = ""
    check_func: Optional[Callable[[], tuple[bool, str]]] = None


@dataclass
class ValidationResult:
    """Result of a validation check."""
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    fix_suggestion: str = ""


class DependencyValidator:
    """Validates Python package and system dependencies."""
    
    # Known package mappings (import name -> distribution name)
    PACKAGE_MAPPINGS = {
        "ddgs": "duckduckgo-search",
        "PIL": "Pillow",
        "yaml": "PyYAML",
        "cv2": "opencv-python",
    }
    
    def __init__(self):
        self._results: dict[str, ValidationResult] = {}
    
    def validate_python_package(
        self,
        spec: DependencySpec,
    ) -> ValidationResult:
        """Validate a Python package is installed and meets version requirements."""
        # Map import name to distribution name if needed
        dist_name = self.PACKAGE_MAPPINGS.get(spec.name, spec.name)
        
        # Windows-specific: help python-vlc find libvlc.dll
        if spec.name == "vlc" and sys.platform == "win32":
            import os
            vlc_paths = [
                os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "VideoLAN", "VLC"),
                os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "VideoLAN", "VLC"),
            ]
            for path in vlc_paths:
                if os.path.exists(os.path.join(path, "libvlc.dll")):
                    if hasattr(os, "add_dll_directory"):
                        try: os.add_dll_directory(path)
                        except: pass
                    os.environ["PATH"] = path + os.pathsep + os.environ["PATH"]
                    break

        try:
            # Try importing
            module = importlib.import_module(spec.name)
            
            # Check version if available
            installed_version = None
            try:
                installed_version = importlib.metadata.version(dist_name)
            except importlib.metadata.PackageNotFoundError:
                # Try getting version from module
                installed_version = getattr(module, "__version__", None)
            
            if installed_version and spec.min_version:
                if version.parse(installed_version) < version.parse(spec.min_version):
                    return ValidationResult(
                        passed=False,
                        message=f"{spec.name} {installed_version} < required {spec.min_version}",
                        fix_suggestion=f"pip install {dist_name}>={spec.min_version}",
                    )
            
            if installed_version and spec.max_version:
                if version.parse(installed_version) > version.parse(spec.max_version):
                    return ValidationResult(
                        passed=False,
                        message=f"{spec.name} {installed_version} > max {spec.max_version}",
                        fix_suggestion=f"pip install {dist_name}<={spec.max_version}",
                    )
            
            # Run custom check if provided
            if spec.check_func:
                ok, msg = spec.check_func()
                if not ok:
                    return ValidationResult(
                        passed=False,
                        message=msg,
                        fix_suggestion=f"Check {spec.name} configuration",
                    )
            
            return ValidationResult(
                passed=True,
                message=f"{spec.name} {installed_version or 'installed'}",
            )
            
        except (ImportError, Exception) as e:
            severity = "optional" if spec.optional else "required"
            # Distinguish between "not installed" and "load error"
            msg = f"{spec.name} not installed ({severity})" if isinstance(e, ImportError) else f"{spec.name} load error: {str(e)}"
            return ValidationResult(
                passed=spec.optional,  # Optional deps don't fail validation
                message=msg,
                fix_suggestion=f"pip install {dist_name}" if not spec.optional else "",
            )
    
    def validate_system_binary(
        self,
        name: str,
        version_flag: str = "--version",
        min_version: Optional[str] = None,
    ) -> ValidationResult:
        """Validate a system binary is available."""
        env = get_environment()
        
        path = env.available_binaries.get(name)
        if not path:
            return ValidationResult(
                passed=False,
                message=f"{name} not found in PATH",
                fix_suggestion=f"Install {name} and ensure it's in PATH",
            )
        
        # Try to get version
        if min_version:
            try:
                result = subprocess.run(
                    [path, version_flag],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    # Extract version number from output
                    version_match = re.search(r'(\d+\.\d+(?:\.\d+)?)', result.stdout)
                    if version_match:
                        installed = version_match.group(1)
                        if version.parse(installed) < version.parse(min_version):
                            return ValidationResult(
                                passed=False,
                                message=f"{name} {installed} < required {min_version}",
                                fix_suggestion=f"Upgrade {name} to >= {min_version}",
                            )
            except Exception as e:
                logger.debug(f"Could not check {name} version: {e}")
        
        return ValidationResult(
            passed=True,
            message=f"{name} available at {path}",
        )
    
    def validate_all(
        self,
        dependencies: list[DependencySpec],
    ) -> dict[str, ValidationResult]:
        """Validate multiple dependencies."""
        results = {}
        for spec in dependencies:
            results[spec.name] = self.validate_python_package(spec)
        return results


class HealthChecker:
    """Performs system health checks."""
    
    def __init__(self):
        self._validator = DependencyValidator()
        self._last_report: Optional[dict[str, Any]] = None
    
    def check_disk_space(
        self,
        path: Path,
        min_mb: int = 100,
    ) -> ValidationResult:
        """Check available disk space."""
        try:
            import shutil
            _, _, free = shutil.disk_usage(path)
            free_mb = free / (1024 * 1024)
            
            if free_mb < min_mb:
                return ValidationResult(
                    passed=False,
                    message=f"Low disk space: {free_mb:.0f}MB < {min_mb}MB required",
                    fix_suggestion="Free up disk space",
                )
            
            return ValidationResult(
                passed=True,
                message=f"Disk space OK: {free_mb:.0f}MB available",
                details={"free_mb": free_mb},
            )
        except Exception as e:
            return ValidationResult(
                passed=False,
                message=f"Could not check disk space: {e}",
            )
    
    def check_memory(self, min_mb: int = 500) -> ValidationResult:
        """Check available memory."""
        env = get_environment()
        ram_mb = env.ram_mb
        
        if ram_mb is None:
            return ValidationResult(
                passed=True,
                message="Memory check skipped (could not detect)",
            )
        
        if ram_mb < min_mb:
            return ValidationResult(
                passed=False,
                message=f"Low memory: {ram_mb}MB < {min_mb}MB recommended",
                fix_suggestion="Close other applications or use a smaller model",
            )
        
        return ValidationResult(
            passed=True,
            message=f"Memory OK: {ram_mb}MB available",
            details={"ram_mb": ram_mb},
        )
    
    def check_network(self, timeout: int = 5) -> ValidationResult:
        """Check network connectivity."""
        import urllib.request
        import socket
        
        try:
            # Try to connect to a reliable host
            socket.setdefaulttimeout(timeout)
            urllib.request.urlopen("https://duckduckgo.com", timeout=timeout)
            return ValidationResult(
                passed=True,
                message="Network connectivity OK",
            )
        except Exception as e:
            return ValidationResult(
                passed=False,
                message=f"Network connectivity issue: {e}",
                fix_suggestion="Check internet connection",
            )
        finally:
            socket.setdefaulttimeout(None)
    
    def check_model_server(
        self,
        base_url: str = "http://127.0.0.1:8080",
        timeout: int = 2,
    ) -> ValidationResult:
        """Check if llama-server is running."""
        import urllib.request
        import json
        
        try:
            for path in ["/health", "/healthz", "/v1/models"]:
                try:
                    req = urllib.request.urlopen(
                        base_url + path,
                        timeout=timeout,
                    )
                    if req.status == 200:
                        return ValidationResult(
                            passed=True,
                            message=f"Model server responsive at {base_url}",
                        )
                except:
                    continue
            
            return ValidationResult(
                passed=False,
                message=f"Model server not responsive at {base_url}",
                fix_suggestion="Start llama-server or check configuration",
            )
        except Exception as e:
            return ValidationResult(
                passed=False,
                message=f"Could not reach model server: {e}",
                fix_suggestion="Start llama-server",
            )
    
    def full_health_check(
        self,
        workspace: Path,
        server_url: Optional[str] = None,
    ) -> dict[str, ValidationResult]:
        """Perform comprehensive health check."""
        with logger.operation("full_health_check"):
            results = {
                "disk_space": self.check_disk_space(workspace),
                "memory": self.check_memory(),
                "network": self.check_network(),
            }
            
            if server_url:
                results["model_server"] = self.check_model_server(server_url)
            
            self._last_report = results
            return results
    
    def generate_report(self, results: dict[str, ValidationResult]) -> str:
        """Generate human-readable health report."""
        lines = ["━━━ Health Report ━━━"]
        
        all_passed = all(r.passed for r in results.values())
        status = "✓ HEALTHY" if all_passed else "✕ ISSUES FOUND"
        lines.append(f"\nStatus: {status}\n")
        
        for name, result in results.items():
            icon = "✓" if result.passed else "✕"
            lines.append(f"{icon} {name}: {result.message}")
            if not result.passed and result.fix_suggestion:
                lines.append(f"    → {result.fix_suggestion}")
        
        return "\n".join(lines)
    
    def raise_if_unhealthy(
        self,
        results: dict[str, ValidationResult],
        critical_only: bool = True,
    ) -> None:
        """Raise exception if health checks failed."""
        failures = [
            (name, r) for name, r in results.items()
            if not r.passed
        ]
        
        if not failures:
            return
        
        # For critical checks only, filter out network if optional
        if critical_only:
            failures = [
                (n, r) for n, r in failures
                if n != "network"  # Network is often optional
            ]
        
        if failures:
            messages = [f"{n}: {r.message}" for n, r in failures]
            raise ValidationError(
                f"Health check failed: {'; '.join(messages)}",
                context=ErrorContext(
                    operation="health_check",
                    recoverable=True,
                    suggested_action="Fix the reported issues and retry",
                ),
            )


# Common dependency specifications
REQUIRED_DEPS: list[DependencySpec] = []

OPTIONAL_DEPS: list[DependencySpec] = [
    DependencySpec(
        name="ddgs",
        optional=True,
        reason="Web search functionality",
    ),
    DependencySpec(
        name="yt_dlp",
        optional=True,
        reason="Media playback functionality",
    ),
    DependencySpec(
        name="certifi",
        optional=True,
        reason="SSL certificate verification",
    ),
    DependencySpec(
        name="prompt_toolkit",
        optional=True,
        reason="Enhanced interactive CLI",
    ),
    DependencySpec(
        name="pygments",
        optional=True,
        reason="Syntax highlighting",
    ),
    DependencySpec(
        name="vlc",
        optional=True,
        reason="High-quality audio streaming and playback (required for music)",
    ),
    DependencySpec(
        name="psutil",
        optional=True,
        reason="Resource monitoring and sandbox management",
    ),
]


def quick_check() -> bool:
    """Quick validation for startup."""
    checker = HealthChecker()
    env = get_environment()
    
    results = checker.full_health_check(env.home_dir)
    
    # Only check critical failures
    critical = ["disk_space", "memory"]
    failed = [r for name, r in results.items() if not r.passed and name in critical]
    
    return len(failed) == 0


__all__ = [
    "DependencySpec",
    "ValidationResult",
    "DependencyValidator",
    "HealthChecker",
    "REQUIRED_DEPS",
    "OPTIONAL_DEPS",
    "quick_check",
]
