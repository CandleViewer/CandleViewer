# ADR-0009 — Secrets and Bybit API-key management

- Status: **decided**
- Date: 2026-09-14
- Deciders: Security engineer, Architect, DevSecOps, Owner
- Consulted: `docs/research/06-bybit-api.md` §18, `docs/research/22-architecture-options.md` §8, §9, `docs/research/12-scope-and-users.md`, planning brief "Locked decisions"
- Related: ADR-0010, `docs/plan/04-security-program.md`, `docs/plan/21-database-schema.md`

## Context and problem statement

CandleViewer holds Bybit API keys that can move real money across a main account and several sub-accounts, in three environments. The runtime lives in WSL Ubuntu on a personal Windows machine today and a small VPS later. WSL has no reliable headless keyring, and the deployment is operated by one person. We need key storage that is meaningfully better than "encrypted with a password in the config file" without requiring enterprise infrastructure.

## Decision drivers

- Withdrawal permission must always be OFF; IP allowlisting must always be on (planning brief).
- Bybit's IP allowlist became browser-only configuration in Feb 2026 — it cannot be automated; treat it as a manual, verified precondition.
- New accounts have a cooldown (~48 h) before API-key creation — onboarding lead time, not a bug.
- Keys must never appear in source, config, logs, backups or database dumps in plaintext.
- Rotation must be practical enough that it actually happens.
- The team includes one security engineer and one DevSecOps engineer; the solution must be operable by them, not by a platform team.

## Considered options

1. **Envelope encryption with the KEK held on the Windows host OS keychain, injected into the process at start; DEK per key record; ciphertext in Postgres.**
2. **HashiCorp Vault** (or OpenBao) as a sidecar.
3. **Cloud KMS** (AWS/GCP).
4. **OS keyring inside WSL.**
5. **Password-derived key** entered at startup.

## Decision outcome

**Chosen: option 1.**

Design:

1. **KEK** — a 256-bit key stored in the Windows Credential Manager on the host, outside WSL and outside any Docker volume. It is injected into `cv-api` at process start as an environment secret by a small host-side launcher script, never written to disk inside WSL, and never logged. `CV_KEK_SOURCE=file` exists for development only and refuses to start when `CV_ENV=live`.
2. **DEK per key record** — each stored API key row has its own AES-256-GCM data key, itself encrypted under the KEK. The row stores `{dek_wrapped, nonce, ciphertext, tag, key_version, created_at, rotated_at}`. Compromise of one row's DEK does not expose others, and rotating the KEK rewraps DEKs without touching ciphertext.
3. **Decryption is narrow** — plaintext keys exist only inside the exchange adapter, only for the lifetime of a request signature, and are held in a wrapper type whose `__repr__`/`__str__` return `***`. A unit test asserts a known secret value never appears in any log output.
4. **Startup assertions (blocking for trading mode)** — for every key marked `trading_enabled`: it decrypts; `GET /v5/user/query-api` reports `withdraw = false`; an IP allowlist is present and includes the current egress IP; the account is UTA with the configured position mode. Any failure puts the app in `Degraded` with order entry disabled and raises a critical alert.
5. **Rotation** — 90-day scheduled rotation with a dual-write window: create the new key via the Bybit API, verify permissions and allowlist, switch the active pointer, soak for 24 h, then delete the old key. Immediate rotation on suspected compromise, triggered from the Admin UI, is a one-click flow that also FREEZEs the affected accounts.
6. **Scope minimisation** — one Bybit sub-UID per manager/strategy for blast-radius isolation; each key is trade + read only; withdrawal never enabled; the 5/20 sub-account cap is surfaced in the Admin UI because it bounds how many managers can exist.
7. **Backups** — database backups contain only ciphertext. The KEK is backed up separately by the owner (offline, e.g. a printed/`age`-encrypted copy in a safe). The restore runbook states explicitly that a backup without the KEK is unusable — that is the intended property.
8. **Other secrets** — session signing keys, TOTP secrets and the notification webhook credential follow the same envelope pattern. TOTP secrets additionally require re-authentication to view a recovery code.

### Consequences

Positive:

- Database theft (stolen laptop, leaked dump, misconfigured backup) does not yield usable keys, because the KEK is not in the database, not in WSL and not in any volume.
- Per-record DEKs make rotation and revocation surgical.
- The startup assertions convert two silent, catastrophic misconfigurations (withdrawal enabled, no IP allowlist) into a loud, blocking error.

Negative / risks:

- The KEK's availability is now a dependency of starting the service; losing it means re-entering every API key. Accepted and documented, with an owner-held offline backup and a runbook.
- The host-side launcher is a small piece of bespoke tooling that must be maintained across Windows and, later, the VPS (where the KEK moves to a systemd credential or an `age`-encrypted file with restrictive permissions). Documented in `04-security-program.md`.
- IP allowlist changes remain manual because Bybit made them browser-only; the VPS migration runbook has an explicit step for this.

