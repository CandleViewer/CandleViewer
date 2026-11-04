"""E40-S02 backend PR 1 (#1130): `getAlertDelivery` (CC-2), the derived `kind` / `summary`
(CC-7) and ack-all over every channel once `unacked_count` counts in-app rows only (CC-18).

Owner scope: another user's delivery is the same 404 as an unknown one, and the foreign case is
audited (`alert.denied`); `context` is served through the allow-list, so `condition_hash` and
`gates` never leave.
"""

from __future__ import annotations

from typing import Any

import pytest
from _deliveries_env import ALERT_B, Env

from candleviewer.api._generated import openapi_models as api
from tests.alerts._alert_api_env import USER_B

FIRING_CONTEXT: dict[str, Any] = {
    "condition_hash": "h" * 64, "gates": ["enabled", "snoozed", "storm"],
    "trigger_type": "on_price_update", "symbol": "BTCUSDT", "event_ts_ms": 1_790_000_000_000,
    "evaluated_at_ms": 1_790_000_000_010, "values": {"price": "65012.5"}, "bar_open_ms": None,
}  # fmt: skip


@pytest.fixture
def env() -> Env:
    return Env()


def test_get_delivery_own_returns_the_row_and_its_context(env: Env) -> None:
    d = env.store.add(context=FIRING_CONTEXT)
    r = env.c.get(f"/alerts/deliveries/{d.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == d.id and body["kind"] == "firing" and body["summary"] is None
    assert body["context"] == {
        k: v for k, v in FIRING_CONTEXT.items() if k not in ("condition_hash", "gates")
    }
    api.AlertDeliveryDetail.model_validate(body)
    assert env.audit.calls == []


def test_get_delivery_never_serves_condition_hash_or_gates(env: Env) -> None:
    d = env.store.add(context=FIRING_CONTEXT | {"nested": {"condition_hash": "x"}})
    text = env.c.get(f"/alerts/deliveries/{d.id}").text
    assert "condition_hash" not in text and "gates" not in text and "nested" not in text


def test_get_delivery_drops_unlisted_and_off_type_keys(env: Env) -> None:
    ctx = {
        "symbol": "BTCUSDT",
        "webhook_url": "https://x.invalid",
        "event_ts_ms": "soon",
        "disarmed": 1,
        "values": {"price": "1", "deep": {"a": 1}},
        "symbols": ["A", 3],
    }
    d = env.store.add(context=ctx)  # fmt: skip
    got = env.c.get(f"/alerts/deliveries/{d.id}").json()["context"]
    assert got == {"symbol": "BTCUSDT", "values": {"price": "1"}, "symbols": ["A"]}


def test_get_delivery_serves_no_account_or_position_scope_value(env: Env) -> None:
    values = {"price": "65012.5", "account_equity": "812.40", "position_qty": "0.5",
              "made_up_metric": "7"}  # fmt: skip
    d = env.store.add(context=FIRING_CONTEXT | {"values": values})
    r = env.c.get(f"/alerts/deliveries/{d.id}")
    assert r.status_code == 200
    assert r.json()["context"]["values"] == {"price": "65012.5"}
    assert "812.40" not in r.text and "0.5" not in r.text


def test_get_delivery_foreign_is_404_and_audited_like_unknown(env: Env) -> None:
    foreign = env.store.add(user=USER_B, alert=ALERT_B, context=FIRING_CONTEXT)
    r = env.c.get(f"/alerts/deliveries/{foreign.id}")
    unknown = env.c.get("/alerts/deliveries/999999")
    assert r.status_code == unknown.status_code == 404
    assert r.json() == unknown.json()
    assert "65012" not in r.text
    [denied] = env.denials()
    assert denied["object_id"] == str(foreign.id)


def test_silenced_firing_is_served_with_its_reason(env: Env) -> None:
    d = env.store.add(context={"symbol": "ETHUSDT", "silenced": "muted_symbol"})
    (item,) = env.c.get("/alerts/deliveries").json()["items"]
    detail = env.c.get(f"/alerts/deliveries/{d.id}").json()
    assert item["silenced"] == detail["silenced"] == detail["context"]["silenced"] == "muted_symbol"


def test_get_delivery_answers_json_never_markup(env: Env) -> None:
    """The no-raw-HTML rule's server half: rendered text travels as a JSON string."""
    d = env.store.add(title="<img src=x onerror=alert(1)>", body="<b>x</b>")
    r = env.c.get(f"/alerts/deliveries/{d.id}")
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["message"] == "<b>x</b>"


def test_get_delivery_read_only_caller_is_allowed(env: Env) -> None:
    """`alerts:read` alone (a Viewer's set) reads its own delivery; nothing is written."""
    d = env.store.add()
    env.perms = frozenset({"alerts:read"})
    r = env.c.get(f"/alerts/deliveries/{d.id}")
    assert r.status_code == 200 and env.store.rows[d.id] == d


@pytest.mark.parametrize("bad", ["0", "-1", "abc", str(2**63)])
def test_get_delivery_malformed_id_is_422_without_lookup(env: Env, bad: str) -> None:
    assert env.c.get(f"/alerts/deliveries/{bad}").status_code == 422
    assert env.denials() == []


@pytest.mark.parametrize(
    ("context", "kind"),
    [
        ({"symbol": "BTCUSDT"}, "firing"),
        ({"suppressed_reason": "storm"}, "firing"),
        ({"disarmed": True, "reason": "source_unavailable", "metric": "price"}, "disarm_notice"),
        ({"channel_failure": True, "failed_delivery_id": 7}, "failure_notice"),
        ({"storm_summary": True, "suppressed": 5, "symbols": ["BTCUSDT"]}, "storm_summary"),
        ({}, "firing"),
    ],
)
def test_list_item_kind_is_derived_from_the_row(
    env: Env, context: dict[str, Any], kind: str
) -> None:
    env.store.add(context=context)
    (item,) = env.c.get("/alerts/deliveries").json()["items"]
    assert item["kind"] == kind
    api.AlertDelivery.model_validate(item)


def test_storm_summary_item_carries_count_symbols_and_window(env: Env) -> None:
    ctx = {
        "storm_summary": True,
        "suppressed": 5,
        "symbols": ["S0USDT", "S1USDT"],
        "window_start_ms": 1_790_000_000_000,
        "window_end_ms": 1_790_000_060_000,
    }
    d = env.store.add(context=ctx)  # fmt: skip
    (item,) = env.c.get("/alerts/deliveries").json()["items"]
    assert item["summary"] == {
        "count": 5, "symbols": ["S0USDT", "S1USDT"],
        "window_start": "2026-09-21T14:13:20+00:00", "window_end": "2026-09-21T14:14:20+00:00",
    }  # fmt: skip
    detail = env.c.get(f"/alerts/deliveries/{d.id}").json()
    assert (
        detail["kind"] == "storm_summary"
        and detail["context"]["window_end_ms"] == ctx["window_end_ms"]
    )


def test_storm_summary_written_before_cc7_has_a_null_window(env: Env) -> None:
    env.store.add(context={"storm_summary": True, "suppressed": 2, "symbols": ["A"]})
    (item,) = env.c.get("/alerts/deliveries").json()["items"]
    assert item["summary"] == {"count": 2, "symbols": ["A"], "window_start": None,
                               "window_end": None}  # fmt: skip


def test_ack_all_acknowledges_desktop_rows_when_no_in_app_row_is_unread(env: Env) -> None:
    """CC-18: `unacked_count` counts in-app rows only, but ack-all still clears every channel."""
    d = env.store.add(channel="desktop")
    r = env.c.post("/alerts/deliveries/ack-all")
    assert r.json() == {"acknowledged": 1} and env.store.rows[d.id].status == "acked"
    [(_, rec)] = [c for c in env.audit.calls if c[0] == "alert.deliveries_acked"]
    assert rec["before_state"] == {"status": "sent", "unacked": 1}
