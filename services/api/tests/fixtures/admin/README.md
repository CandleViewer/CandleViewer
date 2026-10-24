# Admin area fixtures (E42-Q01, #962)

The seeded handles of the admin area's black-box test plan (`docs/qa/e42-admin-test-plan.md` §1), as
code rather than a dump, so they survive schema migrations. Every value is synthetic: `example.invalid`
addresses, `fixture` labels, and ids and numeric exchange uids (the `ea_uid_fmt` check takes digits
only) derived from each handle's name with `uuid5`: the handles' rows are the same on every run. Two
things are random by design: the default profile each account gets from the `trg_ea_default_profile`
trigger, and the invite's token. Nothing here is a credential, an exchange key, a token or anyone's
personal data, and `tests/unit/test_admin_fixture_handles.py`, `test_admin_fixture_seed.py`,
`test_admin_corrupt_chain_fixture.py` and `test_admin_flag_overrides_fixture.py` pass every value,
and this file, through the log redactor to keep it so.

| File                 | What it holds                                                                                   |
| -------------------- | ----------------------------------------------------------------------------------------------- |
| `handles.py`         | The users (every status and role), the demo accounts, grants, flags, and the backups, by handle |
| `seed.py`            | `seed_admin_world`, `seed_backups` and their checks, and the refusal of a non-test database     |
| `corrupt_chain.py`   | AUDIT-CORRUPT: `seed_corrupted_chain`, a chain with one of its own entries altered behind it    |
| `latched_machine.py` | SC-CHAIN-TRIPS: a sealed, degraded order snapshot, its seed and its check                       |
| `audit_10m.py`       | AUDIT-10M: `load_audit_10m`, E42-K01's 10 M-row generator run into a test database              |
| `flag_overrides.py`  | FLAG-OVERRIDE-ROWS: override rows on both safety flags and an unreadable row, and their check   |
| `world.py`           | `require_world`: the rows of slice A's world a later seed needs, each named if missing          |
| `oob_writes.py`      | OOB-WRITES: four writes as `cv_app` outside the API, with no audit record, and their check      |
| `forged_seal.py`     | SC-FORGED-SEAL: a snapshot changed after it was sealed, `forged_row` and its checks             |
| `payloads/`          | The health reports and the overview, as JSON bodies of the contract's models                    |
| `README.md`          | This file                                                                                       |

## The handles

| Handle                    | Seeded as                                                                 |
| ------------------------- | ------------------------------------------------------------------------- |
| OWNER, OWNER-2            | Two active Owners                                                         |
| MGR-M, MGR-N, MGR-MANY    | Active Managers with trade grants on SUB-S; on nothing; on SUB-S, T and U |
| VIEWER-V                  | An active Viewer                                                          |
| INVITED-I                 | An invited Viewer with one open invite, from OWNER                        |
| DISABLED-D, LOCKED-L      | A disabled Manager; a Manager locked for an hour after the seed's `now`   |
| MAIN, SUB-S, SUB-T, SUB-U | A demo main account and three sub-accounts, 30 days old                   |
| SUB-K                     | A demo sub-account an hour old, inside Bybit's 48-hour key restriction    |
| `trading.live_enabled`    | Off: the live gate is blocked                                             |
| `rules.graph_editor`      | On: a boolean flag of `candleviewer/admin/flags/catalogue.py` to change   |

Sessions, step-up state and TOTP enrolment are not seeded: each is a credential or derives from one. A
suite that signs a user in enrols them through the API in its own setup. Nor is the invite's token
seeded; the seed draws one per run and keeps only its sha256, so no one can redeem the seeded invite.
A suite that redeems an invite issues its own through the API.

## How to load them

Into a migrated test database, from `services/api`:

```python
from datetime import UTC, datetime

from tests.fixtures.admin.seed import check_admin_world, seed_admin_world

now = datetime.now(UTC)  # the clock the app under test reads
async with engine.begin() as conn:
    await seed_admin_world(conn, now=now)
    await check_admin_world(conn, now=now)
```

- **Idempotent:** each row is written with `ON CONFLICT` on its primary key (its derived id, or the
  pair of ids of a role or a grant; a flag on its key), so a second run changes nothing.
