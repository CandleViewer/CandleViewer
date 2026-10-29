"""#898 (E27-S04 B3e) chaos: SIGKILL between a key revoke's destroy and the close of the key's
private streams, then a restart (the ticket's test plan; 22 `revokeApiKey`; R7).

The CI `integration` job's chaos step runs it (`-m "chaos and integration"`) against the compose
Postgres, migrated. A child process (`_revoke_child`) revokes one stored key with M2's real broker
over Postgres and the revoke's real effects, and parks inside the close once the destroy has
committed; the parent kills it. After the "restart" (fresh objects, nothing carried over):

- the key reads `revoked` and M2 refuses to lend it (`credential_unavailable`, broker.py's row
  check), a fresh broker included, so no `auth` is ever signed with it;
- no stream reopens on it: the usable-key read that feeds the account's standing and the stream
  set no longer lists it, and M2 refuses the signing a stream's `auth` needs;
- a repeat through the real route answers `204` and lands `api_key.revoked` once; a second repeat
  answers `204` and the record is still there once (keyed, `ON CONFLICT DO NOTHING`).

Manual step (not automatable, SR-E27-06): CandleViewer never deletes a key on Bybit. After a
revoke, the Owner deletes the key in the Bybit dashboard (API management); until then it stays
valid at the exchange, though CandleViewer holds no usable copy of it.

Every wait is bounded and polls a condition; nothing sleeps.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import signal
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from candleviewer.accounts.key_age import KeyRotationPolicy
from candleviewer.accounts.key_revoke import KeyRevoke
from candleviewer.accounts.locks import AccountLocks
from candleviewer.accounts.repository import AccountsRepository
from candleviewer.api.exchange_keys import make_exchange_keys_router
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.secrets import KEY_ID_SLOT
from candleviewer.secrets._rotation import RotatingBroker
from candleviewer.secrets.errors import CredentialUnavailable
from candleviewer.secrets.secret import Secret
from candleviewer.storage.repositories.accounts_sqlalchemy import SqlAlchemyAccountsStore
from candleviewer.storage.repositories.credentials_sqlalchemy import SqlAlchemyCredentialStore
from candleviewer.storage.repositories.key_selfcheck_sqlalchemy import SqlAlchemyKeySelfCheckStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.chaos.accounts._revoke_child import kek
from tests.chaos.audit.test_lane_chaos import drained, running
from tests.chaos.storage import _stack as st

pytestmark = [pytest.mark.chaos, pytest.mark.integration]

API_DIR = Path(__file__).resolve().parents[3]  # services/api, the child's working directory
WAIT_S = 120.0
_SNAP: dict[str, Any] = {
    "fetched_at": "2026-10-28T00:00:00+00:00", "uid": "1",
    "permissions": {"ContractTrade": ["Order"], "Wallet": []},
}  # fmt: skip


@pytest.fixture(autouse=True)
async def _postgres_up() -> None:
    await st.ensure_up("postgres", st.pg_up)


async def fetch(query: str, *args: object) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(st.pg_dsn().replace("+asyncpg", "", 1), timeout=10)
    try:
        rows: list[asyncpg.Record] = await conn.fetch(query, *args, timeout=30)
        return rows
    finally:
        await conn.close()


async def _audit_noop(action: str, fields: dict[str, str]) -> None:
    return None


async def seeded(rel: SqlAlchemyRelationalRepository) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """An Owner, a demo account and one active key on it, stored by M2's real writer under the
    child's fixed test KEK: `(owner, account, key)`."""
    owner, account = uuid.uuid4(), uuid.uuid4()
    await fetch(
        "INSERT INTO users (id, email, username, display_name, password_hash, status) "
        "VALUES ($1, $2, $3, 'u', '$argon2id$x', 'active')",
        owner, f"{owner}@example.test", f"u{owner.hex[:12]}",
    )  # fmt: skip
    await fetch(
        "INSERT INTO user_roles (user_id, role_id) SELECT $1, id FROM roles WHERE name = 'owner'",
        owner,
    )
    labels = await fetch(
        "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
        "WHERE t.typname = 'exchange_code' LIMIT 1"
    )
    exchange = labels[0][0]
    await fetch(
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES ($1, $2::exchange_code, 'demo', 'main', $3, $4)",
        account, exchange, str(account.int % 10**12), f"chaos-{account.hex[:8]}",
    )  # fmt: skip
    broker = RotatingBroker(SqlAlchemyCredentialStore(rel), _audit_noop, kek())
    meta = await broker.store("demo", account, "k", Secret("KEY0CHAOSREVOKE1"), Secret("S"), _SNAP)
    await fetch("UPDATE api_keys SET status = 'active' WHERE id = $1", meta.key_id)
    return owner, account, meta.key_id


