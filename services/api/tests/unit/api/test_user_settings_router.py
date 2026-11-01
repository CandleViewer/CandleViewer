"""`/settings` over HTTP (E02-T13, #5181) with fakes: a principal resolver, the in-memory store, an
audit emitter and a clock; no database and no network (C-13.5). The CSRF and view-as guards are the
app's middlewares, so `tests/contract/test_user_settings_contract.py` drives them through the real
app; here the router's own refusals are pinned, the view-as tripwire among them."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import jsonschema
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.user_settings import make_user_settings_router
from candleviewer.api.user_settings_models import MAX_BODY_BYTES
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.writer import AuditUnavailable, AuditWriter, AuditWriterStopped
from candleviewer.auth.generated_permissions import Permission
from candleviewer.storage.errors import WriteAheadTimeout
from candleviewer.storage.repositories.user_settings import (
    UserSetting,
    UserSettingsWriteAhead,
)
from tests.openapi_helpers import deref
from tests.unit.audit.audit_fakes import FakeAuditRepository
from tests.unit.storage.fakes_replay_sessions import FakeClock
from tests.unit.storage.fakes_user_settings import FakeUserSettings
from tests.unit.storage.user_settings_contract import noop

_SPEC: Any = load_openapi_spec()
_URL = "/api/v1/settings"
_OWNER, _MANAGER, _VIEWER = (uuid.UUID(int=n) for n in (1, 2, 3))
_REQUEST = uuid.UUID("00000000-0000-4000-8000-00000000beef")
_ALL = frozenset(p.value for p in Permission)
_PERMISSIONS = {
    _OWNER: _ALL,
    _MANAGER: frozenset({"settings:read", "settings:write", "workspaces:write"}),
    _VIEWER: frozenset({"settings:read", "workspaces:read"}),
}
_NAMES = {_OWNER: "olga", _MANAGER: "mark", _VIEWER: "vera"}


def _principal(user: uuid.UUID, *, viewer: uuid.UUID | None = None) -> AuditPrincipal:
    return AuditPrincipal(
        user_id=user, username=_NAMES[user], permissions=_PERMISSIONS[user],
        session_id=uuid.uuid5(viewer or user, "session"), ip="100.64.0.7", request_id=_REQUEST,
        is_owner=user == _OWNER, actor_user_id=viewer,
        actor_username=None if viewer is None else _NAMES[viewer],
    )  # fmt: skip


class _Resolver:
    """Bearer `tok-<int>` is that user's session; `tok-<viewer>-as-<target>` a live view."""

    async def resolve(self, request: Request) -> AuditPrincipal | None:
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        viewer, _, target = token.removeprefix("tok-").partition("-as-")
        known = {str(u.int): u for u in _PERMISSIONS}
        if viewer not in known or (target and target not in known):
            return None
        return (
            _principal(known[target], viewer=known[viewer]) if target else _principal(known[viewer])
        )


class _Audit:
    """Records each emit with the store's rows as they stood then; `fail` refuses every emit."""

    def __init__(self, store: FakeUserSettings) -> None:
        self.store = store
        self.records: list[tuple[str, dict[str, Any]]] = []
        self.rows_at_record: list[dict[uuid.UUID, dict[str, UserSetting]]] = []
        self.fail: BaseException | None = None

    async def emit(self, action: str, **kwargs: Any) -> None:
        if self.fail is not None:
            raise self.fail
        self.records.append((action, kwargs))
        self.rows_at_record.append({u: dict(rows) for u, rows in self.store.rows.items()})


class _Env:
    def __init__(self, *, resolver: bool = True) -> None:
        self.clock = FakeClock()
        self.store: Any = FakeUserSettings(self.clock)
        self.audit = _Audit(self.store)
        app = FastAPI()
        router = make_user_settings_router(
            lambda: self.store, _Resolver() if resolver else None, self.audit
        )
        app.include_router(router, prefix="/api/v1")
        self.client = TestClient(app, raise_server_exceptions=False)

    def get(self, user: uuid.UUID, *, viewer: uuid.UUID | None = None) -> Any:
        return self.client.get(_URL, headers=_bearer(user, viewer))

    def patch(self, user: uuid.UUID, body: object, *, viewer: uuid.UUID | None = None) -> Any:
        return self.client.patch(_URL, json=body, headers=_bearer(user, viewer))

    async def seed(self, user: uuid.UUID, patch: Mapping[str, object]) -> None:
        await self.store.apply(user, patch, write_ahead=noop)

    def values(self, user: uuid.UUID) -> dict[str, object]:
        return {key: row.value for key, row in self.store.rows.get(user, {}).items()}


