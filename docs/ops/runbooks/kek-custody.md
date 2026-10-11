# KEK custody runbook (E27-K01 FU-2, implemented by E27-T02)

Status: written 2026-10-11 against the E27-T02 branch. Design owner: `docs/plan/spikes/e27-kek.md`
and ADR-0009. No secret, key material or host-specific address belongs in this file. Host-side
launcher/systemd steps marked **FU-1** are not yet drilled on a real host (#2151).

## What the app expects

| Setting | Meaning |
|---|---|
| `CV_KEK_SOURCE` | `handle` (prod), `file` (dev/ci only — **cv-api refuses to start in `live`** with `kek_source_not_permitted`), `none` |
| `CV_KEK_HANDLE` | path yielding exactly 32 raw bytes: the read-once FIFO (`0600`, WSL) or the systemd credential file (`0400`, VPS); owned by the service uid, never a symlink |
| `CV_KEK_VERSION` | version of the supplied KEK; its KCV must match `kek_versions` |
| `CV_KEK_PREV_HANDLE` | previous KEK, **only** during a rotation window |
| `CV_KEK_ACK_PATH` | writable path where cv-api echoes the handoff nonce (the handoff dir is read-only) |

The KEK must never appear in compose `environment:`, `.env`, argv, logs or `Settings`. CI enforces the
compose rule (`tests/unit/credentials_m2/test_compose_kek.py`).

## Host hygiene (SR-009) — required before go-live

- Core dumps off: `ulimit -c 0` / systemd `LimitCORE=0` / compose `ulimits: core: 0`. cv-api also sets
  `RLIMIT_CORE=0` and `PR_SET_DUMPABLE=0` itself before loading the KEK.
- `kernel.yama.ptrace_scope >= 1`; no `SYS_PTRACE` capability on the container.
- Swap off or encrypted.
- WSL: `/etc/wsl.conf` `[interop] enabled=false`, `appendWindowsPath=false`.
- Compose `restart: "no"` for `api`; the launcher is the only restart supervisor (**FU-1**).

<a id="alert-kekunavailable"></a>

## Symptom: app is Degraded with `secrets.kek_unavailable`

Signals: `/readyz` and the `system` WS topic show the critical notice; `cv_kek_load_failures_total{reason}`
increments; audit `security.kek_load_failed`; `cv_kek_version_state` = 0. Order placement is refused, every
credential operation raises `kek_unavailable`. The log line contains this remediation verbatim:

> KEK unavailable (reason=<r>): trading disabled. Ensure the host launcher/systemd credential supplies
> CV_KEK_HANDLE, then restart cv-api via the launcher. See docs/ops/runbooks/kek-custody.md.

| reason | Check |
|---|---|
| `kek_unavailable` | handle missing, timed out (10 s), or not exactly 32 bytes; handoff nonce missing or ack already present |
| `kek_handle_permissions` | mode is not `0400` (file) / `0600` (FIFO), wrong owner, or a symlink |
| `kek_mismatch` | wrong KEK for `CV_KEK_VERSION` (KCV differs) — do **not** retry with other keys |

Recovery: fix custody, then restart cv-api **via the launcher**. There is no runtime reload; a passing
mesh self-check never clears the KEK latch.

## KEK rotation (owner-run, maintenance window)

1. Provision KEK v(n+1) in custody alongside v(n). Start cv-api with `CV_KEK_VERSION=n+1`,
   `CV_KEK_HANDLE` = v(n+1), `CV_KEK_PREV_HANDLE` = v(n).
2. Run the admin re-wrap (`secrets.rewrap_deks(n+1)`, counts only). Audit `security.kek_rotation_started`
   then `security.kek_rotated`. Ciphertext and `enc_nonce` are untouched; the job is idempotent and
   resumable — if killed, rerun it.
3. Verify the report shows `remaining = 0`, then set `kek_versions.retired_at` for v(n), retire v(n)
   from custody and restart without `CV_KEK_PREV_HANDLE`.

## Restore drill

Restore a dump on a host with **no** KEK: expect Degraded `kek_unavailable` and zero decryptions.
Supplying a wrong KEK gives `kek_mismatch`. Automated equivalent:
`tests/unit/credentials_m2/test_broker.py::test_broker_dump_without_kek_cannot_decrypt`.
