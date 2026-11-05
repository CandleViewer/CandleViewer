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
- Its first review's fold pins the money: the walk by side from the last flat the venue confirmed,
  each step's words, a worked example recomputed from the one docs-transcribed record, the venue's
  figure writable until the record is final, one window and one lookback for the cap and the view.
- Its delta's fold: several records under one order taken as one, the walk at each confirmed flat
  and after a disagreeing `closedSize`, the comparison's gates, and an offset change's first day.
- Fold r3 (rulings C1 to C3): the walk's two indexes built plainly, the one group the walk's opening
  fills name as the record's `trade_group_id`, and a page read per account. With the orchestrator's
  review: the poll kept after a failed read or a fill, a close not yet read served provisional, the
  cap per record, and five sentences no test held.
- Its rebase round: a close with no item (no order row, or a REST-recovered fill with no walk start)
  waits for its record, a record written after its fill's poll ends is a check for #843, a record no
  walk composes is in no group, row 55 keeps the window, row 59 bounds its sort by the named groups,
  and Sec.9.3 rule 3 cites C-5.6.
- Slice 3b and its fold: the sync's composition in the OMS runtime, a refused account's poll
  ended, an empty or absent `orderId` alike, and the orchestrator's ruling of 2026-11-04 (22:19Z),
  the sync's task's end paged and a fourth readiness condition in 24 Sec.8.12 and 20 Sec.6.2;
  with its review of 2026-11-05 (04:05Z), an unasked cancel paged too and a start the lane did
  not confirm a fault as well, in the same words there and in `_oms_state`; logged once, as
  Sec.19.134.
- Slice 4's lens fold: the sync's day is the resolver's and Sec.9.3.6 drops the cap's UTC instant;
  logged once, as Sec.19.135, with the two layers of the ruling of 2026-11-05 (02:37Z).
- Slice 5b, on the rulings of 2026-11-04 (23:45Z): the composition before the read and after the
  settle, one walk per key per pass, the final rule completed by the walk's `c`, step 3's three
  readings and 21 Sec.13.1's rows 61 and 62; logged once, as Sec.19.137.
- Slice 5c, on the rulings Q2 and Q6: the divergence record's action, reasons and after-state,
  the absolute floor (PROPOSED) and the two counters; logged once, as Sec.19.138.

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
from candleviewer.app import _oms_state
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
_RECORD: Final = (
    _PLAN.parents[1] / "packages/fixtures/bybit/2026-10-05/rest/trading-closed-pnl.json"
)
_M, _X, _LE = "\N{MINUS SIGN}", "\N{MULTIPLICATION SIGN}", "\N{LESS-THAN OR EQUAL TO}"


def _doc(name: str) -> str:
    return (_PLAN / name).read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    """The text from `start` to `end` (or to the end), its whitespace collapsed."""
    tail = text[text.index(start) :]
    return " ".join(tail[: tail.index(end) if end in tail else len(tail)].split())


def _missing(text: str, *claims: str) -> list[str]:
    """The claims `text` (whitespace-collapsed) does not hold, each collapsed the same way."""
    return [claim for claim in claims if " ".join(claim.split()) not in text]


def _s813() -> str:
    return _between(_doc("24-internal-schemas.md"), "### 8.13 ", "\n## 9. ")


def _row(doc: str, number: int) -> list[str]:
    """Row `number` of 21 Sec.13.1, its cells stripped."""
    rows = doc[doc.index("### 13.1 Postgres") : doc.index("### 13.2 ")].splitlines()
    [line] = [row for row in rows if row.startswith(f"| {number} ")]
    return [cell.strip() for cell in line.split("|")[1:-1]]


def _num(value: Decimal) -> str:
    return f"{value.normalize():f}"


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
        for account, items in sorted(accounts.items())
    ]
    assert _SCHEMAS["ClosedPnlTotals"]["properties"]["by_account"]["maxItems"] == 25
    window = meta["window"]
    start, next_start = (datetime.fromisoformat(window[k]) for k in ("start", "next_start"))
    assert next_start - start == timedelta(hours=24)  # no offset change takes effect that day
    local_midnight = start + timedelta(minutes=window["utc_offset_minutes"])
    assert (local_midnight.hour, local_midnight.minute, local_midnight.second) == (0, 0, 0)
    closes = [datetime.fromisoformat(i["closed_at"]) for i in page["items"]]
    assert closes == sorted(closes)  # a window read is oldest first
    assert all(start <= at < next_start for at in closes)  # `next_start` as served


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
        "**The empty-orderId rule:** a record the venue writes with an empty or absent `orderId` "
        'has `exchange_order_id` None, never `""`',
        "`local_net_pnl = gross_pnl + fee_pnl + funding_pnl`, present when all three are",
        "`|local_net_pnl \N{MINUS SIGN} closed_pnl| > "
        "CV_OMS_CLOSED_PNL_TOLERANCE_REL \N{MULTIPLICATION SIGN} |closed_pnl|`: "
        "strictly greater, and relative to the venue's figure, so a difference at the bound is "
        "not divergent and, against a venue figure of 0, any difference is;",
        "The tolerance is `1e-8`",
        "shipped **unvalidated** until #843",
        "A divergent comparison writes `pnl.divergence_detected` (§15.5) ahead of the item's flag "
        "(C-2.9), once per record and value pair",
        "in the `poll` lane (`background`, §8.7), never from the stop and cancel reserve",
    ):
        assert claim in text, claim


def test_contract_24_lists_the_adapter_record_with_its_venue_order_id() -> None:
    text = _between(_doc("24-internal-schemas.md"), "### 14.4 ", "\n## 15. ")
    record = text[text.index("class ClosedPnl(BaseModel):") :]
    record = record[: record.index("class AccountInfo")]
    assert "exchange_order_id: str | None = None" in record
    assert 'None, never "", # when the venue writes it empty (counted `no_order_id`)' in record
    for field in ("created_at: TsUs", "open_fee: Notional | None = None", "close_fee: Notional"):
        assert field in record, field
    assert "opened_at" not in record.replace("the code's `opened_at`", "")
    fills = text[text.index("class Execution(BaseModel):") : text.index("class ClosedPnl")]
    assert "closed_size: Qty | None = None" in fills
    assert "position_idx: Literal[0,1,2] | None = None # the venue's fill has none" in fills
    model = _between(_doc("24-internal-schemas.md"), "### 8.1 ", "\n### 8.2 ")
    fill = model[model.index("**`Execution`, as built") : model.index("**`Position`, as built")]
    assert "adds `closed_size`, the venue's `closedSize`: the size the fill closed" in fill
    assert "NULL where its source does not state it" in fill
    assert "in its migration slice; not stored yet" in fill
    assert "`position_idx` is its order row's, as the venue's fill has none (§8.13)" in fill
    assert "from E29-S06's store slices on; not set that way yet" in fill


def test_contract_24_names_the_divergence_action_as_the_registry_holds_it() -> None:
    """In the closed set ahead of its emitter; the note goes when the code registers it."""
    text = _between(_doc("24-internal-schemas.md"), "### 15.5 ", "\n### 15.6 ")
    registered = "pnl.divergence_detected" in AUDIT_ACTIONS
    note = "`pnl.divergence_detected` (not registered yet, E29-S06)"
    assert (note in text) is not registered
    assert "`pnl.divergence_detected` (E29-S06, #981; §8.13)" in text
    assert (
        "The composition writes it as `system:oms`, ahead of the record's `divergent` flag and "
        "once per record and value pair, never on a read."
    ) in text


