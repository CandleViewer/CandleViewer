"""E29-S06 (#981) S1, contract first (C-6.1): closed positions and today's realised PnL.

The orchestrator's ruling of 2026-11-03 (08:03Z), as the four plan documents state it:

- 22 `listClosedPnl` stays the one operation on `/executions/closed-pnl`, with `window=today`, the
  FilterBar's filters (`symbol` and `trade_group_id` repeatable, `side`), and `meta.window` and
  `meta.totals` on a window read. Items are oldest first with `window` and newest first without it,
  pinned both ways.
- Every member E29-S06 adds to `ClosedPnl` is optional, so the per-fill stand-in served today still
  validates. The example's ids are 24 Sec.8.13's uuid5, and its totals sum its items' `net_pnl`.
- The day boundary is `risk_policy.day_boundary_utc_offset_minutes`, east-positive: 22 bounds
  `utc_offset_minutes` as 21's `rp_day` bounds the column.
- 24 gives the adapter's `ClosedPnl` its `exchange_order_id` and the empty-orderId rule, the strict
  relative 1e-8 tolerance, unvalidated until #843, and `pnl.divergence_detected` (Sec.15.5). 20
  lists the tolerance and the two metrics, and 21 the record table.

Nothing serves the new members yet: E29-S06's later slices implement them against this contract.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid5

import pytest
from jsonschema import Draft202012Validator

from candleviewer.api._generated import openapi_models as api
from candleviewer.audit.actions import AUDIT_ACTIONS
from tests.contract._generated_contract import _REGISTRY, _URI, SPEC

_PLAN: Final = Path(__file__).resolve().parents[4] / "docs" / "plan"
_SCHEMAS: Final[dict[str, Any]] = SPEC["components"]["schemas"]
_OPERATION: Final[dict[str, Any]] = SPEC["paths"]["/executions/closed-pnl"]["get"]
_OK: Final = "#/paths/~1executions~1closed-pnl/get/responses/200/content/application~1json/schema"
_ADDED: Final = (
    "exchange_order_id", "gross_pnl", "fee_pnl", "funding_pnl", "local_net_pnl", "net_pnl",
    "provisional", "divergent",
)  # fmt: skip
_FIGURES: Final = ("gross_pnl", "fee_pnl", "funding_pnl", "local_net_pnl", "net_pnl")
_TOLERANCE: Final = Decimal("1e-8")


def _doc(name: str) -> str:
    return (_PLAN / name).read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    """The text from `start` to `end` (or to the end), its whitespace collapsed."""
    tail = text[text.index(start) :]
    return " ".join(tail[: tail.index(end) if end in tail else len(tail)].split())


def _ok_errors(body: object) -> list[str]:
    validator = Draft202012Validator(
        {"$ref": f"{_URI}{_OK}"},
        registry=_REGISTRY,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    return [error.message for error in validator.iter_errors(body)]


def _example() -> dict[str, Any]:
    content = _OPERATION["responses"]["200"]["content"]["application/json"]
    return dict(content["examples"]["today"]["value"])


def test_contract_closed_pnl_is_served_by_one_operation_of_the_executions_family() -> None:
    """Extended, not paralleled: one operation answers `ClosedPnl`, with the family's RBAC."""
    ref = '"#/components/schemas/ClosedPnl"'
    users = [
        (path, method)
        for path, item in SPEC["paths"].items()
        for method, operation in item.items()
        if isinstance(operation, dict) and ref in json.dumps(operation)
    ]
    assert users == [("/executions/closed-pnl", "get")]
    assert _OPERATION["operationId"] == "listClosedPnl"
    assert _OPERATION["x-rbac"] == {"permissions": ["executions:read"], "scope": "granted_accounts"}


