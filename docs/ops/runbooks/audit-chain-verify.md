# Offline audit-chain check runbook (E43-T10, #1238)

Status: slice 1 of #1238 (2026-11-04), not yet run on a deployed host; the demo host run waits on
E29-K01 and #1220. No DSN, password, host address or audit entry content goes here or in a ticket.

The API verifies the chain at start-up and nightly (`cv_audit_verify_*`; alerts in
[`07-release-and-prr.md`](../../plan/07-release-and-prr.md): `AuditChainVerificationFailed`,
`AuditVerifyNotPassing`). Operators and reviewers run this read-only shell check on demand, after
an incident, before a release and for the pen-test audit scope (`04-security-program.md` §13.2 item
10). It needs no API process, writes nothing, engages no halt and walks the chain with the in-app
verify's own code (`AuditQueryService.plan_verify`, `run_verify`: one walk, statement and budget).

## What it checks

| Section           | Pass means                                                                                                                                                                                                          |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `grants`          | On `audit_log` and `audit_checkpoints`, over all seven table privileges, column-level grants, PUBLIC and every role the login can become included: `cv_app` holds exactly SELECT and INSERT, `cv_ro` exactly SELECT |
| `triggers`        | The five guard triggers of `0003_audit_log` exist on their tables and fire for an ordinary session: a disabled or replica-only trigger is a finding                                                                 |
| `fields`          | The deployed `audit_chain()` frames `prev_hash` and then the hashed fields in the order the verifier recomputes them                                                                                                |
| `chain`           | Every entry from genesis to the head links and recomputes to its stored hash, and every database checkpoint names its entry (SR-063)                                                                                |
| `checkpoint-file` | With `--checkpoint-file`: every head in the file names an entry with the same hash, and the file's sha256 is the recorded one                                                                                       |

Until slice 2 of #1238 lands, the `fields` section prints `SKIP fields: lands in slice 2`, never a
pass, and neither `--check` nor `--self-test` checks the field order.

A break reads `first_bad_id=<id> kind=<kind>` as in `audit_ack_break`; the kinds are
`prev_hash_mismatch`, `entry_hash_mismatch`, `checkpoint_mismatch`, `checkpoint_missing`,
`tail_truncated`. Output names ids, hashes, roles and privileges only, and `entries_checked` on
every end; the checkpoint file is compared only against an unbroken chain.

## Run it

1. Log in read-only (`cv_ro`); tool sessions are `default_transaction_read_only` whatever the login.
2. Set `CV_AUDIT_VERIFY_DSN` without echoing it (say, from the host's secret store for this one
   command). The tool never reads `CV_PG_DSN`; without `CV_AUDIT_VERIFY_DSN` it refuses to run.
3. Run, on the host or a machine reaching Postgres over the tailnet:

   ```sh
   cd services/api && uv run --frozen python -m candleviewer.audit_chain_verify \
     --checkpoint-file /path/to/audit-heads.jsonl --checkpoint-sha256 <recorded sha256>
   ```

   `--batch` (1 to 10 000 entries per read, default 2 000) and `--timeout` (whole run, at most
   21 600 s; default 3 600, twice the scheduled 1 800 as this run has its own connection: run it
   off-peak) bound the load; each read keeps the in-app verify statement budget and per-entry cap
   (`CV_AUDIT_VERIFY_STATEMENT_TIMEOUT_MS`, `CV_AUDIT_VERIFY_MAX_ENTRY_BYTES`).

4. Read the exit status: `0` every section passed; `1` a check failed; `2` a usage or settings
   error, nothing ran; `3` stopped (`timeout`, `store_unavailable`, `hasher_busy`,
   `entry_too_large@<id>`, `internal_error`): the result is unknown and never a pass.

`--check` runs only `grants`, `triggers` and `fields`, with no walk. `--self-test` needs no
database: every section runs on a seeded in-memory chain with a changed, a dropped and a re-ordered
entry, a widened grant, a disabled guard and a diverging file.

## When it fails

- `chain` or `checkpoint-file` with a `first_bad_id`: a tamper signal; keep the output and write
  nothing to the audit tables. The tool acknowledges nothing: an Owner at once confirms it with the
  in-app `verifyAuditChain`, which records, pages and halts position-opening orders under the
  enforced posture (`04-security-program.md` §8.1); acknowledge per `07-release-and-prr.md`
  (AuditBreakHaltEngaged).
- `grants`, `triggers` or `fields`: the database no longer holds the append-only guarantee or the
  hash framing. Re-apply `infra/scripts/pg_bootstrap.sql` and the migrations as `cv_owner`, rerun,
  and open a security ticket naming the role, privilege or trigger the tool named.
- A checkpoint-file `sha256` or `line` finding alone: the copy or its record differs. Copy again;
  if it persists, treat the file as suspect and escalate as a break.
- `3` (stopped): fix the cause the reason line names and rerun; a stop is never a pass.

## The checkpoint file (interim anchor) and the off-box target

The checkpoint job (`audit.checkpoint`) appends a JSON line per run (`head_id`, `head_hash`,
`row_count`, `created_at`) to a local path outside the database volume: an interim anchor, not the
SR-068 mirror. Nothing on `main` writes it yet (`run_checkpoint` has no caller); you supply the
file. SR-068 reads: "The audit log MUST be mirrored off-box at least daily (append-only target) so
that a host compromise cannot silently erase history; the mirror's chain head is compared with the
local head, and divergence raises a P1 alert." PROPOSED (the owner decides on #1238 before any
code): an append-only writer, a recorded sha256 per copy, and read access separate from write.
