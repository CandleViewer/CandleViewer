"""Parity of the M10 stores' private Postgres error mapping (#3973, from #3961's lens CR-2B2-04).

`orders_sqlalchemy`, `account_profiles_sqlalchemy` and `trade_groups_sqlalchemy` each carry a copy
of `_constraints()`, the constraint-name reader and the not-serving SQLSTATE set. One corpus of
fake driver errors runs through all three; each error must classify the same way. Only the shared
parts are compared: the SQLSTATE class, the name reader and the `WriteAheadTimeout` pass-through.
The store-specific rule and conflict name sets are not, so a name hit uses each store's own name.

Fake drivers only (the shapes asyncpg and psycopg give SQLAlchemy); no network, no sleeps.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from types import SimpleNamespace
from typing import Any, Final, NamedTuple

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

from candleviewer.storage.errors import (
    StorageQueryFailed,
    StorageTierUnavailable,
    WriteAheadTimeout,
)
from candleviewer.storage.repositories import account_profiles_sqlalchemy as profiles_mod
from candleviewer.storage.repositories import orders_sqlalchemy as orders_mod
from candleviewer.storage.repositories import trade_groups_sqlalchemy as groups_mod


class _Store(NamedTuple):
    label: str
    mod: Any
    hit_name: str  # a name this store maps to a named refusal (its own rule or conflict set)


_STORES: Final = (
    _Store("orders", orders_mod, "any_constraint"),  # orders names every constraint it is given
    _Store("account_profiles", profiles_mod, "ux_ap_name"),
    _Store("trade_groups", groups_mod, "ux_tg_creator_ref"),
)
_MODS: Final = tuple(s.mod for s in _STORES)

#: The union of every copy's not-serving set, spelled out so a copy that grows one fails below.
_NOT_SERVING_CORPUS: Final = ("57P01", "57P02", "57P03", "53300")


class _Named(Exception):
    """A chained driver error carrying the name (a `__cause__` must be an exception)."""

    def __init__(self, name: str | None) -> None:
        super().__init__("chained")
        self.constraint_name = name


class _Driver(Exception):
    def __init__(self, sqlstate: str | None, *, name: str | None = None, where: str = "attr"):
        super().__init__("driver refusal\nDETAIL:  Failing row contains (secret-value)")
        self.sqlstate = sqlstate
        if where == "attr":
            self.constraint_name = name
        elif where == "diag":  # psycopg's spelling: the name only on `.diag`
            self.diag = SimpleNamespace(constraint_name=name)
        elif where == "cause":  # asyncpg's wrapper chains the real error
            self.__cause__ = _Named(name)
        elif where == "driver_exception":  # SQLAlchemy's asyncpg adapter
            self.driver_exception = SimpleNamespace(constraint_name=name)
        else:  # pragma: no cover
            raise AssertionError(where)


def _dbapi(
    cls: type[DBAPIError], state: str | None, name: str | None = None, where: str = "attr"
) -> DBAPIError:
    return cls("STMT", {"p": "secret-value"}, _Driver(state, name=name, where=where))


def _invalidated() -> DBAPIError:
    err = _dbapi(OperationalError, None)
    err.connection_invalidated = True
    return err


class _HookError(RuntimeError):
    """What a write-ahead hook itself raises: not the database's, so it passes untouched."""


class _Case(NamedTuple):
    id: str
    build: Callable[[str], BaseException]  # takes the store's hit name
    marks: tuple[Any, ...] = ()
    reader_only: bool = False  # an unlisted name: each store's own name set decides, not shared


def _fixed(cls: type[DBAPIError], state: str) -> Callable[[str], BaseException]:
    return lambda _name: _dbapi(cls, state)


def _named(cls: type[DBAPIError], state: str) -> Callable[[str], BaseException]:
    return lambda name: _dbapi(cls, state, name)