def test_contract_20_lists_the_tolerance_and_the_two_metrics() -> None:
    doc = _doc("20-architecture.md")
    [row] = [
        line for line in doc.splitlines() if line.startswith("| `CV_OMS_CLOSED_PNL_TOLERANCE_REL`")
    ]
    assert [c.strip() for c in row.split("|")[2:5]] == ["decimal", "`1e-8`", "process"]
    assert "parsed from its text as a `Decimal`, never through a float" in row
    metrics = _between(doc, "### 12.1", "### 12.2")
    assert "| OMS | `oms_closed_pnl_divergence_total` | counter |" in metrics  # no account label
    assert "| OMS | `oms_closed_pnl_fetch_seconds{result}` | histogram |" in metrics
    assert not _missing(metrics, "no labels, `max_series` 1, and no account label (SR-125)")
    assert not _missing(
        metrics,
        "`ok` or `failed`, or `other_account` for a crossing between accounts, which a seed's "
        "positions read that meets one counts too; no account label, `max_series` 3; **ticket** "
        "`OmsClosedPnlAccountCrossing` when `other_account` rose in the hour (§12.5)",
    )


def test_contract_21_declares_the_record_table_and_classifies_it() -> None:
    doc = _doc("21-database-schema.md")
    table = _between(doc, "#### 3.3.13 ", "\n### 3.4 ")
    stored = set(_ADDED) - {"local_net_pnl", "net_pnl", "provisional"}  # derived on the read
    stored |= {"symbol", "side", "qty", "avg_entry_price", "avg_exit_price", "closed_pnl"}
    for column in sorted(stored | {"leverage", "opened_at", "closed_at", "settled_at", "final_at"}):
        assert f" {column} " in table, column
    assert "CONSTRAINT cpr_side CHECK (side IN ('long','short'))" in table
    assert _SCHEMAS["JournalSide"]["enum"] == ["long", "short"]
    assert (
        "CREATE UNIQUE INDEX ux_cpr_order ON closed_pnl_records (exchange_account_id, "
        "exchange_order_id) WHERE exchange_order_id IS NOT NULL;"
    ) in table
    assert re.search(r"^\| `closed_pnl_records` \(PG\) +\| ∞ ", doc, re.MULTILINE)
    assert re.search(r"^\| `closed_pnl_records` +\| monetary columns +\| P1 ", doc, re.MULTILINE)


def test_contract_24_walks_the_fills_by_side_from_the_last_flat_the_venue_confirmed() -> None:
    """M-2: the order's fills that close, read by side and keyed by the order row's
    `position_idx`; a fill the walk cannot read leaves its figures absent, never wrong. The delta
    (m-B, m-C, choice 1): no walk without a venue-confirmed flat, each such flat resets it, and a
    disagreeing `closedSize` counts by `min` until one."""
    text = _s813()
    assert "else from the key's first stored fill" not in text
    missing = _missing(
        text,
        "1. The record's closing fills are the order's fills that close: the stored fills "
        "(`executions.order_id`) of the order row whose `exchange_order_id` is the record's, of a "
        "trade type (`Trade`, `AdlTrade` or `BustTrade`), to which the walk (step 3) gives a `c` "
        "above 0. A record whose order has no row, or one of whose closing fills holds no closed "
        "PnL (a REST-recovered fill, §14.2), has no local figures.",
        "2. `gross_pnl` is the sum of their closed PnL, the venue's `execPnl`, before fees.",
        "keyed by (account, symbol, the `position_idx` of the fill's order row, as the venue's "
        "fills carry none), in `(exec_ts, exec_id)` order after the key's last flat the venue "
        "confirmed (the latest position reading of the key at size 0 dated, by the venue's time, "
        "before the first stored fill of the record's order; 21 §3.3.7, whose prune keeps each "
        "key's latest). With no such reading the walk has no start, never the key's first stored "
        "fill, and the record has no local figures. No writer stores a flat of its own (21 "
        "§3.3.7): a key's first reading is its anchor, so a key first read holding a position has "
        "no walk until the venue reports it flat.",
        "A fill opens when the walk is flat or holds the fill's own side: it adds its size to the "
        f"open size, its size {_X} price to the entry value and its fee to the opening fees.",
        "A fill of the other side closes `c`, the venue's `closedSize` where the fill states it "
        "(21 §3.3.6; the stream's fills do), else `min(exec_qty, open size)`, and takes "
        "`c / open size` of the entry value and of the opening fees; its remainder, "
        f"`exec_qty {_M} c`, opens the other side, and its fee is split between the two pro rata",
        "`opened_at` is the time of the position's first opening fill since the walk was last "
        "flat, and the walk's average entry is the entry value the record's closing fills take "
        "over the size they close.",
        "A flat the venue confirmed comes after every fill dated at or before it, and each one "
        "the walk crosses is a flat of the walk, which drops there any size, entry value and "
        "opening fees it still holds.",
        "A fill the walk cannot read makes the walk's figures (the opening fees, `opened_at`, the "
        "average entry and `funding_pnl`) absent until the walk next goes flat, counting sizes "
        "meanwhile: a fill of the other side with no closed PnL (a REST-recovered one); one larger "
        "than the open size that states no `closedSize`; a stated `closedSize` the walk disagrees "
        "with, above 0 on a fill that opens or other than `min(exec_qty, open size)` on one of the "
        "other side",
        "on a symbol the account holds in hedge mode (positions read with `positionIdx` 1 or 2), "
        "a fill with no order row.",
        "After a disagreeing `closedSize`, and until a flat the venue confirmed after that fill "
        "ends the absence (never a flat of the walk's own count), the walk counts each fill of the "
        "other side as closing `min(exec_qty, open size)`, whatever the fill states, and a record "
        "whose closing fills it reaches in that span has no local figures.",
    )
    assert missing == []


def test_contract_24_signs_the_fees_and_the_funding() -> None:
    """m-1: steps 4 and 5 word for word (the lens's surviving mutant dropped the opening share)."""
    missing = _missing(
        _s813(),
        "4. `fee_pnl` is minus the closing fills' fees, their closing share (step 3 splits a "
        "reversing fill's), and the opening fees they take: a fee paid is negative, a maker rebate "
        "positive.",
        "5. `funding_pnl` is `0` when no funding settlement of the symbol (its "
        "`funding_interval_min` apart, from 00:00 UTC) falls inside `[opened_at, closed_at]`, ends "
        "included. Otherwise funding is pending, and the figure is absent until E29-K01 (#843) "
        "records funding rows, which the walk then apportions as it does the opening fees: a "
        "payment lowers the figure, a receipt raises it.",
        "so a settlement made on an interval the venue has since shortened is missed and `0` can "
        "be wrong, a false flag until #843.",
    )
    assert missing == []