def _bearer(user: uuid.UUID, viewer: uuid.UUID | None = None) -> dict[str, str]:
    token = f"tok-{user.int}" if viewer is None else f"tok-{viewer.int}-as-{user.int}"
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def env() -> _Env:
    return _Env()


def _settings(resp: Any) -> dict[str, Any]:
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    jsonschema.validate(body, deref(_SPEC, {"$ref": "#/components/schemas/Settings"}))
    return body


def _problem(resp: Any, status: int, code: str) -> dict[str, Any]:
    assert (resp.status_code, resp.headers["content-type"]) == (status, "application/problem+json")
    body: dict[str, Any] = resp.json()
    assert body["code"] == code and body["status"] == status
    return body


# -- Gherkin: a user reads their effective settings --------------------------------------------


async def test_get_settings_answers_the_callers_overrides_and_meta_names_them(env: _Env) -> None:
    await env.seed(_MANAGER, {"appearance.density": "compact"})
    assert _settings(env.get(_MANAGER)) == {
        "appearance": {"density": "compact"},
        "_meta": {"overridden": ["appearance.density"], "updated_at": "2026-10-01T00:00:00Z"},
    }


# -- Gherkin: a patch changes only the leaves it names ------------------------------------------


async def test_patch_settings_changes_only_the_named_leaves_and_answers_the_merge(
    env: _Env,
) -> None:
    await env.seed(_MANAGER, {"appearance.density": "compact"})
    body = _settings(env.patch(_MANAGER, {"appearance": {"theme": "light"}}))
    assert body["appearance"] == {"density": "compact", "theme": "light"}
    assert body["_meta"]["overridden"] == ["appearance.density", "appearance.theme"]
    assert env.values(_MANAGER) == {"appearance.density": "compact", "appearance.theme": "light"}
    assert body == _settings(env.get(_MANAGER))


# -- Gherkin: a null leaf resets to the deployment default ----------------------------------------


async def test_patch_settings_a_null_leaf_deletes_the_override(env: _Env) -> None:
    await env.seed(_MANAGER, {"appearance.theme": "dark", "appearance.density": "compact"})
    body = _settings(env.patch(_MANAGER, {"appearance": {"theme": None}}))
    assert body["appearance"] == {"density": "compact"}
    assert body["_meta"]["overridden"] == ["appearance.density"]
    assert env.values(_MANAGER) == {"appearance.density": "compact"}


# -- Gherkin: a change is audited ahead of its commit ---------------------------------------------


async def test_patch_settings_writes_settings_change_ahead_of_its_commit(env: _Env) -> None:
    await env.seed(_OWNER, {"appearance.theme": "dark", "appearance.density": "compact"})
    env.patch(_OWNER, {"appearance": {"theme": "light", "density": "compact"}})
    ((action, record),) = env.audit.records
    assert action == "settings.change"
    assert record == {
        "actor_label": "user:owner", "actor_user_id": _OWNER, "actor_ip": "100.64.0.7",
        "session_id": uuid.uuid5(_OWNER, "session"), "request_id": _REQUEST,
        "object_kind": "setting", "object_id": str(_OWNER), "outcome": "success",
        "severity": "info", "before_state": {"appearance.theme": "dark"},
        "after_state": {"appearance.theme": "light"},  # the changed leaf only
    }  # fmt: skip
    assert env.audit.rows_at_record[0][_OWNER]["appearance.theme"].value == "dark"  # not yet
    assert env.values(_OWNER)["appearance.theme"] == "light"


