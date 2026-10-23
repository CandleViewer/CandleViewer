# Admin area fixtures (E42-Q01, #962)

The seeded handles of the admin area's black-box test plan (`docs/qa/e42-admin-test-plan.md` §1), as
code rather than a dump, so they survive schema migrations. Every value is synthetic: `example.invalid`
addresses, `fixture` labels, and ids and numeric exchange uids (the `ea_uid_fmt` check takes digits
only) derived from each handle's name with `uuid5`: the handles' rows are the same on every run. Two
things are random by design: the default profile each account gets from the `trg_ea_default_profile`
trigger, and the invite's token. Nothing here is a credential, an exchange key, a token or anyone's
personal data, and `tests/unit/test_admin_fixture_handles.py` and `test_admin_fixture_seed.py` pass
every value, and this file, through the log redactor to keep it so.

| File               | What it holds                                                                                   |
| ------------------ | ----------------------------------------------------------------------------------------------- |
| `handles.py`       | The users (every status and role), the demo accounts, the trade grants and the flags, by handle |
| `seed.py`          | `seed_admin_world` and `check_admin_world`, and the refusal of a database not named for tests   |
| `corrupt_chain.py` | AUDIT-CORRUPT: `seed_corrupted_chain`, a chain with one of its own entries altered behind it    |
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

## The corrupted chain (AUDIT-CORRUPT)

```python
from tests.fixtures.admin.corrupt_chain import seed_corrupted_chain

victim = await seed_corrupted_chain(audit_service.writer, psycopg_dsn)
```

- **What it writes:** seven entries through the real append path, so the trigger chains them. Then it
  alters the fourth behind the chain, its `reason` only, and answers that entry's id: the `first_bad_id`
  that `POST /admin/audit/verify` must report.
- **Who can run it:** altering a row behind the chain needs the database's superuser, as an attacker
  holding the owner role would. That is the test container's user.
- **Idempotent:** a second run writes no entry, alters nothing and answers the same id.
- **Test databases only:** a database not named for tests is refused with `FixtureRefused` before any read.
- `tests/integration/admin/test_admin_corrupt_chain_pg.py` runs it through the verify route on Postgres 16.
