"""Integration: `0033_machine_persistence` on real Postgres 16 (E50-T61 #2744).

The migrated tables equal 24 Sec.17.6 built in a scratch schema, with their triggers, and every
column carries the classification comment `db.models` declares; an empty database migrated to the
parent round-trips with an identical schema dump; one row in any table refuses the downgrade by
name; `cv_app` cannot rewrite `machine_events` and the owning role is refused by its triggers; a
journal row is stamped once and `cv_app` never deletes it; every named CHECK refuses its invalid
row. `testcontainers`, CI-only (no docker socket here); run before the PR on a scratch Postgres
16.4 through a local stand-in.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import errors as pgerr
from psycopg import sql
from psycopg.types.json import Jsonb
from testcontainers.postgres import PostgresContainer

from candleviewer.db import models

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_REV = "0033_machine_persistence"
_NAMES = ("machine_snapshots", "machine_drain_journal", "machine_events")
_TEMPLATE = "mpersist_head"
_NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
_STAMP = "UPDATE machine_drain_journal SET replayed_at = %s WHERE send_id = %s"

Conn = psycopg.Connection[tuple[Any, ...]]


@cache
def _prev() -> str:
    """The parent, read from the revision itself, so re-parenting never touches this module."""
    revision = (_ROOT / "candleviewer" / "migrations" / "versions" / f"{_REV}.py").read_text(
        "utf-8"
    )
    found = re.search(r'^down_revision: str \| None = "(\w+)"$', revision, re.M)
    assert found is not None
    return found[1]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Bounded, so a lost `lock_timeout` fails the test instead of hanging it."""
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#2744)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ, "CV_PG_DSN": dsn}, capture_output=True, text=True,
        check=False, timeout=120,
    )  # fmt: skip


def _migrate(dsn: str, *args: str) -> None:
    done = _alembic(dsn, *args)
    assert done.returncode == 0, done.stderr


def _url(container: PostgresContainer) -> str:
    return container.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+psycopg", "postgresql"), autocommit=True)


def _database(dsn: str, name: str) -> str:
    return f"{dsn.rsplit('/', 1)[0]}/{name}"


def _create(dsn: str, template: str | None = None) -> tuple[str, str]:
    """A new database on the same server, empty or a copy of `template`: its DSN and its name."""
    name = f"mpersist_{uuid.uuid4().hex[:12]}"
    statement = sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
    if template is not None:
        statement += sql.SQL(" TEMPLATE {}").format(sql.Identifier(template))
    with _conn(_database(dsn, "postgres")) as c:
        c.execute(statement)
    return _database(dsn, name), name


@pytest.fixture(scope="module")
def pg() -> Iterator[PostgresContainer]:
    """Head, plus an untouched copy of it that `_create` clones for tests needing empty tables."""
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = _url(container)
        _migrate(dsn, "upgrade", "head")
        with _conn(_database(dsn, "postgres")) as c:
            c.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                    sql.Identifier(_TEMPLATE), sql.Identifier(dsn.rsplit("/", 1)[1])
                )
            )
        yield container


def _insert(c: Conn, table: str, row: dict[str, object]) -> dict[str, object]:
    c.execute(
        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, row)),
            sql.SQL(", ").join([sql.Placeholder()] * len(row)),
        ),
        tuple(row.values()),
    )
    return row


def _key() -> dict[str, object]:
    return {"machine_kind": "order", "entity_id": str(uuid.uuid4()), "env": "demo"}


def _snapshot(c: Conn, **cols: object) -> dict[str, object]:
    row = _key() | {"cv_schema_version": 2, "lib_snapshot_ver": 3, "machine_hash": "a" * 64}
    row |= {"snapshot": Jsonb({"value": "idle"}), "hmac_key_id": "k1", "hmac_tag": bytes(32)}
    return _insert(c, "machine_snapshots", row | {"state_ids": ["idle"], "updated_at": _NOW} | cols)


def _journal(c: Conn, **cols: object) -> dict[str, object]:
    row = _key() | {"send_id": uuid.uuid4().hex, "lane": "inbox", "ordinal": 0}
    row |= {"event_type": "SUBMIT", "payload": Jsonb({"type": "SUBMIT"})}
    return _insert(c, "machine_drain_journal", row | cols)


