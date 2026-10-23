# Admin area fixtures (E42-Q01, #962)

The seeded handles of the admin area's black-box test plan (`docs/qa/e42-admin-test-plan.md` §1), as
code rather than a dump, so they survive schema migrations. Every value is synthetic: `example.invalid`
addresses, `fixture` labels, and ids and numeric exchange uids (the `ea_uid_fmt` check takes digits
only) derived from each handle's name with `uuid5`: the handles' rows are the same on every run. Two
things are random by design: the default profile each account gets from the `trg_ea_default_profile`
trigger, and the invite's token. Nothing here is a credential, an exchange key, a token or anyone's
personal data, and `tests/unit/test_admin_fixture_handles.py`, `test_admin_fixture_seed.py` and
`test_admin_corrupt_chain_fixture.py` pass every value, and this file, through the log redactor to
keep it so.

| File               | What it holds                                                                                   |
| ------------------ | ----------------------------------------------------------------------------------------------- |
| `handles.py`       | The users (every status and role), the demo accounts, grants, flags, and the backups, by handle |
| `seed.py`          | `seed_admin_world`, `seed_backups` and their checks, and the refusal of a non-test database     |
| `corrupt_chain.py` | AUDIT-CORRUPT: `seed_corrupted_chain`, a chain with one of its own entries altered behind it    |
| `payloads/`        | The health reports and the overview, as JSON bodies of the contract's models                    |
| `README.md`        | This file                                                                                       |

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
  is not the seed's, a `verified_at` missing on the verified row or set on the failed one, a missing
  row, a failed row that is not the latest, or any row besides these two.
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
  (`audit_verify_max_span`; each entry takes two ids). A chain with more rows after the victim than
  that needs a `from_id` at or below the victim's id.
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
  when `trg_audit_append` is not enabled after the seed (a second run reports a guard a crashed
  run left off).
- `tests/integration/admin/test_admin_corrupt_chain_pg.py` runs it through the verify route on
  Postgres 16, and `tests/unit/test_admin_corrupt_chain_fixture.py` shows each guard on a fake
  connection.