### Why not the alternatives

- **Vault/OpenBao**: the right answer at organisational scale; here it adds a stateful, unseal-managed service to a single-box deployment operated by one person — more moving parts than the risk reduction justifies, and its own root key has exactly the same custody problem.
- **Cloud KMS**: introduces an external dependency and an account relationship to a project whose defining property is being self-hosted and network-isolated.
- **OS keyring inside WSL**: research established it is not reliable headless; a keyring that silently fails is worse than none.
- **Password-derived key at startup**: requires a human at every restart, which is incompatible with unattended recovery while positions are open — directly at odds with the availability requirements in ADR-0008.

## Validation

- Security test: a crafted log line containing a key value is asserted absent from stdout, files and the metrics endpoint.
- Restore drill: restore a database backup on a machine without the KEK and confirm no key can be decrypted and the app refuses trading mode.
- Rotation drill: full 90-day rotation executed once before Live enablement (R4) as a PRR item.
- Pen-test before Live enablement covers key handling explicitly.

## Amendment 1 (2026-10-10, E27-K01 #832)

Refines Design §1; does not reverse it. Detail: `docs/plan/spikes/e27-kek.md`.

- Injection is a **handle** (`CV_KEK_HANDLE`, default `/run/secrets/cv_kek`), not an environment
  variable (env values are visible via `docker inspect` and `/proc/*/environ`).
- WSL mechanism: the Windows launcher reads Credential Manager and pipes the KEK on stdin into
  `wsl.exe`; inside WSL a fresh `0700` dir holds a `0600` FIFO written once, then unlinked, with a
  nonce-acked handoff record. Docker Engine inside WSL is the supported engine; the launcher is the
  only restart supervisor; WSL interop is disabled (`[interop] enabled=false`).
- VPS custody: `systemd-creds` `LoadCredentialEncrypted` (TPM2 when available); `age` `0400` fallback.
- SR-002 tightened: key/credential files are opened `O_NOFOLLOW` and must be exactly `0400` (FIFO
  `0600`) owned by the service uid; an `age` identity is never stored beside its ciphertext.
- Config: `CV_KEK_SOURCE` (`handle`|`file`|`none`), `CV_KEK_HANDLE`, `CV_KEK_VERSION`; `file` with
  `CV_ENV=live` is fatal (`kek_source_not_permitted`).
- Wrap-layer `kek_version` is separate from data-layer `key_version`; the wrapped DEK's AAD binds
  `credential_id` and `kek_version` (SR-003). Each KEK version has a non-secret check value.
- KEK unavailable ⇒ `Degraded`: signing, key add/verify/rotate refused (403) and the hourly C-2.8
  withdrawal check fails (never skipped).
