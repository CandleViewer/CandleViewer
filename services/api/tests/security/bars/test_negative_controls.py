"""E12-X02 negative controls (#452 DoD: "each defence fails when removed"): every defended outcome
of `test_caps_and_cost` and `test_authz_and_revocation`, run again with its defence removed by a
monkeypatch, must turn red. A control that stays green means the case no longer tests its
defence. Each patch is applied before the app is built, since the routes bind some constants
(`Query(le=MAX_LIMIT)`) at build.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

import pytest

from candleviewer.api import market, market_bars
from candleviewer.api.market import MarketDataPrincipal
from candleviewer.bars import spec
from tests.contract import _market_world as mw
from tests.security.bars import test_authz_and_revocation as authz
from tests.security.bars import test_caps_and_cost as caps
from tests.security.bars.conftest import Stores

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


_CONTROLS: Final[list[tuple[Callable[[pytest.MonkeyPatch], None], Callable[[Stores], None]]]] = [
    (_no_limit_cap, caps.check_limit_over_max_refused),
    (_no_tick_floor, caps.check_tick_1_refused_before_any_read),
    (_no_time_window_cap, caps.check_time_window_cap),
    (_no_non_time_window_cap, caps.check_non_time_window_cap),
    (_no_estimate_cap, caps.check_time_estimate_cap),
    (_no_estimate_cap, caps.check_estimate_cap),
    (_everyone_holds_every_permission, lambda s: authz.check_forbidden(s, "getBars")),
    (_everyone_holds_every_permission, lambda s: authz.check_forbidden(s, "getKlines")),
    (_no_session_check, lambda s: authz.check_unauthenticated(s, "getBars")),
    (_no_session_check, lambda s: authz.check_unauthenticated(s, "getKlines")),
]


@pytest.mark.parametrize(
    ("remove", "check"), _CONTROLS, ids=[f"{r.__name__}-{i}" for i, (r, _) in enumerate(_CONTROLS)]
)
def test_negative_control_case_fails_with_its_defence_removed(
    stores: Stores,
    monkeypatch: pytest.MonkeyPatch,
    remove: Callable[[pytest.MonkeyPatch], None],
    check: Callable[[Stores], None],
) -> None:
    remove(monkeypatch)
    with pytest.raises(AssertionError):
        check(stores)
