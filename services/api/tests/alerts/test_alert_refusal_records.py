"""E40-X01 Part B (#5696): the refusals the alert routes record share one budget per caller.

Gherkin "an alert write is bounded before any work": "no record is written for the refused write
beyond the refusal budget". A role refusal on the alert routes is counted in `authz_denied_total`
(SR-125) and recorded within the per-caller budget as `rbac.denied`, which it shares with
`alert.denied` and `alert.scope_refused` across the CRUD and inbox routers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from prometheus_client import REGISTRY

import candleviewer.app as app_module
from candleviewer.api.alert_body import REFUSAL_REASONS
from candleviewer.api.alert_deliveries import DenialBudget, make_alert_deliveries_router
from candleviewer.api.alerts import make_alerts_router
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.settings import Settings
from tests.alerts._alert_api_env import PRICE_CROSS, USER_A, USER_B
from tests.alerts._alert_api_env import Env as AlertsEnv
from tests.alerts._deliveries_env import ALERT_B
from tests.alerts._deliveries_env import Env as DeliveriesEnv
from tests.alerts.test_alert_write_rate import Clock

READ, WRITE = "alerts:read", "alerts:write"
_OUTCOME = {"outcome": "shown", "permission": "granted"}
ROUTES = [
    ("GET", "/alerts", None, READ),
    ("POST", "/alerts", PRICE_CROSS, WRITE),
    ("GET", "/alerts/{alertId}", None, READ),
    ("PUT", "/alerts/{alertId}", PRICE_CROSS, WRITE),
    ("DELETE", "/alerts/{alertId}", None, WRITE),
    ("PUT", "/alerts/{alertId}/enabled", {"enabled": False}, WRITE),
    ("PUT", "/alerts/{alertId}/snooze", {"until": None}, WRITE),
    ("GET", "/alerts/deliveries", None, READ),
    ("POST", "/alerts/deliveries/{deliveryId}/ack", None, WRITE),
    ("POST", "/alerts/deliveries/ack-all", None, WRITE),
    ("POST", "/alerts/deliveries/{deliveryId}/desktop-outcome", _OUTCOME, WRITE),
]


def _denials(permission: str) -> float:
    return REGISTRY.get_sample_value("authz_denied_total", {"permission": permission}) or 0.0


def _budget(per_window: int, clock: Clock) -> DenialBudget:
    return DenialBudget(per_window=per_window, window_s=60, clock=clock)


def _records(env: Any, action: str) -> list[dict[str, Any]]:
    return [kw for a, kw in env.audit.calls if a == action]


def _world(template: str) -> tuple[Any, str, Callable[[], Any]]:
    """The app serving *template*, a row of its caller's, and the state a refusal must not move."""
    if "deliveries" in template:
        inbox = DeliveriesEnv()
        row = inbox.store.add(channel="desktop", status="queued")
        return inbox, str(row.id), lambda: dict(inbox.store.rows)
    crud = AlertsEnv()
    return crud, crud.create()["id"], lambda: (dict(crud.repo.rows), set(crud.repo.deleted))


@pytest.mark.parametrize(("method", "template", "body", "perm"), ROUTES)
def test_alert_route_without_its_permission_is_403_recorded_and_counted(
    method: str, template: str, body: Any, perm: str
) -> None:
    """A role refusal on each of the 11 `/alerts*` routes is the 403, counted once in
    `authz_denied_total` and recorded as one `rbac.denied` naming no object; nothing changes
    (SR-E40-21, SR-125, SR-062)."""
    env, oid, state = _world(template)
    env.perms = frozenset({READ, WRITE} - {perm})
    before, seen, counted = state(), len(env.audit.calls), _denials(perm)
    path = template.replace("{alertId}", oid).replace("{deliveryId}", oid)
    r = env.c.request(method, path, json=body)
    assert r.status_code == 403 and r.json()["required_permissions"] == [perm]
    assert _denials(perm) == counted + 1 and state() == before
    ((action, record),) = env.audit.calls[seen:]
    assert (action, record) == ("rbac.denied", {
        "actor_label": USER_A, "actor_user_id": USER_A, "object_kind": None, "object_id": None,
        "request_id": None, "outcome": AuditOutcome.DENIED, "severity": Severity.WARNING,
        "reason": f"missing_permission:{perm}:self", "session_id": "s",
        "after_state": {"route": f"{method} {template}"},
    })  # fmt: skip


def test_role_refusal_reads_alike_for_an_existing_and_a_missing_alert() -> None:
    """The role refusal comes before any lookup: the answer and the record are the same for an
    alert of the caller's and for no alert at all (SR-E40-21)."""
    env = AlertsEnv()
    aid = env.create()["id"]
    env.perms, seen = frozenset({READ}), len(env.audit.calls)
    answers = [env.c.put(f"/alerts/{x}/enabled", json={"enabled": False}) for x in (aid, uuid4())]
    assert [a.status_code for a in answers] == [403, 403]
    assert answers[0].json() == answers[1].json()
    first, second = env.audit.calls[seen:]
    assert first == second


