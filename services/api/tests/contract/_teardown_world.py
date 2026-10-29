"""The world of the account delete's and the key revoke's provider tests (E27-S04 B3c/B3d, #898).

The RBAC pack's real `create_app()` (no network, C-13.5) over B3b2's fake M13 store, extended with
each account's keys (their status), the soft delete and the key read as Postgres scopes them; the
real consequence read over fake ports that read the store's signable keys; the real
`AccountLifecycle` and `KeyRevoke` over the app's own key standing and WS events, with recording
stand-ins for M2's destroyer (it marks the key `revoked`, as M2's `mark_revoked` does), the rule
disarm and the private-stream close. Every effect lands in one ordered log (`Effects.log`).
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

import candleviewer.app as appmod
from candleviewer.accounts.consequences import ConsequenceRead
from candleviewer.accounts.errors import AccountNotFoundError
from candleviewer.accounts.exposure import ExposureRead
from candleviewer.accounts.key_revoke import KeyRevoke
from candleviewer.accounts.lifecycle import AccountLifecycle
from candleviewer.accounts.models import ApiKeyMetadata, ExchangeAccount, KeyStatus
from candleviewer.audit.writer import keyed_record_id
from candleviewer.exchange.base.errors import PrivateStreamCloseOverran
from candleviewer.storage.repositories.accounts import ApiKeyRow, OwnerScope
from tests.contract._admin_support import SPEC, validate_example
from tests.contract.rbac.rbac_harness import FOREIGN, GRANTED, World, bearer, build_world
from tests.contract.test_update_exchange_account_provider import Effects as PatchEffects
from tests.contract.test_update_exchange_account_provider import Ports as PatchPorts
from tests.contract.test_update_exchange_account_provider import Store as PatchStore
from tests.unit.accounts.test_exposure_read import key
from tests.unit.accounts.test_key_import import key_row

KEY = uuid.UUID("00000000-0000-4000-8000-0000000000f1")
SECOND = uuid.UUID("00000000-0000-4000-8000-0000000000f2")
THEIRS = uuid.UUID("00000000-0000-4000-8000-0000000000f3")  # a key of the foreign account


class Store(PatchStore):
    """B3b2's store, with each account's keys and the soft delete; a deleted account is absent
    to every read, its keys too (`deleted_at IS NULL`, as the SQL reads)."""

    def reset(self) -> None:
        super().reset()
        self.deleted: set[uuid.UUID] = set()
        self.soft_deletes = 0
        self.keys: dict[uuid.UUID, dict[uuid.UUID, str]] = {
            GRANTED: {KEY: "active"}, FOREIGN: {THEIRS: "active"},
        }  # fmt: skip

    def row(self, account_id: uuid.UUID, key_id: uuid.UUID) -> ApiKeyRow:
        base = key_row(key_id, self.keys[account_id][key_id])
        return dataclasses.replace(base, exchange_account_id=account_id)

    async def get_account(self, scope: Any, account_id: uuid.UUID) -> Any:
        found = await super().get_account(scope, account_id)
        return None if account_id in self.deleted else found

    async def list_keys(self, scope: OwnerScope, account_id: uuid.UUID) -> tuple[ApiKeyRow, ...]:
        self._owner(scope)
        if account_id in self.deleted:
            return ()
        return tuple(self.row(account_id, k) for k in self.keys.get(account_id, {}))

    async def get_key(
        self, scope: OwnerScope, account_id: uuid.UUID, key_id: uuid.UUID
    ) -> ApiKeyRow | None:
        self._owner(scope)
        if account_id in self.deleted or key_id not in self.keys.get(account_id, {}):
            return None
        return self.row(account_id, key_id)

    async def soft_delete_account(self, scope: OwnerScope, account_id: uuid.UUID) -> bool:
        self._owner(scope)
        if account_id in self.deleted or account_id not in self.rows:
            return False
        self.deleted.add(account_id)
        self.rows[account_id] = dataclasses.replace(self.rows[account_id], is_enabled=False)
        self.soft_deletes += 1
        return True


class Ports(PatchPorts):
    """The consequence read's ports over the store's rows and live keys."""

    async def get_account(self, scope: Any, account_id: uuid.UUID) -> ExchangeAccount:
        if account_id in self.store.deleted:
            raise AccountNotFoundError("account")
        return await super().get_account(scope, account_id)

    async def list_keys(self, scope: Any, account_id: uuid.UUID) -> tuple[ApiKeyMetadata, ...]:
        held = self.store.keys.get(account_id, {})
        return tuple(key(k, KeyStatus(s), account=account_id) for k, s in held.items())


class Effects(PatchEffects):
    """B3b2's effect log, each hold naming its reason, plus M2's destroyer (it marks the key
    revoked in the store) and the standing's revoke hold."""

    def __init__(self, store: Store) -> None:
        self.store = store
        super().__init__()

    def reset(self) -> None:
        super().reset()
        self.destroy_fails: set[uuid.UUID] = set()
        self.closed: list[tuple[str, str]] = []
        self.revoked_ws: list[str] = []

    def hold(self, account_id: uuid.UUID, reason: Any) -> None:
        self.log.append(f"hold:{reason}")
        self.standings.hold(account_id, reason)

    def revoke(self, account_id: uuid.UUID, key_id: uuid.UUID) -> None:
        self.log.append("standing_revoke")
        self.standings.revoke(account_id, key_id)

    async def destroy(
        self, account_id: uuid.UUID, key_id: uuid.UUID, *, actor_user_id: str, actor_role: str
    ) -> None:
        self.log.append("destroy")
        if key_id in self.destroy_fails:
            raise RuntimeError("credential_unavailable")  # as M2 raises: never shown
        self.store.keys[account_id][key_id] = "revoked"

    async def account_revoked(self, account_id: uuid.UUID, reason: Any) -> int:
        self.revoked_ws.append(str(reason))
        return await super().account_revoked(account_id, reason)

    async def close_private_streams(self, key_ref: str, *, reason: Any) -> tuple[uuid.UUID, ...]:
        self.closed.append((key_ref, str(reason)))
        return await super().close_private_streams(key_ref, reason=reason)