def test_contract_24_worked_example_recomputes_the_docs_record() -> None:
    """m-1: the worked example is the one docs-transcribed record, recomputed here in `Decimal`:
    a long closed by a `Sell`, every fill a taker's, gross + fee = the venue's `closedPnl`."""
    [row] = json.loads(_RECORD.read_text(encoding="utf-8"))["result"]["list"]
    entry, exit_, rate = (
        Decimal(row["cumEntryValue"]),
        Decimal(row["cumExitValue"]),
        Decimal("6e-4"),
    )
    gross, opening, closing = exit_ - entry, entry * rate, exit_ * rate
    fee = -(opening + closing)
    assert (row["side"], row["closedSize"], row["leverage"]) == ("Sell", "3", "3")
    assert gross + fee == Decimal(row["closedPnl"]) == Decimal("-47.4065323")
    g, f, o, c = (_num(abs(v)) for v in (gross, fee, opening, closing))
    venue = _num(abs(Decimal(row["closedPnl"])))
    missing = _missing(
        _s813(),
        f"a long of 3 at an average entry of {row['avgEntryPrice']} (entry value {_num(entry)}), "
        f"closed by one order's fills at an average {row['avgExitPrice']} (exit value "
        f"{_num(exit_)}), every fill a taker's at the fee rate {_num(rate)}",
        f"`gross_pnl` = {_num(exit_)} {_M} {_num(entry)} = {_M}{g}; the opening fees the closing "
        f"fills take are {_num(entry)} {_X} {_num(rate)} = {o} and their closing share "
        f"{_num(exit_)} {_X} {_num(rate)} = {c}, so `fee_pnl` = {_M}{f}; `funding_pnl` = 0; and "
        f"`local_net_pnl` = {_M}{g} {_M} {o} {_M} {c} = {_M}{venue}, the record's `closedPnl` "
        "exactly, so the item is not divergent.",
    )
    assert missing == []


def test_contract_24_keeps_the_venue_figure_writable_until_the_record_is_final() -> None:
    """M-1: a differing read replaces the venue's columns until the record is final; the
    empty-orderId id is the item's side and the venue's `createdTime`, never `updatedTime`. The
    delta (m-A, Nit 4): several records under one `orderId` are one item, and both cases are
    logged. Fold r3 (the review's Minor 3): the cap sums each such record on its own day."""
    text = _s813()
    assert "updated_ms" not in text and "is stored once read" not in text
    assert "logged and counted" not in text and "for the cap as for the item" not in text
    missing = _missing(
        text,
        'f"{account_id}:record:{symbol}:{side}:{created_ms}"',
        "so a record the venue updates keeps its id",
        "it is settled once read and never compared, and, with no order row, never final, so a "
        "later read that differs replaces its venue's columns.",
        "A read that lists several records under one `orderId` takes them as one record for the "
        "item: their sizes, `closed_pnl`, `open_fee` and `close_fee` summed (a fee one of them "
        "omits is absent), their prices weighted by size, `closed_at` the latest `updatedTime`, "
        "`created_at` the earliest `createdTime` and `leverage` the latest record's. The cap sums "
        "each of them in the day of its own `updatedTime`, never at the merged `closed_at`, so a "
        "gain an earlier day counted never lowers a later day's loss again; the view shows the "
        "order's one item on its latest record's day, so for such an order the two differ when "
        "its records fall in different days. The case is logged at WARNING with the account and "
        "the order, and #843's capture of a partly filled closing order (below) shows which shape "
        "the venue writes.",
        "The record is final once its closing order's row is terminal and the record's `qty` "
        "equals the size its stored closing fills close. Until then a read that differs replaces "
        "the venue's columns, logged, and the item is compared again, a new value pair audited if "
        "divergent, so a partly filled closing order's record follows its later fills (E29-K01, "
        "#843, captures one, read before and after them); once final they are frozen (21 "
        "§3.3.13 `final_at`), and a later read that differs is logged at WARNING, never applied.",
    )
    assert missing == []


def test_contract_24_counts_one_window_and_one_lookback_for_the_cap_and_the_view() -> None:
    """m-2, m-3, Nit 6: the cap and the view read one window after one lookback, converge once
    the item settles, and an offset change never moves the day in progress. The delta (m-D, Nit
    2): the offset and bounds the resolver answers that day, as 22 serves them, and no poll for a
    record whose order has no row. Fold r3 (the review's Major 2): a failed read and each stored
    fill keep the poll running, and a close not yet read is served, counted provisional. Slice
    3b's fold (n2): a read the account binding refuses outright ends both."""
    text = _s813()
    for overclaim in ("takes effect at the next read", "[day_start, now)", "never count a record"):
        assert overclaim not in text, overclaim
    missing = _missing(
        text,
        "and the order path's daily-loss figure and the closed-PnL view take it.",
        "the half-open `[day_start, next_start)`: except on the day an offset change takes effect "
        "(below), `day_start` is the latest instant",
        "A change of the column never moves the day in progress: that day keeps the offset it "
        "started with until its `next_start`, so a loss it has counted stays counted, and the new "
        "offset takes effect there, the next day running from that `next_start` to the first "
        "instant after it whose wall time at the new offset is 00:00:00.000",
        "The resolver answers the old offset, and that day's bounds, for the rest of the day the "
        "change is made in, and the new offset from its `next_start`, with that one day's bounds; "
        "a reader takes `next_start` as served, never as `day_start + 24 h`.",
        "so the rule survives a restart: that record is carried to E39-K01 (#880).",
        "E39-S02's lockout `until`, the wallet frame's `realised_pnl_today` (23 §15.4), "
        "`RiskSummary`'s `realised_pnl_today_usd` (22) and the rules vocabulary's "
        '`realised_pnl_today` ("since UTC midnight") and `daily_loss_pct` take it too is '
        "E39-K01's to decide",
        "the day's loss it gives the order path sums the venue's records whose `closed_at` falls "
        "in the view's window, `[day_start, next_start)` from this resolver, selected after a read "
        "that starts `CLOSED_PNL_LOOKBACK` before `day_start`, the sync's own reach (below): one "
        "window and one lookback for the cap and the view. A read that cannot cover that span "
        "within its bound leaves the figure unknown. The cap sums the venue's records, each in the "
        "day of its own `updatedTime`, and the view its items, so the two converge once the item "
        "settles, but for an order with several records (below).",
        "The adapter returns it, counted `no_order_id`, so the day's loss still sums it",
        "so a read, the cap's included, starts `CLOSED_PNL_LOOKBACK` (7 days, the venue's widest "
        "window, PROPOSED) before the day's start: it finds a record created up to that long "
        "before the day and closed in it, and one created earlier is missed if the venue filters "
        "on `createdTime`, a gap for E29-K01 (#843)'s captures. The poll ends for an item whose "
        "`closed_at` is older than that reach",
        "while the account holds an item with an `exchange_order_id` that is not final and whose "
        "order has a row, and runs at startup and after a private-stream reconnect: a record whose "
        "order has no row, such as a liquidation's, is never final, so it keeps no poll running, "
        "as one with an empty or absent `orderId` keeps none.",
        "A read that fails keeps the poll running until one succeeds, and each stored fill of a "
        "trade type keeps it running, within the reach, until a read that starts `SETTLE_POLL_S` "
        "or more after the fill was stored succeeds, so a close is read again once its record is "
        "due, never left to the one read its fill set off, which can fail or come before the "
        "venue writes the record; but a read the account binding refuses outright (the account "
        "missing, deleted, another environment's or holding no active key) ends both, so such an "
        "account is not resolved again every `SETTLE_POLL_S`, and its next stored fill or "
        "`resyncing` asks again.",
        "A close not yet read shows in the window as soon as its fill is stored: the composition "
        "writes a provisional item for each order with a row whose stored fill closes (one "
        "stating a `closedSize` above 0, or one the walk gives a `c` above 0), dated by its last "
        "such fill, local figures or none, so it counts in `meta.totals` at once (`count`, and "
        "`provisional` true) and in their `net_pnl` once it has one. Every other close, such as "
        "one whose order has no row (a liquidation's) or one whose closing fill was recovered over "
        "REST (no `closedSize`, 21 §3.3.6) on a key whose walk has no start, waits for its record, "
        "in no item and no total until that record is read.",
        "The poll such a close's fill keeps running ends at the first read that starts "
        "`SETTLE_POLL_S` or more after the fill was stored and succeeds (above), so a record the "
        "venue writes after that read is missed until something else sets off a read (a later "
        "fill, another item's poll, startup or a reconnect), however long that takes, a check for "
        "E29-K01 (#843)'s captures, which measure how long after its fill the venue writes such a "
        "record.",
    )
    assert missing == []
    members = _SCHEMAS["ClosedPnlWindow"]["properties"]
    window = {k: " ".join(v["description"].split()) for k, v in members.items()}
    assert "as this answer read it" not in window["utc_offset_minutes"]
    assert not _missing(
        window["start"],
        "00:00 at UTC+`utc_offset_minutes`, except on the day an offset change takes effect, "
        "which starts where the day before it ended (24 §8.13).",
    )
    assert not _missing(
        window["next_start"],
        "when the next day starts and the client reads again, taken as served and never "
        "computed; `start` + 24 h, except on the day an offset change takes effect,",
    )
    assert not _missing(
        window["utc_offset_minutes"],
        "except for the rest of the day a change is made in, which keeps the offset it started "
        "with (24 §8.13).",
    )


