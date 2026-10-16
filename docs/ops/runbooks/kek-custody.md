# KEK custody runbook (E27-K01 FU-2, implemented by E27-T02)

Status: written 2026-10-11 against the E27-T02 branch. Design owner: `docs/plan/spikes/e27-kek.md`
and ADR-0009. No secret, key material or host-specific address belongs in this file. Host-side
launcher/systemd steps marked **FU-1** are not yet drilled on a real host (#2151).

## What the app expects

| Setting | Meaning |
|---|---|
| `CV_KEK_SOURCE` | `handle` (prod), `file` (dev/ci only — **cv-api refuses to start in `live`** with `kek_source_not_permitted`), `none` |
| `CV_KEK_HANDLE` | path yielding exactly 32 raw bytes: the read-once FIFO (`0600`, WSL launcher) or the systemd credential file (`0400`, VPS); owned by the service uid, never a symlink. **In `live` a regular file is accepted only if the opened descriptor is on tmpfs/ramfs (`fstatfs`) *and* the path is under `/run/credentials/`** (systemd `LoadCredential*=`). A Docker Compose `secrets: file:` bind mount is disk-backed and is refused (`kek_handle_permissions`) |
| `CV_KEK_VERSION` | version of the supplied KEK in this process's environment (`CV_ENV`); its KCV must match that environment's `kek_versions` row. **One KEK per environment:** live, demo and testnet each keep their own lineage, numbered from 1 (#2338). Never give a live KEK to a non-live process, or one KEK to two environments |
| `CV_KEK_PREV_HANDLE` | previous KEK, **only** during a rotation window |
| `CV_KEK_ACK_PATH` | writable path (outside the read-only handoff dir) where cv-api echoes the launcher's nonce **once, after every FIFO handle (current and previous) has been drained**. **Mandatory in `live` when any handle is a FIFO** (missing ⇒ Degraded `kek_handle_permissions`). Not used for systemd credential files (not read-once; no handoff record) |

**Handoff record format (WSL launcher).** In the handoff directory next to the FIFO the launcher
writes `handoff`: one ASCII line, `[A-Za-z0-9-]{8,128}` (the nonce), regular file, mode
`0400`/`0600`, owned by the service uid, ≤256 bytes. cv-api writes the same line to
`CV_KEK_ACK_PATH` with `O_CREAT|O_EXCL` (mode `0600`). A missing ack, a duplicate ack, or a writer
that completed without the matching ack is an extra reader: the launcher raises
`security.kek_handoff_anomaly` and stops the stack. **Ack cleanup:** the launcher deletes the ack
file before every (re)start; cv-api never overwrites one (an existing ack ⇒ `kek_unavailable`).
**FIFO fill order and location:** cv-api reads the handoff record first, then drains
`CV_KEK_HANDLE` (current), then `CV_KEK_PREV_HANDLE` (previous, rotation only), each with a 10 s
bound. The launcher must fill the **current** FIFO first, then the previous one, and both FIFOs must
sit in the same handoff directory that holds `handoff` (`dirname(CV_KEK_HANDLE)`). In live a FIFO
handle without `CV_KEK_ACK_PATH` is refused **before** any FIFO is read (fatal config error).

The KEK must never appear in compose `environment:`, `.env`, argv, logs or `Settings`. CI enforces the
compose rule (`tests/unit/credentials_m2/test_compose_kek.py`).

## Host hygiene (SR-009) — required before go-live

- Core dumps off: `ulimit -c 0` / systemd `LimitCORE=0` / compose `ulimits: core: 0`. cv-api also sets
  `RLIMIT_CORE=0` and `PR_SET_DUMPABLE=0` itself before loading the KEK and reads both back; in
  `live`, if either did not take effect it degrades with reason `process_hardening_failed`.
- Accepted residual (SR-009): Python creates immutable copies of key material (`bytes` passed to
  the AES/HMAC primitives, the decoded `str` M2 uses for the request MAC) that cannot be zeroed.
  These copies never leave `secrets/` (C-2.7, #2339): the exchange adapter gets only the hex
  signature and the key id. They do not leave in a traceback either: a failed MAC is raised as
  `CredentialUnavailable("signing_failed")` with nothing chained, after the failed call's frames
  are cleared. Zeroisation covers M2's own `bytearray` buffers only (KEK, cached DEKs, decrypted
  plaintext); the DEK cache TTL is capped at 300 s and the internal `Secret` wrappers are
  invalidated after each signing call.
- `kernel.yama.ptrace_scope >= 1`; no `SYS_PTRACE` capability on the container.
- Swap off or encrypted.
- WSL: `/etc/wsl.conf` `[interop] enabled=false`, `appendWindowsPath=false`.
- Compose `restart: "no"` for `api`; the launcher is the only restart supervisor (**FU-1**).

<a id="alert-kekunavailable"></a>

## Symptom: app is Degraded with `secrets.kek_unavailable`

Signals: `/readyz` returns `degraded` with a failing `secrets` check; `/health/report` shows the
`secrets` component `down`; every connected WS client gets the critical `system` `notice` (and every
client connecting later gets it right after `auth_ok`); `cv_kek_degraded_state` = 1 pages
`KekUnavailable`; `cv_kek_load_failures_total{reason}` increments; audit `security.kek_load_failed`;
`cv_kek_version_state` = 0. Order placement is refused, every
credential operation raises `kek_unavailable`. The log line contains this remediation verbatim:

> KEK unavailable (reason=<r>): trading disabled. Ensure the host launcher/systemd credential supplies
> CV_KEK_HANDLE, then restart cv-api via the launcher. See docs/ops/runbooks/kek-custody.md.

| reason | Check |
|---|---|
| `kek_unavailable` | handle missing, timed out (10 s), or not exactly 32 bytes; handoff nonce missing or ack already present |
| `kek_handle_permissions` | mode is not `0400` (file) / `0600` (FIFO), wrong owner, or a symlink |
| `kek_mismatch` | wrong KEK for `CV_KEK_VERSION` (KCV differs, or no KCV yet and a trial unwrap of an existing row failed; the previous KEK's KCV must already be recorded) — do **not** retry with other keys |
| `kek_reused` | the presented KEK's KCV is already recorded for another version or another environment (e.g. the same bytes supplied as current and previous, or the live KEK given to a demo or testnet process) |
| `kek_retired` | `CV_KEK_VERSION` (or the previous version) has `kek_versions.retired_at` set in this environment — a downgrade |
| `kek_version_out_of_sequence` | version is neither this environment's max recorded nor max+1 with the previous KEK = max; other environments' versions never count |
| `process_hardening_failed` | (`live`) core-dump limit or `PR_SET_DUMPABLE` could not be applied — check container/systemd limits |
| `kcv_store_unavailable` | `kek_versions` unreadable (Postgres down, schema older than `0026_kek_versions_env`) — not a custody problem; or two environments raced to enrol one KEK (`kv_kcv_unique`) — a custody problem, see `kek_reused` |
| `audit_unavailable` | the audit writer refused `security.kek_loaded`; the KEK was zeroed — fix the audit WAL/DB first |
| `no_credential_store` | (`live`) started without the Postgres credential store |

Enrolment: the first boot at a new version with no rows records its KCV and writes
`security.kek_enrolled` (with the KCV). A wrongly enrolled KCV can be re-enrolled **only while
zero `api_keys` rows exist at that version**: delete that `kek_versions` row in a maintenance
window under change control (owner + security reviewer), then restart with the correct KEK. Every
manual statement names the environment (`DELETE FROM kek_versions WHERE env = 'demo' AND
version = 3`); a version number alone matches every lineage.

Recovery: fix custody, then restart cv-api **via the launcher**. There is no runtime reload; a passing
mesh self-check never clears the KEK latch.

## KEK rotation (owner-run, maintenance window)

> **Do not start a KEK rotation until #2266 ships.** Step 1 alone (booting v(n+1) with the
> previous handle) enrols v(n+1) and is a one-way door: without the re-wrap entry point, rows left
> at v(n) become unborrowable as soon as cv-api restarts without `CV_KEK_PREV_HANDLE` (health stays
> OK; signing for those keys fails). #2266 also adds the stranded-row check and verifies the
> previous KEK before enrolling the new one.

1. Provision KEK v(n+1) in custody alongside v(n). Start cv-api with `CV_KEK_VERSION=n+1`,
   `CV_KEK_HANDLE` = v(n+1), `CV_KEK_PREV_HANDLE` = v(n).
2. Run the admin re-wrap (`secrets.rewrap_deks(n+1)`, counts only). **Not yet invocable:** no route
   or CLI calls it; the entry point, the transactional per-row audit and `kek_rotation_resumed` are
   tracked in #2266. Audit `security.kek_rotation_started`
   (with both KCVs and the invoking Owner) then `security.kek_rotated` — or
   `security.kek_rotation_incomplete` (with `done`/`left`) if any row is left; never retire v(n)
   after an incomplete record. Ciphertext and `enc_nonce` are untouched; the job
   is idempotent and resumable — if killed, rerun it. Borrows keep working throughout (rows still at
   v(n) are unwrapped with the previous KEK). A row that cannot be unwrapped is reported, audited as
   `security.kek_rotation_failed` (`key_id`, `done`) and left at v(n) — investigate before
   retiring v(n).
3. Verify the report shows `remaining = 0`, then set `kek_versions.retired_at` for v(n) of this
   environment only (`WHERE env = '<env>' AND version = <n>`), retire v(n) from custody and restart
   without `CV_KEK_PREV_HANDLE`.

## Upgrading to per-environment KEK lineages

Migration `0026_kek_versions_env` (#2338) keys `kek_versions` by `(env, version)`.

- It refuses while any `api_keys` row is usable (`revoked_at IS NULL AND status <> 'revoked'`).
  Those rows hold environment-free `v1:` wraps that cv-api no longer opens, and a migration never
  holds the KEK to re-wrap them. Revoke each such key through the audited key-management flow
  (never edit `api_keys` by hand), then run the upgrade again.
- Rows enrolled before it join `demo`. The first live boot afterwards enrols a fresh live lineage:
  compare the KCV in its `security.kek_enrolled` record (`env=live`) with the offline copy's KCV
  (SR-E27-15) before any live key is stored.
- Its downgrade refuses while one version is enrolled under two environments.

## Restore drill

Restore a dump on a host with **no** KEK: expect Degraded `kek_unavailable` and zero decryptions.
Supplying a wrong KEK gives `kek_mismatch`. Automated equivalent:
`tests/unit/credentials_m2/test_broker.py::test_broker_dump_without_kek_cannot_decrypt`.
