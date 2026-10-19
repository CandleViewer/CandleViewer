"""machine_snapshots, machine_drain_journal, machine_events (E50-T61 #2744)

Revision ID: 0033_machine_persistence
Create Date: 2026-10-19

Purely additive (C-5.1). The three tables, their named CHECKs and both indexes are
`docs/plan/24-internal-schemas.md` Sec.17.6 verbatim: the statechart runtime's sealed snapshots,
the drain journal replayed once after a restore, and `CvAuditPlugin`'s hash-chained transition log.
`sha256_hex` (0001), `forbid_mutation()` and `audit_refuse_truncate()` (0003) are reused, never
redefined. No row is written here: the stores are E50-T62, the sink and the wiring E50-T63. The
parent is `down_revision` alone, so re-parenting this revision is a one-line change.

* `machine_events` is append-only (C-2.9, C-5.7), the `audit_log` (0003) and `order_events` (0029)
  pattern: `trg_me_append` (`forbid_mutation()`, BEFORE UPDATE OR DELETE, per row),
  `trg_me_no_truncate` (`audit_refuse_truncate()`, BEFORE TRUNCATE) and `REVOKE UPDATE, DELETE,
  TRUNCATE` from `cv_app` and `cv_ro`.
* `machine_drain_journal` is written once, then stamped once: `cv_app` keeps SELECT and INSERT,
  loses UPDATE, DELETE and TRUNCATE, and gets UPDATE back on `replayed_at` alone (a table REVOKE
  also drops column grants, so it comes first). `trg_mdj_stamp_once` (BEFORE UPDATE, per row, the
  0024/0032 write-once pattern) refuses a change to any other column and lets `replayed_at` go
  from NULL to a value once, with SQLSTATE 23514 naming the column and its rule, never a value
  (`payload` is class P1). It compares with IS DISTINCT FROM, so writing a value over itself
  passes; `ENABLE ALWAYS` keeps it firing under `session_replication_role = replica`, and the
  function pins its `search_path`. It is the only trigger on the table.
* `machine_snapshots` is upserted: `cv_app` keeps SELECT, INSERT and UPDATE and loses DELETE and
  TRUNCATE.
* Every REVOKE and GRANT runs only where its role exists (the 0003 guard): the roles come from
  `infra/scripts/pg_bootstrap.sql`, and a migration-only test cluster has none. They narrow the
  bootstrap's default privileges; the one GRANT gives back a column of what was revoked. The
  owning role and superusers can still disable a trigger, as for `audit_log`.
* C-5.9 / 21 Sec.12: every column carries its class in a comment. `snapshot` and both `payload`
  columns are class P1 (`PII:`): a machine context or an event can repeat order and position
  values. Every other column is P0 (`P0:` and its meaning). No column is class S: `hmac_key_id`
  names a key and `hmac_tag` is an integrity tag. `db.models` mirrors every text byte for byte.
* `SET LOCAL lock_timeout = '5s'` brackets both directions (C-5.6): the upgrade locks only the
  tables it creates, and the downgrade's drops wait for ACCESS EXCLUSIVE.
* The downgrade locks the three tables in SHARE mode and refuses, naming the table, while any of
  them holds a row: audit history and recovery state are never dropped, so a populated database
  is fixed forward (C-5.2, C-5.7). Empty, it drops the tables and the stamp-once function, never
  the shared functions or the domain.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0033_machine_persistence"
down_revision: str | None = "0032_backups_write_once"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_TABLES_SQL)
    op.execute(_GUARDS_SQL)
    op.execute(_GRANTS_SQL)
    op.execute(_COMMENT_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_DOWNGRADE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 24-internal-schemas.md Sec.17.6, verbatim.
_TABLES_SQL = """
CREATE TABLE machine_snapshots (
  machine_kind      text        NOT NULL,   -- catalogue id: order, trade_group, leg, ..., risk_lockout
  entity_id         text        NOT NULL,   -- MachineKey.entity_id verbatim (see "Machine key")
  env               text        NOT NULL,
  cv_schema_version int         NOT NULL,   -- persistence.SEAL_LAYOUT_V at write time; diagnostic only
  lib_snapshot_ver  int         NOT NULL,   -- SealedSnapshot.version; CV-C52 minimum_version=3
  machine_hash      sha256_hex  NOT NULL,   -- sha256(canonical_json(chart)); must equal machine_hashes.lock
  snapshot          jsonb       NOT NULL,   -- interpreter.get_persisted_snapshot() (root only; carries chain_trips)
  hmac_key_id       text        NOT NULL,   -- Seal.key_id
  hmac_tag          bytea       NOT NULL,   -- the 32 raw bytes of Seal.tag; input layout owned by 29 §1.3 (CV-C53)
  state_ids         text[]      NOT NULL,   -- denormalised from the blob, query/index only
  chain_trips       int         NOT NULL DEFAULT 0,  -- denormalised; >0 = latched degraded until operator ack (CV-C63)
  updated_at        timestamptz NOT NULL,
  PRIMARY KEY (machine_kind, entity_id, env),
  CONSTRAINT ms_entity  CHECK (entity_id <> ''),
  CONSTRAINT ms_env     CHECK (env IN ('live','demo','testnet')),
  CONSTRAINT ms_schema  CHECK (cv_schema_version >= 1),
  CONSTRAINT ms_lib_ver CHECK (lib_snapshot_ver >= 3),
  CONSTRAINT ms_tag_len CHECK (octet_length(hmac_tag) = 32),
  CONSTRAINT ms_trips   CHECK (chain_trips >= 0)
);