def test_contract_24_defines_a_provisional_item_and_when_a_settled_one_is_compared() -> None:
    """m-5..m-7, Nit 8: the provisional item's figures, the comparison again each pass, the flag
    cleared within the bound, and the cases below the rounding step. The delta (m-C, Nit 7): the
    comparison's gates, and a flag no comparison clears stays. Its group (m-4) is fold r3's."""
    missing = _missing(
        _s813(),
        "its `qty` is the size its closing fills close (their `c`, never `exec_qty`), its "
        "`avg_exit_price` their size-weighted price and its `avg_entry_price` the walk's average "
        "entry, `leverage` is absent, its `net_pnl` is the sum of the local figures present, and "
        "one without a `gross_pnl` has no `net_pnl` until its record is read, served all the same "
        "(the sync, below).",
        "and `net_pnl` is `closed_pnl` from then on, authoritative.",
        "A settled item is compared when `local_net_pnl` is present, the closing fills close "
        "exactly the record's `qty`, and `|walk's average entry "
        f"{_M} avg_entry_price| {_LE} CV_OMS_CLOSED_PNL_TOLERANCE_REL {_X} "
        "avg_entry_price`. Otherwise the stored fills do not account for the record (a fill not "
        "yet stored, or one the venue made that is missing from the store), and nothing is "
        "compared until a later composition.",
        "a later comparison within the bound clears the flag and writes no record. A composition "
        "that compares nothing, as when it loses its local figures, leaves the flag, and the pair "
        "it recorded, until a later comparison clears it.",
        "which each sync pass makes again for the settled items of its delta set (below),",
        "each pass compares again the settled items of its delta set (below), idempotent by the "
        "recorded pair.",
        "shipped **unvalidated** until #843, whose captures also judge the two cases where it "
        "falls below the 8-decimal rounding step, the relative bound the ruling fixed at `1e-8` "
        "and the absolute floor below beside it: a record under 1 USDT (|`closed_pnl`| < 1), "
        "where the rounding of the opening share alone, or any difference from a venue figure of "
        "0, passes the relative bound; and an entry price below about 0.5, where the venue's "
        "8-decimal `avgEntryPrice` alone fails the entry gate",
    )
    assert missing == []
    assert "a history that starts after the opening" not in _s813()  # Choice 1 removed it


def test_contract_21_guards_the_record_and_stores_the_walks_inputs() -> None:
    """M-1, M-2, Nit 9: `final_at` freezes the venue's columns, a settled row holds them all, no
    row is deleted, and `executions` and `position_snapshots` gain the walk's two inputs. The
    delta (choice 1, Nits 1, 5 and 7): each key's latest confirmed flat outlives the prune, the
    walk's fills have an index, the poll reads within its reach, and `divergent` stays."""
    doc = _doc("21-database-schema.md")
    table = _between(doc, "#### 3.3.13 ", "\n### 3.4 ")
    missing = _missing(
        table,
        "CONSTRAINT cpr_settled CHECK (CASE WHEN settled_at IS NULL THEN exchange_order_id IS NOT "
        "NULL AND closed_pnl IS NULL AND leverage IS NULL AND venue_created_at IS NULL ELSE "
        "closed_pnl IS NOT NULL AND qty IS NOT NULL AND avg_entry_price IS NOT NULL AND "
        "avg_exit_price IS NOT NULL AND leverage IS NOT NULL AND venue_created_at IS NOT NULL "
        "END),",
        "CONSTRAINT cpr_final CHECK (final_at IS NULL OR (settled_at IS NOT NULL AND "
        "exchange_order_id IS NOT NULL AND final_at >= settled_at)),",
        "CREATE INDEX ix_cpr_pending ON closed_pnl_records (exchange_account_id, closed_at) WHERE "
        "final_at IS NULL AND exchange_order_id IS NOT NULL;",
        "CREATE TRIGGER trg_cpr_no_delete BEFORE DELETE ON closed_pnl_records FOR EACH ROW EXECUTE "
        "FUNCTION forbid_mutation();",
        "CREATE TRIGGER trg_cpr_no_truncate BEFORE TRUNCATE ON closed_pnl_records FOR EACH "
        "STATEMENT EXECUTE FUNCTION audit_refuse_truncate(); ALTER TABLE closed_pnl_records "
        "ENABLE ALWAYS TRIGGER trg_cpr_no_delete; ALTER TABLE closed_pnl_records ENABLE ALWAYS "
        "TRIGGER trg_cpr_no_truncate;",
        "`trg_cpr_guard` (BEFORE UPDATE, `ENABLE ALWAYS`, SQLSTATE 23514) refuses any change to "
        "`id`, `exchange_account_id`, `exchange_order_id`, `symbol` or `side`, a `settled_at` or "
        "`final_at` that changes once set, and, once `final_at` is set, any change to the venue's "
        "columns (`qty`, the prices, `leverage`, `closed_pnl`, `closed_at`, `venue_created_at`): "
        "a later read that differs is then logged, never applied.",
        "`divergent` is set only with the pair its `pnl.divergence_detected` record names, "
        "written after that record, and cleared only by a later comparison within the tolerance, "
        "so a composition that compares nothing leaves it and its pair (24 §8.13).",
        "`cv_app` keeps INSERT, SELECT and UPDATE; DELETE and TRUNCATE are revoked where the role "
        "exists",
    )
    assert missing == []
    fills = _between(doc, "#### 3.3.6 ", "\n#### 3.3.7 ")
    missing = _missing(
        fills,
        "ALTER TABLE executions ADD COLUMN closed_size numeric(38,18);",
        "ALTER TABLE executions ADD CONSTRAINT ex_closed CHECK (closed_size IS NULL OR "
        "closed_size BETWEEN 0 AND exec_qty) NOT VALID;",
        "every writer also sets `position_idx` from the fill's order row",
        "CREATE INDEX ix_exec_walk ON executions (exchange_account_id, symbol, exec_ts, exec_id);",
    )
    assert missing == []
    flats = _between(doc, "#### 3.3.7 ", "\n#### 3.3.8 ")
    missing = _missing(
        flats,
        "ALTER TABLE position_snapshots ADD COLUMN exchange_updated_ts timestamptz;",
        "No writer stores a flat of its own, as the orchestrator decided on 2026-11-03 (22:40Z): a "
        "key's first reading is its anchor, a size 0 the venue reports is a confirmed flat and a "
        "reported position is none, so a key first read holding a position has no walk until the "
        "venue reports it flat.",
        "CREATE INDEX ix_psnap_flat ON position_snapshots (exchange_account_id, symbol, "
        "position_idx, exchange_updated_ts) WHERE size = 0 AND exchange_updated_ts IS NOT NULL;",
        "The 90-day prune (§7) keeps each key's latest such row, one per `(exchange_account_id, "
        "symbol, position_idx)`, so a position held longer keeps its walk's start; a key with none "
        "has no walk (24 §8.13).",
    )
    assert missing == []
    kept = r"^\| `position_snapshots` \(PG\) +\| 90 d .+\| The latest flat the venue confirmed "
    assert re.search(kept + "per key stays past 90 d", doc, re.M)
    for row, index in ((56, "ix_cpr_pending"), (57, "ix_psnap_flat"), (58, "ix_exec_walk")):
        assert re.search(rf"^\| {row} +\| Closed-PnL [^|]+\|[^|]+\| `{index}` ", doc, re.M), row
    assert re.search(r"^\| 56 +\| [^|]+\| [^|]+, not final, `closed_at` in reach ", doc, re.M)


