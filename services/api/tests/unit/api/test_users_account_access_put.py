"""PUT /users/{userId}/account-access (E42-T08 S9c, #2648; contract `setUserAccountAccess`): the
route over `AccountAccessService` over the real store, whose unit of work is the store tests' fake.
A refusal changes nothing: no write, no record, no push. The service on its own is
tests/unit/admin/test_account_access_service.py, and AC3 end to end is
tests/unit/architecture/test_ws_principal_composition.py."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from sqlalchemy.exc import DBAPIError

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.users import make_users_router
from candleviewer.auth.scopes import AccountGrant
from candleviewer.observability.context import bind_context
from candleviewer.storage.repositories import account_access_sqlalchemy as m
from candleviewer.storage.repositories.account_access import AccessUserNotFoundError
from tests.contract.rbac import rbac_harness as rbac
from tests.unit.admin import test_account_access_service as svc
from tests.unit.api import test_users_account_access_get as g
from tests.unit.storage import test_account_access_sqlalchemy as st

CALLER, TARGET, OTHER, _A, _B, _C = g.CALLER, g.TARGET, g.OTHER, st._A, st._B, st._C
_SPEC: dict[str, Any] = load_openapi_spec()
_HELD_A = ((_A, True, False, False, None, OTHER),)  # the target's one live grant: _A read
_FORBIDDEN = {"type": "about:blank", "title": "Forbidden", "status": 403, "code": "forbidden"}
_KEYS = ("exchange_account_id", "level", "account_label", "environment", "granted_by")
_PEER = ("192.0.2.7", 50000)  # the caller's address (RFC 5737)
_SESSION = uuid.uuid5(rbac.user_id_of("owner"), "session")  # the owner token's session
_BODY_CAP, _GRANT_CAP = 64 * 1024, 256  # SR-040, as the route bounds the body
_RID = uuid.uuid4()  # the request id a test binds for the call


class _Emitter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: Exception | None = None

    async def emit(self, action: str, **kw: Any) -> None:
        if self.error is not None:
            raise self.error
        self.calls.append({"action": action, **kw})


class _Bound:
    """ASGI middleware binding the request id as `CorrelationMiddleware` does, whatever it is."""

    def __init__(self, app: Any, request_id: str) -> None:
        self.app, self.request_id = app, request_id

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        with bind_context(request_id=self.request_id):
            await self.app(scope, receive, send)


class _World(svc._World):
    """The service's world with the route over it, the caller's audit emitter and a live step-up."""

    def __init__(self, rel: Any = None, **kw: Any) -> None:
        super().__init__(rel, **kw)
        self.emitter, self.step_up = _Emitter(), rbac._StepUp()

    def client(
        self,
        role: str | None = "owner",
        held: Any = (),
        wired: bool = True,
        request_id: str | None = None,
    ) -> TestClient:
        auth: Any = SimpleNamespace(step_up_is_active=wired, sessions_is_active=True)
        auth.step_up, auth.sessions = self.step_up, rbac._Sessions()
        res = g._Resolver(None if role is None else g._principal(role, _SPEC, held))
        users = make_users_router(
            None,
            self.emitter,
            res,
            g._Notifier(),
            auth=auth,
            account_access=self.store,
            access_service=self.service,
        )
        app = FastAPI()
        app.include_router(users)
        if request_id is not None:
            app.add_middleware(_Bound, request_id=request_id)
        token = {"Authorization": f"Bearer {rbac.token_of('owner')}"}
        return TestClient(app, client=_PEER, headers=token)

    def put(
        self, body: Any, *, target: uuid.UUID = TARGET, ack: str | None = None, **kw: Any
    ) -> Any:
        params = {} if ack is None else {"acknowledge_unknown_positions": ack}
        return self.client(**kw).put(g._PATH.format(target), params=params, json=body)


def _body(*grants: tuple[uuid.UUID, str], **extra: object) -> dict[str, Any]:
    return {"grants": [{"exchange_account_id": str(a), "level": lvl} | extra for a, lvl in grants]}


def _item(account: uuid.UUID, level: str, by: uuid.UUID) -> dict[str, str]:
    values = (str(account), level, st._label(account), "demo", str(by))
    return dict(zip(_KEYS, values, strict=True))


@pytest.mark.parametrize(
    ("grants", "ack"),
    [(((_B, "trade", CALLER),), "true"), (((_A, "read", OTHER), (_B, "trade", CALLER)), None)],
    ids=["swap-acknowledged", "add-only"],
)
def test_put_replaces_the_grants_and_pushes_after_the_commit(grants: Any, ack: str | None) -> None:
    """The 200 is the set the store read under its locks; record ahead, push after the commit.
    The record names the caller's session and address, as the route's refusals do (C-2.9)."""
    w = _World()
    r = w.put(_body(*((a, lvl) for a, lvl, _ in grants)), ack=ack)
    assert r.status_code == 200 and r.json() == {"items": [_item(*i) for i in grants]}, r.text
    schema = _SPEC["paths"][g._CONTRACT]["put"]["responses"]["200"]["content"]["application/json"]
    assert g._errors(_SPEC, schema["schema"], r.json()) == []
    ((action, record, _, committed_at_record),) = w.audit.calls
    assert action == "users.access_change" and not committed_at_record and w.rel.committed
    assert (record["actor_ip"], record["session_id"]) == (_PEER[0], _SESSION)
    assert w.notifier.pushes == [(TARGET, True)]


@pytest.mark.parametrize(
    ("bound", "recorded"), [(str(_RID), _RID), ("", None)], ids=["uuid", "empty"]
)
def test_records_name_the_request(bound: str, recorded: uuid.UUID | None) -> None:
    """C-2.9: each record the route writes carries the request id bound for the call, or none:
    an RBAC refusal's, the self-target's and the change's own, written ahead of the commit."""
    w = _World()
    w.put(_body((_A, "trade")), role="manager", request_id=bound)
    w.put(_body((_A, "trade")), target=CALLER, request_id=bound)
    assert w.put(_body((_B, "trade")), ack="true", request_id=bound).status_code == 200
    assert [c["request_id"] for c in w.emitter.calls] == [recorded, recorded]  # both refusals
    assert [call[1]["request_id"] for call in w.audit.calls] == [recorded]