- **Re-seeding:** users, accounts, grants and the invite are `DO NOTHING`; flags are `DO UPDATE`, so a
  flipped `trading.live_enabled` is put back and a disabled MGR-M is not. Time-relative rows do not
  refresh (SUB-K's 48 hours, LOCKED-L's hour, the invite's week), so `now` must be the clock the app
  reads, and a fresh database is the reset.
- **Self-checking:** `check_admin_world` raises `FixtureCheckError`, naming every post-condition the rows
  break.
- **Test databases only:** both refuse, with `FixtureRefused` and nothing written, any database whose
  name is not `test` and does not end in `_test`. A `now` without a timezone raises `ValueError`.
- **No sign-in:** every seeded user's password hash is `PLACEHOLDER_HASH`, which verifies no password. A
  suite that signs in passes a hash it computes at run time, as `password_hash=`.

`tests/integration/admin/test_admin_fixture_seed_pg.py` runs the seed twice on Postgres 16 and checks it.

## The backups

**BACKUP-VERIFY-FAILED** is two rows in an otherwise empty catalogue (`seed_backups`, asserted by
`check_backups`). Into a migrated test database, from `services/api`:

```python
from datetime import UTC, datetime

from tests.fixtures.admin.seed import check_backups, seed_backups

now = datetime.now(UTC)  # the clock the app under test reads
async with engine.begin() as conn:
    await seed_backups(conn, now=now)
    await check_backups(conn)
```

| Handle               | Seeded as                                                                           |
| -------------------- | ----------------------------------------------------------------------------------- |
| BACKUP-VERIFIED      | A backup three days before `now`, verified by `checksum`: the last verified one     |
| BACKUP-VERIFY-FAILED | The latest backup, an hour before `now`, `failed` with the code `checksum_mismatch` |
| BACKUPS-NONE         | A world seeded without `seed_backups`: an empty catalogue                           |

- **Idempotent:** `ON CONFLICT (id) DO NOTHING`: a second run, whatever its `now`, keeps the first's.
- **Self-checking:** `check_backups` raises `FixtureCheckError` naming each difference: a value that
  is not the seed's (`kind`, `status`, `target_path`, `checksum_sha256`, `verify_method`,
  `error_message`, `size_bytes`, `triggered_by`, `encrypted`), a `finished_at` that is not ten minutes
  after `started_at`, a `verified_at` missing on the verified row or set on the failed one, a
  `deleted_at` set on either (a deleted artefact no longer counts as the last verified one), a
  missing row, a failed row that is not the latest, or any row besides these two.
- **Test databases only:** both refuse a database not named `test` or `*_test`, with `FixtureRefused`
  and before anything else is sent: the app's role cannot delete a backup row. `seed_backups` needs
  a `now` with a timezone (`ValueError` otherwise); `check_backups` takes none.

## The payloads

`payloads/` holds JSON bodies of the contract's models, each a state the server can send: a
`HealthReport` (`GET /admin/health`) or an `AdminOverview` (`GET /admin/overview`). A harness answers
the read with one in place of the real call. Each validates against its model and dumps back to
itself, and `test_admin_payload_fixtures.py` scans its strings for secrets and holds it to the
producer: a health report to the registry's names (all ten required components), `overall` as the
worst state and the keys `render_report` sends (`detail: ""` and `last_good_at: null` included, no
`alerts_active`: the server omits it); an overview to the slices and fields the service reads, and
its failed slice to the detail the fan-out gives it.

```python
import json
from pathlib import Path

payload = json.loads(Path("tests/fixtures/admin/payloads/health_degraded.json").read_text("utf-8"))
```

| File                          | Handle                | Model and state                                                          |
| ----------------------------- | --------------------- | ------------------------------------------------------------------------ |
| `health_degraded.json`        | HEALTH-SUB002-WS-DOWN | `HealthReport`: `bybit_private_ws` degraded, its detail naming `sub_002` |
| `health_outage.json`          | none: #962's outage   | `HealthReport`: `postgres` and `questdb` down, so `overall` is down      |
| `overview_recorder_down.json` | HEALTH-RECORDER-DOWN  | `AdminOverview`: the recorder slice `error`, `source failed`             |
| `overview_recorder_hang.json` | HEALTH-RECORDER-HANG  | `AdminOverview`: the recorder slice `error`, `timed out after 300 ms`    |

