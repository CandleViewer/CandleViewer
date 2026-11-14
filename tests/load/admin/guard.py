"""E42-Q03 (#1216): the target guards of the admin perf harness [BQ-9].

The API target is the E27 load-target guard (`tests/load/accounts/guard.py`, loaded by path and
never copied): loopback or the compose service `api`, an exchange host refused first. Audit rows
are permanent (C-5.7), so this adds the two checks the admin harness needs:

- the database: a postgres URL on loopback or the compose service `postgres`, with no query (a
  `dbname=` or `host=` there would override the path), whose database is the one its dataset owns
  (`DATASETS`); each name ends `_test`, the fixture loaders' own rule (`seed.is_test_database`);
- the environment the API runs in: `testnet` or `demo`, never `live`.

Every refusal is a fixed message that never echoes a URL or a DSN (either can carry a password).
`tests/load/k6/admin/lib/guard.js` is k6's copy of the API target rule, the dataset names and the
environments; k6 never sees the DSN, so it checks only the name the driver passes. The harness
guard tests (`services/api/tests/chaos/admin/test_e42_harness_guards.py`) run both copies over
E27's target table and one table each of database names and environments. Stdlib only, no network:
the guard parses text and never resolves a name.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Final
from urllib.parse import urlsplit


def _e27() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "accounts" / "guard.py"
    spec = importlib.util.spec_from_file_location("cv_e27_load_guard", path)
    if spec is None or spec.loader is None:
        raise ImportError("the E27 load-target guard is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_E27: Final = _e27()
TargetRefused: Final[type[ValueError]] = _E27.TargetRefused

DB_HOSTS: Final = frozenset({"127.0.0.1", "localhost", "::1", "postgres"})
DB_SCHEMES: Final = frozenset({"postgresql", "postgresql+asyncpg"})
#: The database each dataset loads into [BQ-3]: a bulk set and a chained set never share one, and
#: neither is ever AUDIT-CORRUPT's (`fixtures/admin/README.md`, AUDIT-CORRUPT's own database).
DATASETS: Final = {"bulk": "admin_perf_test", "chained": "admin_perf1m_test"}
ENVIRONMENTS: Final = frozenset({"testnet", "demo"})


def check_target(base_url: str) -> str:
    """The API's base URL without a trailing slash, or `TargetRefused` (the E27 rule)."""
    return str(_E27.check_target(base_url))


def is_test_database(name: str) -> bool:
    """As `tests/fixtures/admin/seed.is_test_database`: `test`, or a name ending `_test`."""
    return name == "test" or name.endswith("_test")


def database_name(dsn: str) -> str:
    """The database a DSN names, or `TargetRefused` if it is not a loopback test database."""
    try:
        parts = urlsplit(dsn)
        host = parts.hostname or ""
        _ = parts.port  # a bad port raises ValueError here
    except ValueError:
        raise TargetRefused("the database URL is not valid") from None
    netloc = parts.netloc.lower()
    if netloc.count("@") > 1 or any(c in netloc for c in (",", "%40", "%2c")):
        raise TargetRefused("the database URL is not valid")
    if parts.scheme not in DB_SCHEMES or parts.query or parts.fragment:
        raise TargetRefused("the database must be a postgres URL with no query")
    if host not in DB_HOSTS:
        raise TargetRefused("the database must be loopback or the compose service `postgres`")
    name = parts.path.removeprefix("/")
    if "/" in name or not is_test_database(name):
        raise TargetRefused("the database must be a test database: audit rows are permanent")
    return name


def check_dataset(dsn: str, mode: str | None = None) -> str:
    """The database name if it is the one `mode`'s dataset owns (any of them when `mode` is
    None), or `TargetRefused`."""
    name = database_name(dsn)
    owned = DATASETS.values() if mode is None else [DATASETS.get(mode)]
    if name not in owned:
        raise TargetRefused("the database is not the one this dataset owns")
    return name


def check_environment(value: object) -> str:
    """`testnet` or `demo`, or `TargetRefused`: the harness never runs against `live`."""
    if value not in ENVIRONMENTS:
        raise TargetRefused("the API must run in testnet or demo, never live")
    return str(value)
