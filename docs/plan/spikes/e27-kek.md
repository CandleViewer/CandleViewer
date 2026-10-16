# E27-K01 — KEK custody, injection and rotation (WSL and VPS)

- Ticket: E27-K01 (#832) · Feeds: E27-T02 (#835 credential broker + KEK loader), E09-S11 (#2119 break-glass CLI)
- Status: **finding — ★ defaults pre-approved for ratification by the owner (recorded on #1778)**
- Owners of the rules cited: ADR-0009, `04-security-program.md` SR-001/002/023/090–093, C-2.7, C-3.2, C-12.2
- No secret values appear in this document. Paths and variable names only.

## 1. Threat framing

Attacker holds a Postgres dump and/or read access to the WSL filesystem / Docker volumes, but not the
Windows host console. Each option is scored on: KEK at rest, KEK in transit, process visibility
(`/proc/*/environ`, `docker inspect`, WSL FS), auditability, failure mode, unattended restart.

**Evidence status.** This finding was produced desk-side. The measured items the ticket asks for
(per-mechanism start-up latency, non-visibility transcripts, restore-drill log) are **not fabricated
here**; they are owed by follow-up drill **FU-1** (§9) run on the real host against the T02 build.
Figures below marked *(budget)* are targets, not measurements.

## 2. KEK custody

| # | Custody | WSL deployment | VPS deployment | Verdict |
|---|---|---|---|---|
| C1 | Windows Credential Manager (host), read by a host-side launcher | ✔ outside WSL + volumes | n/a | ★ **WSL** |
| C2 | File `0400`, owned by service uid, outside every Docker volume and the repo | weak: WSL FS is in the threat model | acceptable only as source for C3 | dev only (`CV_KEK_SOURCE=file`) |
| C3 | systemd credential: `LoadCredentialEncrypted=` (TPM2 and/or host key sealed via `systemd-creds`) | n/a (no systemd guarantee in WSL) | ✔ unattended, never plaintext on disk | ★ **VPS** |
| C4 | `age`-encrypted file `0600` + identity file | identity sits beside it ⇒ no gain | fallback when no TPM2/`systemd-creds` | VPS fallback |
| C5 | Plain env var in compose `environment:` | visible via `docker inspect` | same | **rejected** |
| C6 | OS keyring inside WSL / password at boot / Vault / KMS | rejected by ADR-0009 | — | not re-litigated |

TPM: on a VPS a virtual TPM2 is used when the provider exposes one (`systemd-creds --with-key=tpm2`);
otherwise `--with-key=host` (key in `/var/lib/systemd/credential.secret`, root `0400`). Both keep the
KEK out of Postgres, out of backups (SR-090) and out of image layers (SR-002).

Offline backup of the KEK stays as ADR-0009 §7: owner-held `age`-encrypted copy, distinct from the
backup key (SR-091).

## 3. Injection path into `cv-api`

Candidates from the ticket:

| Mech | How | Where the KEK is visible | Unattended restart | Verdict |
|---|---|---|---|---|
| (a) `docker compose run --env` from launcher | launcher reads C1, passes env | `/proc/1/environ` of the container **and** `docker inspect` (`Config.Env`) | yes | **rejected** — fails non-visibility |
| (b) Compose `secrets:` backed by a pipe/FIFO | launcher writes to a host FIFO bind-mounted as `/run/secrets/cv_kek` | tmpfs-like mount inside the container only; not in `inspect` env; FIFO is on the WSL FS path but holds no data at rest | yes, if the launcher is the restart supervisor | ★ **chosen** |
| (c) Authenticated localhost unwrap call to a host agent | `cv-api` calls host agent at boot | KEK never enters container if agent unwraps DEKs; otherwise in transit over loopback | needs agent up + its own credential (bootstrap problem recurs) | rejected for v1 — new long-running host service, new auth secret, new network path |

★ **Handle contract.** Whatever the host side does, `cv-api` sees exactly one thing: a path
`CV_KEK_HANDLE` (default `/run/secrets/cv_kek`) that yields exactly 32 raw bytes.

**WSL mechanism (normative for T02):**
1. Supported engine: ★ **Docker Engine installed inside the WSL distro** (bind mounts and FIFOs are
   native). Docker Desktop (separate VM, 9p/virtiofs file sharing) is **not supported** for the FIFO;
   fallback on Docker Desktop is running `cv-api` as a host-distro process (no container) with the
   same handle, until FU-1 shows FIFO semantics hold across the Desktop VM boundary.
2. The Windows launcher (`infra/host/cv-launch.ps1`, T02/infra) reads C1 and starts
   `wsl.exe -d <distro> -u cv -- /opt/cv/kek-handoff` with the KEK on **stdin only** — never argv,
   never env, never a temp file.
3. `kek-handoff` (inside WSL, as service uid `cv`) creates a fresh dir `/run/cv-kek.<nonce>` mode
   `0700`, a FIFO `cv_kek` mode `0600` owned by `cv`, writes a **handoff record**
   (`nonce`, launch id, timestamp; no key material) beside it, bind-mounts the dir into the container
   read-only, starts compose, then writes the 32 bytes **once**, closes, and **unlinks** FIFO and dir.
4. Loader: opens with `O_RDONLY|O_NOFOLLOW` and a bounded timeout (★ 10 s) → else `kek_unavailable`;
   reads exactly 32 bytes; a short read, an extra byte, or an EOF before 32 ⇒ `kek_unavailable`.
   It acknowledges the handoff record's nonce back (write to an ack file); the launcher treats a
   missing/duplicate ack or a writer that completed without the matching ack as **extra reader**,
   raises `security.kek_handoff_anomaly`, and stops the stack (fail closed).
5. **The launcher is the only restart supervisor.** Compose `restart:` is `no` for `cv-api`; a Docker
   restart cannot refill the FIFO and would only produce Degraded. Unattended reboot = Windows Task
   Scheduler "at startup" runs the launcher (no interactive prompt).

**Host-interop hardening (★ required, not residual):** by default any WSL process can run
`powershell.exe` and read the Windows Credential Manager. T02/infra MUST set `/etc/wsl.conf`
`[interop] enabled=false` and `appendWindowsPath=false`; the launcher runs from Windows and only
pushes *into* WSL. Residual: a Windows-side compromise of the owner account still reaches C1 — this
is the host-compromise ceiling already recorded in the E09 threat model §3.6.1 (owner: Owner).

**VPS:** systemd unit with `LoadCredentialEncrypted=cv_kek:...`; the service gets
`$CREDENTIALS_DIRECTORY/cv_kek` (ramfs, `0400`, service uid) at the same handle path. This file is
**not read-once**: it stays readable for the service's lifetime. Mitigations (★): the unit sets
`ProtectProc=invisible`, `NoNewPrivileges=yes`, `PrivateTmp=yes`; the loader reads once at start and
never again; a re-read by the same uid (i.e. code execution inside `cv-api`) remains possible and is
recorded as residual risk (owner: Owner) — at that point the attacker can already call the unwrap path.

**Memory hygiene (SR-009) — T02 acceptance criteria:** core dumps disabled (`ulimit -c 0`,
`LimitCORE=0`, container `--ulimit core=0`, `PR_SET_DUMPABLE=0`); ptrace restricted
(`kernel.yama.ptrace_scope>=1`, no `SYS_PTRACE` capability); swap off or encrypted. Loader zeroes
its `bytearray` buffer (best effort) and never logs length or prefix; the value never enters
`os.environ` or `Settings`. FU-1 additionally checks crash reports, Docker logs and app logs for the KEK.

Rejecting (a): env vars leak into `docker inspect` and every child process. Rejecting (c): it re-creates
the custody problem for the agent's credential and adds a network surface the threat model does not need.

KEK acquisition budget: ≤500 ms added to boot *(budget; measure in FU-1)*.

## 4. Configuration vocabulary (fixed)

| Key | Values | Meaning |
|---|---|---|
| `CV_ENV` | `dev` · `ci` · `demo` · `live` | existing environment selector |
| `CV_KEK_SOURCE` | `handle` ★ (prod default) · `file` (dev/ci only) · `none` | how the loader obtains the KEK. Replaces today's placeholder `kek_source="host-keychain"` in `settings.py`; T02 changes the default to `handle` and keeps `host-keychain` as a deprecated alias for one release. |
| `CV_KEK_HANDLE` | path | `handle`: read-once path (default `/run/secrets/cv_kek`); `file`: path to a dev key file |
| `CV_KEK_VERSION` | int ≥ 1 | the version of the KEK being supplied; must equal the active version in the `kek_versions` metadata (T02) or the current max `api_keys.kek_version` |

Hard rules (startup, before any module starts):
- `CV_KEK_SOURCE=file` with `CV_ENV=live` ⇒ **fatal**, exit non-zero, error code `kek_source_not_permitted`.
- `CV_KEK_SOURCE=file` with `CV_ENV=demo` ⇒ allowed only with an explicit warning log; ★ demo should use `handle`.
- Any key file / credential path is opened with `O_NOFOLLOW` and must be **exactly** mode `0400`
  (or `0600` for the WSL FIFO) and owned by the service uid; anything else ⇒ refuse
  (`kek_handle_permissions`). This tightens SR-002 (noted in ADR-0009 Amendment 1).
- An `age` identity is never stored beside its ciphertext or on a Docker volume (C4 fallback only).

## 5. Key hierarchy and rotation (re-wrap)

> **Superseded in part by #2338 (ADR-0009 Amendment 3):** the KEK lineage is per environment.
> `kek_versions` is keyed `(env, version)` and the wrap-layer AAD below is now
> `cv-dek-v2 ‖ environment ‖ credential_id ‖ kek_version` (`dek_ref` prefix `v2:`); see
> `21-database-schema.md` §3.2.3a.

Rows (`21-database-schema.md` §3.2.2): `key_id_enc`, `secret_enc` (AES-256-GCM under the DEK),
`enc_nonce`, `enc_alg`, `dek_ref`, `kek_version ≥ 1`, index `ix_api_keys_kek`.

★ **Key check value.** Each KEK version is identified by a KCV = first 8 bytes of
HMAC-SHA256(KEK, `"cv-kek-kcv-v1"`), stored (non-secret) in `kek_versions(version, kcv, created_at,
retired_at)` (migration in T02 #835 scope). The loader compares with `hmac.compare_digest`
(constant-time); a mismatch is `kek_mismatch`, not a decrypt storm.

★ **Two version layers, two AADs (SR-003).**
- Data layer: credential ciphertext under the DEK. **As implemented (E27-T02 #835):** AAD =
  `cv-cred-v2 ‖ environment ‖ account_id ‖ credential_id ‖ field` (length-prefixed). `key_version`
  is bound through `credential_id`, because every exchange key rotation inserts a new `api_keys` row
  (21-database-schema §3.2.3a). This is a recorded deviation pending Security sign-off on #835.
  Never changes on KEK rotation.
- Wrap layer: wrapped DEK under the KEK, AAD = `cv-dek-v1 ‖ credential_id ‖ kek_version`. Binding the
  wrapped DEK to `credential_id` stops a DB writer from swapping DEKs between rows; binding
  `kek_version` stops a downgrade to a retired wrap.

Rotation procedure (owner-run, app in maintenance or Degraded, no order flow required):
1. Provision KEK v(n+1) into custody (C1 / C3) alongside v(n); launcher supplies **both** handles
   (`CV_KEK_HANDLE` + `CV_KEK_PREV_HANDLE`, the latter only during rotation). FIFO order: current
   first, then previous, both in the handoff dir (`dirname(CV_KEK_HANDLE)`); cv-api drains them in
   that order.
2. Audit `security.kek_rotation_started` (from, to, row count) before the first row; on a re-run
   with rows still at v(n), `security.kek_rotation_resumed` (from, to, remaining).
3. Re-wrap job (admin-invoked; runs inside `secrets`, admin sees only a report — §7; implementation
   status: the job ships in E27-T02 #835, its entry point + the same-transaction per-row audit + step 2's
   `kek_rotation_resumed` are tracked in #2266): for each row
   `WHERE kek_version = n` (via `ix_api_keys_kek`), unwrap DEK with v(n), wrap with v(n+1), and in
   **one transaction** update `dek_ref` + `kek_version` **and** write its per-row progress audit
   record. Ciphertext and `enc_nonce` untouched. Idempotent and resumable.
4. Verify: zero rows at version n; each re-wrapped DEK decrypts its ciphertext (in memory, discarded).
5. Audit `security.kek_rotated` (from, to, row count; no key material). Retire v(n) from custody,
   set `kek_versions.retired_at`, drop `CV_KEK_PREV_HANDLE`.
Budget: ≤50 rows in ≤5 s *(budget; measure in FU-1)*. Same job re-wraps E09 TOTP/recovery material
once E09 moves onto the KEK (FU-3 #2152).

## 6. Degraded mode (fail CLOSED)

| Condition | Result |
|---|---|
| handle missing / unreadable / timeout / short or long read / bad mode or owner | **Degraded**; `kek_unavailable` or `kek_handle_permissions` |
| KCV mismatch | Degraded; reason `kek_mismatch` |
| handoff anomaly (extra reader) | launcher stops the stack; `security.kek_handoff_anomaly` |
| `file` + `live` | **fatal exit** (`kek_source_not_permitted`) — never Degraded |

In Degraded (KEK): market data stays live; **every operation needing the KEK fails closed**:
- signing / order entry: broker raises typed `KekUnavailable` (`secrets.errors`); order routes 403
  with problem type `kek_unavailable` (E09 route gating);
- key add, key verify/test and key rotation: 403 `kek_unavailable` (rotation preconditions fail);
- the hourly C-2.8 withdrawal-permission check **fails** (recorded as a failed check, alert raised) —
  it is never skipped or reported green;
- `/health` and the `system` WS topic report `secrets` red with reason; critical alert; UI blocking
  banner (E27-D03 / E27-S02); this remediation text is logged verbatim:
`KEK unavailable (reason=<r>): trading disabled. Ensure the host launcher/systemd credential supplies
CV_KEK_HANDLE, then restart cv-api via the launcher. See docs/ops/runbooks/kek-custody.md.`
No runtime re-load in v1: recovery is a launcher restart.

Observability (specified, implemented by T02): `cv_kek_load_seconds` (histogram),
`cv_kek_load_failures_total{reason}` (`kek_unavailable|kek_mismatch|kek_handle_permissions`),
`cv_kek_version` (gauge). Audit: `security.kek_loaded`, `security.kek_load_failed`,
`security.kek_rotation_started`, `security.kek_rotation_resumed`, `security.kek_rotated`,
`security.kek_handoff_anomaly`.

## 7. Loader interface for E27-T02

Lives in `candleviewer/secrets/` (M2). Only `secrets` holds the KEK. The KEK types below are
**private to `secrets`** (leading-underscore module, not re-exported); callers **outside `secrets`**
— including `admin` — get operations returning coarse metadata, never key or DEK bytes (C-2.7, C-3.2).

```python
# secrets/_kek.py — private
class _KekSource(Protocol):
    def load(self) -> _LoadedKek: ...      # raises KekLoadError(reason=...)
class _LoadedKek:                          # repr/str "***"; not picklable; close() zeroes
    version: int
    def wrap_dek(self, dek: bytes, *, credential_id: UUID) -> bytes: ...
    def unwrap_dek(self, wrapped: bytes, *, credential_id: UUID) -> bytearray: ...
def _source_from_settings(settings: Settings) -> _KekSource: ...   # enforces §4 hard rules

# secrets/__init__.py — public surface for admin / exchange.bybit
async def verify_kek_possession() -> KekCheckResult: ...  # version, kcv_ok, reason; no bytes
async def rewrap_deks(from_version: int, to_version: int) -> RewrapReport: ...  # counts only
```

Implementations: handle source (★ prod) and file source (dev/ci, refuses live). `SecretsService.start()`
loads; on `KekLoadError` it records the reason, emits audit + metric and reports health red so the
supervisor enters Degraded (§6). Tests use an in-memory fake source — never a real KEK, no network.

## 8. Break-glass CLI (#2119) — offline KEK load

Per the #2119 decision the CLI lives under `candleviewer.admin` (allowed to import `secrets`, C-3.2):
- Entry `python -m candleviewer.admin.breakglass`; on WSL run via the launcher
  (`cv-launch.ps1 breakglass`, same stdin/FIFO handoff), on the VPS via
  `systemd-run -p LoadCredentialEncrypted=...`. No new custody path.
- Proof of KEK possession = `secrets.verify_kek_possession()` (load + constant-time KCV). Fails closed.
  **As decided (#2119 O1):** the CLI uses `secrets.prove_kek_possession()` instead. It runs the boot
  custody path but never enrols a KEK, refusing `kek_not_enrolled` in every environment.
- Postgres direct, no listener, refuses while `cv-api` holds the run lock; `file` source in `live` refused.
- ★ **Second factor in `live`:** the operator must supply one unused Owner recovery code (SR-023 sealed
  envelope), verified offline against its hash in the DB and consumed. KEK + host access alone is not
  enough in `live`.
- ★ The CLI writes its host-local append-only audit record **before** it acts (intent), then an outcome
  record; both fold into `audit_log` on next boot (E09 threat model §3.6.1; lifespan ack with Agent A
  per #2119).

## 9. Restore drill, inconclusive items, follow-ups

Restore drill (FU-1): restore a Postgres dump on a host with no KEK source; expect `kek_unavailable`,
Degraded, every order and key route 403, zero decrypted rows. Supply the correct KEK → Running. Wrong
KEK → `kek_mismatch`, still nothing decrypts.

Not proven desk-side (the ticket's "inconclusive" branch applies only to these):
- **FU-1 #2151** host drill: timing table for (a)/(b)/(c); non-visibility transcript (`docker inspect`,
  sibling `/proc/1/environ`, grep of every mounted volume); handoff-anomaly test; interop-disabled
  check; unattended-reboot test; restore-drill log; KEK absent from crash reports, Docker and app logs.
  Interim control: T02 adds a CI test that compose has no `CV_KEK*` under `environment:`.
- **FU-2** runbook `docs/ops/runbooks/kek-custody.md` — in E27-T02 #835 scope.
- **FU-3 #2152** move E09 TOTP/recovery keys under KEK-wrapped DEKs.
- **FU-4** `kek_versions` migration — in E27-T02 #835 scope.

## 10. ★ Recommendation summary

1. Custody: WSL — Windows Credential Manager via host launcher, with WSL interop **disabled**; VPS —
   `systemd-creds` `LoadCredentialEncrypted` (TPM2 if present), `age` `0400` fallback, identity never
   beside ciphertext.
2. Injection: handle `/run/secrets/cv_kek`. WSL: stdin → `wsl.exe` → fresh `0700` dir, `0600` FIFO,
   written once, unlinked, nonce-acked; Docker Engine in WSL; launcher is the only supervisor. VPS:
   systemd credential (not read-once; residual recorded). Never env/argv/`Settings`.
3. Rotation: dual-handle window, resumable per-row re-wrap with per-row audit in the same transaction,
   started/resumed/rotated events; separate `kek_version` (wrap AAD + `credential_id`) from `key_version`.
4. Degraded: fail closed for signing, key add/verify/rotate and the hourly withdrawal check; 403,
   health red, critical alert; `file`+`live` fatal. SR-009 hygiene is a T02 acceptance criterion.
5. Interface: private `_KekSource`/`_LoadedKek` in `secrets`; public `verify_kek_possession()` and
   `rewrap_deks()` return metadata only. Break-glass in `admin` needs KEK + an Owner recovery code in
   `live` and audits before acting.
