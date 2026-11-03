"""The web fills goldens (E29-S04, #979, BQ-18): what the web client's fills and contract tests
read, written through the shipped code, never by hand (C-13.5).

``packages/fixtures/golden/executions/`` holds the `executions` topic's snapshot and one delta,
the `listExecutions` body and five `getOrder?include_events=true` bodies. Each fill of an order
starts as the recorded private `execution` push (``packages/fixtures/bybit/2026-10-05/ws/
private-execution.jsonl``, line 1), takes E29-D03 §3.4's values (boards 02, 04 and 05; board 02's
maker fill is split in two, so its order fills in four executions as the ticket's Gherkin says)
and goes through the shipped chain: ``classify`` and ``read_push`` (the adapter), ``exec_payload``
(B1's `EXEC`), ``apply_execution`` (the order's totals) and ``order_steps._fill`` (the fill's
write-ahead unit), then ``execution_item`` with ``_snapshot``, ``execution_document`` and, for the
orders, ``order_document`` with ``event_document``. The one fill of no order, an ADL fill, starts
as the recorded ``execution/list`` row (``.../rest/trading-execution-list.json``) and takes
reconciliation's store path (``parse``, ``to_execution``, ``reconciler.new_execution``). No
producer stores a funding fill yet (the adapter sets one aside, D03 G5), so none is here.

Regenerate from ``services/api`` and review the diff (nothing is written otherwise):
``CV_REGEN_GOLDEN=1 uv run pytest tests/unit/oms/test_executions_web_golden.py``. Without it the
test rebuilds every file in memory and compares it byte for byte.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.oms_reads import event_document, execution_document, order_document
from candleviewer.domain.order_link import account_tag
from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.exchange.base.models import AccountRef, Execution
from candleviewer.exchange.bybit.private_parse import Push, classify, read_push
from candleviewer.exchange.bybit.trading_parse import ExecutionRow as VenueRow
from candleviewer.exchange.bybit.trading_parse import parse, to_execution
from candleviewer.oms.execution import Fill, OrderFills, apply_execution
from candleviewer.oms.order_steps import _fill
from candleviewer.oms.push_mapping import exec_payload, money_text
from candleviewer.oms.reconciler import new_execution
from candleviewer.oms.ws_topics import EXECUTIONS, View, _snapshot, epoch_ms, execution_item
from candleviewer.statechart.bindings.b01_order import Step
from candleviewer.storage.repositories.executions import ExecutionRow, NewExecution
from candleviewer.storage.repositories.oms_reads import ListedExecution, ListedOrder
from candleviewer.storage.repositories.orders import (
    NewOrderEvent,
    OrderEventKind,
    OrderEventRow,
    OrderRow,
    OrderState,
    OrderTransition,
)

ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / "packages/fixtures/golden/executions"
PUSH = "packages/fixtures/bybit/2026-10-05/ws/private-execution.jsonl"
LIST = "packages/fixtures/bybit/2026-10-05/rest/trading-execution-list.json"
REGEN = os.environ.get("CV_REGEN_GOLDEN") == "1"
REGEN_CMD = "CV_REGEN_GOLDEN=1 uv run pytest tests/unit/oms/test_executions_web_golden.py"
ENV: Environment = "live"
DAY = datetime(2026, 10, 22, tzinfo=UTC)

MAIN = UUID("a1000000-0000-4000-8000-000000000001")
SUB1 = UUID("a1000000-0000-4000-8000-000000000002")
SUB2 = UUID("a1000000-0000-4000-8000-000000000003")
LABELS = {MAIN: "Main", SUB1: "Sub-1", SUB2: "Sub-2"}
#: D03 §3.4 board 04's trade group ("…7c1e").
GROUP = UUID("0c000000-0000-4000-8000-000000007c1e")
#: D03 §1.4's fee rates: 0.0550 % taker, 0.0200 % maker.
TAKER, MAKER = "0.00055", "0.0002"


def at(h: int, m: int, s: int, ms: int) -> datetime:
    return DAY.replace(hour=h, minute=m, second=s, microsecond=ms * 1000)


@dataclass(frozen=True)
class F:
    """One fill: the venue's exec id, price, qty, maker flag, time and closed PnL."""

    exec_id: str
    price: str
    qty: str
    maker: bool
    at: datetime
    pnl: str | None = None


