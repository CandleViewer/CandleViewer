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

On `storage_backend="real"`, `StorageService.start()` builds one for the storage
module (`storage.real_tiers`, #3874). Callers that need only the relational tier
also construct their own via `SqlAlchemyRelationalRepository(dsn, suffix)` (the
`0002_rbac_seed` re-seed job, the auth, admin and accounts wiring in `app.py`).
"""

from __future__ import annotations

import re
from types import SimpleNamespace, TracebackType

from sqlalchemy import exc as sa_exc
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from candleviewer.storage.errors import (
    StorageConstraintViolated,
    StorageQueryFailed,
    StorageTierUnavailable,
)

_STATEMENT_TIMEOUT_MS = 30_000
_SQLSTATE = re.compile(r"[0-9A-Z]{5}")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]{0,62}")
#: Driver exceptions carry the server's message and `DETAIL` (`Failing row contains (...)`,
#: `Key (col)=(val)`): a stripped chain drops every link of theirs (#2748).
_DRIVER_PACKAGES = frozenset({"asyncpg", "psycopg", "psycopg2"})
#: A driver error's own text fields (asyncpg's, its statement `query` included, and the adapted
#: error's `detail`).
_DRIVER_TEXT = ("message", "detail", "hint", "context", "internal_query", "query")
#: A `PendingRollbackError`'s message quotes the error that rolled the session back.
_ROLLED_BACK = "this session's transaction was rolled back after an earlier error"


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


def _sources(exc: object) -> tuple[object, ...]:
    """Where a driver error's facts live: SQLAlchemy's `orig` (the adapted error), and asyncpg's
    own error behind it (`orig.orig`, or its `__cause__`)."""
    orig = getattr(exc, "orig", None)
    return orig, getattr(orig, "orig", None), getattr(orig, "__cause__", None)


def sqlstate_of(exc: object) -> str | None:
    """The SQLSTATE a database error reports, or None (a driver-side failure has none)."""
    codes = (getattr(src, key, None) for src in _sources(exc) for key in ("sqlstate", "pgcode"))
    return next((c for c in codes if isinstance(c, str) and _SQLSTATE.fullmatch(c)), None)


def constraint_of(exc: object) -> str | None:
    """The name of the constraint a database error reports, or None."""
    holders = (h for src in _sources(exc) for h in (src, getattr(src, "diag", None)))
    names = (getattr(h, "constraint_name", None) for h in holders)
    return next((n for n in names if isinstance(n, str) and _IDENTIFIER.fullmatch(n)), None)


def _is_driver(error: object) -> bool:
    """A driver's own error, or SQLAlchemy's emulation of one: their text is the server's."""
    return isinstance(error, sa_exc.EmulatedDBAPIException) or (
        type(error).__module__.split(".")[0] in _DRIVER_PACKAGES
    )


#: "Cannot serve this now, retry": the SQLSTATE classes and code `api.storage_outage` treats as an
#: outage (connection, rollback, resources, operator intervention, system; lock not available).
_OUTAGE_SQLSTATE_CLASSES = frozenset({"08", "40", "53", "57", "58"})
_LOCK_NOT_AVAILABLE = "55P03"


def is_outage(exc: BaseException) -> bool:
    """Whether *exc* means the database cannot serve the call now (a 503), as
    `api.storage_outage.is_storage_outage` classes it (`api` may not be imported here; a test
    pins the two equal, and their SQLSTATE classes). A typed `StorageTierUnavailable` is one."""
    if isinstance(exc, OSError | StorageTierUnavailable):
        return True
    if isinstance(exc, sa_exc.OperationalError | sa_exc.InterfaceError):
        return True
    if isinstance(exc, sa_exc.TimeoutError):  # the pool's checkout timeout
        return True
    if not isinstance(exc, sa_exc.DBAPIError):
        return False
    state = sqlstate_of(exc)
    return exc.connection_invalidated or (
        state is not None
        and (state[:2] in _OUTAGE_SQLSTATE_CLASSES or state == _LOCK_NOT_AVAILABLE)
    )


def query_failure(state: str | None, constraint: str | None) -> StorageQueryFailed:
    """The typed error for a statement the database refused, built from its facts alone (C-12.6):
    class 23 is `StorageConstraintViolated`, any other `StorageQueryFailed`. Raise it `from None`;
    pass `sqlstate_of(exc)` and `constraint_of(exc)`, never the error. A fact that is not a
    SQLSTATE or an identifier is dropped, so no text reaches the typed error's message."""
    state = state if isinstance(state, str) and _SQLSTATE.fullmatch(state) else None
    name = constraint if isinstance(constraint, str) and _IDENTIFIER.fullmatch(constraint) else None
    if state is not None and state.startswith("23"):
        return StorageConstraintViolated(state, name)
    return StorageQueryFailed(state)


class _DriverFacts(Exception):
    """A stripped error's `orig`: the SQLSTATE and constraint name, where every classifier in
    the adapters reads them (asyncpg's `sqlstate`, psycopg's `pgcode` and `diag`), and no text
    of the server's. `client` names the class of a failure raised before the database (a bind
    processor's `ValueError`), whose text can quote a bound value."""

    def __init__(
        self, state: str | None, constraint: str | None, client: str | None = None
    ) -> None:
        if client:
            super().__init__(f"{client} raised before the database")
        else:
            named = f", constraint {constraint}" if constraint else ""
            super().__init__(f"database error (sqlstate {state or 'unknown'}{named})")
        self.sqlstate = self.pgcode = state
        self.constraint_name = constraint
        self.client = client
        self.diag = self

    def __reduce__(
        self,
    ) -> tuple[type[_DriverFacts], tuple[str | None, str | None, str | None]]:
        return type(self), (self.sqlstate, self.constraint_name, self.client)


def _strip_unwrapped(error: BaseException) -> None:
    """A driver error raised as it is: keep its type, SQLSTATE and constraint name, read as
    `sqlstate_of` and `constraint_of` read a wrapped one (asyncpg's, psycopg's or an emulated
    error's); drop its message and text fields, its notes, and the driver error an emulated one
    wraps."""
    held = SimpleNamespace(orig=error)
    facts = _DriverFacts(sqlstate_of(held), constraint_of(held))
    error.args = (str(facts),)
    if isinstance(error, sa_exc.EmulatedDBAPIException):
        error.orig = facts
    for name in _DRIVER_TEXT:
        if getattr(error, name, None) is not None:
            setattr(error, name, None)
    if hasattr(error, "__notes__"):
        del error.__notes__


def strip_driver_text(exc: BaseException) -> None:
    """Remove the database server's text from *exc* and its chain, in place (#2748, C-12.6).

    Each SQLAlchemy `StatementError` in the graph keeps its type, `connection_invalidated`,
    SQLSTATE and constraint name, and loses its message, statement, parameters, driver error
    and chain. A driver error left unwrapped (*exc* itself or a group member) keeps its type
    and codes, and loses its text; a `PendingRollbackError` loses the text it quotes. Any other
    exception keeps its type and message, but loses chain links that are driver exceptions. In
    place, because `async with` re-raises this same object."""
    seen: set[int] = set()
    todo = [exc]
    while todo:
        node = todo.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, sa_exc.StatementError):
            orig = node.orig
            client: str | None = None
            if isinstance(orig, _DriverFacts):
                client = orig.client
            elif orig is not None and not _is_driver(orig):
                client = type(orig).__name__
            facts = _DriverFacts(sqlstate_of(node), constraint_of(node), client)
            node.args = (str(facts),)
            node.orig, node.statement, node.params, node.detail = facts, None, None, []
            node.__cause__ = node.__context__ = None
            node.__suppress_context__ = True
            if hasattr(node, "__notes__"):  # `add_note()` text can quote the server too
                del node.__notes__
            continue
        if _is_driver(node):  # *exc* itself or a group member: a link to one is cut below
            _strip_unwrapped(node)
        elif isinstance(node, sa_exc.PendingRollbackError):
            node.args = (_ROLLED_BACK,)
        if isinstance(node, BaseExceptionGroup):
            todo.extend(node.exceptions)
        for link in ("__cause__", "__context__"):
            linked = getattr(node, link)
            if linked is None:
                continue
            if _is_driver(linked):
                setattr(node, link, None)
            else:
                todo.append(linked)


