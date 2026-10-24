"""`0051_replay_symbols_streams` (E26 G7, PR 1): the offline render, two-way plan-doc parity with
21 Sec.3.6.4's second block, the backfill, the CHECKs, the downgrade and the model mirror. Real
Postgres (the backfill on existing rows, the named rejections, the round trip):
`tests/integration/storage/test_replay_sessions_migration.py`."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

from sqlalchemy import CheckConstraint, Text
from sqlalchemy.dialects.postgresql import ARRAY

from candleviewer.db import models
from candleviewer.storage.repositories.recorded import REPLAYABLE_STREAMS

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0051_replay_symbols_streams", "0050_ea_identity_write_once"
_LOCK, _RESET = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"
#: Every replayable stream, as `ReplayRequest.streams` names them (`StreamKind` values); a test
#: pins it to `REPLAYABLE_STREAMS`. Literal SQL text throughout, never built from values.
_ALL = (
    "'{trades,orderbook_delta,orderbook_snapshot,tickers,klines,liquidations,open_interest,"
    "funding_rates}'"
)
_STAMP_UP = "UPDATE alembic_version SET version_num='0051_replay_symbols_streams'"
_STAMP_DOWN = "UPDATE alembic_version SET version_num='0050_ea_identity_write_once'"


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (G7)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    flat = " ".join(re.sub(r"--[^\n]*", "", sql).split())
    return flat.replace("( ", "(").replace(" )", ")")


def _statements(sql: str) -> list[str]:
    """`sql` cut at every `;`, blanks dropped (alembic ends each `op.execute` with one more `;`)."""
    return [part.strip() for part in sql.split(";") if part.strip()]


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", f"{_PREV}:{_REV}", "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", f"{_REV}:{_PREV}", "--sql"))


def _section() -> str:
    doc = _DOC.read_text(encoding="utf-8")
    return doc.split("#### 3.6.4 `replay_sessions`", 1)[1].split("### 3.7 ", 1)[0]


def _second_block() -> str:
    """Sec.3.6.4's second ```sql block (0023's table comes first), to its fence."""
    blocks = _section().split("```sql")
    assert len(blocks) > 2, f"expected a second ```sql block, found {len(blocks) - 1}"
    return _norm(blocks[2].split("```", 1)[0])


def test_revision_chains_onto_its_parent_and_21_registers_it() -> None:
    """Whoever merges second re-parents it (C-5.3); 21 Sec.9.4 keeps a row per revision."""
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", f"{_PREV}:{_REV}")
    rows = [
        r
        for r in _DOC.read_text(encoding="utf-8").split("### 9.4 ", 1)[1].splitlines()
        if r.startswith(f"| `{_REV}` ")
    ]
    assert len(rows) == 1 and "**#2674**" in rows[0]


def test_upgrade_is_exactly_the_plan_doc_block_under_a_bounded_lock_wait() -> None:
    """Two-way parity: inside the bounded lock wait (C-5.6) the upgrade runs Sec.3.6.4's second
    block and nothing else; outside it, only the transaction and alembic's version stamp."""
    before, rest = _up().split(_LOCK, 1)
    ddl, after = rest.split(_RESET, 1)
    assert _statements(ddl) == _statements(_second_block())
    assert _statements(before) == ["BEGIN"]
    assert _statements(after)[-1] == "COMMIT"
    assert _statements(after)[0].startswith(_STAMP_UP)


def test_upgrade_adds_nullable_columns_backfills_then_constrains() -> None:
    """Expand (C-5.1): the columns arrive nullable with no default (Sec.9.3 rule 2), every
    existing row is backfilled with its one symbol and every replayable stream (the 21:03Z
    ruling), and only then are they NOT NULL and CHECKed; `symbol` stays, as the first symbol."""
    sql = _second_block()
    order = [
        "ALTER TABLE replay_sessions ADD COLUMN symbols symbol_code[], ADD COLUMN streams text[]",
        "UPDATE replay_sessions SET symbols = ARRAY[symbol], streams = '{trades,orderbook_delta,"
        "orderbook_snapshot,tickers,klines,liquidations,open_interest,funding_rates}'",
        "ALTER COLUMN symbols SET NOT NULL",
        "ALTER COLUMN streams SET NOT NULL",
        "ADD CONSTRAINT rps_symbols CHECK",
        "ADD CONSTRAINT rps_streams CHECK",
    ]
    at = [sql.index(part) for part in order]
    assert at == sorted(at)
    for absent in ("DROP COLUMN symbol,", "DEFAULT", "GRANT", "COMMENT ON", "CREATE INDEX"):
        assert absent not in sql, f"{absent!r} is outside this revision"


