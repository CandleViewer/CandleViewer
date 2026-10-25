"""`SqlAlchemySessionLock` (#913 slice 3 L2, SEC-S3N-01) over a fake engine whose server keeps
session advisory locks as Postgres does: `pg_try_advisory_lock` never waits and a session's lock
goes with the session. One holder per key; a lock not got keeps nothing; a held one sets its
session's keepalives (CR-S3L2-03); `confirm` answers whether the session still holds it; a release
ends its session whatever the unlock did, after the pool's dispose too (CR-S3L2-06); a lock that
cannot be asked, or whose ask is cut short, keeps nothing and says only so (CR-S3L2-05). The real
statements run in `tests/integration/oms/test_environment_lock_pg.py`."""

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
#: Each literal statement the lock sends, by the name the fake server knows it by.
STATEMENTS = {
    str(module._TRY): "try",
    str(module._KEEPALIVE): "keepalive",
    str(module._HELD): "held",
    str(module._UNLOCK): "unlock",
}
#: A bound on each of the tests' waits, never a time they expect.
BOUND_S = 10.0


class Server:
    """Session advisory locks by key, each held by one session (a connection) at most."""

    def __init__(self) -> None:
        self.holders: dict[int, Connection] = {}
        self.fail: str | None = None  # the statement that fails next
        self.hang: str | None = None  # the statement that never answers, once it has run
        self.connect_hangs = False  # the pool gives no connection

    def ended(self, session: Connection) -> None:
        self.holders = {k: s for k, s in self.holders.items() if s is not session}


class Result:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar(self) -> object:
        return self._value


def _key(params: Mapping[str, int]) -> int:
    """The signed 64-bit key a `pg_locks` probe names by its two unsigned 32-bit halves."""
    unsigned = (params["high"] << 32) | params["low"]
    return unsigned - (1 << 64) if unsigned >= 1 << 63 else unsigned


class Connection:
    def __init__(self, server: Server) -> None:
        self.server, self.calls = server, list[str]()
        self.settings: dict[str, str] = {}
        self.ended = False

    async def execute(self, statement: Any, params: Mapping[str, Any]) -> Result:
        kind = STATEMENTS[str(statement)]  # bound, never formatted: one of the lock's literals
        self.calls.append(kind)
        server = self.server
        if self.ended or server.fail == kind:
            raise RuntimeError(f"server text that must not leave: {dict(params)}")
        if kind == "try":
            got = server.holders.setdefault(params["key"], self) is self
            answer: object = got
        elif kind == "keepalive":
            self.settings = dict(params)
            answer = None
        elif kind == "held":
            answer = server.holders.get(_key(params)) is self
        else:
            answer = server.holders.pop(params["key"], None) is self
        if server.hang == kind:
            await asyncio.Event().wait()
        return Result(answer)

    async def commit(self) -> None:
        self.calls.append("commit")

    async def invalidate(self) -> None:
        self.calls.append("invalidate")
        self.ended = True
        self.server.ended(self)

    async def close(self) -> None:
        self.calls.append("close")


class Engine:
    def __init__(self, server: Server) -> None:
        self.server, self.opened, self.disposed = server, list[Connection](), False

    async def connect(self) -> Connection:
        if self.server.connect_hangs:
            await asyncio.Event().wait()
        self.opened.append(Connection(self.server))
        return self.opened[-1]

    async def dispose(self) -> None:
        """As SQLAlchemy's: the pool's checked-in connections close, a checked-out one stays."""
        self.disposed = True


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
    assert first.opened[0].calls == [
        "try", "keepalive", "commit", "unlock", "commit", "invalidate", "close"
    ]  # fmt: skip
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


async def test_a_held_lock_sets_its_sessions_keepalives_and_a_refused_one_none() -> None:
    """CR-S3L2-03: the server's TCP keepalives on the holder's session, so Postgres ends a dead
    holder's session, and its lock, within `STALE_HOLDER_S`; a session that got no lock goes back
    to its pool as it came."""
    server = Server()
    engine, other = Engine(server), Engine(server)
    assert await _lock(engine).acquire() and not await _lock(other).acquire()
    assert engine.opened[0].settings == module.KEEPALIVE
    idle, interval, count = (int(module.KEEPALIVE[k]) for k in ("idle", "interval", "count"))
    assert idle + interval * count == module.STALE_HOLDER_S
    assert int(module.KEEPALIVE["user_timeout"]) == 1000 * module.STALE_HOLDER_S
    assert "keepalive" not in other.opened[0].calls


async def test_a_lock_whose_keepalives_fail_ends_its_session_and_holds_nothing() -> None:
    """CR-S3L2-03: never held without its keepalives: the session that took the lock ends, and the
    lock with it, and the failure says only that it could not be asked."""
    server = Server()
    server.fail, engine = "keepalive", Engine(server)
    lock = _lock(engine)
    with pytest.raises(StorageTierUnavailable) as failed:
        await lock.acquire()
    assert "server text" not in str(failed.value) and failed.value.__cause__ is None
    assert engine.opened[0].calls == ["try", "keepalive", "invalidate", "close"]
    assert not lock.held and server.holders == {}


