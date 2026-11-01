"""The web orders goldens (E29-S02, #912; BQ-1, BQ-3, BQ-4, BQ-6, BQ-7, BQ-17): what the web
client's working-orders contract and store tests read, written through the shipped code, never by
hand (C-13.5).

``packages/fixtures/golden/orders/`` holds the `orders` topic's snapshot and its deltas (an order's
first steps, the three `change: "amend"` steps of BQ-1 and the amend's transport fault, a cancel
that a fill beats, a cancel the venue answers 110001 and reconciliation resolves, an untracked
order adopted, an order held, and a late frame), one contract-valid extension, the
``listOrders?open_only=true`` body with the held and the untracked order the snapshot never carries
(23 §6.2.3), the ``cancelAllOrders`` 200 for five accounts of which three succeed, and the two
request bodies the writes will send.

The rows are OMS rows (24 §8.1) holding E29-D02 §6.2's fixture values: an order row is the OMS's
own, never an exchange payload, so no capture starts them. They go through the shipped chain:
``change_of`` and ``order_item`` (the topic), the topic's closed rule (``OPEN_STATES``: a closed
step is also `removed`, ``OmsTopics._fan_out``), ``order_document`` (the REST mapper), the
cancel-all route's ``_result``, and the routes' own body readers ``_terms`` and ``_request``.
``manifest.json`` names the sources and each mapper's commit.

Regenerate from ``services/api`` and review the diff (nothing is written otherwise):
``CV_REGEN_GOLDEN=1 uv run pytest tests/unit/oms/test_orders_web_golden.py``. Without it the test
rebuilds every file in memory and compares it byte for byte, so a mapper whose output moves fails
here until the goldens are regenerated with it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.oms_reads import order_document
from candleviewer.api.order_cancel_all import _request, _result
from candleviewer.api.order_exits import _terms
from candleviewer.domain.primitives import Environment
from candleviewer.oms.cancel_all import AccountCancels, AccountError, CancelAllOutcome
from candleviewer.oms.order_steps import CommittedOrderStep
from candleviewer.oms.ws_topics import change_of, epoch_ms, order_item
from candleviewer.storage.repositories.oms_reads import ListedOrder
from candleviewer.storage.repositories.orders import (
    OPEN_STATES,
    ORDER_STATE_OF,
    LifecycleState,
    OrderEventKind,
    OrderRow,
)

ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / "packages/fixtures/golden/orders"
REGEN = os.environ.get("CV_REGEN_GOLDEN") == "1"
REGEN_CMD = "CV_REGEN_GOLDEN=1 uv run pytest tests/unit/oms/test_orders_web_golden.py"
ENV: Environment = "live"
#: The read's start that stamps each account's snapshot view, and the deltas after it (23 §6.2.3).
READ_AT = datetime(2026, 10, 31, 14, 2, 11, tzinfo=UTC)

MAIN = UUID("a1000000-0000-4000-8000-000000000001")
SUB1 = UUID("a1000000-0000-4000-8000-000000000002")
SUB2 = UUID("a1000000-0000-4000-8000-000000000003")
SUB3 = UUID("a1000000-0000-4000-8000-000000000004")
SUB4 = UUID("a1000000-0000-4000-8000-000000000005")
#: The three accounts of the positions goldens, and two more for the five-account cancel-all.
LABELS: Mapping[UUID, str] = {
    MAIN: "Main",
    SUB1: "Sub-1",
    SUB2: "Sub-2",
    SUB3: "Sub-3",
    SUB4: "Sub-4",
}
GROUP = UUID("0c000000-0000-4000-8000-000000000001")
LEG = UUID("0b000000-0000-4000-8000-000000000001")
#: D02 §6.2's "Bracket · #7c1e": the Sub-1 entry's parent.
BRACKET = UUID("7c1e0000-0000-4000-8000-000000000001")


def oid(n: int) -> UUID:
    return UUID(f"0e000000-0000-4000-8000-{n:012d}")


#: 24 §8.3's `OUR_ID` purpose code, by intent, as the generated `Order` pattern admits it.
_PURPOSE: Mapping[str, str] = {"entry": "en", "stop_loss": "sl", "take_profit": "tp"}


def link_id(order_id: UUID, intent: str) -> str:
    """A fixture `OUR_ID` (24 §8.3): the scheme's shape, deterministic per order, never a key's."""
    return f"cvl-0E29S02xOrder{int(order_id.hex[-4:], 16):09d}-Fx12-00{_PURPOSE[intent]}"


TP, ENTRY, ETH, COND, STOP, HELD, UNTRACKED, NEW, ADOPTED = (oid(n) for n in range(1, 10))


def row(
    order_id: UUID, account: UUID, symbol: str, side: str, intent: str, order_type: str,
    qty: str, chart: LifecycleState, created: timedelta, **over: Any,
) -> OrderRow:  # fmt: skip
    """An open OMS row with D02 §6.2's values: `chart` its B1 state, stored as 24 §8.2 maps it."""
    quantity = Decimal(qty)
    base: dict[str, Any] = {
        "id": order_id, "trade_group_leg_id": None, "exchange_account_id": account,
        "parent_order_id": None, "oco_group_ref": None,
        "order_link_id": link_id(order_id, intent),
        "exchange_order_id": f"8a1f0f9c-3d2e-4b11-9f77-{order_id.hex[-12:]}", "symbol": symbol,
        "side": side, "intent": intent, "order_type": order_type, "qty": quantity, "price": None,
        "trigger_price": None, "trigger_by": None, "trigger_direction": None, "take_profit": None,
        "stop_loss": None, "tpsl_mode": "Full", "time_in_force": "GTC", "reduce_only": False,
        "close_on_trigger": False, "position_idx": 0, "state": ORDER_STATE_OF[chart],
        "cum_exec_qty": Decimal("0"), "cum_exec_value": Decimal("0"), "avg_price": None,
        "leaves_qty": quantity, "fee_paid": Decimal("0"), "reject_code": None,
        "reject_message": None, "submit_attempts": 1, "idempotency_state": "acked",
        "created_ts": READ_AT - created, "submitted_ts": READ_AT - created,
        "exchange_created_ts": READ_AT - created, "exchange_updated_ts": READ_AT - created,
        "last_reconciled_at": None, "is_paper": False, "lifecycle_state": chart,
        "provenance": "placed",
    }  # fmt: skip
    base.update(over)
    return OrderRow(**base)


