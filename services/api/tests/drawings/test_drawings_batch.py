"""E14-T01 POST /drawings/batch: the #357 "Batch is atomic" scenario, op order, the three 409
rules, immutable symbol/tool (422), the 413/422 limits checked before any operation runs, per-op
field paths, and the batch-size / conflict metrics handed to C4."""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import MagicMock, call

import pytest
from _drawings_api_env import BATCH, DRAWING_KEYS, TRENDLINE, USER_A, USER_B, Env, wire
from pydantic import ValidationError

from candleviewer.api.drawings_models import MAX_BATCH_BODY_BYTES, MAX_BATCH_OPS, BatchIn

STALE = "2026-10-14T12:00:00.000000Z"


@pytest.fixture
def env() -> Env:
    return Env()


def _batch(env: Env, *ops: dict[str, Any], raw: bool = False) -> Any:
    body = {"operations": list(ops)}  # `raw`: payloads a generated client cannot build
    return env.c.post("/drawings/batch", json=body if raw else wire(body, BATCH))


def _update(d: dict[str, Any], **over: Any) -> dict[str, Any]:
    op = {"op": "update", "id": d["id"], "if_match": d["updated_at"], "drawing": TRENDLINE}
    return op | over


def test_batch_is_atomic(env: Env) -> None:
    gone = env.create()
    assert env.c.delete(f"/drawings/{gone['id']}").status_code == 204
    creates = [{"op": "create", "drawing": TRENDLINE} for _ in range(3)]
    r = _batch(env, *creates, _update(gone))  # the update targets a deleted drawing
    assert r.status_code == 409 and r.json()["code"] == "conflict"
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [
        ("operations.3", "target_unavailable")
    ]
    assert env.listed() == [] and list(env.repo.rows) == [gone["id"]]  # no create survived


def test_batch_applies_in_order_and_reports_each_kind(env: Env) -> None:
    a, b = env.create(), env.create()
    cid = str(uuid.uuid4())
    r = _batch(env, {"op": "create", "id": cid, "drawing": TRENDLINE}, _update(a),
               {"op": "delete", "id": b["id"], "if_match": b["updated_at"]})  # fmt: skip
    assert r.status_code == 200, r.text
    body = r.json()
    assert [d["id"] for d in body["created"]] == [cid]
    assert [d["id"] for d in body["updated"]] == [a["id"]] and body["deleted"] == [b["id"]]
    assert body["updated"][0]["updated_at"] > a["updated_at"]
    assert all(set(d) == DRAWING_KEYS for d in body["created"] + body["updated"])
    assert {d["id"] for d in env.listed()} == {a["id"], cid}
    minted = _batch(env, {"op": "create", "drawing": TRENDLINE}).json()["created"][0]["id"]
    assert uuid.UUID(minted).version == 7  # no client id: the server mints a UUIDv7


@pytest.mark.parametrize("rule", ["version_conflict", "id_unavailable", "target_unavailable"])
def test_batch_conflict_rules_name_the_failing_op_and_roll_back(env: Env, rule: str) -> None:
    d = env.create()
    op = {
        "version_conflict": {"op": "delete", "id": d["id"], "if_match": STALE},
        "id_unavailable": {"op": "create", "id": d["id"], "drawing": TRENDLINE},
        "target_unavailable": _update(d, id=str(uuid.uuid4())),
    }[rule]
    r = _batch(env, {"op": "create", "drawing": TRENDLINE}, op)
    assert r.status_code == 409
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [("operations.1", rule)]
    assert env.listed() == [d]


def test_batch_create_with_another_users_id_is_id_unavailable(env: Env) -> None:
    mine = env.create()  # foreign update/delete targets: the IDOR matrix (409 target_unavailable)
    env.user = USER_B
    taken = _batch(env, {"op": "create", "id": mine["id"], "drawing": TRENDLINE})
    assert taken.json()["errors"][0]["rule"] == "id_unavailable"  # owner and state not revealed
    env.user = USER_A
    assert env.listed() == [mine]


def test_batch_limits_are_checked_before_any_operation(env: Env) -> None:
    op = {"op": "create", "drawing": TRENDLINE}
    too_many = env.c.post("/drawings/batch", json={"operations": [op] * 201})
    assert too_many.status_code == 413 and too_many.json()["code"] == "payload_too_large"
    assert "201 operations" in too_many.json()["detail"]
    blob = json.dumps({"operations": [op]}).encode() + b" " * (1024 * 1024)
    too_big = env.c.post("/drawings/batch", content=blob)
    assert too_big.status_code == 413
    assert _batch(env, *[op] * 200).status_code == 200  # exactly the cap is fine
    empty = _batch(env, raw=True)
    assert empty.status_code == 422 and empty.json()["errors"][0]["field"] == "operations"
    not_json = env.c.post("/drawings/batch", content=b'{"operations": [')
    assert not_json.status_code == 422 and not_json.json()["errors"][0]["rule"] == "json_invalid"
    assert len(env.repo.rows) == 200
    assert [name for name, _ in env.repo.calls if name == "apply_batch"] == ["apply_batch"]


