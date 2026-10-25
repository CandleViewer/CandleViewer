"""E29-T04 (#913) slice 4, S4-D1a: the order routes' shared admission (`api/order_admission.py`).

`OnAccount` is the `rbac.denied` writer every order route shares (C-2.9): it forwards the
request's correlation id as its caller names it, `None` when the caller names none, and names
the account it concerns as the record's object, over any object the caller named. The scan in
`test_audit_request_id_carried.py` reads only that the keyword is passed; these pin its value
(CR-S4D1A-01)."""

from __future__ import annotations

import uuid
from typing import Any

from candleviewer.api.order_admission import OnAccount
from candleviewer.domain.primitives import AccountId


class _Recording:
    """The audit writer's `emit`, each call kept."""

    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **fields: Any) -> None:
        self.emitted.append((action, fields))


async def test_on_account_forwards_the_request_id_and_names_its_account_over_the_callers() -> None:
    audit, account, request_id = _Recording(), AccountId(uuid.uuid4()), uuid.uuid4()
    await OnAccount(audit, account).emit(
        "rbac.denied", actor_label="u", object_kind="order", object_id="x", request_id=request_id
    )
    [(action, fields)] = audit.emitted
    assert (action, fields["request_id"], fields["actor_label"]) == ("rbac.denied", request_id, "u")
    assert (fields["object_kind"], fields["object_id"]) == ("exchange_account", str(account))


async def test_on_account_forwards_none_when_its_caller_names_no_request_id() -> None:
    audit = _Recording()
    await OnAccount(audit, AccountId(uuid.uuid4())).emit("rbac.denied", actor_label="u")
    [(_, fields)] = audit.emitted
    assert "request_id" in fields and fields["request_id"] is None
