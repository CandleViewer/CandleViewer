"""#2505 composition guard: the deployed `create_app()` (nothing injected) on the real backend
builds the WS principal from the store (`StorePrincipalLoader`). So a `sub` over `/ws` answers
as `tests/contract/rbac/matrix.yaml` says, for every topic family and actor, and a withdrawn grant
revokes a live subscription. Only the SQL edges of the real classes
(`SqlAlchemyIdentityProvider.user`/`session_info`, `SqlAlchemyScopeSource.load_grants`) and the
session service are faked, through the RBAC pack's seams (no Postgres, no network). The fake
backend keeps the deny-all principal. #2648 S9c: the owner's PUT drives the push (AC3), with its
store edge (`SqlAlchemyAccountAccessStore.replace_grants`) and the step-up service faked too."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from types import SimpleNamespace
from typing import Any

import pytest
import structlog
import yaml
from fastapi.testclient import TestClient
from pydantic import SecretStr

import candleviewer.app as appmod
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.settings import Settings
from candleviewer.storage.repositories import account_access as aa
from candleviewer.storage.repositories.account_access_sqlalchemy import SqlAlchemyAccountAccessStore
from candleviewer.storage.repositories.identity_sqlalchemy import SqlAlchemyIdentityProvider
from candleviewer.storage.repositories.scope_sqlalchemy import SqlAlchemyScopeSource
from candleviewer.ws.limits import MACHINE_ENTRIES_MAX
from tests.contract.rbac import rbac_harness as rbac
from tests.csrf_helpers import csrf_headers

_MATRIX: dict[str, Any] = yaml.safe_load(rbac.MATRIX_PATH.read_text(encoding="utf-8"))
_TOPICS: dict[str, dict[str, Any]] = _MATRIX["topics"]
#: `bars` and `footprint` take a `BarBuilderSet` lease whose build reads the real tape store on
#: this backend (I/O). Their check is the same `marketdata:read` decision as `book` or `trades`.
_LEASED = frozenset({"bars", "footprint"})
FAMILIES = tuple(sorted(set(_TOPICS) - _LEASED))
#: `machines.*` rows are scoped by entity, not by an `exchange_account_ids` option.
ACCOUNT_SCOPED = tuple(
    f for f in FAMILIES if _TOPICS[f]["scope"] == "granted_accounts" and "." not in f
)
UNLISTED = uuid.UUID("00000000-0000-4000-8000-00000000000c")  # in no `user_account_access` row
_WS_TIMEOUT_S = 5.0


def _delegate(target: Any, name: str) -> Callable[..., Any]:
    return lambda _self, *args, **kwargs: getattr(target, name)(*args, **kwargs)


class _Grants:
    """`load_grants` over the pack's actors. The pack's source returns rows for the owner too,
    so the loader's "an owner's empty grants mean every account" rule is exercised. `withdrawn`
    empties a user's rows, as removing their access would; `held` replaces them, and
    `replace_grants` (the store's commit) writes it."""

    def __init__(self) -> None:
        self._source = rbac._ScopeSource(rbac.load_contract())
        self.withdrawn: set[uuid.UUID] = set()
        self.held: dict[uuid.UUID, tuple[uuid.UUID, ...]] = {}

    async def load_grants(self, owner: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]:
        if owner in self.held:
            return [(account, True, False) for account in self.held[owner]]
        return [] if owner in self.withdrawn else await self._source.load_grants(owner)

    async def replace_grants(self, user_id: uuid.UUID, grants: Any, **kw: Any) -> Any:
        before: dict[uuid.UUID, aa.AccessLevel] = {
            a: "read" for a, *_ in await self.load_grants(user_id)
        }
        granted = tuple(aa.AccessGrant(a, "read", "acct", "demo") for a in grants)
        change = aa.AccessChange(user_id, before, dict(grants), granted=granted)
        if change.removed and kw["removal"].blocks_removal:
            raise aa.AccessPositionsUnknownError(str(user_id))
        self.held[user_id] = tuple(grants)
        return change


@pytest.fixture(scope="module")
def deployed() -> Iterator[SimpleNamespace]:
    identity, grants = rbac._Identity(rbac.load_contract()), _Grants()
    real = Settings(
        storage_backend="real",
        auth_pepper=SecretStr("test-pepper"),
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
        allowed_origins=rbac.WS_ORIGIN,
        # One app serves every parametrised socket below, so one actor connects far more than 20
        # times a minute. The per-user connect rate (#2558) is not under test here.
        ws_max_auths_per_user_per_min=600,
    )
    with pytest.MonkeyPatch.context() as mp:
        for name in ("user", "session_info"):
            mp.setattr(SqlAlchemyIdentityProvider, name, _delegate(identity, name))
        mp.setattr(SqlAlchemyScopeSource, "load_grants", _delegate(grants, "load_grants"))
        mp.setattr(
            SqlAlchemyAccountAccessStore, "replace_grants", _delegate(grants, "replace_grants")
        )
        app = appmod.create_app(real)  # nothing injected: the deployed composition
        ctx = app.state.app_context
        ctx.audit._writer = rbac._AuditSink()  # `ws.subscribe.denied` is audited
        ctx.auth._sessions, ctx.auth._step_up = rbac._Sessions(), rbac._StepUp()
        yield SimpleNamespace(app=app, grants=grants)


def _client(app: Any) -> TestClient:
    return TestClient(app, client=("127.0.0.1", 50000), headers={"origin": rbac.WS_ORIGIN})


def _recv(ws: Any) -> dict[str, Any]:
    """`receive_json` with a deadline, so a missing frame fails instead of hanging the suite."""
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        frame: dict[str, Any] = pool.submit(ws.receive_json).result(timeout=_WS_TIMEOUT_S)
    except FutureTimeout:
        pytest.fail(f"no WS frame within {_WS_TIMEOUT_S}s")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return frame


def _open(ws: Any, actor: str) -> dict[str, Any] | None:
    """`hello`, then `auth` unless `actor` is unauthenticated. Returns the `auth` reply."""
    ws.send_json({"t": "hello", "id": "h"})
    assert _recv(ws)["t"] == "welcome"
    if actor == "unauthenticated":
        return None
    ws.send_json({"t": "auth", "id": "a", "p": {"access_token": rbac.token_of(actor)}})
    return _recv(ws)


def _sub(ws: Any, ch: str, account: uuid.UUID | None) -> str:
    """`sub_ok` when accepted, else the refusal's error code."""
    entry: dict[str, Any] = {"ch": ch}
    if account is not None:
        entry["opts"] = {"exchange_account_ids": [str(account)]}
    ws.send_json({"t": "sub", "id": ch, "p": {"topics": [entry]}})
    frame = _recv(ws)
    if frame["t"] != "sub_ok":
        return str(frame["p"]["code"])
    result = frame["p"]["results"][0]
    return "sub_ok" if result["ok"] else str(result["error"]["code"])


def _subscribe_once(app: Any, actor: str, ch: str, account: uuid.UUID | None) -> str:
    with _client(app).websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        reply = _open(ws, actor)
        assert reply is None or reply["t"] == "auth_ok", reply
        return _sub(ws, ch, account)


@pytest.mark.parametrize(
    ("family", "actor"),
    [pytest.param(f, a, id=f"{f}|{a}") for f in FAMILIES for a in rbac.ACTORS],
)
def test_deployed_app_ws_sub_answers_as_the_matrix_says(
    deployed: SimpleNamespace, family: str, actor: str
) -> None:
    row = _TOPICS[family]
    account = rbac.GRANTED if family in ACCOUNT_SCOPED else None
    if family.startswith("machines."):
        rbac.seed_machine(deployed.app, row, actor)
    observed = _subscribe_once(deployed.app, actor, row["sample"], account)
    assert observed == row["outcomes"][actor], (family, actor)


@pytest.mark.parametrize("family", ACCOUNT_SCOPED)
def test_granted_manager_is_refused_an_account_it_holds_no_grant_for(
    deployed: SimpleNamespace, family: str
) -> None:
    sample = _TOPICS[family]["sample"]
    observed = _subscribe_once(deployed.app, "manager_with_grant", sample, rbac.FOREIGN)
    assert observed == "account_scope_denied"


@pytest.mark.parametrize("family", ACCOUNT_SCOPED)
def test_owner_sees_an_account_no_grant_row_lists(deployed: SimpleNamespace, family: str) -> None:
    sample = _TOPICS[family]["sample"]
    assert _subscribe_once(deployed.app, "owner", sample, UNLISTED) == "sub_ok"


def test_deployed_app_caps_the_machine_registry(deployed: SimpleNamespace) -> None:
    assert deployed.app.state.ws_registry.services.machines.max_entries == MACHINE_ENTRIES_MAX


def test_deployed_app_snaps_a_machine_from_the_registry_sub_reads(
    deployed: SimpleNamespace,
) -> None:
    """The snapshot router serves the registry `sub` was authorised against (§6.4)."""
    row = _TOPICS["machines.kill_switch"]
    rbac.seed_machine(deployed.app, row, "owner")
    with _client(deployed.app).websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        _open(ws, "owner")
        assert _sub(ws, row["sample"], None) == "sub_ok"
        snap = _recv(ws)
    assert (snap["t"], snap["p"]) == ("snap", {"state": "seeded"})


def test_deployed_app_wakes_a_pending_machine_subscription(deployed: SimpleNamespace) -> None:
    """A registry publish reaches the socket through the hub the gateway registered it with."""
    row = _TOPICS["machines.kill_switch"]
    deployed.app.state.ws_registry.services.machines._entries.clear()
    with (
        _client(deployed.app) as client,
        client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws,
    ):
        _open(ws, "owner")
        assert _sub(ws, row["sample"], None) == "sub_ok"
        assert client.portal is not None  # set while the client context is open
        client.portal.call(rbac.seed_machine, deployed.app, row, "owner")
        snap = _recv(ws)
    assert (snap["t"], snap["meta"]["reason"]) == ("snap", "initial")


def test_auth_ok_carries_the_principal_read_from_the_store(deployed: SimpleNamespace) -> None:
    spec = rbac.load_contract()
    bodies: dict[str, dict[str, Any]] = {}
    for actor in ("owner", "manager_with_grant"):
        with _client(deployed.app).websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
            reply = _open(ws, actor)
        assert reply is not None and reply["t"] == "auth_ok", reply
        bodies[actor] = reply["p"]
        assert bodies[actor]["roles"] == [rbac.ROLE_OF[actor]]
        assert bodies[actor]["permissions"] == sorted(rbac.actor_permissions(actor, spec))
    assert bodies["manager_with_grant"]["account_scope"] == [str(rbac.GRANTED)]
    assert bodies["owner"]["account_scope"] == []  # empty means every account


def test_withdrawn_grant_revokes_the_live_subscription(deployed: SimpleNamespace) -> None:
    """`WsEvents.grants_changed` re-reads the store, so the `orders` subscription is revoked."""
    manager = rbac.user_id_of("manager_with_grant")
    with (
        _client(deployed.app) as client,
        client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws,
    ):
        reply = _open(ws, "manager_with_grant")
        assert reply is not None and reply["t"] == "auth_ok", reply
        assert _sub(ws, "orders", rbac.GRANTED) == "sub_ok"
        deployed.grants.withdrawn.add(manager)
        try:
            portal = client.portal
            assert portal is not None  # set while the client context is open
            portal.call(deployed.app.state.ws_events.grants_changed, manager)
            change, revoked = _recv(ws), _recv(ws)
        finally:
            deployed.grants.withdrawn.discard(manager)
        assert _sub(ws, "orders", rbac.GRANTED) == "account_scope_denied"
    assert change["t"] == "permission_change"
    assert (revoked["t"], revoked["ch"]) == ("revoked", "orders")
    assert revoked["p"]["reason"] == "account_scope_changed"


@pytest.fixture
def held(deployed: SimpleNamespace) -> Iterator[dict[uuid.UUID, tuple[uuid.UUID, ...]]]:
    """The grants a test writes through the owner's PUT are undone."""
    try:
        yield deployed.grants.held
    finally:
        deployed.grants.held.clear()


def _owner_puts(app: Any, client: TestClient, user: uuid.UUID, *accounts: uuid.UUID) -> None:
    """The owner's PUT, step-up live, acknowledging that open positions are unknown."""
    csrf = csrf_headers(app.state.csrf_codec, uuid.uuid5(rbac.user_id_of("owner"), "session"))
    body = {"grants": [{"exchange_account_id": str(a), "level": "read"} for a in accounts]}
    path = f"/users/{user}/account-access?acknowledge_unknown_positions=true"
    r = client.put(path, json=body, headers={"Authorization": "Bearer tok-owner"} | csrf)
    assert r.status_code == 200 and len(r.json()["items"]) == len(accounts), r.text


def test_revoked_frame_within_2s(deployed: SimpleNamespace, held: Any) -> None:
    """AC3 through the owner's PUT: the push ends inside the request's wait (`PUSH_WAIT_S`, 2 s,
    pinned in tests/unit/admin/test_account_access_service.py), so the `revoked` frame is sent
    before the 200 and the resubscribe is refused."""
    manager = rbac.user_id_of("manager_with_grant")
    with (
        _client(deployed.app) as client,
        client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws,
    ):
        _open(ws, "manager_with_grant")
        assert _sub(ws, "positions", rbac.GRANTED) == "sub_ok"
        with structlog.testing.capture_logs() as logs:
            _owner_puts(deployed.app, client, manager)
        change, revoked = _recv(ws), _recv(ws)
        assert _sub(ws, "positions", rbac.GRANTED) == "account_scope_denied"  # the resubscribe
    assert change["t"] == "permission_change"
    assert (revoked["t"], revoked["ch"]) == ("revoked", "positions")
    assert revoked["p"]["reason"] == "account_scope_changed"  # never `unsubscribed`
    # Logged before the 200, and no `timeout`: the push ended within the request's wait.
    assert [e["outcome"] for e in logs if e["event"] == "account access push"] == ["pushed"]


def test_resubscribe_scope_denied(deployed: SimpleNamespace, held: Any) -> None:
    """AC3 on a new socket too: its principal is read from the store the PUT wrote."""
    _owner_puts(deployed.app, _client(deployed.app), rbac.user_id_of("manager_with_grant"))
    observed = _subscribe_once(deployed.app, "manager_with_grant", "executions", rbac.GRANTED)
    assert observed == "account_scope_denied"


def test_other_subscriptions_and_other_managers_unaffected(
    deployed: SimpleNamespace, held: dict[uuid.UUID, tuple[uuid.UUID, ...]]
) -> None:
    """I6, I7: M holds S and T; removing S revokes M's S subscription only (T goes on and can be
    subscribed again), and N, who also holds S, gets no frame and keeps it."""
    m, n = rbac.user_id_of("manager_with_grant"), rbac.user_id_of("manager_without_grant")
    s, t = rbac.GRANTED, rbac.FOREIGN
    held.update({m: (s, t), n: (s,)})
    with (
        _client(deployed.app) as client,
        client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws_m,
        client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws_n,
    ):
        _open(ws_m, "manager_with_grant")
        _open(ws_n, "manager_without_grant")
        assert [_sub(ws_m, "positions", s), _sub(ws_m, "orders", t)] == ["sub_ok"] * 2
        assert _sub(ws_n, "positions", s) == "sub_ok"
        _owner_puts(deployed.app, client, m, t)
        change, revoked = _recv(ws_m), _recv(ws_m)
        assert _sub(ws_m, "positions", s) == "account_scope_denied"
        assert _sub(ws_m, "wallet", t) == "sub_ok"  # the next frame: `orders` was not revoked
        assert _sub(ws_n, "orders", s) == "sub_ok"  # N's next frame is this reply: nothing pushed
    assert change["t"] == "permission_change"
    assert (revoked["ch"], revoked["p"]["removed_accounts"]) == ("positions", [str(s)])


def test_fake_backend_keeps_the_deny_all_principal() -> None:
    owner = rbac.user_id_of("owner")
    app = appmod.create_app(Settings())
    snap = asyncio.run(app.state.ws_registry.resolve(owner))
    assert snap.principal == PrincipalSnapshot(owner, frozenset(), frozenset())
    assert snap.version >= 1


def test_the_derived_families_cover_the_issue_scope() -> None:
    """Guard for the derived parametrisation: it can never silently become empty."""
    assert {"orders", "positions", "wallet", "executions"} <= set(ACCOUNT_SCOPED)
    assert {"alerts", "recorder", "book", "trades", "ticker"} <= set(FAMILIES)
