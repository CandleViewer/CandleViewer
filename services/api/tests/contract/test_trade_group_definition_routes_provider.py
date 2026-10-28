"""Contract, provider side (E28-T05 #909, S2b; C-6.2): each status the two definition reads
declare in 22, answered by their router over the unit test's world, validates against its schema.
Unwired, both answer 501, which 22 does not declare (the profile reads' precedent; a later contract
delta adds it)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.trade_group_definitions import DefinitionScopeDeniedError
from tests.contract._admin_support import SPEC, validate_example
from tests.unit.api.test_trade_group_definition_create import L, caller, payload
from tests.unit.api.test_trade_group_definition_create import World as Writes
from tests.unit.api.test_trade_group_definition_reads import CORE3, MISSING, A, C, World, principal

CALLERS = {"owner": principal("owner"), "manager": principal("manager", A, C), "anonymous": None}
CALLERS["bare"] = principal("viewer", read=False)  # the forbidden-role case


@pytest.mark.parametrize(
    ("caller", "definition", "fault", "status"),
    [
        ("owner", None, None, 200), ("owner", CORE3, None, 200), ("manager", CORE3, None, 404),
        ("owner", None, "cursor", 400), ("anonymous", CORE3, None, 401), ("bare", None, None, 403),
        ("owner", CORE3, DefinitionScopeDeniedError(), 403),
        ("owner", None, StorageTierUnavailable("down"), 503), ("owner", None, "store", 503),
        ("owner", CORE3, "readiness", 503), ("owner", None, "resolver", 501),
        ("owner", CORE3, "resolver", 501),
    ],
)  # fmt: skip
def test_each_answer_is_one_22_declares(
    caller: str, definition: UUID | None, fault: Any, status: int
) -> None:
    world = World(fault if fault in ("store", "readiness", "resolver") else "")
    world.principal, world.store.fails = CALLERS[caller], None if isinstance(fault, str) else fault
    resp = world.read(definition, **({"cursor": "nope"} if fault == "cursor" else {}))
    assert resp.status_code == status
    if status != 501:  # the body, against what the operation declares for its status
        path = "/trade-group-definitions" + ("" if definition is None else "/{definitionId}")
        declared = SPEC["paths"][path]["get"]["responses"][str(status)]
        own = "#/paths/" + path.replace("/", "~1") + f"/get/responses/{status}"
        media = "application~1json" if status == 200 else "application~1problem+json"
        validate_example(f"{declared.get('$ref', own)[1:]}/content/{media}/schema", resp.json())
    assert world.store.reads == int(status in (200, 404) or isinstance(fault, Exception))


@pytest.mark.parametrize(
    ("role", "sent", "fault", "status"),
    [
        ("owner", None, None, 201), ("owner", (A, L), None, 400), (None, None, None, 401),
        ("manager", None, None, 403), ("owner", (A, MISSING), None, 403),
        ("owner", None, "flag", 403), ("owner", (A, C), None, 409), ("owner", (A, A), None, 422),
        ("owner", None, "audit", 503), ("owner", None, "writes", 503),
    ],
)  # fmt: skip
def test_each_create_answer_is_one_22_declares(
    role: str | None, sent: tuple[UUID, ...] | None, fault: str | None, status: int
) -> None:
    """S2c: Pair's name is taken; unwired, 501 (undeclared, as above)."""
    world = Writes("writes" if fault == "writes" else "")
    world.principal, world.flag = None if role is None else caller(role), fault != "flag"
    world.faults = {"audit": RuntimeError("not started")} if fault == "audit" else {}
    resp = world.post(None if sent is None else payload(*sent, name="Pair" if C in sent else "N"))
    declared = SPEC["paths"]["/trade-group-definitions"]["post"]["responses"][str(status)]
    own, media = f"#/paths/~1trade-group-definitions/post/responses/{status}", "problem+json"
    media = "application~1" + ("json" if status == 201 else media)
    assert resp.status_code == status
    validate_example(f"{declared.get('$ref', own)[1:]}/content/{media}/schema", resp.json())