def open_rows() -> list[OrderRow]:
    """D02 §6.2's five open rows: three Working, two Conditional (the second a native stop)."""
    return [
        row(TP, MAIN, "BTCUSDT", "Sell", "take_profit", "Limit", "0.250", "submitted",
            timedelta(hours=1, minutes=12), price=Decimal("64800.0"), reduce_only=True),
        row(ENTRY, SUB1, "BTCUSDT", "Buy", "entry", "Limit", "0.150", "partially_filled",
            timedelta(minutes=4), price=Decimal("63950.0"), cum_exec_qty=Decimal("0.050"),
            cum_exec_value=Decimal("3197.50"), avg_price=Decimal("63950.0"),
            leaves_qty=Decimal("0.100"), parent_order_id=BRACKET, trade_group_leg_id=LEG),
        row(ETH, SUB2, "ETHUSDT", "Buy", "entry", "Limit", "1.00", "submitted",
            timedelta(seconds=38), price=Decimal("2500.00"), time_in_force="PostOnly",
            position_idx=1),
        row(COND, SUB1, "BTCUSDT", "Buy", "entry", "Limit", "0.100", "submitted",
            timedelta(minutes=9), price=Decimal("64520.0"), trigger_price=Decimal("64500.0"),
            trigger_by="LastPrice", trigger_direction=1),
        # a recorded stop's TP/SL order: its push carries no trigger direction (BQ-17)
        row(STOP, SUB2, "BTCUSDT", "Sell", "stop_loss", "Market", "0.080", "submitted",
            timedelta(hours=2, minutes=5), trigger_price=Decimal("63950.0"),
            trigger_by="MarkPrice", reduce_only=True, close_on_trigger=True, tpsl_mode="Partial",
            position_idx=1, provenance="recorded_stop"),
    ]  # fmt: skip