CREATE TABLE machine_drain_journal (          -- CV-C65': drained events, replayed exactly once after restore
  machine_kind  text        NOT NULL,
  entity_id     text        NOT NULL,
  env           text        NOT NULL,
  send_id       text        NOT NULL,         -- stable id (R11-W-1): 32 hex of sha256; de-dup key for re-submits (R14-02)
  lane          text        NOT NULL,
  ordinal       int         NOT NULL,         -- position in drain_pending() output, priority first
  event_type    text        NOT NULL,
  payload       jsonb       NOT NULL,         -- JournalEntry.record (the persist_event output)
  receipt_error text,                         -- Receipt.error class name if set (e.g. InterpreterStoppedError)
  replayed_at   timestamptz,                  -- set once, by replay_once
  PRIMARY KEY (machine_kind, entity_id, env, send_id),
  CONSTRAINT mdj_entity  CHECK (entity_id <> ''),
  CONSTRAINT mdj_env     CHECK (env IN ('live','demo','testnet')),
  CONSTRAINT mdj_send_id CHECK (send_id ~ '^[0-9a-f]{32}$'),
  CONSTRAINT mdj_lane    CHECK (lane IN ('priority','inbox')),
  CONSTRAINT mdj_ordinal CHECK (ordinal >= 0)
);
CREATE INDEX ix_mdj_pending ON machine_drain_journal (machine_kind, entity_id, env, ordinal)
  WHERE replayed_at IS NULL;                  -- list-unreplayed, in replay order

