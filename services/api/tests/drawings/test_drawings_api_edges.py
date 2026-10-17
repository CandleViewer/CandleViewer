"""E14-T01 /drawings edge cases: ETag/If-Match forms, request-level refusals, keyset paging and
every cursor refusal, query 422s, 401/503 on every route, races after the ownership check, the
streamed body cap, logs without drawing content, and the real `create_app()` behind CSRF."""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Iterator
from typing import Any

import _drawings_api_env as fakes
import pytest
from _drawings_api_env import BATCH, DRAWING_KEYS, SID, TRENDLINE, USER_A, Env, wire
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError
from structlog.testing import capture_logs

import candleviewer.app as appmod
from candleviewer.api.drawings import CURSOR_TTL_S, encode_cursor, make_drawings_router
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.drawings import (
    DrawingIdUnavailableError,
    DrawingNotFoundError,
    DrawingVersionConflictError,
)
from tests.csrf_helpers import arm_csrf
from tests.unit.auth.auth_fakes import FullUsers

PTS = TRENDLINE["geometry"]["points"]
MISSING = "00000000-0000-4000-8000-0000000000ff"  # fixed: parametrize ids must be stable
ROUTES = [
    ("GET", "/drawings?symbol=BTCUSDT", None),
    ("POST", "/drawings", TRENDLINE),
    ("POST", "/drawings/batch", {"operations": [{"op": "create", "drawing": TRENDLINE}]}),
    ("PUT", f"/drawings/{MISSING}", TRENDLINE),
    ("DELETE", f"/drawings/{MISSING}", None),
]


@pytest.fixture
def env() -> Env:
    return Env()


def test_put_accepts_quoted_weak_and_bare_tokens_and_returns_a_fresh_etag(env: Env) -> None:
    d = env.create()
    moved = wire(TRENDLINE | {"geometry": {"points": [PTS[0], {"t": "2026-09-15T00:00:00Z",
                                                                "p": "-1.5"}]}})  # fmt: skip
    for fmt in ('"{}"', 'W/"{}"', "{}"):
        r = env.c.put(f"/drawings/{d['id']}", json=moved,
                      headers={"If-Match": fmt.format(d["updated_at"])})  # fmt: skip
        assert r.status_code == 200 and set(r.json()) == DRAWING_KEYS, r.text
        assert r.headers["etag"] == f'"{r.json()["updated_at"]}"' != f'"{d["updated_at"]}"'
        assert r.json()["geometry"] == moved["geometry"]
        assert r.json()["created_at"] == d["created_at"]
        d = r.json()
    for other_spelling in (d["updated_at"].replace("Z", "+00:00"), "2026-10-14T12:00:00"):
        r = env.c.put(f"/drawings/{d['id']}", json=moved, headers={"If-Match": other_spelling})
        assert r.status_code == 412  # only the token exactly as served can match


def test_request_level_refusals(env: Env) -> None:
    d = env.create()
    url, lid, body = f"/drawings/{d['id']}", str(uuid.uuid4()), wire(TRENDLINE)
    stale = {"If-Match": '"2026-10-14T12:00:00.000000Z"'}
    hline = wire(TRENDLINE | {"tool": "horizontal_line", "geometry": {"points": PTS[:1]}})
    vf, vc = "validation_failed", "version_conflict"
    cases: list[tuple[str, str, dict[str, Any], int, str]] = [
        ("POST", "/drawings", {"content": b"{" + b" " * 70_000 + b"}"}, 413, "payload_too_large"),
        ("POST", "/drawings", {"content": b"\xff"}, 422, vf),
        ("POST", "/drawings", {"content": b"[" * 17 + b"]" * 17}, 422, vf),
        ("POST", "/drawings", {"json": wire(TRENDLINE | {"layout_id": lid})}, 422, vf),
        ("PUT", "/drawings/not-a-uuid", {"json": body}, 422, vf),
        ("DELETE", "/drawings/not-a-uuid", {}, 422, vf),
        ("PUT", url, {"json": body, "headers": stale}, 412, vc),
        ("PUT", url, {"json": hline}, 422, vf),
        ("GET", f"/drawings?symbol=BTCUSDT&layout_id={lid}", {}, 404, "not_found"),
    ]
    for method, path, kw, status, code in cases:
        r = env.c.request(method, path, **kw)
        assert (r.status_code, r.json()["code"]) == (status, code), (method, path, r.text)
    assert env.listed() == [d]  # nothing was written by any refusal