def test_contract_list_closed_pnl_takes_the_window_and_the_filter_chips() -> None:
    params = {p.get("name", p.get("$ref")): p for p in _OPERATION["parameters"]}
    for shared in ("Cursor", "Limit", "AccountIdsQuery", "From", "To"):
        assert f"#/components/parameters/{shared}" in params
    assert params["window"]["schema"] == {"type": "string", "enum": ["today"]}
    assert params["side"]["schema"] == {"$ref": "#/components/schemas/JournalSide"}
    for repeatable in ("symbol", "trade_group_id"):
        assert params[repeatable]["explode"] is True
        assert params[repeatable]["schema"]["type"] == "array"
        assert params[repeatable]["schema"]["maxItems"] == 32
    assert not any(p.get("required") for p in params.values())


def test_contract_list_closed_pnl_pins_the_item_order_both_ways() -> None:
    """Oldest first with `window` (a new close appends, D02 Sec.5.6); newest first without it."""
    text = " ".join(_OPERATION["description"].split())
    assert "With `window`, items are oldest first by `closed_at`, then `id`" in text
    assert "Without it they stay newest first, by `closed_at`, then `id`" in text
    assert "one item per fill, newest first by fill time" in text  # the stand-in, until S6


def test_contract_list_closed_pnl_states_its_window_refusals_and_one_environment() -> None:
    text = " ".join(_OPERATION["description"].split())
    assert "`window` with `from` or `to` is `400 validation_failed`" in text
    assert "`503 store_unavailable`, never a UTC-midnight guess" in text
    assert "shows each one's totals, never one sum" in text
    assert "never a sum of one page" in text


def test_contract_every_added_closed_pnl_member_is_optional() -> None:
    schema = _SCHEMAS["ClosedPnl"]
    assert "required" not in schema
    assert set(_ADDED) <= set(schema["properties"])
    for flag in ("provisional", "divergent"):
        member = schema["properties"][flag]
        assert (member["type"], member["default"]) == ("boolean", False)
    order_id = schema["properties"]["exchange_order_id"]
    assert (order_id["type"], order_id["minLength"], order_id["maxLength"]) == ("string", 1, 64)
    for figure in _FIGURES:
        assert schema["properties"][figure]["$ref"] == "#/components/schemas/Decimal"


def test_contract_a_stand_in_page_still_validates_and_reads_unflagged() -> None:
    """The per-fill item served until E29-S06's route slice carries none of the new members."""
    item = {
        "id": "0e000000-0000-4000-8000-000000000001",
        "exchange_account_id": "a1000000-0000-4000-8000-000000000001",
        "symbol": "BTCUSDT",
        "side": "short",
        "avg_exit_price": "63099.80",
        "closed_pnl": "-6.941",
        "closed_at": "2026-09-14T10:30:11.402Z",
    }
    page = {"items": [item], "meta": {"next_cursor": None, "has_more": False, "count": 1}}
    assert _ok_errors(page) == []
    model = api.ClosedPnl.model_validate(item)
    assert (model.provisional, model.divergent, model.net_pnl) == (False, False, None)


def test_contract_the_window_and_totals_meta_shapes() -> None:
    assert _SCHEMAS["ClosedPnlMeta"]["allOf"][0] == {"$ref": "#/components/schemas/PageMeta"}
    window, totals = _SCHEMAS["ClosedPnlWindow"], _SCHEMAS["ClosedPnlTotals"]
    assert window["required"] == ["start", "next_start", "utc_offset_minutes"]
    assert totals["required"] == ["count", "net_pnl", "provisional", "by_account"]
    by_account = _SCHEMAS["ClosedPnlAccountTotals"]
    assert by_account["required"] == ["exchange_account_id", "count", "net_pnl", "provisional"]
    assert window["additionalProperties"] is totals["additionalProperties"] is False


def test_contract_the_window_offset_is_bounded_as_rp_day_bounds_the_column() -> None:
    (low, high) = re.findall(
        r"CONSTRAINT rp_day\s+CHECK \(day_boundary_utc_offset_minutes BETWEEN (-?\d+) AND (\d+)\)",
        _doc("21-database-schema.md"),
    )[0]
    offset = _SCHEMAS["ClosedPnlWindow"]["properties"]["utc_offset_minutes"]
    assert (offset["minimum"], offset["maximum"]) == (int(low), int(high)) == (-720, 840)