async def test_a_lock_whose_statement_fails_keeps_nothing_and_says_so_without_server_text() -> None:
    """CR-S3L2-09: one behaviour: a refused ask keeps no connection and carries no server text."""
    server = Server()
    server.fail, engine = "try", Engine(server)
    lock = _lock(engine)
    with pytest.raises(StorageTierUnavailable) as failed:
        await lock.acquire()
    assert "server text" not in str(failed.value) and failed.value.__cause__ is None
    assert engine.opened[0].calls == ["try", "invalidate", "close"] and not lock.held


async def test_a_lock_the_pool_gives_no_connection_in_time_is_unavailable() -> None:
    server = Server()
    server.connect_hangs = True
    with pytest.raises(StorageTierUnavailable):
        await _lock(Engine(server), timeout_s=0.0).acquire()


async def test_a_lock_asked_again_after_a_failure_is_held() -> None:
    server = Server()
    server.fail, lock = "try", _lock(Engine(server))
    with pytest.raises(StorageTierUnavailable):
        await lock.acquire()
    server.fail = None
    assert await lock.acquire() and lock.held


async def test_a_lock_held_already_is_not_asked_again() -> None:
    server = Server()
    engine = Engine(server)
    lock = _lock(engine)
    assert await lock.acquire()
    with pytest.raises(RuntimeError, match="held already"):
        await lock.acquire()
    assert len(engine.opened) == 1


async def test_a_lock_whose_statement_never_answers_keeps_nothing_within_its_bound() -> None:
    """CR-S3L2-05: the statement's own bound, not only the connection's: a lock the server granted
    but whose answer never came is cut at `timeout_s`, its session ended, and so the lock too."""
    server = Server()
    server.hang, engine = "try", Engine(server)
    lock = _lock(engine, timeout_s=0.0)
    with pytest.raises(StorageTierUnavailable):
        await asyncio.wait_for(lock.acquire(), BOUND_S)
    assert engine.opened[0].calls == ["try", "invalidate", "close"]
    assert not lock.held and server.holders == {}


async def test_a_cancelled_acquire_ends_its_session_and_keeps_nothing() -> None:
    """CR-S3L2-05: an acquire cancelled after the server granted the lock, its answer not yet in:
    the cancellation propagates, its session ends, and the lock goes with it."""
    server = Server()
    server.hang, engine = "try", Engine(server)
    lock = _lock(engine)
    asking = asyncio.ensure_future(lock.acquire())
    for _ in range(8):  # the ask is sent and the server has granted it
        await asyncio.sleep(0)
    assert KEY in server.holders
    asking.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(asking, BOUND_S)
    assert engine.opened[0].calls == ["try", "invalidate", "close"]
    assert not lock.held and server.holders == {}


async def test_confirm_answers_true_while_the_session_holds_the_key() -> None:
    """CR-S3L2-03: the watchdog's probe, on the holder's own session: its `pg_locks` row, by the
    key's two halves."""
    server = Server()
    engine = Engine(server)
    lock = _lock(engine)
    assert await lock.acquire()
    assert await lock.confirm()
    assert engine.opened[0].calls[-2:] == ["held", "commit"]


async def test_confirm_answers_false_once_the_session_holds_it_no_more_or_none_is_held() -> None:
    server = Server()
    engine = Engine(server)
    lock = _lock(engine)
    assert not await lock.confirm() and engine.opened == []  # nothing held: nothing asked
    assert await lock.acquire()
    server.holders.clear()  # the key was given up on that session without this lock's release
    assert not await lock.confirm()


async def test_confirm_on_a_session_that_cannot_answer_is_unavailable_without_server_text() -> None:
    """CR-S3L2-03: an ended session, or one that does not answer within `timeout_s`: the caller
    cannot tell, so it is told so, never that the lock is held."""
    server = Server()
    lock = _lock(Engine(server), timeout_s=0.0)
    assert await lock.acquire()
    server.fail = "held"
    with pytest.raises(StorageTierUnavailable) as failed:
        await lock.confirm()
    assert "server text" not in str(failed.value) and failed.value.__cause__ is None
    server.fail, server.hang = None, "held"
    with pytest.raises(StorageTierUnavailable):
        await asyncio.wait_for(lock.confirm(), BOUND_S)


async def test_a_release_after_the_pools_dispose_still_unlocks_on_its_session() -> None:
    """CR-S3L2-06: the runtime's stop disposes of the OMS pool before it releases the lock; the
    dispose leaves the lock's checked-out connection open, so the release still unlocks on that
    session and then ends it."""
    server = Server()
    engine = Engine(server)
    lock = _lock(engine)
    assert await lock.acquire()
    await engine.dispose()
    await lock.release()
    assert engine.disposed and engine.opened[0].calls[-4:] == [
        "unlock", "commit", "invalidate", "close"
    ]  # fmt: skip
    assert server.holders == {} and await _lock(Engine(server)).acquire()
