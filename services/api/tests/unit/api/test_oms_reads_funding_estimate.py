"""E24-S03 (#778) serving slice: `Position.funding_estimate` on `listPositions` / `getPosition`
(22 `FundingEstimate`; 24 §19.110; ruling 6612964585 Q3/Q4), on the fakes of
`oms_reads_world.py` with the recorded BTCUSDT ticker (`ws/recorded_tickers_BTCUSDT.jsonl`, its
first frame, a full snapshot: mark 82751.20, rate 0.0000771). §19.110's two named cases: a Manager
reading an unassigned account's position, and a caller without `positions:read`."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import jsonschema
import pytest

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.exchange.base.models import TickerEvent
from candleviewer.exchange.bybit.ticker import parse_ticker_frame
from candleviewer.ingestion.ticker_stream import TickerMerger
from tests._tickers import DATA, FRAMES
from tests.unit.api.oms_reads_world import (
    ACCOUNT_A,
    ACCOUNT_B,
    World,
    bearer,
    position,
    viewing_as,
)

_INGEST_US = 1_792_391_746_500_000  # 271 ms after the recorded frame's `ts`


def _recorded_ticker() -> TickerEvent:
    delta = parse_ticker_frame(FRAMES[0])
    assert delta is not None
    event = TickerMerger().apply(delta, ts_ingest_us=_INGEST_US)
    assert event is not None
    return event


class _Tickers:
    """The recorded BTCUSDT ticker only, `drop` fields set to None; every read counted."""

    def __init__(self, *drop: str) -> None:
        self.event = _recorded_ticker().model_copy(update=dict.fromkeys(drop))
        self.asked: list[str] = []

    def __call__(self, symbol: str) -> TickerEvent | None:
        self.asked.append(symbol)
        return self.event if symbol == "BTCUSDT" else None


async def _get(world: World, path: str, who: str = "owner", **params: Any) -> Any:
    async with world.client() as client:
        return await client.get(path, params=params, headers=bearer(who))


def _by_id(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in body["items"]}


_A1, _B2, _A3, _A5 = (str(position(n, ACCOUNT_A).id) for n in (1, 2, 3, 5))


async def test_a_position_carries_the_server_computed_charge_from_the_recorded_ticker() -> None:
    world = World(tickers=_Tickers())
    body = (await _get(world, "/positions", open_only="false")).json()
    found = _by_id(body)
    assert DATA["markPrice"] == "82751.20" and DATA["fundingRate"] == "0.0000771"
    assert found[_A1]["funding_estimate"] == {  # long 0.200: 0.2 x 82751.20 x 0.0000771
        "amount": "1.27602350", "direction": "pay", "funding_rate": "0.0000771",
        "settles_at": "2026-10-19T08:00:00.000000Z",
        "computed_at": "2026-10-19T06:35:46.500000Z",
    }  # fmt: skip
    short = found[_B2]["funding_estimate"]  # short 0.100 on B
    assert (short["direction"], short["amount"]) == ("receive", "0.63801175")


async def test_no_charge_is_null_never_a_zero() -> None:
    body = (await _get(World(tickers=_Tickers()), "/positions", open_only="false")).json()
    found = _by_id(body)
    assert found[_A3]["side"] == "flat" and found[_A3]["funding_estimate"] is None
    # No SOLUSDT ticker is held at all (none is recorded), so neither mark nor rate is.
    assert found[_A5]["symbol"] == "SOLUSDT" and found[_A5]["funding_estimate"] is None


@pytest.mark.parametrize("missing", ["mark_price", "funding_rate", "next_funding_time"])
async def test_a_ticker_without_its_mark_rate_or_settlement_time_is_no_charge(
    missing: str,
) -> None:
    """The BTCUSDT ticker is held, but without one of the three values the estimate needs."""
    tickers = _Tickers(missing)
    assert getattr(tickers.event, missing) is None
    world = World(tickers=tickers)
    listed = _by_id((await _get(world, "/positions")).json())
    assert listed[_A1]["funding_estimate"] is None and tickers.asked
    shown = (await _get(world, f"/positions/{_A1}")).json()
    assert shown["funding_estimate"] is None


async def test_get_position_carries_the_same_estimate_as_the_list() -> None:
    world = World(tickers=_Tickers())
    listed = _by_id((await _get(world, "/positions")).json())
    shown = (await _get(world, f"/positions/{_A1}", "viewer")).json()
    assert shown["funding_estimate"] == listed[_A1]["funding_estimate"]


async def test_a_manager_reading_an_unassigned_accounts_position_gets_no_estimate() -> None:
    """§19.110: the read's scope refusal holds and no estimate is computed or leaked."""
    tickers = _Tickers()
    world = World(tickers=tickers)
    answer = await _get(world, f"/positions/{_B2}", "manager")
    assert (answer.status_code, answer.json()["code"]) == (404, "not_found")
    assert "funding_estimate" not in answer.text and tickers.asked == []
    assert world.audit.actions() == ["rbac.denied"]
    listed = await _get(world, "/positions", "manager", exchange_account_ids=[str(ACCOUNT_B)])
    assert (listed.status_code, listed.json()["code"]) == (403, "account_scope_denied")
    assert tickers.asked == []


