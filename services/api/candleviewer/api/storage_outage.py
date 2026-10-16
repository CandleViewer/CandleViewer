"""Shared classifier for storage outages on HTTP routes (#2478).

Same semantics as `_is_outage` in `api/workspaces.py` (E15-T01); `/workspaces` adopts this
helper in a follow-up on the E15 train. Imports no route module.
"""

from typing import Final

from candleviewer.storage.errors import StorageTierUnavailable

#: Driver errors that mean "the database is unreachable or timed out". `api` may not import a
#: storage driver (ADR-0003), so they are recognised by class identity, not imported; the
#: repository does not translate them (S3). Integrity/Programming/Data errors are bugs: 500.
_OUTAGE_CLASSES: Final = frozenset(
    {
        "sqlalchemy.exc.OperationalError",
        "sqlalchemy.exc.InterfaceError",
        "sqlalchemy.exc.TimeoutError",  # pool checkout timeout
    }
)
_DBAPI_ERROR: Final = "sqlalchemy.exc.DBAPIError"


#: SQLSTATE classes that mean "the database cannot serve this now, retry": connection (08),
#: transaction rollback incl. deadlock/serialization (40), resources (53), operator
#: intervention incl. statement timeout 57014 (57), system (58); plus lock_not_available 55P03.
#: Data (22), integrity (23) and syntax/access (42) errors are bugs: 500. Anything else, and a
#: missing SQLSTATE, stays 500 so it fails visibly.
_OUTAGE_SQLSTATE_CLASSES: Final = frozenset({"08", "40", "53", "57", "58"})


def _sqlstate(exc: Exception) -> str | None:
    """The SQLSTATE a DBAPI error carries, read like the repository's `map_integrity`: the
    wrapped driver error (`orig`), then its cause; `.sqlstate` (asyncpg) or `.pgcode`."""
    orig = getattr(exc, "orig", None)
    for src in (orig, getattr(orig, "__cause__", None), exc.__cause__):
        for attr in ("sqlstate", "pgcode"):
            code = getattr(src, attr, None)
            if isinstance(code, str) and len(code) == 5:
                return code
    return None


def is_storage_outage(exc: Exception) -> bool:
    """True when `exc` means the store is unreachable or timed out (route: 503, not 500)."""
    if isinstance(exc, OSError | StorageTierUnavailable):
        return True
    names = {f"{c.__module__}.{c.__qualname__}" for c in type(exc).__mro__}
    if names & _OUTAGE_CLASSES:
        return True
    if _DBAPI_ERROR not in names:
        return False
    if getattr(exc, "connection_invalidated", False) is True:
        return True
    state = _sqlstate(exc)  # a generic DBAPIError: real timeouts and deadlocks arrive this way
    return state is not None and (state[:2] in _OUTAGE_SQLSTATE_CLASSES or state == "55P03")