def _refuse(env: AlertsEnv, kind: str, aid: str) -> str:
    """One refusal of *kind* (a role refusal, another user's alert, an ungranted account): its
    answer."""
    if kind == "role":
        env.perms = frozenset({READ})
        r = env.c.put(f"/alerts/{aid}/enabled", json={"enabled": False})
    elif kind == "foreign":
        env.user = USER_B
        r = env.c.get(f"/alerts/{aid}")
    else:
        ungranted = PRICE_CROSS | {"exchange_account_id": "00000000-0000-4000-8000-0000000000ff"}
        r = env.c.post("/alerts", json=ungranted)
    assert r.status_code == (404 if kind == "foreign" else 403)
    answer: str = r.text
    return answer


@pytest.mark.parametrize(
    ("kind", "action"),
    [("role", "rbac.denied"), ("foreign", "alert.denied"), ("scope", "alert.scope_refused")],
)
def test_the_held_count_rides_the_callers_next_record(kind: str, action: str) -> None:
    """Gherkin "beyond the refusal budget": a refusal past it is answered the same, writes no
    record and is counted; the caller's next record carries the count (SR-E40-16)."""
    clock = Clock()
    env = AlertsEnv(denials=_budget(1, clock))
    aid = env.create()["id"]
    assert len({_refuse(env, kind, aid) for _ in range(3)}) == 1
    assert env.held == [None, None]
    clock.t += 60.0
    _refuse(env, kind, aid)
    first, last = _records(env, action)
    assert "suppressed_before" not in first.get("after_state", {})
    assert last["after_state"]["suppressed_before"] == 2


def test_crud_and_inbox_refusals_share_one_budget_per_caller() -> None:
    """One budget per acting user across both routers: alternating between them does not double
    the allowance, and the next record carries what either held (SR-E40-16)."""
    clock = Clock()
    env = DeliveriesEnv(denials=_budget(2, clock))
    theirs = env.store.add(user=USER_B, alert=ALERT_B)
    assert env.c.post(f"/alerts/deliveries/{theirs.id}/ack").status_code == 404
    env.perms = frozenset({READ})
    assert env.c.put(f"/alerts/{uuid4()}/enabled", json={"enabled": False}).status_code == 403
    assert env.c.post("/alerts/deliveries/ack-all").status_code == 403  # held
    assert env.audit.actions() == ["alert.denied", "rbac.denied"] and env.held == [None]
    clock.t += 60.0
    env.c.post("/alerts/deliveries/ack-all")
    assert env.audit.calls[-1][1]["after_state"]["suppressed_before"] == 1


def test_create_app_hands_both_alert_routers_one_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """The app wires one budget into both routers, and their counters: each bound refusal reason
    bound at 0, a held record counted (SR-E40-16, SR-125)."""
    seen: dict[str, dict[str, Any]] = {}

    def spy(name: str, make: Any) -> Any:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            seen[name] = kwargs
            return make(*args, **kwargs)

        return wrapped

    monkeypatch.setattr(app_module, "make_alerts_router", spy("crud", make_alerts_router))
    monkeypatch.setattr(
        app_module, "make_alert_deliveries_router", spy("inbox", make_alert_deliveries_router)
    )
    facade = app_module.create_app(Settings(alerts_evaluator_enabled=False)).state.metrics_facade
    assert isinstance(seen["crud"]["denials"], DenialBudget)
    assert seen["crud"]["denials"] is seen["inbox"]["denials"]
    seen["crud"]["on_refused"]("rate_limited")
    seen["inbox"]["on_refused"]("body_too_large")
    seen["inbox"]["on_held"]()

    def sample(name: str, **labels: str) -> float | None:
        value: float | None = facade.registry.get_sample_value(name, {"env": facade.env, **labels})
        return value

    counted = {r: sample("cv_alert_write_refused_total", reason=r) for r in REFUSAL_REASONS}
    assert counted == dict.fromkeys(REFUSAL_REASONS, 0.0) | {"rate_limited": 1, "body_too_large": 1}
    assert sample("cv_alert_refusal_records_held_total") == 1.0
    specs = {s.name: (s.labels, s.max_series, s.status) for s in CATALOGUE}
    assert specs["cv_alert_write_refused_total"] == (("reason",), len(REFUSAL_REASONS), "live")
    assert specs["cv_alert_refusal_records_held_total"] == ((), 1, "live")


def test_a_refusal_record_that_fails_gives_its_slot_back_and_answers_503() -> None:
    """A due record that cannot be written is the declared 503 with nothing changed; its slot
    and its count go back, so the next refusal is written and carries it (SR-E40-16, C-2.9)."""
    env = AlertsEnv(denials=_budget(1, Clock()))
    aid = env.create()["id"]
    before = dict(env.repo.rows)
    env.perms = frozenset({READ})

    async def refuse(action: str, **kw: Any) -> None:
        raise AuditUnavailable("WAL full")

    real, env.audit.emit = env.audit.emit, refuse  # type: ignore[method-assign]  # fault injection
    r = env.c.put(f"/alerts/{aid}/enabled", json={"enabled": False})
    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    assert env.repo.rows == before
    env.audit.emit = real  # type: ignore[method-assign]  # fault injection
    assert env.c.put(f"/alerts/{aid}/enabled", json={"enabled": False}).status_code == 403
    (record,) = _records(env, "rbac.denied")
    assert record["after_state"]["suppressed_before"] == 1 and env.held == []
