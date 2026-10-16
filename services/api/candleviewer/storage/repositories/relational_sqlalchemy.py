"""`SqlAlchemyUnitOfWork` / `SqlAlchemyRelationalRepository` — the concrete
Postgres implementation of the `UnitOfWork`/`RelationalRepository` Protocols
from `candleviewer.storage.repositories.relational` (E07-T01).

Async engine with `asyncpg`; pool sized `pool_size=10, max_overflow=5` per
the ticket's "Technical notes" (Sec.11.4 budgets Postgres at <=50 tx/s — a
larger pool is wasted memory on the target VPS profile). Every checked-out
connection sets `statement_timeout` and `application_name` so slow queries
are attributable on the SCR-142 panel (ticket "Technical notes"), via the
`"connect"` pool event below — this fires once per physical connection, not
once per checkout, which is why `SET` (not `SET LOCAL`) is used there; the
per-transaction `SET LOCAL` additionally applied in `unit_of_work()` is the
one that actually resets at each transaction boundary as intended.

Not wired into `StorageService.start()` — that construction site also owns
the QuestDB and cold-tier clients (E07-T03/T04, still unimplemented), and
`storage_backend="real"` is documented (ticket "Out of scope" is implicit
here: E07-T02's own scope is the relational tier only) to raise
`StorageTierUnavailable` until every tier has a real client. This module is
constructed directly by callers that only need the relational tier today
(the `0002_rbac_seed` re-seed job, forthcoming E09 auth-service code) via
`SqlAlchemyRelationalRepository(dsn)`.
"""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_STATEMENT_TIMEOUT_MS = 30_000


def _build_engine(dsn: str) -> AsyncEngine:
    # `application_name`/`statement_timeout` are applied per-`unit_of_work()`
    # via `SET LOCAL` (see `_PendingUnitOfWork.__aenter__`), not at connect
    # time — the DSN is constructed at runtime from `Settings.pg_dsn` with no
    # per-connection kwargs, and `SET LOCAL` resets cleanly at every
    # transaction boundary, which a connect-time `SET` would not.
    #
    # `hide_parameters=True`: `DBAPIError.__str__` otherwise renders the bound
    # parameters (`[parameters: ...]`), and bound values include P1 columns such
    # as `replay_sessions.bookmarks` (21 §12). This is the one engine builder for
    # every relational repository, so no exception chain they raise can carry
    # bound values into a log (C-12.6).
    return create_async_engine(
        dsn,
        pool_size=10,
        max_overflow=5,
        pool_pre_ping=True,
        hide_parameters=True,
    )


class SqlAlchemyUnitOfWork:
    """Concrete `UnitOfWork`: one Postgres transaction, one commit point.

    `commit()`/`rollback()` are single-shot (raise on a second call) per the
    Protocol's documented invariant; `__aexit__` rolls back on any unhandled
    exception and is a no-op if `commit()` already ran.
    """

    def __init__(self, session: AsyncSession, connection: AsyncConnection) -> None:
        self._session = session
        self._connection = connection
        self._committed = False
        self._rolled_back = False

    @property
    def session(self) -> AsyncSession:
        """The bound `AsyncSession` — aggregate repositories built on top of
        this UoW (`UserRepository` etc., owned by E09/E27/E29) read/write
        through this, never opening their own session."""
        return self._session

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None and not self._committed and not self._rolled_back:
            await self.rollback()
        await self._session.close()

    async def commit(self) -> None:
        if self._committed:
            raise RuntimeError("SqlAlchemyUnitOfWork.commit() called twice")
        if self._rolled_back:
            raise RuntimeError("SqlAlchemyUnitOfWork.commit() called after rollback()")
        await self._session.commit()
        self._committed = True

    async def rollback(self) -> None:
        if self._rolled_back:
            return
        await self._session.rollback()
        self._rolled_back = True


class SqlAlchemyRelationalRepository:
    """Concrete `RelationalRepository`: constructs one `AsyncEngine`
    (module-lifetime, per the pool-sizing rationale above) and hands out a
    fresh `SqlAlchemyUnitOfWork`/`AsyncSession` per call to `unit_of_work()`.
    """

    def __init__(self, dsn: str, application_name_suffix: str = "api") -> None:
        self._engine = _build_engine(dsn)
        self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False)
        self._application_name_suffix = application_name_suffix

    @property
    def engine(self) -> AsyncEngine:
        """The shared engine (E16-T06: the reaper's `PgAdvisoryRunLock` holds a connection)."""
        return self._engine

    async def dispose(self) -> None:
        """Release the pool. Call once at module `stop()`."""
        await self._engine.dispose()

    def unit_of_work(self) -> _PendingUnitOfWork:
        """Returns an async-context-manager factory: `async with
        repo.unit_of_work() as uow: ...` opens the session, sets the
        per-transaction `SET LOCAL statement_timeout`/`application_name`
        (ticket "Technical notes"), and yields the bound `SqlAlchemyUnitOfWork`.
        """
        return _PendingUnitOfWork(self._sessionmaker, self._application_name_suffix)


class _PendingUnitOfWork:
    """Deferred `unit_of_work()` result — opens the session lazily on
    `__aenter__` so `RelationalRepository.unit_of_work()` stays a plain,
    non-async factory call per the Protocol's signature."""

    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], app_name_suffix: str
    ) -> None:
        self._sessionmaker = sessionmaker
        self._app_name_suffix = app_name_suffix
        self._uow: SqlAlchemyUnitOfWork | None = None

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        session = self._sessionmaker()
        connection = await session.connection()
        await connection.exec_driver_sql(f"SET LOCAL statement_timeout = '{_STATEMENT_TIMEOUT_MS}'")
        await connection.exec_driver_sql(
            f"SET LOCAL application_name = 'candleviewer:{self._app_name_suffix}'"
        )
        self._uow = SqlAlchemyUnitOfWork(session, connection)
        return self._uow

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._uow is None:
            raise RuntimeError("_PendingUnitOfWork.__aexit__ called before __aenter__")
        await self._uow.__aexit__(exc_type, exc, tb)
