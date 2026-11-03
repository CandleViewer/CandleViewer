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
_RECORD: Final = (
    _PLAN.parents[1] / "packages/fixtures/bybit/2026-10-05/rest/trading-closed-pnl.json"
)
_M, _X = "\N{MINUS SIGN}", "\N{MULTIPLICATION SIGN}"


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
    for field in ("created_at: TsUs", "open_fee: Notional | None = None", "close_fee: Notional"):
        assert field in record, field
    assert "opened_at" not in record.replace("the code's `opened_at`", "")
    fills = text[text.index("class Execution(BaseModel):") : text.index("class ClosedPnl")]
    assert "closed_size: Qty | None = None" in fills
    assert "position_idx: Literal[0,1,2] | None = None # the venue's fill has none" in fills
    model = _between(_doc("24-internal-schemas.md"), "### 8.1 ", "\n### 8.2 ")
    fill = model[model.index("class Execution(BaseModel):") : model.index("class Position(")]
    assert "closed_size: Qty | None = None # the venue's closedSize" in fill
    assert "position_idx: Literal[0, 1, 2] = 0 # its order row's" in fill


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
    assert [c.strip() for c in row.split("|")[2:5]] == ["decimal", "`1e-8`", "process"]
    assert "parsed from its text as a `Decimal`, never through a float" in row
    metrics = _between(doc, "### 12.1", "### 12.2")
    assert "| OMS | `oms_closed_pnl_divergence_total` | counter |" in metrics  # no account label
    assert "| OMS | `oms_closed_pnl_fetch_seconds{result}` | histogram |" in metrics
    assert not _missing(metrics, "no labels, `max_series` 1, and no account label (SR-125)")
    assert not _missing(metrics, "`ok` or `failed`; no account label, `max_series` 2;")


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
    `position_idx`; a fill the walk cannot read leaves its figures absent, never wrong."""
    missing = _missing(
        _s813(),
        "1. The record's closing fills are the order's fills that close: the stored fills "
        "(`executions.order_id`) of the order row whose `exchange_order_id` is the record's, of a "
        "trade type (`Trade`, `AdlTrade` or `BustTrade`), to which the walk (step 3) gives a `c` "
        "above 0. A record whose order has no row, or one of whose closing fills holds no closed "
        "PnL (a REST-recovered fill, §14.2), has no local figures.",
        "2. `gross_pnl` is the sum of their closed PnL, the venue's `execPnl`, before fees.",
        "keyed by (account, symbol, the `position_idx` of the fill's order row, as the venue's "
        "fills carry none), in `(exec_ts, exec_id)` order after the key's last flat the venue "
        "confirmed (the latest position reading of the key at size 0 dated, by the venue's time, "
        "before the first stored fill of the record's order; 21 §3.3.7), else from the key's first "
        "stored fill",
        "A fill opens when the walk is flat or holds the fill's own side: it adds its size to the "
        f"open size, its size {_X} price to the entry value and its fee to the opening fees.",
        "A fill of the other side closes `c`, the venue's `closedSize` where the fill states it "
        "(21 §3.3.6; the stream's fills do), else `min(exec_qty, open size)`, and takes "
        "`c / open size` of the entry value and of the opening fees; its remainder, "
        f"`exec_qty {_M} c`, opens the other side, and its fee is split between the two pro rata",
        "A fill the walk cannot read makes the walk's figures (the opening fees, `opened_at`, the "
        "average entry and `funding_pnl`) absent until the walk next goes flat, counting sizes "
        "meanwhile: a fill of the other side with no closed PnL (a REST-recovered one); one larger "
        "than the open size that states no `closedSize`; a stated `closedSize` the walk disagrees "
        "with, above 0 on a fill that opens or other than `min(exec_qty, open size)` on one of the "
        "other side",
        "on a symbol the account holds in hedge mode (positions read with `positionIdx` 1 or 2), "
        "a fill with no order row.",
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
    empty-orderId id is the item's side and the venue's `createdTime`, never `updatedTime`."""
    text = _s813()
    assert "updated_ms" not in text and "is stored once read" not in text
    missing = _missing(
        text,
        'f"{account_id}:record:{symbol}:{side}:{created_ms}"',
        "so a record the venue updates keeps its id",
        "it is settled once read and never compared, and, with no order row, never final, so a "
        "later read that differs replaces its venue's columns.",
        "The record is final once its closing order's row is terminal and the record's `qty` "
        "equals the size its stored closing fills close. Until then a read that differs replaces "
        "the venue's columns, logged, and the item is compared again, a new value pair audited if "
        "divergent, so a partly filled closing order's record follows its later fills (E29-K01, "
        "#843, captures one, read before and after them); once final they are frozen (21 "
        "§3.3.13 `final_at`), and a later read that differs is logged and counted, never applied.",
    )
    assert missing == []


