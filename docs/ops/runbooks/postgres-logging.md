# Runbook — Postgres server log (#2748)

Status: written 2026-10-21 with #2748 slice 4; not yet drilled on a real host. No secret, row value,
DSN or host address belongs in this file.

## What is set, and why

The `postgres` service in `infra/compose/docker-compose.yml` starts with two server settings. The
deploys start that file with `docker-compose.dev.yml` (`tools/ci/deploy_dev.py`,
`DEFAULT_COMPOSE_FILES`). Neither that override nor `docker-compose.vps.yml` replaces the command;
`services/api/tests/unit/storage/test_postgres_server_log.py` pins both facts.

- **`log_error_verbosity = terse`: the control.** An error's line in the server log keeps its
  message and drops its `DETAIL`, `HINT`, `QUERY` and `CONTEXT`. For an integrity error the
  `DETAIL` is the row: `Failing row contains (...)` for a CHECK or NOT NULL violation,
  `Key (col)=(val)` for a unique or foreign-key one. Those carry P1 and S column values (C-12.6,
  C-5.9).
- **`log_parameter_max_length_on_error = 0`: defence in depth.** It is Postgres's default. A failed
  statement's bound parameters would be logged as a `CONTEXT` line, which `terse` already drops; the
  pin keeps them out if the verbosity is ever relaxed.

Clients still receive every field. From #2748 slice 1a (#4074) on, the API strips them from an
error as it leaves a unit of work, so its log lines carry the error's class, SQLSTATE and
constraint name instead.

What the server log still holds for a failed statement:

- **The `ERROR:` line, with the message.** A data error's message can quote the bad input (22P02:
  `invalid input syntax for type uuid: "..."`). A trigger's `RAISE` message holds what the trigger
  formats into it. A trigger must not format a row value into its message; none does today.
- **The `STATEMENT:` line** (`log_min_error_statement = error`, the default). It is the statement's
  text:
  - The API binds every value, so its statements hold `$1`-style placeholders.
  - A statement written with a literal is logged with it. A failed `CREATE ROLE ... PASSWORD '...'`
    or `ALTER ROLE ... PASSWORD '...'` logs the password. Set a role's password with `psql`'s
    `\password`, which sends a hashed verifier, or run that session with
    `SET log_min_error_statement = panic`.

On a host that holds real data, do not:

- lower either setting;
- raise `log_statement` above `none`;
- turn on `log_min_duration_statement` or `auto_explain`.

## Check it

On the host, from the repo root, with the deploy's files:

```bash
docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.dev.yml \
  --profile core exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At' <<'SQL'
SELECT name, setting, source FROM pg_settings
 WHERE name IN ('log_error_verbosity', 'log_parameter_max_length_on_error');
SELECT count(*) FROM pg_db_role_setting
 WHERE array_to_string(setconfig, ',') LIKE '%log_error_verbosity%'
    OR array_to_string(setconfig, ',') LIKE '%log_parameter_max_length_on_error%';
SQL
```

Expected output: `log_error_verbosity|terse|command line`,
`log_parameter_max_length_on_error|0|command line`, then `0`. The last line counts the role and
database overrides of either setting; a non-zero count means one of them changes the setting for
someone, and is a finding.

## Apply it to a running install

The command takes effect when the container is recreated. The next deploy's
`docker compose ... up` does that, because the service's configuration changed. To apply it
earlier, in a quiet moment:

```bash
docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.dev.yml \
  --profile core up -d postgres
```

Postgres restarts. The API's pool reconnects; requests in flight at that moment fail once. If the
stack was started with `docker-compose.vps.yml`, use it in place of the dev file in both commands.

## Who can change it

A setting given on the command line overrides `postgresql.conf` and `ALTER SYSTEM`. It does not
override an `ALTER DATABASE ... SET`, an `ALTER ROLE ... SET` or a session's `SET`:

- Only a superuser can change `log_error_verbosity`.
- The API's bootstrapped role, `cv_app` (`infra/scripts/pg_bootstrap.sql`), is not a superuser. With
  the compose file's default DSN, the API connects as the image's `POSTGRES_USER`, which is one.
- The application never sets either setting.

To see a failure's full `DETAIL`, reproduce it with `psql` against a dev database: the client shows
it there.
