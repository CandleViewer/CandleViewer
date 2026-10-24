"""replay_sessions: every symbol and stream a session replays (E26 G7 #2674, PR 1)

Revision ID: 0051_replay_symbols_streams
Revises: 0050_ea_identity_write_once
Create Date: 2026-10-24

`docs/plan/21-database-schema.md` Sec.3.6.4's second block, verbatim. A session's request names
1-8 symbols and its streams (`ReplayRequest`), but the row kept one `symbol` and no stream, so the
retention guard (`live_covering`, G7) could only protect the first symbol, on every stream.

* Expand (C-5.1): `symbols symbol_code[]` and `streams text[]` arrive nullable with no default
  (Sec.9.3 rule 2), the backfill fills every existing row with its one symbol and every replayable
  stream (the orchestrator's 21:03Z ruling: fail toward retaining), then both turn NOT NULL. The
  backfill is one UPDATE on a small table (the owner's and a few managers' sessions), as
  `0037_account_profiles` backfills in its revision. `symbol` stays, as the first symbol
  (`rps_symbols`); its removal is a later expand -> migrate -> contract (Sec.14 row 11).
* `streams` holds `StreamKind` names (`funding_rates`, not the `stream_kind` enum's `funding`), the
  names the request and the retention defaults use; `rps_streams` closes it on
  `REPLAYABLE_STREAMS` (raw recorded streams only), so a stream added there needs a revision.
* No index: `live_covering` takes `created` rows, which `ix_rps_live` leaves out, and a GIN on
  `symbols` would index every destroyed row; the table is small and is scanned (Sec.13.1).
* No GRANT (`cv_app`'s table-level DML covers the columns) and no comment tag (P0).
* `lock_timeout = 5s` both ways (C-5.6): the ALTERs and the UPDATE hold ACCESS EXCLUSIVE on
  `replay_sessions` for a table of at most a few thousand rows.
* Reversible (C-5.2): the downgrade refuses, with a clear error, while a row holds more than one
  symbol or fewer streams than all (a list the backfill could not rebuild), then drops both CHECKs
  and both columns.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0051_replay_symbols_streams"
down_revision: str | None = "0050_ea_identity_write_once"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_UPGRADE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_DOWNGRADE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.3.6.4, second block, verbatim.
_UPGRADE_SQL = """
ALTER TABLE replay_sessions
  ADD COLUMN symbols symbol_code[],
  ADD COLUMN streams text[];
UPDATE replay_sessions
   SET symbols = ARRAY[symbol],
       streams = '{trades,orderbook_delta,orderbook_snapshot,tickers,klines,liquidations,open_interest,funding_rates}';
ALTER TABLE replay_sessions
  ALTER COLUMN symbols SET NOT NULL,
  ALTER COLUMN streams SET NOT NULL,
  ADD CONSTRAINT rps_symbols CHECK (cardinality(symbols) BETWEEN 1 AND 8 AND symbols[1] = symbol),
  ADD CONSTRAINT rps_streams CHECK (cardinality(streams) >= 1 AND streams <@ '{trades,orderbook_delta,orderbook_snapshot,tickers,klines,liquidations,open_interest,funding_rates}');
"""

_DOWNGRADE_SQL = """
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM replay_sessions WHERE cardinality(symbols) > 1 OR NOT streams @> '{trades,orderbook_delta,orderbook_snapshot,tickers,klines,liquidations,open_interest,funding_rates}') THEN
    RAISE EXCEPTION '0051_replay_symbols_streams downgrade refused: a replay session names more than one symbol or fewer than every replayable stream';
  END IF;
END $BODY$;
ALTER TABLE replay_sessions
  DROP CONSTRAINT rps_streams,
  DROP CONSTRAINT rps_symbols,
  DROP COLUMN streams,
  DROP COLUMN symbols;
"""