CREATE TABLE machine_events (                 -- append-only, hash-chained; CvAuditPlugin; order_events (§8) specialises it
  seq          bigserial   PRIMARY KEY,
  machine_kind text        NOT NULL,
  entity_id    text        NOT NULL,
  env          text        NOT NULL,
  event_type   text        NOT NULL,
  payload      jsonb       NOT NULL,
  from_states  text[]      NOT NULL,
  to_states    text[]      NOT NULL,
  actions_run  text[]      NOT NULL,          -- from the actual execution list (MUST-02)
  fault        jsonb,                         -- non-null exactly when phase = 'fault'
  occurred_at  timestamptz NOT NULL,
  phase        text        NOT NULL,          -- MachineEventRow.phase: write-ahead row, commit row, or fault row
  prev_hash    sha256_hex  NOT NULL,          -- previous row_hash of the same (machine_kind, entity_id, env); 64 zeros first
  row_hash     sha256_hex  NOT NULL UNIQUE,   -- row_digest(); the idempotency key for WAL replay
  CONSTRAINT me_entity     CHECK (entity_id <> ''),
  CONSTRAINT me_env        CHECK (env IN ('live','demo','testnet')),
  CONSTRAINT me_phase      CHECK (phase IN ('ahead','commit','fault')),
  CONSTRAINT me_fault_phase CHECK ((phase = 'fault') = (fault IS NOT NULL))
);
CREATE INDEX ix_me_machine_seq ON machine_events (machine_kind, entity_id, env, seq);
"""

_GUARDS_SQL = """
CREATE FUNCTION machine_drain_journal_stamp_once() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE changed text;
BEGIN
  changed := CASE
    WHEN NEW.machine_kind IS DISTINCT FROM OLD.machine_kind THEN 'machine_kind'
    WHEN NEW.entity_id IS DISTINCT FROM OLD.entity_id THEN 'entity_id'
    WHEN NEW.env IS DISTINCT FROM OLD.env THEN 'env'
    WHEN NEW.send_id IS DISTINCT FROM OLD.send_id THEN 'send_id'
    WHEN NEW.lane IS DISTINCT FROM OLD.lane THEN 'lane'
    WHEN NEW.ordinal IS DISTINCT FROM OLD.ordinal THEN 'ordinal'
    WHEN NEW.event_type IS DISTINCT FROM OLD.event_type THEN 'event_type'
    WHEN NEW.payload IS DISTINCT FROM OLD.payload THEN 'payload'
    WHEN NEW.receipt_error IS DISTINCT FROM OLD.receipt_error THEN 'receipt_error'
    WHEN OLD.replayed_at IS NOT NULL
      AND NEW.replayed_at IS DISTINCT FROM OLD.replayed_at THEN 'replayed_at'
  END;
  IF changed IS NOT NULL THEN
    RAISE EXCEPTION 'trg_mdj_stamp_once: machine_drain_journal.% is %', changed,
      CASE WHEN changed = 'replayed_at' THEN 'set-once' ELSE 'write-once' END
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $BODY$;
CREATE TRIGGER trg_mdj_stamp_once BEFORE UPDATE ON machine_drain_journal
  FOR EACH ROW EXECUTE FUNCTION machine_drain_journal_stamp_once();
ALTER TABLE machine_drain_journal ENABLE ALWAYS TRIGGER trg_mdj_stamp_once;

CREATE TRIGGER trg_me_append BEFORE UPDATE OR DELETE ON machine_events
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER trg_me_no_truncate BEFORE TRUNCATE ON machine_events
  FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_truncate();
"""

# 24 Sec.17.6 "Privileges and triggers". Each statement runs only where `pg_bootstrap.sql` made its
# role (0003/0029 pattern). Static literals: SQL built from strings at runtime trips bandit B608.
_GRANTS_SQL = """
DO $BODY$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN
    EXECUTE 'REVOKE DELETE, TRUNCATE ON machine_snapshots FROM cv_app';
    EXECUTE 'REVOKE UPDATE, DELETE, TRUNCATE ON machine_drain_journal FROM cv_app';
    EXECUTE 'GRANT UPDATE (replayed_at) ON machine_drain_journal TO cv_app';
    EXECUTE 'REVOKE UPDATE, DELETE, TRUNCATE ON machine_events FROM cv_app';
  END IF;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_ro') THEN
    EXECUTE 'REVOKE UPDATE, DELETE, TRUNCATE ON machine_events FROM cv_ro';
  END IF;