@dataclass(frozen=True)
class Spec:
    """One order (D03 §3.4) and its fills, oldest first; `case` names its `getOrder` body."""

    case: str | None
    id: UUID
    account: UUID
    side: Literal["Buy", "Sell"]
    kind: Literal["Limit", "Market"]
    qty: str
    price: str | None
    trigger: str | None
    intent: Literal["entry", "stop_loss", "take_profit", "flatten"]
    placed: datetime
    fills: tuple[F, ...]
    group: UUID | None = None
    amended: bool = False


def oid(tail: str) -> UUID:
    return UUID(f"0a000000-0000-4000-8000-{tail:0>12}")


X = "7f3c9a1e-4219-438b-b30a-32ec8630"  # the venue's exec ids: "7f3c9a1e…" (D03 §1.4)
ORDERS: tuple[Spec, ...] = (
    Spec("market", oid("6d01"), MAIN, "Sell", "Market", "0.5", None, None, "flatten",
         at(13, 40, 0, 300), (F(f"{X}0001", "95900.1", "0.5", False, at(13, 40, 0, 353), "0.05"),)),
    Spec("amended", oid("5a01"), MAIN, "Buy", "Limit", "0.100", "63400.0", None, "entry",
         at(13, 50, 20, 0), (F(f"{X}0002", "63399.6", "0.100", False, at(13, 50, 21, 6)),),
         amended=True),
    Spec("at_limit", oid("5e01"), SUB1, "Buy", "Limit", "0.250", "64250.0", None, "entry",
         at(13, 58, 1, 0), (F(f"{X}0003", "64250.0", "0.250", True, at(13, 58, 2, 214)),)),
    Spec("limit", oid("a3f2"), MAIN, "Buy", "Limit", "0.250", "63420.0", None, "entry",
         at(14, 2, 10, 0), (
             F(f"{X}0004", "63410.0", "0.100", False, at(14, 2, 11, 418)),
             F(f"{X}0005", "63414.5", "0.090", False, at(14, 2, 11, 418)),
             F(f"{X}0006", "63420.0", "0.030", True, at(14, 2, 11, 903)),
             F(f"{X}0007", "63420.0", "0.030", True, at(14, 2, 12, 517)),
         )),
    Spec("stop_exit", oid("91c4"), SUB1, "Sell", "Market", "0.250", None, "63900.0", "stop_loss",
         at(13, 58, 3, 0), (
             F(f"{X}0008", "63885.0", "0.150", False, at(14, 3, 39, 861), "-54.75"),
             F(f"{X}0009", "63872.5", "0.100", False, at(14, 3, 40, 0), "-37.75"),
         )),
    Spec(None, oid("4c01"), MAIN, "Buy", "Limit", "0.300", "63500.0", None, "entry",
         at(14, 5, 2, 0), (F(f"{X}0010", "63495.0", "0.200", False, at(14, 5, 2, 640)),
                           F(f"{X}0011", "63500.0", "0.100", True, at(14, 5, 3, 112))),
         group=GROUP),
    Spec(None, oid("4c02"), SUB1, "Buy", "Limit", "0.200", "63500.0", None, "entry",
         at(14, 5, 2, 0), (F(f"{X}0012", "63498.5", "0.200", False, at(14, 5, 2, 655)),),
         group=GROUP),
    Spec(None, oid("4c03"), SUB2, "Buy", "Limit", "0.100", "63500.0", None, "entry",
         at(14, 5, 2, 0), (F(f"{X}0013", "63500.0", "0.100", True, at(14, 5, 3, 120)),),
         group=GROUP),
)  # fmt: skip
#: The fill the `executions` delta brings after the snapshot: board 02's last.
DELTA = f"{X}0007"
#: The ADL fill reconciliation stores with no order (D03 §3.6's type sampler), on Sub-2.
ADL_AT = at(14, 10, 0, 0)
ADL = {"symbol": "BTCUSDT", "side": "Sell", "execType": "AdlTrade", "execPrice": "63450.0",
       "execQty": "0.050", "execValue": "3172.5", "execFee": "0", "feeRate": "0",
       "execId": f"{X}0014", "execTime": str(epoch_ms(ADL_AT))}  # fmt: skip