def test_self_target_403() -> None:
    """F7, SR-055: refused before any lookup or step-up, audited once naming the target."""
    w = _World()
    r = w.put(_body((_A, "trade")), target=CALLER)
    assert r.status_code == 403 and r.json() == _FORBIDDEN | {"reason": "self_target"}
    (record,) = w.emitter.calls
    assert (record["action"], record["reason"]) == ("rbac.denied", "self_target")
    assert record["object_id"] == str(CALLER)
    assert w.rel.log == [] and w.positions.asked == [] and w.unchanged()


_HELD = (AccountGrant(_A, True, True, False),)


@pytest.mark.parametrize(
    ("role", "held", "target"),
    [
        ("manager", (), TARGET),
        ("manager", _HELD, TARGET),
        ("viewer", (), TARGET),
        ("manager", _HELD, CALLER),
        ("manager", _HELD, g.MISSING),
    ],
    ids=["manager-without-grant", "manager-with-grant", "viewer", "manager-own-id", "missing-id"],
)
def test_forbidden_manager_viewer_audited(role: str, held: Any, target: uuid.UUID) -> None:
    """F1, F2, F4: one 403 body for any id (U25), one record naming the target; nothing read."""
    labels = {"permission": "users:write"}
    w, before = _World(), REGISTRY.get_sample_value("authz_denied_total", labels) or 0.0
    r = w.put(_body((_A, "trade")), role=role, held=held, target=target)
    assert r.status_code == 403 and r.json() == _FORBIDDEN | {"reason": "missing_permission"}
    (record,) = w.emitter.calls
    assert record["action"] == "rbac.denied" and record["object_id"] == str(target)
    assert REGISTRY.get_sample_value("authz_denied_total", labels) == before + 1
    assert w.rel.log == [] and w.positions.asked == [] and w.unchanged()