@dataclasses.dataclass
class Served:
    world: World
    store: Store
    ports: Ports
    fx: Effects
    spends: list[str]
    lifecycle: list[AccountLifecycle]
    revoker: list[KeyRevoke]


@pytest.fixture(scope="module")
def _teardown() -> Iterator[Served]:
    store, mp = Store(), pytest.MonkeyPatch()
    ports, fx = Ports(store), Effects(store)
    built: list[AccountLifecycle] = []
    revokers: list[KeyRevoke] = []

    def consequences(*_args: Any, env: str) -> ConsequenceRead:
        return ConsequenceRead(ports, ExposureRead(ports, env=env), ports, ports, env=env)

    def lifecycle(accounts: Any, _rules: Any, *, standings: Any, subscriptions: Any,
                  **_kw: Any) -> AccountLifecycle:  # fmt: skip
        fx.standings, fx.ws = standings, subscriptions
        built.append(AccountLifecycle(
            accounts, fx, fx, fx, fx, count=fx.counted.append, destroyer=fx,
            count_deleted=lambda r: fx.counted.append(f"deleted:{r}"),
        ))  # fmt: skip
        return built[-1]

    def key_revoke(life: Any, _rules: Any, **_kw: Any) -> KeyRevoke:
        revokers.append(KeyRevoke(fx, fx, fx, fx, fx, locks=life.locks))
        return revokers[-1]

    try:
        mp.setattr(appmod, "_build_accounts_counts", lambda _settings: store)
        mp.setattr(appmod, "wire_consequence_read", consequences)
        mp.setattr(appmod, "wire_account_lifecycle", lifecycle)
        mp.setattr(appmod, "wire_key_revoke", key_revoke)
        world = build_world(mp)
        spends: list[str] = []
        consume = world.step_up.consume_single_use

        async def spending(session_id: str, action_class: str, *, fingerprint: str) -> Any:
            spent = await consume(session_id, action_class, fingerprint=fingerprint)
            spends.append(action_class)  # reached only when the grant was spent
            return spent

        mp.setattr(world.step_up, "consume_single_use", spending)

        async def emit_keyed(action: str, name: str, **kw: Any) -> None:
            """`AuditWriter.emit_keyed` as Postgres lands it: `ON CONFLICT (record_id) DO
            NOTHING`, so a second write of one record id stores nothing."""
            rid = keyed_record_id(action, name)
            if all(r.get("record_id") != rid for r in world.audit.records):
                world.audit.records.append({"action": action, "record_id": rid, **kw})

        mp.setattr(world.audit, "emit_keyed", emit_keyed, raising=False)
        yield Served(world, store, ports, fx, spends, built, revokers)
    finally:
        mp.undo()


@pytest.fixture
def served(_teardown: Served) -> Iterator[Served]:
    s = _teardown
    kept = dict(s.store.rows)
    s.world.audit.records.clear()
    s.world.step_up.elevated, s.world.step_up.classes = True, None
    for part in (s.store, s.ports, s.fx):
        part.reset()
    s.spends.clear()
    s.fx.standings.release(GRANTED)
    yield s
    s.store.rows.clear()
    s.store.rows.update(kept)
    s.fx.standings.release(GRANTED)
    s.fx.standings._state = dataclasses.replace(s.fx.standings._state, holds={})


def send(
    s: Served, method: str, path: str, *, actor: str = "owner", choice: str | None = None,
    key: str | None = None,
) -> httpx.Response:  # fmt: skip
    headers = bearer(actor) | ({} if key is None else {"Idempotency-Key": key})
    params = {} if choice is None else {"open_exposure": choice}
    resp: httpx.Response = s.world.client.request(method, path, params=params, headers=headers)
    return resp


def answer(resp: httpx.Response, path: str, method: str = "delete") -> Any:
    """The body (None for a `204`), once it validates against what 22 declares for its status."""
    status = resp.status_code
    declared = SPEC["paths"][path][method]["responses"][str(status)]
    if status == 204:
        assert resp.text == "" and "content" not in declared
        return None
    own = "#/paths/" + path.replace("/", "~1") + f"/{method}/responses/{status}"
    pointer = declared.get("$ref", own)
    validate_example(f"{pointer.removeprefix('#')}/content/application~1problem+json/schema",
                     resp.json())  # fmt: skip
    return resp.json()


def records(s: Served, action: str) -> list[dict[str, Any]]:
    return [r for r in s.world.audit.records if r["action"] == action]


def overran() -> PrivateStreamCloseOverran:
    return PrivateStreamCloseOverran((GRANTED,))
