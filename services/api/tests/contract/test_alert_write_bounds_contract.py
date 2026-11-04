"""Provider contract (#5696, E40-X01 Part B): the alert write bounds answer as 22 declares.

Each refusal of a bound validates against the response its operation declares for the status (the
`413`, `422` and `429` that #5696 adds), the `429` carries the declared integer `Retry-After` and
no `RateLimit-*` header, and the numbers in 22's "Alert write bounds and refusal records" are the
code's (C-6.1, C-6.2). The routers run over the in-memory stores of `tests/alerts/`.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from candleviewer.api.alert_body import MAX_ALERT_BODY_BYTES, MAX_ALERT_JSON_DEPTH, MAX_ALERT_VALUES
from candleviewer.api.alert_deliveries import DENIAL_WINDOW_S, DENIALS_PER_WINDOW
from candleviewer.api.alerts import ALERT_WRITE_BURST, ALERT_WRITES_PER_MINUTE
from tests.alerts.test_alert_write_bounds import BODY_ROUTES, deep, padded, sized, target
from tests.alerts.test_alert_write_rate import Clock, limited, spend
from tests.contract.test_alert_inbox_contract import _SPEC, _check
from tests.openapi_helpers import deref

#: (path, method) of each alert write in 22.
OPS = {
    "create": ("/alerts", "post"),
    "update": ("/alerts/{alertId}", "put"),
    "delete": ("/alerts/{alertId}", "delete"),
    "enabled": ("/alerts/{alertId}/enabled", "put"),
    "snooze": ("/alerts/{alertId}/snooze", "put"),
    "desktop": ("/alerts/deliveries/{deliveryId}/desktop-outcome", "post"),
}


@pytest.mark.parametrize("op", BODY_ROUTES)
def test_alert_body_bound_refusals_are_the_declared_413_and_422(op: str) -> None:
    """Over the bytes, past the depth and past the values: each answer is the one the operation
    declares for its status (SR-E40-17)."""
    t = target(op)
    path, method = OPS[op]
    over = json.dumps(sized(t.body, "padding", MAX_ALERT_VALUES + 1)).encode()
    for content, status in (
        (padded(t.body, MAX_ALERT_BODY_BYTES + 1), 413),
        (deep(MAX_ALERT_JSON_DEPTH + 1), 422),
        (over, 422),
    ):
        r = t.send(content)
        assert r.status_code == status, r.text[:300]
        _check(path, method, status, r.json())


@pytest.mark.parametrize("op", ["create", "update", "delete", "enabled", "snooze"])
def test_alert_write_past_the_burst_is_the_declared_429_with_retry_after(op: str) -> None:
    """The 429 is the declared `RateLimited`, with its integer `Retry-After` header and no
    `RateLimit-*` one: this bucket sends none (SR-E40-16)."""
    t = limited(op, Clock())
    spend(t)
    path, method = OPS[op]
    r = t.write()
    _check(path, method, 429, r.json())
    declared = deref(_SPEC, _SPEC["paths"][path][method]["responses"]["429"])["headers"]
    assert deref(_SPEC, declared["Retry-After"])["schema"] == {"type": "integer"}
    assert int(r.headers["Retry-After"]) == r.json()["retry_after_seconds"] >= 1
    assert not [h for h in r.headers if h.lower().startswith("ratelimit-")]


def test_alert_write_bounds_in_22_are_the_codes() -> None:
    """The numbers 22 states are the constants the routes enforce, and each new answer's code is
    catalogued with its status (SR-E40-16, SR-E40-17)."""
    text: Any = _SPEC["info"]["description"]
    start = text.index("### Alert write bounds and refusal records")
    section = " ".join(text[start : text.index("### RBAC", start)].split())
    for phrase in (
        f"{MAX_ALERT_BODY_BYTES // 1024} KiB ({MAX_ALERT_BODY_BYTES:,} bytes)",
        f"at most {MAX_ALERT_JSON_DEPTH} levels",
        f"at most {MAX_ALERT_VALUES:,} values",
        f"bucket of {ALERT_WRITE_BURST}, refilled at {ALERT_WRITES_PER_MINUTE} a minute",
        f"up to {DENIALS_PER_WINDOW} records in a rolling hour",
    ):
        assert phrase in section, phrase
    assert DENIAL_WINDOW_S == 3600
    catalogue = {(e["status"], e["code"]) for e in _SPEC["x-error-codes"]}
    assert {(413, "payload_too_large"), (429, "rate_limited")} <= catalogue
