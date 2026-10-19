"""Pure measurement maths: quantiles, frame items, the 23-ws S5 ordering checker, the backfill
diff, and the stream's down windows with the REST-only split they decide.

Synthetic frames use only the documented Bybit v5 private fields (`docs/research/06-bybit-api.md`
§10): `topic`, `creationTime`, `data[].orderId/orderStatus/cumExecQty/updatedTime` (order) and
`data[].orderId/execId/execQty/execTime/seq` (execution).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from spikes.oms_demo_path.stats import (
    GRACE_MS,
    RestExecution,
    WsItem,
    backfill_only,
    check_ordering,
    delivering_at,
    down_windows,
    items_from_frame,
    latencies,
    quantiles,
    rest_execution,
    split_rest_only,
)

T0 = 1_760_000_000_000


def _order(order_id: str, cum: str, at: int) -> dict[str, Any]:
    item = {"orderId": order_id, "orderStatus": "PartiallyFilled", "cumExecQty": cum}
    return {"topic": "order", "creationTime": at, "data": [item | {"updatedTime": str(at)}]}


def _execution(order_id: str, exec_id: str, qty: str, at: int, seq: int) -> dict[str, Any]:
    item = {"orderId": order_id, "execId": exec_id, "execQty": qty, "execTime": str(at)}
    return {"topic": "execution", "creationTime": at, "data": [item | {"seq": seq}]}


def _items(*frames: dict[str, Any]) -> list[WsItem]:
    """Frames in receipt order, each received 7 ms after the previous one."""
    out: list[WsItem] = []
    for n, frame in enumerate(frames):
        out += items_from_frame(frame, recv_seq=n, recv_ms=T0 + 100 + 7 * n)
    return out


def test_quantiles_use_the_nearest_rank() -> None:
    q = quantiles(float(v) for v in range(1, 101))
    assert (q.n, q.p50, q.p95, q.p99) == (100, 50.0, 95.0, 99.0)
    assert quantiles([]).p95 is None and quantiles([4.0]).p99 == 4.0


def test_items_from_frame_reads_order_and_execution_fields() -> None:
    order, execution = _items(_order("o1", "0.02", T0), _execution("o1", "e1", "0.02", T0 - 3, 9))
    assert (order.topic, order.qty, order.exch_ms, order.status) == (
        "order",
        Decimal("0.02"),
        T0,
        "PartiallyFilled",
    )
    assert (execution.exec_id, execution.qty, execution.exch_ms, execution.seq) == (
        "e1",
        Decimal("0.02"),
        T0 - 3,
        9,
    )
    assert items_from_frame({"op": "pong"}, recv_seq=0, recv_ms=T0) == []


def test_ordering_flags_an_execution_received_after_the_order_push_it_caused() -> None:
    items = _items(_order("o1", "0.02", T0), _execution("o1", "e1", "0.02", T0, 1))
    report = check_ordering(items, "execution")
    assert (report.executions, report.violations, report.unmatched) == (1, 1, 0)
    assert report.lag_ms.p95 == 7.0


def test_ordering_is_clean_when_each_execution_leads_its_order_push() -> None:
    items = _items(
        _execution("o1", "e1", "0.01", T0, 1),
        _order("o1", "0.01", T0),
        _execution("o1", "e2", "0.01", T0 + 5, 2),
        _order("o1", "0.02", T0 + 5),
    )
    report = check_ordering(items, "execution")
    assert (report.executions, report.violations, report.unmatched) == (2, 0, 0)


def test_ordering_dedupes_exec_ids_and_counts_an_execution_with_no_order_push() -> None:
    items = _items(
        _execution("o1", "e1", "0.01", T0, 1),
        _execution("o1", "e1", "0.01", T0, 1),
        _order("o1", "0.01", T0),
        _execution("o2", "e9", "0.01", T0, 3),
    )
    report = check_ordering(items, "execution")
    assert (report.executions, report.violations, report.unmatched) == (2, 0, 1)


def test_backfill_only_counts_rest_executions_the_stream_missed_by_type() -> None:
    rest = {
        e: RestExecution(t, T0) for e, t in (("e1", "Trade"), ("e2", "Trade"), ("e3", "Funding"))
    }
    assert backfill_only(rest, {"e1"}) == {"Trade": 1, "Funding": 1}
    assert backfill_only(rest, set(rest)) == {}


def test_rest_execution_keeps_the_type_and_the_exec_time() -> None:
    row = {"execId": "e1", "execType": "Trade", "execTime": str(T0)}
    assert rest_execution(row) == RestExecution("Trade", T0)
    assert rest_execution({"execType": "Funding"}).exec_ms is None


def test_down_windows_are_the_run_outside_every_live_span() -> None:
    live = [(T0 + 30, T0 + 40), (T0 + 10, T0 + 20)]
    assert down_windows(live, T0, T0 + 50) == [
        (T0, T0 + 10),
        (T0 + 20, T0 + 30),
        (T0 + 40, T0 + 50),
    ]
    assert down_windows([(T0 - 5, T0 + 60)], T0, T0 + 50) == []
    assert down_windows([], T0, T0 + 50) == [(T0, T0 + 50)]


@pytest.mark.parametrize(
    ("at", "delivering"),
    [
        (T0 + GRACE_MS - 1, False),
        (T0 + GRACE_MS, True),
        (T0 + 5_000, True),
        (T0 + 5_001, False),
        (None, None),
    ],
    ids=["inside-the-grace", "grace-ends", "last-frame", "after-the-last-frame", "no-time"],
)
def test_delivering_at_counts_a_span_from_its_grace_to_its_last_frame(
    at: int | None, delivering: bool | None
) -> None:
    assert delivering_at(at, [(T0, T0 + 5_000)]) is delivering


def test_split_rest_only_places_each_missed_execution_against_the_live_spans() -> None:
    live = [(T0, T0 + 5_000)]
    rest = {
        "streamed": RestExecution("Trade", T0 + 2_000),
        "connected": RestExecution("Trade", T0 + 3_000),
        "also connected": RestExecution("Trade", T0 + 4_000),
        "down": RestExecution("Trade", T0 + 9_000),
        "untimed": RestExecution("Funding", None),
    }
    split = split_rest_only(rest, {"streamed"}, live)
    assert split == {"while_connected": 2, "stream_down": 1, "no_exec_time": 1}


def test_latencies_run_from_the_exchange_stamp_to_receipt_per_topic() -> None:
    items = _items(_order("o1", "0.01", T0), _execution("o1", "e1", "0.01", T0 + 50, 1))
    by_topic = latencies(items)
    assert by_topic["order"].p50 == 100.0 and by_topic["execution"].p50 == 57.0