def unowned_rows() -> list[OrderRow]:
    """The held and the untracked order: open on REST (`open_only`), never in the snapshot."""
    return [
        row(HELD, MAIN, "SOLUSDT", "Buy", "entry", "Limit", "10.0", "held",
            timedelta(minutes=20), price=Decimal("150.00")),
        row(UNTRACKED, SUB1, "SOLUSDT", "Sell", "entry", "Limit", "5.0", "untracked",
            timedelta(minutes=50), price=Decimal("155.00"), provenance="reconciliation",
            order_link_id="ext-" + "5" * 32, submit_attempts=0),
    ]  # fmt: skip


def stamp(offset_ms: int) -> int:
    return epoch_ms(READ_AT) + offset_ms


def frame(step: CommittedOrderStep, at: int) -> dict[str, Any]:
    """The frame a non-`open_only` subscription gets for one step (`OmsTopics._order_changes`,
    `_fan_out`): the item, and the order's id in `removed` when the step closes it."""
    item = order_item(step.order, environment=ENV, stamp=at, change=change_of(step))
    if step.order.state in OPEN_STATES:
        return {"orders": [item]}
    return {"orders": [item], "removed": [str(step.order.id)]}


def to(order: OrderRow, chart: LifecycleState, **over: Any) -> OrderRow:
    """The row after a step into `chart`, its other columns as `over` sets them."""
    return replace(order, state=ORDER_STATE_OF[chart], lifecycle_state=chart, **over)


def step(order: OrderRow, kind: OrderEventKind, before: OrderRow | None) -> CommittedOrderStep:
    return CommittedOrderStep(
        order=order, kind=kind, from_state=None if before is None else before.state
    )


def ws_snapshot(rows: Sequence[OrderRow]) -> dict[str, Any]:
    """`{"orders": [...]}`: each account's view, accounts in id order, each stamped with its read's
    start, one millisecond apart (`TopicReads.read`, `_snapshot`)."""
    items: list[dict[str, Any]] = []
    for n, account in enumerate(sorted({r.exchange_account_id for r in rows})):
        mine = [r for r in rows if r.exchange_account_id == account]
        items.extend(order_item(r, environment=ENV, stamp=stamp(n)) for r in mine)
    return {"orders": items}


