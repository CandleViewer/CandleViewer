"""E40-T04 delivery inbox: list, ack, ack-all and the desktop report-back (`/alerts/deliveries*`).

Gherkin covered here: "Acknowledgement is idempotent", "A user cannot read another user's
deliveries" (404, nothing changes, the denial is audited) and the desktop half of "A firing
reaches every configured channel" (the desktop row moves to sent when the shell confirms).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from _alert_api_env import USER_A, USER_B
from _deliveries_env import ALERT_A, ALERT_B, T0, Env
from structlog.testing import capture_logs

from candleviewer.api import alert_deliveries
from candleviewer.api.alert_deliveries import ACK_ALL_BATCH, ACK_ALL_MAX_BATCHES, DenialBudget
from candleviewer.audit.writer import AuditUnavailable, AuditWriterStopped
from candleviewer.observability.correlation import CorrelationMiddleware


@pytest.fixture
def env() -> Env:
    return Env()


# --- GET /alerts/deliveries --------------------------------------------------------------


def test_list_returns_only_the_callers_deliveries_newest_first(env: Env) -> None:
    a1, a2 = env.store.add(), env.store.add()
    env.store.add(user=USER_B, alert=ALERT_B)
    r = env.c.get("/alerts/deliveries")
    assert r.status_code == 200
    body = r.json()
    assert [i["id"] for i in body["items"]] == [a2.id, a1.id]
    assert body["meta"] == {"next_cursor": None, "has_more": False, "count": 2}


def test_list_item_is_the_contract_alert_delivery_shape(env: Env) -> None:
    d = env.store.add(body="", error_message=None)
    (item,) = env.c.get("/alerts/deliveries").json()["items"]
    assert item == {
        "id": d.id, "alert_id": ALERT_A, "channel": "in_app", "status": "sent",
        "severity": "info", "title": "BTC reclaims 64k", "message": "BTC reclaims 64k",
        "symbol": "BTCUSDT", "fired_at": d.queued_at.isoformat(), "acked_at": None,
        "error": None,
    }  # fmt: skip


def test_list_symbol_is_null_when_the_context_names_no_single_symbol(env: Env) -> None:
    env.store.add(context={"storm_summary": True, "symbols": ["BTCUSDT", "ETHUSDT"]})
    env.store.add(context={"symbol": "not a symbol"})
    assert {i["symbol"] for i in env.c.get("/alerts/deliveries").json()["items"]} == {None}


def test_list_pages_with_a_cursor_without_gaps_or_repeats(env: Env) -> None:
    ids = [env.store.add().id for _ in range(5)]
    seen: list[int] = []
    cursor: str | None = None
    for _ in range(3):
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        body = env.c.get("/alerts/deliveries", params=params).json()
        seen += [i["id"] for i in body["items"]]
        cursor = body["meta"]["next_cursor"]
    assert seen == sorted(ids, reverse=True) and cursor is None


def test_list_filters_status_unacked_and_window(env: Env) -> None:
    sent = env.store.add()
    env.store.add(status="failed", error_message="email relay timeout")
    env.store.add(status="acked", acked_at=T0)
    unacked = env.c.get("/alerts/deliveries", params={"unacked_only": "true"}).json()
    assert [i["id"] for i in unacked["items"]] == [sent.id]
    failed = env.c.get("/alerts/deliveries", params={"status": "failed"}).json()["items"]
    assert [i["error"] for i in failed] == ["email relay timeout"]
    window = {"from": (sent.queued_at + timedelta(seconds=1)).isoformat()}
    assert sent.id not in [
        i["id"] for i in env.c.get("/alerts/deliveries", params=window).json()["items"]
    ]


def test_list_reads_a_window_bound_without_offset_as_utc(env: Env) -> None:
    d = env.store.add()
    naive = d.queued_at.replace(tzinfo=None).isoformat()
    got = env.c.get("/alerts/deliveries", params={"from": naive}).json()["items"]
    assert [i["id"] for i in got] == [d.id]


def test_list_by_own_alert_id_filters_to_that_alert(env: Env) -> None:
    own = env.store.add()
    env.store.owners["13000000-0000-4000-8000-0000000000aa"] = USER_A
    env.store.add(alert="13000000-0000-4000-8000-0000000000aa")
    got = env.c.get("/alerts/deliveries", params={"alert_id": ALERT_A}).json()["items"]
    assert [i["id"] for i in got] == [own.id]


def test_list_by_another_users_alert_id_is_404_and_audited(env: Env) -> None:
    env.store.add(user=USER_B, alert=ALERT_B)
    r = env.c.get("/alerts/deliveries", params={"alert_id": ALERT_B})
    assert r.status_code == 404 and r.json()["code"] == "not_found"
    (denial,) = env.denials()
    assert denial["object_kind"] == "alert" and denial["object_id"] == ALERT_B
    assert denial["actor_user_id"] == USER_A


def test_list_by_unknown_alert_id_is_404_without_a_denial(env: Env) -> None:
    r = env.c.get("/alerts/deliveries", params={"alert_id": "13000000-0000-4000-8000-0000000000ff"})
    assert r.status_code == 404 and env.denials() == []


def test_list_refuses_a_malformed_alert_id_or_status(env: Env) -> None:
    assert env.c.get("/alerts/deliveries", params={"alert_id": "x"}).status_code == 422
    assert env.c.get("/alerts/deliveries", params={"status": "lost"}).status_code == 422


def test_list_invalid_cursor_is_400(env: Env) -> None:
    r = env.c.get("/alerts/deliveries", params={"cursor": "bm9wZQ=="})
    assert r.status_code == 400 and r.json()["code"] == "invalid_cursor"  # 22's code for it


def test_list_is_not_shadowed_by_the_alert_crud_route(env: Env) -> None:
    """`/alerts/{alertId}` would read `deliveries` as a malformed alert id (422)."""
    assert env.c.get("/alerts/deliveries").status_code == 200


# --- POST /alerts/deliveries/{id}/ack ---------------------------------------------------


def test_ack_moves_sent_to_acked_and_audits_once(env: Env) -> None:
    d = env.store.add()
    r = env.c.post(f"/alerts/deliveries/{d.id}/ack")
    assert r.status_code == 200
    assert r.json()["status"] == "acked" and r.json()["acked_at"] is not None
    assert env.audit.actions() == ["alert.delivery_acked"]
    (_, kw), = env.audit.calls  # fmt: skip
    assert kw["object_id"] == str(d.id) and kw["after_state"] == {"status": "acked"}


def test_ack_twice_returns_the_same_acked_state_and_acked_at(env: Env) -> None:
    d = env.store.add()
    first = env.c.post(f"/alerts/deliveries/{d.id}/ack").json()
    second = env.c.post(f"/alerts/deliveries/{d.id}/ack")
    assert second.status_code == 200 and second.json() == first
    assert env.store.rows[d.id].acked_at is not None
    assert env.audit.actions() == ["alert.delivery_acked"]  # the no-op is not audited


@pytest.mark.parametrize("status", ["queued", "failed", "suppressed"])
def test_ack_of_a_delivery_that_never_reached_sent_changes_nothing(env: Env, status: str) -> None:
    d = env.store.add(status=status)
    r = env.c.post(f"/alerts/deliveries/{d.id}/ack")
    assert r.status_code == 200 and r.json()["status"] == status
    assert env.store.rows[d.id] == d and env.audit.calls == []


def test_ack_of_another_users_delivery_is_404_audited_and_changes_nothing(env: Env) -> None:
    b = env.store.add(user=USER_B, alert=ALERT_B)
    r = env.c.post(f"/alerts/deliveries/{b.id}/ack")
    assert r.status_code == 404 and r.json()["code"] == "not_found"
    assert env.store.rows[b.id] == b
    (denial,) = env.denials()
    assert denial["object_kind"] == "alert_delivery" and denial["object_id"] == str(b.id)
    assert env.audit.actions() == ["alert.denied"]


def test_ack_of_an_orphaned_delivery_is_treated_as_foreign(env: Env) -> None:
    """`user_id` is SET NULL when the user is deleted: nobody owns the row any more."""
    d = env.store.add(user_id=None)
    assert env.c.post(f"/alerts/deliveries/{d.id}/ack").status_code == 404
    assert len(env.denials()) == 1


def test_ack_of_an_unknown_delivery_is_404_without_a_denial(env: Env) -> None:
    assert env.c.post("/alerts/deliveries/999999/ack").status_code == 404
    assert env.denials() == []


@pytest.mark.parametrize("bad", ["0", "-1", "abc", str(2**63)])
def test_ack_refuses_an_id_outside_int64(env: Env, bad: str) -> None:
    assert env.c.post(f"/alerts/deliveries/{bad}/ack").status_code == 422


def test_ack_that_loses_the_race_answers_with_the_row_as_it_now_is(env: Env) -> None:
    d = env.store.add()
    won = replace(d, status="acked", acked_at=T0, acked_by=USER_A)

    async def lost(_id: int, _user: str) -> None:
        env.store.rows[d.id] = won  # another session's conditional update landed first
        return None

    env.store.ack = lost  # type: ignore[method-assign]  # fault injection
    r = env.c.post(f"/alerts/deliveries/{d.id}/ack")
    assert r.status_code == 200 and r.json()["acked_at"] == T0.isoformat()


# --- POST /alerts/deliveries/ack-all -----------------------------------------------------


def test_ack_all_acknowledges_only_the_callers_sent_rows(env: Env) -> None:
    mine = [env.store.add() for _ in range(3)]
    queued = env.store.add(status="queued")
    other = env.store.add(user=USER_B, alert=ALERT_B)
    r = env.c.post("/alerts/deliveries/ack-all")
    assert r.status_code == 200 and r.json() == {"acknowledged": 3}
    assert {env.store.rows[d.id].status for d in mine} == {"acked"}
    assert env.store.rows[queued.id].status == "queued"
    assert env.store.rows[other.id] == other
    (_, kw), = env.audit.calls  # fmt: skip
    assert kw["before_state"] == {"status": "sent", "unacked": 3}
    assert kw["after_state"] == {"status": "acked", "scope": "all_sent", "max": 5000}


def test_ack_all_writes_its_record_before_any_batch_commits(env: Env) -> None:
    """#3917 review CR-03: write-ahead (C-2.9); a failing writer leaves every row unacked."""
    d = env.store.add()

    async def refuse(action: str, **kw: object) -> None:
        raise RuntimeError("audit writer down")

    env.audit.emit = refuse  # type: ignore[method-assign]  # fault injection
    with pytest.raises(RuntimeError, match="audit writer down"):
        env.c.post("/alerts/deliveries/ack-all")
    assert env.store.rows[d.id].status == "sent" and env.store.ack_all_calls == []
    assert env.changes == []


