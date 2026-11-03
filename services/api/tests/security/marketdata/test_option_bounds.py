"""E21-X02 (#652; the model's G-16, AC-HM-08's WS half; E21-Q01's boundary table): the live
heatmap's option bounds, at their edges, through the real `/ws` router (`conftest.py`, under both
subprotocols, `heatmap_depth_500` on). Each option at its bound is served, and one step past it is
refused `invalid_options` naming that option, with nothing held: the bounds are 23 §6.1's, read
from the topic registry (`ws/topics.py`), not restated."""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.ws.topics import DEPTHS, FAMILIES
from tests.security.marketdata.conftest import QuotaWorld
from tests.security.ws._raw import answers, authenticated, raw_connect
from tests.unit.ws._seq_support import ACC_A

_OPTIONS = FAMILIES["heatmap"].options
_WINDOW, _GROUPING = _OPTIONS["window_seconds"], _OPTIONS["price_grouping"]
#: (option, value, served): each bound, and one step past it on either side.
CASES: list[tuple[str, int, bool]] = [
    ("window_seconds", 900, True),
    ("window_seconds", 901, False),
    ("window_seconds", 10, True),
    ("window_seconds", 9, False),
    *(("depth", d, True) for d in sorted(DEPTHS)),
    ("depth", 0, False),
    ("depth", 2, False),
    ("depth", 501, False),
    ("price_grouping", 1, True),
    ("price_grouping", 1000, True),
    ("price_grouping", 0, False),
    ("price_grouping", 1001, False),
]


def test_the_cases_are_the_registrys_bounds() -> None:
    """The table holds 23 §6.1's numbers as the registry enforces them, so it cannot drift."""
    assert sorted(DEPTHS) == [1, 50, 200, 500]
    assert (_WINDOW.lo, _WINDOW.hi, _GROUPING.lo, _GROUPING.hi) == (10, 900, 1, 1000)


@pytest.mark.parametrize(
    ("option", "value", "served"), CASES, ids=[f"{o}={v}" for o, v, _ in CASES]
)
def test_g16_an_option_at_its_bound_is_served_and_one_past_it_is_refused(
    world: QuotaWorld, option: str, value: int, served: bool
) -> None:
    entry: dict[str, Any] = {"ch": "heatmap.BTCUSDT", "opts": {option: value}}
    with raw_connect(world) as c:
        authenticated(c, world.login("alice", ACC_A))
        (result,) = answers(c, entry)
    if served:
        assert result["ok"] is True, result
        assert result["effective"][option] == value
    else:
        assert result["ok"] is False and result["error"]["code"] == "invalid_options", result
        assert result["error"].get("field") == option
        assert world.held(world.login("alice", ACC_A)) == (0, 0, 0)  # nothing was charged