def test_contract_22_pins_the_window_parameter_the_filters_and_the_stand_in() -> None:
    """m-1, m-4, Nits 1, 2, 4, 5, 13, 14: the operation's words a later slice serves. The delta
    (Nits 3 and 6): a settled item can change until final, and the 25 accounts are one server's."""
    params = {p.get("name"): p for p in _OPERATION["parameters"]}
    assert " ".join(params["window"]["description"].split()) == (
        "`today`: the configured trading day that contains the request (24 §8.13), oldest first, "
        "with `meta.window` and `meta.totals`. Not with `from` or `to`."
    )
    assert params["trade_group_id"]["description"] == (
        "Repeatable, at most 32; matched through the item's trade group (above)."
    )
    missing = _missing(
        " ".join(_OPERATION["description"].split()),
        "Mirrors `GET /v5/position/closed-pnl`, kept by the sync of 24-internal-schemas.md §8.13, "
        "which reads the venue's records as positions close (no nightly backfill), and used to "
        "seed journal entries",
        "Until the venue's record is final (24 §8.13), a later read can still change a settled "
        "item's `closed_pnl` and `net_pnl`, `qty`, prices, `leverage` and `closed_at`.",
        "and so is a window read whose accounts, named or granted, number more than 25 in this "
        "server's environment. Without `window`, `from` and `to` bound `closed_at`.",
        "a client keys rows by `id`.",
        "An item's trade group is its position's, the one group its opening fills' orders name "
        "(24 §8.13); an item whose opening fills name several groups or none matches no "
        "`trade_group_id`, so no group's totals count it.",
        "It ignores `window`, `side` and `trade_group_id`, as a list ignores a parameter it does "
        "not know, refuses a second `symbol` (`400 validation_failed`)",
        "and `net_pnl` is their sum, absent when they compose no `gross_pnl`: such an item is "
        "still served and counted, provisional, so a close not yet read whose order the server "
        "stores shows in the items and the totals once a stored fill of that order is known to "
        "close (24 §8.13).",
    )
    assert missing == []
    content = _OPERATION["responses"]["200"]["content"]["application/json"]
    assert "once E29-K01 (#843) records funding" in content["examples"]["today"]["summary"]
    assert "in ascending `exchange_account_id` order" in " ".join(
        _SCHEMAS["ClosedPnlTotals"]["properties"]["by_account"]["description"].split()
    )
    assert "`net_pnl` sums their `net_pnl`, provisional items included." in " ".join(
        _SCHEMAS["ClosedPnlTotals"]["description"].split()
    )
    assert _SCHEMAS["ClosedPnl"]["properties"]["net_pnl"]["description"].endswith(
        "else the sum of the local figures present, absent with no `gross_pnl`."
    )


def test_contract_21_builds_the_walks_two_indexes_plainly_under_a_lock_timeout() -> None:
    """Fold r3, C1: both in the revision's transaction under a 5 s `lock_timeout`, as 0034, 0042
    and 0047 build theirs: a concurrent build waits on a second booting process's snapshot (0034's
    docstring), and both tables are far below Sec.9.3 rule 3's 1 M rows."""
    doc = _doc("21-database-schema.md")
    fills = _between(doc, "#### 3.3.6 ", "\n#### 3.3.7 ")
    flats = _between(doc, "#### 3.3.7 ", "\n#### 3.3.8 ")
    for section in (fills, flats):
        assert "CONCURRENTLY ix_" not in section and "built `CONCURRENTLY`" not in section
    assert not _missing(
        fills,
        "through `ix_exec_walk` (§13.1 row 58), a plain `CREATE INDEX` in the revision's "
        "transaction under `lock_timeout` (5 s), not `CONCURRENTLY`: a concurrent build waits for "
        "every older snapshot of the database, and a second API process booting meanwhile holds "
        "one while it waits for the migration advisory lock (`migrations/boot.py`), so the two "
        "boots would wait on each other (`0034_order_vocabulary`); §9.3 rule 3 (C-5.6) asks for a "
        "concurrent build over 1 M rows, and `executions` is far below that (§11.3).",
    )
    assert not _missing(
        flats,
        "`ix_psnap_flat` is a plain `CREATE INDEX` in the revision's transaction under "
        "`lock_timeout` (5 s), not `CONCURRENTLY`, as `ix_exec_walk` is (§3.3.6): a concurrent "
        "build would wait on the snapshot a second booting API process holds "
        "(`0034_order_vocabulary`), and `position_snapshots` is far below the 1 M rows over which "
        "§9.3 rule 3 (C-5.6) asks for one (§11.3).",
    )
    assert "3. **Indexes are built `CONCURRENTLY`** on any table with > 1 M rows" in doc
    versions = _PLAN.parents[1] / "services/api/candleviewer/migrations/versions"
    reason = " ".join((versions / "0034_order_vocabulary.py").read_text(encoding="utf-8").split())
    assert (
        "a second booting API process holds one while it waits for the `cv_migrations` advisory "
        "lock (`migrations/boot.py`), so the two boots would wait on each other"
    ) in reason


