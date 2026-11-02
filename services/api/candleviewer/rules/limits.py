"""A rule's action budget at save and at arming: the IR defaults and the hard caps (SR-104, #3232).

SR-104 budgets a rule in two layers (`docs/plan/04-security-program.md` §6.5). This module owns
the first, the evaluation budget in the IR `limits` block: `max_fires_per_hour` and
`max_fires_per_day`, counted per scope instance. A value above its default needs the Owner role
(04 §7.2.2 row 26); a value above its hard cap is refused for every role. Arming checks both
again, the Owner check on the arming actor. The second layer, the order budget counted at
dispatch with its circuit breaker, belongs to the action executor (#863): its defaults and hard
caps live here too (`ORDER_BUDGET_DEFAULTS`, `ORDER_BUDGET_CAPS`; E35-T10), beside the count of
scope refusals that disarms a rule (`SCOPE_DENIALS_BEFORE_DISARM`).

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
#: SR-104's order budget per rule (24 §11.7; E35-T10, BQ-6): the defaults the two boot settings
#: start from (`CV_RULES_ORDER_BUDGET_PER_MINUTE`, `CV_RULES_ORDER_BUDGET_PER_DAY`), and the hard
#: caps no setting may exceed (`create_app` refuses to start above one). Interim, pending the
#: owner's ratification (#2701): one order a second per rule stays well under the per-UID create
#: budget the rate governor holds, and the daily cap keeps the minute cap's ratio to its default.
ORDER_BUDGET_DEFAULTS: Final[Mapping[str, int]] = MappingProxyType(
    {"per_minute": 10, "per_day": 200}
)
ORDER_BUDGET_CAPS: Final[Mapping[str, int]] = MappingProxyType({"per_minute": 60, "per_day": 2_000})
#: Consecutive `scope` or `permission` refusals per rule and account, the tick's scope-skipped
#: evaluations included, that disarm the rule (24 §11.5; RE-E1, BQ-10). Interim, pending the
#: owner's ratification (#2701).
SCOPE_DENIALS_BEFORE_DISARM: Final = 5
#: The signal chain's depth limit (24 §11.5; RE-D7, E35-T13 BQ-5): the boot setting
#: `CV_RULES_SIGNAL_MAX_DEPTH` starts from the default, and `create_app` refuses to start above the
#: hard cap. The cap and the signal queue's bound are interim, pending the owner's ratification
#: (#2701): a signal past the queue's bound is refused, the newest, never one waiting.
SIGNAL_MAX_DEPTH_DEFAULT: Final = 3
SIGNAL_MAX_DEPTH_CAP: Final = 3
SIGNAL_QUEUE_BOUND: Final = 256
#: A rule's variable store (24 §11.5, E35-T13 BQ-6): at most this many variables per rule, each
#: value at most this many bytes of canonical JSON; a set past either is refused, never an eviction.
VARIABLES_PER_RULE: Final = 32
VARIABLE_VALUE_MAX_BYTES: Final = 1024
#: A `rule.notify` outbox row still unclaimed this long after it was written is dead-lettered, and
#: kept (21 §3.10.4; E35-T13, BQ-8 of #5005): PROPOSED, interim, pending the owner's ratification
#: (#2701). No consumer claims the topic until E40, and the table keeps no retention, so each
#: write dead-letters at most `RULE_NOTIFY_SWEEP_LIMIT` of the topic's expired rows.
RULE_NOTIFY_TTL_S: Final = 86_400.0
RULE_NOTIFY_SWEEP_LIMIT: Final = 100


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
    "ORDER_BUDGET_CAPS",
    "ORDER_BUDGET_DEFAULTS",
    "RULE_NOTIFY_SWEEP_LIMIT",
    "RULE_NOTIFY_TTL_S",
    "SCOPE_DENIALS_BEFORE_DISARM",
    "SIGNAL_MAX_DEPTH_CAP",
    "SIGNAL_MAX_DEPTH_DEFAULT",
    "SIGNAL_QUEUE_BOUND",
    "VARIABLES_PER_RULE",
    "VARIABLE_VALUE_MAX_BYTES",
    "above_cap",
    "above_default",
    "cap_message",
    "owner_message",
    "owner_only_errors",
]