async def test_patch_settings_records_a_reset_as_no_override_after(env: _Env) -> None:
    await env.seed(_MANAGER, {"appearance.theme": "dark"})
    env.patch(_MANAGER, {"appearance": {"theme": None}, "data": {"default_depth": 200}})
    ((_, record),) = env.audit.records
    assert record["actor_label"] == "user:manager"
    assert record["before_state"] == {"appearance.theme": "dark", "data.default_depth": None}
    assert record["after_state"] == {"appearance.theme": None, "data.default_depth": 200}


@pytest.mark.parametrize(
    "error",
    [AuditUnavailable("down"), AuditWriterStopped(), RuntimeError("no writer started")],
    ids=["unavailable", "stopped", "not-started"],
)
async def test_patch_settings_a_record_that_cannot_be_written_is_503_and_changes_nothing(
    env: _Env, error: BaseException
) -> None:
    await env.seed(_OWNER, {"appearance.theme": "dark"})
    env.audit.fail = error
    with capture_logs() as logs:
        resp = env.patch(_OWNER, {"appearance": {"theme": "light"}})
    _problem(resp, 503, "audit_unavailable")
    assert resp.headers["retry-after"] == "5"
    assert env.values(_OWNER) == {"appearance.theme": "dark"}
    assert [log["event"] for log in logs] == ["user_settings_audit_unavailable"]


async def test_patch_settings_a_record_past_its_bound_is_503_audit_unavailable(env: _Env) -> None:
    class _Slow(FakeUserSettings):
        async def apply(self, *_a: Any, write_ahead: UserSettingsWriteAhead) -> tuple[Any, ...]:
            raise WriteAheadTimeout("write-ahead audit exceeded 5.0 s")

    env.store = _Slow()
    _problem(env.patch(_OWNER, {"appearance": {"theme": "light"}}), 503, "audit_unavailable")


async def test_patch_settings_that_changes_nothing_writes_no_record(env: _Env) -> None:
    await env.seed(_MANAGER, {"appearance.theme": "dark"})
    body = _settings(env.patch(_MANAGER, {"appearance": {"theme": "dark", "density": None}}))
    assert body["appearance"] == {"theme": "dark"} and env.audit.records == []


# -- Gherkin: an invalid patch changes nothing -----------------------------------------------------


@pytest.mark.parametrize(
    ("body", "field", "rule"),
    [
        ({"appearance": {"glow": True}}, "appearance.glow", "extra_forbidden"),
        ({"bigtrade": {"k": 3}}, "bigtrade", "extra_forbidden"),
        ({"appearance": {"theme": "neon"}}, "appearance.theme", "literal_error"),
        ({"appearance": {"font_scale": 0.5}}, "appearance.font_scale", "greater_than_equal"),
        ({"trading": {"one_click_armed": True}}, "trading.one_click_armed", "read_only"),
    ],
    ids=["undeclared", "bigtrade", "enum", "range", "one-click-armed"],
)
async def test_patch_settings_an_invalid_patch_is_422_and_nothing_changes(
    env: _Env, body: dict[str, Any], field: str, rule: str
) -> None:
    await env.seed(_MANAGER, {"appearance.density": "compact"})
    body = {**body, "appearance": {**body.get("appearance", {}), "density": "spacious"}}
    problem = _problem(env.patch(_MANAGER, body), 422, "validation_failed")
    assert [(e["field"], e["rule"]) for e in problem["errors"]] == [(field, rule)]
    assert env.values(_MANAGER) == {"appearance.density": "compact"}  # the good leaf too
    assert ("apply", _MANAGER) not in env.store.calls[1:] and env.audit.records == []


async def test_patch_settings_a_body_over_the_cap_is_422_and_read_no_further(env: _Env) -> None:
    big = {"chart": {"default_param": "x" * MAX_BODY_BYTES}}
    problem = _problem(env.patch(_MANAGER, big), 422, "validation_failed")
    assert problem["errors"][0]["rule"] == "body_too_large"
    declared = env.client.patch(
        _URL, content=b"{}", headers={**_bearer(_MANAGER), "content-length": str(10**7)}
    )
    assert declared.status_code == 422 and env.store.calls == []


