"""Integration (E28-Q01, #904): `tests/fixtures/e28/seed.sql` on a migrated Postgres 16.

The seed loads as one command sends it, and its world is the plan's: six accounts in two
environments and no API key, each demo account defaulting to its E28 profile exactly as
`profile_values` stores it, two definitions and the groups fired from them with their legs (each
snapshot its profile), E28-B's failing key self-check and E28-A's one open position. A second run
writes nothing, and a database not named for tests is refused. Needs Docker (testcontainers); CI
`integration` runs it.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql

from candleviewer.accounts.profiles import AccountProfile, profile_values
from candleviewer.storage.repositories.account_profiles import LadderRung
from tests.integration import _refused

pytestmark = pytest.mark.integration

pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16, migrated; its database is named `test`
_E28 = Path(__file__).resolve().parents[5] / "tests" / "fixtures" / "e28"
_FROZEN = Path(__file__).resolve().parents[2] / "fixtures" / "profiles"
Conn = psycopg.Connection[tuple[Any, ...]]
#: Every table the seed writes or one of its triggers fills.
_TABLES = (
    "users user_roles exchange_accounts account_profiles account_profile_revisions positions"
    " trade_group_definitions trade_group_definition_members trade_groups trade_group_legs"
).split()


def _profiles() -> dict[str, AccountProfile]:
    spec = json.loads((_E28 / "profiles.json").read_text(encoding="utf-8"))
    out = {}
    for entry in spec.values():
        frozen = json.loads((_FROZEN / entry["from"]).read_text(encoding="utf-8"))
        profile = AccountProfile.model_validate(frozen | entry["set"])
        out[str(profile.profile_id)] = profile
    return out


def _dsn(pg_dsn: str, database: str = "test") -> str:
    return pg_dsn.replace("postgresql+asyncpg", "postgresql").rsplit("/", 1)[0] + "/" + database


def _counts(conn: Conn) -> dict[str, tuple[Any, ...] | None]:
    count = sql.SQL("SELECT count(*) FROM {}")
    return {t: conn.execute(count.format(sql.Identifier(t))).fetchone() for t in _TABLES}


@pytest.fixture(scope="module")
def db(pg_dsn: str) -> Iterator[Conn]:
    with psycopg.connect(_dsn(pg_dsn), autocommit=True) as conn:
        conn.execute((_E28 / "seed.sql").read_bytes())  # the file's own BEGIN ... COMMIT
        yield conn


def test_six_accounts_in_two_environments_and_no_api_key(db: Conn) -> None:
    query = (
        "SELECT env::text, kind::text, count(*) FROM exchange_accounts GROUP BY 1, 2 ORDER BY 1, 2"
    )
    want = [("demo", "main", 1), ("demo", "sub", 3), ("live", "main", 1), ("live", "sub", 1)]
    assert db.execute(query).fetchall() == want
    assert db.execute("SELECT count(*) FROM api_keys").fetchone() == (0,)


def test_each_demo_account_defaults_to_its_profile_as_stored(db: Conn) -> None:
    for profile_id, profile in _profiles().items():
        stored = profile_values(profile)
        names = [f.name for f in dataclasses.fields(stored)]
        columns = sql.SQL(", ").join(map(sql.Identifier, names))
        query = sql.SQL(
            "SELECT {} FROM account_profiles"
            " WHERE id = %s AND is_default AND deleted_at IS NULL AND version = 1"
        ).format(columns)
        row = db.execute(query, (profile_id,)).fetchone()
        assert row is not None, profile.name
        for name, value in zip(names, row, strict=True):
            if name == "tp_ladder" and value:  # jsonb numbers, as trg_ap_ladder_sum reads them
                value = [
                    LadderRung(pct=Decimal(str(r["pct"])), r=Decimal(str(r["r"]))) for r in value
                ]
            assert (tuple(value) if isinstance(value, list) else value) == getattr(stored, name)
    live = db.execute(
        "SELECT a.env::text, p.name FROM account_profiles p JOIN exchange_accounts a"
        " ON a.id = p.exchange_account_id WHERE p.deleted_at IS NULL ORDER BY 1, 2"
    )
    ours = sorted(p.name for p in _profiles().values())  # the live accounts keep their bootstrap
    assert live.fetchall() == [("demo", n) for n in ours] + [("live", "Default")] * 2


def test_the_definitions_groups_and_legs(db: Conn) -> None:
    members = db.execute(
        "SELECT d.name, count(*) FROM trade_group_definition_members m"
        " JOIN trade_group_definitions d ON d.id = m.definition_id GROUP BY 1 ORDER BY 1"
    )
    assert members.fetchall() == [("Core3", 3), ("Pair", 2)]
    legs = db.execute(
        "SELECT d.name, g.status::text, l.account_profile_id::text, l.profile_snapshot"
        " FROM trade_group_legs l JOIN trade_groups g ON g.id = l.trade_group_id"
        " JOIN trade_group_definitions d ON d.id = g.definition_id ORDER BY 1, l.sequence_no"
    ).fetchall()
    assert [(n, s) for n, s, _, _ in legs] == [("Core3", "cancelled")] * 2 + [
        ("Pair", "cancelled")
    ] * 2
    profiles = _profiles()
    assert all(AccountProfile.model_validate(snap) == profiles[p] for _, _, p, snap in legs)


def test_the_failing_self_check_and_the_open_position(db: Conn) -> None:
    disarmed = db.execute(
        "SELECT label, trading_enabled, policy_disarm_code, policy_disarm_audited_at"
        " FROM exchange_accounts WHERE policy_disarm_code IS NOT NULL"
    )
    assert disarmed.fetchall() == [("fx-e28-demo-b", False, "key_ip_whitelist_mismatch", None)]
    held = db.execute(
        "SELECT a.label, p.symbol::text, p.side, p.size, p.stop_loss FROM positions p"
        " JOIN exchange_accounts a ON a.id = p.exchange_account_id WHERE p.size > 0"
    )
    assert held.fetchall() == [
        ("fx-e28-demo-a", "BTCUSDT", "Buy", Decimal("0.001"), Decimal("63080.00"))
    ]


def test_a_second_run_writes_nothing(db: Conn, pg_dsn: str) -> None:
    before = _counts(db)
    with psycopg.connect(_dsn(pg_dsn), autocommit=True) as again:
        with pytest.raises(psycopg.errors.UniqueViolation):  # its first row's key is taken
            again.execute((_E28 / "seed.sql").read_bytes())
    assert _counts(db) == before


def test_a_database_not_named_for_tests_is_refused(db: Conn, pg_dsn: str) -> None:
    db.execute("DROP DATABASE IF EXISTS e28_other")
    db.execute("CREATE DATABASE e28_other")
    with psycopg.connect(_dsn(pg_dsn, "e28_other"), autocommit=True) as other:
        with pytest.raises(psycopg.errors.RaiseException, match="not a test database"):
            other.execute((_E28 / "seed.sql").read_bytes())
