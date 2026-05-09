from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ApprovalPolicy:
    """Runtime approval policy.

    ask:
        Ask before every write/run/destructive action.
    safe:
        Auto-approve non-destructive actions. Still ask before delete/move/overwrite/system installs.
    all:
        Auto-approve everything, including destructive actions. Use carefully.
    """

    mode: str = "ask"

    def set_mode(self, mode: str) -> None:
        mode = mode.lower().strip()
        if mode not in {"ask", "safe", "all"}:
            mode = "ask"
        self.mode = mode

    @property
    def auto_safe(self) -> bool:
        return self.mode in {"safe", "all"}

    @property
    def auto_destructive(self) -> bool:
        return self.mode == "all"

    def should_ask(self, *, destructive: bool = False) -> bool:
        if destructive:
            return not self.auto_destructive
        return not self.auto_safe


POLICY = ApprovalPolicy()


def set_approval_mode(mode: str) -> None:
    POLICY.set_mode(mode)


def approval_mode() -> str:
    return POLICY.mode


def should_auto_approve(*, destructive: bool = False, assume_yes: bool = False) -> bool:
    if destructive:
        return POLICY.auto_destructive
    return assume_yes or POLICY.auto_safe