@pytest.mark.parametrize(("role", "target"), [("manager", TARGET), ("owner", CALLER)])
def test_refusal_that_cannot_be_audited_is_503(role: str, target: uuid.UUID) -> None:
    """F6: a refusal is never answered unaudited."""
    w = _World()
    w.emitter.error = RuntimeError("AuditService.start() has not wired a real backend")
    r = w.put(_body((_A, "trade")), role=role, target=target)
    assert r.status_code == 503 and r.json()["code"] == "audit_unavailable"
    assert w.rel.log == [] and w.unchanged()


async def _peek_down(self: object, token: str) -> Any:
    raise ConnectionRefusedError("session store down")


@pytest.mark.parametrize(
    ("method", "role", "target", "reason"),
    [
        ("PUT", "manager", TARGET, "missing_permission"),
        ("PUT", "owner", CALLER, "self_target"),
        ("GET", "manager", TARGET, "missing_permission"),  # S9b's read refuses the same way
    ],
)
def test_refusal_is_audited_without_a_session_when_the_peek_fails(
    monkeypatch: pytest.MonkeyPatch, method: str, role: str, target: uuid.UUID, reason: str
) -> None:
    """C-2.9: the session a refusal's record names is a read of the session store. When that
    fails the record is still written, naming none, and the refusal is a 403, not a 500."""
    monkeypatch.setattr(rbac._Sessions, "peek_access_token", _peek_down)
    w = _World()
    body = _body((_A, "trade")) if method == "PUT" else None
    r = w.client(role).request(method, g._PATH.format(target), json=body)
    assert r.status_code == 403 and r.json() == _FORBIDDEN | {"reason": reason}
    (record,) = w.emitter.calls
    assert (record["action"], record["object_id"]) == ("rbac.denied", str(target))
    assert record["session_id"] is None and w.rel.log == [] and w.unchanged()


def test_stepup_and_audit_503() -> None:
    """SR-025: no live elevation is 403 before any read. AC8: an unwritable record is 503."""
    w = _World()
    w.step_up.elevated = False
    r = w.put(_body((_A, "trade")))
    assert r.status_code == 403 and r.json()["code"] == "step_up_required"
    assert w.rel.log == [] and w.positions.asked == []
    w = _World(audit_error=RuntimeError("audit WAL unavailable"))
    r = w.put(_body((_A, "trade")))
    assert r.status_code == 503 and r.json()["code"] == "audit_unavailable"
    assert not w.rel.committed and not w.notifier.pushes


@pytest.mark.parametrize("rel", [{"unknown": frozenset({_C})}, {"status": None}])
def test_unknown_account_404(rel: dict[str, Any]) -> None:
    """I1, I2: the whole set is refused, a deleted account or user like a missing one."""
    w = _World(st._Rel(rows=_HELD_A, **rel))
    r = w.put(_body((_A, "read"), (_C, "trade")), ack="true")
    assert r.status_code == 404 and r.json()["code"] == "not_found" and w.unchanged()
    assert str(_C) not in r.text and str(TARGET) not in r.text


@pytest.mark.parametrize("status", ["invited", "locked", "disabled"])
def test_non_active_user_409(status: str) -> None:
    w = _World(st._Rel(status=status, rows=_HELD_A))
    r = w.put(_body((_A, "trade")))
    assert r.status_code == 409 and r.json()["code"] == "conflict" and w.unchanged()


