"""Contract, provider side (E28-T05 #909, S3c; C-6.2): each status `previewTradeGroup` declares in
22, answered by its router over the unit test's world, validates against its schema. Unwired, it
answers 501, which 22 does not declare (the definition routes' precedent; a later delta adds it)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.contract._admin_support import SPEC, validate_example
from tests.unit.api.test_trade_group_preview_route import ALT, FOREIGN, A, B, L, World, body


@pytest.mark.parametrize(
    ("who", "sent", "fault", "status"),
    [
        ("owner", body(), None, 200), ("owner", body(A, L), None, 400),
        ("nobody", body(), None, 401), ("viewer", body(), None, 403),
        ("owner", body(A, FOREIGN), None, 403),
        ("owner", body((B, {"profile_id": str(ALT)})), None, 404),
        ("owner", body(A, A), None, 422), ("owner", body(), "rate", 429),
        ("owner", body(), "audit", 503),
    ],
)  # fmt: skip
def test_each_preview_answer_is_one_22_declares(
    who: str, sent: dict[str, Any], fault: str | None, status: int
) -> None:
    world = World(rate=1 if fault == "rate" else 20)
    world.fail = "trade_group.previewed" if fault == "audit" else None
    if fault == "rate":
        world.post(sent, who=who)  # the one token
    resp = world.post(sent, who=who)
    assert resp.status_code == status
    declared = SPEC["paths"]["/trade-groups/preview"]["post"]["responses"][str(status)]
    own = f"#/paths/~1trade-groups~1preview/post/responses/{status}"
    media = "application~1" + ("json" if status == 200 else "problem+json")
    validate_example(f"{declared.get('$ref', own)[1:]}/content/{media}/schema", resp.json())