def test_contract_the_record_stores_the_one_group_its_opening_fills_name() -> None:
    """Fold r3, C2: `trade_group_id`, the one group the walk's opening fills name, else NULL
    (several, or none, never the closing side's), the composition's alone and writable at any
    stage; `listClosedPnl`'s filter and totals read it through `ix_cpr_group`."""
    doc = _doc("21-database-schema.md")
    assert not _missing(
        _between(doc, "#### 3.3.13 ", "\n### 3.4 "),
        "trade_group_id uuid REFERENCES trade_groups(id) ON DELETE RESTRICT, -- the position's "
        "group (24 §8.13); NULL: none or several",
        "CREATE INDEX ix_cpr_group ON closed_pnl_records (exchange_account_id, trade_group_id, "
        "closed_at) WHERE trade_group_id IS NOT NULL;",
        "The composition upserts by `id` and writes the local figures, `trade_group_id`, and the "
        "provisional `qty`, prices and `closed_at`;",
        "and so may `trade_group_id`, the composition's alone (24 §8.13): settling never writes "
        "it, and `trg_cpr_guard` refuses no change to it, the record final or not;",
        "and its `trade_group_id` filter (`ix_cpr_group`, row 59)",
        "The filter matches the stored `trade_group_id`, so a record whose `trade_group_id` is "
        "NULL is in no group's page or totals (24 §8.13).",
        "`trade_group_id`, an id, is class P0 with no comment; it references its group `ON DELETE "
        "RESTRICT`, as `idempotency_anchors.trade_group_id` does (§3.3.10), and no index serves "
        "that reference, as a group is never deleted (§7, §3.3.3a).",
    )
    assert _row(doc, 59) == [
        "59", "Closed-PnL group filter",
        "row 55's read and totals with `trade_group_id = ANY($2)`, which a NULL never matches",
        "`ix_cpr_group` (partial); 2 to 32 groups: a sort of only their records",
        "< 5 ms for a group's records",
    ]  # fmt: skip
    text = _s813()
    for gone in ("(the first's, when they differ)", "else of its closing fills' leg"):
        assert gone not in text, gone
    assert not _missing(
        text,
        "An item's trade group is its position's, which the composition stores as the record's "
        "`trade_group_id` (21 §3.3.13) whenever it walks the record: the one group the legs of the "
        "walk's opening fills' orders name (step 3: the fills that opened the position since the "
        "walk was last flat, before the record's closing fills), a fill whose order is on no leg "
        "(an adopted order's) naming none.",
        "It is NULL when they name several, as when a second ticket's entry adds to the position: "
        "the walk pools their entries and the record's one figure cannot be split between them, "
        "so naming one group would count the other's share in its totals.",
        "It is NULL too when they name none or the walk has no start, never the closing side's "
        "group instead: a group's take-profit ladder is orders on its leg while its native stop's "
        "materialised order and a manual close are on none, so the group would count its "
        "take-profits and miss its stop-outs. Settling never writes it, so a record no walk "
        "composes, such as a liquidation's, keeps it NULL, and the group whose position it closes "
        "misses that stop-out in its totals.",
        "`listClosedPnl`'s `trade_group_id` filter, and the totals it narrows, read the stored "
        "column: an item whose `trade_group_id` is NULL is in no group's filter or totals, and "
        "counts in its account's as any item does.",
    )
    assert "else its closing fills'" not in " ".join(_OPERATION["description"].split())


def test_contract_21_reads_a_page_per_account_and_never_sorts_every_match() -> None:
    """Fold r3, C3: row 55 reads each account's page and merges them, the bounded read #4997 gave
    `listOrders` and `listExecutions` (`oms_reads_sqlalchemy._merged`, still `LATERAL`); its
    rebase round put the window's `closed_at` bound back in the row."""
    doc = _doc("21-database-schema.md")
    assert _row(doc, 55) == [
        "55", "Closed-PnL pages and totals",
        "per account (`LATERAL`): `closed_at` in the window, `LIMIT` past the cursor, both ways",
        "`ix_cpr_day`, merged: never a sort of every match (`oms_reads`, #4997)",
        "< 20 ms for a day's records",
    ]  # fmt: skip
    assert not _missing(
        _between(doc, "#### 3.3.13 ", "\n### 3.4 "),
        "`listClosedPnl`'s pages and totals (`ix_cpr_day`, §13.1 row 55)",
        "A page reads each account on its own (`LATERAL` over the accounts): at most the page's "
        "`limit` rows past the cursor, in `(closed_at, id)` order either way, which it then "
        "merges, so no read sorts every matching row, as `listOrders` and `listExecutions` read "
        "(`storage/repositories/oms_reads_sqlalchemy.py`, #4997); the totals sum each account's "
        "window.",
    )
    repositories = _PLAN.parents[1] / "services/api/candleviewer/storage/repositories"
    source = (repositories / "oms_reads_sqlalchemy.py").read_text(encoding="utf-8")
    assert "def _merged(" in source and ".lateral(" in source  # the pointer still holds


@pytest.mark.parametrize(
    "claim",
    [
        "### 19.105 2026-11-03 — ",
        "closed positions and today's realised PnL, contract first (E29-S06, #981)",
        "The orchestrator assigned this number on 2026-11-03 (09:16Z)",
        "Folded again on the orchestrator's rulings of 2026-11-04 (00:53Z), C1 to C3",
        "C1: 21's `ix_exec_walk` and `ix_psnap_flat` are plain builds in the revision's "
        "transaction under a 5 s `lock_timeout`, not `CONCURRENTLY`",
        "C2: `closed_pnl_records` gains `trade_group_id`, the one group the walk's opening fills "
        "name, else NULL, which only the composition writes",
        "C3: 21 §13.1 row 55 reads each account's page apart and merges them",
        "a failed read, and each stored fill until a read after it succeeds, keep the poll "
        "running, and a close not yet read whose order the server stores is served provisional "
        "once a stored fill of that order is known to close",
        "the cap sums several records under one `orderId` each on its own `updatedTime`",
        "the generated TypeScript types read `provisional` and `divergent`, which have defaults, "
        "as present; nothing reads them yet",
        "Folded on the rebase round (2026-11-04, note 6623235535). 21 §13.1's closed-PnL rows are",
    ],
)
def test_contract_24_change_log_records_this_slice(claim: str) -> None:
    assert claim in _between(_doc("24-internal-schemas.md"), "### 19.105 ", "\n### 19.")


def test_contract_24_states_the_final_rule_as_the_composition_builds_it_and_21_its_reads() -> None:
    """Slice 5b (Q4, option 3): the walk's `c` completes the final rule, decided per record from
    its own closes; the stated sum (21 §13.1 row 60), the S3 review's m2, is the sync's without
    its composition (rows 58, 61 and 62, the composition's reads, are pinned on their own)."""
    assert _row(_doc("21-database-schema.md"), 60)[1:4] == [
        "Closed-PnL stated final rule",
        "the order's trade `executions` in its account: `sum(closed_size)`, NULL if one is NULL",
        "`ix_exec_order`; read by a sync built without its composition alone",
    ]
    text = _s813()
    assert "until E29-S06's composition slice gives such a fill the walk's `c`" not in text
    assert not _missing(
        text,
        "that size is the sum of the `c` the walk gives the record's closing fills, and the record "
        "is final only when it is settled, its order's row is terminal, its walk has a start and "
        "stopped at no cap, the walk is sure of its count of sizes at each of those closes, and "
        "that sum is its `qty`.",
        "A fill with no closed PnL, such as a REST-recovered one, leaves the walk sure of its "
        "count, so its record can be final with no local figures;",
        "Each record is decided from its own closes, never the whole walk's: a span after them "
        "does not touch them.",
        "The sync built without its composition keeps the stated rule, the sum of the "
        "`closed_size` the order's stored trade fills state (21 §13.1 row 60), which a fill "
        "stating none leaves open.",
    )
    log = _between(_doc("24-internal-schemas.md"), "### 19.129 ", "\n### 19.")
    assert "which 21 §13.1's new row 60 reads over `ix_exec_order`" in log