def ws_deltas(rows: Sequence[OrderRow]) -> list[dict[str, Any]]:
    """The steps after the snapshot, each a frame as the topic sends it (module docstring)."""
    tp, entry, eth, cond = rows[0], rows[1], rows[2], rows[3]
    validated = row(NEW, MAIN, "ETHUSDT", "Buy", "entry", "Limit", "0.50", "validated",
                    timedelta(0), price=Decimal("2480.00"), exchange_order_id=None,
                    idempotency_state="unsent", submit_attempts=0,
                    created_ts=READ_AT + timedelta(milliseconds=500))  # fmt: skip
    sending = to(validated, "submitting", idempotency_state="in_flight", submit_attempts=1)
    acked = to(sending, "submitted", idempotency_state="acked",
               exchange_order_id="8a1f0f9c-3d2e-4b11-9f77-000000000008")  # fmt: skip
    amending = to(eth, "amend_pending")
    amended = to(eth, "submitted", price=Decimal("2495.00"))
    kept = to(eth, "submitted")
    unconfirmed = to(eth, "unknown")
    cancelling = to(tp, "cancel_pending")
    filled = to(tp, "filled", cum_exec_qty=Decimal("0.250"), cum_exec_value=Decimal("16200.000"),
                avg_price=Decimal("64800.0"), leaves_qty=Decimal("0"))  # fmt: skip
    parked = to(tp, "unknown")
    adopted = row(ADOPTED, SUB2, "BTCUSDT", "Buy", "entry", "Limit", "0.010", "untracked",
                  timedelta(minutes=1), price=Decimal("60000.0"), provenance="reconciliation",
                  order_link_id="ext-" + "a" * 32, submit_attempts=0)  # fmt: skip
    held = to(cond, "held")
    late = replace(entry, cum_exec_qty=Decimal("0.020"), leaves_qty=Decimal("0.130"))
    steps: list[tuple[str, CommittedOrderStep, int]] = [
        ("created", step(validated, "local_create", None), 500),
        ("submitted", step(sending, "submit_attempt", validated), 600),
        ("acked", step(acked, "ack", sending), 700),
        ("amend_request", step(amending, "amend_request", eth), 1000),
        ("amend_accepted", step(amended, "amend_ack", amending), 2000),
        ("amend_rejected", step(kept, "amend_ack", amending), 2000),
        ("amend_unknown", step(unconfirmed, "error", amending), 2000),
        ("cancel_request", step(cancelling, "cancel_request", tp), 3000),
        ("cancel_lost_race", step(filled, "fill", cancelling), 4000),
        ("cancel_110001", step(parked, "error", cancelling), 4000),
        ("reconcile_filled", step(filled, "reconcile_diff", parked), 6000),
        ("untracked_adopted", step(adopted, "adopt", None), 7000),
        ("held", step(held, "reconcile_diff", cond), 8000),
    ]
    out = [{"case": case, "body": frame(done, stamp(at))} for case, done, at in steps]
    # older than the snapshot read: 23 §15 discards it
    late_item = order_item(late, environment=ENV, stamp=stamp(-1000))
    return [*out, {"case": "late", "body": {"orders": [late_item]}}]


