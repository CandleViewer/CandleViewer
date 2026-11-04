# Offline audit-chain check runbook (E43-T10, #1238)

Status: written 2026-11-04 for the first slice of #1238; not yet run on a deployed host. The run on
the demo host waits on E29-K01 and #1220. No connection string, password, host address or audit
entry content belongs in this file or in a ticket comment.

The API checks the chain itself at start-up and nightly (`cv_audit_verify_*`, the alerts
`AuditChainVerificationFailed` and `AuditVerifyNotPassing` in
[`07-release-and-prr.md`](../../plan/07-release-and-prr.md)). This tool is a read-only check an
operator or a reviewer runs from a shell: on demand, after an incident, before a release, and for
the pen-test's audit scope item (`04-security-program.md` §13.2 item 10). It needs no API process,
writes nothing and engages no halt. It walks the chain with the in-app verify's own code
(`AuditQueryService.plan_verify` and `run_verify`: one walk, one verify statement, one budget).

## What it checks

| Section           | Pass means                                                                                                                                |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `grants`          | On `audit_log` and `audit_checkpoints`, over all seven table privileges: `cv_app` holds exactly SELECT and INSERT, `cv_ro` exactly SELECT |
| `triggers`        | The five guard triggers of `0003_audit_log` exist on their tables and are enabled                                                         |
| `fields`          | The deployed `audit_chain()` frames `prev_hash` and then the hashed fields in the order the verifier recomputes them                      |
| `chain`           | Every entry from genesis to the head links and recomputes to its stored hash, and every database checkpoint names its entry (SR-063)      |
| `checkpoint-file` | With `--checkpoint-file`: every head in the file names an entry with the same hash, and the file's sha256 is the recorded one             |

A break is named as `audit_ack_break` names one: `first_bad_id=<id> kind=<kind>`, with the kinds
`prev_hash_mismatch`, `entry_hash_mismatch`, `checkpoint_mismatch`, `checkpoint_missing` and
`tail_truncated`. Output names ids, hashes, roles and privileges only, and `entries_checked` on
every end. The checkpoint file is compared only against a chain with no break.

## Run it

1. Use a read-only login: `cv_ro` is enough. Every session the tool opens is read-only
   (`default_transaction_read_only`), whatever the login.
2. Put its connection string in `CV_AUDIT_VERIFY_DSN` without echoing it, for example from the
   host's secret store into the environment of this one command. The tool never reads
   `CV_PG_DSN`: with `CV_AUDIT_VERIFY_DSN` unset it refuses to run.
3. Run, on the host or a machine that reaches Postgres over the tailnet:

   ```sh
   cd services/api
   uv run --frozen python -m candleviewer.audit_chain_verify \
     --checkpoint-file /path/to/audit-heads.jsonl --checkpoint-sha256 <recorded sha256>
   ```

   `--batch` (1 to 10 000 entries per read, default 2 000) and `--timeout` (seconds for the whole
   run, default 3 600, at most 21 600) bound the load; each read keeps the in-app verify statement
   budget and per-entry cap (`CV_AUDIT_VERIFY_STATEMENT_TIMEOUT_MS`,
   `CV_AUDIT_VERIFY_MAX_ENTRY_BYTES`). The default is twice the scheduled run's 1 800 s because
   this run has one connection of its own; run it off-peak.

4. Read the exit status: `0` every section passed; `1` a check failed; `2` a usage or settings
   error, nothing ran; `3` stopped (`timeout`, `store_unavailable`, `hasher_busy`,
   `entry_too_large@<id>`, `internal_error`): the result is unknown and never a pass.

`--check` runs only `grants`, `triggers` and `fields` against the database, without the walk.
`--self-test` runs every section on a seeded in-memory chain with a changed, a dropped and a
re-ordered entry, a widened grant, a disabled guard, a changed field order and a diverging file;
it needs no database.

## When it fails

- `chain` or `checkpoint-file` with a `first_bad_id`: a tamper signal. Keep the output and write
  nothing to the audit tables. This tool engages no halt and acknowledges nothing: an Owner
  confirms the break at once with the in-app `verifyAuditChain`, which records it, pages and halts
  position-opening orders under the enforced posture (`04-security-program.md` §8.1). The
  acknowledgement path is the one in `07-release-and-prr.md` (AuditBreakHaltEngaged).
- `grants`, `triggers` or `fields`: the append-only guarantee or the hash framing no longer holds
  at the database. Re-apply `infra/scripts/pg_bootstrap.sql` and the migrations as `cv_owner`, run
  the tool again, and open a security ticket naming the role, privilege or trigger it named.
- A checkpoint-file `sha256` or `line` finding alone: the copy or its record differs. Copy again;
  if it persists, treat the file itself as suspect and escalate as a break.
- `3` (stopped): fix the cause (the reason line names it) and run again; a stop is never a pass.

## The checkpoint file (interim anchor) and the off-box target

The checkpoint job (`audit.checkpoint`) appends one JSON line per run (`head_id`, `head_hash`,
`row_count`, `created_at`) to a local path outside the database volume. It is an interim anchor,
not the SR-068 mirror: nothing on `main` writes it yet (`run_checkpoint` has no caller), so today
this section runs on files you supply. SR-068 reads: "The audit log MUST be mirrored off-box at
least daily (append-only target) so that a host compromise cannot silently erase history; the
mirror's chain head is compared with the local head, and divergence raises a P1 alert." PROPOSED
for that target, to be decided with the owner on #1238 before any code: a writer that cannot
rewrite or delete earlier lines, a recorded sha256 per copy, and read access separate from write.