def test_contract_21_states_the_compositions_reads() -> None:
    """E29-S06 slice 5b (#981): the composition's three account-scoped reads, 21 §13.1 rows 58
    (the walk's fills with their order rows and the leg groups of the fill's own account), 61 (the
    orders it composes) and 62 (the hedge probe), and §3.3.13's Readers clause, row 61 reading
    whether an order's record is stored by `ux_cpr_order`."""
    doc = _doc("21-database-schema.md")
    assert [_row(doc, n)[1:4] for n in (58, 61, 62)] == [
        ["Closed-PnL walk's fills",
         "the key's `executions` after its start, in order, with order rows and leg groups",
         "`ix_exec_walk` and the `orders` PK, the fill's account's leg by its PK"],
        ["Closed-PnL composition orders",
         "the account's orders by id or venue id, each with its fill times, walk start, record",
         "the `orders` keys; `ix_exec_order`, `ix_psnap_flat`, `ux_cpr_order`"],
        ["Closed-PnL hedge probe",
         "`EXISTS` the account's `positions` of the symbol at `position_idx` 1 or 2",
         "the `positions` key `(exchange_account_id, symbol, position_idx)`"],
    ]  # fmt: skip
    readers = _between(doc, "- **Readers.** `listClosedPnl`", "\n- **Grants")
    assert not _missing(
        readers,
        "and its upsert by order (`ux_cpr_order`), by which its composition also reads whether an "
        "order's record is stored (row 61).",
    )


def test_contract_24_composes_in_each_pass_and_logs_slice_5b_once() -> None:
    """The orchestrator's rulings of 2026-11-04 (23:45Z): the named orders before the read (Q2),
    the delta set after the settle with one walk per key per pass (Q3); step 3's three readings
    (the S5a review's m2), funding absent with no interval, a group read through the account's
    own legs; Sec.19.137, which occurs once."""
    internal = _doc("24-internal-schemas.md")
    assert not _missing(
        _s813(),
        "Three readings of these sentences, as the walk takes them (§19.137): a fill the walk "
        "cannot read that reverses the position goes flat within itself, and its remainder opens "
        "the other side unreadable, as the walk read none of it; a disagreeing fill itself closes "
        "`min(exec_qty, open size)`, never the size it states; and a key at `position_idx` 1 or 2 "
        "is walked in hedge mode whatever the account's positions show",
        "With no interval cached (the cache not loaded, the symbol not listed, or an interval "
        "outside 1 to 1,440 minutes) funding is absent, never `0`;",
        "A leg of another account names none either: the walk reads the legs of the fill's own "
        "account alone (21 §13.1 row 58, C-12.4).",
        "Before it reads the venue it composes the orders whose stored trade fills `stored` named "
        "since its last pass (at most 256 an account;",
        "After the records settle it composes the pass's delta set (Q3): the records the read "
        "inserted, settled or replaced (every record it read at the account's first composition, "
        "as after a restart), those the poll reads (21 §13.1 row 56) and the named orders,",
        "One walk per key per pass: the orders of a key that share a start share one walk up to "
        "their last fill, which the second step reuses,",
        "A walk takes at most 500 fills and 32 flats and runs on a worker thread, and a pass "
        "spends about 5 s composing, checked before each order; past the cap an order's figures "
        "are absent, and past the budget it waits for the next pass, each logged at WARNING with "
        "the account and the record, never a figure (C-12.6).",
        "The figures are quantized once, `ROUND_HALF_UP` to 8 dp (§1.5), from the walk's exact "
        "outputs, `local_net_pnl` being their exact sum,",
        "No cap reads a composed figure: `DayRiskFigures` sums the venue's records alone.",
    )
    assert internal.count("\n### 19.137 ") == 1
    log = _between(internal, "### 19.137 ", "\n### 19.")
    assert not _missing(
        log,
        "2026-11-05 — §8.13: the composition writes the provisional items and completes the final "
        "rule with the walk's `c` (E29-S06, #981)",
        "The orchestrator assigned this number on 2026-11-04 (23:45Z)",
        "the literal re-walk of the whole reach set aside (C-2.18)",
        "decided per record, never from the whole walk; a REST-recovered close can be final.",
        "No REST operation, WS frame, table, column, migration, chart or `machine_hash` changes.",
    )


def test_contract_24_states_the_fold_of_slice_5bs_review() -> None:
    """The S5b review and the orchestrator's rulings of 2026-11-05 (06:36Z, 07:47Z): the delta
    set's order and carry (m1), the figures a later pass leaves (m2), the reason step 5's window
    ends at the last closing fill (ruling 3), the pass's comparison over its delta set and the
    pieces' overlap (m4), logged under Sec.19.137."""
    text = _s813()
    for gone in (
        "so no fill is walked twice",
        "each pass compares again the settled items its read covers",
        "makes again for the settled items its read covers",
        "a pass spends at most 5 s composing",
    ):
        assert gone not in text, gone
    assert not _missing(
        text,
        "the composition's `closed_at` here is the record's last closing fill's time, never the "
        "record's, as the venue's `updatedTime` may move after the close.",
        "each pass compares again the settled items of its delta set (below), idempotent by the "
        "recorded pair.",
        "That step takes the named orders first, then the venue ids an earlier step left, then the "
        "records the read changed, then the poll's page less those, so a full page starves no "
        "fresh settle; what it leaves past its 256 orders or its budget, but the page's, which the "
        "poll reads again, is carried to the next pass, which it asks for, at most 1,024 an "
        "account, any past that dropped and logged at WARNING with the account and their count.",
        "and the pieces overlap only where an order's own fills straddle a flat, with the same "
        "closes. A shared walk that a later order's fills cap is taken again for each earlier "
        "order, to its own last fill.",
        "A later pass that cannot walk a held record leaves the figures it composed, as when its "
        "walk's start is pruned past the 90-day reach (21 §3.3.7) or its walk is past the cap, "
        "and such a record is never final;",
        "keeps the poll, the named orders and what it was to carry; the read goes on.",
    )
    log = _between(_doc("24-internal-schemas.md"), "### 19.137 ", "\n### 19.")
    assert not _missing(
        log,
        "Folded on the slice's review and the orchestrator's rulings of 2026-11-05 (06:36Z and "
        "07:47Z)",
        "a later pass that cannot walk a held record leaves the figures it composed",
        "as the venue's `updatedTime` may move after the close;",
    )