async def killed_in_the_close(order: dict[str, str]) -> list[str]:
    """Run `_revoke_child` until it parks in the close, then SIGKILL it; the lines it said."""
    child = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "tests.chaos.accounts._revoke_child", cwd=API_DIR,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )  # fmt: skip
    assert child.stdin is not None and child.stdout is not None
    child.stdin.write(json.dumps(order).encode() + b"\n")
    seen: list[str] = []
    try:
        async with asyncio.timeout(WAIT_S):
            await child.stdin.drain()
            while (line := (await child.stdout.readline()).decode()) != "@@ parked close\n":
                assert line, "the child ended before it parked:\n" + "".join(seen[-40:])
                seen.append(line)
    except TimeoutError:
        raise AssertionError("the child never parked:\n" + "".join(seen[-40:])) from None
    finally:
        with contextlib.suppress(ProcessLookupError):
            child.kill()
        await child.wait()
    assert child.returncode == -signal.SIGKILL
    return [line.removeprefix("@@ ").strip() for line in seen if line.startswith("@@ ")]


class _Owner:
    """The route's principal resolver: the seeded Owner, `keys:manage` held."""

    def __init__(self, owner: uuid.UUID) -> None:
        self.principal = PrincipalSnapshot(
            owner, frozenset({"owner"}), frozenset({Permission.KEYS_MANAGE})
        )

    def resolve(self, request: Any) -> PrincipalSnapshot:
        return self.principal


class _Nothing:
    """The ports a repeat never reaches before its close: refused if reached."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"a repeat reached {name}")


class _Effects:
    """After the restart: the standing and the WS as no-ops; the close returns at once (no stream
    is open on the key: a fresh registry has none, and nothing may open one)."""

    def revoke(self, account_id: uuid.UUID, key_id: uuid.UUID) -> None:
        return None

    async def account_revoked(self, account_id: uuid.UUID, reason: Any) -> int:
        return 0

    async def disarm(self, account_id: uuid.UUID, **_kw: Any) -> None:
        return None

    async def close_private_streams(self, key_ref: str, *, reason: Any) -> tuple[uuid.UUID, ...]:
        return ()


async def _admit(request: Any, text: Any) -> None:
    return None  # a live `keys` window (the step-up is not under test here)


async def test_a_revoke_killed_between_the_destroy_and_the_close_stays_revoked_after_restart(
    tmp_path: Path,
) -> None:
    rel = SqlAlchemyRelationalRepository(st.pg_dsn(), "revoke-chaos")
    try:
        owner, account, key_id = await seeded(rel)
        said = await killed_in_the_close({
            "dsn": st.pg_dsn(), "owner": str(owner), "account": str(account), "key": str(key_id),
            "at": datetime(2026, 10, 28, tzinfo=UTC).isoformat(),
        })  # fmt: skip
        assert said == ["m2 security.credential_destroyed", "standing_revoke", "ws", "disarm"]

        # -- after the restart: nothing carried over from the killed process --------------
        status = await fetch("SELECT status::text, revoked_at IS NOT NULL FROM api_keys "
                             "WHERE id = $1", key_id)  # fmt: skip
        assert [tuple(r) for r in status] == [("revoked", True)]
        fresh = RotatingBroker(SqlAlchemyCredentialStore(rel), _audit_noop, kek())
        handle = fresh.borrow_handle("exchange_adapter")
        with pytest.raises(CredentialUnavailable, match=r"^credential_unavailable$"):
            await handle.sign(key_id, (KEY_ID_SLOT,), purpose="sign_rest")
        with pytest.raises(CredentialUnavailable, match=r"^credential_unavailable$"):
            await handle.sign(key_id, (KEY_ID_SLOT,), purpose="sign_ws_auth")  # a stream's `auth`
        usable = await SqlAlchemyKeySelfCheckStore(rel, env="demo").targets()
        assert key_id not in {row.key_id for row in usable}  # no stream set lists it again

        async with running(tmp_path / "audit", b"\x07" * 32) as svc:
            fx = _Effects()
            revoker = KeyRevoke(fx, fx, fx, fx, _Nothing(), locks=AccountLocks())  # type: ignore[arg-type]  # a repeat never destroys
            app = FastAPI()
            app.include_router(make_exchange_keys_router(
                None, svc.writer, _Owner(owner), egress_ip=None, rotation=KeyRotationPolicy(),
                elevation=_admit, accounts=AccountsRepository(SqlAlchemyAccountsStore(rel)),
                revoker=revoker, consequences=_Nothing(),  # type: ignore[arg-type]  # unread
                environment="demo",
            ))  # fmt: skip
            transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
            target = f"/exchange-accounts/{account}/keys/{key_id}"
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                first, second = await client.delete(target), await client.delete(target)
            await drained(svc)
        assert (first.status_code, second.status_code) == (204, 204)
        rows = await fetch(
            "SELECT after_state FROM audit_log WHERE action = 'api_key.revoked' AND object_id = $1",
            str(key_id),
        )
        assert len(rows) == 1
        after = json.loads(rows[0]["after_state"])
        assert after["accounts_closed"] == [str(account)] and after["flattened"] is False
    finally:
        await rel.dispose()
