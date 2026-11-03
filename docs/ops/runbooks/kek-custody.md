# KEK custody runbook (E27-K01 FU-2, implemented by E27-T02)

Status: written 2026-10-11 against the E27-T02 branch. Design owner: `docs/plan/spikes/e27-kek.md`
and ADR-0009. No secret, key material or host-specific address belongs in this file. Host-side
launcher/systemd steps marked **FU-1** are not yet drilled on a real host (#2151).

## What the app expects

| Setting              | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `CV_KEK_SOURCE`      | `handle` (prod), `file` (dev/ci only — **cv-api refuses to start in `live`** with `kek_source_not_permitted`), `none`                                                                                                                                                                                                                                                                                                                                       |
| `CV_KEK_HANDLE`      | path yielding exactly 32 raw bytes: the read-once FIFO (`0600`, WSL launcher) or the systemd credential file (`0400`, VPS); owned by the service uid, never a symlink. **In `live` a regular file is accepted only if the opened descriptor is on tmpfs/ramfs (`fstatfs`) _and_ the path is under `/run/credentials/`** (systemd `LoadCredential*=`). A Docker Compose `secrets: file:` bind mount is disk-backed and is refused (`kek_handle_permissions`) |
| `CV_KEK_VERSION`     | version of the supplied KEK in this process's environment (`CV_ENV`); its KCV must match that environment's `kek_versions` row. **One KEK per environment:** live, demo and testnet each keep their own lineage, numbered from 1 (#2338). Never give a live KEK to a non-live process, or one KEK to two environments                                                                                                                                       |
| `CV_KEK_PREV_HANDLE` | previous KEK, **only** during a rotation window                                                                                                                                                                                                                                                                                                                                                                                                             |
| `CV_KEK_ACK_PATH`    | writable path (outside the read-only handoff dir) where cv-api echoes the launcher's nonce **once, after every FIFO handle (current and previous) has been drained**. **Mandatory in `live` when any handle is a FIFO** (missing ⇒ Degraded `kek_handle_permissions`). Not used for systemd credential files (not read-once; no handoff record)                                                                                                             |

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

| reason                        | Check                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `kek_unavailable`             | handle missing, timed out (10 s), or not exactly 32 bytes; handoff nonce missing or ack already present                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `kek_handle_permissions`      | mode is not `0400` (file) / `0600` (FIFO), wrong owner, or a symlink                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `kek_mismatch`                | wrong KEK for `CV_KEK_VERSION` (KCV differs, or no KCV yet and a trial unwrap of an existing row failed: an API key row, or with none at that version the active audit export signing key, ADR-0039 decision 6; the previous KEK's KCV must already be recorded) — do **not** retry with other keys                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `kek_reused`                  | the presented KEK's KCV is already recorded for another version or another environment (e.g. the same bytes supplied as current and previous, or the live KEK given to a demo or testnet process)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `kek_retired`                 | `CV_KEK_VERSION` (or the previous version) has `kek_versions.retired_at` set in this environment — a downgrade                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `kek_version_out_of_sequence` | version is neither this environment's max recorded nor max+1 with the previous KEK = max; other environments' versions never count                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `process_hardening_failed`    | (`live`) core-dump limit or `PR_SET_DUMPABLE` could not be applied — check container/systemd limits                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `kcv_store_unavailable`       | `kek_versions` unreadable (Postgres down, schema older than `0026_kek_versions_env`) — not a custody problem; at an enrolment with no API key row, `audit_signing_keys` unreadable (a schema older than `0046_audit_signing_keys` too); the count of stranded rows unreadable within 2 s; an enrolment that cannot commit with its `security.kek_enrolled` record, which shares the row's transaction (the audit row builder refused it, an `audit_log` constraint or trigger failed, or none is wired) — check `audit_log` and the Postgres log too, since `secrets.io_failed` names only a typed refusal such as `KcvEnrolmentNotAudited`; or two environments raced to enrol one KEK (`kv_kcv_unique`) — a custody problem, see `kek_reused`              |
| `audit_unavailable`           | the audit writer refused `security.kek_loaded`, or `security.kek_rows_stranded` (a stranded boot that cannot record itself degrades fully rather than keep the broker); the KEK was zeroed — fix the audit WAL/DB first. An enrolment's record no longer goes through the writer: its failure is `kcv_store_unavailable`                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `no_credential_store`         | (`live`) started without the Postgres credential store                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `kek_rows_stranded`           | the KEK loaded, but unrevoked API key rows of this environment are wrapped under a version this process did not load: typically a restart without `CV_KEK_PREV_HANDLE` before a re-wrap finished. Unlike the reasons above, cv-api keeps the broker: those keys fail closed, every other key still signs (cancels and SL amendments included), and new orders stay latched with `secrets.kek_rows_stranded`. Its log line and `security.kek_rows_stranded` give the count. Of the signals above, `security.kek_load_failed`, `cv_kek_version_state` = 0 and "every credential operation raises" do not apply here: the record is `security.kek_rows_stranded`, the version gauge shows the loaded version, and only the stranded keys fail. Recover as below |

**Recovering from `kek_rows_stranded`** (either way ends with a restart that finds no stranded row).
Do not mark `api_keys` rows revoked by hand to clear the latch: that revocation would not be
audited (C-2.9).

1. The previous KEK is in custody: restart via the launcher with `CV_KEK_PREV_HANDLE` = that KEK
   beside the current one, so the stranded keys sign again, and finish the re-wrap, which resumes
   where it stopped (KEK rotation step 2, below). Then restart without it (step 3).
2. The previous KEK is lost: those keys can never be opened again. Revoke each at Bybit, then in
   CandleViewer through the audited key-management flow (#898), which has to work under this
   degrade because revocation needs no KEK. Until it ships the stranded keys stay failed and new
   orders stay latched. Restart, then provision new keys.

Enrolment: the first boot at a new version with no rows records its KCV and writes
`security.kek_enrolled` (with the KCV). A wrongly enrolled KCV can be re-enrolled **only while
zero `api_keys` rows exist at that version**: delete that `kek_versions` row in a maintenance
window under change control (owner + security reviewer), then restart with the correct KEK. Every
manual statement names the environment (`DELETE FROM kek_versions WHERE env = 'demo' AND
version = 3`); a version number alone matches every lineage.

Recovery: fix custody, then restart cv-api **via the launcher**. There is no runtime reload; a passing
mesh self-check never clears the KEK latch.

<a id="alert-auditsigningkeyunavailable"></a>

## Symptom: `secrets` degraded with an `export_key_*` reason

The audit export signing key (ADR-0039) cannot be used while the KEK is up: export is refused,
trading is not, and nothing latches order entry. Signals: `cv_audit_signing_key_unavailable_state`
= 1 pages `AuditSigningKeyUnavailable`, never `KekUnavailable`; `/readyz` `degraded` with a failing
`secrets` check; `/health/report` shows the `secrets` component `down`, as for a KEK failure, since
its probe reads every M2 degrade as `down`; a critical `secrets.export_key_unavailable` log; and
`security.audit_signing_key_unavailable` at error. The page has its own component,
`audit_signing`, so it hides no `secrets` ticket while it stands. A signing attempt can raise it too:
the `security.audit_export_sign_failed` record just before it names the key and the reason, and a
restart runs the boot check again.

| reason                                         | Check                                                                                                                                                                                                                                                                                                           |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `export_key_store_unavailable`                 | `audit_signing_keys` unreadable (Postgres down, or a schema older than `0046_audit_signing_keys`); restart once fixed                                                                                                                                                                                           |
| `export_key_generation_failed`                 | the environment had no key and the first could not be stored with its record: check `audit_log` and the Postgres log, then restart                                                                                                                                                                              |
| `export_key_stranded`                          | the key is wrapped under a KEK version this process did not load: restart with `CV_KEK_PREV_HANDLE`, as for `kek_rows_stranded`; if that KEK is lost, rotate (below) with reason `unrecoverable` (ADR-0039 decision 6)                                                                                          |
| `export_key_unopenable`, `export_key_mismatch` | the key's wrap or seal does not open, or its seed is not its public key's: a custody or tampering incident (AD-D13). Never edit the row. Recover with the rotation below, reason `unrecoverable` (or `compromise`): once the new key passes its check, export is available again, with no restart (ADR-0039 Q4) |
| `export_key_inactive`                          | keys exist and none is active (an out-of-band retire); boot never generates over them, the rotation refuses them (`409 conflict`), and the recovery is open (ADR-0039 Q4)                                                                                                                                       |

The rotation, the Owner's: `POST /admin/keys/audit-signing/rotate` with `{"reason": "unrecoverable"}`
(or `compromise`), after a `keys` step-up (a grace class: one in the last 5 minutes serves) and with
a fresh UUID `Idempotency-Key`. After a lost answer, send the same key and body again: that replays
the `200` and rotates nothing. At most 3 rotations start per environment in a rolling hour
(`audit_signing_rotate_rate_per_hour`), a failed one counting too, so a store outage can use up the
hour. The `200` is no pin: pin the new key's `active_fingerprint_sha256` from the
`security.audit_signing_key_rotated` record of your own rotation (`24-internal-schemas.md` §15.7),
never from the answer or the list. A fresh `200` (no `Idempotency-Replayed`) whose `active.verified` is
`false`, with `secrets` degraded, means the new key failed its check and is latched as at boot: read its
reason in the table above. For any other `false`, list the keys: if the active one is `verified`, nothing is
wrong (a replay shows its key as it was made, and a marking read can fail after the check passed).
Otherwise this process has not checked it (no KEK held, a `stop()` during the check, or
`secrets.export_key_not_checked` in the log): restart, or rotate again.

<a id="alert-auditsigningkeybootstepfailed"></a>

A failed Q3 destroy or re-wrap at boot degrades nothing: `cv_audit_signing_key_boot_failures_total`
counts it by `step`, which raises the `AuditSigningKeyBootStepFailed` ticket, and
`secrets.export_key_boot_step_failed` names the step, the error's class and its `code`. The KEK
re-wrap stays incomplete (`export_left`) until a boot moves the key (rotation step 2), and a
retired key's seed stays until a boot destroys it: restart once the store or the audit writer is
fixed, and read the destroy's record, which names the keys it destroyed. The ticket sees a failure
only as an increase over a clean sample under 15 minutes old: the same failure at the next boot, or
after a longer outage, raises nothing, so read that log line after every restart.

## Symptom: export refused as `signing_unavailable` while `secrets` is healthy

`exportAuditLog` answers `503 signing_unavailable`, but `secrets` is not degraded and no
`export_key_*` reason is set: the export directory takes no hard links (#889 S10). Signals:
`admin.audit_denied` with reason `export_volume_unavailable`, and `audit.export.link_probe_failed`,
critical the first time and a warning while it keeps failing. The export file is published by a
hard link, so `<data_dir>/audit-exports` must support `link(2)` within one device. Recovery: fix the
mount (one device, a filesystem that takes hard links); the sweep probes again every 60 s, so export
recovers with no restart. Never rotate the signing key for this: the key is sound, and an
`unrecoverable` rotation would retire it and destroy its seed for nothing.

<a id="alert-authkeyringunavailable"></a>

## Auth keyring: `secrets` degraded with an `auth_keyring_*` reason

Each environment has one auth keyring (ADR-0009 Amendment 4, #2152): the TOTP sealing key and the
recovery-code key, generated inside M2 (or imported once on `demo` and `testnet`, below) and stored
only as wraps under the environment's KEK in `auth_keys`. M2 opens it at every boot once the KEK
is verified. When it cannot be used while the
KEK is up, MFA fails closed and nothing else does: the eight MFA operations answer
`503 auth_unavailable` with `Retry-After: 30` (`22-api-openapi.yaml`, `AuthUnavailable`), nothing
is counted or consumed, users without MFA still sign in, and order entry is not latched. Signals:
`cv_auth_keyring_unavailable_state` = 1 pages `AuthKeyringUnavailable` (its own component,
`auth_keyring`, so it hides no `secrets` ticket); `/readyz` `degraded` with a failing `secrets`
check; a critical `secrets.auth_keyring_unavailable` log and `security.auth_keyring_load_failed`
at error, both carrying the reason and this remediation. With the KEK down, `KekUnavailable` pages
instead (above): recover the KEK first.

**Never delete MFA material (`mfa_methods`, `recovery_codes`) or `auth_keys` rows to force a new
keyring.** A boot generates one only when the environment has no rows and no environment holds an
unrevoked TOTP method or an unused recovery code, so a deletion either changes nothing or gives a
keyring that opens nothing sealed before, and every enrolled user loses MFA.

| reason                           | Check and recovery                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `auth_keyring_missing`           | No rows for this environment and MFA material that needs a key (`secrets.auth_keyring_material_without_keyring` gives the count), or on `demo` or `testnet` one of the two old settings set without the other (`secrets.auth_keyring_setting_missing` names it). In `live` also a database whose MFA material another environment sealed: live never imports and never generates over it. Restore the environment's two `auth_keys` rows from a backup under the owner role: they open nothing without the KEK. On `demo` or `testnet`, a boot with both old settings imports them once instead (below). Then restart. The `live` case has no rows in any backup to restore: confirm before the switch-over that no live database holds MFA material made under the old settings or by another environment (#2152 BQ-2); moving such material to live is an E38/R4 question, and there is no carry-over tool (ADR-0009 Amendment 4) |
| `auth_keyring_mismatch`          | The rows do not open as one pair under this KEK: a swapped, edited or lone row, an `imported_env` row in `live`, or another keyring's rows. A custody or tampering incident: keep the rows as evidence, restore the pair from a backup under the owner role, restart                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `auth_keyring_stranded`          | The rows are wrapped under a KEK version this process did not load: a restart without `CV_KEK_PREV_HANDLE` before a rotation boot re-wrapped them. Restart with the previous KEK as `CV_KEK_PREV_HANDLE` (KEK rotation step 1): that boot re-wraps them                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `auth_keyring_store_unavailable` | `auth_keys` or the MFA material count could not be read or written within its bound (Postgres down, or a schema older than `0030`); `secrets.auth_keyring_store_failed` names the error's class. Fix Postgres, then restart                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `auth_keyring_audit_unavailable` | A keyring write's record (`security.auth_keyring_imported` or `_enrolled`, in the rows' transaction) failed, so nothing was written, or the load's `security.auth_keyring_loaded` was refused. Fix the audit writer or `audit_log`, then restart                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `auth_keyring_unopenable`        | An error M2 did not expect stopped the open before any verdict on the rows (its class is logged). Keep the rows and never restore over them: fix the cause, then restart                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |

**The `503`'s record.** Each `503` writes `auth.mfa_unavailable` (failure, warning) naming the
operation, the user when known and the reason (`24-internal-schemas.md` §15.5). Besides the
reasons above it can read `auth_keyring_unavailable` (no keyring is open in this process),
`kek_unavailable` or `auth_keyring_closed` (the KEK went, or cv-api is stopping), or
`auth_key_not_held`: the keyring is up, but one user's TOTP method names a key it does not hold,
such as an old-format method on a generated keyring. Only that user gets the `503`: the Owner
resets that user's TOTP (`auth-rbac.md` §2) and the user enrols again. A record that cannot be
written is counted on `auth_audit_outcome_lost_total` (`action="other"`) and the answer is still
the `503`.

**The one-time import (`demo` and `testnet` only).** A database enrolled before #2152 sealed its
TOTP seeds and digested its recovery codes with the two old settings, `CV_AUTH_TOTP_KEY_HEX` and
`CV_AUTH_RECOVERY_HMAC_KEY_HEX`. The first boot that finds no rows and both settings imports them
as the keyring (`origin = imported_env`, `security.auth_keyring_imported`), so every enrolment
keeps working; a later boot that still has them warns
(`secrets.auth_keyring_env_settings_ignored`) and ignores them. `live` refuses either setting at
start-up (`auth_key_env_forbidden`) and never imports. After the import boot:

1. Confirm `security.auth_keyring_imported`, then a `security.auth_keyring_loaded` with
   `origin` `imported_env` at the next boot.
2. **Scrub both settings** from the host's environment file (on the demo host, the compose `.env`
   that `infra/compose/docker-compose.demo-host.yml` reads; both are optional there) and from any
   copy of it, then restart. An imported key is the old value itself: until it is gone, a
   database dump plus that file opens every seed of the environment, old and new.
3. Old backups of the file still hold the values; they expire with the backups. Re-keying means
   every user enrols again (the Owner's call; there is no re-key tool).

**The dual-read window.** On an imported keyring only, M2 still opens the old formats: a TOTP seal
with no binding (`secret_key_ref = 'local-dev-v1'`) and a recovery-code digest without the user.
Every boot of an imported keyring logs the window's exit test as
`secrets.auth_keyring_legacy_window`: `material` counts the unrevoked `local-dev-v1` methods and the
unused recovery codes created before the import, and `exit_test_passed` is true at zero (a warning
while material is left, else info; `secrets.auth_keyring_legacy_window_unknown` if the count
failed, which never stops the boot). Material drains only through the audited flows (a re-enrolment
after the Owner's TOTP reset, a code used at sign-in); never edit or delete the rows to pass the
test. A follow-up retires the old reads once it passes.

<a id="alert-authkeyringbootstepfailed"></a>

**A failed re-wrap at a rotation boot** degrades nothing: `cv_auth_keyring_boot_failures_total`
counts it with `step="rewrap"`, which raises the `AuthKeyringBootStepFailed` ticket, and
`secrets.auth_keyring_boot_step_failed` names the step, the error's class and its `code`. The
keyring still opens under the previous KEK on that boot, and the KEK re-wrap run does not record
`security.kek_rotated` while an auth row is left at the old version. Fix the store or the audit
writer, then restart with `CV_KEK_PREV_HANDLE` again (KEK rotation step 1): the next rotation boot
moves the row, with `security.auth_keyring_rewrapped` in the same transaction. The ticket sees a
failure only as an increase over a clean sample under 15 minutes old, so read that log line after
every rotation restart.

## KEK rotation (owner-run, per environment)

Each environment has its own KEK lineage (#2338): rotate one environment at a time, on that
environment's process. Nothing here reads or changes another environment's rows or versions.

1. **Stage.** Provision KEK v(n+1) in custody beside v(n). Restart cv-api via the launcher with
   `CV_KEK_VERSION=n+1`, `CV_KEK_HANDLE` = v(n+1) and `CV_KEK_PREV_HANDLE` = v(n). The boot checks
   the previous KEK first, then enrols v(n+1) (`security.kek_enrolled`). From this boot on, rows
   still at v(n) sign only while the previous handle is supplied.
2. **Re-wrap.** As the Owner, log in, complete MFA, and send `POST /admin/keys/kek-rewrap` with the
   CSRF token and `{"environment": "<env>", "to_version": <n+1>}`. Its first answer, unless a `keys`
   step-up is still live, is `403 step_up_required`: step up for class `keys` and send it again. The
   call latches new orders read-only (`secrets.kek_rotation`) until the restart in step 3; cancels,
   stop-loss amendments and borrows keep working. The answer holds counts only. Repeat the call
   until it answers `complete: true`: each call resumes the run, and a `503` keeps the rows moved so
   far. Investigate every `failed` row first: `security.kek_rotation_failed` names it, and it stays
   at v(n). A `409 kek_rotation_not_staged` means the body differs from the boot or the previous
   handle is missing; a `409 kek_rotation_in_progress`, that a run is under way (call again after
   its `Retry-After`); a `403 kek_unavailable`, that the process is degraded (see the Symptom
   section above; stage again as in step 1 once it is fixed). Each run writes
   `security.kek_rotation_started` (or `security.kek_rotation_resumed`), one
   `security.credential_rewrapped` per moved row in that row's transaction, and
   `security.kek_rotated`, or `security.kek_rotation_incomplete` while rows are left: never go on
   after an incomplete record. An auth keyring row or an audit export signing key left at v(n)
   moves only at a rotation boot: restart as in step 1, then call again (ADR-0009 Amendment 4;
   ADR-0039 decision 6).
3. **Prove v(n+1) alone.** Restart via the launcher without `CV_KEK_PREV_HANDLE`, keeping v(n) in
   custody. Confirm health is OK with no `kek_rows_stranded` and that the stored-key self-check
   passed (no `accounts.key_*` latch). If rows are stranded, stage again as in step 1 and resume
   step 2.
4. **Retire.** Only then set `kek_versions.retired_at` for v(n) of this environment only
   (`WHERE env = '<env>' AND version = <n>`), under change control (owner + security reviewer).
   A boot that supplies a retired KEK is refused (`kek_retired`).
5. **Destroy v(n).** In a routine rotation keep it only in the owner's offline copy (ADR-0009 §7)
   until every database backup taken before the rotation has expired, then destroy it; in a
   compromise rotation destroy it now.

## Upgrading to per-environment KEK lineages

Migration `0026_kek_versions_env` (#2338) keys `kek_versions` by `(env, version)`.

- It refuses while any `api_keys` row is usable (`revoked_at IS NULL AND status <> 'revoked'`).
  Such rows may hold environment-free `v1:` wraps (rows written before #2338) that cv-api no
  longer opens, and a migration never holds the KEK to re-wrap them. Revoke each such key through
  the audited key-management flow (never edit `api_keys` by hand), then run the upgrade again.
- Rows enrolled before it join `demo`. The first live boot afterwards enrols a fresh live lineage:
  compare the KCV in its `security.kek_enrolled` record (`env=live`) with the offline copy's KCV
  (SR-E27-15) before any live key is stored.
- A KCV that a live process enrolled before the upgrade is now in a `demo`-labelled row, so a live
  boot with the same KEK is refused as `kek_reused` (the reuse check spans every environment).
  Either boot live with a different KEK (one KEK per environment), or, before the first live
  boot, delete that row in a maintenance window under change control (owner + security
  reviewer): `DELETE FROM kek_versions WHERE env = 'demo' AND version = <n>`. The live lineage
  then starts at `CV_KEK_VERSION=1`. Use a different KEK if a demo or testnet process ever held
  this one.
- Its downgrade refuses while one version is enrolled under two environments. Lineages with
  disjoint versions, such as `(live, 1)` and `(demo, 2)`, pass that check and merge into one
  version sequence, and the restored pre-#2338 code applies its global policy to it, so a live
  boot can then be refused as `kek_version_out_of_sequence`. A rollback is only safe while a
  single environment has enrolled; otherwise delete the other environments' `kek_versions` rows
  under change control (owner + security reviewer) before the downgrade.

## Restore drill

Restore a dump on a host with **no** KEK: expect Degraded `kek_unavailable` and zero decryptions.
Supplying a wrong KEK gives `kek_mismatch`. Automated equivalent:
`tests/unit/credentials_m2/test_broker.py::test_broker_dump_without_kek_cannot_decrypt`. The auth
keyring is in the dump only as wraps, so neither a TOTP seed nor a recovery-code digest can be
computed from it without the KEK (#2152 AC12; on an imported keyring only once the old settings
are scrubbed, above):
`tests/integration/storage/test_restore_drill.py::test_a_restored_dump_without_the_kek_opens_no_seed_and_computes_no_digest`.
