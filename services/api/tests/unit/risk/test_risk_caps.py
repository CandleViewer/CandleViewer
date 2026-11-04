"""E39-T01 (#881) slice 1: cap resolution (Gherkin 3) and the override-never-widens invariant.

SR-E39-03 (`docs/security/threat-models/E39-risk-killswitch.md`): caps resolve only from the three
stored layers, most restrictive first; nothing in a request and no override raises one.
"""

from __future__ import annotations

from dataclasses import fields
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from candleviewer.risk.caps import CapSource, ManagerCaps, resolve_caps
from candleviewer.risk.inputs import RiskOrder
from candleviewer.risk.models import RiskRefusal
from tests.unit.risk._risk_builders import D, caps, figures, policy, profile, run


def test_resolve_caps_most_restrictive_wins_and_names_the_manager() -> None:  # Gherkin 3
    c = caps(
        pol={"max_daily_loss_usd": D(1000)},
        prof={"max_daily_loss_usd": D(800)},
        mgr=ManagerCaps(max_daily_loss_usd=D(500)),
    )
    cap = c.get("max_daily_loss_usd")
    assert cap is not None and (cap.limit, cap.source) == (D(500), CapSource.MANAGER)
    decision = run(f=figures(daily_figure=D(-600)), c=c).decision
    assert (decision.code, decision.limit, decision.actual) == (
        RiskRefusal.RISK_LIMIT_BREACHED,
        D(500),
        D(600),
    )
    assert decision.message.endswith("set by the manager override")


def test_resolve_caps_tie_names_the_most_specific_layer() -> None:
    c = caps(pol={"max_daily_loss_usd": D(800)}, prof={"max_daily_loss_usd": D(800)})
    assert c.caps["max_daily_loss_usd"].source is CapSource.PROFILE
    c = caps(prof={"max_daily_loss_usd": D(500)}, mgr=ManagerCaps(D(500)))
    assert c.caps["max_daily_loss_usd"].source is CapSource.MANAGER


def test_resolve_caps_null_layers_set_no_limit() -> None:
    c = resolve_caps(policy(), profile())
    assert "max_position_notional_usd" not in c.caps and c.get("max_consecutive_losses") is None
    assert c.caps["max_open_positions"].source is CapSource.POLICY
    assert c.caps["max_leverage"].limit == D(100)


def test_resolve_caps_policy_orders_per_minute_alone_blocks() -> None:
    c = caps(pol={"max_orders_per_minute": 5})
    cap = c.get("max_orders_per_minute")
    assert cap is not None and (cap.limit, cap.source) == (D(5), CapSource.POLICY)
    assert run(f=figures(orders_last_minute=4), c=c).decision.allowed
    decision = run(f=figures(orders_last_minute=5), c=c).decision
    assert (decision.cap, decision.limit) == ("max_orders_per_minute", D(5))


def test_resolve_caps_profile_leverage_cap_maps_to_max_leverage() -> None:
    cap = caps(prof={"max_leverage_cap": D(3)}).caps["max_leverage"]
    assert (cap.limit, cap.source) == (D(3), CapSource.PROFILE)


def test_resolve_caps_policy_warn_is_a_threshold_apart_from_the_blocking_limit() -> None:
    bb = {"max_open_positions": "warn", "max_leverage": "flatten", "max_daily_loss_usd": "warn"}
    c = caps(
        pol={"breach_behaviour": bb, "max_open_positions": 2},
        prof={"max_leverage_cap": D(3), "max_open_positions": 3},
    )
    # The warn policy limit never enters the blocking minimum: the profile's 3 blocks.
    blocking, warn = c.caps["max_open_positions"], c.warn_limits["max_open_positions"]
    assert (blocking.limit, blocking.source, blocking.behaviour) == (
        D(3),
        CapSource.PROFILE,
        "block",
    )
    assert (warn.limit, warn.source, warn.behaviour) == (D(2), CapSource.POLICY, "warn")
    assert "max_daily_loss_usd" not in c.caps  # only the policy sets it, as a warn threshold
    assert c.caps["max_leverage"].behaviour == "block"  # profile binds: always block
    assert c.caps["max_total_notional_usd"].behaviour == "block"  # no key: block
    assert caps(pol={"breach_behaviour": bb}).caps["max_leverage"].behaviour == "flatten"


def test_request_cannot_raise_any_cap() -> None:  # SR-E39-03 (slice 1: the gate's input type)
    # The order the gate judges carries no cap: limits come only from `resolve_caps`' layers.
    assert not {f.name for f in fields(RiskOrder)} & set(caps().caps)


def test_cap_source_labels() -> None:
    assert [s.label for s in CapSource] == [
        "the manager override",
        "the account profile",
        "the global risk policy",
    ]


_limits = st.one_of(st.none(), st.decimals(min_value=1, max_value=10**9, places=6))
_behaviours = st.sampled_from(["warn", "block", "flatten"])


@given(
    mgr=_limits,
    prof=_limits,
    pol=st.decimals(min_value=0, max_value=10**9, places=6),
    behaviour=_behaviours,
)
def test_override_never_widens_a_cap(  # SR-E39-03
    mgr: Decimal | None, prof: Decimal | None, pol: Decimal, behaviour: str
) -> None:
    c = resolve_caps(
        policy(max_daily_loss_usd=pol, breach_behaviour={"max_daily_loss_usd": behaviour}),
        profile(max_daily_loss_usd=prof),
        ManagerCaps(max_daily_loss_usd=mgr),
    )
    blocking = [v for v in (mgr, prof) if v is not None] + ([pol] if behaviour != "warn" else [])
    resolved = c.get("max_daily_loss_usd")
    assert (resolved and resolved.limit) == (min(blocking) if blocking else None)
    warn = c.warn_limit("max_daily_loss_usd")
    assert (warn and warn.limit) == (pol if behaviour == "warn" else None)
