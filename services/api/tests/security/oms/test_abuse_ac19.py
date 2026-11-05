"""E29-X02 (#982), AC-19 of the E29 threat model (`docs/security/threat-models/E29-oms.md` section
8.2): a burst of orders from one session, through the routes `create_app()` serves, in a world of
this module's own whose admitted entries reach the venue and a `202` (`oms_world`'s `submits`),
with `trading.oms_enabled` on at the route. Its world is this module's alone: B1's ports are one
per process, so it cannot run beside the suite's module world (`conftest.py`). The per-user limit
is a strict xfail naming its owner and its accepted-risk record, X02-R4, in
`docs/security/abuse-cases/e29-oms.md` (BQ-5 as ruled). No network, no sleeps (C-13.5, C-13.7).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import ExitStack
from decimal import Decimal
from typing import Any, Final

import pytest

from candleviewer.api import position_close
from candleviewer.statechart.bindings import b16_session
from tests.contract.rbac.rbac_harness import FOREIGN, GRANTED, observed
from tests.security.oms._world import OmsWorld, oms_world
from tests.security.oms.test_abuse_cases import _PER_USER, M, call

#: One past the position writes' per-user rate, the shipped rate the order routes are pinned to.
_BURST: Final = position_close.RATE_PER_MINUTE + 1
#: A resting limit buy on M's account with its native stop (C-2.6), sized so the burst stays in
#: the profile's caps; the other user's order is the Owner's, on the Owner's own account.
_STOP: Final = Decimal("58900")
_ENTRY: Final = {
    "exchange_account_id": str(GRANTED), "symbol": "BTCUSDT", "side": "buy",
    "order_type": "limit", "price": "59000", "sizing": {"mode": "fixed_qty", "qty": "0.001"},
    "reduce_only": False, "stop_loss": {"unit": "price", "value": str(_STOP)},
}  # fmt: skip
_OTHER: Final = _ENTRY | {"exchange_account_id": str(FOREIGN)}
_LATE: Final = {"headers": {"Idempotency-Key": "not-a-key"}}


@pytest.fixture(scope="module")
def submitting(_live_guard: None, tmp_path_factory: pytest.TempPathFactory) -> Iterator[OmsWorld]:
    """The module's world, `trading.oms_enabled` on at the route (its flag view read on), so an
    entry passes step 9 of `api/orders.py`. A world that cannot start is a `RuntimeError`, never
    an `AssertionError` the pin's xfail would take for its own."""
    with ExitStack() as stack:
        try:
            world = stack.enter_context(oms_world(tmp_path_factory.mktemp("bars"), submits=True))
        except AssertionError as exc:
            raise RuntimeError(f"the AC-19 world did not start: {exc}") from exc
        mp = stack.enter_context(pytest.MonkeyPatch.context())
        mp.setattr(world.app.state.feature_flags.oms_enabled, "value", True)
        yield world


@pytest.fixture
def world(submitting: OmsWorld, b16_audit: object) -> OmsWorld:
    """The module's world, its audit index emptied; B16's records land in its audit too."""
    submitting.reset()
    b16_session.set_audit_sink(submitting.pack.audit)
    return submitting


def _sent(world: OmsWorld, account: uuid.UUID) -> list[Any]:
    """Every create the venue took for `account`."""
    return [c.request for port in world.oms.venue.ports for c in port.calls
            if c.method == "place_order" and c.account_id == account]  # fmt: skip


def _burst(world: OmsWorld, name: str, shape: str) -> list[tuple[Any, list[tuple[str, Any]]]]:
    """`_BURST` requests of `shape` from M's one session, each answered with its records."""
    late = _LATE if shape == "refused_late" else {}
    return [call(world, M, "POST", "/orders", f"{name}|{shape}|{n}", json=_ENTRY, **late)
            for n in range(_BURST)]  # fmt: skip


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=_PER_USER.format(
    4, "a burst of orders from one session"))  # fmt: skip
@pytest.mark.parametrize("shape", ["entry", "refused_late"])
def test_ac19_a_burst_of_orders_from_one_session_meets_a_429_and_another_user_is_admitted(
    world: OmsWorld, shape: str
) -> None:
    """AC-19 and the rows posted on #982 on 2026-10-23 and 2026-10-24: a burst from one session,
    of entries or of requests refused late (a malformed `Idempotency-Key`, step 6), meets `429
    rate_limited` with `Retry-After`; every entry it admitted went out with its native stop
    (C-2.6), and another user's order is still admitted, `202`. The limit is expected per user
    between step 2 (`enforce`) and step 3 (the runtime) of `api/orders.py`, as the position
    writes' limiter stands after their `enforce`: before step 6, so both shapes meet it. With
    `trading.oms_enabled` on, an entry reaches step 12's submit, so a limit anywhere on its path
    turns this pin XPASS."""
    sent = len(_sent(world, GRANTED))
    answers = [r for r, _ in _burst(world, "ac19", shape)]
    limited = [r for r in answers if observed(r) == "429 rate_limited"]
    assert limited and all(r.headers.get("Retry-After") for r in limited), {
        observed(r) for r in answers}  # fmt: skip
    admitted = _sent(world, GRANTED)[sent:]
    assert len(admitted) == sum(r.status_code == 202 for r in answers)
    assert all(o.stop_loss == _STOP and not o.reduce_only for o in admitted), admitted
    other, _ = call(world, "owner", "POST", "/orders", f"ac19|{shape}|other", json=_OTHER)
    assert observed(other) == "202", other.text


#: What the burst meets on `main` today, step by step of `api/orders.py`, with
#: `trading.oms_enabled` on: an entry passes every step and is sent (step 12), a malformed key
#: stops at step 6 (`Idempotency-Key`). Each answer with the records written under its id.
_TODAY: Final = {
    "entry": ("202", (("orders.submit", "submitted"), ("orders.submit", "validated"),
                      ("trade_group.submit", "submitting"))),
    "refused_late": ("400 validation_failed", (("orders.submit", "validation_failed"),)),
}  # fmt: skip


@pytest.mark.parametrize("shape", list(_TODAY))
def test_ac19_the_burst_meets_today_the_step_its_pin_stands_before(
    world: OmsWorld, shape: str
) -> None:
    """X02-R4's non-vacuity, in the pin's own world: its burst reaches the route and is answered,
    each request alike and audited, at the step named here and never `429`; each entry is sent
    with its native stop (C-2.6), and the other user's order is `202`. A per-user limit at or
    before that step changes this test as it turns the pin XPASS."""
    sent = len(_sent(world, GRANTED))
    seen = {(observed(r), tuple(sorted(w))) for r, w in _burst(world, "ac19-today", shape)}
    assert seen == {_TODAY[shape]}, seen
    admitted = _sent(world, GRANTED)[sent:]
    assert len(admitted) == (_BURST if shape == "entry" else 0)
    assert all(o.stop_loss == _STOP and not o.reduce_only for o in admitted), admitted
    other, _ = call(world, "owner", "POST", "/orders", f"ac19-today|{shape}|other", json=_OTHER)
    assert observed(other) == "202", other.text