def test_contract_the_example_validates_and_its_figures_add_up() -> None:
    page = _example()
    assert _ok_errors(page) == []
    namespace = UUID(_SCHEMAS["ClosedPnl"]["x-cv-uuid5-namespace"])
    accounts: dict[str, list[dict[str, Any]]] = {}
    for item in page["items"]:
        assert item["id"] == str(
            uuid5(namespace, f"{item['exchange_account_id']}:order:{item['exchange_order_id']}")
        )
        local = [Decimal(item[k]) for k in ("gross_pnl", "fee_pnl", "funding_pnl") if k in item]
        assert Decimal(item["local_net_pnl"]) == sum(local, Decimal(0))
        if item["provisional"]:
            assert "closed_pnl" not in item and Decimal(item["net_pnl"]) == sum(local, Decimal(0))
            assert item["divergent"] is False
        else:
            venue, ours = Decimal(item["closed_pnl"]), Decimal(item["local_net_pnl"])
            assert Decimal(item["net_pnl"]) == venue  # the venue's figure is authoritative
            assert item["divergent"] is (abs(ours - venue) > _TOLERANCE * abs(venue))
        accounts.setdefault(item["exchange_account_id"], []).append(item)
    meta = page["meta"]
    totals = meta["totals"]
    assert totals["count"] == meta["count"] == len(page["items"])
    assert Decimal(totals["net_pnl"]) == sum(
        (Decimal(i["net_pnl"]) for i in page["items"]), Decimal(0)
    )
    assert totals["provisional"] is any(i["provisional"] for i in page["items"])
    assert totals["by_account"] == [
        {
            "exchange_account_id": account,
            "count": len(items),
            "net_pnl": str(sum((Decimal(i["net_pnl"]) for i in items), Decimal(0))),
            "provisional": any(i["provisional"] for i in items),
        }
        for account, items in accounts.items()
    ]
    window = meta["window"]
    start = datetime.fromisoformat(window["start"])
    assert datetime.fromisoformat(window["next_start"]) - start == timedelta(hours=24)
    local_midnight = start + timedelta(minutes=window["utc_offset_minutes"])
    assert (local_midnight.hour, local_midnight.minute, local_midnight.second) == (0, 0, 0)
    closes = [datetime.fromisoformat(i["closed_at"]) for i in page["items"]]
    assert closes == sorted(closes)  # a window read is oldest first
    assert all(start <= at < start + timedelta(hours=24) for at in closes)


def test_contract_24_states_the_day_boundary_once_and_east_positive() -> None:
    text = _between(_doc("24-internal-schemas.md"), "### 8.13 ", "\n## 9. ")
    for claim in (
        "The ticket's key `risk.day_boundary_utc_offset` is the column "
        "`risk_policy.day_boundary_utc_offset_minutes`",
        "one value, never a second constant",
        "the offset, in minutes east of UTC, of the zone whose midnight starts the trading day",
        "\N{MINUS SIGN}720..840 is UTC\N{MINUS SIGN}12..UTC+14",
        "At +180 (UTC+3) the day starts at 21:00:00.000Z of the previous UTC date",
        "the half-open `[day_start, next_start)`",
        "fails closed and never falls back to UTC midnight",
        "is recorded for E39-K01 (#880) to confirm",
        "**`DayRiskFigures` stays demo and testnet only (§9.3.6).** It refuses `live` at "
        "construction until E39-T01 (#881)",
    ):
        assert claim in text, claim


