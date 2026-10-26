"""E14-X02 (#474) abuse cases, part C: the backend items the 2026-10-20 QA record left open.

The abuse table (every 22 `/drawings*` operation names its cases); server signals per abuse class
(SR-E14-11; missing counters are #2727 tripwires); mass assignment; IDOR under dead or downgraded
sessions (real `create_app`); the batch 422/413 literal differential; hostile keys in
`errors[].field`; SR-E14-06's log half (analytics and journal: #4602). Router-level cases use the
in-memory repository; findings and SR coverage: `qa/security/e14-abuse-cases.md`."""

from __future__ import annotations

import ast
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import _drawings_api_env as fakes
import pytest
from _drawings_api_env import BATCH, SID, TRENDLINE, USER_A, USER_B, VIEWER, Env, wire
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY, generate_latest
from structlog.testing import capture_logs

import candleviewer.app as appmod
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.drawings_models import MAX_BATCH_OPS, MAX_SINGLE_BODY_BYTES, sanitize_text
from candleviewer.auth.errors import SessionNotFound, SessionRevoked
from tests.csrf_helpers import arm_csrf
from tests.unit.auth.auth_fakes import MFA_PROVED_AT, FullUsers

HERE = Path(__file__).parent
CORPUS = json.loads((HERE.parent / "fixtures/drawings_abuse/corpus.v1.json").read_text("utf-8"))
RANDOM = "9b2f6c1e-5d47-4a8e-b3c0-7e1d2a4f8c65"  # an id nobody owns
PT = TRENDLINE["geometry"]["points"][0]
FIB = {"symbol": "BTCUSDT", "tool": "fib_retracement", "geometry": {"points": [PT, PT],
                                                                    "levels": [0.5]}}  # fmt: skip
PER_REQUEST = {"date", "x-request-id", "traceparent", "x-trace-id", "x-correlation-id"}

# --- the abuse table -----------------------------------------------------------------------------

#: operationId -> abuse cases (`<module suffix>::<test>`) by class. `idor` is required for every
#: operation; `body` (injection and exhaustion) for every operation with a request body.
ABUSE_TABLE: dict[str, dict[str, tuple[str, ...]]] = {
    "listDrawings": {
        "idor": (
            "abuse_xss_idor::test_a_cursor_minted_for_another_user_opens_nothing",
            "layouts::test_listing_by_a_foreign_or_missing_layout_is_one_identical_404",
            "api_rbac::test_idor_matrix",
            "abuse_backend::test_a_dead_or_downgraded_session_reaches_no_foreign_drawing",
        )
    },
    "createDrawing": {
        "idor": (
            "abuse_backend::test_server_owned_fields_in_a_body_are_refused_and_nothing_moves",
            "abuse_xss_idor::test_a_second_users_reuse_of_the_same_key_and_body_is_a_409_without_the_first_response",
            "abuse_backend::test_a_dead_or_downgraded_session_reaches_no_foreign_drawing",
        ),
        "body": (
            "abuse_xss_idor::test_corpus_is_stored_stripped_never_decoded_and_served_as_json",
            "abuse_exhaustion::test_single_body_at_the_cap_is_served_and_one_byte_over_is_413",
            "abuse_exhaustion::test_a_huge_or_non_finite_price_is_a_bounded_422_never_a_500",
            "abuse_backend::test_a_hostile_json_key_is_echoed_sanitised_and_clipped_as_data",
        ),
    },
    "updateDrawing": {
        "idor": (
            "abuse_xss_idor::test_put_delete_probes_return_one_identical_404_and_change_nothing",
            "abuse_xss_idor::test_unusable_if_match_is_a_uniform_412_for_own_foreign_and_missing_ids",
            "abuse_backend::test_server_owned_fields_in_a_body_are_refused_and_nothing_moves",
            "abuse_backend::test_a_dead_or_downgraded_session_reaches_no_foreign_drawing",
        ),
        "body": (
            "abuse_xss_idor::test_corpus_is_stored_stripped_never_decoded_and_served_as_json",
            "abuse_backend::test_a_hostile_json_key_is_echoed_sanitised_and_clipped_as_data",
        ),
    },
    "deleteDrawing": {
        "idor": (
            "abuse_xss_idor::test_put_delete_probes_return_one_identical_404_and_change_nothing",
            "abuse_xss_idor::test_enumerated_id_classes_are_404_for_every_method",
            "abuse_backend::test_a_dead_or_downgraded_session_reaches_no_foreign_drawing",
        )
    },
    "batchUpsertDrawings": {
        "idor": (
            "abuse_xss_idor::test_a_batch_with_one_unavailable_target_rolls_back_the_attackers_own_ops",
            "abuse_xss_idor::test_batch_bodies_are_identical_for_foreign_deleted_and_missing_targets",
            "abuse_backend::test_server_owned_fields_in_a_body_are_refused_and_nothing_moves",
            "abuse_backend::test_a_dead_or_downgraded_session_reaches_no_foreign_drawing",
        ),
        "body": (
            "abuse_exhaustion::test_batch_body_at_the_cap_is_served_and_one_byte_over_is_413",
            "abuse_exhaustion::test_a_batch_of_maximum_size_geometry_is_413_before_validation",
            "abuse_backend::test_a_batch_numeric_literal_is_422_under_the_op_cap_and_413_over_it",
            "abuse_backend::test_a_hostile_json_key_is_echoed_sanitised_and_clipped_as_data",
        ),
    },
}


