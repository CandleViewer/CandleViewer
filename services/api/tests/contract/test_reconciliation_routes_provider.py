"""Contract, provider side (E29-T06 #914): `reconcileAccount` and `resolveReconciliation` as their
router serves them, over `test_admin_reconciliation`'s rig (the real step-up service and admin
guard; a fake account store and OMS). Every answer is checked against 22: its status is one the
operation declares (each declared status but `501`'s fake-free case is reached), a 2xx body is the
operation's response schema with its declared headers, and a problem is a `Problem` whose `code`
the catalogue (`x-error-codes`) registers, with its title."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import Response

from tests.contract._admin_support import SPEC, validate_example
from tests.unit.api.test_admin_reconciliation import (
    ABSENT,
    ACCOUNT,
    BODY,
    KEY2,
    RESOLVE,
    RUN,
    SECOND,
    Rig,
    _rig,
)

_CODES = {entry["code"]: entry for entry in SPEC["x-error-codes"]}
_PASS_OP = SPEC["paths"]["/admin/reconciliation/{accountId}"]["post"]
_RESOLVE_OP = SPEC["paths"]["/admin/reconciliation/{accountId}/resolve"]["post"]


def _check(operation: dict[str, Any], schema: str, response: Response) -> None:
    status = str(response.status_code)
    assert status in operation["responses"], f"{status} is not declared"
    body = response.json()
    if response.status_code < 300:
        validate_example(f"/components/schemas/{schema}", body)
        declared = operation["responses"][status]["headers"]
        assert response.headers["cache-control"] == "no-store" and "Cache-Control" in declared
        assert "Idempotency-Replayed" in declared
        return
    validate_example("/components/schemas/Problem", body)
    entry = _CODES[body["code"]]
    assert body["type"].endswith(f"/errors/{body['code']}")
    if response.status_code not in (401, 403) or body["code"] == "step_up_required":
        assert body["title"] == entry["title"]  # the guard's 401 and 403 are the admin area's
    if body["code"] != "validation_failed":  # 22 answers its body and key checks `422`
        assert body["status"] == response.status_code == entry["status"]


def _pass_answers(r: Rig) -> list[Response]:
    answers = [r.post(RUN.format(ACCOUNT)), r.post(RUN.format(ACCOUNT))]  # 202, its replay
    answers.append(r.post(RUN.format(ACCOUNT), key=KEY2))  # 202 joined
    answers.append(r.post(RUN.format(SECOND)))  # 409 idempotency_key_reuse
    answers.append(r.post(RUN.format(ACCOUNT), key=None))  # 422
    answers.append(r.post(RUN.format(ABSENT), key=str(SECOND)))  # 404
    answers.append(r.post(RUN.format(ACCOUNT), role="viewer", key=str(ABSENT)))  # 403
    answers.append(r.post(RUN.format(ACCOUNT), who=None))  # 401
    r.service.states[SECOND] = "stale_lockout"
    answers.append(r.post(RUN.format(SECOND), key=str(ACCOUNT)))  # 409 reconciliation_locked
    r.runtime.readiness = "starting"
    answers.append(r.post(RUN.format(SECOND), key=str(ACCOUNT)))  # 503 oms_not_ready
    r.oms[0] = None
    answers.append(r.post(RUN.format(SECOND), key=str(ACCOUNT)))  # 501
    return answers


def _resolve_answers(r: Rig) -> list[Response]:
    r.service.states[ACCOUNT] = "stale_lockout"
    answers = [r.post(RESOLVE.format(ACCOUNT), json=BODY)]  # 403 step_up_required
    _, resolved = r.stepped()
    _, replayed = r.stepped()
    answers += [resolved, replayed]  # 200 and its replay, each behind a fresh code
    answers.append(r.stepped(body={"reason": "Another decision."})[1])  # 409 reuse
    answers.append(r.stepped(key=KEY2)[1])  # 409 nothing_to_resolve
    answers.append(r.post(RESOLVE.format(ACCOUNT), json={}))  # 422
    answers.append(r.stepped(account=ABSENT, key=str(ABSENT))[1])  # 404
    answers.append(r.post(RESOLVE.format(ACCOUNT), json=BODY, who=None))  # 401
    r.w.audit.fail_on = frozenset({"oms.reconcile"})
    r.service.states[SECOND] = "stale_lockout"
    answers.append(r.stepped(account=SECOND, key=str(SECOND))[1])  # 503 audit_unavailable
    r.oms[0] = None
    answers.append(r.stepped(account=SECOND, key=str(SECOND))[1])  # 501
    return answers


@pytest.mark.parametrize(
    ("operation", "schema", "drive"),
    [
        (_PASS_OP, "ReconciliationPass", _pass_answers),
        (_RESOLVE_OP, "ReconciliationResolved", _resolve_answers),
    ],
    ids=["reconcileAccount", "resolveReconciliation"],
)
async def test_every_answer_the_route_gives_is_one_22_declares(
    operation: dict[str, Any], schema: str, drive: Any
) -> None:
    answers = drive(await _rig())
    for response in answers:
        _check(operation, schema, response)
    assert {str(a.status_code) for a in answers} == set(operation["responses"])
    first = next(a for a in answers if a.status_code < 300)
    replays = [a for a in answers if a.headers.get("idempotency-replayed") == "true"]
    assert len(replays) == 1 and replays[0].content == first.content
