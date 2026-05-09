from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .environment import EnvironmentDetector

def _get_app_dir() -> Path:
    """Get platform-appropriate application directory."""
    detector = EnvironmentDetector()
    return detector.get_config_dir() / "settings"

def _get_settings_file() -> Path:
    """Get platform-appropriate settings file path."""
    return _get_app_dir() / "settings.json"

# Legacy support - module-level constants computed on first use
APP_DIR = _get_app_dir()
SETTINGS_FILE = _get_settings_file()


def load_settings() -> dict[str, Any]:
    try:
        if SETTINGS_FILE.exists():
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_settings(settings: dict[str, Any]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def get_saved_models_dir() -> Path | None:
    settings = load_settings()
    value = str(settings.get("models_dir", "")).strip()
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.exists() else None


def set_saved_models_dir(path: Path) -> None:
    settings = load_settings()
    settings["models_dir"] = str(path.expanduser().resolve())
    save_settings(settings)


def clear_saved_models_dir() -> None:
    settings = load_settings()
    settings.pop("models_dir", None)
    save_settings(settings)


def get_cached_model(models_dir: Path) -> Path | None:
    settings = load_settings()
    value = str(settings.get("cached_model", "")).strip()
    cached_dir = str(settings.get("cached_model_dir", "")).strip()
    if not value or not cached_dir:
        return None

    if str(models_dir.expanduser().resolve()) != cached_dir:
        return None

    path = Path(value).expanduser()
    return path if path.exists() else None


def set_cached_model(models_dir: Path, model: Path) -> None:
    settings = load_settings()
    settings["cached_model_dir"] = str(models_dir.expanduser().resolve())
    settings["cached_model"] = str(model.expanduser().resolve())
    save_settings(settings)


def clear_cached_model() -> None:
    settings = load_settings()
    settings.pop("cached_model", None)
    settings.pop("cached_model_dir", None)
    save_settings(settings)