MAPPERS: tuple[tuple[str, str], ...] = (
    ("candleviewer.exchange.bybit.private_parse.read_push", "exchange/bybit/private_parse.py"),
    ("candleviewer.exchange.bybit.trading_parse.to_execution", "exchange/bybit/trading_parse.py"),
    ("candleviewer.oms.push_mapping.exec_payload", "oms/push_mapping.py"),
    ("candleviewer.oms.execution.apply_execution", "oms/execution.py"),
    ("candleviewer.oms.order_steps._fill", "oms/order_steps.py"),
    ("candleviewer.oms.reconciler.new_execution", "oms/reconciler.py"),
    ("candleviewer.oms.ws_topics.execution_item", "oms/ws_topics.py"),
    ("candleviewer.api.oms_reads.execution_document", "api/oms_reads.py"),
)
SHA = re.compile(r"[0-9a-f]{40}")


def account_ref(account: UUID) -> AccountRef:
    n = list(LABELS).index(account) + 1
    key = f"00000000-0000-4000-8000-{n:012d}"  # an opaque handle, never a key (C-2.7)
    return AccountRef(
        account_id=AccountId(account), uid=f"1000000{n}", environment=ENV, key_ref=key
    )


def link(spec: Spec) -> str:
    """A 24 §8.3 `OUR_ID` for the order: its own `group22`, its account's tag, a purpose suffix."""
    purpose = "sl" if spec.intent == "stop_loss" else "en"
    tag = account_tag(AccountId(spec.account))
    return f"cvl-0TLr6mSAQFGvyfsJ0n{str(spec.id)[-4:]}-{tag}-00{purpose}"


def xid(spec: Spec) -> str:
    return f"9aac161b-8ed6-450d-9cab-{str(spec.id)[-12:]}"


def pushed(spec: Spec, fill: F) -> Execution:
    """The recorded push with this fill's values, through the adapter's parse."""
    frame: dict[str, Any] = json.loads((ROOT / PUSH).read_text(encoding="utf-8").splitlines()[0])
    stamp = epoch_ms(fill.at)
    rate = MAKER if fill.maker else TAKER
    value = Decimal(fill.price) * Decimal(fill.qty)
    row = {**frame["data"][0], "execId": fill.exec_id, "orderId": xid(spec),
           "orderLinkId": link(spec), "side": spec.side, "execPrice": fill.price,
           "execQty": fill.qty, "execValue": str(value), "execFee": str(value * Decimal(rate)),
           "feeRate": rate, "isMaker": fill.maker, "execTime": str(stamp),
           "orderType": spec.kind, "orderQty": spec.qty, "orderPrice": spec.price or "0",
           "closedSize": fill.qty if fill.pnl else "0", "execPnl": fill.pnl or "0",
           "leavesQty": "0"}  # fmt: skip
    push = classify(json.dumps({**frame, "creationTime": stamp, "data": [row]}))
    assert isinstance(push, Push)  # a topic frame is a push, never a reply
    (event,) = read_push(push, account_ref(spec.account), now_us=stamp * 1000)
    assert isinstance(event.payload, Execution)
    return event.payload


def stored(new: NewExecution, n: int, recv: datetime) -> ExecutionRow:
    kept = {f.name: getattr(new, f.name) for f in fields(NewExecution)}
    return ExecutionRow(**kept, id=UUID(f"0e000000-0000-4000-8000-{n:012d}"), recv_ts=recv)


