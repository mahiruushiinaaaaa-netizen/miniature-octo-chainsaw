"""
prompting.py – Lean prompt builder. /no_think disables chain-of-thought for speed.
"""
from __future__ import annotations

import re

_CLEAN_TOKENS = (
    "<|im_end|>", "<|endoftext|>",
    "<|im_start|>assistant", "<|im_start|>user",
)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN = re.compile(r"^<think>.*", re.DOTALL | re.IGNORECASE)


def build_chat_prompt(user_text: str, system_text: str | None = None) -> str:
    system_text = system_text or (
        "You are a helpful local AI assistant. Answer directly and concisely."
    )
    return (
        "<|im_start|>system\n"
        f"{system_text}\n"
        "<|im_end|>\n"
        "<|im_start|>user\n"
        f"{user_text}\n"
        "<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def clean_model_output(text: str) -> str:
    # text = _THINK_RE.sub("", text)
    # text = _THINK_OPEN.sub("", text)
    for tok in _CLEAN_TOKENS:
        text = text.replace(tok, "")
    text = text.strip()
    if text.lower().startswith("assistant"):
        text = text[len("assistant"):].strip()
    if text.startswith(":"):
        text = text[1:].strip()
    return text.strip()
