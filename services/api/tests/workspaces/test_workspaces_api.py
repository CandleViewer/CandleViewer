"""E15-T01 /workspaces behaviour: round trip, ETag/If-Match, no-op rule, 409s, 422s, caps."""

from __future__ import annotations

from typing import Any

import pytest
from _workspaces_api_env import (
    WORKSPACE_KEYS,
    Env,
    FakeWorkspaceRepo,
    contract_valid,
    wire,
)

from candleviewer.api.workspaces import make_workspaces_router
from candleviewer.api.workspaces_models import DEFAULT_ICON
from candleviewer.storage.repositories.workspaces import WorkspaceFields


@pytest.fixture
def env() -> Env:
    return Env()


def test_workspace_round_trips_with_contract_shape(env: Env) -> None:
    made = env.create("Scalping", is_default=True, sort_order=3)
    contract_valid(made)
    assert set(made) == WORKSPACE_KEYS and made["is_default"] is True and made["sort_order"] == 3
    assert made["icon_token"] == DEFAULT_ICON and made["layout_count"] == 0
    got = env.c.get(f"/workspaces/{made['id']}")
    assert got.status_code == 200 and got.json() == made | {"layouts": []}
    contract_valid(got.json(), "WorkspaceDetail")
    assert "etag" not in got.headers  # the detail body mixes tokens (D12)


def test_post_and_put_carry_a_strong_etag_equal_to_updated_at(env: Env) -> None:
    r = env.c.post("/workspaces", json=wire({"name": "A"}))
    assert r.headers["etag"] == f'"{r.json()["updated_at"]}"' and r.status_code == 201
    assert r.json()["updated_at"].endswith("Z") and len(r.json()["updated_at"].split(".")[1]) == 7
    u = env.c.put(f"/workspaces/{r.json()['id']}", json=wire({"name": "B"}))
    assert u.status_code == 200 and u.headers["etag"] == f'"{u.json()["updated_at"]}"'
    assert u.json()["updated_at"] > r.json()["updated_at"] and u.json()["name"] == "B"


@pytest.mark.parametrize("form", ["quoted", "weak", "bare"])
def test_put_accepts_quoted_weak_and_bare_tokens(env: Env, form: str) -> None:
    w = env.create()
    tok = w["updated_at"]
    header = {"quoted": f'"{tok}"', "weak": f'W/"{tok}"', "bare": tok}[form]
    r = env.c.put(f"/workspaces/{w['id']}", json=wire({"name": "B"}), headers={"If-Match": header})
    assert r.status_code == 200 and r.json()["name"] == "B"


def test_put_with_stale_if_match_is_412_and_keeps_the_workspace(env: Env) -> None:
    w = env.create()
    env.c.put(f"/workspaces/{w['id']}", json=wire({"name": "B"}))
    r = env.c.put(
        f"/workspaces/{w['id']}",
        json=wire({"name": "C"}),
        headers={"If-Match": f'"{w["updated_at"]}"'},
    )
    assert r.status_code == 412 and r.json()["code"] == "version_conflict"
    assert r.headers["content-type"] == "application/problem+json"
    assert env.repo.rows[w["id"]].name == "B"


@pytest.mark.parametrize("header", ["*", '"a", "b"', "garbage", '"2026-10-14T12:00:00Z"'])
def test_unparseable_if_match_is_412_unless_the_body_is_a_no_op(env: Env, header: str) -> None:
    w = env.create()
    url, h = f"/workspaces/{w['id']}", {"If-Match": header}
    r = env.c.put(url, json=wire({"name": "B"}), headers=h)
    assert r.status_code == 412 and env.repo.rows[w["id"]].name == "Scalping"
    same = env.c.put(url, json=wire({"name": "Scalping"}), headers=h)  # no-op: already applied
    assert (
        same.status_code == 200
        and same.json() == w
        and same.headers["etag"] == f'"{w["updated_at"]}"'
    )


def test_no_op_put_with_a_stale_token_changes_nothing(env: Env) -> None:
    w = env.create()
    env.c.put(f"/workspaces/{w['id']}", json=wire({"name": "B"}))
    before = env.repo.tick
    r = env.c.put(
        f"/workspaces/{w['id']}",
        json=wire({"name": "B"}),
        headers={"If-Match": f'"{w["updated_at"]}"'},
    )
    assert r.status_code == 200 and env.repo.tick == before


