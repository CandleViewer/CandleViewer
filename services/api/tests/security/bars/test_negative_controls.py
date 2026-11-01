"""E12-X02 negative controls (#452 DoD: "each defence fails when removed"): every defended outcome
of `test_caps_and_cost`, `test_deadlines` and `test_authz_and_revocation`, run again with its
defence removed by a monkeypatch, must turn red, and red for the reason named (`match=`): the
answer the removal lets through. A control that stays green means the case no longer tests its
defence. The deadline control lifts SR-E12-01's 2 s to an hour; the revocation control skips
`roles_changed`. Each patch is applied before the app is built, since the routes bind some
constants (`Query(le=MAX_LIMIT)`) at build.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Final

import httpx
import pytest

from candleviewer.api import market, market_bars, market_response
from candleviewer.api.market import MarketDataPrincipal
from candleviewer.bars import spec
from tests.contract import _market_world as mw
from tests.security.bars import _oracle
from tests.security.bars import test_authz_and_revocation as authz
from tests.security.bars import test_caps_and_cost as caps
from tests.security.bars import test_deadlines as deadlines
from tests.security.bars.conftest import BAR_READ, Stores, hang
from tests.unit.audit.audit_waits import virtual

_HUGE: Final = 10**18


def _no_limit_cap(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(market_bars, "MAX_LIMIT", _HUGE)
    mp.setattr(market, "MAX_LIMIT", _HUGE)


def _no_tick_floor(mp: pytest.MonkeyPatch) -> None:
    mp.setitem(spec._PARAM_BOUNDS, "tick", (1, 1_000_000))


def _no_time_window_cap(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(market_bars, "MAX_TIME_WINDOW_US", _HUGE)


def _no_non_time_window_cap(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(market_bars, "MAX_NON_TIME_WINDOW_US", _HUGE)


def _no_estimate_cap(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(market_bars, "MAX_WINDOW_BARS", _HUGE)


def _everyone_holds_every_permission(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(MarketDataPrincipal, "has", lambda self, permission: True)


def _no_session_check(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(
        mw.Resolver, "resolve", lambda self, request: MarketDataPrincipal("x", frozenset({"*"}))
    )


def _no_response_ceiling(mp: pytest.MonkeyPatch) -> None:
    """The ceiling the probe page meets is lifted: `kline_response` reads it per call."""

    @contextmanager
    def lifted(_max_bytes: int | None) -> Iterator[None]:
        with pytest.MonkeyPatch.context() as inner:
            inner.setattr(market_response, "RESPONSE_MAX_BYTES", _HUGE, raising=True)
            yield

    mp.setattr(caps, "response_ceiling", lifted, raising=True)


#: The served answer each removal lets through, in the check's own assertion message.
_SERVED: Final = r"\(200, None\) == "
_Check = Callable[[Stores], None]
_CONTROLS: Final[list[tuple[Callable[[pytest.MonkeyPatch], None], _Check, str]]] = [
    (_no_limit_cap, caps.check_limit_over_max_refused, r"assert 200 in \(400, 422\)"),
    # Floor gone, `tick:1` reaches the recording start and is refused later, for its window.
    (_no_tick_floor, caps.check_tick_1_refused_before_any_read, "no_data_recorded"),
    (_no_time_window_cap, caps.check_time_window_cap, _SERVED),
    (_no_non_time_window_cap, caps.check_non_time_window_cap, _SERVED),
    (_no_estimate_cap, caps.check_time_estimate_cap, _SERVED),
    (_no_estimate_cap, caps.check_estimate_cap, _SERVED),
    (_no_response_ceiling, caps.check_response_ceiling, _SERVED),
    # The bars query is also `tick:1`: past authz it meets the param floor (400).
    (_everyone_holds_every_permission, lambda s: authz.check_forbidden(s, "getBars"),
     r"\(400, 'validation_failed'\) == \(403, 'forbidden'\)"),
    (_everyone_holds_every_permission, lambda s: authz.check_forbidden(s, "getKlines"), _SERVED),
    (_no_session_check, lambda s: authz.check_unauthenticated(s, "getBars"),
     r"\(400, 'validation_failed'\) == \(401, 'unauthenticated'\)"),
    (_no_session_check, lambda s: authz.check_unauthenticated(s, "getKlines"), _SERVED),
]  # fmt: skip


@pytest.mark.parametrize(
    ("remove", "check", "match"),
    _CONTROLS,
    ids=[f"{r.__name__}-{i}" for i, (r, _, _) in enumerate(_CONTROLS)],
)
def test_negative_control_case_fails_with_its_defence_removed(
    stores: Stores,
    monkeypatch: pytest.MonkeyPatch,
    remove: Callable[[pytest.MonkeyPatch], None],
    check: _Check,
    match: str,
) -> None:
    remove(monkeypatch)
    with pytest.raises(AssertionError, match=match):
        check(stores)


@virtual
async def test_negative_control_deadline_removed_hangs_to_the_guard(
    stores: Stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SR-E12-01's deadline lifted to an hour: the hung bar read now outlives the guard (fake
    seconds, `@virtual`)."""
    monkeypatch.setattr(market_bars, "QUERY_TIMEOUT_S", 3_600.0, raising=True)
    stores.faults[BAR_READ] = hang
    query = {**deadlines.BARS, "bar_type": "time", "param": "1"}
    with pytest.raises(pytest.fail.Exception, match="still running after the"):
        await deadlines.assert_unavailable(stores, "getBars", query, BAR_READ)


def test_negative_control_without_revocation_the_update_arrives(wire: str) -> None:
    """The revocation case's "no `d` after" is not vacuous: unrevoked, the same update is a `d`
    that arrives before the `pong`."""
    frames = authz.run_revocation(revoke=False).frames
    assert "d" in [f["t"] for f in frames], [f["t"] for f in frames]


_PROBE: Final = "P" * 40  # longer than the oracle's echo bound
_PROBLEM: Final = {"code": "validation_failed", "status": 400}
#: `(query, a fabricated answer, the oracle rule it breaks)`: each oracle rule fires on its own
#: input, so a known gap's `raises=` names a rule that can fail, never one that is inert.
_BROKEN: Final = [
    ({}, httpx.Response(500, json={"code": "internal_error", "status": 500}), _oracle.StatusError),
    ({}, httpx.Response(400, json={"code": "made_up", "status": 400}), _oracle.StatusError),
    ({}, httpx.Response(400, json={**_PROBLEM, "detail": "Traceback (most recent call last)"}),
     _oracle.LeakError),
    ({}, httpx.Response(400, json={**_PROBLEM, "detail": 'File "/srv/x.py", line 1'}),
     _oracle.LeakError),
    ({"param": _PROBE}, httpx.Response(400, json={**_PROBLEM, "detail": _PROBE}),
     _oracle.LeakError),
    ({"from": "2020-01-01T00:00:00Z", "to": "2022-01-01T00:00:00Z", "bar_type": "time",
      "param": "D"}, httpx.Response(200, json={"bars": []}), _oracle.SpanCapError),
]  # fmt: skip


@pytest.mark.parametrize(("query", "resp", "rule"), _BROKEN)
def test_negative_control_oracle_rule_fires_on_its_input(
    query: dict[str, object], resp: httpx.Response, rule: type[_oracle.OracleError]
) -> None:
    with pytest.raises(rule):
        _oracle.check("getBars", query, resp)
