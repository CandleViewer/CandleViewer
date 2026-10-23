# Admin area fixtures (E42-Q01, #962)

The seeded handles of the admin area's black-box test plan (`docs/qa/e42-admin-test-plan.md` §1), as
code rather than a dump, so they survive schema migrations. Every value is synthetic: `example.invalid`
addresses, `fixture` labels and uids, and ids derived from each handle's name with `uuid5`, the same on
every run. Nothing here is a credential, an exchange key, a token or anyone's personal data, and
`tests/unit/test_admin_fixture_handles.py` passes every value, and this file, through the log redactor
to keep it so.

| File         | What it holds                                                                                   |
| ------------ | ----------------------------------------------------------------------------------------------- |
| `handles.py` | The users (every status and role), the demo accounts, the trade grants and the flags, by handle |
| `seed.py`    | `seed_admin_world` and `check_admin_world`, and the refusal of a database not named for tests   |
| `README.md`  | This file                                                                                       |

## The handles

| Handle                    | Seeded as                                                                 |
| ------------------------- | ------------------------------------------------------------------------- |
| OWNER, OWNER-2            | Two active Owners                                                         |
| MGR-M, MGR-N, MGR-MANY    | Active Managers with trade grants on SUB-S; on nothing; on SUB-S, T and U |
| VIEWER-V                  | An active Viewer                                                          |
| INVITED-I                 | An invited Viewer with one open invite                                    |
| DISABLED-D, LOCKED-L      | A disabled Manager; a Manager locked for an hour after the seed's `now`   |
| MAIN, SUB-S, SUB-T, SUB-U | A demo main account and three sub-accounts, 30 days old                   |
| SUB-K                     | A demo sub-account an hour old, inside Bybit's 48-hour key restriction    |
| `trading.live_enabled`    | Off: the live gate is blocked                                             |
| `rules.graph_editor`      | On: the catalogued flag the plan's flag cases change (the plan's Q-9)     |

Sessions, step-up state and TOTP enrolment are not seeded: each is a credential or derives from one. A
suite that signs a user in enrols them through the API in its own setup.

## How to load them

Into a migrated test database, from `services/api`:

```python
from tests.fixtures.admin.seed import check_admin_world, seed_admin_world

async with engine.begin() as conn:
    await seed_admin_world(conn, now=now)
    await check_admin_world(conn, now=now)
```

- **Idempotent:** each row is written with `ON CONFLICT` on its derived id, and a flag on its key, so a
  second run with the same `now` changes nothing.
- **Self-checking:** `check_admin_world` raises `FixtureCheckError`, naming every post-condition the rows
  break.
- **Test databases only:** both refuse, with `FixtureRefused` and nothing written, any database whose name
  is not `test` or does not end in `_test`.
- **No sign-in:** every seeded user's password hash is `PLACEHOLDER_HASH`, which verifies no password. A
  suite that signs in passes a hash it computes at run time, as `password_hash=`.

`tests/integration/admin/test_admin_fixture_seed_pg.py` runs the seed twice on Postgres 16 and checks it.