def _contract_ops() -> dict[str, dict[str, Any]]:
    spec: dict[str, Any] = load_openapi_spec()
    return {
        op["operationId"]: op
        for path, item in spec["paths"].items() if path.startswith("/drawings")
        for method, op in item.items() if method in ("get", "put", "post", "delete", "patch")
    }  # fmt: skip


def test_every_drawings_operation_in_the_contract_has_abuse_rows() -> None:
    ops = _contract_ops()
    assert set(ABUSE_TABLE) == set(ops), "a /drawings* operation changed: update ABUSE_TABLE"
    for name, op in ops.items():
        needed = {"idor", "body"} if "requestBody" in op else {"idor"}
        assert {k for k, v in ABUSE_TABLE[name].items() if v} >= needed, name


def _tests_in(module: str) -> set[str]:
    tree = ast.parse((HERE / f"test_drawings_{module}.py").read_text("utf-8"))
    return {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}


def test_every_case_the_abuse_table_names_exists() -> None:
    refs = {ref for row in ABUSE_TABLE.values() for refs in row.values() for ref in refs}
    missing = [r for r in sorted(refs) if r.split("::")[1] not in _tests_in(r.split("::")[0])]
    assert missing == []


# --- server signals per abuse class (SR-E14-11) -------------------------------------------------

WRITES: dict[str, tuple[str, str]] = {  # op -> (method, path); "{id}" is the target drawing
    "create": ("POST", "/drawings"),
    "put": ("PUT", "/drawings/{id}"),
    "delete": ("DELETE", "/drawings/{id}"),
    "batch": ("POST", "/drawings/batch"),
}


def _write(env: Env, op: str, target: dict[str, Any]) -> Any:
    method, path = WRITES[op]
    delete = {"op": "delete", "id": target["id"], "if_match": target["updated_at"]}
    batch = wire({"operations": [delete]}, BATCH)
    body = {"create": wire(TRENDLINE), "put": wire(TRENDLINE), "delete": None, "batch": batch}[op]
    return env.c.request(method, path.format(id=target["id"]), json=body)


def _denied_total(permission: str = "workspaces:write") -> float:
    return REGISTRY.get_sample_value("authz_denied_total", {"permission": permission}) or 0.0


@pytest.mark.parametrize("op", list(WRITES))
def test_a_viewer_write_moves_the_denied_counter_once_and_leaves_one_record(op: str) -> None:
    env = Env()
    mine = env.create()
    env.user, before = VIEWER, _denied_total()
    r = _write(env, op, mine)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert _denied_total() == before + 1
    assert [c["reason"] for c in env.audit.denied()] == ["missing_permission:workspaces:write:self"]


@pytest.mark.parametrize("op", ["put", "delete"])
def test_a_foreign_id_probe_is_audited_but_counted_nowhere_tripwire_2727(op: str) -> None:
    """Finding F-02: a scope denial (404 to a foreign id) writes `rbac.denied` and moves no counter;
    SR-E14-11's denied counter is #2727's. When it lands, assert it here instead."""
    metrics = MagicMock()
    env = Env(metrics=metrics)
    mine = env.create()
    env.user, before = USER_B, _denied_total()
    r = _write(env, op, mine)
    assert r.status_code == 404
    assert [c["reason"] for c in env.audit.denied()] == ["not_owner:workspaces:write:self"]
    assert _denied_total() == before and metrics.conflicts.labels.call_args_list == []