def test_default_switch_bumps_the_previous_default_token(env: Env) -> None:
    a = env.create("A", is_default=True)
    b = env.create("B", is_default=True)
    first = env.repo.rows[a["id"]]
    assert first.is_default is False and first.token > a["updated_at"] and b["is_default"]


def test_name_conflicts_and_the_cap_are_409_with_the_rule_named(env: Env) -> None:
    env.create("Scalping")
    dup = env.c.post("/workspaces", json=wire({"name": "scalping"}))
    assert dup.status_code == 409 and dup.json()["code"] == "conflict"
    assert dup.json()["errors"][0] == {
        "field": "name",
        "rule": "name_taken",
        "message": "That name is already in use.",
    }
    other = env.create("Other")
    clash = env.c.put(f"/workspaces/{other['id']}", json=wire({"name": "SCALPING"}))
    assert clash.status_code == 409 and clash.json()["errors"][0]["rule"] == "name_taken"
    for i in range(30):
        env.create(f"W{i}")
    full = env.c.post("/workspaces", json=wire({"name": "one more"}))
    assert full.status_code == 409 and full.json()["errors"] == [
        {"rule": "limit_reached", "message": "The limit has been reached."}]  # fmt: skip


def test_delete_last_workspace_is_409_last_workspace_and_still_listed(env: Env) -> None:
    w = env.create()
    r = env.c.delete(f"/workspaces/{w['id']}")
    assert r.status_code == 409 and r.json()["errors"] == [
        {"field": "workspaceId", "rule": "last_workspace",
         "message": "You need at least one workspace."}]  # fmt: skip
    assert env.c.get(f"/workspaces/{w['id']}").status_code == 200  # still there
    env.create("Second")
    assert env.c.delete(f"/workspaces/{w['id']}").status_code == 204
    assert env.c.get(f"/workspaces/{w['id']}").status_code == 404


def test_unknown_conflict_rule_still_maps_to_409() -> None:
    from candleviewer.api.workspaces import _conflict
    from candleviewer.storage.repositories.workspaces import WorkspaceConflictError

    assert _conflict(WorkspaceConflictError("mystery", None)).extra["errors"][0] == {
        "rule": "mystery", "message": "State conflict."}  # fmt: skip


@pytest.mark.parametrize(
    ("body", "field", "rule"),
    [
        ({"name": ""}, "name", "string_too_short"),
        ({"name": "x" * 41}, "name", "string_too_long"),
        ({"name": "A", "is_default": None}, "is_default", "null_not_allowed"),
        ({"name": "A", "icon_token": None}, "icon_token", "null_not_allowed"),
        ({"name": "A", "sort_order": None}, "sort_order", "null_not_allowed"),
        ({"name": "A", "sort_order": 32768}, "sort_order", "less_than_equal"),
        ({"name": "A", "icon_token": "http://x"}, "icon_token", "literal_error"),
        ({"name": "A", "extra": 1}, "extra", "extra_forbidden"),
        ({}, "name", "missing"),
    ],
)
def test_invalid_bodies_are_422_with_field_and_rule(
    env: Env, body: dict[str, Any], field: str, rule: str
) -> None:
    for call in (lambda: env.c.post("/workspaces", json=body),
                 lambda: env.c.put(f"/workspaces/{env.create('T')['id']}", json=body)):  # fmt: skip
        r = call()
        assert r.status_code == 422 and r.json()["code"] == "validation_failed", r.text
        assert r.json()["errors"][0]["field"] == field and r.json()["errors"][0]["rule"] == rule
        assert not r.json()["errors"][0]["field"].startswith("body")
        env.repo.deleted.update(env.repo.rows)  # free the name for the PUT round


def test_request_level_refusals(env: Env) -> None:
    c = env.c
    assert c.post("/workspaces", content=b"\xff\xfe").json()["errors"][0]["rule"] == "json_invalid"
    deep = "[" * 40 + "]" * 40
    assert c.post("/workspaces", content=deep).json()["errors"][0]["rule"] == "json_too_deep"
    assert c.post("/workspaces", content=b"{").status_code == 422
    big = c.post("/workspaces", json={"name": "A", "x": "y" * 5000})
    assert big.status_code == 413 and big.json()["code"] == "payload_too_large"
    assert big.headers["content-type"] == "application/problem+json"
    assert env.repo.calls == []


def test_body_cap_holds_without_a_content_length(env: Env) -> None:
    def chunks() -> Any:
        yield b'{"name":"A","pad":"'
        yield b"x" * 5000
        yield b'"}'

    r = env.c.post("/workspaces", content=chunks())
    assert r.status_code == 413 and env.repo.calls == []


