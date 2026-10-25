# Demo host runbook (#3180)

Status: written 2026-10-25 for #3180 against `main`; not yet run on the host. Owner: infra-devops.
The Owner's command sequence for the Bybit demo host that E29-K01 (#843) needs: manual compose from
a checkout at a pinned `main` sha, on the real backend, with a file KEK. No host name, address,
key, token or password belongs in this file. The dev deploy (`tools/ci/deploy_dev.py`,
`deploy-dev.yml` on the `[self-hosted, dev-host]` runner) does not take this overlay yet: that is
the follow-up after the spike.

## What runs

Compose project `cv-demo`, profile `core` (postgres, questdb, api), from three files in this order:
`infra/compose/docker-compose.yml`, `docker-compose.vps.yml` and `docker-compose.demo-host.yml`.
The overlay forwards to `api`, from `infra/compose/.env`, the settings the real backend needs, and
compose refuses every command while a required one is empty:

| Name in `.env`                                                                                    | On this host                                                                          |
| ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `CV_STORAGE_BACKEND`                                                                              | `real`                                                                                |
| `CV_EGRESS_IP`                                                                                    | the address the exchange sees from the host (Confidential: E27 threat model §1.2)     |
| `CV_KEK_FILE`, `CV_KEK_VERSION`                                                                   | `/etc/candleviewer/demo/kek-demo-v1.bin`, `1`                                         |
| `CV_AUTH_PEPPER`, `CV_AUTH_CSRF_KEY_HEX`, `CV_AUTH_TOTP_KEY_HEX`, `CV_AUTH_RECOVERY_HMAC_KEY_HEX` | the pepper; three different 32-byte keys as hex                                       |
| `CV_MESH_CIDRS_CSV`                                                                               | must hold `172.28.0.0/24` (cv-internal): the healthcheck and `127.0.0.1` come from it |
| `CV_ALLOWED_ORIGINS`                                                                              | empty (no browser origin) unless a web client is served                               |
| `CV_AUDIT_LANE_MAC_SOURCE`                                                                        | `/etc/candleviewer/demo/audit-lane.key`                                               |
| `CV_PG_OWNER_DSN`                                                                                 | the `cv_owner` DSN, which only the `migrate` one-shot takes                           |

