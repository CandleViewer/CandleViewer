"""Domain errors for the rules module (M15)."""

from __future__ import annotations


class RulesError(Exception):
    """Base exception for the M15 `rules` module."""


class FormUnrepresentableError(RulesError, ValueError):
    """The form editor cannot express this rule (E35-Q02: a lossy hop fails loudly).

    Subclasses ``ValueError`` so existing callers of ``to_form_model`` keep working.
    """

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = tuple(reasons)
        super().__init__("rule is not form-compatible: " + "; ".join(reasons))


class ScopeForbiddenError(RulesError):
    """403: absent and not-granted accounts are indistinguishable (no existence leak)."""

    message = "Forbidden"


class ConstantTypeError(RulesError, ValueError):
    """A rule constant the evaluator cannot read as its place needs (#5807): one that is not a
    number where a comparison orders its operands or an arithmetic node computes, or text that
    reads as a number but is not decimal text (``5%``, ``NaN``). ``loc`` is its path in the rule
    (``("conditions", "right", "const")``); ``args`` is ``(loc, reason)``, so the error pickles and
    copies."""

    def __init__(self, loc: tuple[str | int, ...], reason: str) -> None:
        super().__init__(loc, reason)
        self.loc = loc
        self.reason = reason

    def __str__(self) -> str:
        return f"{self.reason} at /{'/'.join(map(str, self.loc))}"