@pytest.mark.parametrize("method", ["GET", "DELETE"])
def test_malformed_path_uuid_is_422_and_touches_no_store(env: Env, method: str) -> None:
    r = env.c.request(method, "/workspaces/not-a-uuid")
    assert r.status_code == 422 and r.json()["errors"][0] == {
        "field": "workspaceId",
        "rule": "uuid_parsing",
        "message": "workspaceId must be a UUID.",
    }
    put = env.c.put("/workspaces/not-a-uuid", json=wire({"name": "A"}))
    assert put.status_code == 422 and env.repo.calls == []


def test_idempotency_key_format_is_validated_and_a_valid_key_accepted(env: Env) -> None:
    bad = env.c.post("/workspaces", json=wire({"name": "A"}), headers={"Idempotency-Key": "nope"})
    assert bad.status_code == 422 and bad.json()["errors"][0]["field"] == "Idempotency-Key"
    key = {"Idempotency-Key": "0b6f1a3e-5c1e-4c1e-9a3e-1b2c3d4e5f60"}
    ok = env.c.post("/workspaces", json=wire({"name": "A"}), headers=key)
    assert ok.status_code == 201 and "idempotency-replayed" not in ok.headers
    w = env.create("B")
    gone = env.c.delete(f"/workspaces/{w['id']}", headers={"Idempotency-Key": "nope"})
    assert gone.status_code == 422 and w["id"] in env.repo.rows and w["id"] not in env.repo.deleted


def test_logs_never_carry_workspace_names(env: Env) -> None:
    from structlog.testing import capture_logs

    with capture_logs() as logs:
        w = env.create("SECRET-NAME-123")
        env.c.put(f"/workspaces/{w['id']}", json=wire({"name": "SECRET-NAME-456"}))
        env.create("other")
        env.c.delete(f"/workspaces/{w['id']}")
    assert {e["event"] for e in logs} >= {
        "workspace_created",
        "workspace_updated",
        "workspace_deleted",
    }
    assert "SECRET-NAME" not in repr(logs)


def test_router_requires_an_audit_emitter() -> None:
    with pytest.raises(TypeError, match="audit emitter"):
        make_workspaces_router(lambda: FakeWorkspaceRepo(), None, None)  # type: ignore[arg-type]  # the guard under test
    assert WorkspaceFields("a", False, "workspace.default", 0)  # keeps the import honest


def test_workspace_detail_round_trips_four_panes_in_slot_order(env: Env) -> None:
    from datetime import UTC, datetime

    from candleviewer.storage.repositories.workspaces import LayoutRow, PaneFields

    w = env.create()
    kinds = [("chart", "BTCUSDT", "time:1"), ("dom", "ETHUSDT", None),
             ("tape", None, None), ("alerts", None, None)]  # fmt: skip
    panes = tuple(
        PaneFields(i, k, s, iv, None, (), {"sync_group": "A", "settings": {"n": 1.0}}, "auto")
        for i, (k, s, iv) in enumerate(kinds)
    )
    t = datetime(2026, 10, 14, 12, 0, 0, 5, tzinfo=UTC)

    def row(rid: str) -> LayoutRow:
        return LayoutRow(rid, w["id"], "L", "2x2", None, True, False, False, 3, False, panes, t, t)

    env.repo.layouts_of = lambda _o, _w: (
        row("b" * 8 + "-0000-4000-8000-000000000000"),
        row("a" * 8 + "-0000-4000-8000-000000000000"),
    )  # type: ignore[method-assign]  # fixture
    got = env.c.get(f"/workspaces/{w['id']}").json()
    contract_valid(got, "WorkspaceDetail")
    assert [x["id"][0] for x in got["layouts"]] == ["a", "b"]  # by id
    shown = [
        (p["slot_index"], p["pane_kind"], p["symbol"], p["interval_code"])
        for p in got["layouts"][0]["panes"]
    ]
    assert shown == [(i, *k) for i, k in enumerate(kinds)]
    assert got["layouts"][0]["panes"][0]["pane_config"]["settings"]["n"] == 1.0
    assert got["layouts"][0]["updated_at"] == "2026-10-14T12:00:00.000005Z"
    assert (
        got["layouts"][0]["grid_spec"] is None
        and "etag" not in env.c.get(f"/workspaces/{w['id']}").headers
    )