def test_contract_24_counts_one_window_and_one_lookback_for_the_cap_and_the_view() -> None:
    """m-2, m-3, Nit 6: the cap and the view read one window after one lookback, converge once
    the item settles, and an offset change never moves the day in progress."""
    text = _s813()
    for overclaim in ("takes effect at the next read", "[day_start, now)", "never count a record"):
        assert overclaim not in text, overclaim
    missing = _missing(
        text,
        "and the order path's daily-loss figure and the closed-PnL view take it.",
        "A change of the column never moves the day in progress: that day keeps the offset it "
        "started with until its `next_start`, so a loss it has counted stays counted, and the new "
        "offset takes effect there, the next day running from that `next_start` to the first "
        "instant after it whose wall time at the new offset is 00:00:00.000",
        'the rules vocabulary\'s `realised_pnl_today` ("since UTC midnight") and `daily_loss_pct` '
        "take it too is E39-K01's to decide",
        "the day's loss it gives the order path sums the venue's records whose `closed_at` falls "
        "in the view's window, `[day_start, next_start)` from this resolver, selected after a read "
        "that starts `CLOSED_PNL_LOOKBACK` before `day_start`, the sync's own reach (below): one "
        "window and one lookback for the cap and the view. A read that cannot cover that span "
        "within its bound leaves the figure unknown. The cap sums the venue's records and the view "
        "its items, so the two converge once the item settles.",
        "The adapter returns it, counted `no_order_id`, so the day's loss still sums it",
        "so a read, the cap's included, starts `CLOSED_PNL_LOOKBACK` (7 days, the venue's widest "
        "window, PROPOSED) before the day's start: it finds a record created up to that long "
        "before the day and closed in it, and one created earlier is missed if the venue filters "
        "on `createdTime`, a gap for E29-K01 (#843)'s captures. The poll ends for an item whose "
        "`closed_at` is older than that reach",
        "while the account holds an item with an `exchange_order_id` that is not final",
    )
    assert missing == []


def test_contract_24_defines_a_provisional_item_and_when_a_settled_one_is_compared() -> None:
    """m-4..m-7, Nit 8: the provisional item's figures, its group, the comparison again each
    pass, the flag cleared within the bound, and the cases below the rounding step."""
    missing = _missing(
        _s813(),
        "its `qty` is the size its closing fills close (their `c`, never `exec_qty`), its "
        "`avg_exit_price` their size-weighted price and its `avg_entry_price` the walk's average "
        "entry, `leverage` is absent, its `net_pnl` is the sum of the local figures present, and "
        "one without a `gross_pnl` is not served until its record is read.",
        "and `net_pnl` is `closed_pnl` from then on, authoritative.",
        "An item's trade group is its position's: the group of the walk's opening orders' leg "
        "(the first's, when they differ), else of its closing fills' leg, else of its closing "
        "order's leg.",
        "a later comparison within the bound clears the flag and writes no record.",
        "which each sync pass makes again for the settled items its read covers",
        "each pass compares again the settled items its read covers, idempotent by the recorded "
        "pair.",
        "shipped **unvalidated** until #843, whose captures also judge the two cases where it "
        "falls below the 8-decimal rounding step, with no floor added (the ruling fixed `1e-8`): "
        "a record under 1 USDT (|`closed_pnl`| < 1), where the rounding of the opening share "
        "alone, or any difference from a venue figure of 0, is divergent; and an entry price "
        "below about 0.5, where the venue's 8-decimal `avgEntryPrice` alone fails the entry gate",
    )
    assert missing == []


def test_contract_21_guards_the_record_and_stores_the_walks_inputs() -> None:
    """M-1, M-2, Nit 9: `final_at` freezes the venue's columns, a settled row holds them all, no
    row is deleted, and `executions` and `position_snapshots` gain the walk's two inputs."""
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
        "CREATE INDEX ix_cpr_pending ON closed_pnl_records (exchange_account_id) WHERE final_at "
        "IS NULL AND exchange_order_id IS NOT NULL;",
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
        "a later read that differs is then logged and counted, never applied.",
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
    )
    assert missing == []
    flats = _between(doc, "#### 3.3.7 ", "\n#### 3.3.8 ")
    missing = _missing(
        flats,
        "ALTER TABLE position_snapshots ADD COLUMN exchange_updated_ts timestamptz;",
        "CREATE INDEX CONCURRENTLY ix_psnap_flat ON position_snapshots (exchange_account_id, "
        "symbol, position_idx, exchange_updated_ts) WHERE size = 0 AND exchange_updated_ts IS NOT "
        "NULL;",
    )
    assert missing == []
    for row, index in ((54, "ix_cpr_pending"), (55, "ix_psnap_flat")):
        assert re.search(rf"^\| {row} +\| Closed-PnL [^|]+\|[^|]+\| `{index}` ", doc, re.M), row


def test_contract_22_pins_the_window_parameter_the_filters_and_the_stand_in() -> None:
    """m-1, m-4, Nits 1, 2, 4, 5, 13, 14: the operation's words a later slice serves."""
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
        "and so is a window read whose accounts, named or granted, number more than 25. Without "
        "`window`, `from` and `to` bound `closed_at`.",
        "a client keys rows by `id`.",
        "An item's trade group is its position's, that of its opening orders' leg, else its "
        "closing fills', else its closing order's (24 §8.13)",
        "It ignores `window`, `side` and `trade_group_id`, as a list ignores a parameter it does "
        "not know, refuses a second `symbol` (`400 validation_failed`)",
    )
    assert missing == []
    content = _OPERATION["responses"]["200"]["content"]["application/json"]
    assert "once E29-K01 (#843) records funding" in content["examples"]["today"]["summary"]
    assert "in ascending `exchange_account_id` order" in " ".join(
        _SCHEMAS["ClosedPnlTotals"]["properties"]["by_account"]["description"].split()
    )


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