def test_a_foreign_batch_target_moves_the_conflict_counter_and_leaves_one_record() -> None:
    metrics = MagicMock()
    env = Env(metrics=metrics)
    mine = env.create()
    env.user = USER_B
    r = _write(env, "batch", mine)
    assert r.status_code == 409 and r.json()["errors"][0]["rule"] == "target_unavailable"
    metrics.conflicts.labels.assert_called_once_with("target_unavailable")
    metrics.conflicts.labels.return_value.inc.assert_called_once_with()
    assert [c["object_id"] for c in env.audit.denied()] == [mine["id"]]


def _over_cap_batch() -> bytes:
    op = {"op": "create", "drawing": wire(TRENDLINE)}
    return json.dumps({"operations": [op] * (MAX_BATCH_OPS + 1)}).encode()


OVERSIZE = {  # abuse class -> (path, body)
    "single_body": ("/drawings", b'{"label":"' + b"x" * MAX_SINGLE_BODY_BYTES + b'"}'),
    "batch_ops": ("/drawings/batch", _over_cap_batch()),
}


@pytest.mark.parametrize("kind", list(OVERSIZE))
def test_an_oversize_or_over_cap_refusal_leaves_no_drawings_signal_tripwire_2727(kind: str) -> None:
    """Finding F-03: a 413 leaves no drawings counter, no audit record and no log line; only the
    route's `cv_http_request_duration_seconds{status_class="4xx"}` moves (next test). SR-E14-11's
    oversize and batch-cap counters are #2727's: when they land, assert them here instead."""
    metrics = MagicMock()
    env = Env(metrics=metrics)
    path, body = OVERSIZE[kind]
    with capture_logs() as logs:
        r = env.c.post(path, content=body)
    assert r.status_code == 413 and r.json()["code"] == "payload_too_large"
    assert metrics.mock_calls == [] and env.audit.calls == [] and logs == []
    assert env.repo.calls == []


def _app(sessions: Any = None, identity: Any = None, users: Any = None) -> tuple[Any, Any]:
    """The real `create_app()` on the drawings fakes; returns (app, CSRF-armed client)."""
    mp = pytest.MonkeyPatch()
    mp.setattr(appmod, "build_identity_provider", lambda _s: identity or fakes.Identity())
    try:
        app = appmod.create_app()
    finally:
        mp.undo()
    app.state.app_context.auth._sessions = sessions or fakes.Sessions()
    app.state.app_context.auth._repository = users or FullUsers()  # #2295: classified as full
    app.state.app_context.audit._writer = fakes.Audit()
    app.state.drawings_repository = fakes.FakeDrawingRepo()
    peer = ("127.0.0.1", 50000)
    return app, arm_csrf(TestClient(app, client=peer), app.state.csrf_codec, SID)


def _series(app: Any, prefix: str) -> dict[str, float]:
    text = generate_latest(app.state.app_context.metrics).decode()
    rows = (line.rpartition(" ") for line in text.splitlines() if line.startswith(prefix))
    return {name: float(value) for name, _, value in rows}


@pytest.mark.parametrize("kind", list(OVERSIZE))
def test_the_only_trace_of_an_oversize_refusal_is_the_routes_4xx_duration_series(kind: str) -> None:
    app, c = _app()
    path, body = OVERSIZE[kind]
    count = f'cv_http_request_duration_seconds_count{{env="demo",method="POST",route="{path}",'
    before = _series(app, "cv_drawings_")
    r = c.post(path, content=body, headers={"Authorization": "Bearer tok-a"})
    assert r.status_code == 413
    assert _series(app, count) == {count + 'status_class="4xx"}': 1.0}
    assert _series(app, "cv_drawings_") == before


# --- mass assignment ----------------------------------------------------------------------------

#: Server-owned or internal columns: `DrawingInput` is closed (`additionalProperties: false`).
STAMP = "2026-01-01T00:00:00Z"
SERVER_FIELDS = {"owner_user_id": str(USER_A), "id": RANDOM, "created_at": STAMP,
                 "updated_at": STAMP, "alert_id": RANDOM, "deleted_at": None}  # fmt: skip