def test_contract_24_and_20_state_the_syncs_composition_and_its_fourth_readiness_line() -> None:
    """E29-S06 slice 3b (#981): 24 Sec.8.13 "Its composition" as built, and the orchestrator's
    ruling of 2026-11-04 (22:19Z) with its review of 2026-11-05 (04:05Z): a sync that has faulted,
    its task ended unasked (a cancel included) or a start the lane did not confirm, is paged once
    and is a fourth condition of Sec.8.12 "Readiness", which 20 Sec.6.2's consumer paragraph and
    `_oms_state` state in the same words, never a gate on order entry. Its fold's change log is
    Sec.19.134, which occurs once."""
    internal = _doc("24-internal-schemas.md")
    assert not _missing(
        _s813(),
        "A start the lane does not confirm (one that fails, or one whose answer the bound cuts "
        "off, which may still have run) is logged CRITICAL and paged as unconfirmed, and the "
        '`oms` check of `/readyz` reads `degraded` (§8.12 "Readiness"), while `ready` stands.',
        "and, with reconciliation composed, each `resyncing` the consumer answers goes to "
        "`reconnected` ahead of reconciliation's request.",
        "once it has ended unasked (by an error, a return, or a cancellation no stop asked for, "
        "as the order lane's death makes one), its end is paged once and the `oms` check of "
        '`/readyz` reads `degraded` (§8.12 "Readiness"), and what `placeOrder` and the exits '
        "read is unchanged; a stop it was asked for pages nothing.",
    )
    readiness = _between(internal, "**Readiness (the orchestrator's ruling of 2026-10-25).**", "\n")
    assert not _missing(
        readiness,
        "The orchestrator's ruling of 2026-11-04 (22:19Z), with its review of 2026-11-05 "
        "(04:05Z), adds a fourth condition: the check is `degraded` too once the closed-PnL sync "
        'has faulted (its task ended unasked, or a start the lane did not confirm; §8.13 "Its '
        'composition"), as neither is tried again, and each is paged once. That condition never '
        "gates order entry: `placeOrder` and the exits read neither the check nor the sync, whose "
        "records no route serves yet.",
    )
    consumer = _between(_doc("20-architecture.md"), "**The private-stream consumer (E29-T05", "\n")
    assert not _missing(
        consumer,
        "The check is also `degraded` once E29-S06's closed-PnL sync, which the runtime starts "
        "after the consumer, has faulted (its task ended unasked, or a start the lane did not "
        "confirm): neither is tried again, and each is paged once (the orchestrator's ruling of "
        "2026-11-04 and its review of 2026-11-05, `24-internal-schemas.md` §8.12 and §8.13); that "
        "condition never gates order entry either.",
    )
    fourth = "has faulted (its task ended unasked, or a start the lane did not confirm"
    code = " ".join((_oms_state.__doc__ or "").split())
    assert all(fourth in text for text in (readiness, consumer, code))  # the same words
    assert internal.count("\n### 19.134 ") == 1
    log = _between(internal, "### 19.134 ", "\n### 19.")
    assert not _missing(
        log,
        "2026-11-04 — §8.12, §8.13 and 20 §6.2: the OMS runtime runs the closed-PnL sync, whose "
        "task's end is paged and degrades `/readyz` (E29-S06, #981)",
        "The orchestrator assigned this number on 2026-11-04 (22:19Z)",
        "a fourth condition beside the three of the ruling of 2026-10-25",
        "ends that account's poll, a stored fill's included, until its next stored fill or "
        "`resyncing` asks again; any other failure keeps the poll.",
        "the adapter reads a record with no `orderId` field as one with an empty one (§14.2 rule "
        "12).",
        "The orchestrator's review of 2026-11-05 (04:05Z): an end of the sync's task that no stop "
        "asked for is unasked, a cancellation included (the order lane's death makes one), and is "
        "paged once; and a start the lane did not confirm is the sync's fault too.",
    )


def test_contract_24_and_20_count_a_crossing_between_accounts_apart_and_ticket_it() -> None:
    """The orchestrator's review of slice 3b (2026-11-04, 22:38Z): a crossing between accounts is
    timed under a `result` of its own, the seed's too, and raises a ticket (20 Sec.12.5)."""
    assert not _missing(
        _s813(),
        "Each read is timed in `oms_closed_pnl_fetch_seconds{result}`, `ok` or `failed`, and a "
        "crossing between accounts apart, under `other_account`: an account read, a record or a "
        "seed's position reading (below) that names another account (C-2.11), which raises the "
        "ticket `OmsClosedPnlAccountCrossing` (`20-architecture.md` §12.5).",
    )
    alerts = _between(_doc("20-architecture.md"), "### 12.5", "\n## 13. ")
    assert not _missing(
        alerts,
        "Ticket — `OmsClosedPnlAccountCrossing`, when "
        '`oms_closed_pnl_fetch_seconds{result="other_account"}` rose in the last hour.',
    )
    log = _between(_doc("24-internal-schemas.md"), "### 19.134 ", "\n### 19.")
    assert not _missing(
        log,
        "raises the ticket `OmsClosedPnlAccountCrossing`, modelled on `BybitRowsRefusedAccount`; "
        "the histogram's `max_series` is 3.",
        "No REST operation, WS frame, table, column, migration, chart or `machine_hash` changes.",
    )


def test_contract_24_gives_the_cap_and_the_sync_the_one_resolver_and_logs_it_once() -> None:
    """Slice 4's lens fold (M1): Sec.8.13 "Its composition" gives the sync the resolver's day and
    Sec.9.3.6 drops the UTC instant the cap read until this slice. Sec.19.135, which occurs once,
    logs the one resolver on one clock, a kept day's loss served only inside its day and its TTL,
    and the two layers of the orchestrator's ruling of 2026-11-05 (02:37Z)."""
    internal = _doc("24-internal-schemas.md")
    for stale in ("Its day is the UTC day until", "the instant read until E29-S06 rewires it)"):
        assert stale not in internal, stale
    assert not _missing(
        _s813(),
        "and the exchange-synced clock the position store reads, so the seed's 5 s skew is "
        "measured on the server's time. Its day is the resolver's (§8.13 "
        '"The day boundary"). It starts where the runtime sets `ready`',
    )
    assert internal.count("\n### 19.135 ") == 1
    log = _between(internal, "### 19.135 ", "\n### 19.")
    assert not _missing(
        log,
        "2026-11-05 — §8.13 and §9.3.6: the cap and the sync take the one day resolver, and a kept "
        "day's loss is served only inside its day (E29-S06, #981)",
        "The orchestrator assigned this number on 2026-11-05",
        "the order path's daily-loss figure (`DayRiskFigures`, the cap) and the closed-PnL sync "
        "take the one resolver and hand it instants from one clock, the exchange-synced one",
        "A kept day's loss is unknown from its day's `next_start` and before its `day_start`, and "
        "also past `FIGURES_TTL_S` (§9.3.6's few seconds), for `DayRiskFigures.read` and `peek` "
        "alike, and a failed re-read never serves it",
        "on the order path the fail-closed answer is the size step's `figure_unknown` (`503 "
        "sizing_unavailable` with `Retry-After`), as §8.4 reads the figures before the risk gate, "
        "while the gate's own `risk_state_unavailable` stays for held costs (#881 addendum 3).",
    )


def test_contract_24_states_the_divergence_record_and_the_floor_and_logs_slice_5c_once() -> None:
    """The rulings Q2 and Q6 (2026-11-04 23:45Z, 2026-11-05): the record's reasons and after-state,
    the floor; Sec.19.138, which occurs once; 20's floor and second counter; 21's flag writes."""
    internal = _doc("24-internal-schemas.md")
    assert not _missing(
        _s813(),
        "a comparison is divergent only when the difference is also strictly greater than "
        "`CV_OMS_CLOSED_PNL_TOLERANCE_ABS` (0.01 USDT,",
    )
    vocabulary = _between(internal, "### 15.5 ", "\n### 15.6 ")
    assert "reason `closed_pnl_venue_missing`, its `closed_pnl` and difference null" in vocabulary
    assert "`difference` (signed, local \N{MINUS SIGN} venue)" in vocabulary
    assert "severity `warning` and its reason as above;" in vocabulary
    assert internal.count("\n### 19.138 ") == 1
    log = _between(internal, "### 19.138 ", "\n### 19.")
    assert not _missing(
        log,
        "2026-11-05 — §8.13 and §15.5: the comparison writes the divergence record, bounded, and a "
        "venue figure missing is recorded (E29-S06, #981)",
        "The absolute floor, PROPOSED (Q6; 24 carried none, as checked on 2026-11-05)",
        "superseding the ticket's `{account}`",
        "No REST operation, WS frame, table, column, migration, chart or `machine_hash` changes.",
    )
    doc = _doc("20-architecture.md")
    [row] = [
        line for line in doc.splitlines() if line.startswith("| `CV_OMS_CLOSED_PNL_TOLERANCE_ABS`")
    ]
    assert [c.strip() for c in row.split("|")[2:5]] == ["decimal", "`0.01`", "process"]
    assert "| OMS | `oms_closed_pnl_divergence_withheld_total{reason}` | counter |" in doc
    assert "clears `divergent` alone, keeping the pair" in _doc("21-database-schema.md")
