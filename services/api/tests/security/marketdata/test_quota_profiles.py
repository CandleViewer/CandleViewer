"""E21-X02 (#652; BQ-12): the quota against two load profiles, driven through the real admission
path (the `/ws` router, real sessions) and deterministic: no refusal under the realistic peak, and
the budgeted refusals under AC-HM-10's worst case. The k6 runs stay E21-Q03's (#698), which watches
`cv_ws_subscription_quota_rejections_total`.

The realistic peak (E21-Q03's text and 23 §16.3's reference workspace): 5 users on 10 recorded
symbols, each user with the reference panes (a 1 m chart, a 5 m footprint, a depth-50 DOM and the
tape) on every symbol, and SCR-050 open on 2 of them, a `book.{s}.200` and a `heatmap.{s}` at its
defaults. Each profile states the points a connection and a user hold, as the ledgers show them."""

from __future__ import annotations

from contextlib import ExitStack

from tests.security.marketdata.conftest import QuotaWorld
from tests.security.marketdata.test_quota_abuse import (
    HEAVY,
    SYMBOLS,
    codes,
    counted,
    deep_flood,
    results,
    socket,
)

TEN = SYMBOLS[:10]
USERS = 5


def reference_panes(symbol: str) -> list[str]:
    """23 §16.3's reference workspace on `symbol`."""
    return [f"bars.{symbol}.time.1", f"footprint.{symbol}.time.5", f"book.{symbol}.50",
            f"trades.{symbol}"]  # fmt: skip


def test_realistic_peak_is_never_refused(world: QuotaWorld) -> None:
    users = [world.login(f"trader{n}") for n in range(USERS)]
    seen = counted("points_connection", "points_user", "heatmap_connection", "heatmap_user")
    with ExitStack() as stack:
        for n, user in enumerate(users):
            c = stack.enter_context(socket(world, user))
            panes = [t for s in TEN for t in reference_panes(s)]
            heatmapped = TEN[2 * n : 2 * n + 2]  # SCR-050 on two symbols, the defaults
            scr_050 = [t for s in heatmapped for t in (f"book.{s}.200", f"heatmap.{s}")]
            assert codes(results(c, *panes)) == [None] * len(panes)
            assert codes(results(c, *scr_050)) == [None] * len(scr_050)
            # one connection: 2 x (a default heatmap's 13 points + a deep book's 1)
            assert world.held(user) == (28, 2, 2)
        assert world.heatmap._points == USERS * 2 * 13  # each a spec of its own
    assert all(read() == 0 for read in seen.values())


def test_worst_case_is_refused_where_the_budgets_say(world: QuotaWorld) -> None:
    """AC-HM-10's profile, 8 sockets of one user: each socket holds at most 200 points and the
    user at most 400; past them each entry is refused, and the deep books on top fit until the
    deep-book cap."""
    alice = world.login("alice")
    seen = counted("points_connection", "points_user", "deep_book_connection")
    sockets = deep_flood(world, alice)
    held = [sum(1 for code in got[:40] if code is None) for got in sockets]
    assert held == [1, 1, 0, 0, 0, 0, 0, 0]  # 160 points a socket: two sockets, 320 of 400
    assert (seen["points_connection"](), seen["points_user"]()) == (78, 240)
    assert seen["deep_book_connection"]() == 8
    with socket(world, alice) as c:  # the flood's sockets are closed: the whole budget is back
        assert world.held(alice) == (0, 0, 0)
        assert codes(results(c, *(dict(ch=f"heatmap.{s}", opts=HEAVY) for s in TEN[:2]))) == [
            None, "subscription_limit"
        ]  # fmt: skip