class SqlAlchemyUnitOfWork:
    """Concrete `UnitOfWork`: one Postgres transaction, one commit point.

    `commit()`/`rollback()` are single-shot (raise on a second call) per the
    Protocol's documented invariant; `__aexit__` rolls back on any unhandled
    exception and is a no-op if `commit()` already ran. An exception leaving the unit of work
    leaves without the database server's text (`strip_driver_text`, #2748), its type and
    SQLSTATE kept, so every caller's classification holds.
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
        try:
            try:
                if exc is not None and not self._committed and not self._rolled_back:
                    await self.rollback()
            finally:
                await self._session.close()  # even when the rollback failed
        except BaseException as cleanup:  # the rollback or the close failed as well
            strip_driver_text(cleanup)
            if exc is not None and cleanup.__context__ is None:
                cleanup.__context__, cleanup.__suppress_context__ = exc, False
            raise
        finally:
            if exc is not None:
                strip_driver_text(exc)  # in place: `async with` re-raises this same object

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
        A start that fails closes the session and raises without the server's text; if the
        close fails too, its error keeps the start's failure as its context (#2748).
        """
        return _PendingUnitOfWork(self._sessionmaker, self._application_name_suffix)


class _PendingUnitOfWork:
    """Deferred `unit_of_work()` result — opens the session lazily on
    `__aenter__` so `RelationalRepository.unit_of_work()` stays a plain,
    non-async factory call per the Protocol's signature. A session that cannot
    start is closed here, since no unit of work is handed out to close it."""

    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], app_name_suffix: str
    ) -> None:
        self._sessionmaker = sessionmaker
        self._app_name_suffix = app_name_suffix
        self._uow: SqlAlchemyUnitOfWork | None = None

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        session = self._sessionmaker()
        try:
            connection = await session.connection()
            await connection.exec_driver_sql(
                f"SET LOCAL statement_timeout = '{_STATEMENT_TIMEOUT_MS}'"
            )
            await connection.exec_driver_sql(
                f"SET LOCAL application_name = 'candleviewer:{self._app_name_suffix}'"
            )
        except BaseException as failed:  # never handed out: close it here, or the pool waits on GC
            strip_driver_text(failed)
            try:
                await session.close()
            except BaseException as cleanup:  # the close failed as well
                strip_driver_text(cleanup)
                if cleanup.__context__ is None:  # the strip cuts it; keep the start's failure
                    cleanup.__context__, cleanup.__suppress_context__ = failed, False
                raise
            raise
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
