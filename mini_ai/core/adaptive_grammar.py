"""
adaptive_grammar.py – Adaptive grammar selection based on model size and runtime behavior.

Selects the appropriate GBNF grammar for constraining model output:
- Small models (< 7B): THINK_JSON_GRAMMAR (allows think block prefix)
- Large models (≥ 7B): JSON_ACTION_GRAMMAR (direct JSON action)

Automatically disables grammar enforcement if the model produces consecutive
empty responses, falling back to JSON parsing with repair.
"""
from __future__ import annotations

import re
from pathlib import Path

from .grammars import THINK_JSON_GRAMMAR, JSON_ACTION_GRAMMAR
from .logger import get_logger

logger = get_logger("adaptive_grammar")

# Regex to extract model size from GGUF filename (e.g., "3B", "7B", "14B", "0.5B")
_SIZE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*[Bb]")


class AdaptiveGrammarSelector:
    """Selects grammar based on model size and runtime behavior.

    The selector detects model parameter count from the GGUF filename and
    chooses the appropriate grammar. It also monitors for empty responses
    and disables grammar enforcement after 2 consecutive empty outputs.
    """

    def __init__(self, config):
        """Initialize with a Config object containing the model path.

        Args:
            config: Config instance with a `model` attribute (Path or None).
        """
        self.model_size_b: float = self._detect_model_size(config.model)
        self.empty_response_count: int = 0
        self.grammar_disabled: bool = False

        logger.info(
            f"Adaptive grammar initialized: model_size={self.model_size_b}B, "
            f"grammar={'THINK_JSON' if self.model_size_b < 7 else 'JSON_ACTION'}"
        )

    def _detect_model_size(self, model_path: Path | None) -> float:
        """Extract parameter count from GGUF filename.

        Matches patterns like "3B", "7B", "14B", "0.5B" in the filename.
        Defaults to a value < 7 (3.0) if no pattern is found.

        Args:
            model_path: Path to the GGUF model file, or None.

        Returns:
            Detected model size in billions of parameters.
        """
        if model_path is None:
            logger.debug("No model path provided, defaulting to < 7B")
            return 3.0

        filename = Path(model_path).name
        match = _SIZE_PATTERN.search(filename)

        if match:
            size = float(match.group(1))
            logger.debug(f"Detected model size {size}B from filename: {filename}")
            return size

        logger.debug(f"No size pattern found in filename: {filename}, defaulting to < 7B")
        return 3.0

    def select_grammar(self) -> str | None:
        """Return the appropriate grammar string or None if disabled.

        Returns:
            THINK_JSON_GRAMMAR for < 7B models, JSON_ACTION_GRAMMAR for ≥ 7B,
            or None if grammar has been disabled due to empty responses.
        """
        if self.grammar_disabled:
            return None

        if self.model_size_b < 7:
            return THINK_JSON_GRAMMAR

        return JSON_ACTION_GRAMMAR

    def record_empty_response(self) -> None:
        """Track a consecutive empty response from the model.

        After 2 consecutive empty responses, grammar enforcement is disabled
        for the remainder of the session.
        """
        self.empty_response_count += 1
        if self.empty_response_count >= 2:
            self.grammar_disabled = True
            logger.warn(
                "Grammar disabled due to 2 consecutive empty responses. "
                "Falling back to JSON parsing with repair."
            )

    def record_success(self) -> None:
        """Record a successful (non-empty) model response.

        Resets the empty response counter.
        """
        self.empty_response_count = 0