async def test_a_manager_sees_the_estimate_on_the_assigned_account_only() -> None:
    world = World(tickers=_Tickers())
    body = (await _get(world, "/positions", "manager", open_only="false")).json()
    assert {item["exchange_account_id"] for item in body["items"]} == {str(ACCOUNT_A)}
    assert _by_id(body)[_A1]["funding_estimate"]["amount"] == "1.27602350"


async def test_the_owner_viewing_as_a_manager_gets_estimates_in_the_viewed_scope_only() -> None:
    """C-12.4 under view-as (L2): with the Owner's live view bound, the read answers as the
    Manager (the session resolves to the target, as in `test_oms_reads_route.py`), so B's positions
    are absent from the list (not merely estimate-less) and B's position is the scope's 404,
    recorded with the Owner as its actor."""
    tickers = _Tickers()
    world = World(tickers=tickers, viewing=viewing_as("manager"))
    body = (await _get(world, "/positions", "manager", open_only="false")).json()
    assert {item["exchange_account_id"] for item in body["items"]} == {str(ACCOUNT_A)}
    assert str(ACCOUNT_B) not in json.dumps(body)
    found = _by_id(body)
    assert found[_A1]["funding_estimate"]["amount"] == "1.27602350"
    assert all("funding_estimate" in item for item in body["items"])
    tickers.asked.clear()
    answer = await _get(world, f"/positions/{_B2}", "manager")
    assert (answer.status_code, answer.json()["code"]) == (404, "not_found")
    assert "funding_estimate" not in answer.text and tickers.asked == []
    [record] = world.audit.emitted
    assert record["action"] == "rbac.denied" and record["actor_label"] == "user:owner"


async def test_a_caller_without_positions_read_is_refused_and_no_ticker_is_read() -> None:
    tickers = _Tickers()
    world = World(tickers=tickers)
    for path in ("/positions", f"/positions/{_A1}"):
        answer = await _get(world, path, "bare")
        assert (answer.status_code, answer.json()["code"]) == (403, "forbidden")
    assert tickers.asked == []


async def test_with_no_ticker_source_composed_the_member_is_absent() -> None:
    body = (await _get(World(), "/positions")).json()
    assert all("funding_estimate" not in item for item in body["items"])


async def test_the_served_positions_conform_to_22_and_the_generated_model() -> None:
    spec: Any = load_openapi_spec()
    body = (await _get(World(tickers=_Tickers()), "/positions", open_only="false")).json()
    schema = {"$ref": "#/components/schemas/Position", "components": spec["components"]}
    for item in body["items"]:
        jsonschema.validate(item, schema)
        model = api.Position.model_validate(item)
        if model.funding_estimate is not None:
            assert Decimal(model.funding_estimate.amount) >= 0