def contract_fields(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """The snapshot with the two members 23 §15.1 allows and no producer sends (23 §6.2.3):
    the Sub-1 entry's bracket and its leg's trade group; every other order has neither."""
    items = []
    for item in snapshot["orders"]:
        mine = item["id"] == str(ENTRY)
        items.append({**item, "trade_group_id": str(GROUP) if mine else None,
                      "algo_kind": "bracket" if mine else "none"})  # fmt: skip
    return {"orders": items}


def rest_open(rows: Sequence[OrderRow]) -> dict[str, Any]:
    """`listOrders?open_only=true` 200: newest first by creation time (22), the leg's group with
    the Sub-1 entry."""
    listed = sorted(rows, key=lambda r: r.created_ts, reverse=True)
    items = [order_document(ListedOrder(r, GROUP if r.id == ENTRY else None), ENV) for r in listed]
    return {"items": items, "meta": {"next_cursor": None, "has_more": False, "count": len(items)}}


def cancel_all_partial() -> dict[str, Any]:
    """`cancelAllOrders` 200 (22 `BulkAccountResult`): three of five accounts succeed; Sub-2's
    venue never answered (nothing cancelled), Sub-4's timed out after one cancel."""
    outcome = CancelAllOutcome(accounts=(
        AccountCancels(MAIN, 4),
        AccountCancels(SUB1, 2),
        AccountCancels(SUB2, 0, AccountError("exchange_unavailable", retryable=False)),
        AccountCancels(SUB3, 3),
        AccountCancels(SUB4, 1, AccountError("timeout", retryable=True)),
    ))  # fmt: skip
    return _result(outcome)


#: The bodies the writes will send (PR 2 and PR 3): D02 §7's specimen amend, and a cancel-all over
#: the five accounts that keeps reduce-only exits (22's default, D02 §8.3).
AMEND_BODY: Mapping[str, Any] = {"price": "2495.00"}
CANCEL_ALL_BODY: Mapping[str, Any] = {
    "exchange_account_ids": [str(a) for a in (MAIN, SUB1, SUB2, SUB3, SUB4)],
    "exclude_reduce_only": True,
}


def bodies() -> dict[str, Any]:
    rows = open_rows()
    snapshot = ws_snapshot(rows)
    return {
        "ws_orders_snapshot.json": snapshot,
        "ws_orders_deltas.json": ws_deltas(rows),
        "ws_orders_contract_fields.json": contract_fields(snapshot),
        "rest_list_orders_open.json": rest_open([*rows, *unowned_rows()]),
        "rest_cancel_all_partial.json": cancel_all_partial(),
        "rest_amend_order_request.json": dict(AMEND_BODY),
        "rest_cancel_all_request.json": dict(CANCEL_ALL_BODY),
    }


def text(obj: object) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


MAPPERS: tuple[tuple[str, str], ...] = (
    ("candleviewer.oms.ws_topics.order_item", "oms/ws_topics.py"),
    ("candleviewer.oms.ws_topics.change_of", "oms/ws_topics.py"),
    ("candleviewer.storage.repositories.orders.OPEN_STATES", "storage/repositories/orders.py"),
    ("candleviewer.api.oms_reads.order_document", "api/oms_reads.py"),
    ("candleviewer.api.order_acceptance.order_body", "api/order_acceptance.py"),
    ("candleviewer.api.order_cancel_all._result", "api/order_cancel_all.py"),
    ("candleviewer.api.order_cancel_all._request", "api/order_cancel_all.py"),
    ("candleviewer.api.order_exits._terms", "api/order_exits.py"),
)
SHA = re.compile(r"[0-9a-f]{40}")


def mapper_commit(rel: str) -> str:
    """The last commit of the mapper's file (regeneration only: the check never runs git)."""
    git = shutil.which("git")
    assert git is not None
    path = f"services/api/candleviewer/{rel}"
    done = subprocess.run(  # noqa: S603 -- resolved absolute path, fixed argv, no shell
        [git, "log", "-1", "--format=%H", "--", path], cwd=ROOT, capture_output=True, text=True,
        check=True,
    )  # fmt: skip
    return done.stdout.strip()


def manifest(files: Mapping[str, str], commits: Mapping[str, str]) -> dict[str, Any]:
    return {
        "note": f"GENERATED - do not hand-edit. Regenerate from services/api with `{REGEN_CMD}` "
        "and review the diff.",
        "story": "E29-S02 (#912), BQ-1, BQ-3, BQ-4, BQ-6, BQ-7, BQ-17",
        "sources": {
            "rows": "OMS rows (24 §8.1) holding docs/design/E29/E29-D02.md §6.2's fixture values; "
            "no exchange capture: an order row is the OMS's own",
            "steps": "each delta is a committed step (`CommittedOrderStep`) framed as the topic "
            "frames it: `change_of`, `order_item`, and `removed` beside a step that closes it",
            "unowned": "the held and the untracked order of rest_list_orders_open.json: open on "
            "`listOrders?open_only=true`, never in the snapshot (23 §6.2.3; BQ-6)",
            "contract_fields": "ws_orders_contract_fields.json adds trade_group_id and algo_kind: "
            "23 §15.1 allows them and no producer sends them (23 §6.2.3)",
            "requests": "rest_amend_order_request.json and rest_cancel_all_request.json are the "
            "client's bodies, read by the routes' own readers (`_terms`, `_request`)",
        },
        "accounts": {str(a): label for a, label in LABELS.items()},
        "environment": ENV,
        "mappers": [
            {"function": fn, "path": f"services/api/candleviewer/{rel}", "commit": commits[rel]}
            for fn, rel in MAPPERS
        ],
        "files": [
            {"name": name, "sha256": hashlib.sha256(body.encode()).hexdigest()}
            for name, body in sorted(files.items())
        ],
    }  # fmt: skip


def without_commits(doc: Mapping[str, Any]) -> dict[str, Any]:
    return {**doc, "mappers": [{**m, "commit": None} for m in doc["mappers"]]}


def test_orders_web_golden_matches_the_shipped_mappers() -> None:
    files = {name: text(body) for name, body in bodies().items()}
    if REGEN:
        OUT.mkdir(parents=True, exist_ok=True)
        commits = {rel: mapper_commit(rel) for _, rel in MAPPERS}
        for name, body in {**files, "manifest.json": text(manifest(files, commits))}.items():
            (OUT / name).write_text(body, encoding="utf-8")
    for name, body in files.items():
        assert (OUT / name).read_text(encoding="utf-8") == body, f"{name} is stale: {REGEN_CMD}"
    kept = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    assert all(SHA.fullmatch(m["commit"]) for m in kept["mappers"])
    expected = manifest(files, {rel: "" for _, rel in MAPPERS})
    assert without_commits(kept) == without_commits(expected), f"manifest.json: {REGEN_CMD}"


def test_orders_web_golden_amend_steps_all_say_amend() -> None:
    """BQ-1's trap, from the shipped `change_of`: the request, the accepted and the rejected amend
    all carry `change: "amend"`; only the state and the price tell them apart, and a transport
    fault carries none."""
    cases = {d["case"]: d["body"]["orders"][0] for d in ws_deltas(open_rows())}
    request, accepted, rejected = (
        cases[c] for c in ("amend_request", "amend_accepted", "amend_rejected")
    )
    assert {request["change"], accepted["change"], rejected["change"]} == {"amend"}
    assert (request["lifecycle_state"], request["price"]) == ("amend_pending", "2500")
    assert (accepted["lifecycle_state"], accepted["price"]) == ("submitted", "2495")
    assert (rejected["lifecycle_state"], rejected["price"]) == ("submitted", "2500")
    assert "change" not in cases["amend_unknown"]
    assert cases["amend_unknown"]["lifecycle_state"] == "unknown"


def test_orders_web_golden_closed_steps_are_removed_and_the_snapshot_is_open() -> None:
    """A step out of the open set is `removed` too: a fill, reconciliation's fill, and also a
    step into `held` or `untracked` (neither is in `OPEN_STATES`); a 110001 park in `unknown`
    stays open. The snapshot holds open orders only, never held or untracked (23 §6.2.3)."""
    deltas = {d["case"]: d["body"] for d in ws_deltas(open_rows())}
    removed = {case for case, body in deltas.items() if "removed" in body}
    assert removed == {"cancel_lost_race", "reconcile_filled", "untracked_adopted", "held"}
    assert deltas["cancel_110001"]["orders"][0]["lifecycle_state"] == "unknown"
    snap = ws_snapshot(open_rows())["orders"]
    assert all(i["state"] in OPEN_STATES for i in snap)
    late = deltas["late"]["orders"][0]
    assert late["updated_at_ms"] < min(i["updated_at_ms"] for i in snap)
    assert all("trigger_direction" in i for i in snap)
    stop = next(i for i in snap if i["id"] == str(STOP))
    assert stop["trigger_direction"] is None  # BQ-17: the client derives it from the closing side


def test_orders_web_golden_rest_bodies_fit_the_generated_contract() -> None:
    """Each REST body validates against 22's generated models (`api._generated`), and the request
    bodies pass the routes' own strict readers."""
    files = bodies()
    for item in files["rest_list_orders_open.json"]["items"]:
        api.Order.model_validate(item)
    links = [i["order_link_id"] for i in files["rest_list_orders_open.json"]["items"]]
    assert all(len(link) <= 36 for link in links)  # 23 §15.1 `maxLength`
    states = {i["lifecycle_state"] for i in files["rest_list_orders_open.json"]["items"]}
    assert {"held", "untracked"} <= states
    api.BulkAccountResult.model_validate(files["rest_cancel_all_partial.json"])
    result = files["rest_cancel_all_partial.json"]
    assert (result["requested"], result["succeeded"]) == (5, 3)
    assert all(r["error"] is None or "ret_msg" not in r["error"] for r in result["results"])
    terms = _terms(json.dumps(AMEND_BODY).encode())
    assert terms.price == Decimal("2495.00")
    assert terms.qty is None and terms.trigger_price is None
    request = _request(json.dumps(CANCEL_ALL_BODY).encode())
    assert request.exclude_reduce_only is True
    assert len(request.exchange_account_ids) == 5
