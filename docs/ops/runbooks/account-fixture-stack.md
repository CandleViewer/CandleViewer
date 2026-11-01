# Runbook — account fixture stack (#2893)

Owner: infra-devops (with accounts-admin for the seed and the driver). Code:
`infra/scripts/account_fixture_stack.py`, `infra/compose/docker-compose.account-fixture-real.yml`,
`services/api/cvdev/account_fixture/seed.py` and `services/api/cvdev/account_fixture/drive.py`. ADR-0036
decision 9 (S16a); threat rows FX-S03, FX-I02, FX-I03, FX-T02, FX-E02 and FX-I04 in `E27-accounts.md` §12.

A dev and test stack only. It runs the real backend (Postgres storage, sign-in with TOTP, the key vault) on the
dev-only account fixture transport, so the E27 pack's scenarios (`packages/fixtures/accounts/`) can be loaded
through the shipped key pipeline and recorded. It holds no real key and talks to no exchange: the transport answers
the pack's fabricated keys alone, on the demo hosts alone, and the S8 boot guard refuses any other stored key before
a module starts. Never run it against a database or a host that holds anything real. It assumes a rootful Docker
daemon: under a rootless or user-namespace-remapped one the one-shots see the run directory as another uid's, and
the seed's gate refuses it with one fixed line.

Every command below runs from the checkout's root, with `S` set once:

```bash
S=infra/scripts/account_fixture_stack.py
```

## What `up` does

```bash
python3 $S up            # prints the project name, cv-acctfix-<6 hex>
```

1. **Host checks.** The project is `cv-acctfix-<6 hex digits>` (a new one each run, or `--project`; never
   `cv-demo` or any other name), nothing of it is left over (container, network or volume), and the five
   loopback ports it publishes are free and distinct: drawn per run, or pinned with `--port NAME=N` (NAME one of
   `POSTGRES_PORT`, `QUESTDB_PG_PORT`, `QUESTDB_ILP_PORT`, `QUESTDB_HTTP_PORT`, `CV_BIND_PORT`).
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
   guard, which passes on the seeded database; the base file makes the schema step a dependency of the api, so
   this start runs that step once more, which changes nothing on a migrated database).

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
python3 $S up -f /path/to/lane-net.yml        # and -f on restart-api and drive too; down takes no -f
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

## Drive it

The driver (`python -m cvdev.account_fixture.drive`) runs in the project's `fixture-drive` one-shot, as root, with
the run directory read-only and the project's session volume. It prints statuses and masked bodies, never a
credential, a token or a code.

```bash
D="python3 $S drive --project <project> --"            # and -f <lane file> before --, if up took one
$D signin qa-owner-1                                     # password, then a code for a TOTP step not used yet
$D call qa-owner-1 GET /me
$D call qa-owner-1 POST /exchange-accounts --body-json \
  '{"exchange":"bybit","environment":"demo","kind":"main","label":"QA Main","exchange_uid":"90000001"}'
```

- **`signin <user>`** reads the user's password and TOTP secret from the run directory, signs in, waits for a 30 s
  step the user has not used (the api refuses a replayed step: a sign-in right after another one waits up to
  30 s), checks `GET /me` and keeps the session (the bearer, the CSRF token, the last step used) in a 0600 file in
  the session volume. An expired session later answers `401 unauthenticated`: sign in again.
