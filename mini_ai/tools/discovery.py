from __future__ import annotations

import shutil
from pathlib import Path

from ..core.config import LMSTUDIO_CLI_CANDIDATES, LLAMA_SERVER_CANDIDATES
from ..ui import err, ok
from ..core.settings import get_cached_model, set_cached_model



def which_any(names: list[str]) -> Path | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def existing_path(path_text: str | Path | None) -> Path | None:
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    return path if path.exists() else None


def find_llama_cli(user_bin: str | None) -> Path | None:
    explicit = existing_path(user_bin)
    if explicit:
        return explicit
    for candidate in LMSTUDIO_CLI_CANDIDATES:
        if candidate.exists():
            return candidate
    return which_any(["llama-cli", "llama-cli.exe", "llama"])


def find_llama_server(user_bin: str | None, cli_bin: Path | None) -> Path | None:
    explicit = existing_path(user_bin)
    if explicit:
        return explicit
    if cli_bin:
        for name in ("llama-server.exe", "llama-server"):
            sibling = cli_bin.with_name(name)
            if sibling.exists():
                return sibling
    for candidate in LLAMA_SERVER_CANDIDATES:
        if candidate.exists():
            return candidate
    return which_any(["llama-server", "llama-server.exe"])


def list_models(models_dir: Path) -> list[Path]:
    if not models_dir.is_dir():
        return []
    return sorted(models_dir.rglob("*.gguf"))


def is_chat_model(path: Path) -> bool:
    text = str(path).lower()
    if "mmproj" in text or "embedding" in text:
        return False
    return path.suffix.lower() == ".gguf"


def model_score(path: Path) -> int:
    text = str(path).lower()
    score = 0

    # Prefer models that worked well in this project.
    if "dria" in text and "agent" in text:
        score += 100
    if "qwen2" in text and "instruct" in text:
        score += 90
    if "qwen3" in text:
        score += 70

    # Avoid non-chat/helper models.
    if "mmproj" in text:
        score -= 1000
    if "embedding" in text:
        score -= 1000

    # Avoid tiny weak models unless there is no better choice.
    if "135m" in text:
        score -= 80
    if "500m" in text:
        score -= 35
    if "0.5b" in text:
        score -= 35

    # Prefer reasonable quantizations.
    if "q4_k_m" in text:
        score += 10
    if "q8_0" in text:
        score += 5
    if "q6_k" in text:
        score += 4

    return score


def auto_choose_model(models_dir: Path, avoid: Path | list[Path] | None = None) -> Path | None:
    avoid_paths = [avoid.resolve()] if isinstance(avoid, Path) else ([p.resolve() for p in avoid] if isinstance(avoid, list) else [])
    
    cached = get_cached_model(models_dir)
    if cached and cached.resolve() not in avoid_paths:
        try:
            display = cached.relative_to(models_dir)
        except ValueError:
            display = cached
        ok(f"Using cached model: {display}")
        return cached

    models = [model for model in list_models(models_dir) if is_chat_model(model)]
    if not models:
        err(f"No chat GGUF models found in: {models_dir}")
        return None
        
    if avoid_paths and len(models) > 1:
        models = [m for m in models if m.resolve() not in avoid_paths] or models

    selected = max(models, key=model_score)
    set_cached_model(models_dir, selected)

    try:
        display = selected.relative_to(models_dir)
    except ValueError:
        display = selected
    ok(f"Auto-selected model: {display}")
    return selected


def model_label(path: Path) -> str:
    text = str(path).lower()
    if "mmproj" in text:
        return "  [vision helper, not chat]"
    if "embedding" in text:
        return "  [not for chat]"
    if "dria" in text and "agent" in text:
        return "  [best for agent]"
    if "qwen2" in text and "instruct" in text:
        return "  [good for commands]"
    if "qwen3" in text:
        return "  [bigger/slower]"
    if "135m" in text or "500m" in text or "0.5b" in text:
        return "  [tiny/weak]"
    return ""


def choose_model(models_dir: Path) -> Path | None:
    models = list_models(models_dir)
    if not models:
        err(f"No GGUF models found in: {models_dir}")
        return None

    print("Available models:")
    for index, model in enumerate(models, start=1):
        try:
            display = model.relative_to(models_dir)
        except ValueError:
            display = model
        print(f"  {index}. {display}{model_label(model)}")

    while True:
        choice = input("Select model number> ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(models):
            return models[int(choice) - 1]
        print(f"Invalid selection. Enter a number from 1 to {len(models)}.")


def ui_model_score(path: Path) -> int:
    text = str(path).lower()
    score = 0

    # UI model should be quick and conversational, not embeddings/vision helpers.
    if "qwen2" in text and "500m" in text:
        score += 110
    if "smollm" in text:
        score += 95
    if "500m" in text:
        score += 60
    if "135m" in text:
        score += 45
    if "qwen3" in text and "1.7b" in text:
        score += 30
    if "dria" in text and "agent" in text:
        score += 20

    if "mmproj" in text or "embedding" in text:
        score -= 1000
    if "nsfw" in text:
        score -= 200

    if "q8_0" in text:
        score += 8
    if "q4_k_m" in text:
        score += 5

    return score


def auto_choose_ui_model(models_dir: Path, avoid: Path | list[Path] | None = None) -> Path | None:
    avoid_paths = [avoid.resolve()] if isinstance(avoid, Path) else ([p.resolve() for p in avoid] if isinstance(avoid, list) else [])
    
    models = [model for model in list_models(models_dir) if is_chat_model(model)]
    if not models:
        return None

    if avoid_paths and len(models) > 1:
        models = [model for model in models if model.resolve() not in avoid_paths] or models

    selected = max(models, key=ui_model_score)
    try:
        display = selected.relative_to(models_dir)
    except ValueError:
        display = selected
    ok(f"Auto-selected UI model: {display}")
    return selected


def auto_choose_role_model(models_dir: Path, role: str) -> Path | None:
    """Choose a model from a role-specific subdirectory (e.g. models/agent/)."""
    role_dir = models_dir / role
    if not role_dir.is_dir():
        return None
    
    models = [model for model in list_models(role_dir) if is_chat_model(model)]
    if not models:
        return None
        
    # Use ui_model_score for analyzer (fast) and model_score for others
    score_fn = ui_model_score if role == "analyzer" else model_score
    selected = max(models, key=score_fn)
    
    try:
        display = selected.relative_to(models_dir)
    except ValueError:
        display = selected
        
    ok(f"Auto-selected {role} model: {display}")
    return selected