async def test_patch_settings_a_streamed_body_over_the_cap_is_refused(env: _Env) -> None:
    def chunks() -> Any:
        yield b'{"chart": {"default_param": "'
        yield b"x" * MAX_BODY_BYTES
        yield b'"}}'

    resp = env.client.patch(_URL, content=chunks(), headers=_bearer(_MANAGER))
    assert _problem(resp, 422, "validation_failed")["errors"][0]["rule"] == "body_too_large"


# -- Gherkin: a Viewer may read and may not write --------------------------------------------------


async def test_settings_a_viewer_reads_and_is_refused_403_on_a_write(env: _Env) -> None:
    await env.seed(_VIEWER, {"accessibility.verbosity": "high"})
    assert _settings(env.get(_VIEWER))["accessibility"] == {"verbosity": "high"}
    problem = _problem(
        env.patch(_VIEWER, {"accessibility": {"verbosity": "low"}}), 403, "forbidden"
    )
    assert problem["required_permissions"] == ["settings:write"]
    assert env.values(_VIEWER) == {"accessibility.verbosity": "high"}
    ((action, record),) = env.audit.records
    assert (action, record["reason"]) == ("rbac.denied", "missing_permission:settings:write:self")


@pytest.mark.parametrize("error", [AuditUnavailable("down"), RuntimeError("no writer")])
async def test_settings_a_denial_whose_record_cannot_be_written_is_503(
    env: _Env, error: BaseException
) -> None:
    env.audit.fail = error
    resp = env.patch(_VIEWER, {"accessibility": {"verbosity": "low"}})
    _problem(resp, 503, "audit_unavailable")
    assert env.store.calls == []


@pytest.mark.parametrize("resolver", [True, False], ids=["unknown-session", "no-resolver"])
async def test_settings_an_unauthenticated_caller_is_401_on_both(resolver: bool) -> None:
    env = _Env(resolver=resolver)
    headers = {"Authorization": "Bearer tok-unknown"}
    _problem(env.client.get(_URL, headers=headers), 401, "unauthenticated")
    _problem(env.client.patch(_URL, json={}, headers=headers), 401, "unauthenticated")
    assert env.store.calls == []


# -- Gherkin: one user never reads or writes another user's settings -----------------------------


async def test_settings_one_user_never_reads_or_writes_another_users(env: _Env) -> None:
    await env.seed(_OWNER, {"appearance.theme": "dark", "chart.crosshair_sync": False})
    await env.seed(_MANAGER, {"appearance.density": "compact"})
    owner_before = _settings(env.get(_OWNER))
    env.patch(_MANAGER, {"appearance": {"theme": "light"}, "chart": {"crosshair_sync": None}})
    mine = _settings(env.get(_MANAGER))
    assert mine["_meta"]["overridden"] == ["appearance.density", "appearance.theme"]
    assert "chart" not in mine  # none of the Owner's overrides
    assert _settings(env.get(_OWNER)) == owner_before
    assert [user for _, user in env.store.calls] == [
        _OWNER,
        _MANAGER,
        _OWNER,
        _MANAGER,
        _MANAGER,
        _OWNER,
    ]


# -- SR-026: no query parameter, a target user's least of all -------------------------------------


@pytest.mark.parametrize(
    ("query", "rule"),
    [
        ({"user_id": str(_OWNER)}, "target_user_not_accepted"),
        ({"userId": str(_OWNER)}, "target_user_not_accepted"),
        ({"theme": "light"}, "undeclared_parameter"),
    ],
    ids=["user_id", "userId", "undeclared"],
)
async def test_settings_a_query_parameter_is_422_and_nothing_is_read_or_written(
    env: _Env, query: dict[str, str], rule: str
) -> None:
    await env.seed(_MANAGER, {"appearance.theme": "dark"})
    calls, sent = list(env.store.calls), {"appearance": {"theme": "light"}}
    for resp in (
        env.client.get(_URL, params=query, headers=_bearer(_MANAGER)),
        env.client.patch(_URL, params=query, json=sent, headers=_bearer(_MANAGER)),
    ):
        body = _problem(resp, 422, "validation_failed")
        assert [e["rule"] for e in body["errors"]] == [rule]
        assert set(body) == {"type", "title", "status", "code", "detail", "errors"}  # no data
    assert env.store.calls == calls and env.audit.records == []  # nothing read, no record
    assert env.values(_MANAGER) == {"appearance.theme": "dark"}


