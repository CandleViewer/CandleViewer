"""Provider contract (E40-T04 PR-A): the inbox and notification routes answer the bodies
`22-api-openapi.yaml` declares for `listAlertDeliveries`, `ackAlertDelivery`,
`ackAllAlertDeliveries`, `reportAlertDesktopOutcome` and `listNotifications` (C-6.1, C-6.2).

Each answer validates against the schema the operation declares for its status, and the 200
items round-trip through the generated models, so a payload that drifts from the contract fails
here. The routers run over the in-memory stores of `tests/alerts/`; the SQL behind them is
pinned in `tests/integration/storage/test_notifications_union_pg.py`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from candleviewer.api import alert_deliveries
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from tests.alerts._deliveries_env import ALERT_B, Env
from tests.alerts.test_notifications_api import ACCT, ORDER, RULE, _row
from tests.alerts.test_notifications_api import Env as NotificationsEnv
from tests.openapi_helpers import deref

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_USER_B = "00000000-0000-4000-8000-00000000000b"


def _check(path: str, method: str, status: int, body: Any) -> None:
    """*body* is what the operation declares for *status* (which it must declare)."""
    responses = _SPEC["paths"][path][method]["responses"]
    assert str(status) in responses, f"{method.upper()} {path} does not declare {status}"
    content = deref(_SPEC, responses[str(status)]).get("content", {})
    if status == 204:
        assert body == b"" and not content
        return
    (media,) = content.values()
    Draft202012Validator(media["schema"]).validate(body)


@pytest.fixture
def env() -> Env:
    e = Env()
    e.store.add()
    e.store.add(status="failed", error_message="email relay timeout", body="")
    e.store.add(context={"storm_summary": True}, severity="critical")
    return e


def test_list_alert_deliveries_200(env: Env) -> None:
    r = env.c.get("/alerts/deliveries", params={"limit": 2})
    _check("/alerts/deliveries", "get", r.status_code, r.json())
    assert r.json()["meta"]["has_more"] is True
    for item in r.json()["items"]:
        api.AlertDelivery.model_validate(item)


def test_list_alert_deliveries_404_for_a_foreign_alert(env: Env) -> None:
    r = env.c.get("/alerts/deliveries", params={"alert_id": ALERT_B})
    _check("/alerts/deliveries", "get", r.status_code, r.json())


def test_ack_alert_delivery_200_and_404(env: Env) -> None:
    did = next(iter(env.store.rows))
    r = env.c.post(f"/alerts/deliveries/{did}/ack")
    _check("/alerts/deliveries/{deliveryId}/ack", "post", r.status_code, r.json())
    api.AlertDelivery.model_validate(r.json())
    foreign = env.store.add(user=_USER_B, alert=ALERT_B)
    r = env.c.post(f"/alerts/deliveries/{foreign.id}/ack")
    _check("/alerts/deliveries/{deliveryId}/ack", "post", r.status_code, r.json())


def test_ack_all_200(env: Env) -> None:
    r = env.c.post("/alerts/deliveries/ack-all")
    _check("/alerts/deliveries/ack-all", "post", r.status_code, r.json())
    assert r.json() == {"acknowledged": 2}


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"outcome": "shown", "permission": "granted"}, 204),
        ({"outcome": "blocked", "permission": "denied"}, 204),
        ({"outcome": "shown", "permission": "granted", "extra": 1}, 422),
    ],
)
def test_report_desktop_outcome(env: Env, body: dict[str, Any], status: int) -> None:
    d = env.store.add(channel="desktop", status="queued")
    r = env.c.post(f"/alerts/deliveries/{d.id}/desktop-outcome", json=body)
    assert r.status_code == status
    path = "/alerts/deliveries/{deliveryId}/desktop-outcome"
    _check(path, "post", r.status_code, r.content if status == 204 else r.json())


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/alerts/deliveries", "get"),
        ("/alerts/deliveries/{deliveryId}/ack", "post"),
        ("/alerts/deliveries/ack-all", "post"),
        ("/alerts/deliveries/{deliveryId}/desktop-outcome", "post"),
    ],
)
def test_store_down_is_the_shared_503(env: Env, path: str, method: str) -> None:
    env.store_up = False
    body = {"outcome": "shown", "permission": "granted"}
    r = env.c.request(method.upper(), path.format(deliveryId=1), json=body)
    _check(path, method, r.status_code, r.json())


def test_list_notifications_200() -> None:
    env = NotificationsEnv()
    env.store.rows = [
        _row("alert", 1, 4471, title="BTC reclaims 64k", symbol="BTCUSDT"),
        _row("rule", 2, 3, title="Move SL", event="action_ok", source_uuid=RULE, account_id=ACCT),
        _row(
            "order",
            3,
            9,
            title=None,
            severity=None,
            event="reject",
            code="10018",
            symbol="BTCUSDT",
            source_uuid=ORDER,
            account_id=ACCT,
        ),
        _row("system", 4, 5, title="Dead-man's-switch call owed", severity="warning"),
    ]
    env.store.last = env.store.rows[-1]
    r = env.c.get("/notifications")
    _check("/notifications", "get", r.status_code, r.json())
    for item in r.json()["items"]:
        api.Notification.model_validate(item)


def test_list_notifications_503() -> None:
    env = NotificationsEnv()
    env.store_up = False
    r = env.c.get("/notifications")
    _check("/notifications", "get", r.status_code, r.json())


#: The modules whose `Problem(<status>, "<code>", ...)` these operations answer with.
_ROUTERS = ("alert_deliveries.py", "notifications.py", "alerts_http.py")
_PROBLEM = re.compile(r'Problem\(\s*(\d{3}),\s*"([^"]+)"')
_CALL = re.compile(r"(?<!class )\bProblem\(")


def test_every_problem_code_the_routes_answer_is_catalogued_with_its_status() -> None:
    """22's `x-error-codes` is the closed catalogue of `code` (no service emits one outside it):
    a refused write-ahead record is `audit_unavailable`, a store down `store_unavailable`. Each
    status is the catalogue's, but `validation_failed` may also be the 422 of
    `UnprocessableEntity`, as `test_openapi_conformance.py` allows; a call the pattern cannot
    read (a keyword or computed code) fails here instead of slipping past it."""
    here = Path(alert_deliveries.__file__).parent
    found: set[tuple[int, str]] = set()
    for name in _ROUTERS:
        source = (here / name).read_text("utf-8")
        literal = _PROBLEM.findall(source)
        assert len(literal) == len(_CALL.findall(source)), name  # every call has a literal code
        found |= {(int(status), code) for status, code in literal}
    catalogue = {(entry["status"], entry["code"]) for entry in _SPEC["x-error-codes"]}
    expected = {"audit_unavailable", "store_unavailable", "unauthenticated", "invalid_cursor"}
    assert expected <= {code for _, code in found}
    assert found <= catalogue | {(422, "validation_failed")}, found - catalogue


@pytest.mark.parametrize(
    ("body", "valid"),
    [
        ({"outcome": "skipped", "reason": "window_visible", "permission": "granted"}, True),
        ({"outcome": "skipped", "reason": "desktop_off", "permission": "denied"}, True),
        ({"outcome": "shown", "permission": "granted"}, True),
        ({"outcome": "skipped", "permission": "granted"}, False),  # a skip says why
        ({"outcome": "shown", "reason": "desktop_off", "permission": "granted"}, False),
        ({"outcome": "skipped", "reason": "bored", "permission": "granted"}, False),
    ],
)
def test_desktop_outcome_body_states_the_skipped_reason_conditional(
    body: dict[str, Any], valid: bool
) -> None:
    """E40-D02 CC-17 (#1130 S1 lens m-1): `reason` is required with `skipped`, refused otherwise."""
    op = _SPEC["paths"]["/alerts/deliveries/{deliveryId}/desktop-outcome"]["post"]
    schema = op["requestBody"]["content"]["application/json"]["schema"]
    errors = list(Draft202012Validator(schema).iter_errors(body))
    assert (not errors) is valid


_CONTEXT_SCHEMA = Draft202012Validator(
    deref(_SPEC, _SPEC["components"]["schemas"]["AlertDeliveryContext"])
)


def _model_refuses(context: dict[str, Any]) -> bool:
    try:
        api.AlertDeliveryContext.model_validate(context)
    except ValidationError:
        return True
    return False


@pytest.mark.parametrize(
    ("context", "model_refuses"),
    [
        ({"trigger_type": "t" * 1001}, True),
        ({"symbol": "S" * 1001}, True),
        ({"reason": "r" * 1001}, True),
        ({"metric": "m" * 1001}, True),
        # The key bound is `22`-only (`if: true` / `then:`): a `constr` key fails `mypy --strict`.
        ({"values": {"k" * 65: "1"}}, False),
        ({"values": {"price": "v" * 1001}}, True),
        ({"values": {"price": float("inf")}}, True),
        ({"values": {"price": float("-inf")}}, True),
        ({"values": {f"m{i}": 1 for i in range(65)}}, True),
    ],
)
def test_alert_delivery_context_bounds_are_contract(
    context: dict[str, Any], model_refuses: bool
) -> None:
    """#5676 Major 1: every string at most 1,000 characters, `values` keys at most 64 and at most
    64 entries, finite numbers only: `22` refuses each, and the generated model each bound it
    still carries (C-6.2)."""
    assert list(_CONTEXT_SCHEMA.iter_errors(context))
    assert _model_refuses(context) is model_refuses


def test_alert_delivery_context_nan_is_refused_by_the_model() -> None:
    """A JSON-schema validator lets NaN through `maximum`, so the finite bound is the model's."""
    assert _model_refuses({"values": {"price": float("nan")}})


@pytest.mark.parametrize(
    "context",
    [
        {"trigger_type": "t" * 1000, "values": {"k" * 64: 1.5, "p": "v" * 1000}},
        {"values": {f"m{i}": 1 for i in range(64)}},
        {"values": {"hi": sys.float_info.max, "lo": -sys.float_info.max}},
    ],
)
def test_alert_delivery_context_at_bound_is_accepted(context: dict[str, Any]) -> None:
    """At each bound (#5676 Minor b): 64 entries, a 64-character key, 1,000 characters and the
    largest finite float pass both `22` and the model."""
    assert not list(_CONTEXT_SCHEMA.iter_errors(context))
    assert not _model_refuses(context)