- **Ten components, not fifteen:** a real `GET /admin/health` sends five rows more than a health
  payload, which holds the ten required components only. The five more are `hot_tier_write_behind`,
  `ingestion`, `secrets`, `bars` and `bars_writer`, which `app.py` registers. No plan case reads them.
- **No stack switch makes a health payload:** on this `main` the registry holds `oms`, `rule_engine`,
  `recorder`, `bybit_rest` and `bybit_private_ws` as `not_deployed` placeholders, so a state of
  theirs, HEALTH-SUB002-WS-DOWN's degraded `bybit_private_ws` included, is a harness's, served in
  place of the real call.
- **Two recorder handles, a file each:** AD-S01-03 runs both, and a failed read and a read that
  outran the fan-out's 300 ms budget carry different details; "Error — timed out after 300 ms
  [Retry]" is the second's. Both are `error`, the status that gives the tile its Retry. On this
  `main` the real recorder slice is always `unavailable`, so no stack switch makes either.
- **The outage** has no handle in the plan's §1: #962 asks for it, and no case uses it yet.
- **The clock:** every instant is `2026-10-22T12:00:00Z` or minutes before. A browser draws "as of"
  and "stale since" from its own clock, so a suite that asserts them freezes it at that instant.
- **HEALTH-TIMEOUT and OVERVIEW-503** are behaviours of a harness (a health read that times out, an
  overview that answers `503`), not payloads.

## The corrupted chain (AUDIT-CORRUPT)

Into a migrated test database, from `services/api`:

```python
from pathlib import Path

from tests.fixtures.admin.corrupt_chain import seed_corrupted_chain
from tests.integration import _refused

pg_dsn = _refused.pg_dsn  # a migrated Postgres 16 whose database is named `test`


async def test_verify_reports_the_victim(pg_dsn: str, tmp_path: Path) -> None:
    victim = await seed_corrupted_chain(pg_dsn, tmp_path)  # tmp_path holds the writer's WAL file
    ...  # POST /admin/audit/verify over this database now answers first_bad_id == victim
```

- **What it writes:** seven entries through the real append path, so the trigger chains them, by a
  writer it builds on `pg_dsn` (not one of yours: it cannot point at another database). Then it
  alters the fourth behind the chain, its `reason` only, and answers that entry's id: the
  `first_bad_id` that `POST /admin/audit/verify` must report.
- **Deterministic in shape:** the seven entries, the victim's position (the fourth, `object_id`
  `fixture-3`) and the forged `reason` are fixed. Row ids, `record_id`, `event_ts` and the hashes
  differ on every run, as the writer draws them.
- **The verify range must hold the victim:** a body of `{}` verifies only the newest 1,000,000 ids
  (`audit_verify_max_span`; each entry takes two ids), about 500,000 entries. A chain with more rows
  after the victim than that needs a `from_id` at or below the victim's id and within
  `audit_verify_max_span` of it: the range then holds that many ids from `from_id` on, or stops at
  the head if that is nearer (`audit/query.py`).
- **Who can run it:** altering a row behind the chain needs the owner of `audit_log` (the role that
  ran the migrations), as an attacker holding the owner role would: the test container's user. The
  app's role holds no `UPDATE`. The append-only trigger is off inside one transaction only, so a
  failure, a lost connection among them, rolls the alteration back.
- **Idempotent:** a second run writes no entry, alters nothing and answers the same id.
- **Test databases only, because it is permanent:** audit rows can never be removed, so an altered
  chain stays so for the life of its database. A database not named for tests is refused with
  `FixtureRefused` before an entry is written, whether the alteration's connection or the writer's
  pool reaches it.
- **Self-checking:** `FixtureCheckError` when the chain does not hold exactly the seven entries, or
  when `trg_audit_append` is not enabled after the seed. The alteration rolls back with its own
  transaction, so a crash of the fixture cannot leave the guard off; a second run reports one that
  something else left off.
- `tests/integration/admin/test_admin_corrupt_chain_pg.py` runs it through the verify route on
  Postgres 16, and `tests/unit/test_admin_corrupt_chain_fixture.py` shows each guard on a fake
  connection.

## The flag overrides (FLAG-OVERRIDE-ROWS)

Into a migrated test database that holds slice A's world, from `services/api`:

```python
from tests.fixtures.admin.flag_overrides import check_flag_overrides, seed_flag_overrides

async with engine.begin() as conn:
    await seed_flag_overrides(conn)
    await check_flag_overrides(conn)
```