async def test_settings_the_permission_is_refused_before_a_query_parameter_is(env: _Env) -> None:
    sent = {"accessibility": {"verbosity": "low"}}
    resp = env.client.patch(
        _URL, params={"user_id": str(_OWNER)}, json=sent, headers=_bearer(_VIEWER)
    )
    _problem(resp, 403, "forbidden")
    assert [action for action, _ in env.audit.records] == ["rbac.denied"]
    assert env.store.calls == []


# -- Gherkin: a view-as context reads the target and writes nothing -------------------------------


async def test_settings_a_view_reads_the_targets_settings_never_the_viewers(env: _Env) -> None:
    await env.seed(_OWNER, {"appearance.theme": "dark"})
    await env.seed(_MANAGER, {"appearance.theme": "light"})
    assert _settings(env.get(_MANAGER, viewer=_OWNER)) == _settings(env.get(_MANAGER))


async def test_settings_a_write_under_a_view_is_refused_before_anything_else(env: _Env) -> None:
    await env.seed(_MANAGER, {"appearance.theme": "light"})
    resp = env.patch(_MANAGER, {"appearance": {"theme": "dark"}}, viewer=_OWNER)
    _problem(resp, 403, "view_as_read_only")
    assert env.values(_MANAGER) == {"appearance.theme": "light"}
    assert env.audit.records == [] and ("apply", _MANAGER) not in env.store.calls[1:]


# -- the store -------------------------------------------------------------------------------------


async def test_settings_answer_503_when_no_store_is_wired(env: _Env) -> None:
    env.store = None
    for resp in (env.get(_MANAGER), env.patch(_MANAGER, {"appearance": {"theme": "dark"}})):
        assert _problem(resp, 503, "store_unavailable")["retry_after_seconds"] == 5


async def test_settings_answer_503_when_the_store_cannot_serve_the_call(env: _Env) -> None:
    env.store.down = True
    with capture_logs() as logs:
        reads, writes = env.get(_MANAGER), env.patch(_MANAGER, {"appearance": {"theme": "dark"}})
    _problem(reads, 503, "store_unavailable")
    _problem(writes, 503, "store_unavailable")
    assert [(log["event"], log["error"]) for log in logs] == [
        ("user_settings_store_unavailable", "StorageTierUnavailable")
    ] * 2


async def test_settings_a_store_error_that_is_no_outage_is_a_server_error(env: _Env) -> None:
    class _Broken(FakeUserSettings):
        async def read(self, user_id: uuid.UUID) -> tuple[UserSetting, ...]:
            raise LookupError("a defect")

    env.store = _Broken()
    assert env.get(_MANAGER).status_code == 500


# -- observability and the record's role -----------------------------------------------------------


async def test_patch_settings_logs_the_changed_keys_and_never_a_value(env: _Env) -> None:
    hook = "https://hooks.example.test/T000/canary-5181"
    with capture_logs() as logs:
        env.patch(_MANAGER, {"notifications": {"webhook_url": hook, "email_enabled": True}})
    assert logs == [
        {
            "event": "user_settings_changed", "user_id": str(_MANAGER), "log_level": "info",
            "keys": ["notifications.email_enabled", "notifications.webhook_url"],
        }
    ]  # fmt: skip
    assert "canary-5181" not in json.dumps(logs)


def test_record_role_holds_while_only_the_owner_and_managers_hold_settings_write() -> None:
    """`_role` labels a writer `owner` or `manager`: it holds only while no other role holds
    `settings:write` (22 `x-permissions`, the owner by `*`)."""
    roles = {
        role
        for role, codes in _SPEC["x-permissions"].items()
        if "settings:write" in codes or "*" in codes or role == "owner"
    }
    assert roles == {"owner", "manager"}


# -- Q3, as ruled: the webhook URL leaves its owner masked -----------------------------------------