def test_ack_all_with_nothing_to_acknowledge_is_zero_and_unaudited(env: Env) -> None:
    assert env.c.post("/alerts/deliveries/ack-all").json() == {"acknowledged": 0}
    assert env.audit.calls == []


def test_ack_all_is_bounded_per_request_and_continues_on_the_next_call(env: Env) -> None:
    total = ACK_ALL_BATCH * ACK_ALL_MAX_BATCHES + 7
    for _ in range(total):
        env.store.add()
    first = env.c.post("/alerts/deliveries/ack-all").json()["acknowledged"]
    assert first == ACK_ALL_BATCH * ACK_ALL_MAX_BATCHES
    assert env.store.ack_all_calls == [ACK_ALL_BATCH] * ACK_ALL_MAX_BATCHES
    assert env.c.post("/alerts/deliveries/ack-all").json() == {"acknowledged": 7}


# --- POST /alerts/deliveries/{id}/desktop-outcome ---------------------------------------


def _desktop(env: Env, **over: object) -> int:
    return env.store.add(channel="desktop", status="queued", sent_at=None, **over).id


def test_desktop_shown_moves_queued_to_sent_with_latency(env: Env) -> None:
    did = _desktop(env)
    body = {"outcome": "shown", "permission": "granted"}
    r = env.c.post(f"/alerts/deliveries/{did}/desktop-outcome", json=body)
    assert r.status_code == 204 and r.content == b""
    assert env.store.rows[did].status == "sent"
    names = [(n, labels) for n, labels, _ in env.metrics.seen]
    assert names == [("cv_alert_delivery_total", ("desktop", "sent")),
                     ("cv_alert_delivery_latency_seconds", ("desktop",))]  # fmt: skip
    (_, kw), = env.audit.calls  # fmt: skip
    assert kw["after_state"] == {"status": "sent", "outcome": "shown", "permission": "granted"}


