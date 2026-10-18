"""A rule's action budget at save and at arming: the IR defaults and the hard caps (SR-104, #3232).

SR-104 budgets a rule in two layers (`docs/plan/04-security-program.md` §6.5). This module owns
the first, the evaluation budget in the IR `limits` block: `max_fires_per_hour` and
`max_fires_per_day`, counted per scope instance. A value above its default needs the Owner role
(04 §7.2.2 row 26); a value above its hard cap is refused for every role. Arming checks both
again, the Owner check on the arming actor. The second layer, the order budget counted at
dispatch with its circuit breaker, belongs to the action executor (#863).

The defaults are read from `RuleLimits`, never restated. The caps live only here (C-16.5): the
contract mirrors them as `x-cv-limit-caps` on `RuleIr`, and a contract test keeps the two equal.
Their values are interim until the Owner ratifies them (#2701). Alerts share `RuleLimits` and are
not held to the caps (#3259).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Final

from candleviewer.rules.ir.models import RuleLimits

#: The budget fields held to a default and a cap (issue #3232, decision 6).
BUDGET_FIELDS: Final = ("max_fires_per_hour", "max_fires_per_day")
#: 600 an hour is SR-104's default order rate, 10 a minute, held for an hour; 5 000 a day keeps
#: the daily cap at the hourly cap's ratio to its default (10 times).
LIMIT_CAPS: Final[Mapping[str, int]] = MappingProxyType(
    {"max_fires_per_hour": 600, "max_fires_per_day": 5_000}
)
LIMIT_DEFAULTS: Final[Mapping[str, int]] = MappingProxyType(
    {name: int(RuleLimits.model_fields[name].default) for name in BUDGET_FIELDS}
)
_LABELS: Final = {"max_fires_per_hour": "Fires per hour", "max_fires_per_day": "Fires per day"}


def above_default(limits: RuleLimits) -> dict[str, int]:
    """Each budget field above its default, with its value: saving it needs the Owner role."""
    return {n: v for n in BUDGET_FIELDS if (v := getattr(limits, n)) > LIMIT_DEFAULTS[n]}


def above_cap(limits: RuleLimits) -> dict[str, int]:
    """Each budget field above its hard cap, with its value: no role may save it."""
    return {n: v for n in BUDGET_FIELDS if (v := getattr(limits, n)) > LIMIT_CAPS[n]}


def cap_message(name: str) -> str:
    return f"{_LABELS[name]} can be at most {LIMIT_CAPS[name]}, the hard cap for every rule."


def owner_message(name: str) -> str:
    return f"{_LABELS[name]} above the default of {LIMIT_DEFAULTS[name]} needs the Owner."


def owner_only_errors(names: Iterable[str]) -> list[dict[str, str]]:
    """The `errors` of the `403 forbidden` a non-Owner gets, at save and at arming: one entry
    per budget field above its default."""
    return [
        {"field": f"limits.{n}", "rule": "owner_only_above_default", "message": owner_message(n)}
        for n in names
    ]


__all__ = [
    "BUDGET_FIELDS",
    "LIMIT_CAPS",
    "LIMIT_DEFAULTS",
    "above_cap",
    "above_default",
    "cap_message",
    "owner_message",
    "owner_only_errors",
]