_CASES: Final[tuple[_Case, ...]] = (
    *(_Case(f"not-serving-{s}", _fixed(OperationalError, s)) for s in _NOT_SERVING_CORPUS),
    # In none of the not-serving sets: a query failure, not an outage.
    _Case("other-40001", lambda n: _dbapi(OperationalError, "40001")),
    _Case("other-XX000", lambda n: _dbapi(OperationalError, "XX000")),
    _Case("other-42P01", lambda n: _dbapi(OperationalError, "42P01")),
    _Case("no-sqlstate", lambda n: _dbapi(OperationalError, None)),
    # The 08 class and a dropped connection are outages whatever the SQLSTATE.
    _Case("class-08-08006", lambda n: _dbapi(OperationalError, "08006")),
    _Case("class-08-08001", lambda n: _dbapi(OperationalError, "08001")),
    _Case("connection-invalidated", lambda n: _invalidated()),
    # A name reader hit and a miss, on each violation class.
    *(_Case(f"hit-{s}", _named(IntegrityError, s)) for s in ("23505", "23514", "23503")),
    _Case("miss-no-name-23505", lambda n: _dbapi(IntegrityError, "23505", None)),
    _Case(
        "unlisted-name-23505",
        lambda n: _dbapi(IntegrityError, "23505", "zz_unknown"),
        reader_only=True,
    ),
    _Case("miss-name-on-other-sqlstate", lambda n: _dbapi(IntegrityError, "40001", n)),
    _Case("miss-not-null-23502", lambda n: _dbapi(IntegrityError, "23502", n)),
    # Where the driver puts the name.
    _Case("hit-via-cause", lambda n: _dbapi(IntegrityError, "23505", n, "cause")),
    _Case(
        "hit-via-driver-exception", lambda n: _dbapi(IntegrityError, "23505", n, "driver_exception")
    ),
    _Case("hit-via-diag", lambda n: _dbapi(IntegrityError, "23505", n, "diag")),
    # Pass-through and non-DBAPI errors.
    _Case("write-ahead-timeout", lambda n: WriteAheadTimeout()),
    _Case("hook-error", lambda n: _HookError("hook refused")),
    _Case("raw-os-error", lambda n: ConnectionResetError("reset")),
    _Case("pool-timeout", lambda n: sa.exc.TimeoutError("pool exhausted")),
)


def _classify(mod: Any, store: _Store, error: BaseException) -> tuple[str, str | None]:
    """What the store's `_constraints()` leaves a driver error as: (kind, detail)."""
    ctx: AbstractContextManager[None] = mod._constraints()
    try:
        with ctx:
            raise error
    except StorageTierUnavailable as out:
        assert out.__cause__ is None and out.__suppress_context__  # never chained (C-12.6)
        return "tier-unavailable", str(out)
    except StorageQueryFailed as out:
        assert out.__cause__ is None and out.__suppress_context__
        return "query-failed", out.sqlstate
    except WriteAheadTimeout as out:
        assert out is error  # passes as it is
        return "write-ahead-timeout", None
    except Exception as out:
        if out is error:  # anything else (a hook's own error) passes as it is
            return "pass-through", type(out).__name__
        assert out.__cause__ is None and out.__suppress_context__
        name = getattr(out, "constraint", None) or getattr(out, "rule", None)
        assert name is not None, f"unexpected {type(out).__name__}"
        return "named", str(name)  # the store's own named refusal
    return "none", None


def _is_named(kind: str) -> bool:
    return kind == "named"


_PARAMS_CLASSIFY: Final = [
    pytest.param(c, id=c.id, marks=c.marks) for c in _CASES if not c.reader_only
]


@pytest.mark.parametrize("case", _PARAMS_CLASSIFY)
def test_constraints_classify_a_driver_error_the_same_in_every_store(case: _Case) -> None:
    results = []
    for store in _STORES:
        kind, detail = _classify(store.mod, store, case.build(store.hit_name))
        # A named refusal carries the store's own name; compare that it is the one given.
        results.append(
            ("named", "hit") if _is_named(kind) and detail == store.hit_name else (kind, detail)
        )
        if _is_named(kind):
            assert detail == store.hit_name, f"{store.label} named {detail!r}"
    assert results[0] == results[1] == results[2], dict(
        zip((s.label for s in _STORES), results, strict=True)
    )


_PARAMS_READER: Final = [
    pytest.param(c, id=c.id, marks=c.marks) for c in _CASES if isinstance(c.build("x"), DBAPIError)
]


@pytest.mark.parametrize("case", _PARAMS_READER)
def test_the_constraint_reader_finds_the_same_name_in_every_store(case: _Case) -> None:
    error = case.build("any_constraint")
    assert isinstance(error, DBAPIError)
    names = [s.mod._violated_constraint(error) for s in _STORES]
    assert names[0] == names[1] == names[2], dict(
        zip((s.label for s in _STORES), names, strict=True)
    )


def test_the_not_serving_sets_are_equal_and_the_corpus_covers_their_union() -> None:
    sets = [m._NOT_SERVING for m in _MODS]
    assert sets[0] == sets[1] == sets[2]
    assert frozenset().union(*sets) == frozenset(_NOT_SERVING_CORPUS)


def test_the_named_violation_sets_are_equal() -> None:
    sets = [m._NAMED_VIOLATIONS for m in _MODS]
    assert sets[0] == sets[1] == sets[2]


def test_the_corpus_has_the_cases_the_ticket_names() -> None:
    ids = {c.id for c in _CASES}
    assert {
        "write-ahead-timeout",
        "hook-error",
        "miss-no-name-23505",
        "hit-23505",
        "other-XX000",
    } <= ids
    assert len(_CASES) >= 20