END $BODY$;
"""

# C-5.9 / 21 Sec.12. Byte-identical to the column comments in `db.models` (`alembic check` diffs
# them); no quote in any text, as each sits in a SQL string literal.
_KEY = {
    "machine_kind": "P0: catalogue machine kind (28 B1-B20); part of the machine key",
    "entity_id": "P0: MachineKey.entity_id, the owning module canonical id; part of the machine key",
    "env": "P0: environment, live, demo or testnet; part of the machine key",
}
_EVENT_TYPE = "P0: event name"
_P1 = "PII: financial personal data (21 Sec.12, class P1): {}; holds no credential, token or key; never logged"
_COMMENTS = {
    "machine_snapshots": {
        **_KEY,
        "cv_schema_version": "P0: persistence.SEAL_LAYOUT_V at write time; diagnostic only",
        "lib_snapshot_ver": "P0: SealedSnapshot.version, the library snapshot version (CV-C52, 3 or more)",
        "machine_hash": "P0: sha256 of the canonical chart JSON; equals machine_hashes.lock",
        "snapshot": _P1.format("machine context, HMAC-sealed (CV-C53)"),
        "hmac_key_id": "P0: Seal.key_id, a reference to the HMAC key, never key material",
        "hmac_tag": "P0: the 32 raw bytes of the HMAC-SHA256 seal tag (CV-C53); an integrity tag",
        "state_ids": "P0: active state ids, denormalised from the sealed blob for query only",
        "chain_trips": "P0: chain-trip count, denormalised; above 0 latches the machine degraded (CV-C63)",
        "updated_at": "P0: time of the last snapshot write; outside the seal",
    },
    "machine_drain_journal": {
        **_KEY,
        "send_id": "P0: stable send id, 32 hex of sha256; de-dup key for re-submits (R14-02)",
        "lane": "P0: drain lane, priority or inbox",
        "ordinal": "P0: position in the drain output, priority lane first; the replay order",
        "event_type": _EVENT_TYPE,
        "payload": _P1.format("a drained event replayed once after restore"),
        "receipt_error": "P0: Receipt.error class name when the drain failed a waiter",
        "replayed_at": "P0: set once, when replay_once re-enqueued the event",
    },
    "machine_events": {
        "seq": "P0: insertion order; the chain order within one machine",
        **_KEY,
        "event_type": _EVENT_TYPE,
        "payload": _P1.format("event data, hash-chained (row_hash)"),
        "from_states": "P0: active state ids before the transition",
        "to_states": "P0: active state ids after the transition",
        "actions_run": "P0: names of the actions actually executed (MUST-02)",
        "fault": "P0: action names, exception class names and refusal reasons; never a payload or context value",
        "occurred_at": "P0: transition time (UTC), as the plugin emitted it",
        "phase": "P0: ahead (write-ahead), commit or fault",
        "prev_hash": "P0: row_hash of the previous row of the same machine; 64 zeros first",
        "row_hash": "P0: sha256 over the canonical JSON of the other fields; the WAL-replay idempotency key",
    },
}
_COMMENT_SQL = "\n".join(
    f"COMMENT ON COLUMN {table}.{column} IS '{text}';"
    for table, columns in _COMMENTS.items()
    for column, text in columns.items()
)

_DOWNGRADE_SQL = """
LOCK TABLE machine_snapshots, machine_drain_journal, machine_events IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM machine_snapshots) THEN
    RAISE EXCEPTION '0033_machine_persistence downgrade refused: machine_snapshots holds rows; recovery state and audit history are never dropped, so fix forward with a new revision instead (C-5.2, C-5.7)';
  END IF;
  IF EXISTS (SELECT 1 FROM machine_drain_journal) THEN
    RAISE EXCEPTION '0033_machine_persistence downgrade refused: machine_drain_journal holds rows; recovery state and audit history are never dropped, so fix forward with a new revision instead (C-5.2, C-5.7)';
  END IF;
  IF EXISTS (SELECT 1 FROM machine_events) THEN
    RAISE EXCEPTION '0033_machine_persistence downgrade refused: machine_events holds rows; recovery state and audit history are never dropped, so fix forward with a new revision instead (C-5.2, C-5.7)';
  END IF;
END $BODY$;
DROP TABLE machine_events;
DROP TABLE machine_drain_journal;
DROP TABLE machine_snapshots;
DROP FUNCTION machine_drain_journal_stamp_once();
"""
