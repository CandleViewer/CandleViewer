"""`0032_backups_write_once` (E42-T05 #966, BK-2): offline render, plan-doc parity, the guard's
columns and refusal, the downgrade guard and the model mirror.
Real Postgres: `tests/integration/storage/test_backups_write_once_pg.py`."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

from sqlalchemy import CheckConstraint

from candleviewer.db.models import backups

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0032_backups_write_once", "0031_policy_disarm"
#: Refused outright (SR-E42-05); `triggered_by_user` may still be cleared by its FK.
_WRITE_ONCE = ("id", "kind", "target_path", "encryption_ref", "started_at", "triggered_by")
#: May go from NULL to a value once; `deleted_by` only with the mark, then its FK alone clears it.
_SET_ONCE = ("checksum_sha256", "deleted_at", "deleted_by")
#: Written by the engine, verify and delete paths (BK-3); reviewed, not guarded.
_WRITABLE = {
    "status", "size_bytes", "encrypted", "covers_from", "covers_to", "wal_start_lsn",
    "wal_end_lsn", "duration_ms", "verified_at", "verify_method", "restored_at", "error_message",
    "finished_at", "retention_until",
}  # fmt: skip
#: 0024/0030's guarded REVOKE, for `backups`; the downgrade's GRANT is its mirror.
_REVOKE = (
    "DO $BODY$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN "
    "EXECUTE 'REVOKE DELETE ON backups FROM cv_app'; END IF; END $BODY$;"
)
_GRANT = _REVOKE.replace("REVOKE DELETE ON backups FROM", "GRANT DELETE ON backups TO")


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#966)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """Drop `--` comments and collapse whitespace, so layout never matters."""
    return " ".join(re.sub(r"--[^\n]*", "", sql).split())


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", f"{_PREV}:{_REV}", "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", f"{_REV}:{_PREV}", "--sql"))


def _in_order(sql: str, steps: list[str]) -> bool:
    missing = [step for step in steps if step not in sql]
    assert not missing, f"not in the rendered SQL: {missing}"
    positions = [sql.index(step) for step in steps]
    return positions == sorted(positions)


def test_revision_chains_onto_0031() -> None:
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", f"{_PREV}:{_REV}")


def test_upgrade_is_the_plan_doc_ddl_then_the_guard_under_a_bounded_lock_wait() -> None:
    """The second ```sql block of Sec.3.10.3 (the first is 0028's), to its fence; then the guard
    and the REVOKE."""
    section = _DOC.read_text(encoding="utf-8").split("#### 3.10.3 `backups`", 1)[1]
    section = re.split(r"\n#{1,4} ", section, maxsplit=1)[0]
    ddl = _norm(section.split("```sql", 2)[2].split("```", 1)[0])
    assert ddl.startswith("ALTER TABLE backups ADD COLUMN deleted_at timestamptz,")
    assert _in_order(
        _up(),
        [
            "SET LOCAL lock_timeout = '5s';",
            ddl,
            "CREATE FUNCTION backups_write_once() RETURNS trigger LANGUAGE plpgsql "
            "SET search_path = pg_catalog, pg_temp AS $BODY$",
            "CREATE TRIGGER trg_backups_write_once BEFORE UPDATE ON backups "
            "FOR EACH ROW EXECUTE FUNCTION backups_write_once();",
            "ALTER TABLE backups ENABLE ALWAYS TRIGGER trg_backups_write_once;",
            _REVOKE,
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
    )


def test_the_only_privilege_change_is_cv_app_losing_delete_and_getting_it_back() -> None:
    """A narrowing (0024/0030): DELETE on `backups` leaves `cv_app` where the role exists, and the
    downgrade grants it back. No other GRANT or REVOKE, and no other table is touched."""
    up, down = _up(), _down()
    counts = [sql.count(verb) for sql in (up, down) for verb in ("REVOKE ", "GRANT ")]
    assert counts == [1, 0, 0, 1] and _REVOKE in up and _GRANT in down
    for sql in (up, down):
        for absent in ("INSERT INTO", "COMMENT ON", "audit_log"):
            assert absent not in sql
        assert set(re.findall(r"\b(?:ON|TABLE) (?!DELETE\b)(\w+)", sql)) == {"backups"}


def test_the_guard_compares_each_column_once_in_this_order() -> None:
    """The CASE arms, verbatim: six refused outright; `triggered_by_user` only while its user
    exists (the FK's ON DELETE SET NULL is an UPDATE too); two may go from NULL once; `deleted_by`
    is frozen with the mark, under the same FK carve-out."""
    found = re.search(r"changed := CASE WHEN (.+?) END;", _up())
    assert found is not None
    outright = [f"NEW.{c} IS DISTINCT FROM OLD.{c} THEN '{c}'" for c in _WRITE_ONCE]
    user = (
        "NEW.triggered_by_user IS DISTINCT FROM OLD.triggered_by_user AND "
        "(NEW.triggered_by_user IS NOT NULL OR EXISTS "
        "(SELECT FROM public.users u WHERE u.id = OLD.triggered_by_user)) THEN 'triggered_by_user'"
    )
    once = [
        f"OLD.{c} IS NOT NULL AND NEW.{c} IS DISTINCT FROM OLD.{c} THEN '{c}'"
        for c in _SET_ONCE[:2]
    ]
    deleter = (
        "NEW.deleted_by IS DISTINCT FROM OLD.deleted_by AND OLD.deleted_at IS NOT NULL AND "
        "(NEW.deleted_by IS NOT NULL OR EXISTS "
        "(SELECT FROM public.users u WHERE u.id = OLD.deleted_by)) THEN 'deleted_by'"
    )
    assert found.group(1).split(" WHEN ") == [*outright, user, *once, deleter]


def test_every_backups_column_is_guarded_or_reviewed_writable() -> None:
    """Tripwire: a new column fails here until it is reviewed into one of the sets."""
    guarded = {*_WRITE_ONCE, "triggered_by_user", *_SET_ONCE}
    assert not guarded & _WRITABLE
    assert {c.name for c in backups.columns} == guarded | _WRITABLE


def test_refusal_names_the_column_and_its_rule_and_never_a_value() -> None:
    """The only RAISE formats `changed`, a column-name literal, and the rule word chosen from two
    literals; no OLD or NEW value reaches the message (`encryption_ref` is class S)."""
    assert _up().count("RAISE") == 1
    assert re.findall(r"RAISE EXCEPTION (.+? USING ERRCODE = '\w+');", _up()) == [
        "'trg_backups_write_once: backups.% is % (SR-E42-05)', changed, CASE WHEN changed IN "
        f"{tuple(_SET_ONCE)} THEN 'set-once' ELSE 'write-once' END "
        "USING ERRCODE = 'check_violation'"
    ]


def test_downgrade_refuses_while_an_artefact_is_marked_deleted_then_drops_what_it_added() -> None:
    assert _in_order(
        _down(),
        [
            "SET LOCAL lock_timeout = '5s';",
            "LOCK TABLE backups IN SHARE MODE;",
            "IF EXISTS (SELECT 1 FROM backups WHERE deleted_at IS NOT NULL) THEN",
            "RAISE EXCEPTION '0032_backups_write_once downgrade refused:",
            _GRANT,
            "DROP TRIGGER trg_backups_write_once ON backups;",
            "DROP FUNCTION backups_write_once();",
            "ALTER TABLE backups DROP CONSTRAINT bk_deleted, DROP COLUMN deleted_by, "
            "DROP COLUMN deleted_at;",
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
    )
    assert "Fix forward with a new revision instead (C-5.2)" in _down()


def test_the_model_mirrors_the_columns_their_fk_and_the_check() -> None:
    columns = [backups.c.deleted_at, backups.c.deleted_by]
    assert [(c.nullable, c.server_default, c.comment) for c in columns] == [(True, None, None)] * 2
    assert [(fk.column.table.name, fk.ondelete) for fk in backups.c.deleted_by.foreign_keys] == [
        ("users", "SET NULL")
    ]
    checks = {
        str(c.name): " ".join(str(c.sqltext).split())
        for c in backups.constraints
        if isinstance(c, CheckConstraint)
    }
    assert f"CONSTRAINT bk_deleted CHECK ({checks['ck_backups_bk_deleted']})" in _up()
