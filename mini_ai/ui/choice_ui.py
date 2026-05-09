from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

from .ui import C


@dataclass
class ChoiceResult:
    index: int
    label: str
    value: Any


def _read_key() -> str:
    """Read one key in a Windows-friendly way.

    Supports:
    - Up/Down arrows
    - Enter
    - Esc
    - j/k
    - n/p
    - number keys
    """
    try:
        import msvcrt

        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            if ch2 == "H":
                return "up"
            if ch2 == "P":
                return "down"
            if ch2 == "K":
                return "left"
            if ch2 == "M":
                return "right"
            return ""
        if ch == "\r":
            return "enter"
        if ch == "\x1b":
            return "esc"
        return ch
    except Exception as e:
        from ..core.logger import get_logger
        logger = get_logger("choice_ui")
        logger.debug(f"getkey() error: {e}, falling back to input()")
        raw = input("> ").strip()
        if raw == "":
            return "enter"
        return raw


def _clear_menu(lines: int) -> None:
    # Avoid fancy terminal control. Keep it compatible with cmd.exe.
    print("\n" * min(lines, 3), end="")


def choose_from_list(
    title: str,
    options: list[dict[str, Any]],
    *,
    page_size: int = 8,
    allow_cancel: bool = True,
) -> ChoiceResult | None:
    if not options:
        print("[choice] No options.")
        return None

    selected = 0
    page_size = max(3, min(page_size, 15))

    while True:
        start = max(0, min(selected - page_size // 2, len(options) - page_size))
        end = min(len(options), start + page_size)

        print("")
        print("╭─ " + title)
        print("│ Use ↑/↓ or j/k, Enter to select, Esc to cancel.")
        print("│ Type a number then Enter in basic terminals.")
        print("├" + "─" * 60)

        for i in range(start, end):
            item = options[i]
            label = str(item.get("label", item.get("title", item.get("value", f"Option {i + 1}"))))
            description = str(item.get("description", "")).strip()
            prefix = "➤" if i == selected else " "
            number = f"{i + 1:>2}."
            print(f"│ {prefix} {number} {label}")
            if description:
                print(f"│      {description[:72]}")

        print("╰" + "─" * 60)
        print(f"Selected {selected + 1}/{len(options)}", end=" ", flush=True)

        key = _read_key()

        if key in {"esc", "q"} and allow_cancel:
            print("[choice] Cancelled.")
            return None

        if key in {"up", "k", "p", "left"}:
            selected = max(0, selected - 1)
            _clear_menu(end - start + 6)
            continue

        if key in {"down", "j", "n", "right"}:
            selected = min(len(options) - 1, selected + 1)
            _clear_menu(end - start + 6)
            continue

        if key == "enter":
            item = options[selected]
            return ChoiceResult(
                index=selected,
                label=str(item.get("label", item.get("title", item.get("value", selected)))),
                value=item.get("value", item.get("label", selected)),
            )

        if key.isdigit():
            choice = int(key)
            if 1 <= choice <= len(options):
                selected = choice - 1
                item = options[selected]
                return ChoiceResult(
                    index=selected,
                    label=str(item.get("label", item.get("title", item.get("value", selected)))),
                    value=item.get("value", item.get("label", selected)),
                )

        # Fallback for typed number + enter through stdin.
        try:
            choice = int(key)
            if 1 <= choice <= len(options):
                selected = choice - 1
                item = options[selected]
                return ChoiceResult(
                    index=selected,
                    label=str(item.get("label", item.get("title", item.get("value", selected)))),
                    value=item.get("value", item.get("label", selected)),
                )
        except (ValueError, IndexError) as e:
            from ..core.logger import get_logger
            logger = get_logger("choice_ui")
            logger.debug(f"Invalid choice input '{key}': {e}")

        _clear_menu(end - start + 6)


def normalize_options(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []

    options: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            label = str(item.get("label", item.get("title", item.get("value", ""))).strip())
            if not label:
                label = "Option"
            options.append(dict(item, label=label))
        else:
            options.append({"label": str(item), "value": item})
    return options


def confirm(question: str, default: bool = True) -> bool:
    """Ask a yes/no question using left/right arrows for selection."""
    # If not in a TTY, fall back to simple input for compatibility (e.g. GUI)
    if not sys.stdout.isatty():
        hint = "[Y/n]" if default else "[y/N]"
        prompt = f"{question} {hint}> "
        try:
            ans = input(prompt).strip().lower()
            if not ans: return default
            return ans == "y"
        except EOFError:
            return default

    selected = 0 if default else 1  # 0 for Yes, 1 for No

    # Hide cursor
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

    try:
        while True:
            # Highlight selected option
            if selected == 0:
                yes_btn = f"{C.bg_soft}{C.bold}{C.a_green} › Yes {C.reset}"
                no_btn = f"   No  "
            else:
                yes_btn = f"   Yes "
                no_btn = f"{C.bg_soft}{C.bold}{C.a_red} › No  {C.reset}"

            # Add hint about what Enter does
            hint = f"{C.gray}(Enter for {'Yes' if default else 'No'}){C.reset}"
            sys.stdout.write(f"\r{C.bold}{C.a_yellow}?{C.reset} {question}  {yes_btn}  {no_btn} {hint} ")
            sys.stdout.flush()

            key = _read_key()

            if key in {"left", "right", "h", "l", "tab"}:
                selected = 1 - selected
            elif key == "y":
                selected = 0
                break
            elif key == "n":
                selected = 1
                break
            elif key == "enter":
                break
            elif key == "esc":
                selected = 1  # Default to No on escape
                break

        # Move to next line and show final choice
        sys.stdout.write("\r" + " " * 100 + "\r")  # Clear line
        final_label = f"{C.a_green}Yes{C.reset}" if selected == 0 else f"{C.a_red}No{C.reset}"
        sys.stdout.write(f"{C.bold}{C.a_green}✓{C.reset} {question} {C.gray}›{C.reset} {final_label}\n")
        sys.stdout.flush()
        return selected == 0

    finally:
        # Show cursor again
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