def filled(spec: Spec, first: int) -> tuple[list[ExecutionRow], OrderFills]:
    """The order's fills as the fill step stores them, and its totals after the last."""
    totals, rows = OrderFills(qty=Decimal(spec.qty)), []
    for k, fill in enumerate(spec.fills):
        execution = pushed(spec, fill)
        totals = apply_execution(totals, Fill(execution.qty, execution.price, execution.fee,
                                              execution.fee_rate))  # fmt: skip
        assert totals.avg_price is not None
        done = totals.filled_qty == totals.qty
        context = {"filled_qty": money_text(totals.filled_qty),
                   "cum_exec_value": money_text(totals.cum_exec_value),
                   "avg_price": money_text(totals.avg_price),
                   "fee_paid": money_text(totals.fee_paid)}  # fmt: skip
        payload = exec_payload(execution, order_id=spec.id, order_link_id=link(spec))
        to: OrderState = "filled" if done else "partially_filled"
        step = Step(str(spec.id), str(spec.account), link(spec), "submitted", to, "EXEC",
                    payload, context)  # fmt: skip
        event = NewOrderEvent(kind="fill" if done else "partial_fill", source="ws_private",
                              event_ts=fill.at, payload=payload)  # fmt: skip
        move = OrderTransition(account_id=spec.account, order_id=spec.id,
                               from_state="partially_filled" if k else "accepted", to_state=to,
                               event=event)  # fmt: skip
        rows.append(stored(_fill(step, move).execution, first + k, fill.at))
    return rows, totals


def order_row(spec: Spec, totals: OrderFills) -> OrderRow:
    last = spec.fills[-1].at
    trigger = None if spec.trigger is None else Decimal(spec.trigger)
    return OrderRow(
        id=spec.id, trade_group_leg_id=None, exchange_account_id=spec.account,
        parent_order_id=None, oco_group_ref=None, order_link_id=link(spec),
        exchange_order_id=xid(spec), symbol="BTCUSDT", side=spec.side, intent=spec.intent,
        order_type=spec.kind, qty=Decimal(spec.qty),
        price=None if spec.price is None else Decimal(spec.price), trigger_price=trigger,
        trigger_by=None if trigger is None else "LastPrice",
        trigger_direction=None if trigger is None else 2, take_profit=None, stop_loss=None,
        tpsl_mode="Full", time_in_force="GTC", reduce_only=spec.intent != "entry",
        close_on_trigger=trigger is not None, position_idx=0, state="filled",
        cum_exec_qty=totals.filled_qty, cum_exec_value=totals.cum_exec_value,
        avg_price=totals.avg_price, leaves_qty=totals.leaves_qty, fee_paid=totals.fee_paid,
        reject_code=None, reject_message=None, submit_attempts=1, idempotency_state="acked",
        created_ts=spec.placed, submitted_ts=spec.placed, exchange_created_ts=spec.placed,
        exchange_updated_ts=last, last_reconciled_at=None, is_paper=False,
        lifecycle_state="filled", provenance="placed",
    )  # fmt: skip


def events(spec: Spec, base: int) -> list[OrderEventRow]:
    """The order's chain (24 §8.2): created, sent, acknowledged, an amend when it had one, and
    one event per fill, the last `fill`."""
    head: list[tuple[OrderEventKind, datetime]] = [("local_create", spec.placed),
        ("submit_attempt", spec.placed + timedelta(milliseconds=40)),
        ("ack", spec.placed + timedelta(milliseconds=180))]  # fmt: skip
    if spec.amended:
        head += [("amend_request", spec.placed + timedelta(milliseconds=600)),
                 ("amend_ack", spec.placed + timedelta(milliseconds=750))]  # fmt: skip
    fills: list[tuple[OrderEventKind, datetime]] = [("partial_fill", f.at) for f in spec.fills]
    kinds = [*head, *fills[:-1], ("fill", spec.fills[-1].at)]
    return [
        OrderEventRow(id=base + n, order_id=spec.id, order_link_id=link(spec), seq=n,
                      kind=kind, from_state=None, to_state=None,
                      source="local" if n < 2 else "ws_private", payload={}, ret_code=None,
                      ret_msg=None, latency_ms=None, event_ts=ts, recv_ts=ts)
        for n, (kind, ts) in enumerate(kinds)
    ]  # fmt: skip


def adl_row(n: int) -> ExecutionRow:
    """The recorded `execution/list` row with D03's ADL values, as reconciliation stores it."""
    reply = json.loads((ROOT / LIST).read_text(encoding="utf-8"))
    raw = {**reply["result"]["list"][0], **ADL}
    venue = parse(VenueRow, raw, "execution")
    execution = to_execution(venue, account_ref(SUB2), ts_ingest=epoch_ms(ADL_AT) * 1000)
    return stored(new_execution(execution), n, ADL_AT)


