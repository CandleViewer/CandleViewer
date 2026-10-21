# Runbook — Postgres server log (#2748)

Status: written 2026-10-21 with #2748 slice 4; not yet drilled on a real host. No secret, row value,
DSN or host address belongs in this file.

## What is set, and why

The `postgres` service in `infra/compose/docker-compose.yml` starts with two server settings. The
dev stack and the VPS deploy both extend that file, and neither override replaces the command
(`infra/scripts/tests/test_lint_compose.py` pins both).

- **`log_error_verbosity = terse`.** An error's line in the server log keeps its message and drops
  its `DETAIL`, `HINT`, `QUERY` and `CONTEXT`. For an integrity error the `DETAIL` is the row:
  `Failing row contains (...)` for a CHECK or NOT NULL violation, `Key (col)=(val)` for a unique or
  foreign-key one. Those carry P1 and S column values (C-12.6, C-5.9).
- **`log_parameter_max_length_on_error = 0`.** A failed statement's bound parameters are not logged.
  This is Postgres's default; it is pinned so that nobody raises it.

Clients still receive every field. The API strips them from an error as it leaves a unit of work
(#2748 slice 1a, PR #4074), so its log lines carry the error's class, SQLSTATE and constraint name
instead.

What the server log still holds for a failed statement:

- the `ERROR:` line, with the message. A data error's message can quote the bad input (22P02:
  `invalid input syntax for type uuid: "..."`), and a trigger's `RAISE` message holds what the
  trigger formats into it. A trigger must not format a row value into its message;
- the `STATEMENT:` line (`log_min_error_statement = error`, the default). The adapters bind every
  value, so it holds `$1`-style placeholders, not values.

## Check it

On the host, from the repo root, with the files the stack was started with (the VPS deploy's shown):

```bash
docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.vps.yml \
  exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At \
  -c "SHOW log_error_verbosity" -c "SHOW log_parameter_max_length_on_error"'
```

Expected output: `terse`, then `0`.

## Apply it to a running install

The command takes effect when the container is recreated. The next deploy's
`docker compose ... up` does that, because the service's configuration changed. To apply it
earlier, in a quiet moment:

```bash
docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.vps.yml \
  up -d postgres
```

Postgres restarts, and the API's pool reconnects.

A setting given on the command line overrides `postgresql.conf` and `ALTER SYSTEM`. Do not lower
either setting on a host that holds real data. To see a failure's full `DETAIL`, reproduce it with
`psql` against a dev database: the client shows it there.