- **What it writes**, into `feature_flags` and `feature_flag_overrides`, as a database writer would,
  for AC-ADM-09 (AD-S05-N03; AD-S05-03 reads the unreadable row):
  - a role override (`owner`) and a user override (MGR-M), both `true`, on each safety flag,
    `trading.live_enabled` and the kill switch `maintenance.mode`: neither takes an override, so each
    resolves to its stored `false` for both;
  - an unreadable row: `algo.twap` stored as the string `"on"`, which no boolean flag can hold, with
    a role override (`owner`) of `true`. Readable, it would resolve `true` for an Owner; unreadable,
    it fails closed to `false`, its override ignored. Slice A's flags are not touched, and no other
    handle reads `algo.twap`.
- **The world first:** it needs OWNER, MGR-M and the live gate's row (`world.py` checks them) and
  never writes them. A missing one is a `FixtureCheckError` naming it, before any row is written.
  `maintenance.mode` is not slice A's: the seed adds its row, `false` and a kill switch, if it has
  none, and leaves a value already stored.
- **Idempotent and self-checking:** the unreadable value is an `ON CONFLICT DO UPDATE` that writes
  only a different value, the overrides `DO NOTHING`, so a second run changes no row.
  `check_flag_overrides` builds each flag as the store holds it from the rows read back, and asserts
  with the app's own `resolve` that each caller gets the closed value: each safety flag its stored
  `false`, `algo.twap` its fail-closed `false`. It names a changed value, a lost override, or an
  unreadable row made readable.
- **Slice A's check still passes after it:** the seed writes no row of slice A's, and its Postgres
  case runs `check_admin_world` after it.
- **Seed it again right before AD-S05-N03:** the plan runs AD-S05-05 first, and a successful `PUT` on
  a safety flag keeps no user override (`admin/flags/writes.py`), so it deletes MGR-M's row on
  `maintenance.mode`. A second seed puts that row back and leaves a stored value as it is.
- **Test databases only:** both refuse a database not named `test` or `*_test`, with
  `FixtureRefused` and before a row is read.

## The out-of-band writes (OOB-WRITES)

```python
from tests.fixtures.admin.oob_writes import check_oob_writes, seed_oob_writes

async with engine.begin() as conn:  # a transaction: a failed write rolls the role switch back
    await seed_oob_writes(conn, now=now)
    await check_oob_writes(conn)
```

