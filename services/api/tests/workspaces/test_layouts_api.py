"""E15-T01 /layouts + /layout-presets + listings: round trip, 412/no-op, 409, 422, paging."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from _workspaces_api_env import LAYOUT, MISSING, USER_A, USER_B, Env, contract_valid, wire

from candleviewer.api.workspaces import CURSOR_TTL_S, encode_cursor, make_workspaces_router
from candleviewer.api.workspaces_presets import LAYOUT_PRESETS

NOW = 1_800_000_000


@pytest.fixture
def env() -> Env:
    return Env()


@pytest.fixture
def ws(env: Env) -> str:
    return str(env.create("Home")["id"])


def _layout(**over: Any) -> dict[str, Any]:
    return wire(LAYOUT | over, "LayoutInput")


def test_layout_round_trips_four_panes_in_slot_order(env: Env, ws: str) -> None:
    made = env.make_layout(ws)
    contract_valid(made, "Layout")
    assert [(p["slot_index"], p["pane_kind"]) for p in made["panes"]] == [
        (0, "chart"), (1, "dom"), (2, "alerts"), (3, "tape")]  # fmt: skip
    cfg = {"sync_group": "A", "settings": {"depth": 20, "footprint": True}}
    assert made["panes"][0]["pane_config"] == cfg
    assert made["grid_spec"] is None and made["workspace_id"] == ws
    got = env.c.get(f"/workspaces/{ws}/layouts/{made['id']}")
    assert got.json() == made and got.headers["etag"] == f'"{made["updated_at"]}"'
    detail = env.c.get(f"/workspaces/{ws}").json()
    contract_valid(detail, "WorkspaceDetail")
    assert detail["layouts"] == [made]


def test_put_layout_is_412_when_stale_and_keeps_the_stored_panes(env: Env, ws: str) -> None:
    made = env.make_layout(ws)
    url = f"/workspaces/{ws}/layouts/{made['id']}"
    ok = env.c.put(
        url, json=_layout(name="Renamed"), headers={"If-Match": f'"{made["updated_at"]}"'}
    )
    assert ok.status_code == 200 and ok.json()["updated_at"] > made["updated_at"]
    stale = env.c.put(url, json=_layout(panes=[]), headers={"If-Match": f'"{made["updated_at"]}"'})
    assert stale.status_code == 412 and stale.json()["code"] == "version_conflict"
    assert len(env.c.get(url).json()["panes"]) == 4  # nothing written
    same = env.c.put(url, json=_layout(name="Renamed"), headers={"If-Match": "*"})  # no-op
    assert same.status_code == 200 and same.json() == ok.json()
    assert env.c.put(url, json=_layout(panes=[]), headers={"If-Match": "*"}).status_code == 412
    assert env.c.put(url, json=_layout(panes=[])).json()["panes"] == []  # absent: last write wins


def test_invalid_pane_set_is_422_with_pane_fields_and_stores_nothing(env: Env, ws: str) -> None:
    url = f"/workspaces/{ws}/layouts"
    dup = [{"slot_index": 0, "pane_kind": "chart"}, {"slot_index": 1, "pane_kind": "dom"},
           {"slot_index": 0, "pane_kind": "tape"}]  # fmt: skip
    r = env.c.post(url, json={"name": "X", "panes": dup})
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [
        ("panes.2.slot_index", "duplicate_slot")
    ]  # exactly the later pane
    bad = [{"slot_index": 16, "pane_kind": "chart"}, {"slot_index": 2, "pane_kind": "bogus"}]
    r = env.c.post(url, json={"name": "X", "panes": bad})
    got = {(e["field"], e["rule"]) for e in r.json()["errors"]}
    assert r.status_code == 422 and {f for f, _ in got} == {
        "panes.0.slot_index", "panes.1.pane_kind"}  # fmt: skip
    assert env.repo.layouts == {}


@pytest.mark.parametrize("field", ["grid_preset", "crosshair_sync", "hotkey_slot_x", "panes"])
def test_explicit_null_on_a_non_nullable_layout_field_is_422(env: Env, ws: str, field: str) -> None:
    r = env.c.post(f"/workspaces/{ws}/layouts", json={"name": "X", "panes": [], field: None})
    assert r.status_code == 422, r.text


def test_layout_conflicts_name_hotkey_and_cap(env: Env, ws: str) -> None:
    env.make_layout(ws)
    c = env.c.post(f"/workspaces/{ws}/layouts", json=_layout(name="MAIN", hotkey_slot=4))
    assert c.status_code == 409 and c.json()["errors"][0]["rule"] == "name_taken"
    h = env.c.post(f"/workspaces/{ws}/layouts", json=_layout(name="Other"))
    assert h.status_code == 409 and h.json()["errors"][0] == {
        "field": "hotkey_slot", "rule": "hotkey_slot_taken",
        "message": "That hotkey is held by another layout."}  # fmt: skip
    other = env.make_layout(ws, name="Second", hotkey_slot=None)
    put = env.c.put(f"/workspaces/{ws}/layouts/{other['id']}", json=_layout(name="main"))
    assert put.status_code == 409 and put.json()["errors"][0]["rule"] == "name_taken"
    for i in range(30):
        env.make_layout(ws, name=f"L{i}", hotkey_slot=None)
    full = env.c.post(f"/workspaces/{ws}/layouts", json=_layout(name="one more", hotkey_slot=None))
    assert full.status_code == 409 and full.json()["errors"][0]["rule"] == "limit_reached"


def test_layout_body_cap_is_128_kib_and_workspace_cap_does_not_apply(env: Env, ws: str) -> None:
    mid = {"name": "X", "panes": [], "pad": "y" * 8000}  # over 4 KiB: refused by the model, not 413
    assert env.c.post(f"/workspaces/{ws}/layouts", json=mid).status_code == 422
    big = env.c.post(f"/workspaces/{ws}/layouts", json={"name": "X", "pad": "y" * 140_000})
    assert big.status_code == 413 and big.json()["code"] == "payload_too_large"
    assert env.repo.layouts == {}


def test_delete_layout_and_idempotency_key_format(env: Env, ws: str) -> None:
    made = env.make_layout(ws)
    url = f"/workspaces/{ws}/layouts/{made['id']}"
    assert env.c.delete(url, headers={"Idempotency-Key": "nope"}).status_code == 422
    key = {"Idempotency-Key": "0b6f1a3e-5c1e-4c1e-9a3e-1b2c3d4e5f60"}
    assert env.c.delete(url, headers=key).status_code == 204
    assert env.c.get(url).status_code == 404 and env.c.delete(url).status_code == 404
    assert env.c.get(f"/workspaces/{ws}").json()["layouts"] == []
    bad = env.c.post(f"/workspaces/{ws}/layouts", json=_layout(), headers={"Idempotency-Key": "x"})
    assert bad.status_code == 422


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE"])
def test_malformed_layout_path_uuids_are_422_without_touching_the_store(
    env: Env, ws: str, method: str
) -> None:
    calls = len(env.repo.calls)
    for path in (f"/workspaces/{ws}/layouts/nope", f"/workspaces/nope/layouts/{MISSING}"):
        r = env.c.request(method, path, json=_layout() if method == "PUT" else None)
        assert r.status_code == 422 and r.json()["errors"][0]["rule"] == "uuid_parsing"
    for method2, path in (
        ("GET", "/workspaces/nope/layouts"),
        ("POST", "/workspaces/nope/layouts"),
    ):
        r = env.c.request(method2, path, json=_layout())
        assert r.status_code == 422
    assert len(env.repo.calls) == calls


def test_layouts_of_a_missing_workspace_are_404_everywhere(env: Env) -> None:
    gone = f"/workspaces/{MISSING}/layouts"
    assert env.c.get(gone).status_code == 404
    assert env.c.post(gone, json=_layout()).status_code == 404
    assert env.audit.denied() == []


def test_layouts_are_listed_by_id_with_an_opaque_cursor(env: Env, ws: str) -> None:
    ids = [env.make_layout(ws, name=f"L{i}", hotkey_slot=None)["id"] for i in range(5)]
    seen, cursor = [], None
    while True:
        params: dict[str, Any] = {"limit": 2} | ({} if cursor is None else {"cursor": cursor})
        page = env.c.get(f"/workspaces/{ws}/layouts", params=params).json()
        contract_valid(page["items"][0], "Layout")
        seen += [i["id"] for i in page["items"]]
        cursor = page["meta"]["next_cursor"]
        if cursor is None:
            break
    assert seen == sorted(ids)
    other = env.c.get(f"/workspaces/{ws}").json()["id"]
    assert other == ws


def test_workspaces_are_listed_by_sort_order_then_id(env: Env) -> None:
    ids = [env.create(f"W{i}", sort_order=i % 2)["id"] for i in range(5)]
    seen, cursor = [], None
    while True:
        params: dict[str, Any] = {"limit": 2} | ({} if cursor is None else {"cursor": cursor})
        page = env.c.get("/workspaces", params=params).json()
        seen += [i["id"] for i in page["items"]]
        cursor = page["meta"]["next_cursor"]
        if cursor is None:
            break
    assert seen == [
        r.id for r in sorted(env.repo.rows.values(), key=lambda r: (r.sort_order, r.id))
    ]
    assert sorted(seen) == sorted(ids)


def test_presets_are_the_static_catalogue_and_page(env: Env) -> None:
    page = env.c.get("/layout-presets").json()
    assert [i["name"] for i in page["items"]] == [p.name for p in LAYOUT_PRESETS]
    assert page["meta"] == {"next_cursor": None, "has_more": False, "count": 6}
    for item in page["items"]:
        contract_valid(item, "LayoutPreset")
        assert env.c.post(f"/workspaces/{env.create(item['name'])['id']}/layouts",
                          json=wire(item["layout"], "LayoutInput")).status_code == 201  # fmt: skip
    first = env.c.get("/layout-presets", params={"limit": 4}).json()
    rest = env.c.get("/layout-presets", params={"cursor": first["meta"]["next_cursor"]}).json()
    assert first["meta"]["has_more"]
    assert [i["name"] for i in rest["items"]] == [p.name for p in LAYOUT_PRESETS[4:]]
    assert env.repo.calls and all(c[0] != "list_layout_presets" for c in env.repo.calls)


def _raw(d: Any) -> str:
    return base64.urlsafe_b64encode(json.dumps(d).encode()).decode()


@pytest.mark.parametrize(
    "path", ["/workspaces", "/layout-presets", f"/workspaces/{MISSING}/layouts"]
)
@pytest.mark.parametrize(
    "name",
    ["garbage", "expired", "future", "other_scope", "bad_after", "extra_key", "not_object", "long",
     "bad_version", "float_iat", "scalar_after", "bad_order"],
)  # fmt: skip
def test_cursor_is_refused_when_expired_mismatched_or_malformed(path: str, name: str) -> None:
    env = Env()
    env.repo.rows[MISSING] = env.repo.rows.get(MISSING) or _ws(env)
    kind, scope = {"/workspaces": ("ws", str(USER_A)), "/layout-presets": ("pre", "-")}.get(
        path, ("lay", f"{USER_A}:{MISSING}")
    )
    after: Any = {"ws": [0, MISSING], "pre": 0}.get(kind, MISSING)
    good = {"v": 1, "k": kind, "s": scope, "a": after, "iat": NOW}
    bad_after: Any = {"ws": [0, "nope"], "pre": 99}.get(kind, "nope")
    cursors = {
        "garbage": "!!!", "expired": encode_cursor(kind, scope, after, NOW - CURSOR_TTL_S - 1),
        "future": encode_cursor(kind, scope, after, NOW + 5),
        "other_scope": encode_cursor(kind, str(USER_B), after, NOW),
        "bad_after": encode_cursor(kind, scope, bad_after, NOW), "extra_key": _raw(good | {"z": 1}),
        "not_object": _raw([1]), "long": "a" * 600, "bad_version": _raw(good | {"v": True}),
        "float_iat": _raw(good | {"iat": 1.5}),
        "scalar_after": encode_cursor(kind, scope, 7.5, NOW),
        "bad_order": encode_cursor(kind, scope, {"ws": [-1, MISSING], "pre": -1}.get(kind, 1), NOW),
    }  # fmt: skip
    env.c = _clocked(env)
    r = env.c.get(path, params={"cursor": cursors[name]})
    assert r.status_code == 400 and r.json()["code"] == "invalid_cursor", r.text


def _ws(env: Env) -> Any:
    from datetime import UTC, datetime

    from candleviewer.storage.repositories.workspaces import WorkspaceRow

    t = datetime(2026, 1, 1, tzinfo=UTC)
    return WorkspaceRow(MISSING, str(USER_A), "W", False, "workspace.default", 0, 0, t, t)


def _clocked(env: Env) -> Any:
    from _workspaces_api_env import PERMS
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from candleviewer.audit.access import AuditPrincipal

    class R:
        async def resolve(self, _r: Any) -> AuditPrincipal:
            assert env.user is not None
            return AuditPrincipal(env.user, "u", frozenset(PERMS[env.user]), session_id=None)

    app = FastAPI()
    app.include_router(make_workspaces_router(lambda: env.repo, R(), env.audit, clock=lambda: NOW))
    return TestClient(app)


def test_cursor_is_valid_for_exactly_one_hour(env: Env) -> None:
    for i in range(3):
        env.create(f"W{i}")
    c = _clocked(env)
    cur = encode_cursor("ws", str(USER_A), [0, "00000000-0000-4000-8000-000000000000"], NOW - 3600)
    ok = c.get("/workspaces", params={"cursor": cur})
    assert ok.status_code == 200 and ok.json()["meta"]["count"] == 3


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 501}, {"limit": "x"}])
def test_list_query_errors_are_422_field_errors(env: Env, params: dict[str, Any]) -> None:
    for path in ("/workspaces", "/layout-presets", f"/workspaces/{MISSING}/layouts"):
        r = env.c.get(path, params=params)
        assert r.status_code == 422 and r.json()["errors"][0]["field"] == "limit"


def test_layout_logs_carry_counts_and_ids_never_content(env: Env, ws: str) -> None:
    from structlog.testing import capture_logs

    with capture_logs() as logs:
        made = env.make_layout(ws, name="SECRET-LAYOUT")
        url = f"/workspaces/{ws}/layouts/{made['id']}"
        env.c.put(url, json=_layout(name="SECRET-2", symbol_sync=True))
        env.c.delete(url)
    events = {e["event"]: e for e in logs}
    assert {"layout_created", "layout_updated", "layout_deleted"} <= set(events)
    assert events["layout_created"]["pane_count"] == 4
    assert "SECRET" not in repr(logs) and "BTCUSDT" not in repr(logs)