- **The KEK** reaches the api only as the `cv_kek` file secret at `/run/secrets/cv_kek`
  (`CV_KEK_SOURCE=file`, `CV_KEK_HANDLE=/run/secrets/cv_kek`): never in `environment:` or `.env`,
  which hold its path and version only (`docs/ops/runbooks/kek-custody.md`). `file` is refused in
  `live`; in `demo` each boot logs the `secrets.kek_file_source` warning, which is expected here.
  `docs/plan/spikes/e27-kek.md` §4 prefers `handle` for demo; this host takes `file` (#3180).
- **`/data`** is the named volume `cv-demo_cv-api-data`: the cold tier's root `/data/parquet`, which
  the real backend requires and never creates, and the recorder WAL (each its own filesystem, step
  3a), admin jobs and audit exports.
  The image creates `/data/parquet` owned by uid 10001 (mode 0700), and Docker copies that into the
  empty volume on its first mount, as it does for the audit volume.
- **Core dumps** are off (`ulimits: core: 0`); cv-api also sets `RLIMIT_CORE=0` and
  `PR_SET_DUMPABLE=0` itself before it loads the KEK.
- `infra/scripts/lint_compose.py` checks the overlay: `api`, `migrate` and `bootstrap-owner`
  only, every value from the env file, the KEK a file secret and never a value, `/data` a named
  volume, and no log of the bootstrap's output (step 6).

## The host (provisioned 2026-10-25)

- Ubuntu 26.04 with Docker 29 and Compose v5, `cosign`, `curl` and `python3`.
- `kernel.yama.ptrace_scope` is 1, and the container gets no `SYS_PTRACE` (Docker's default).
- **Swap is on (3 GB) and not encrypted: an accepted deviation for demo.** SR-009
  (`docs/plan/04-security-program.md`) asks for swap off or on an encrypted volume. A demo key
  trades only demo funds; before this host ever holds a live key, turn swap off or encrypt it.
- `/etc/candleviewer/demo/` (root, 0700) holds the KEK and the audit lane key; the Owner's offline
  KEK copy waits for collection in root's home.
- `infra/compose/.env` (to be owned by root, 0600; step 2 checks) holds every name `.env.example`
  lists.

The pinned sha must hold #4479 (`candleviewer.bootstrap_owner`, step 6) and #4484
(`POST /exchange-accounts`, step 7). Every command below runs as root from the checkout's root,
with this prefix set once per shell:

```bash
COMPOSE="docker compose -p cv-demo -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.vps.yml -f infra/compose/docker-compose.demo-host.yml"
```

Every compose command warns that the secrets' `uid`, `gid` and `mode` are not supported outside
Swarm mode. That is expected: compose bind-mounts each file as it is, so the host files carry them.
Never run `$COMPOSE config` without `--quiet` here: it prints the env file's values.

## 1. The image: check out the pinned sha and build

The GHCR package is not anonymously pullable, so the host builds `api` from the checkout:

```bash
git fetch origin
git checkout --detach <pinned main sha>
git rev-parse HEAD
$COMPOSE --profile core build api
```

`git rev-parse HEAD` must print the pinned sha. Set `CV_GIT_SHA` in `infra/compose/.env` to it, so
`GET /admin/health` and `/metrics` report the build.

**Alternative, once the package is public: verify the image by digest.** Take the digest of the
`<version>-<12-digit sha>` tag that `main.yml` pushed for the pinned sha, and verify it with the
identity `tools/ci/deploy_dev.py` pins (the `main.yml` workflow on `refs/heads/main`):

```bash
IMAGE=ghcr.io/candleviewer/candleviewer-api
DIGEST="$(docker buildx imagetools inspect "$IMAGE:<version>-<12-digit sha>" --format '{{json .Manifest}}' | python3 -c 'import json, sys; print(json.load(sys.stdin)["digest"])')"
cosign verify \
  --certificate-identity-regexp '^https://github\.com/CandleViewer/CandleViewer/\.github/workflows/main\.yml@(?:refs/heads/main)$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  "$IMAGE@$DIGEST"
```

If `cosign verify` exits non-zero, stop here: set neither variable and do not run `up`; build from
the checkout (above) instead. Otherwise add `-f infra/compose/docker-compose.deploy.yml` as the last
file of `$COMPOSE`, set `CV_API_IMAGE_REF=$IMAGE` and `CV_IMAGE_DIGEST=$DIGEST` in `.env`, and pass
`--no-build` to `up`. The `migrate` one-shot still builds from the checkout, so keep it at the same
sha.

## 2. The secret files and their modes

Check owners, modes and sizes without reading a value:

```bash
stat -c '%n %u:%g %a %s' /etc/candleviewer/demo /etc/candleviewer/demo/kek-demo-v1.bin /etc/candleviewer/demo/audit-lane.key
test "$(stat -c '%U %a' infra/compose/.env)" = 'root 600' && echo '.env ok' || stat -c '.env is %U %a, not root 600' infra/compose/.env
comm -13 <(grep -oE '^[A-Z][A-Z0-9_]*=' infra/compose/.env | sort -u) <(grep -oE '^[A-Z][A-Z0-9_]*=' infra/compose/.env.example | sort -u)
$COMPOSE --profile core --profile migrate config --quiet
```

Expected: the directory `0:0 700`; `kek-demo-v1.bin` `10001:10001 400 32` (exactly 32 raw bytes);
`audit-lane.key` `10001:10001 400` and 64 bytes (65 with a final line feed: 64 hex digits);
`.env ok` (owned by root, mode 600: a provisioned `.env` may be the operator's, so fix it as
below); `comm` prints nothing (no name of `.env.example` is missing, and it prints names only, never
values); `config --quiet` prints nothing and exits 0. A missing required name is compose's
`required variable ... is missing a value`. Fix a mode or an owner in place with `chown` and
`chmod` (`10001:10001` and `0400` for the secret files, `root` and `0600` for `.env`): never open,
copy or print a secret file.

## 3. The schema: `migrate`

On a fresh database, create the three roles first (`21-database-schema.md` §1.1). Check:

```bash
$COMPOSE --profile core up -d --wait postgres questdb
$COMPOSE exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At' <<'SQL'
SELECT rolname FROM pg_roles WHERE rolname IN ('cv_owner', 'cv_app', 'cv_ro') ORDER BY 1;
SQL
```

If it does not list all three, run `infra/scripts/pg_bootstrap.sql` once, with the passwords that
`CV_PG_OWNER_DSN` (`cv_owner`) and `CV_PG_DSN` (`cv_app`) hold and a new one for `cv_ro`, typed at
hidden prompts and handed to `psql` on its stdin, never on a command line. They sit unescaped in the
DSNs, so use letters and digits only:

```bash
read -rs -p 'cv_owner password: ' OWNER_PW; echo
read -rs -p 'cv_app password: ' APP_PW; echo
read -rs -p 'cv_ro password: ' RO_PW; echo
{ printf "\\set owner_pw '%s'\n\\set app_pw '%s'\n\\set ro_pw '%s'\n" "$OWNER_PW" "$APP_PW" "$RO_PW"
  cat infra/scripts/pg_bootstrap.sql; } |
  $COMPOSE exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
unset OWNER_PW APP_PW RO_PW
```

Then apply both schemas (`docs/ops/runbooks/storage-migrate.md`; `--build` rebuilds `migrate` from
this checkout, as that runbook does):

```bash
$COMPOSE --profile core --profile migrate run --rm --build migrate
```

Expected: exit 0 and a `storage_migrate_done` line; a second run applies nothing and exits 0. Any
other exit is in `storage-migrate.md` ("Exit status"): do not start the api on it. On this host the
owner DSN lives in `.env`, as provisioned, where `storage-migrate.md` gives it to the one command as
a prefix: the overlay requires it for every command, and `lint_compose.py` keeps it off `api` and
`bootstrap-owner`.

## 3a. The recording volumes (SR-096)

The recorder records only when the recording root `/data/parquet` and its WAL `/data/recorder-wal`
are each their own filesystem, apart from the audit volume and the state the backend needs (SR-096).
Docker's named volumes on one disk share one device, so on such a host the api logs
`recording_volume_shared` and `recorder_startup_failed` (`RecorderWalVolumeError`) at boot and
refuses to record; trading still starts. Before the api's first start, give each an ext4 filesystem
of its own. On a one-disk host, use a sparse loop image for each, mounted inside the data volume:

```bash
$COMPOSE --profile core create api
VOL=$(docker volume inspect -f '{{ .Mountpoint }}' cv-demo_cv-api-data)
( set -eu; test -d "$VOL"; umask 077
  [ -e /etc/fstab.pre-cv-demo ] || cp -a /etc/fstab /etc/fstab.pre-cv-demo
  for spec in parquet:20G recorder-wal:4G; do
    name=${spec%%:*} img=/var/lib/cv-demo-${spec%%:*}.img
    if [ ! -e "$img" ]; then
      truncate -s "${spec##*:}" "$img.part"; mkfs.ext4 -q "$img.part"; mv "$img.part" "$img"
      mkdir -p "$VOL/$name"; echo "$img $VOL/$name ext4 loop,nofail 0 0" >> /etc/fstab
    fi
    mountpoint -q "$VOL/$name" || mount "$VOL/$name"
    rmdir "$VOL/$name/lost+found" 2>/dev/null || true
    chown 10001:10001 "$VOL/$name"; chmod 0700 "$VOL/$name"
  done
  chown 10001:10001 "$VOL"; chmod 0700 "$VOL" )
for n in parquet recorder-wal; do findmnt -no SOURCE,TARGET "$VOL/$n"; done
stat -c '%n %u:%g %a dev=%d' "$VOL" "$VOL/parquet" "$VOL/recorder-wal"
```

Expected: each `findmnt` prints a loop device at its path; `stat` prints `10001:10001 700` three
times with three different `dev` numbers, which is what the code compares (SR-096). The block stops
at its first failure. A second run formats nothing and appends nothing: an image exists only once it
is formatted, and the run mounts what is not mounted and resets the owners. The images are `0600`.
`nofail` lets the host boot without them; the api then refuses to record until `mount -a` brings
them back. A host with disks or partitions to spare mounts one per path instead, with the same owner
and mode. Before `docker volume rm cv-demo_cv-api-data` or `down -v`, `umount` both paths and drop
their `/etc/fstab` lines and images: removing the volume deletes what is mounted inside it.

## 4. Start: `up --wait`

```bash
$COMPOSE --profile core up -d --wait --wait-timeout 180 api
$COMPOSE ps api
```

Expected: `api` is `healthy`, and its log has `secrets.kek_file_source` (a warning, expected in
demo) and no `secrets.kek_unavailable`. If it does not get healthy, read
`$COMPOSE logs --tail 200 api`: `kek_handle_permissions` is the KEK file's mode or owner (step 2);
`kek_unavailable`, a KEK that is missing or not 32 bytes; `StorageTierUnavailable` naming
`storage_cold`, a `/data/parquet` that is not there (a volume first mounted by an image without it,
before step 3a: `$COMPOSE down`, `docker volume rm cv-demo_cv-api-data` while it is still empty,
then start again);
a healthcheck refused with `403`, a `CV_MESH_CIDRS_CSV` without `172.28.0.0/24`. A healthy api
with `recording_volume_shared` in its log is step 3a undone (`recorder_startup_failed` most likely
is too; its `error` field may read `[redacted:key-shape]`): run step 3a's block again, which mounts
what is missing, then `$COMPOSE restart api`.

## 5. The KCV check: `security.kek_enrolled`

The first boot enrols the KEK's check value for `demo` version 1 and writes `security.kek_enrolled`
with it, in one transaction (`kek-custody.md`, "Enrolment"). Compare it with the check value of the
file you supplied and of the offline copy before any key is stored:

```bash
$COMPOSE exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At' <<'SQL'
SELECT after_state->>'kcv' FROM audit_log
 WHERE action = 'security.kek_enrolled' AND env = 'demo' AND after_state->>'kek_version' = '1';
SELECT encode(kcv, 'hex') FROM kek_versions WHERE env = 'demo' AND version = 1;
SQL
python3 -I -c 'import hashlib, hmac, sys; k = open(sys.argv[1], "rb").read(); print(hmac.new(k, b"cv-kek-kcv-v1", hashlib.sha256).hexdigest()[:16] if len(k) == 32 else "not 32 bytes")' /etc/candleviewer/demo/kek-demo-v1.bin
```

Expected: the same 16 hex digits three times. Run the last line over the offline copy too (an
encrypted copy: decrypt it to a pipe and give `/dev/stdin` as the path), never to a file. A
different value is a wrong KEK: stop and follow `kek-custody.md` (`kek_mismatch`); a KCV can be
enrolled again only while no `api_keys` row exists at that version.

An image built before `a4859525` (#4538, the fix for #4535) stored that row's `kek_version` as
`<redacted:secret>`, and audit rows are never rewritten. So on a KEK enrolled by such an image, the
first query returns no row: drop its `kek_version` condition, and expect exactly one row for `demo`.

## 6. Bootstrap the Owner (#4479): the `bootstrap-owner` service

#4479's CLI, `python -m candleviewer.bootstrap_owner --owner <email>`, mints one invite that makes
that email the Owner and prints its token once, on its terminal. A container's output also goes to
Docker's logging driver, which would keep that print: `json-file` and `local` until the container
is removed, `journald`, `syslog` and remote drivers for good (DC-4479-02, #4479's design critique).
So the overlay runs the CLI in its own service, `bootstrap-owner`: `logging: driver: none`, a
profile that `up` never starts, and cv-api's settings for what the CLI reads, and nothing else:
`CV_ENVIRONMENT`, cv-api's database role (`CV_PG_DSN`), the KEK (`CV_KEK_SOURCE`, `CV_KEK_HANDLE`,
`CV_KEK_VERSION` and the `cv_kek` file secret) and cv-api's `CV_AUDIT_WAL_PATH` on the audit
volume, where its journal and the run lock it shares with cv-api live. Never run it as
`$COMPOSE run ... api`, whose logging driver keeps the print.

The first-run script (step 7) does this step for you. By hand, from a terminal (no `-T`, no pipe,
no `| tee`), never with `--live` on this host:

```bash
$COMPOSE stop api
$COMPOSE --profile bootstrap-owner run --rm --no-deps bootstrap-owner --owner <owner email>
$COMPOSE --profile core up -d --wait api
```

Retype the phrase it shows. It prints the token once: take it straight to step 7, over nothing that
keeps a copy. Run it with no session recorder (`script`, `asciinema`), keep the token out of any
clipboard manager's history, and once step 7 has redeemed it clear the terminal and its scrollback
(`clear; printf '\033[3J'`, and `tmux clear-history` in tmux). Its options, exit statuses and
refusals are #4479's: `docs/ops/runbooks/auth-rbac.md` §4, "Bootstrap the first Owner (O5, #4479)",
which ships with it.

## 7. Account and key import: the first-run script

```bash
infra/scripts/demo_host_owner_first_run.sh
```

Run it from a terminal, with no session recorder, and keep what it shows once (the token, the
otpauth URI, the recovery codes) out of any clipboard manager's history. It starts with step 6: it
asks for the Owner's email, stops api, runs `bootstrap-owner` on your terminal (retype the phrase;
the token is printed once), starts api, waits until it is healthy and asks you to paste the token,
which it reads silently. If it stops while api is stopped, it prints the command that starts api
again. From then on it calls `127.0.0.1:8000` only, reads every secret silently and writes nothing
to disk. Have ready the authenticator app, the Bybit demo account's UID, and its API key and secret.
Create the key at Bybit demo, on a unified trading account, with only `ContractTrade` `Order` and
`Position` (and `Derivatives` `DerivativesTrade`), no withdrawal or transfer right, and the host's
egress address (`CV_EGRESS_IP`) as its only whitelisted IP (`createApiKey` in
`22-api-openapi.yaml`). In order, it redeems the invite (a new password; the otpauth URI is shown
once, for the authenticator; the recovery codes are shown once: seal them, SR-023), signs in with
the email, steps up for `keys` (registering the account needs it too), registers the demo account
and imports the key. Each code it asks for is a new one from the authenticator.

It prints only the verification verdict fields and exits 0 with `passed: true`. A run that succeeds
first asks the terminal to clear its screen and scrollback (`CSI 3 J`) and clears tmux's history. A
terminal that ignores the request keeps its scrollback: scroll up, and clear the token, the URI or
the codes yourself if they are still there. One that stops says to clear them yourself. Clear any
clipboard history yourself either way. A refused step stops it with a message and exit 1. Once the
invite is redeemed, run it again with `--skip-invite`; once the account is registered (it shows the
id on the terminal), add `--account-id <id>`. A refused key names its rule (`key-selfcheck.md`, "Key
import: a refused key").

## 8. `/readyz` ok

```bash
curl -fsS --noproxy '*' http://127.0.0.1:8000/readyz
```

Expected: `"status":"ok"`. `degraded` names its failing check: `accounts`, the stored key or its
self-check (`key-selfcheck.md`; `CV_EGRESS_IP` must be the key's whitelisted address); `secrets`,
the KEK (`kek-custody.md`); a `storage_*` tier, step 4.

## Stopping

`$COMPOSE stop` keeps everything. `$COMPOSE down` removes the containers and keeps the volumes;
`down -v` also deletes the databases, the audit WAL and `/data`, and with them the audit trail;
after step 3a, `umount` its two filesystems first, as that step says.