- **What it writes**, after `SET ROLE cv_app` and with no audit record, for AC-ADM-31: an Owner role
  row for MGR-M, a second grant for MGR-M (SUB-T beside SUB-S), `trading.live_enabled` set to
  `true`, and a backup's digest set. The case shows each write captured once the change capture of
  SR-E42-06 exists (#3196).
- **The backup is its own:** OOB-BACKUP is made first, as the session's user, finished and with no
  digest, and the write sets one. `0032_backups_write_once` refuses a change to a digest already
  set, for every role, so a digest can only be set. The row shares no database with `seed_backups`,
  whose check refuses a backup that is not its own two: the seed refuses a database holding one.
- **A database of its own:** `check_admin_world` fails after it, by design: it names MGR-M's second
  grant, the extra role and the set live gate. So does `check_flag_overrides`, which expects the gate
  off: OOB-WRITES shares no database with FLAG-OVERRIDE-ROWS or FLAG-LIVE-BLOCKED. Seed the world and
  check it first. The Postgres test runs it in `oob_test`, migrated after its stand-in `cv_app` got
  the bootstrap's default privileges, so the migrations' revokes apply to the stand-in too.
- **The world first:** MGR-M, SUB-S, SUB-T and the live gate's row; a missing one is a
  `FixtureCheckError` naming it. The role `cv_app` must exist too: the shipped bootstrap creates it,
  and the Postgres test makes a stand-in.
- **Idempotent and self-checking:** each write is conditional (`DO NOTHING`, an update only where
  the value differs, the digest only where none is set), so a second run writes nothing.
  `check_oob_writes` names each write that is not in the rows.
- **Test databases only, and the test container's login:** it refuses, with `FixtureRefused` and
  before a row is read, a database not named `test` or `*_test`, and a session not logged in as
  `test`, the user of the test container. The writes leave a standing privilege and a set live
  gate; `seed_admin_world` puts the gate back, and nothing removes the role row or the grant.

## The forged seal (SC-FORGED-SEAL)

```python
from tests.fixtures.admin.forged_seal import check_forged_seal, seed_forged_seal

await seed_forged_seal(relational, keys, now=now)  # keys: the test's own `HmacKeys`
await check_forged_seal(relational, keys, now=now)
```

- **What it writes:** the degraded snapshot's row (SC-CHAIN-TRIPS) with its snapshot changed after it
  was sealed (the trips cleared), through the same `SnapshotAdapter`. Its HMAC no longer holds, so the
  inspector leaves it out, `snapshots` says `error` with "snapshot seal did not verify", and the list
  is empty (AD-T07-N01). It takes that row's key, order `0a000000-0000-4000-8000-0000000000c7` in
  `demo`: a database holds one of SC-FORGED-SEAL and SC-CHAIN-TRIPS, and the later seed replaces the
  earlier row. Like that row it carries no drain seal, so a `Restorer` refuses it.
- **The key is the caller's:** the row is sealed with the `HmacKeys` passed in, and the fixture
  holds no key.
- **In process:** `forged_row` builds the same row without a database, and `check_left_out` checks
  any rows read back. The plan runs AD-T07-N01 in process only, over an injected store.
- **Idempotent and self-checking:** a second run rewrites the same row (an upsert), and the check
  passes again. `check_forged_seal` raises
  `FixtureCheckError` unless the row is there once, its seal fails on the HMAC (not on an unknown
  key or a hash) and the inspector, reading it back with the same keys, lists nothing and says
  `error`. The critical `system_events` row AD-T07-N01 expects is not written by the inspector yet.
- **Test databases only:** a database not named for tests is refused with `FixtureRefused` before
  any read.
- `tests/integration/admin/test_admin_fixture_b4a_pg.py` runs the three seeds on Postgres 16,
  OOB-WRITES in its own database as `cv_app` through a stand-in role.

## The degraded snapshot (SC-CHAIN-TRIPS)

```python
from tests.fixtures.admin.latched_machine import check_latched_machine, seed_latched_machine

await seed_latched_machine(relational, keys, now=now)  # keys: the test's own `HmacKeys`
await check_latched_machine(relational, keys, now=now)
```

- **What it writes:** one `machine_snapshots` row, through the composition root's `SnapshotAdapter`:
  order `0a000000-0000-4000-8000-0000000000c7` in `demo`, triggered with its stop-loss present, two chain
  trips and two deferred events, and its two leaf ids as `state_ids`, as cv-api writes a snapshot. The
  inspector lists it degraded, as `order:<id>` (AD-S08-01). `latched_row` builds the same row without a
  database, for a test that serves it from a fake store. The handle and the code keep their names
  (`SC-CHAIN-TRIPS`, `latched_*`); the row is a degraded snapshot until something restores it.
- **The key is the caller's:** the row is sealed with the `HmacKeys` passed in, and the fixture holds no
  key. A deployed cv-api has no provider that opens snapshot seals yet (#2701), so its inspector lists
  nothing; the row is for a test that opens it with the same test provider.
- **Not a restorable machine:** the latch is process memory, set only by a successful `Restorer.restore`
  of a drain-sealed snapshot of the library's shape. This row is the shape the inspector reads, with no
  drain seal (`cv_epoch`), so a `Restorer` refuses it and no latch is set
  (`test_admin_latched_machine_fixture.py` shows the refusal).
- **AD-S08-02 and AD-S08-03 need more:** acknowledging a latch waits on its operation (Q-7), and also on
  a restorable seed that this fixture does not make: the plan's SC-CHAIN-TRIPS text says "restored".
- **Idempotent and self-checking:** the same keys and `now` give the same row, so a second run rewrites
  it unchanged; `check_latched_machine` raises `FixtureCheckError` unless the inspector, reading the rows
  back with the same keys, lists it degraded with its trips and deferred events.
- **Test databases only:** a database not named for tests is refused with `FixtureRefused` before any
  read, and before the keys are used.
- `tests/integration/admin/test_admin_latched_machine_pg.py` seeds it twice, compares the stored row after
  each seed and checks it on Postgres 16.

## The 10 M-row audit dataset (AUDIT-10M)

```python
from tests.fixtures.admin.audit_10m import load_audit_10m

load_audit_10m(psycopg_dsn)  # about 30 to 45 minutes through the chain trigger
```

- **What it writes:** ten million synthetic `audit_log` rows for the search budget (AD-S04-01), made
  inside Postgres by E42-K01's set-based SQL (`bench/audit_index/ci_spike.py`), so nothing is stored,
  numbered from 0 as K01 numbers them. It also inserts the 50 `users` rows the rows reference
  (`seed_users_sql`: active, no role, an unusable password hash, `ON CONFLICT DO NOTHING`), which add 50
  to an admin user list's count. It ends with `ANALYZE audit_log`, as K01's load ended with a
  `VACUUM (ANALYZE)`, so the planner has statistics before a measurement.
- **What is deterministic:** the row count, the time span (from 2026-01-01 over 365 days, evenly spaced)
  and the 50 users `user_00` to `user_49`; after `setseed`, each row's action, severity, outcome,
  environment and state, on the same Postgres version. `record_id`, `session_id` and `request_id` come
  from `gen_random_uuid()` and differ on every load; no case names one.
- **Chained or bulk:** by default the rows go through the chain trigger, so a verify over a range of them
  passes (E42-K01 measured 0.18 to 0.27 ms a row, from one 100,000-row batch on a shared runner: about
  30 to 45 minutes for the set). `chained=False` is K01's bulk load with the trigger off for the load
  only, and placeholder hashes (`prev_hash` is 64 zeros on every row, as K01's SQL writes it), so a
  verify reports the first row; use it for the search budget alone. Unlike K01's, which dropped the five
  secondary indexes for its load, it keeps them, so it is slower than K01's 506 s.
- **A verify covers a range:** a verify with no bounds covers only the newest `audit_verify_max_span`
  ids (1,000,000: about 500,000 entries since 0045), so "a verify over them passes" holds for a range
  (`from_id` and `to_id`) of a chained load, not for the whole set. Loaded after AUDIT-CORRUPT, the set
  pushes the altered entry out of an unbounded verify's window, and a bulk-loaded database must not also
  host AUDIT-CORRUPT: its verify reports the first bulk row, not the victim.
- **Locks:** a chained batch holds the chain's advisory lock while it inserts its 250,000 rows (about a
  minute), so no other audit writer runs during a batch; each batch commits on its own, so another
  writer can run between two. The bulk load holds `audit_log`'s table lock for the whole load. Both are
  for test databases only. The loader takes a session advisory lock on its own connection, so two
  loaders never both load: the second waits, then finds the rows.
- **The bulk load is one transaction:** it reads the trigger's state, runs `DISABLE TRIGGER`, the inserts
  and `ENABLE TRIGGER`, reads the state again, and only then commits. An error, a cancellation or a
  killed loader rolls the trigger state back with the rows, and a trigger found off before the load or
  after it is a `FixtureCheckError` that commits nothing. `DISABLE TRIGGER` needs the table's owner (the
  role that ran the migrations: the test container's user), not a superuser. Every run, the second
  included, ends with `trg_audit_chain` enabled or a `FixtureCheckError`; a trigger found off is not
  repaired, so enable it with `ALTER TABLE audit_log ENABLE TRIGGER trg_audit_chain`. The one
  exception is a bulk load that finds it off after its own `ENABLE`: the rollback has restored it, and
  the message says so, with no recovery line.
- **Idempotent:** a second run in the same mode finds the dataset's rows and loads nothing. A call in the
  other mode is refused with `FixtureCheckError` naming both modes: a bulk set holds the genesis
  `prev_hash` on every row, a chained set on at most its first. A partly loaded dataset is refused too,
  once its trigger is read (one found off is reported first): audit rows can never be removed (C-5.7),
  so load into a fresh test database. The dataset's rows are those labelled `user_00` to `user_49`: no
  other seed may use that label shape.
- **Test databases only:** a database not named for tests is refused with `FixtureRefused` before any
  read. No test loads 10 M rows: `tests/unit/test_admin_audit_10m_fixture.py` checks the batches, the SQL
  and the guards over a fake, and `tests/integration/admin/test_admin_audit_10m_pg.py` loads 600 rows in
  both modes on Postgres 16, and shows that a bulk load that fails, or whose connection is killed
  mid-transaction, leaves the trigger on and no row.
