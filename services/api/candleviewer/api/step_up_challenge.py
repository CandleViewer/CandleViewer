"""What a step-up challenge restates (#2304; PR #2290 ruling, rule 4).

Restates: `Problem.action_summary` is the route's fixed-template text over the validated request,
naming each account by its label, `environment` and `exchange_uid` with every label escaped so
its quotes bound it; `Problem.target` is the typed-confirmation text. Both come from server-side
records, never from the client. Pure functions, no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from candleviewer.accounts.models import ExchangeEnv

_ENVIRONMENTS = frozenset(env.value for env in ExchangeEnv)
_EXCHANGE_UID = re.compile(r"[0-9]{1,20}")


@dataclass(frozen=True)
class ChallengeText:
    """What a challenge restates: the route's fixed-template summary of the validated request,
    and the text a typed confirmation must equal (None when the action asks for none)."""

    action_summary: str
    target: str | None = None


def quote_label(label: str) -> str:
    """A label quoted for `action_summary`: `'` and `\\` get a backslash, and every character
    outside printable ASCII is written `\\u{XXXX}` (upper-case hex, at least four digits)."""
    out = []
    for ch in label:
        if ch in "'\\":
            out.append("\\" + ch)
        elif " " <= ch <= "~":
            out.append(ch)
        else:
            out.append(f"\\u{{{ord(ch):04X}}}")
    return "'" + "".join(out) + "'"


def account_reference(label: str, environment: str, exchange_uid: str) -> str:
    """An account named beyond its label, which can be renamed and need not be unique: its
    `environment` and `exchange_uid` never change after registration."""
    if environment not in _ENVIRONMENTS or not _EXCHANGE_UID.fullmatch(exchange_uid):
        raise ValueError("an account is named by its registered environment and UID")
    return f"{quote_label(label)} ({environment}, UID {exchange_uid})"


def typed_target(label: str, identifier: str, others: Iterable[str]) -> str:
    """`Problem.target`: the label only when it is printable ASCII and no other object of its
    kind the caller can see has it (compared case-insensitively); else the identifier."""
    folded = label.casefold()
    unique = all(other.casefold() != folded for other in others)
    return label if unique and label.isascii() and label.isprintable() else identifier


__all__ = ["ChallengeText", "account_reference", "quote_label", "typed_target"]