@pytest.mark.parametrize("path", ["create", "put", "batch_create", "batch_update"])
@pytest.mark.parametrize("key", list(SERVER_FIELDS))
def test_server_owned_fields_in_a_body_are_refused_and_nothing_moves(key: str, path: str) -> None:
    """User B names user A (the victim) as owner, or sets an id, timestamp or alert: always 422."""
    env = Env()
    victim = env.create()
    env.user = USER_B
    own = env.create()
    drawing = wire(TRENDLINE) | {key: SERVER_FIELDS[key]}
    rows, deleted = dict(env.repo.rows), dict(env.repo.deleted)
    if path == "create":
        r, field = env.c.post("/drawings", json=drawing), key
    elif path == "put":
        r, field = env.c.put(f"/drawings/{own['id']}", json=drawing), key
    else:
        op: dict[str, Any] = {"op": "create", "drawing": drawing}
        if path == "batch_update":
            op = {
                "op": "update",
                "id": own["id"],
                "if_match": own["updated_at"],
                "drawing": drawing,
            }
        r = env.c.post("/drawings/batch", json={"operations": [op]})
        field = f"operations.0.drawing.{key}"
    assert r.status_code == 422, r.text
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [(field, "extra_forbidden")]
    assert env.repo.rows == rows and env.repo.deleted == deleted
    assert env.repo.rows[victim["id"]].owner_user_id == str(USER_A)


# --- IDOR under a dead or downgraded session (the real composition root) ------------------------

GONE = uuid.UUID("00000000-0000-4000-8000-00000000000d")  # the user row was deleted
DOWN = uuid.UUID("00000000-0000-4000-8000-00000000000e")  # manager downgraded to viewer
#: bearer -> user. `peek` (the CSRF binding) ignores TTL and revocation as the real store does;
#: `authenticate` refuses: `tok-ttl` access token past its TTL, `tok-revoked` absolute expiry.
TOKENS = {"tok-a": USER_A, "tok-ttl": USER_B, "tok-revoked": USER_B, "tok-gone": GONE,
          "tok-down": DOWN}  # fmt: skip
EXPIRED_TTL, EXPIRED_ABSOLUTE, DOWNGRADED = {"tok-ttl"}, {"tok-revoked"}, {"tok-down"}


class _Sessions:
    async def peek_access_token(self, token: str) -> Any:
        user = TOKENS.get(token)
        return None if user is None else SimpleNamespace(
            view_as=None, id=SID, user_id=user, mfa_satisfied_at=MFA_PROVED_AT)  # fmt: skip

    async def authenticate_access_token(self, token: str, **_kw: Any) -> Any:
        if token in EXPIRED_TTL:
            raise SessionNotFound("access token expired")
        if token in EXPIRED_ABSOLUTE:
            raise SessionRevoked("expired")
        if (record := await self.peek_access_token(token)) is None:
            raise SessionNotFound("unknown token")
        return record


class _Identity:
    async def user(self, user_id: str) -> dict[str, Any]:
        if user_id == str(GONE):
            raise LookupError(user_id)
        return {"username": "u", "roles": ["viewer" if user_id == str(DOWN) else "manager"],
                "status": "active"}  # fmt: skip

    async def session_info(self, user_id: str) -> dict[str, Any]:
        perms = ["workspaces:read"] + ([] if user_id == str(DOWN) else ["workspaces:write"])
        return {"permissions": perms, "account_scope": []}


def _probe(c: Any, token: str, did: str, token_of: str) -> list[Any]:
    h = {"Authorization": f"Bearer {token}"}
    upd = {"op": "update", "id": did, "if_match": token_of, "drawing": TRENDLINE}
    return [
        c.get("/drawings?symbol=BTCUSDT", headers=h),
        c.post("/drawings", json=wire(TRENDLINE), headers=h),
        c.put(f"/drawings/{did}", json=wire(TRENDLINE), headers=h),
        c.delete(f"/drawings/{did}", headers=h),
        c.post("/drawings/batch", json=wire({"operations": [upd]}, BATCH), headers=h),
    ]


def _shape(r: Any) -> tuple[int, str, dict[str, str]]:
    return r.status_code, r.text, {k: v for k, v in r.headers.items() if k not in PER_REQUEST}