def test_busy_409() -> None:
    """A lock wait past `lock_timeout` (55P03): retryable; nothing changed or pushed."""
    error = DBAPIError("SELECT", None, st._DriverError("55P03"))
    w = _World(st._Rel(rows=_HELD_A, fail_on=m._LOCK_USER, error=error))
    r = w.put(_body((_A, "trade")))
    assert r.status_code == 409 and r.json()["code"] == "conflict" and w.unchanged()


def test_last_grant_needs_ack() -> None:
    """AC7: the open-position count is unknown (and no open-order count exists yet)."""
    w = _World()
    r = w.put(_body())
    assert r.status_code == 409 and r.json()["code"] == "positions_unknown" and w.unchanged()


def test_partial_removal_needs_ack() -> None:
    """#2648 Q2: every removal of a live grant, while a count is unknown."""
    w = _World(st._Rel(rows=(*_HELD_A, (_B, True, True))), positions=0)
    r = w.put(_body((_B, "trade")))
    assert r.status_code == 409 and r.json()["code"] == "positions_unknown" and w.unchanged()
    assert w.put(_body((_B, "trade")), ack="true").status_code == 200


@pytest.mark.parametrize(
    ("body", "ack"),
    [
        (_body((_A, "read"), frozen=False), None),
        (_body((_A, "read"), max_daily_loss_usd="9"), None),
        (_body((_A, "read"), can_trade=True), None),
        (_body((_A, "read"), granted_by=str(CALLER)), None),
        (_body((_A, "read")) | {"user_id": str(TARGET)}, None),
        (_body((_A, "read"), (_A, "trade")), None),
        (_body((_A, "admin")), None),
        (_body((_A, "read")), "maybe"),
    ],
    ids=["frozen", "cap", "can_trade", "granted_by", "user_id", "repeated", "level", "ack"],
)
def test_body_rejects_freeze_cap_and_duplicate_fields_400(body: Any, ack: str | None) -> None:
    """I5, UL2-T1: nothing in the request can carry a freeze, a cap or another user."""
    w = _World()
    r = w.put(body, ack=ack)
    assert r.status_code == 400 and r.json()["code"] == "validation_failed"
    assert w.rel.log == [] and w.positions.asked == []


def _spaced(size: int) -> bytes:
    """The target's set as it is (`_A` read), padded with JSON whitespace to `size` bytes."""
    raw = json.dumps(_body((_A, "read"))).encode()
    return raw + b" " * (size - len(raw))


def _chunked(raw: bytes) -> Any:  # an iterator body: sent chunked, with no `Content-Length`
    return iter([raw[:1024], raw[1024:]])


_AS_SENT = pytest.mark.parametrize("as_sent", [bytes, _chunked], ids=["content-length", "chunked"])


@_AS_SENT
def test_body_of_64_kib_is_read(as_sent: Callable[[bytes], Any]) -> None:
    """SR-040's byte cap is inclusive: the set as it is, padded to 64 KiB, is a no-op 200."""
    content = as_sent(_spaced(_BODY_CAP))
    r = _World().client().put(g._PATH.format(TARGET), content=content)
    assert r.status_code == 200 and r.json() == {"items": [_item(_A, "read", OTHER)]}


@_AS_SENT
def test_body_past_64_kib_is_400_and_reads_nothing(as_sent: Callable[[bytes], Any]) -> None:
    """SR-040: one byte more is refused before the body is held whole, by its declared
    `Content-Length` or, sent chunked without one, as the stream passes the cap."""
    w = _World()
    content = as_sent(_spaced(_BODY_CAP + 1))
    r = w.client().put(g._PATH.format(TARGET), content=content)
    assert r.status_code == 400 and r.json()["code"] == "validation_failed"
    assert w.rel.log == [] and w.positions.asked == []


class _Unread:
    """A body that fails the moment anything iterates it."""

    def __iter__(self) -> Iterator[bytes]:
        raise AssertionError("the body was read")