@pytest.mark.parametrize("outcome", ["blocked", "failed"])
def test_desktop_failure_fails_the_row_and_raises_one_notice(env: Env, outcome: str) -> None:
    did = _desktop(env)
    before = len(env.store.rows)
    body = {"outcome": outcome, "permission": "denied"}
    assert env.c.post(f"/alerts/deliveries/{did}/desktop-outcome", json=body).status_code == 204
    row = env.store.rows[did]
    assert row.status == "failed"
    assert row.error_message == f"desktop notification {outcome} (OS permission: denied)"
    (notice,) = [r for r in env.store.rows.values() if r.context.get("channel_failure")]
    assert notice.channel == "in_app" and notice.context["failed_delivery_id"] == did
    assert len(env.store.rows) == before + 1
    assert env.metrics.seen == [("cv_alert_delivery_total", ("desktop", "failed"), 1)]


def test_desktop_report_on_a_settled_row_is_a_204_no_op(env: Env) -> None:
    did = _desktop(env)
    body = {"outcome": "shown", "permission": "granted"}
    env.c.post(f"/alerts/deliveries/{did}/desktop-outcome", json=body)
    settled, calls = env.store.rows[did], len(env.audit.calls)
    again = env.c.post(f"/alerts/deliveries/{did}/desktop-outcome",
                       json={"outcome": "blocked", "permission": "denied"})  # fmt: skip
    assert again.status_code == 204
    assert env.store.rows[did] == settled and len(env.audit.calls) == calls