def _event(c: Conn, **cols: object) -> dict[str, object]:
    row = _key() | {"event_type": "SUBMIT", "payload": Jsonb({}), "from_states": ["idle"]}
    row |= {"to_states": ["pending"], "actions_run": [], "occurred_at": _NOW, "phase": "commit"}
    row |= {"prev_hash": "0" * 64, "row_hash": uuid.uuid4().hex * 2}
    return _insert(c, "machine_events", row | cols)


_ROW: dict[str, Callable[..., dict[str, object]]] = {
    "machine_snapshots": _snapshot,
    "machine_drain_journal": _journal,
    "machine_events": _event,
}

# --- The catalog equals 24 Sec.17.6, and the round trip leaves nothing behind -----------------

_CATALOG = (
    "SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, "
    "pg_get_expr(d.adbin, d.adrelid) FROM pg_attribute a LEFT JOIN pg_attrdef d "
    "ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
    "WHERE a.attrelid = %(t)s::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum",
    "SELECT conname, contype, pg_get_constraintdef(oid) FROM pg_constraint "
    "WHERE conrelid = %(t)s::regclass ORDER BY conname",
    "SELECT i.relname, pg_get_indexdef(i.oid) FROM pg_index x "
    "JOIN pg_class i ON i.oid = x.indexrelid WHERE x.indrelid = %(t)s::regclass ORDER BY 1",
)
#: `trg_mdj_stamp_once` fires ALWAYS (`A`), even under `session_replication_role = replica`.
_TRIGGERS = [
    (
        "machine_drain_journal", "trg_mdj_stamp_once", "A",
        "BEFORE UPDATE ON machine_drain_journal FOR EACH ROW "
        "EXECUTE FUNCTION machine_drain_journal_stamp_once()",
    ),
    (
        "machine_events", "trg_me_append", "O",
        "BEFORE DELETE OR UPDATE ON machine_events FOR EACH ROW EXECUTE FUNCTION forbid_mutation()",
    ),
    (
        "machine_events", "trg_me_no_truncate", "O",
        "BEFORE TRUNCATE ON machine_events FOR EACH STATEMENT "
        "EXECUTE FUNCTION audit_refuse_truncate()",
    ),
]  # fmt: skip


def _section_ddl() -> str:
    """24-internal-schemas.md Sec.17.6's ```sql block: the three tables and their indexes."""
    text = (_ROOT.parents[1] / "docs" / "plan" / "24-internal-schemas.md").read_text("utf-8")
    return text.split("\n### 17.6 ", 1)[1].split("```sql", 1)[1].split("```", 1)[0]


def _as_created(ddl: str) -> str:
    """The section's DDL as 0033 created it: the four columns the #3857 revision made `json`
    back to the `jsonb` they were created as."""
    created, altered = re.subn(
        r"^(  (?:snapshot|payload|fault) +)json\b", r"\1jsonb", ddl, flags=re.M
    )
    assert altered == 4, altered
    return created


def _catalog(c: Conn, schema: str) -> list[list[tuple[str, ...]]]:
    unqualify = re.compile(r"\b(?:public|doc_ref)\.")
    return [
        [
            tuple(unqualify.sub("", str(v)) for v in row)
            for row in c.execute(q, {"t": f"{schema}.{t}"})
        ]
        for t in _NAMES
        for q in _CATALOG
    ]


def _assert_matches_section(c: Conn, ddl: str | None = None) -> None:
    """Build the section's DDL (or `ddl`) in a scratch schema (rolled back) and diff the two
    catalogs: columns, types, nullability, defaults, CHECKs, keys and indexes."""
    got: list[list[tuple[str, ...]]] = []
    want: list[list[tuple[str, ...]]] = []
    with c.transaction():
        c.execute("CREATE SCHEMA doc_ref")
        c.execute("SET LOCAL search_path = doc_ref, public")
        c.execute((ddl or _section_ddl()).encode())
        got, want = _catalog(c, "public"), _catalog(c, "doc_ref")
        raise psycopg.Rollback
    assert got == want and all(got)