def test_contract_24_composes_the_record_and_bounds_the_comparison() -> None:
    text = _between(_doc("24-internal-schemas.md"), "### 8.13 ", "\n## 9. ")
    namespace = _SCHEMAS["ClosedPnl"]["x-cv-uuid5-namespace"]
    for claim in (
        f'`CLOSED_PNL_NAMESPACE = UUID("{namespace}")`',
        'f"{account_id}:order:{exchange_order_id}"',
        "**The empty-orderId rule:** a record the venue writes with an empty `orderId` has "
        '`exchange_order_id` None, never `""`',
        "`local_net_pnl = gross_pnl + fee_pnl + funding_pnl`, present when all three are",
        "`|local_net_pnl \N{MINUS SIGN} closed_pnl| > "
        "CV_OMS_CLOSED_PNL_TOLERANCE_REL \N{MULTIPLICATION SIGN} |closed_pnl|`: "
        "strictly greater, and relative to the venue's figure",
        "The tolerance is `1e-8`",
        "shipped **unvalidated** until #843",
        "once per record and value pair",
        "in the `poll` lane (`background`, §8.7), never from the stop and cancel reserve",
    ):
        assert claim in text, claim


def test_contract_24_lists_the_adapter_record_with_its_venue_order_id() -> None:
    text = _between(_doc("24-internal-schemas.md"), "### 14.4 ", "\n## 15. ")
    record = text[text.index("class ClosedPnl(BaseModel):") :]
    record = record[: record.index("class AccountInfo")]
    assert "exchange_order_id: str | None = None" in record
    assert 'None, never "", # when the venue writes it empty (counted `no_order_id`)' in record


def test_contract_24_names_the_divergence_action_as_the_registry_holds_it() -> None:
    """In the closed set ahead of its emitter; the note goes when the code registers it."""
    text = _between(_doc("24-internal-schemas.md"), "### 15.5 ", "\n### 15.6 ")
    registered = "pnl.divergence_detected" in AUDIT_ACTIONS
    note = "`pnl.divergence_detected` (not registered yet, E29-S06)"
    assert (note in text) is not registered
    assert "`pnl.divergence_detected` (E29-S06, #981; §8.13)" in text
    assert "once per record and value pair, never on a read" in text


def test_contract_20_lists_the_tolerance_and_the_two_metrics() -> None:
    doc = _doc("20-architecture.md")
    [row] = [
        line for line in doc.splitlines() if line.startswith("| `CV_OMS_CLOSED_PNL_TOLERANCE_REL`")
    ]
    assert [c.strip() for c in row.split("|")[2:5]] == ["float", "`1e-8`", "process"]
    metrics = _between(doc, "### 12.1", "### 12.2")
    assert "| OMS | `oms_closed_pnl_divergence_total` | counter |" in metrics  # no account label
    assert "| OMS | `oms_closed_pnl_fetch_seconds{result}` | histogram |" in metrics


def test_contract_21_declares_the_record_table_and_classifies_it() -> None:
    doc = _doc("21-database-schema.md")
    table = _between(doc, "#### 3.3.13 ", "\n### 3.4 ")
    stored = set(_ADDED) - {"local_net_pnl", "net_pnl", "provisional"}  # derived on the read
    stored |= {"symbol", "side", "qty", "avg_entry_price", "avg_exit_price", "closed_pnl"}
    for column in sorted(stored | {"leverage", "opened_at", "closed_at", "settled_at"}):
        assert f" {column} " in table, column
    assert "CONSTRAINT cpr_side CHECK (side IN ('long','short'))" in table
    assert _SCHEMAS["JournalSide"]["enum"] == ["long", "short"]
    assert (
        "CREATE UNIQUE INDEX ux_cpr_order ON closed_pnl_records (exchange_account_id, "
        "exchange_order_id) WHERE exchange_order_id IS NOT NULL;"
    ) in table
    assert re.search(r"^\| `closed_pnl_records` \(PG\) +\| ∞ ", doc, re.MULTILINE)
    assert re.search(r"^\| `closed_pnl_records` +\| monetary columns +\| P1 ", doc, re.MULTILINE)


@pytest.mark.parametrize(
    "claim",
    [
        "### 19.105 2026-11-03 — ",
        "closed positions and today's realised PnL, contract first (E29-S06, #981)",
        "The orchestrator assigned this number on 2026-11-03 (09:16Z)",
    ],
)
def test_contract_24_change_log_records_this_slice(claim: str) -> None:
    assert claim in _between(_doc("24-internal-schemas.md"), "### 19.105 ", "\n### 19.")