def test_desktop_report_on_a_non_desktop_row_is_422(env: Env) -> None:
    d = env.store.add(status="queued")
    r = env.c.post(f"/alerts/deliveries/{d.id}/desktop-outcome",
                   json={"outcome": "shown", "permission": "granted"})  # fmt: skip
    assert r.status_code == 422 and r.json()["errors"][0]["rule"] == "not_desktop_delivery"
    assert env.store.rows[d.id] == d


@pytest.mark.parametrize(
    "body",
    [
        {"outcome": "shown"},
        {"outcome": "seen", "permission": "granted"},
        {"outcome": "shown", "permission": "maybe"},
        {"outcome": "shown", "permission": "granted", "user_id": USER_B},
    ],
)
def test_desktop_report_body_is_closed_and_validated(env: Env, body: dict[str, str]) -> None:
    did = _desktop(env)
    r = env.c.post(f"/alerts/deliveries/{did}/desktop-outcome", json=body)
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    assert env.store.rows[did].status == "queued" and env.audit.calls == []


def test_desktop_report_non_json_body_is_422(env: Env) -> None:
    did = _desktop(env)
    r = env.c.post(f"/alerts/deliveries/{did}/desktop-outcome", content=b"not json",
                   headers={"content-type": "application/json"})  # fmt: skip
    assert r.status_code == 422 and r.json()["detail"] == "Body is not JSON."


def test_desktop_report_for_another_users_delivery_is_404_and_audited(env: Env) -> None:
    did = _desktop(env, user=USER_B, alert=ALERT_B)
    r = env.c.post(f"/alerts/deliveries/{did}/desktop-outcome",
                   json={"outcome": "shown", "permission": "granted"})  # fmt: skip
    assert r.status_code == 404 and env.store.rows[did].status == "queued"
    assert env.audit.actions() == ["alert.denied"]


# --- on_change: the alerts topic's seam ----------------------------------------------------


def test_on_change_gets_the_acked_id_once_the_ack_is_committed(env: Env) -> None:
    d = env.store.add()
    env.c.post(f"/alerts/deliveries/{d.id}/ack")
    env.c.post(f"/alerts/deliveries/{d.id}/ack")  # no change: not told again
    assert env.changes == [[d.id]]


def test_on_change_is_not_told_about_refusals_or_no_ops(env: Env) -> None:
    queued = env.store.add(status="queued")
    foreign = env.store.add(user=USER_B, alert=ALERT_B)
    env.c.post(f"/alerts/deliveries/{queued.id}/ack")
    env.c.post(f"/alerts/deliveries/{foreign.id}/ack")
    env.c.post("/alerts/deliveries/ack-all")  # nothing sent to acknowledge
    assert env.changes == []


def test_on_change_gets_each_ack_all_batch(env: Env) -> None:
    for _ in range(ACK_ALL_BATCH + 3):
        env.store.add()
    env.c.post("/alerts/deliveries/ack-all")
    assert [len(batch) for batch in env.changes] == [ACK_ALL_BATCH, 3]