def test_schema_is_section_17_6_and_every_column_is_classified(pg: PostgresContainer) -> None:
    """Gherkins "24 Sec.17.6 is implementable as written" and "every column is classified"."""
    with _conn(_url(pg)) as c:
        _assert_matches_section(c)
        triggers = c.execute(
            "SELECT tgrelid::regclass::text, tgname, tgenabled, pg_get_triggerdef(oid) "
            "FROM pg_trigger WHERE tgrelid = ANY(%s::regclass[]) AND NOT tgisinternal "
            "ORDER BY 1, 2",
            (list(_NAMES),),
        ).fetchall()
        comments = c.execute(
            "SELECT attrelid::regclass::text, attname, col_description(attrelid, attnum) "
            "FROM pg_attribute WHERE attrelid = ANY(%s::regclass[]) AND attnum > 0",
            (list(_NAMES),),
        ).fetchall()
    defs = [(t, n, e, re.sub(r"^CREATE TRIGGER \w+ |\bpublic\.", "", d)) for t, n, e, d in triggers]
    assert defs == _TRIGGERS
    want = {(t, col.name): col.comment for t in _NAMES for col in getattr(models, t).columns}
    assert {(t, col): text for t, col, text in comments} == want
    assert all(str(text).startswith(("P0: ", "PII: ")) for text in want.values())


def _dump(pg: PostgresContainer, name: str) -> list[str]:
    """`pg_dump --schema-only` inside the container (the server's own client); a newer client's
    `\\restrict` key lines are random per dump."""
    code, out = pg.exec(["pg_dump", "-U", pg.username, "-d", name, "--schema-only"])
    assert code == 0, out.decode(errors="replace")[-2000:]
    return [
        line
        for line in out.decode().splitlines()
        if not line.startswith(("\\restrict ", "\\unrestrict "))
    ]


def test_round_trip_on_an_empty_database_restores_the_parent_schema(pg: PostgresContainer) -> None:
    """C-5.5, Gherkin "round trip on an empty database" (named revisions, so a later head cannot
    change what `-1` means): up, down and up again; the dump after the downgrade equals the dump
    before the upgrade; the tables match the section again, as 0033 created them."""
    dsn, name = _create(_url(pg))
    _migrate(dsn, "upgrade", _prev())
    before = _dump(pg, name)
    _migrate(dsn, "upgrade", _REV)
    _migrate(dsn, "downgrade", _prev())
    assert _dump(pg, name) == before and any("CREATE TABLE public.backups" in x for x in before)
    _migrate(dsn, "upgrade", _REV)
    with _conn(dsn) as c:
        _assert_matches_section(c, _as_created(_section_ddl()))


@pytest.mark.parametrize("name", _NAMES)
def test_downgrade_refuses_while_one_table_holds_a_row(pg: PostgresContainer, name: str) -> None:
    """Gherkin "a populated database refuses the downgrade": the refusal names the table, and
    nothing is dropped (C-5.2, C-5.7). The database starts at `0034_order_vocabulary`, the
    revision below #3857's, so 0034's downgrade runs first and 0033's guard is the one that
    answers; #3857's revision refuses a populated downgrade itself, ahead of both."""
    dsn, _ = _create(_url(pg))
    _migrate(dsn, "upgrade", "0034_order_vocabulary")
    count = sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(name))
    with _conn(dsn) as c:
        _ROW[name](c)
        head = c.execute("SELECT version_num FROM alembic_version").fetchone()
        refused = _alembic(dsn, "downgrade", _prev())
        assert refused.returncode != 0
        assert f"0033_machine_persistence downgrade refused: {name} holds rows;" in refused.stderr
        assert c.execute("SELECT version_num FROM alembic_version").fetchone() == head
        for table in _NAMES:
            assert c.execute("SELECT to_regclass(%s)::text", (table,)).fetchone() == (table,)
        assert c.execute(count).fetchone() == (1,)


# --- Privileges and triggers (24 Sec.17.6), on the CI `migrations` bootstrap ---------------------


