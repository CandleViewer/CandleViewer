"""E29-T08's acceptance criteria (#916; 24-internal-schemas.md Sec.8.13), one test per Gherkin
scenario, each named in the scenario's own words.

The orders are real: each is driven through the order facade and B1 (`order_rig`) into the state
the scenario names, and the row the scan reads is the facade's stored row (its state, its
`idempotency_state`, its ids), aged as the scenario says, since the in-memory reads keep no
`order_events` clock (the Postgres read's age is `test_stuck_detection_pg.py`'s). The detector, its
judgement and its sinks are the real ones (`stuck_rig`). The rule halves read the shipped rule file
and the promtool cases CI runs (`promtool test rules`); the rules this ticket adds land with its
second change, after #5185 (BQ-1, BQ-13), with their own near-miss cases. No network, no sleeps.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.repositories.stuck import StuckOrderRow
from tests.unit.oms.order_rig import ACCOUNT, Rig, build_rig, gated, order_of
from tests.unit.oms.stuck_rig import build, position

_ROOT = Path(__file__).resolve().parents[5]
_RULES = _ROOT / "infra" / "prometheus" / "alerts" / "system_page.yml"
_CASES = _ROOT / "infra" / "prometheus" / "tests" / "system_alerts.test.yml"


@pytest.fixture
async def orders(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Rig]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    built = build_rig()
    yield built
    await built.facade.stop()


async def _scan_row(orders: Rig, order_id: Any, *, age_s: float) -> StuckOrderRow:
    """The scan's row of the facade's stored order, aged `age_s`."""
    row = await orders.orders.get(ACCOUNT, order_id)
    assert row is not None
    return StuckOrderRow(
        row.id, row.exchange_account_id, row.order_link_id, row.symbol, row.state,
        row.idempotency_state == "in_flight", age_s,
    )  # fmt: skip


def _rule(name: str) -> dict[str, Any]:
    for group in yaml.safe_load(_RULES.read_text(encoding="utf-8"))["groups"]:
        for rule in group["rules"]:
            if rule.get("alert") == name:
                return dict(rule)
    raise AssertionError(f"no rule {name}")


def _seconds(duration: str) -> int:
    found = re.fullmatch(r"(\d+)([smh])", duration)
    assert found is not None, duration
    return int(found[1]) * {"s": 1, "m": 60, "h": 3600}[found[2]]


def _cases(alert: str) -> list[tuple[list[str], bool]]:
    """Each promtool case of `alert`: its input series and whether it expects the alert."""
    found: list[tuple[list[str], bool]] = []
    for case in yaml.safe_load(_CASES.read_text(encoding="utf-8"))["tests"]:
        for test in case.get("alert_rule_test", []):
            if test["alertname"] == alert:
                series = [s["series"] for s in case["input_series"]]
                found.append((series, bool(test.get("exp_alerts"))))
    return found


async def test_an_unknown_order_pages(orders: Rig) -> None:
    """Given an order has been in unknown for 61 seconds
    Then oms_unknown_orders is greater than zero, the alert rule fires, and an incident event with
    the order_link_id is emitted."""

    async def ambiguous(_command: b01.Command) -> Mapping[str, Any]:
        raise TimeoutError

    orders.commands.on_place = ambiguous
    order = order_of()
    await orders.start(order)
    await orders.facade.command(ACCOUNT, order.id, "SEND", actor="user")
    await orders.quiet()
    assert orders.facade.state(order.id) == ("unknown", "not_required")
    assert orders.count("oms_unknown_orders", reason="transport") == 1 > 0
    # the rule pages on that series once it has held above zero for its `for`, inside 61 s; the
    # reason does not take a transport fault out of it
    rule = _rule("OmsUnknownOrders")
    assert "oms_unknown_orders" in rule["expr"] and rule["expr"].replace(" ", "").endswith(">0")
    assert 'reason="transport"' not in rule["expr"] and _seconds(rule["for"]) <= 61
    assert rule["labels"]["severity"] == "page"
    assert any(fires for _series, fires in _cases("OmsUnknownOrders"))
    # the detector raises the incident naming the order, on the bus and in its record
    detect = build()
    detect.reads.orders["demo"] = [await _scan_row(orders, order.id, age_s=61.0)]
    await detect.detector.scan()
    [found] = detect.bus.offered
    assert (found.kind, found.severity, found.order_link_id) == (
        "unknown", "critical", order.order_link_id
    )  # fmt: skip
    assert [f.order_link_id for f, _k, _o in detect.records.written] == [order.order_link_id]


async def test_a_stuck_in_flight_submission_is_detected(orders: Rig) -> None:
    """Given an order has been idempotency_state in_flight for 31 seconds
    Then a stuck-order incident is raised naming the order and its age."""
    _gate, held = gated({"ok": True, "exchange_order_id": "x1"})
    orders.commands.on_place = held  # the create leaves and its answer never comes
    order = order_of()
    await orders.start(order)
    await orders.facade.command(ACCOUNT, order.id, "SEND", actor="user")
    await orders.quiet()
    row = await _scan_row(orders, order.id, age_s=31.0)
    assert row.in_flight and orders.facade.state(order.id) == ("submitting", "not_required")
    detect = build()
    detect.reads.orders["demo"] = [row]
    await detect.detector.scan()
    [(found, object_kind, object_id)] = detect.records.written
    assert (found.kind, found.order_link_id, found.age_s) == ("in_flight", order.order_link_id, 31)
    assert (object_kind, object_id) == ("order", str(order.id))
    assert detect.count("oms_stuck_orders", kind="in_flight") == 1


async def test_a_naked_position_is_detected_within_the_deadline() -> None:
    """Given an open position with no exchange-side stop-loss
    When 3 seconds elapse
    Then naked_position_alerts_total increments and a critical incident is emitted.

    The first scan that reads the position naked starts its episode; the first scan once more
    than `CV_NATIVE_SL_DEADLINE_MS` (3 s) has passed raises it, read-only and alert-only (BQ-4)."""
    detect = build()
    detect.reads.positions["demo"] = [position()]
    await detect.detector.scan()
    assert detect.count("naked_position_alerts_total") == 0
    detect.clock.advance(3.001)
    await detect.detector.scan()
    assert detect.count("naked_position_alerts_total") == 1
    [found] = detect.bus.offered
    assert (found.kind, found.severity, found.symbol) == ("naked", "critical", "BTCUSDT")
    assert detect.pager.severities == ["page"]
    await detect.detector.scan()  # once per episode
    assert detect.count("naked_position_alerts_total") == 1


def test_alert_rules_are_tested_not_assumed() -> None:
    """When the alert-rule unit tests run against synthetic metric series
    Then each rule fires exactly for the intended series and not for the near-miss series.

    Each rule over a series this change emits holds a case that fires and a near-miss that does
    not, which CI's `promtool test rules` runs; the rules this ticket adds bring theirs (BQ-13)."""
    for alert, series in (
        ("OmsUnknownOrders", "oms_unknown_orders"),
        ("NakedPositionDetected", "naked_position_alerts_total"),
    ):
        cases = _cases(alert)
        assert any(fires for _s, fires in cases), alert
        assert any(not fires for _s, fires in cases), alert
        assert all(series in names for names, _fires in cases), alert
