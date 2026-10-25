"""`SqlAlchemySessionLock` (#913 slice 3 L2, SEC-S3N-01) over a fake engine whose server keeps
session advisory locks as Postgres does: `pg_try_advisory_lock` never waits and a session's lock
goes with the session. One holder per key; a lock not got keeps nothing; a release ends its
session whatever the unlock did; a lock that cannot be asked keeps nothing and says only so. The
real statements run in `tests/integration/oms/test_environment_lock_pg.py`."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories import session_lock_sqlalchemy as module
from candleviewer.storage.repositories.session_lock_sqlalchemy import SqlAlchemySessionLock

KEY, OTHER = -0x1234_5678_9ABC_DEF0, 0x0FED_CBA9_8765_4321


class Server:
    """Session advisory locks by key, each held by one session (a connection) at most."""

    def __init__(self) -> None:
        self.holders: dict[int, Connection] = {}
        self.fail: str | None = None  # the statement that fails next ("try" or "unlock")
        self.hang = False  # the pool gives no connection

    def ended(self, session: Connection) -> None:
        self.holders = {k: s for k, s in self.holders.items() if s is not session}


class Result:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar(self) -> object:
        return self._value


class Connection:
    def __init__(self, server: Server) -> None:
        self.server, self.calls = server, list[str]()

    async def execute(self, statement: Any, params: Mapping[str, int]) -> Result:
        text = str(statement)
        kind = "try" if "pg_try_advisory_lock(:key)" in text else "unlock"
        assert text in (str(module._TRY), str(module._UNLOCK))  # bound, never formatted
        self.calls.append(kind)
        if self.server.fail == kind:
            raise RuntimeError(f"server text that must not leave: {params}")
        key, holders = params["key"], self.server.holders
        if kind == "try":
            got = holders.setdefault(key, self) is self
            return Result(got)
        return Result(holders.pop(key, None) is self)

    async def commit(self) -> None:
        self.calls.append("commit")

    async def invalidate(self) -> None:
        self.calls.append("invalidate")
        self.server.ended(self)

    async def close(self) -> None:
        self.calls.append("close")


class Engine:
    def __init__(self, server: Server) -> None:
        self.server, self.opened = server, list[Connection]()

    async def connect(self) -> Connection:
        if self.server.hang:
            await asyncio.Event().wait()
        self.opened.append(Connection(self.server))
        return self.opened[-1]


def _lock(engine: Engine, key: int = KEY, timeout_s: float = 5.0) -> SqlAlchemySessionLock:
    return SqlAlchemySessionLock(cast(AsyncEngine, engine), key, timeout_s=timeout_s)


async def test_one_session_holds_a_key_and_a_second_gets_none_until_it_is_released() -> None:
    server = Server()
    first, second = Engine(server), Engine(server)
    held, refused = _lock(first), _lock(second)
    assert await held.acquire() and held.held
    assert not await refused.acquire() and not refused.held
    assert second.opened[0].calls == ["try", "commit", "close"]  # back to its pool, nothing kept
    assert await _lock(Engine(server), OTHER).acquire()  # another environment's key: its own
    await held.release()
    assert first.opened[0].calls == ["try", "commit", "unlock", "commit", "invalidate", "close"]
    assert not held.held and await refused.acquire()
    await held.release()  # not held: nothing


async def test_a_release_whose_unlock_fails_ends_the_session_and_with_it_the_lock() -> None:
    server = Server()
    engine = Engine(server)
    held = _lock(engine)
    assert await held.acquire()
    server.fail = "unlock"
    with pytest.raises(RuntimeError):
        await held.release()
    assert engine.opened[0].calls[-2:] == ["invalidate", "close"]
    server.fail = None
    assert await _lock(Engine(server)).acquire()  # the session ended: the lock went with it


async def test_a_lock_that_cannot_be_asked_keeps_nothing_and_says_so_without_server_text() -> None:
    server = Server()
    server.fail = "try"
    engine = Engine(server)
    lock = _lock(engine)
    with pytest.raises(StorageTierUnavailable) as failed:
        await lock.acquire()
    assert "server text" not in str(failed.value) and failed.value.__cause__ is None
    assert engine.opened[0].calls == ["try", "invalidate", "close"] and not lock.held
    server.fail, server.hang = None, True
    with pytest.raises(StorageTierUnavailable):
        await _lock(Engine(server), timeout_s=0.0).acquire()
    server.hang = False
    assert await lock.acquire()
    with pytest.raises(RuntimeError, match="held already"):
        await lock.acquire()