@pytest.fixture(scope="module")
def boot() -> Iterator[str]:
    """`pg_bootstrap.sql` first, then the migrations as `cv_owner`: the CI `migrations` order, so
    the default privileges apply and the revision's grants meet real roles."""
    with PostgresContainer("postgres:16-alpine", dbname="candleviewer") as container:
        dsn = _url(container)
        info = psycopg.conninfo.conninfo_to_dict(dsn.replace("postgresql+psycopg", "postgresql"))
        psql = shutil.which("psql")
        assert psql is not None, "the CI jobs that run this module install postgresql-client"
        subprocess.run(  # noqa: S603 -- resolved absolute path, fixed argv, no shell (#2744)
            [psql, "-h", str(info["host"]), "-p", str(info["port"]), "-U", str(info["user"]),
             "-d", "candleviewer", "-v", "ON_ERROR_STOP=1", "-v", "owner_pw=cv_owner_test_pw",
             "-v", "app_pw=cv_app_test_pw", "-v", "ro_pw=cv_ro_test_pw",
             "-f", str(_ROOT.parents[1] / "infra" / "scripts" / "pg_bootstrap.sql")],
            check=True, capture_output=True, timeout=120,
            env={**os.environ, "PGPASSWORD": str(info["password"])},
        )  # fmt: skip
        _migrate(re.sub(r"://[^@]+@", "://cv_owner:cv_owner_test_pw@", dsn), "upgrade", "head")
        yield dsn


@contextmanager
def _as(dsn: str, role: str) -> Iterator[Conn]:
    """A session with the privileges of `role` (`SET ROLE`), as a login as it would have."""
    with _conn(dsn) as c:
        c.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
        yield c


def test_each_role_has_exactly_the_section_privileges(boot: str) -> None:
    privileges = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
    with _conn(boot) as c:
        got = {
            (role, table): [
                p
                for p in privileges
                if c.execute("SELECT has_table_privilege(%s, %s, %s)", (role, table, p)).fetchone()
                == (True,)
            ]
            for role in ("cv_app", "cv_ro")
            for table in _NAMES
        }
        columns = c.execute(
            "SELECT attname FROM pg_attribute WHERE attrelid = 'machine_drain_journal'::regclass "
            "AND attnum > 0 AND has_column_privilege('cv_app', attrelid, attnum, 'UPDATE')"
        ).fetchall()
    assert got == {
        ("cv_app", "machine_snapshots"): ["SELECT", "INSERT", "UPDATE"],
        ("cv_app", "machine_drain_journal"): ["SELECT", "INSERT"],
        ("cv_app", "machine_events"): ["SELECT", "INSERT"],
        ("cv_ro", "machine_snapshots"): ["SELECT"],
        ("cv_ro", "machine_drain_journal"): ["SELECT"],
        ("cv_ro", "machine_events"): ["SELECT"],
    }
    assert columns == [("replayed_at",)]


@pytest.mark.parametrize(
    "verb",
    [
        "UPDATE machine_events SET env = env",
        "DELETE FROM machine_events",
        "TRUNCATE machine_events",
    ],
)
def test_machine_events_is_append_only_for_cv_app_and_the_owner(boot: str, verb: str) -> None:
    """Gherkin "machine_events is append-only" (C-2.9, C-5.7): a row written as `cv_app`; the
    rewrite is insufficient_privilege for `cv_app` and refused by the triggers for the owner."""
    with _as(boot, "cv_app") as c:
        _event(c)
        with pytest.raises(pgerr.InsufficientPrivilege):
            c.execute(verb)
    with _as(boot, "cv_owner") as c, pytest.raises(pgerr.RaiseException) as refused:
        c.execute(verb)
    assert str(refused.value.diag.message_primary).startswith("table machine_events is append-only")


def test_a_journal_row_is_stamped_once_and_never_deleted_by_cv_app(boot: str) -> None:
    """Gherkin "a journal row is stamped once": the stamp succeeds (and may be written over
    itself); a reset, another value, another column and DELETE are refused."""
    with _as(boot, "cv_app") as c:
        send_id = str(_journal(c)["send_id"])
        c.execute(_STAMP, (_NOW, send_id))
        c.execute(_STAMP, (_NOW, send_id))
        for again in (None, _NOW + timedelta(seconds=1)):
            with pytest.raises(pgerr.CheckViolation) as refused:
                c.execute(_STAMP, (again, send_id))
            assert refused.value.diag.message_primary == (
                "trg_mdj_stamp_once: machine_drain_journal.replayed_at is set-once"
            )
        for verb in (
            "UPDATE machine_drain_journal SET lane = 'priority' WHERE send_id = %s",
            "DELETE FROM machine_drain_journal WHERE send_id = %s",
        ):
            with pytest.raises(pgerr.InsufficientPrivilege):
                c.execute(verb, (send_id,))
        row = c.execute(
            "SELECT replayed_at, lane FROM machine_drain_journal WHERE send_id = %s", (send_id,)
        ).fetchone()
    assert row == (_NOW, "inbox")