@pytest.mark.parametrize("n", [17, 18, 19, 20])  # 21..24 characters: matches `Symbol`, > 20
def test_list_symbol_longer_than_the_storage_domain_is_422_never_500(env: Env, n: int) -> None:
    r = env.c.get("/drawings", params={"symbol": "A" * n + "USDT"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "symbol"
    assert env.repo.calls == []  # refused before any SQL could hit the `symbol_code` domain


def test_query_uses_the_intended_index(env: Env) -> None:
    """#357 Gherkin 6 (EXPLAIN + p99 on Postgres: #2384): the owner + symbol query, limit + 1."""
    env.c.get("/drawings", params={"symbol": "BTCUSDT", "limit": "7"})
    assert env.repo.calls[-1] == (
        "list_page",
        {"owner": str(USER_A), "symbol": "BTCUSDT", "layout_id": None, "after_id": None,
         "limit": 8},
    )  # fmt: skip


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_every_route_401_without_a_session(method: str, path: str, body: Any) -> None:
    for env in (Env(), Env(wired=False)):  # no session / no resolver wired: fail closed
        env.user = None
        r = env.c.request(method, path, json=body)
        assert r.status_code == 401 and r.json()["code"] == "unauthenticated"
        assert r.headers["content-type"] == "application/problem+json"
        assert env.repo.calls == [] and env.audit.calls == []


def test_list_pages_by_id_with_an_opaque_cursor(env: Env) -> None:
    ids = sorted(env.create()["id"] for _ in range(5))
    seen: list[str] = []
    params: dict[str, str] = {"symbol": "BTCUSDT", "limit": "2"}
    while True:
        page = env.c.get("/drawings", params=params).json()
        seen += [d["id"] for d in page["items"]]
        assert page["meta"]["count"] == len(page["items"])
        if not page["meta"]["has_more"]:
            assert page["meta"]["next_cursor"] is None
            break
        params["cursor"] = page["meta"]["next_cursor"]
    assert seen == ids


def _cursors(now: int) -> Iterator[tuple[str, str]]:
    a = str(uuid.uuid4())
    yield "expired", encode_cursor("BTCUSDT", None, a, now - CURSOR_TTL_S - 1)
    yield "from_the_future", encode_cursor("BTCUSDT", None, a, now + 1)
    yield "other_symbol", encode_cursor("ETHUSDT", None, a, now)
    yield "other_layout", encode_cursor("BTCUSDT", a, a, now)
    yield "not_a_uuid", encode_cursor("BTCUSDT", None, "x", now)
    yield "not_base64_json", "!!!!"
    yield "too_long", "A" * 513
    for name, data in (
        ("version_2", {"v": 2, "s": "BTCUSDT", "l": None, "a": a, "iat": now}),
        ("version_true", {"v": True, "s": "BTCUSDT", "l": None, "a": a, "iat": now}),
        ("iat_text", {"v": 1, "s": "BTCUSDT", "l": None, "a": a, "iat": str(now)}),
        ("extra_key", {"v": 1, "s": "BTCUSDT", "l": None, "a": a, "iat": now, "x": 1}),
        ("a_list", [1]),
    ):
        yield name, base64.urlsafe_b64encode(json.dumps(data).encode()).decode()


@pytest.mark.parametrize("name", [n for n, _ in _cursors(0)])
def test_cursor_is_refused_when_expired_mismatched_or_malformed(env: Env, name: str) -> None:
    cursor = dict(_cursors(int(env.now)))[name]
    r = env.c.get("/drawings", params={"symbol": "BTCUSDT", "cursor": cursor})
    assert r.status_code == 400 and r.json()["code"] == "invalid_cursor"


def test_cursor_is_valid_for_exactly_one_hour(env: Env) -> None:
    oldest = encode_cursor("BTCUSDT", None, str(uuid.uuid4()), int(env.now) - CURSOR_TTL_S)
    r = env.c.get("/drawings", params={"symbol": "BTCUSDT", "cursor": oldest})
    assert r.status_code == 200


S = {"symbol": "BTCUSDT"}


@pytest.mark.parametrize(
    ("params", "field"),
    [({}, "symbol"), ({"symbol": "btc"}, "symbol"), (S | {"limit": "0"}, "limit"),
     (S | {"limit": "501"}, "limit"), (S | {"limit": "x"}, "limit"),
     (S | {"layout_id": "x"}, "layout_id")],
)  # fmt: skip
def test_list_query_errors_are_422_field_errors(
    env: Env, params: dict[str, str], field: str
) -> None:
    r = env.c.get("/drawings", params=params)
    assert r.status_code == 422 and [e["field"] for e in r.json()["errors"]] == [field]


@pytest.mark.parametrize("fault", [None, OSError("refused"), StorageTierUnavailable("down")])
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [ROUTES[0], ROUTES[1], ROUTES[2], ROUTES[4]],
)  # fmt: skip
def test_store_unavailable_is_503(method: str, path: str, body: Any, fault: Any) -> None:
    env = Env()
    env.repo_up, env.repo.fail = fault is not None, fault
    with capture_logs() as logs:
        r = env.c.request(method, path, json=body)
    assert r.status_code == 503 and r.json()["code"] == "store_unavailable"
    assert "refused" not in r.text and "down" not in r.text
    expected = [] if fault is None else ["drawings_store_unavailable"]  # never the audit event
    assert [e["event"] for e in logs if e["event"].endswith("_unavailable")] == expected


@pytest.mark.parametrize("state", ["57014", "08006"])  # statement timeout, lost connection
def test_driver_outage_is_503_without_echoing_detail(state: str) -> None:
    class _Driver(Exception):
        sqlstate = state

    env = Env()
    env.repo_up, env.repo.fail = True, DBAPIError("SELECT secret_token", {}, _Driver("leak-me"))
    r = env.c.request(*ROUTES[0][:2], json=ROUTES[0][2])
    assert r.status_code == 503 and r.json()["code"] == "store_unavailable"
    assert "leak-me" not in r.text and "secret_token" not in r.text


def test_router_requires_an_audit_emitter() -> None:
    with pytest.raises(TypeError):
        make_drawings_router(lambda: None, None, None)  # type: ignore[arg-type]  # the point


@pytest.mark.parametrize(
    ("method", "error", "status", "code"),
    [("update", DrawingNotFoundError, 404, "not_found"),
     ("update", DrawingVersionConflictError, 412, "version_conflict"),
     ("create", DrawingIdUnavailableError, 409, "conflict")],
)  # fmt: skip
def test_store_races_after_the_ownership_check_keep_their_meaning(
    env: Env, method: str, error: type[Exception], status: int, code: str
) -> None:
    d = env.create()

    async def racing(*_a: Any, **_k: Any) -> Any:
        raise error("raced")

    setattr(env.repo, method, racing)  # e.g. deleted by another session between get and update
    r = (env.c.put(f"/drawings/{d['id']}", json=wire(TRENDLINE)) if method == "update"
         else env.c.post("/drawings", json=wire(TRENDLINE)))  # fmt: skip
    assert (r.status_code, r.json()["code"]) == (status, code)


def test_body_cap_holds_without_a_content_length(env: Env) -> None:
    chunks = iter([b'{"symbol":"' + b"A" * 40_000, b"A" * 40_000 + b'"}'])
    r = env.c.post("/drawings", content=chunks)  # chunked: no Content-Length to pre-check
    assert r.status_code == 413 and env.repo.rows == {}


def test_logs_never_carry_drawing_content(env: Env) -> None:
    sentinel = "SENTINEL-label-and-text"
    callout = TRENDLINE | {"tool": "callout", "label": sentinel,
                           "geometry": TRENDLINE["geometry"] | {"text": sentinel}}  # fmt: skip
    with capture_logs() as logs:
        d = env.create(**callout)
        env.c.put(f"/drawings/{d['id']}", json=wire(callout))
        env.c.post(
            "/drawings/batch",
            json=wire({"operations": [{"op": "create", "drawing": callout}]}, BATCH),
        )
        env.c.delete(f"/drawings/{d['id']}")
    assert [e["event"] for e in logs] == [
        "drawing_created", "drawing_updated", "drawings_batch_applied", "drawing_deleted",
    ]  # fmt: skip
    assert all(e["user_id"] == str(USER_A) and "op_count" in e for e in logs)
    assert sentinel not in repr(logs) and "61200.10" not in repr(logs)


# -- the real composition root -------------------------------------------------------------


def test_create_app_serves_drawings_behind_csrf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(appmod, "build_identity_provider", lambda _settings: fakes.Identity())
    app = appmod.create_app()  # as main.py: no principal_resolver
    app.state.app_context.auth._sessions = fakes.Sessions()
    app.state.app_context.auth._repository = FullUsers()  # #2295: classified as full
    writer = app.state.app_context.audit._writer = fakes.Audit()
    h, peer = {"Authorization": "Bearer tok-a"}, ("127.0.0.1", 50000)
    c = arm_csrf(TestClient(app, client=peer), app.state.csrf_codec, SID)
    assert c.delete(f"/drawings/{MISSING}", headers=h).status_code == 503  # fake backend
    app.state.drawings_repository = repo = fakes.FakeDrawingRepo()
    refused = TestClient(app, client=peer).post("/drawings", json=wire(TRENDLINE), headers=h)
    assert refused.status_code == 403 and refused.json()["code"] == "csrf_token_invalid"
    assert repo.rows == {}
    made = c.post("/drawings", json=wire(TRENDLINE), headers=h)
    assert made.status_code == 201 and set(made.json()) == DRAWING_KEYS, made.text
    assert c.get("/drawings?symbol=BTCUSDT", headers=h).json()["items"] == [made.json()]
    gone = {"op": "delete", "id": made.json()["id"], "if_match": made.json()["updated_at"]}
    done = c.post("/drawings/batch", json=wire({"operations": [gone]}, BATCH), headers=h)
    assert done.json() == {"created": [], "updated": [], "deleted": [made.json()["id"]]}
    assert [w["action"] for w in writer.calls] == ["auth.csrf_refused"]