def test_declared_length_past_64_kib_is_refused_before_any_read() -> None:
    """SR-040: the declared `Content-Length` alone refuses the call. The stream cap would also
    refuse an honest body, but only after reading it; this one fails if it is read at all."""
    w = _World()
    headers = {"Content-Length": str(_BODY_CAP + 1)}
    r = w.client().put(g._PATH.format(TARGET), content=_Unread(), headers=headers)
    assert r.status_code == 400 and r.json()["code"] == "validation_failed"
    assert w.rel.log == [] and w.positions.asked == []


def _many(count: int) -> dict[str, Any]:
    return _body(*((uuid.UUID(int=i + 1), "read") for i in range(count)))


def test_256_grants_are_served() -> None:
    r = _World().put(_many(_GRANT_CAP), ack="true")
    assert r.status_code == 200 and len(r.json()["items"]) == _GRANT_CAP


def test_grant_past_the_256th_is_400_and_reads_nothing() -> None:
    """SR-040: 257 grants (about 20 KiB, under the byte cap) are refused by the schema before
    any read, and no account id is echoed."""
    w = _World()
    r = w.put(_many(_GRANT_CAP + 1), ack="true")
    assert r.status_code == 400 and r.json()["code"] == "validation_failed"
    assert str(uuid.UUID(int=_GRANT_CAP + 1)) not in r.text
    assert w.rel.log == [] and w.positions.asked == []


def test_unauthenticated_or_unwired_put_fails_closed() -> None:
    """F5: no session is 401; no service, or no step-up after RBAC, is 501. None reads."""
    w = _World()
    assert w.put(_body(), role=None).json()["code"] == "unauthenticated"
    gone = {"Authorization": "Bearer tok-gone"}  # the session ended after the resolver read it
    assert w.client().put(g._PATH.format(TARGET), json=_body(), headers=gone).status_code == 401
    assert w.put(_body(), wired=False).status_code == 501
    app = FastAPI()
    app.include_router(make_users_router(None, w.emitter, g._Resolver(None), g._Notifier()))
    assert TestClient(app).put(g._PATH.format(TARGET), json=_body()).status_code == 501
    assert w.rel.log == [] and not w.emitter.calls


def test_a_subclass_of_a_refusal_is_answered_as_its_parent() -> None:
    """The refusals are mapped by class, not by exact type: a subclass of one is 404, not a 500."""

    class _Gone(AccessUserNotFoundError):
        """A refusal the map has never seen."""

    w = _World(st._Rel(rows=_HELD_A, fail_on=m._LOCK_USER, error=_Gone("gone")))
    r = w.put(_body((_A, "trade")))
    assert r.status_code == 404 and r.json()["code"] == "not_found" and w.unchanged()


@pytest.mark.parametrize(
    "rel",
    [
        {"fail_on": m._LOCK_USER, "error": DBAPIError("SELECT", None, st._DriverError("57P01"))},
        {"on_close": DBAPIError("CLOSE", None, st._DriverError("08006"))},
        {"fail_on": m._LOCK_USER, "error": ConnectionRefusedError("database down")},
    ],
    ids=["before-the-commit", "after-the-commit", "database-down"],
)
def test_store_failure_is_503_and_re_evaluates_the_sockets(rel: dict[str, Any]) -> None:
    """A failure may follow a landed commit (the second did): 503, and the push runs anyway."""
    w = _World(st._Rel(rows=_HELD_A, **rel))
    with w.client() as client:
        r = client.put(g._PATH.format(TARGET), json=_body((_A, "trade")))
        assert client.portal is not None  # set while the client context is open
        client.portal.call(w.service.drain)
    assert r.status_code == 503 and r.json()["code"] == "store_unavailable"
    for leak in ("57P01", "08006", "drawdown", "database down"):  # no driver text, no SQLSTATE
        assert leak not in r.text
    assert [user for user, _ in w.notifier.pushes] == [TARGET]