def test_the_checks_bound_both_lists_and_keep_symbol_first() -> None:
    sql = _second_block()
    assert (
        "CONSTRAINT rps_symbols CHECK (cardinality(symbols) BETWEEN 1 AND 8 "
        "AND symbols[1] = symbol)"
    ) in sql
    assert f"CONSTRAINT rps_streams CHECK (cardinality(streams) >= 1 AND streams <@ {_ALL})" in sql


def test_the_stream_list_is_the_replayable_streams_in_order() -> None:
    """The backfill and `rps_streams` name `REPLAYABLE_STREAMS` (the raw recorded streams, by
    their `StreamKind` names): a stream added there needs a revision, and this test says so."""
    assert _ALL == "'{" + ",".join(s.value for s in REPLAYABLE_STREAMS) + "}'"
    assert _second_block().count(_ALL) == 2


def test_downgrade_refuses_to_lose_a_list_then_drops_what_upgrade_added() -> None:
    """Rollback only (C-5.2): a row the backfill could not rebuild (a second symbol, or fewer
    streams than all) refuses the downgrade with a clear error; otherwise both CHECKs and both
    columns go, and `symbol` keeps the first symbol."""
    stmts = _statements(_down())
    assert stmts[:2] == ["BEGIN", _LOCK.rstrip(";")]
    refusal = " ".join(stmts[2:4])
    assert (
        "IF EXISTS (SELECT 1 FROM replay_sessions WHERE cardinality(symbols) > 1 OR NOT streams @> "
        "'{trades,orderbook_delta,orderbook_snapshot,tickers,klines,liquidations,open_interest,"
        "funding_rates}') THEN RAISE EXCEPTION '0051_replay_symbols_streams downgrade refused"
    ) in refusal
    assert (
        "ALTER TABLE replay_sessions DROP CONSTRAINT rps_streams, DROP CONSTRAINT rps_symbols, "
        "DROP COLUMN streams, DROP COLUMN symbols"
    ) in stmts
    assert (stmts[-3], stmts[-1]) == (_RESET.rstrip(";"), "COMMIT")
    assert stmts[-2].startswith(_STAMP_DOWN)


def test_the_model_mirrors_the_columns_and_their_checks() -> None:
    """`alembic check` compares type and nullability, never a CHECK's body: pinned here."""
    t = models.replay_sessions
    symbols, streams = t.c.symbols, t.c.streams
    assert isinstance(symbols.type, ARRAY) and symbols.type.item_type is models.symbol_code
    assert isinstance(streams.type, ARRAY) and type(streams.type.item_type) is Text
    assert not symbols.nullable and not streams.nullable
    assert symbols.server_default is None and streams.server_default is None
    assert [c.name for c in t.columns][-2:] == ["symbols", "streams"]
    checks = {
        str(c.name).removeprefix("ck_replay_sessions_"): " ".join(str(c.sqltext).split())
        for c in t.constraints
        if isinstance(c, CheckConstraint)
    }
    assert checks["rps_symbols"] == ("cardinality(symbols) BETWEEN 1 AND 8 AND symbols[1] = symbol")
    assert checks["rps_streams"] == f"cardinality(streams) >= 1 AND streams <@ {_ALL}"


def test_no_index_is_added_and_the_live_index_is_unchanged() -> None:
    """`live_covering` takes `created` rows too, which `ix_rps_live` leaves out, and a GIN on
    `symbols` would index every destroyed row; the table is small, so it is scanned (21 Sec.13.1).
    """
    assert {str(ix.name) for ix in models.replay_sessions.indexes} == {
        "ix_rps_user_time",
        "ix_rps_live",
    }
    assert "INDEX" not in _up() and "CONCURRENTLY" not in _up()