- **`call <user> <METHOD> <PATH> [--body-json JSON]`** sends one request with the session: the bearer, the
  `__Host-cv_csrf` cookie and, on a write, its `X-CSRF-Token` header and a new `Idempotency-Key`. A
  `403 step_up_required` is answered on the spot (the password and a code for an unused step, with the
  challenge's id), and the held request is sent again unchanged, its key included. It prints
  `HTTP <status> <problem code or ->` and the answer's body, every credential and token in it masked.
- **`scan <PATH>...`** counts, per path, how often any value this run generated appears in it (the run
  directory's files, the env file's secrets, the sessions' tokens): counts only, exit 1 on any hit; a path over
  64 MiB is refused, never counted in part. Copy a record or a saved log into the run directory first (the
  invoking user owns it) and scan it at `/run-dir/<name>`.

**Loading a scenario** (the E27 test plan's section 11 load check): store the scenario's pack key on the account
its manifest's `tester_inputs` names (`QA Main`, UID `90000001`, or `QA Sub 1`, UID `90000011`), with the derived
secret and `expected_uid`:

```bash
$D call qa-owner-1 POST /exchange-accounts/<account id>/keys --body-json \
  '{"api_key":"fixture-compliant-0001","api_secret":"fixture-compliant-secret-not-real","label":"compliant","expected_uid":"90000001"}'
```

The answer holds the pipeline's verdict; the stub's side is in the request log, `requests.jsonl` in the api's
`CV_ACCOUNT_FIXTURE_DIR` (`docker compose ... exec api`; leave its `host` field out of a record), and the audit
actions in Postgres. An account holds one key: revoke it (`DELETE /exchange-accounts/<id>/keys/<key id>`) before
the next. On a loaded host a revoke can answer `503 store_unavailable` (its consequence reads are bounded at
250 ms each): send it again. `rate_limited_10018` makes the adapter hold every REST call of the stack for 10
minutes (the IP-level back-off, `24-internal-schemas.md` §8.6), so load it last, or wait out the hold
(`bybit_ip_hold_remaining_seconds` on the api's metrics). A stub-half scenario is stored, then switched with the
switch CLI
(`exec api python -m cvdev.account_fixture.cli switch <key id> [--to S]`, packages/fixtures/accounts/README.md),
or needs the stack default (`restart-api --default`, above). A key switched to a scenario that rejects it leaves the
account's exposure unreadable, so its revoke answers `409 exposure_unknown`: switch a stub-half key back
(`switch <key id> --to compliant`) before you revoke it.

## Take it down

```bash
python3 $S down --project <project>
```

`down` goes by the project name alone: `docker compose -p <project> down -v --remove-orphans`, run from an empty
directory, so compose reads no compose file and no env file and needs no `-f`, no run directory and no value.
Then the project's containers, networks and volumes are listed by their compose label, and only when that lists
nothing is the run directory unlinked: the line ends `0 containers, 0 networks, 0 volumes left; run directory
removed`. A second `down` finds nothing and ends `; no run directory`. After a reboot (the tmpfs run directory
gone, the volumes not) `down` works the same way.

`down` removes no image: the api, the schema step and both one-shots are built here, and compose tags each by the
project's name and the service's. After `down`, list those images by the project's name prefix and remove each by
its id (`docker image ls`, then `docker image rm <id>`); a new project name builds them again.

**A failed `down`** (compose exits non-zero, or the label still lists something) keeps the run directory and ends
`run down again` with exit 1: run the same `down` again; it needs nothing but the project's name. A project a
reboot or an interrupted `up` left behind is found by its label:

```bash
docker volume ls --filter label=com.docker.compose.project --format '{{.Label "com.docker.compose.project"}}' | sort -u
```

(`docker ps -a` and `docker network ls` take the same filter and format); take down only the `cv-acctfix-*`
projects you started.

## Rules

- **Never print a value.** Never `cat` or copy `stack.env` or a run-directory file, never run
  `docker compose config` (it prints the environment; `--quiet` alone is safe) or `docker inspect`, and never put
  the run directory's path, a host port or an address in a record. The script prints names, steps, statuses and
  counts only.
- **Touch only your project.** Stop, remove or prune nothing that is not `cv-acctfix-*` and yours; never
  `docker system prune`.
- **No real key, ever.** The pack's keys are fabricated public constants (`fixture-<scenario>-NNNN`, secret
  `fixture-<scenario>-secret-not-real`); the transport answers nothing else.