_HOOK = "notifications.webhook_url"
#: A canary in each part `masked` drops: the userinfo, the path, the query and the fragment.
_CANARY_1 = "https://canary-u1@hooks.example.test:8443/T000/canary-p1?k=canary-q1#canary-f1"
_CANARY_2 = "https://canary-u2@hooks.example.test/T001/canary-p2?k=canary-q2#canary-f2"
_SHOWN = "https://hooks.example.test/…"


def _states(records: list[tuple[str, dict[str, Any]]]) -> list[tuple[Any, Any]]:
    return [(record["before_state"], record["after_state"]) for _, record in records]


async def test_patch_settings_records_the_webhook_url_masked_on_a_set_a_change_and_a_reset(
    env: _Env,
) -> None:
    for url in (_CANARY_1, _CANARY_2, None):  # set, change, reset
        _settings(env.patch(_MANAGER, {"notifications": {"webhook_url": url}}))
    assert _states(env.audit.records) == [
        ({_HOOK: None}, {_HOOK: _SHOWN}),
        ({_HOOK: _SHOWN}, {_HOOK: _SHOWN}),
        ({_HOOK: _SHOWN}, {_HOOK: None}),
    ]
    assert "canary" not in json.dumps(_states(env.audit.records))


async def test_patch_settings_a_webhook_url_changed_in_its_path_only_is_one_record(
    env: _Env,
) -> None:
    await env.seed(_OWNER, {_HOOK: "https://hooks.example.test/T000/canary-old"})
    sent = "https://hooks.example.test/T000/canary-new"
    body = _settings(env.patch(_OWNER, {"notifications": {"webhook_url": sent}}))
    assert _states(env.audit.records) == [({_HOOK: _SHOWN}, {_HOOK: _SHOWN})]
    assert body["notifications"] == {"webhook_url": sent}  # its owner reads it in full
    assert env.values(_OWNER) == {_HOOK: sent}


async def test_settings_a_view_reads_the_webhook_url_masked_and_its_owner_in_full(
    env: _Env,
) -> None:
    await env.seed(_MANAGER, {_HOOK: _CANARY_1, "notifications.email_enabled": True})
    own, viewed = _settings(env.get(_MANAGER)), _settings(env.get(_MANAGER, viewer=_OWNER))
    assert own["notifications"] == {"webhook_url": _CANARY_1, "email_enabled": True}
    assert viewed["notifications"] == {"webhook_url": _SHOWN, "email_enabled": True}
    assert viewed["_meta"] == own["_meta"]


class _Emits:
    """The app's emitter shape over the real writer, as `_LazyAuditEmitter` passes it on."""

    def __init__(self, writer: AuditWriter) -> None:
        self.writer = writer

    async def emit(self, action: str, **fields: Any) -> None:
        await self.writer.emit(action, **fields)


async def test_patch_settings_the_real_writer_stores_the_webhook_url_masked(tmp_path: Path) -> None:
    """Through the real `AuditWriter.build()` and `audit.redact`, not the fake sink: the masked
    form passes the redactor (no secret-shaped key), and the stored rows hold no canary."""
    repo = FakeAuditRepository()
    writer = AuditWriter(repo, str(tmp_path / "audit.wal"), sleep=repo.retry_sleep)
    await writer.start()
    store = FakeUserSettings(FakeClock())
    app = FastAPI()
    app.include_router(
        make_user_settings_router(lambda: store, _Resolver(), _Emits(writer)), prefix="/api/v1"
    )
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://cv") as client:
            for url in (_CANARY_1, _CANARY_2, None):
                sent = {"notifications": {"webhook_url": url}}
                resp = await client.patch(_URL, json=sent, headers=_bearer(_MANAGER))
                assert resp.status_code == 200, resp.text
        await writer.flush(5)
    finally:
        await writer.stop(1)
    stored = [(r["action"], r["before_state"], r["after_state"]) for r in repo.rows]
    assert [(a, json.loads(b), json.loads(f)) for a, b, f in stored] == [
        ("settings.change", {_HOOK: None}, {_HOOK: _SHOWN}),
        ("settings.change", {_HOOK: _SHOWN}, {_HOOK: _SHOWN}),
        ("settings.change", {_HOOK: _SHOWN}, {_HOOK: None}),
    ]
    assert "canary" not in json.dumps(repo.rows, default=str)
