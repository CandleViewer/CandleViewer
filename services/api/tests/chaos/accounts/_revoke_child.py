"""A cv-api stand-in for #898's key-revoke chaos (E27-S04 B3e): it revokes one stored key over
Postgres with M2's real broker and the revoke's real effects in their order, and parks inside the
close of the key's private streams, after the destroy committed (the key fenced, recorded, its row
`revoked`) and before the close completed; it says so on stdout and waits for its SIGKILL. The
parent's order (the DSN and the ids) comes on stdin, never in argv, the environment or a file. No
network: the stream closer is a stand-in that never dials.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from datetime import datetime
from typing import Any
from uuid import UUID

from candleviewer.accounts.key_revoke import KeyRevoke, completion
from candleviewer.accounts.locks import AccountLocks
from candleviewer.secrets import KeyDestroyer
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets._rotation import RotatingBroker
from candleviewer.storage.repositories.credentials_sqlalchemy import SqlAlchemyCredentialStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)


def say(line: str) -> None:
    sys.stdout.write(f"@@ {line}\n")
    sys.stdout.flush()


def kek() -> LoadedKek:
    """The parent's fixed test KEK (never a real one): the seeded key's DEK is wrapped under it."""
    return LoadedKek(bytearray(range(32)), 1, env_name="demo")


async def _sink(action: str, fields: dict[str, str]) -> None:
    say(f"m2 {action}")


class Effects:
    """The standing, the WS revoke and the disarm as no-ops that log; the close parks."""

    def revoke(self, account_id: UUID, key_id: UUID) -> None:
        say("standing_revoke")

    async def account_revoked(self, account_id: UUID, reason: Any) -> int:
        say("ws")
        return 0

    async def disarm(self, account_id: UUID, **_kw: Any) -> None:
        say("disarm")

    async def close_private_streams(self, key_ref: str, *, reason: Any) -> tuple[UUID, ...]:
        say("parked close")
        threading.Event().wait()  # until SIGKILL: the close never completes
        return ()

    def hold(self, account_id: UUID, reason: Any) -> None:  # unused by a revoke
        raise AssertionError

    def release(self, account_id: UUID) -> bool:  # unused by a revoke
        raise AssertionError

    def reopen_private_streams(self, key_ref: str, *, reason: Any) -> bool:  # unused
        raise AssertionError


async def main() -> None:
    order = json.loads(sys.stdin.readline())
    rel = SqlAlchemyRelationalRepository(order["dsn"], "revoke-chaos-child")
    broker = RotatingBroker(SqlAlchemyCredentialStore(rel), _sink, kek())
    account, key_id, actor = UUID(order["account"]), UUID(order["key"]), UUID(order["owner"])

    async def destroy(acct: UUID, key: UUID, user: str, role: str) -> None:
        await broker.destroy(key, actor=("user", role, user), account_id=acct)

    fx = Effects()
    revoker = KeyRevoke(fx, fx, fx, fx, KeyDestroyer(destroy), locks=AccountLocks(),
                        clock=lambda: datetime.fromisoformat(order["at"]))  # fmt: skip
    payload = completion(account, choice=None, last=True)
    await revoker.revoke(account, key_id, last=True, payload=payload, actor=actor, role="owner")


if __name__ == "__main__":
    asyncio.run(main())