def test_batch_validation_reports_per_operation_paths(env: Env) -> None:
    dup = str(uuid.uuid4())
    r = _batch(env, {"op": "create", "drawing": TRENDLINE | {"tool": "scribble"}},
               {"op": "delete", "id": dup, "if_match": 1}, {"op": "move", "id": dup},
               raw=True)  # fmt: skip
    assert r.status_code == 422
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [
        ("operations.0.drawing.tool", "literal_error"),
        ("operations.1.if_match", "string_type"),
        ("operations.2", "union_tag_invalid"),
    ]
    ok_but_layout = _batch(env, {"op": "create", "drawing": TRENDLINE | {"layout_id": dup}})
    assert ok_but_layout.json()["errors"] == [
        {"field": "operations.0.drawing.layout_id", "rule": "layout_not_found",
         "message": "No such layout."}
    ]  # fmt: skip
    dupes = _batch(env, {"op": "create", "id": dup, "drawing": TRENDLINE},
                   {"op": "delete", "id": dup, "if_match": STALE})  # fmt: skip
    assert ("operations.1.id", "duplicate_id") in {
        (e["field"], e["rule"]) for e in dupes.json()["errors"]
    }
    assert env.repo.rows == {}


def test_batch_update_cannot_change_symbol_or_tool(env: Env) -> None:
    d = env.create()
    for change in ({"symbol": "ETHUSDT"}, {"tool": "ray"}):
        r = _batch(env, {"op": "create", "drawing": TRENDLINE},
                   _update(d, drawing=TRENDLINE | change))  # fmt: skip
        assert r.status_code == 422 and r.json()["errors"] == [
            {"field": "operations.1.drawing", "rule": "immutable_field",
             "message": "symbol and tool cannot change"}
        ]  # fmt: skip
    assert env.listed() == [d]  # rolled back: the create did not survive either


def test_batch_sizes_and_conflicts_by_rule_are_recorded_for_c4() -> None:
    metrics = MagicMock()  # C4's `DrawingsMetrics` (two `BoundedMetric`s)
    env = Env(metrics=metrics)
    d = env.create()
    _batch(env, {"op": "create", "drawing": TRENDLINE}, {"op": "delete", "id": d["id"],
                                                          "if_match": STALE})  # fmt: skip
    _batch(env, _update(d, drawing=TRENDLINE | {"tool": "ray"}))  # 422: not a conflict
    _batch(env, {"op": "create", "id": d["id"], "drawing": TRENDLINE})
    env.c.put(f"/drawings/{d['id']}", json=wire(TRENDLINE), headers={"If-Match": f'"{STALE}"'})
    env.c.put(f"/drawings/{d['id']}", json=wire(TRENDLINE), headers={"If-Match": "x"})  # malformed
    observed = metrics.batch_ops.child.return_value.observe.call_args_list
    assert observed == [call(2), call(1), call(1)]
    rules = ["version_conflict", "id_unavailable", "version_conflict"]
    assert metrics.conflicts.labels.call_args_list == [call(r) for r in rules]
    assert metrics.conflicts.labels.return_value.inc.call_count == len(rules)


def test_a_megabyte_of_invalid_points_yields_a_bounded_error_count() -> None:
    """Points are `FailFast`: each op reports only its first bad point, at most one error per
    `DrawingPointIn` field (t, p), so <= 2 x MAX_BATCH_OPS = 400 (was 2 x 366 x 200 = 146,400)."""
    points = [{"t": 0, "p": 0}] * 366
    op = {"op": "create", "drawing": {"symbol": "BTCUSDT", "tool": "polyline",
                                      "geometry": {"points": points}}}  # fmt: skip
    raw = json.dumps({"operations": [op] * MAX_BATCH_OPS}, separators=(",", ":"))
    assert 1_000_000 < len(raw) <= MAX_BATCH_BODY_BYTES  # ~1 MiB, passes the body cap
    with pytest.raises(ValidationError) as ei:
        BatchIn.model_validate_json(raw)
    assert ei.value.error_count() <= 2 * MAX_BATCH_OPS
    r = Env().c.post("/drawings/batch", content=raw)  # the router path: a 422, not a 413
    assert r.status_code == 422 and len(r.json()["errors"]) == 20
