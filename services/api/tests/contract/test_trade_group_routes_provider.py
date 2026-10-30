"""Contract, provider side (E28-T05 #909, S2f; C-6.2): each status `listTradeGroups` and
`getTradeGroup` declare in 22, answered by their router over the unit test's world, validates
against its schema, the `TradeGroup` items included. Unwired (no resolver), both answer 501, which
22 does not declare: the profile reads' precedent, asserted directly (a later contract delta adds
it)."""

from __future__ import annotations

from typing import Any, get_args

import pytest

from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.trade_groups import (
    TradeGroupStatus,
    TradeGroupStoreScopeDeniedError,
)
from tests.contract._admin_support import SPEC, validate_example
from tests.unit.api.test_trade_group_routes import CORE3, PAIR, A, C, World, principal

CALLERS = {"owner": principal("owner"), "manager": principal("manager", A, C), "anonymous": None}
CALLERS["bare"] = principal("viewer", held=())  # the forbidden-role case
BAD = {"cursor": {"cursor": "nope"}, "range": {"from": "2026-10-20T08:00:00"}}


@pytest.mark.parametrize(
    ("caller", "group", "fault", "status"),
    [
        ("owner", None, None, 200), ("owner", PAIR, None, 200), ("manager", CORE3, None, 404),
        ("owner", None, "cursor", 400), ("owner", None, "range", 400),
        ("anonymous", PAIR, None, 401), ("bare", None, None, 403),
        ("owner", PAIR, TradeGroupStoreScopeDeniedError(), 403),
        ("owner", None, StorageTierUnavailable("down"), 503), ("owner", None, "store", 503),
        ("owner", None, "resolver", 501), ("owner", PAIR, "resolver", 501),
    ],
)  # fmt: skip
def test_each_answer_is_one_22_declares(caller: str, group: Any, fault: Any, status: int) -> None:
    world = World(fault if fault in ("store", "resolver") else "")
    world.principal, world.store.fails = CALLERS[caller], None if isinstance(fault, str) else fault
    resp = world.read(group.group.id if group else None, **BAD.get(fault, {}))
    assert resp.status_code == status
    if status != 501:  # the body, against what the operation declares for its status
        path = "/trade-groups" + ("" if group is None else "/{tradeGroupId}")
        declared = SPEC["paths"][path]["get"]["responses"][str(status)]
        own = "#/paths/" + path.replace("/", "~1") + f"/get/responses/{status}"
        media = "application~1json" if status == 200 else "application~1problem+json"
        validate_example(f"{declared.get('$ref', own)[1:]}/content/{media}/schema", resp.json())


def test_the_status_filter_is_22s_trade_group_status_and_repeats() -> None:
    declared = SPEC["paths"]["/trade-groups"]["get"]["parameters"]
    status = next(p for p in declared if p.get("name") == "status")
    enum = SPEC["components"]["schemas"]["TradeGroupStatus"]["enum"]
    assert get_args(TradeGroupStatus) == tuple(enum) and status["explode"] is True
