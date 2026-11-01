"""Contract (#2904 PR 2): `acknowledgeAuditChainBreak` on the real `create_app` (the RBAC pack's
world). The Owner, holding the `killswitch` step-up, acknowledges an engaged break: the answer is
22's `200` shape, the acknowledgement is written ahead with the session, IP and request named,
and the halt lifts. `scope: none`: no cross-account cell; the other roles' cells are the matrix's
own (`rbac/matrix.yaml`, `executed`), and the unit cases are `test_audit_break_ack_route.py`'s."""

from __future__ import annotations

from typing import Any

import jsonschema
import pytest

import candleviewer.app as appmod
from candleviewer.admin.wiring import build_audit_break_halt
from candleviewer.audit.break_halt import ACKNOWLEDGED, AuditBreakHaltService, BreakIdentity
from candleviewer.audit.models import ChainBreakKind
from tests.contract.rbac.rbac_harness import bearer, build_world, load_contract, user_id_of

_TEMPLATE = "/admin/audit/chain-breaks/{firstBadId}/acknowledge"
_BREAK = BreakIdentity(41207, "entry_hash_mismatch")


def _operation() -> dict[str, Any]:
    operation: dict[str, Any] = load_contract()["paths"][_TEMPLATE]["post"]
    return operation


def test_the_operation_is_owner_scoped_and_names_the_break_by_the_verifiers_kinds() -> None:
    operation = _operation()
    assert operation["operationId"] == "acknowledgeAuditChainBreak"
    assert operation["x-rbac"] == {"permissions": ["killswitch:write"], "scope": "none"}
    body = operation["requestBody"]["content"]["application/json"]["schema"]
    kinds = body["properties"]["kind"]["enum"]
    assert set(kinds) == {kind.value for kind in ChainBreakKind} | {"unknown"}
    assert body["required"] == ["kind", "reason"] and body["additionalProperties"] is False
    assert set(operation["responses"]) == {"200", "401", "403", "409", "422", "503"}


def test_the_owner_acknowledges_on_the_real_app_written_ahead_and_the_halt_lifts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[AuditBreakHaltService] = []
    real = build_audit_break_halt  # what `create_app` calls, by its name in `app`

    def capture(*args: Any, **kwargs: Any) -> AuditBreakHaltService:
        built.append(real(*args, **kwargs))
        return built[-1]

    monkeypatch.setattr(appmod, "build_audit_break_halt", capture)
    world = build_world(monkeypatch)
    [service] = built
    assert service.halt.trip(_BREAK)
    written = len(world.audit.records)
    url = _TEMPLATE.format(firstBadId=_BREAK.first_bad_id)
    body = {"kind": _BREAK.kind, "reason": "Restored row 41207 from the off-box mirror"}
    response = world.client.post(url, json=body, headers=bearer("owner"))
    assert response.status_code == 200, response.text
    schema = _operation()["responses"]["200"]["content"]["application/json"]["schema"]
    jsonschema.validate(response.json(), schema)
    assert response.json() == {"first_bad_id": 41207, "kind": _BREAK.kind, "halted": False}
    [record] = [r for r in world.audit.records[written:] if r["action"] == ACKNOWLEDGED]
    assert (record["object_id"], record["actor_user_id"]) == (
        _BREAK.object_id, user_id_of("owner")
    )  # fmt: skip
    assert record["session_id"] is not None and record["reason"] == body["reason"]
    assert not service.halt.engaged