def test_the_owner_may_change_no_journal_column_but_the_stamp(boot: str) -> None:
    """`trg_mdj_stamp_once` binds the owning role too, naming the column, never a value."""
    changes: dict[str, object] = {
        "machine_kind": "leg", "entity_id": "other", "env": "live", "send_id": "0" * 32,
        "lane": "priority", "ordinal": 1, "event_type": "CANCEL", "payload": Jsonb({"x": 1}),
        "receipt_error": "InterpreterStoppedError",
    }  # fmt: skip
    with _as(boot, "cv_owner") as c:
        send_id = str(_journal(c)["send_id"])
        for column, value in changes.items():
            update = sql.SQL("UPDATE machine_drain_journal SET {} = %s WHERE send_id = %s")
            with pytest.raises(pgerr.CheckViolation) as refused:
                c.execute(update.format(sql.Identifier(column)), (value, send_id))
            assert refused.value.diag.message_primary == (
                f"trg_mdj_stamp_once: machine_drain_journal.{column} is write-once"
            )
        c.execute(_STAMP, (_NOW, send_id))
    assert [*changes, "replayed_at"] == [col.name for col in models.machine_drain_journal.columns]


def test_cv_app_upserts_a_snapshot_but_never_deletes_one(boot: str) -> None:
    with _as(boot, "cv_app") as c:
        entity = _snapshot(c)["entity_id"]
        c.execute(
            "INSERT INTO machine_snapshots AS s SELECT * FROM machine_snapshots "
            "WHERE entity_id = %s ON CONFLICT (machine_kind, entity_id, env) "
            "DO UPDATE SET chain_trips = s.chain_trips + 1",
            (entity,),
        )
        for verb in ("DELETE FROM machine_snapshots", "TRUNCATE machine_snapshots"):
            with pytest.raises(pgerr.InsufficientPrivilege):
                c.execute(verb)
        trips = c.execute(
            "SELECT chain_trips FROM machine_snapshots WHERE entity_id = %s", (entity,)
        ).fetchone()
    assert trips == (1,)


# --- Every invalid row is refused by its NAMED constraint (#2744 test plan) ----------------------


@pytest.mark.parametrize(
    ("table", "cols", "constraint"),
    [
        ("machine_snapshots", {"entity_id": ""}, "ms_entity"),
        ("machine_snapshots", {"env": "paper"}, "ms_env"),
        ("machine_snapshots", {"cv_schema_version": 0}, "ms_schema"),
        ("machine_snapshots", {"lib_snapshot_ver": 2}, "ms_lib_ver"),
        ("machine_snapshots", {"hmac_tag": bytes(31)}, "ms_tag_len"),
        ("machine_snapshots", {"chain_trips": -1}, "ms_trips"),
        ("machine_drain_journal", {"entity_id": ""}, "mdj_entity"),
        ("machine_drain_journal", {"env": "paper"}, "mdj_env"),
        ("machine_drain_journal", {"send_id": "g" * 32}, "mdj_send_id"),
        ("machine_drain_journal", {"lane": "x"}, "mdj_lane"),
        ("machine_drain_journal", {"ordinal": -1}, "mdj_ordinal"),
        ("machine_events", {"entity_id": ""}, "me_entity"),
        ("machine_events", {"env": "paper"}, "me_env"),
        ("machine_events", {"phase": "x"}, "me_phase"),
        ("machine_events", {"fault": Jsonb({"failed": []})}, "me_fault_phase"),
        ("machine_events", {"phase": "fault"}, "me_fault_phase"),
        ("machine_events", {"row_hash": "A" * 64}, "sha256_hex_check"),
    ],
)
def test_invalid_row_is_refused_by_its_named_check(
    pg: PostgresContainer, table: str, cols: dict[str, object], constraint: str
) -> None:
    with _conn(_url(pg)) as c, pytest.raises(pgerr.CheckViolation) as refused:
        _ROW[table](c, **cols)
    assert refused.value.diag.constraint_name == constraint


def test_row_hash_is_the_wal_replay_idempotency_key(pg: PostgresContainer) -> None:
    with _conn(_url(pg)) as c:
        row_hash = _event(c)["row_hash"]
        with pytest.raises(pgerr.UniqueViolation) as duplicate:
            _event(c, row_hash=row_hash)
    assert duplicate.value.diag.constraint_name == "machine_events_row_hash_key"