@pytest.mark.parametrize("token", ["tok-ttl", "tok-revoked", "tok-gone", "tok-down"])
def test_a_dead_or_downgraded_session_reaches_no_foreign_drawing(token: str) -> None:
    app, c = _app(_Sessions(), _Identity(), FullUsers({str(GONE): None}))
    repo, audit = app.state.drawings_repository, app.state.app_context.audit._writer
    victim = c.post("/drawings", json=wire(TRENDLINE), headers={"Authorization": "Bearer tok-a"})
    d = victim.json()
    rows, calls = dict(repo.rows), len(repo.calls)
    foreign = _probe(c, token, d["id"], d["updated_at"])
    missing = _probe(c, token, RANDOM, d["updated_at"])
    assert [_shape(r) for r in foreign] == [_shape(r) for r in missing]  # no existence oracle
    assert repo.rows == rows and d["id"] not in repo.deleted
    if token not in DOWNGRADED:  # refused before any route: 401, no store call, nothing audited
        assert {(r.status_code, r.json()["code"]) for r in foreign} == {(401, "unauthenticated")}
        assert repo.calls[calls:] == [] and audit.denied() == []
        return
    assert foreign[0].status_code == 200 and foreign[0].json()["items"] == []  # own scope only
    assert [r.status_code for r in foreign[1:]] == [403] * 4
    assert [n for n, _ in repo.calls[calls:]] == ["list_page"] * 2  # writes never reach the store
    reasons = {c["reason"] for c in audit.denied()}
    assert reasons == {"missing_permission:workspaces:write:self"} and len(audit.denied()) == 8


# --- batch numeric literals: 422 under the op cap, 413 over it ----------------------------------


def _fib_op(literal: str) -> str:
    op = json.dumps({"op": "create", "drawing": wire(FIB)}, separators=(",", ":"))
    return op.replace('"levels":[0.5]', f'"levels":[{literal}]')


def _batch(n_ops: int, literal: str, extra: str = "") -> str:
    ops = [_fib_op("0.5")] * (n_ops - 1) + [_fib_op(literal)]
    return '{"operations":[' + ",".join(ops) + "]" + extra + "}"


@pytest.mark.parametrize("literal", ["1e999", "-1e999", "NaN", "Infinity", "1" + "0" * 400 + ".5"])
def test_a_batch_numeric_literal_is_422_under_the_op_cap_and_413_over_it(literal: str) -> None:
    """22 `batchUpsertDrawings`: the 413 op cap is checked before per-operation validation, so the
    same hostile literal is a field 422 inside the cap and a 413 one operation past it."""
    env = Env()
    under = env.c.post("/drawings/batch", content=_batch(MAX_BATCH_OPS, literal))
    assert (under.status_code, under.json()["code"]) == (422, "validation_failed")
    assert [e["field"] for e in under.json()["errors"]] == [
        f"operations.{MAX_BATCH_OPS - 1}.drawing.geometry.levels.0"
    ]
    over = env.c.post("/drawings/batch", content=_batch(MAX_BATCH_OPS + 1, literal))
    assert (over.status_code, over.json()["code"]) == (413, "payload_too_large")
    assert literal[:40] not in under.text + over.text and env.repo.calls == []


#: name -> (body around a 201-operation batch, status): where the stdlib count and the model's
#: parser could disagree about what is JSON.
EDGES: dict[str, tuple[Callable[[str], str], int]] = {
    "int_4300_digits": (lambda b: b[:-1] + ',"x":' + "9" * 4300 + "}", 413),
    "int_4301_digits": (lambda b: b[:-1] + ',"x":' + "9" * 4301 + "}", 422),
    "leading_bom": (lambda b: "\ufeff" + b, 422),
    "trailing_data": (lambda b: b + " x", 422),
    "raw_tab_in_a_string": (lambda b: b[:-1] + ',"x":"a\tb"}', 422),
}


@pytest.mark.parametrize("edge", list(EDGES))
def test_the_op_count_and_the_model_agree_on_where_json_stops_being_json(edge: str) -> None:
    """The cap is counted on the stdlib parse; a body it cannot parse (an integer past CPython's
    4300-digit limit, a BOM, trailing data, a raw control character) is refused by the model's
    parser too, as `json_invalid`, never validated operation by operation: no input turns a 413
    into a full per-operation walk."""
    env = Env()
    build, status = EDGES[edge]
    r = env.c.post("/drawings/batch", content=build(_batch(MAX_BATCH_OPS + 1, "0.5")))
    assert r.status_code == status, r.text
    rules = [e["rule"] for e in r.json().get("errors", [])]
    assert rules == ([] if status == 413 else ["json_invalid"]) and env.repo.calls == []


# --- hostile JSON keys echoed in errors[].field -------------------------------------------------

