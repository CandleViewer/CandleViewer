# Runbook — account fixture stack (#2893)

Owner: infra-devops (with accounts-admin for the seed and the driver). Code:
`infra/scripts/account_fixture_stack.py`, `infra/compose/docker-compose.account-fixture-real.yml`,
`services/api/cvdev/account_fixture/seed.py` and `services/api/cvdev/account_fixture/drive.py`. ADR-0036
decision 9 (S16a); threat rows FX-S03, FX-I02, FX-I03, FX-T02 and FX-E02 in `E27-accounts.md` §12.

A dev and test stack only. It runs the real backend (Postgres storage, sign-in with TOTP, the key vault) on the
dev-only account fixture transport, so the E27 pack's scenarios (`packages/fixtures/accounts/`) can be loaded
through the shipped key pipeline and recorded. It holds no real key and talks to no exchange: the transport answers
the pack's fabricated keys alone, on the demo hosts alone, and the S8 boot guard refuses any other stored key before
a module starts. Never run it against a database or a host that holds anything real.

## What `up` does

```bash
python3 infra/scripts/account_fixture_stack.py up            # prints the project name, cv-acctfix-<6 hex>
```

1. **Host checks.** The project is `cv-acctfix-<6 hex digits>` (a new one each run, or `--project`; never
   `cv-demo` or any other name), nothing of it is left over (container, network or volume), and the host's
   loopback ports it publishes are free.
2. **The run directory**, `$XDG_RUNTIME_DIR/<project>` (else under `/dev/shm`): mode 0700, flat, on tmpfs, gone at
   `down` or at reboot. It holds `stack.env` (0600, the user's: the Postgres password and DSNs, the pepper and the
   three auth keys, each new per run, the paths compose needs, free ports, inert values for the stores that never
   start), then what the one-shot writes as root: `kek` and `lane.key` (0400), `pw-<user>` (0400),
   `totp-<user>` (0600), `roster.json` and `.seeded` (0444). The invoking user can unlink root's files there but
   cannot read them; the stack's containers read them as root.
3. **Postgres and QuestDB** (`up --wait`), then **the schema step** (`run --rm migrate`, with the `core` and
   `migrate` profiles: on the dev stack `cv` owns the schema, so the owner DSN is the app DSN), then
   **`fixture-init`** (`python -m cvdev.account_fixture.seed init`: the gate, the run's KEK and audit lane key, the
   six users and their TOTP enrolment, the marker), then **the api** (`up --wait`: healthy behind the S8 boot
   guard, which passes on the seeded database).

`up` prints the step names and, last, `account-fixture-stack: up: <project>`. A step that fails ends `up` with
`account-fixture-stack: refused: the <step> step exited <n>: take the project down`; take it down and run `up`
again. The seed's refusals are one fixed line each (`account-fixture: refused: ...`): the gate's legs are listed in
the seed module's docstring.

**On a host that runs another stack** whose network holds the base file's `172.28.0.0/24` (the demo host's
`cv-demo`), give `up` and every later command a lane-local file with a private /24 of its own, outside the checkout
(the compose lint reads every `docker-compose*.yml` in `infra/compose/`, and `!override` is not plain YAML):

```yaml
networks:
  cv-internal:
    ipam:
      config: !override
        - subnet: <a private /24 that no network of this host uses>
services:
  api:
    environment:
      CV_BIND_HOST: <its .10 address>
      CV_METRICS_BIND: <its .10 address>:9108
      CV_MESH_CIDRS_CSV: <the same /24>
    networks:
      cv-internal:
        ipv4_address: <its .10 address>
```

```bash
S=infra/scripts/account_fixture_stack.py
python3 $S up -f /path/to/lane-net.yml        # then -f /path/to/lane-net.yml on every command below
```

**Expected log noise** on this stack: `secrets.kek_file_source` (a file KEK, a warning in demo),
`recording_volume_shared` and `recording_refused` (recording only), `storage_guarded_privileges_privileged_role`
(the dev stack's `cv` login is a superuser, so the grants-based append-only property of the audit log is not shown
here) and `key_selfcheck_no_keys` at boot. Neither `secrets.kek_unavailable` nor `kek_handle_permissions` is
expected: either means a run-directory file is not root's 0400 one.

## Restart the api with another stack default

The stack default (`CV_ACCOUNT_FIXTURE`) answers traffic that carries no key (ADR-0036 decision 6). Two scenarios
need it as the default (`demo_ws_unreachable`, `ws_auth_then_drop`); every other key scenario is served per key.

```bash
python3 $S restart-api --project <project> --default demo_ws_unreachable
```

## Take it down

```bash
python3 $S down --project <project>
```

`down -v --remove-orphans` with every profile active (every service here has a profile, so with none active
compose removes nothing), then the run directory is unlinked, then the project's containers, networks and volumes
are listed by their compose label: the line ends `0 containers, 0 networks, 0 volumes left; run directory
removed`. A second `down` finds nothing and says the same. After a reboot (the tmpfs run directory gone, the
volumes not) `down` hands compose inert values for the variables it requires, in a temporary file it removes.

## Rules

- **Never print a value.** Never `cat` or copy `stack.env` or a run-directory file, never run
  `docker compose config` (it prints the environment; `--quiet` alone is safe) or `docker inspect`, and never put
  the run directory's path, a host port or an address in a record. The script prints names, steps, statuses and
  counts only.
- **Touch only your project.** Stop, remove or prune nothing that is not `cv-acctfix-*` and yours; never
  `docker system prune`.
- **No real key, ever.** The pack's keys are fabricated public constants (`fixture-<scenario>-NNNN`, secret
  `fixture-<scenario>-secret-not-real`); the transport answers nothing else.