def test_on_change_gets_the_settled_desktop_delivery(env: Env) -> None:
    did = _desktop(env)
    env.c.post(f"/alerts/deliveries/{did}/desktop-outcome",
               json={"outcome": "blocked", "permission": "denied"})  # fmt: skip
    assert env.changes == [[did]]


def test_a_failing_hook_never_fails_the_committed_request(env: Env) -> None:
    env.change_fails = True
    d = env.store.add()
    r = env.c.post(f"/alerts/deliveries/{d.id}/ack")
    assert r.status_code == 200 and env.store.rows[d.id].status == "acked"
    assert env.changes == [[d.id]]


def test_a_hook_that_outlives_its_bound_is_dropped_not_waited_on(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#3917 review CR-08: the committed request answers; the topic repairs a lost delta."""
    monkeypatch.setattr(alert_deliveries, "CHANGE_HOOK_TIMEOUT_S", 0.01)
    env.change_hangs = True
    d = env.store.add()
    r = env.c.post(f"/alerts/deliveries/{d.id}/ack")
    assert r.status_code == 200 and env.store.rows[d.id].status == "acked"
    assert env.changes == [[d.id]]


# --- lost races (#3917 review CR-07) ------------------------------------------------------


def test_ack_whose_row_vanished_after_losing_the_race_is_404(env: Env) -> None:
    d = env.store.add()

    async def lost(_id: int, _user: str) -> None:
        del env.store.rows[d.id]  # gone (retention) between the update and the re-read
        return None

    env.store.ack = lost  # type: ignore[method-assign]  # fault injection
    assert env.c.post(f"/alerts/deliveries/{d.id}/ack").status_code == 404
    assert env.changes == []


def test_desktop_report_that_loses_the_race_is_204_with_no_metric_and_no_hook(env: Env) -> None:
    did = _desktop(env)

    async def lost(*_a: object, **_kw: object) -> None:
        return None  # the dispatcher (or another report) settled it first

    env.store.report_desktop = lost  # type: ignore[method-assign]  # fault injection
    r = env.c.post(f"/alerts/deliveries/{did}/desktop-outcome",
                   json={"outcome": "shown", "permission": "granted"})  # fmt: skip
    assert r.status_code == 204 and env.metrics.seen == [] and env.changes == []
    assert env.audit.actions() == ["alert.desktop_outcome"]  # the attempt stays recorded


def test_desktop_report_passes_the_callers_id_to_the_store(env: Env) -> None:
    """The store's update re-checks it (#3917 review SR-E40T04A-03; the SQL is pinned in
    `test_alert_inbox_store.py` and on Postgres in `test_notifications_union_pg.py`)."""
    did = _desktop(env)
    env.c.post(f"/alerts/deliveries/{did}/desktop-outcome",
               json={"outcome": "shown", "permission": "granted"})  # fmt: skip
    assert env.store.desktop_reports == [(did, USER_A)]


# --- the denial budget (#3917 review SR-E40T04A-02) --------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_denials_past_the_budget_are_counted_not_written() -> None:
    clock = _Clock()
    env = Env(denials=DenialBudget(per_window=2, window_s=60, clock=clock))
    foreign = [env.store.add(user=USER_B, alert=ALERT_B).id for _ in range(5)]
    for did in foreign:
        assert env.c.post(f"/alerts/deliveries/{did}/ack").status_code == 404
    assert [kw["object_id"] for kw in env.denials()] == [str(foreign[0]), str(foreign[1])]
    assert all("after_state" not in kw for kw in env.denials())
    clock.t += 60  # the window slides: the next record carries the three held back
    assert env.c.post(f"/alerts/deliveries/{foreign[0]}/ack").status_code == 404
    assert env.denials()[-1]["after_state"] == {"suppressed_before": 3}


def test_a_held_denial_is_still_a_404_and_changes_nothing() -> None:
    env = Env(denials=DenialBudget(per_window=1, window_s=60, clock=_Clock()))
    b = env.store.add(user=USER_B, alert=ALERT_B)
    for _ in range(3):
        r = env.c.post(f"/alerts/deliveries/{b.id}/ack")
        assert r.status_code == 404 and r.json()["code"] == "not_found"
    assert env.store.rows[b.id] == b and len(env.denials()) == 1


def test_the_list_filter_on_a_foreign_alert_spends_the_same_budget() -> None:
    env = Env(denials=DenialBudget(per_window=1, window_s=60, clock=_Clock()))
    env.store.add(user=USER_B, alert=ALERT_B)
    for _ in range(2):
        assert env.c.get("/alerts/deliveries", params={"alert_id": ALERT_B}).status_code == 404
    assert len(env.denials()) == 1


def test_each_caller_has_its_own_budget() -> None:
    budget = DenialBudget(per_window=1, window_s=60, clock=_Clock())
    assert budget.admit(USER_A) == 0 and budget.admit(USER_A) is None
    assert budget.admit(USER_B) == 0


def test_the_budget_is_bounded_and_logs_an_evicted_held_count() -> None:
    budget = DenialBudget(per_window=1, window_s=60, max_callers=2, clock=_Clock())
    with capture_logs() as logs:
        budget.admit("u1")
        assert budget.admit("u1") is None  # one held: the run's first is logged at once
        budget.admit("u2")
        budget.admit("u3")  # u1 is the least recently used: evicted with its held count
    assert len(budget) == 2
    assert [(e["event"], e.get("held")) for e in logs] == [
        ("alert_denied_audit_held", 1),
        ("alert_denied_audit_held_evicted", 1),
    ]
    assert budget.admit("u1") == 0  # a fresh entry: the evicted count was logged, not carried


@pytest.mark.parametrize(
    ("per_window", "window_s", "max_callers"), [(0, 60, 1), (1, 0, 1), (1, 60, 0)]
)
def test_the_budget_refuses_bounds_that_are_not_positive(
    per_window: int, window_s: float, max_callers: int
) -> None:
    with pytest.raises(ValueError, match="positive"):
        DenialBudget(per_window=per_window, window_s=window_s, max_callers=max_callers)


# --- what an answer never carries (#3917 review SR-E40T04A-06) ---------------------------

#: A value the rows hold in fields that are never served (the firing `context`, the alert's
#: SECRET webhook columns under any key, who acked): it must not reach the wire anywhere.
_MARKER = "never-served-7f3a"


def _keys(doc: object) -> set[str]:
    if isinstance(doc, dict):
        return set(doc) | {k for v in doc.values() for k in _keys(v)}
    if isinstance(doc, list):
        return {k for v in doc for k in _keys(v)}
    return set()


def test_no_list_answer_carries_a_withheld_field(env: Env) -> None:
    from candleviewer.api.contract_conformance import load_openapi_spec

    held = {"symbol": "BTCUSDT", "webhook_url_enc": _MARKER, "webhook_secret_enc": _MARKER,
            "payload": {"a": _MARKER}}  # fmt: skip
    env.store.add(context=held)
    env.store.add(status="acked", acked_at=T0, acked_by=_MARKER)
    r = env.c.get("/alerts/deliveries")
    assert _MARKER not in r.text
    declared = set(load_openapi_spec()["components"]["schemas"]["AlertDelivery"]["properties"])
    assert _keys(r.json()["items"]) == declared  # field by field: exactly the contract's


def test_a_denial_whose_record_fails_keeps_its_slot_and_its_count() -> None:
    """A failed write gives back what `admit` took: the next record still carries the count."""
    clock = _Clock()
    env = Env(denials=DenialBudget(per_window=1, window_s=60, clock=clock))
    b = env.store.add(user=USER_B, alert=ALERT_B)

    async def refuse(action: str, **kw: object) -> None:
        raise RuntimeError("audit writer down")

    real, env.audit.emit = env.audit.emit, refuse  # type: ignore[method-assign]  # fault injection
    with pytest.raises(RuntimeError, match="audit writer down"):
        env.c.post(f"/alerts/deliveries/{b.id}/ack")
    env.audit.emit = real  # type: ignore[method-assign]  # fault injection
    assert env.c.post(f"/alerts/deliveries/{b.id}/ack").status_code == 404
    (denial,) = env.denials()  # the slot came back: written, carrying the failed one
    assert denial["after_state"] == {"suppressed_before": 1}


def test_held_runs_are_logged_with_their_count_at_powers_of_ten() -> None:
    budget = DenialBudget(per_window=1, window_s=60, clock=_Clock())
    budget.admit("u1")
    with capture_logs() as logs:
        for _ in range(100):
            budget.admit("u1")
    assert [e["held"] for e in logs if e["event"] == "alert_denied_audit_held"] == [1, 10, 100]


@pytest.mark.parametrize(
    "bound", [{"from": "0001-01-01T00:00:00+14:00"}, {"to": "9999-12-31T23:59:59-14:00"}]
)
def test_a_window_bound_without_a_utc_instant_is_422(env: Env, bound: dict[str, str]) -> None:
    r = env.c.get("/alerts/deliveries", params=bound)
    (error,) = r.json()["errors"]
    assert r.status_code == 422 and error["rule"] == "datetime_range"
    assert error["field"] == f"query.{next(iter(bound))}"  # as SR-026 and FastAPI name it


@pytest.mark.parametrize("route", ["ack", "desktop-outcome"])
def test_a_single_transition_writes_its_record_before_it_commits(env: Env, route: str) -> None:
    """Write-ahead (C-2.9), as ack-all's: a failing writer leaves the row as it was, and no hook
    or metric runs."""
    did = env.store.add().id if route == "ack" else _desktop(env)
    before = env.store.rows[did]

    async def refuse(action: str, **kw: object) -> None:
        raise RuntimeError("audit writer down")

    env.audit.emit = refuse  # type: ignore[method-assign]  # fault injection
    body = None if route == "ack" else {"outcome": "shown", "permission": "granted"}
    with pytest.raises(RuntimeError, match="audit writer down"):
        env.c.post(f"/alerts/deliveries/{did}/{route}", json=body)
    assert env.store.rows[did] == before and env.changes == [] and env.metrics.seen == []


@pytest.mark.parametrize("refusal", [AuditUnavailable("WAL full"), AuditWriterStopped()])
def test_a_refused_audit_write_is_the_declared_503_and_changes_nothing(
    env: Env, refusal: Exception
) -> None:
    d = env.store.add()

    async def refuse(action: str, **kw: object) -> None:
        raise refusal

    env.audit.emit = refuse  # type: ignore[method-assign]  # fault injection
    with capture_logs() as logs:
        r = env.c.post(f"/alerts/deliveries/{d.id}/ack")
    assert r.status_code == 503 and r.headers["content-type"] == "application/problem+json"
    assert r.json()["code"] == "audit_unavailable"
    assert env.store.rows[d.id] == d and env.changes == []
    assert [(e["event"], e["error"]) for e in logs] == [
        ("alerts_audit_unavailable", type(refusal).__name__)
    ]


def test_a_restore_for_an_evicted_caller_logs_the_count() -> None:
    budget = DenialBudget(per_window=1, window_s=60, clock=_Clock(), max_callers=1)
    assert budget.admit("u1") == 0
    assert budget.admit("u2") == 0  # u1 is evicted: one caller is tracked
    with capture_logs() as logs:
        budget.restore("u1", 2)
    assert [(e["event"], e["held"]) for e in logs] == [("alert_denied_audit_held_evicted", 3)]


class _Cut(BaseException):
    """What a cancellation is to `_deny`: not an `Exception`."""


def test_a_denial_cut_short_keeps_its_slot_and_its_count() -> None:
    env = Env(denials=DenialBudget(per_window=1, window_s=60, clock=_Clock()))
    b = env.store.add(user=USER_B, alert=ALERT_B)

    async def cut(action: str, **kw: object) -> None:
        raise _Cut

    real, env.audit.emit = env.audit.emit, cut  # type: ignore[method-assign]  # fault injection
    with pytest.raises(_Cut):
        env.c.post(f"/alerts/deliveries/{b.id}/ack")
    env.audit.emit = real  # type: ignore[method-assign]  # fault injection
    assert env.c.post(f"/alerts/deliveries/{b.id}/ack").status_code == 404
    (denial,) = env.denials()
    assert denial["after_state"] == {"suppressed_before": 1}


def test_a_delivery_record_names_the_request_the_middleware_bound() -> None:
    """#3990: the router's records carry the id `CorrelationMiddleware` bound."""
    env = Env()
    env.c.app.add_middleware(CorrelationMiddleware)  # type: ignore[attr-defined]  # typed as ASGIApp
    d = env.store.add()
    r = env.c.post(f"/alerts/deliveries/{d.id}/ack")
    assert r.status_code == 200
    ((action, record),) = env.audit.calls
    assert action == "alert.delivery_acked"
    assert str(record["request_id"]) == r.headers["x-correlation-id"]
