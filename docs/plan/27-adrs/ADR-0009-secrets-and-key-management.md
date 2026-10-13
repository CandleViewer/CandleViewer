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
  id goes (`API_KEY_ID`). It owns that format (C-2.2).
- M2's capability `CredentialBorrower.sign(key_id, message, purpose=...)` decrypts, splices the
  key id in and computes HMAC-SHA256 inside M2. It returns the lowercase hex signature and the key
  id (`Secret[str]`, for the request header). It never returns the API secret.
- The plaintext-yielding borrow (`with_credentials`) is removed. Each signing call keeps the single
  audited path: caller check, status and env fence, write-ahead `security.credential_borrowed`.
- The message is plain data, so the out-of-process signer (#2279) can serve the same call.
- Enforcement: the M2 AST guard (`tests/unit/credentials_m2/_m2_guard.py`, rule R10) refuses
  the plaintext borrow and `.reveal()` outside `secrets/` (one reviewed site: the returned key id
  for the header). In `exchange/` it also refuses any `hmac` import, `SecretStr` and
  `get_secret_value`.
