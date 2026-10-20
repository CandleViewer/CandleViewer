"""#2191: range:20 / delta:500 compose a live builder set through the PRODUCTION wiring.

Deviation, stated explicitly: `GET /market/bars` reads only the stored `bars_*` tables
(`BarReader`); the live `BarBuilderSet` is a separate write path (trades -> set -> writer ->
table). So the route cannot be made to read from the set. The composition is asserted at the
boundary the route's data depends on: `wire_bars` (the function `create_app` calls) builds the
set with `production_factory`, and registering the specs the route accepts must yield live
range/delta builders on the lane. Reverting `bars_wiring` to `default_factory` fails this test
(range raises `BarSpecError`). The route is then shown to serve those same specs.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from candleviewer.api.market_bars import parse_bar_request
from candleviewer.app import build_app_context
from candleviewer.bars_wiring import wire_bars
from candleviewer.settings import Environment, Settings
from tests.contract.test_market_bars_contract import _P, _client
from tests.unit.bars._trades import SYM


@pytest.mark.parametrize(("bar_type", "param"), [("range", "20"), ("delta", "500")])
async def test_market_bars_range_and_delta_compose_a_live_builder_set(
    bar_type: str, param: str, tmp_path: Path
) -> None:
    settings = Settings(
        environment=Environment.DEMO,
        git_sha="deadbeef",
        version="9.9.9",
        bars_enabled=False,  # renko flag off: range/delta must not depend on it
        bars_state_root=str(tmp_path / "bars"),
        metrics_enabled=False,
    )
    ctx = build_app_context(settings)
    runtime = wire_bars(ctx, now_us=lambda: 0, tick_size=lambda _s: Decimal("0.1"))
    spec = parse_bar_request(bar_type, param, qty_step=Decimal("0.001"))
    await runtime.builder_set.register(spec, SYM, "c1")
    lane = runtime.builder_set._lanes[SYM]
    assert [e.spec.kind for e in lane.entries] == [bar_type]
    resp = _client().get("/market/bars", params={**_P, "bar_type": bar_type, "param": param})
    assert resp.status_code == 200, resp.text
    await runtime.builder_set.stop()