@dataclass(frozen=True)
class Sub:
    """The fields of a WS subscription `_snapshot` reads (`ws_topics.TopicSub`)."""

    ch: str
    accounts: frozenset[UUID]
    effective: Mapping[str, Any]


def bodies() -> dict[str, Any]:
    rows: list[tuple[ExecutionRow, UUID | None]] = []
    gets: list[dict[str, Any]] = []
    for spec in ORDERS:
        fills, totals = filled(spec, len(rows) + 1)
        rows += [(r, spec.group) for r in fills]
        if spec.case is not None:
            body = order_document(ListedOrder(order_row(spec, totals), spec.group), ENV)
            body["executions"] = [execution_document(ListedExecution(r, spec.group)) for r in fills]
            body["events"] = [event_document(e) for e in events(spec, 100 * len(gets) + 1)]
            gets.append({"case": spec.case, "body": body})
    rows.append((adl_row(len(rows) + 1), None))
    newest = sorted(rows, key=lambda r: (r[0].exec_ts, r[0].id), reverse=True)  # the SQL keyset
    items = [execution_document(ListedExecution(r, g)) for r, g in newest]
    ws = {r.exec_id: execution_item(r, environment=ENV) for r, _ in rows}
    held = [i for i in ws.values() if i is not None and i["exec_id"] != DELTA]
    views = [View(0, tuple(i for i in held if i["exchange_account_id"] == str(a))) for a in LABELS]
    sub = Sub(EXECUTIONS, frozenset(LABELS), {"exchange_account_ids": [str(a) for a in LABELS]})
    return {
        "ws_executions_snapshot.json": _snapshot(EXECUTIONS, sub, views),
        "ws_executions_deltas.json": [{"case": "new", "body": {"executions": [ws[DELTA]]}}],
        "rest_list_executions.json": {
            "items": items, "meta": {"next_cursor": None, "has_more": False, "count": len(items)},
        },
        "rest_get_order.json": gets,
    }  # fmt: skip


def text(obj: object) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


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
        "story": "E29-S04 (#979), BQ-18",
        "sources": {
            "capture": f"{PUSH}, line 1 (a Market `execution` push), the frame every fill of an "
            "order starts from",
            "no_order": f"{LIST}, its one row, the ADL fill reconciliation stores with no order",
            "values": "docs/design/E29/E29-D03.md §3.4, boards 02, 04 and 05 (board 02's maker "
            "fill split in two: four executions); the market order's fill keeps the capture's "
            "values",
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


def test_executions_web_golden_matches_the_shipped_mappers() -> None:
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


def test_executions_web_golden_d03_arithmetic_holds_on_the_stored_totals() -> None:
    """D03 §3.4: board 02's Σ value 15,853.505 over 0.250 is 63,414.02, its fees 7.38760775."""
    rows, totals = filled(ORDERS[3], 1)
    assert (totals.filled_qty, totals.cum_exec_value) == (Decimal("0.250"), Decimal("15853.505"))
    assert (totals.avg_price, totals.fee_paid) == (Decimal("63414.02"), Decimal("7.38760775"))
    assert [r.is_maker for r in rows] == [False, False, True, True]


def test_executions_web_golden_ws_never_carries_the_fill_of_no_order() -> None:
    """23 §15.3 requires `order_id`: the ADL fill is REST's alone (D03 G20)."""
    files = bodies()
    snap = files["ws_executions_snapshot.json"]["executions"]
    rest = files["rest_list_executions.json"]["items"]
    assert ADL["execId"] not in {i["exec_id"] for i in snap}
    assert [i for i in rest if "order_id" not in i] == [
        next(i for i in rest if i["exec_id"] == ADL["execId"])
    ]
    assert [i["ts_ms"] for i in snap] == sorted(i["ts_ms"] for i in snap)  # oldest first


def test_executions_web_golden_rest_bodies_fit_the_generated_contract() -> None:
    """Each REST body validates against 22's generated models (`api._generated`)."""
    files = bodies()
    for item in files["rest_list_executions.json"]["items"]:
        api.Execution.model_validate(item)
    for case in files["rest_get_order.json"]:
        api.OrderWithEvents.model_validate(case["body"])
