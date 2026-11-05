"""The order-path guard's gates and their reduce-only exemptions (E28-T04, #908; 24 Sec.8.4 "The
reduce-only exemption matrix"; C-2.6, SR-E28-24, SR-E28-30).

`EXEMPTIONS` declares, once, what each guard gate of `OrderSubmission` does to an order whose
effect is `REDUCE` (reduce-only, and shown by step 3d's read to reduce its position; never the
`reduce_only` label alone): `NONE` holds it as it holds an entry, `REDUCE` exempts it, `PROTECTIVE`
exempts it only when its route marked it `SubmitContext.protective`. An entry is exempt from no
gate. A gate added to `GuardGate` without a row fails `test_every_gate_is_in_the_exemption_matrix`.

`RefusalGate` is the closed class a guard refusal (`RiskRefused`) is counted under
(`cv_risk_guard_refusals_total{gate}`); the record names the exact rule (24 Sec.15.5).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from candleviewer.oms.ports import OrderEffect


class GuardGate(StrEnum):
    """Each gate of the submission pipeline that can refuse an order (`oms.submit` steps 1 to 6)."""

    CLOCK = "clock"
    READ_ONLY = "read_only"
    PROFILE = "profile"
    SYMBOL = "symbol"
    LEVERAGE = "leverage"
    CAPS = "caps"
    RISK_GATE = "risk_gate"
    SWITCHES = "switches"
    FENCE = "fence"


class Exemption(StrEnum):
    NONE = "none"
    REDUCE = "reduce"
    PROTECTIVE = "protective"


EXEMPTIONS: Final[Mapping[GuardGate, Exemption]] = MappingProxyType(
    {
        GuardGate.CLOCK: Exemption.NONE,  # nothing can be signed while the clock is off (10002)
        GuardGate.READ_ONLY: Exemption.NONE,  # the read-only degradation sends nothing
        GuardGate.PROFILE: Exemption.REDUCE,
        GuardGate.SYMBOL: Exemption.REDUCE,
        GuardGate.LEVERAGE: Exemption.REDUCE,
        GuardGate.CAPS: Exemption.REDUCE,  # a reduce-only order is sized by its own qty
        GuardGate.RISK_GATE: Exemption.REDUCE,
        GuardGate.SWITCHES: Exemption.PROTECTIVE,  # 24 Sec.8.10's carve-out
        GuardGate.FENCE: Exemption.NONE,  # a lane that lost its lock sends nothing
    }
)


def exempt(gate: GuardGate, effect: OrderEffect, *, protective: bool = False) -> bool:
    """Whether `gate` lets an order of `effect` through unjudged. Only a `REDUCE` effect is ever
    exempt, compared by identity, so any other value fails closed."""
    if effect is not OrderEffect.REDUCE:
        return False
    rule = EXEMPTIONS[gate]
    return rule is Exemption.REDUCE or (rule is Exemption.PROTECTIVE and protective)


class RefusalGate(StrEnum):
    """The class a guard refusal is counted under: never an account, a symbol or a figure."""

    PROFILE = "profile"
    SYMBOL = "symbol"
    CAPS = "caps"
    RISK_GATE = "risk_gate"


_PROFILE_RULES: Final = frozenset({"profile_disabled"})
_SYMBOL_RULES: Final = frozenset({"symbol_not_allowed", "symbol_denied"})


def refusal_gate(rule: str | None, step: str) -> RefusalGate:
    """The class of a guard refusal named `rule` (`RiskRefused.cap`) at pipeline `step`: the risk
    gate's verdict at `risk`, the profile's re-check at `persist`, else by its rule; any other
    rule of the size step is a cap's (or the margin's)."""
    if step == "risk":
        return RefusalGate.RISK_GATE
    if rule in _SYMBOL_RULES:
        return RefusalGate.SYMBOL
    if rule in _PROFILE_RULES or rule is None or step == "persist":
        return RefusalGate.PROFILE
    return RefusalGate.CAPS
