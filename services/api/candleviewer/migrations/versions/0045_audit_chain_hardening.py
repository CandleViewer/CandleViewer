"""audit_log: `audit_chain()` pins its search_path and draws each id under the chain lock

Revision ID: 0045_audit_chain_hardening
Revises: 0044_account_no_hard_delete
Create Date: 2026-10-21

One statement each way replaces 0003's `audit_chain()` (#889 S3, SR-E42-10; #4032). The upgrade is
0003's text with two changes, and the downgrade is 0003's text.

* A `search_path` of the function's own, `pg_catalog, public, pg_temp`, set on the definition.
  0003's function names what it calls (`digest`, `encode`, `audit_field`, ...), the table it reads
  (`audit_log`) and the domain it declares without a schema, so each resolved through the
  search_path of the session that inserts: a schema that session put first, with a
  `digest(text, text)` of its own, forged every hash. `pg_catalog` first; `public`, where the
  tables, the sequence and pgcrypto live; `pg_temp` last, so a temporary table never stands in for
  `audit_log`. The pin holds while `public` stays closed to other roles: a better-typed overload
  created there (a `pg_advisory_xact_lock(int4)`, a `nextval(text)`) would still win over
  `pg_catalog`'s. `cv_owner` owns `public`, `pg_bootstrap.sql` revokes CREATE on it from PUBLIC
  (PostgreSQL's default since 15), and the role privilege matrix pins it for `cv_app`
  (`test_cv_app_may_use_schema_public_but_not_create_in_it`). `audit_field()` runs under this path
  when the chain calls it, and `forbid_mutation()` and `audit_refuse_truncate()` only raise, so the
  pin on `audit_chain()` alone covers what the guards resolve.
* `NEW.id := nextval('audit_log_id_seq')` right after the advisory lock, overwriting whatever id the
  INSERT carried, the column default's or one the caller named. `audit_log.id` is a `bigserial`
  (0003): an INSERT draws its id from the column default before the BEFORE INSERT trigger takes
  the chain lock. The chain links rows in lock order (each `prev_hash` is the head's
  `entry_hash`, read under the lock) and verify walks them in id order, so an INSERT that did not
  take the lock first (another tool, a migration, a manual insert) could hold an id below a row
  that committed ahead of it and hash that row as its predecessor: a valid chain read as broken,
  or a break hid. The app's path locks first (`insert_audit_row_locked`); SR-E42-10 and AC-ADM-16
  (`docs/security/threat-models/e42-admin.md`) require every path to be safe. Ids now follow lock
  order on every path; the link follows the head on every path that inserts at READ COMMITTED, the
  writer's rule: at REPEATABLE READ or SERIALIZABLE the trigger reads the head from a snapshot
  taken before the lock, so such an insert can link to a stale head, a break verify reports. The id
  is not hashed, so every stored `entry_hash` still recomputes.
* The column default stays: removing it would alter an append-only table. An INSERT that omits `id`
  draws two, the default's going unused: each insert consumes two ids, so N rows span about 2N ids
  and a verify range, capped by `audit_verify_max_span` in ids, covers about half as many entries.
  Verify never assumes consecutive ids (keyset batches by id, a range anchored on the greatest id
  below its start, checkpoints by id), and ids had gaps already (a rolled-back insert, a WAL replay
  that conflicts on `record_id`). Ids follow lock order only while `audit_log_id_seq` keeps
  `CACHE 1`, the `bigserial` default: a cached sequence hands each session its own block (the
  two-connection integration test checks it).
* No grant changes (C-5.7): `nextval` runs as the inserting role, which holds USAGE on the sequence
  already, for the default. No lock on `audit_log` (C-5.6): the replacement rewrites the function's
  `pg_proc` row, and `trg_audit_chain` keeps calling the same function.
* CI-MIG-003 refuses any change to a guard function, and exempts this file only in exactly this
  shape: one inline statement each way, each text pinned by its sha256 in
  `tools/ci/migration_lint.py`. Hence no named SQL constants and no `lock_timeout` bracket.

Reversible (C-5.2): `downgrade()` restores 0003's definition exactly, which also drops the pin
(a replacement keeps no setting it does not name); a unit test holds both texts to 0003's. Neither
direction touches a row, so an empty or a seeded database round-trips (C-5.5).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0045_audit_chain_hardening"
down_revision: str | None = "0044_account_no_hard_delete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
CREATE OR REPLACE FUNCTION audit_chain() RETURNS trigger LANGUAGE plpgsql
  SET search_path = pg_catalog, public, pg_temp AS $BODY$
DECLARE last_hash sha256_hex;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('audit_log'));
  NEW.id := nextval('audit_log_id_seq');
  SELECT entry_hash INTO last_hash FROM audit_log ORDER BY id DESC LIMIT 1;
  NEW.prev_hash := COALESCE(last_hash, repeat('0',64));
  NEW.entry_hash := encode(digest(
      audit_field(NEW.prev_hash)
      || audit_field(NEW.actor_user_id::text) || audit_field(NEW.actor_label)
      || audit_field(NEW.actor_ip::text) || audit_field(NEW.session_id::text)
      || audit_field(NEW.action) || audit_field(NEW.object_kind)
      || audit_field(NEW.object_id) || audit_field(NEW.outcome::text)
      || audit_field(NEW.severity::text) || audit_field(NEW.reason)
      || audit_field(NEW.before_state::text) || audit_field(NEW.after_state::text)
      || audit_field(NEW.request_id::text) || audit_field(NEW.env::text)
      || audit_field(to_char(NEW.event_ts AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.USOF')),
    'sha256'), 'hex');
  RETURN NEW;
END $BODY$;
""")


def downgrade() -> None:
    op.execute("""
CREATE OR REPLACE FUNCTION audit_chain() RETURNS trigger LANGUAGE plpgsql AS $BODY$
DECLARE last_hash sha256_hex;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('audit_log'));
  SELECT entry_hash INTO last_hash FROM audit_log ORDER BY id DESC LIMIT 1;
  NEW.prev_hash := COALESCE(last_hash, repeat('0',64));
  NEW.entry_hash := encode(digest(
      audit_field(NEW.prev_hash)
      || audit_field(NEW.actor_user_id::text) || audit_field(NEW.actor_label)
      || audit_field(NEW.actor_ip::text) || audit_field(NEW.session_id::text)
      || audit_field(NEW.action) || audit_field(NEW.object_kind)
      || audit_field(NEW.object_id) || audit_field(NEW.outcome::text)
      || audit_field(NEW.severity::text) || audit_field(NEW.reason)
      || audit_field(NEW.before_state::text) || audit_field(NEW.after_state::text)
      || audit_field(NEW.request_id::text) || audit_field(NEW.env::text)
      || audit_field(to_char(NEW.event_ts AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.USOF')),
    'sha256'), 'hex');
  RETURN NEW;
END $BODY$;
""")
