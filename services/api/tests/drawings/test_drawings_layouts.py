"""E15-T01 spec Sec.7 at the /drawings router (#402): a drawing may name only a live layout of
its caller. The repository checks inside its own write transaction; the router maps a refusal
to 422 `layout_not_found` on the request field, worded the same for unknown, foreign and
deleted layouts, and `GET ?layout_id` asks the workspaces store (`is_live_layout`), else 404."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from _drawings_api_env import BATCH, TRENDLINE, USER_A, USER_B, Env, wire

OWN, FOREIGN, GONE = (str(uuid.uuid4()) for _ in range(3))  # GONE: deleted or never existed


@pytest.fixture
def env() -> Env:
    e = Env()
    e.repo.layouts = {OWN: str(USER_A), FOREIGN: str(USER_B)}
    return e


def _refusal(field: str) -> dict[str, str]:
    return {"field": field, "rule": "layout_not_found", "message": "No such layout."}


def test_single_writes_naming_a_missing_layout_are_one_identical_422(env: Env) -> None:
    d = env.create(layout_id=OWN)
    bodies = set()
    for layout in (FOREIGN, GONE):
        body = wire(TRENDLINE | {"layout_id": layout})
        for r in (env.c.post("/drawings", json=body), env.c.put(f"/drawings/{d['id']}", json=body)):
            assert r.status_code == 422 and r.json()["errors"] == [_refusal("layout_id")], r.text
            bodies.add(r.content)
    assert len(bodies) == 1  # unknown, foreign and deleted are indistinguishable
    assert env.listed() == [d]  # nothing was written


def test_batch_names_each_op_with_a_missing_layout_and_writes_nothing(env: Env) -> None:
    d1, d2 = env.create(), env.create()
    ops: list[dict[str, Any]] = [
        {"op": "create", "drawing": TRENDLINE | {"layout_id": OWN}},
        {"op": "create", "drawing": TRENDLINE | {"layout_id": FOREIGN}},
        {"op": "update", "id": d1["id"], "if_match": d1["updated_at"],
         "drawing": TRENDLINE | {"layout_id": GONE}},
        {"op": "delete", "id": d2["id"], "if_match": d2["updated_at"]},
    ]  # fmt: skip
    r = env.c.post("/drawings/batch", json=wire({"operations": ops}, BATCH))
    assert r.status_code == 422, r.text
    assert r.json()["errors"] == [
        _refusal("operations.1.drawing.layout_id"),
        _refusal("operations.2.drawing.layout_id"),
    ]
    assert env.listed() == [d1, d2]  # the whole batch rolled back


def test_an_own_live_layout_is_writable_and_listable(env: Env) -> None:
    on, _off = env.create(layout_id=OWN), env.create()
    assert on["layout_id"] == OWN
    r = env.c.get("/drawings", params={"symbol": "BTCUSDT", "layout_id": OWN})
    assert r.status_code == 200 and [i["id"] for i in r.json()["items"]] == [on["id"]]
    assert ("is_live_layout", {"owner": str(USER_A), "layout_id": OWN}) in env.repo.calls


def test_listing_by_a_foreign_or_missing_layout_is_one_identical_404(env: Env) -> None:
    got = [env.c.get("/drawings", params={"symbol": "BTCUSDT", "layout_id": lid})
           for lid in (FOREIGN, GONE)]  # fmt: skip
    assert [r.status_code for r in got] == [404, 404] and got[0].content == got[1].content
    assert "list_page" not in [name for name, _ in env.repo.calls]  # refused before any read


def test_listing_by_layout_without_a_layout_store_is_503(env: Env) -> None:
    env.repo_up = False
    r = env.c.get("/drawings", params={"symbol": "BTCUSDT", "layout_id": OWN})
    assert r.status_code == 503 and r.json()["code"] == "store_unavailable"


def test_put_reports_a_missing_drawing_before_its_layout(env: Env) -> None:
    """The documented PUT order (router docstring): the 404 precedes `layout_not_found`."""
    r = env.c.put(f"/drawings/{uuid.uuid4()}", json=wire(TRENDLINE | {"layout_id": GONE}))
    assert r.status_code == 404 and r.json()["code"] == "not_found"
