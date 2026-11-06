"""Validation / compile issue model shared by the compiler and validator (E35-T04).

Every issue carries a stable machine ``code`` (editors key inline messages and jump-to-node off it,
never the prose) and a human message that names the row/node in words.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

Severity = Literal["error", "warning"]
IssueClass = Literal["syntax", "semantics", "safety", "performance"]

#: The most issues a validation answer lists (22 `validateRule`, `compileRule`, "Bounded answer"):
#: the first ones found, in order, beside `issues_total`, the count of every one found.
MAX_RETURNED_ISSUES: Final = 50


@dataclass(frozen=True, slots=True)
class Issue:
    path: str
    code: str
    message: str
    severity: Severity = "error"
    klass: IssueClass = "semantics"
    node_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "path": self.path,
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "class": self.klass,
        }
        if self.node_ids:
            out["node_ids"] = list(self.node_ids)
        return out


class RuleCompileError(Exception):
    """Structural compile failure: no IR is produced (maps to 422 ``rule_ir_invalid``). ``total``
    counts every issue found, ``issues`` holding only the first of them when a collector keeps
    no more than an answer lists (``MAX_RETURNED_ISSUES``); it defaults to their number."""

    def __init__(self, issues: list[Issue], total: int | None = None) -> None:
        first = issues[0].message if issues else "invalid rule model"
        self.total = len(issues) if total is None else total
        super().__init__(f"{self.total} error(s) compiling the rule model: {first}")
        self.issues = issues