- KEK types are private to `secrets`; other modules get metadata-only calls (C-3.2).
- Break-glass (#2119) lives in `candleviewer.admin`, proves KEK possession through `secrets`, and in
  `live` also requires an unused Owner recovery code; it audits before acting.

## Amendment 2 (2026-10-13, #2339; decision owner-delegated per #1778)

Supersedes Design §3's "plaintext keys exist only inside the exchange adapter". It conforms to
C-2.7: credentials are plaintext only inside `secrets` (M2), at the moment of request signing.

- The exchange adapter builds its venue's string-to-sign as byte segments and marks where the key
  id goes (`KEY_ID_SLOT`). It owns that format (C-2.2).
- M2's capability `CredentialBorrower.sign(key_id, message, purpose=...)` decrypts, splices the
  key id in and computes HMAC-SHA256 inside M2. It returns the lowercase hex signature and the key
  id (`Secret[str]`, for the request header). It never returns the API secret.
- The plaintext-yielding borrow (`with_credentials`) is removed. Each signing call keeps the single
  audited path: caller check, status and env fence, write-ahead `security.credential_borrowed`.
  That record carries `message_sha256`, the digest of the message before the key id is spliced
  in. A failure after it appends `security.credential_sign_failed` (#2350 security review).
- The message is bounded: at most 64 KiB, 16 parts and one `KEY_ID_SLOT`. A refused message is
  refused before any decrypt or audit. A failed MAC leaves M2 as a typed `signing_failed` with
  nothing chained, after the failed call's frames are cleared, so no traceback carries plaintext.
- The message is plain data, so the out-of-process signer (#2279) can serve the same call.
- Enforcement: the M2 AST guard (`tests/unit/credentials_m2/_m2_guard.py`, rule R10) refuses
  the plaintext borrow and `.reveal()` outside `secrets/` (one reviewed site: the returned key id
  for the header). In `exchange/` it also refuses any `hmac` import, `SecretStr` and
  `get_secret_value`.

## Amendment 3 (2026-10-15, #2338; owner decision 2026-10-14, #1778 comment 6174148616)

Refines Amendment 1. Each environment (`live`, `demo`, `testnet`) has its own KEK lineage in the
shared Postgres, so a KEK that can unwrap a live DEK is only ever loaded under the live custody
rules. This does not decide the E38 topology, and the custody rules themselves are unchanged.

- `kek_versions` is keyed `(env, version)` (`0026_kek_versions_env`) and each lineage is numbered
  from 1. The KCV label stays environment-independent and `kv_kcv_unique` stays global, so one KEK
  is never enrolled in two environments: the boot refuses it as `kek_reused`.
- KCV enrolment and the retired and sequence checks run inside the process's environment; the
  reuse check spans every environment. A non-live boot never changes what a live boot accepts.
- The wrap AAD binds the environment: `cv-dek-v2 ‖ environment ‖ credential_id ‖ kek_version`,
  `dek_ref` prefix `v2:`. The environment is bound into the KEK at load from the process settings,
  never taken from a row or a request; the broker refuses a KEK loaded for another environment.
- Environment-free `v1:` wraps fail closed. Nothing re-wraps them: the migration refuses while
  usable `api_keys` rows exist, and rows enrolled before it join `demo`, never `live`. The first
  live boot enrols a fresh live lineage (residual KV-S03, Owner check SR-E27-15).

## Amendment 4 (2026-10-16, #2152; rulings D1–D7 under the owner's delegation, veto venue #2701)

Implements Design §8 for the two E09 keys, the TOTP sealing key and the recovery-code HMAC key.
Until now they were env-provided (`CV_AUTH_TOTP_KEY_HEX`, `CV_AUTH_RECOVERY_HMAC_KEY_HEX`) with no
KEK behind them. Table and formats: `21-database-schema.md` §3.1.5a. Slices S1–S6 on #2152.

- **One auth keyring per environment.** Both keys are generated inside M2 and stored only as wraps
  under that environment's KEK, with their `kek_version`, in `auth_keys`. The keyring follows the
  process environment, like `api_keys` (Amendment 3): MFA material sealed by one environment's
  process never opens in another's, and nothing is generated over it. Moving a demo user base to
  live is an E38/R4 question; there is no carry-over tool.
- **Bindings.** The wrap AAD binds environment, purpose, row id and `kek_version` under its own
  label and `dek_ref` prefix, so neither a credential wrap nor a swapped row opens as an auth key.
  New TOTP seals and recovery-code digests bind the user, so a database writer cannot transplant one
  user's seed or unused code into another user's rows.
- **Provisioning, in `SecretsService.start()` after the KEK is verified.** Rows exist: unwrap them.
  No rows on `demo` or `testnet` with both env keys set: import them once (`imported_env`). No rows,
  no env keys and no MFA material that needs a key: generate both. Anything else generates nothing
  and leaves MFA unavailable (`auth_keyring_missing`); an unwrap failure is `auth_keyring_mismatch`
  and is never regenerated over. Either env key in `live` refuses start-up
  (`auth_key_env_forbidden`); on `demo` and `testnet` a later boot that still has them warns and
  ignores them. The old formats (no AAD, an HMAC without the user) are read only on an imported
  keyring, never on a generated one and never in `live`; there is no re-seal job.
- **KEK rotation.** At a rotation boot M2 re-wraps the environment's `auth_keys` rows itself, each
  new wrap verified before a compare-and-set on `kek_version` and audited; seeds and code hashes
  never change. The KCV trial unwrap covers `auth_keys`, and `kek_rotated` waits until no auth row
  is left at the old version. Auth rows left at an old version with no previous handle make MFA
  unavailable (`auth_keyring_stranded`) until a restart with `CV_KEK_PREV_HANDLE`.
- **Injected capability, no import edge (C-3.4).** `auth` (M18) imports neither `secrets` nor
  `admin`, and the import-linter contracts do not change. M2's `AuthKeyring` capability holds only
  closures, like `CredentialBorrower` (Amendment 2), and offers `available()`, `seal_totp_seed`,
  `open_totp_seed` and `recovery_code_digests` with plain-data inputs and outputs, so #2279 can
  serve it out of process. It is minted once in `admin/wiring.py`, a site the M2 AST guard pins,
  and adapted there to auth's own `MfaKeyring` protocol. Key bytes never leave M2.
- **Seed plaintext in M18 (ruling D7).** An opened TOTP seed exists only inside the M18 MFA
  verifier, as a `bytearray` zeroed after use, and is never logged, snapshotted or returned
  (C-12.6). A new seed is shown once at enrolment, before it is sealed, as today. C-2.7 governs
  exchange API credentials.
- **Unavailable means fail closed (ruling D4).** Without the KEK or the needed auth key, the eight
  MFA operations answer `503 auth_unavailable` (`22-api-openapi.yaml`, `AuthUnavailable`);
  `authLogin` does so only for a user with a confirmed method and only after the password verified.
  Nothing is counted or consumed, and a method this process cannot open never counts as "no
  method". A keyring failure alone reports `secrets` degraded and pages but adds no trading latch;
  a KEK failure still latches it (Amendment 1).
- **Dev, demo and CI (from S5b).** Today a `demo` or `testnet` process without the env keys falls
  back to a process-local key. S5b removes that fallback, so from then on no environment has MFA
  without a keyring: without a KEK (`CV_KEK_SOURCE=none` or a KEK failure) the eight operations
  answer `503 auth_unavailable`, while users without MFA still sign in. A dev, CI or E2E stack
  that exercises MFA must supply a KEK by then (`CV_KEK_SOURCE=file` is allowed outside `live`,
  `docs/plan/spikes/e27-kek.md` §4) and gets its keyring generated at its first boot. Unit tests
  use the keyring fixture of S5a, never a real KEK. A demo database enrolled under the env keys
  keeps its enrolments through the one-time import.
- **Operator recovery.** S6 of #2152 owns the operator path for each reason MFA is unavailable
  (`auth_keyring_missing`, `auth_keyring_mismatch`, `auth_keyring_stranded`, a KEK failure): the
  steps in the `kek-custody.md` and `auth-rbac.md` runbooks and the `AuthKeyringUnavailable` alert.
- **Break-glass (#2119, ruling D5).** The offline KEK proof keeps its single custody pass and, in
  the same pass, returns a digest-only session for the environment's recovery key. M21 receives
  only digests, which count as C-3.2 metadata; without a proven KEK the CLI refuses before any
  digest is computed. If O3 on #2119 removes the live recovery code, this shrinks to deleting the
  key-bytes port.
- **Unchanged.** `CV_AUTH_PEPPER` and `CV_AUTH_CSRF_KEY_HEX` stay env-provided, and there is no
  tool to re-key the auth keys themselves.

## Amendment 5 (2026-10-16, #2417; interim decision D1 by main-orchestrator, recorded on #2417)

Supersedes Design §5's "soak for 24 h". The rotation overlap is one fixed 900 s: the
`api_key_rotations.grace_seconds` default and US-ACCT-004's 15-minute drain window (`rotateApiKey`
in `docs/plan/22-api-openapi.yaml`). The rest of §5 (keys are created in the Bybit dashboard, not
"via the Bybit API"; the old key is revoked locally only) stays with E27-T05.

## Amendment 6 (2026-10-17, #836 slice 2b3; decision 7 by main-orchestrator, recorded on #836)

Refines Amendment 2's single audited path: key import signs inside M2 too (SR-E27-01).
`CandidateKeys` holds a pasted pair in M2 memory for one check, bounded by the ticket's 12 s
deadline (`CANDIDATE_HOLD_S`). Its `CandidateSigner` signs `key_verify` messages for the candidate's
own id only, each after a write-ahead `security.credential_borrowed` naming the acting Owner the
caller passes (SR-E27-09). The pair is stored `pending` only after the check passes; a refusal, an
error or the bound stores nothing (decision 7, in place of SR-E27-01's `pending` row destroyed on
refusal, whose ciphertext 0024 would keep). Both paths share one MAC wrapper and one record close. A
stored key's borrow also re-checks C-2.8 on its row before its audit and any decrypt (SR-E27-14).

## Amendment 7 (2026-10-18, #3009; ADR-0037 decision 6, accepted on an interim basis on #3009)

Adds one application secret to the key inventory (Design §8; Amendment 4, "Unchanged").

- **The audit lane key** MACs the frames, marker and release note of the journal-first audit lane
  (ADR-0037): 32 bytes, one per environment (C-2.11), an application secret like
  `CV_AUTH_CSRF_KEY_HEX` and not under the KEK. It lives in the file that `CV_AUDIT_LANE_KEY_FILE`
  names, by default `/run/secrets/cv_audit_lane_key` (a compose secret); during a rotation the
  previous key, which only verifies, is in `CV_AUDIT_LANE_PREVIOUS_KEY_FILE`. The composition root
  reads both once at boot and hands the bytes to `audit` (C-3.2); logs carry only each key's `kid`.
  The file rules and the boot refusals: `24-internal-schemas.md` §15.6 and ADR-0037 decision 6.