MAX_SEGMENT = 64  # #357 decision record: each echoed key segment, in code points (22 sets none)
HOSTILE_KEYS = [
    pytest.param("<script>alert(1)</script>", id="script"),
    pytest.param("<img src=x onerror=alert(1)>" * 8, id="long_markup"),
    pytest.param("a" + chr(0x202E) + "b" + chr(0x2028) + "c\nd\x00e\x85f", id="bidi_and_controls"),
    pytest.param('"},"owner_user_id":"x', id="json_breakout"),
    pytest.param("\U0001f680" * 70, id="astral_over_cap"),
]


def _key_body(path: str, key: str, env: Env) -> tuple[str, str, Any]:
    drawing = wire(TRENDLINE) | {key: 1}
    if path == "batch":
        return "POST", "/drawings/batch", {"operations": [{"op": "create", "drawing": drawing}]}
    if path == "put":
        return "PUT", f"/drawings/{env.create()['id']}", drawing
    return "POST", "/drawings", drawing


@pytest.mark.parametrize("path", ["create", "put", "batch"])
@pytest.mark.parametrize("key", HOSTILE_KEYS)
def test_a_hostile_json_key_is_echoed_sanitised_and_clipped_as_data(key: str, path: str) -> None:
    """The unknown key becomes a path segment: control and bidi characters stripped, cut to 64
    code points plus an ellipsis, never HTML-encoded (SR-E14-01: the client renders it as text),
    served as problem+json. Finding F-04: 22 states no bound on `errors[].field`."""
    env = Env()
    method, url, body = _key_body(path, key, env)
    r = env.c.request(method, url, json=body)
    assert r.status_code == 422 and r.headers["content-type"] == "application/problem+json"
    clean = sanitize_text(key, allow_newline=False)
    segment = clean if len(clean) <= MAX_SEGMENT else clean[:MAX_SEGMENT] + "…"
    prefix = "operations.0.drawing." if path == "batch" else ""
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [
        (prefix + segment, "extra_forbidden")
    ]
    assert len(env.repo.rows) == (1 if path == "put" else 0)


def test_fifty_hostile_keys_yield_at_most_twenty_bounded_errors() -> None:
    env = Env()
    body = wire(TRENDLINE) | {f"<svg/onload=alert({i})>" + "x" * 200: i for i in range(50)}
    r = env.c.post("/drawings", json=body)
    assert r.status_code == 422 and len(r.json()["errors"]) == 20
    assert all(len(e["field"]) <= MAX_SEGMENT + 1 for e in r.json()["errors"])
    assert len(r.content) < 20 * 2 * (MAX_SEGMENT + 200)  # bounded, not proportional to the body


# --- SR-E14-06, log half: no corpus text in a log line or an audit record -------------------------


def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for k, v in node.items() for s in (*_strings(k), *_strings(v))]
    if isinstance(node, list | tuple):
        return [s for v in node for s in _strings(v)]
    return [str(node)] if node is not None else []


@pytest.mark.parametrize("case", [pytest.param(c, id=c["id"]) for c in CORPUS["payloads"]])
def test_no_corpus_text_reaches_a_log_line_or_an_audit_record(case: dict[str, str]) -> None:
    sentinel = f"SR-E14-06-{case['id']}"
    text = case["payload"] + sentinel
    label = text if len(text) <= 120 else None
    note: dict[str, Any] = {"symbol": "BTCUSDT", "tool": "text", "style": {},
                            "geometry": {"points": [PT], "text": text}}  # fmt: skip
    if label is not None:
        note["label"] = label
    env = Env()
    with capture_logs() as logs:
        d = env.create(**note)
        env.c.put(f"/drawings/{d['id']}", json=wire(note))
        env.c.post("/drawings", json=TRENDLINE | {"label": "x" * 121 + text})  # 422 too long
        env.user = USER_B  # probes on A's drawing: 404 and 409, both audited
        env.c.put(f"/drawings/{d['id']}", json=wire(note))
        batch = {"operations": [{"op": "update", "id": d["id"], "if_match": d["updated_at"],
                                 "drawing": note}]}  # fmt: skip
        assert env.c.post("/drawings/batch", json=wire(batch, BATCH)).status_code == 409
    assert len(env.audit.denied()) == 2 and logs != []
    seen = _strings(logs) + _strings(env.audit.calls)
    assert not any(sentinel in s for s in seen)
    if len(case["text"]) >= 8:  # a short one collides with ordinary words; the sentinel covers it
        assert not any(case["text"] in s for s in seen)
