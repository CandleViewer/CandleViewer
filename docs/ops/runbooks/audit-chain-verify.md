# Offline audit-chain check runbook (E43-T10, #1238)

Status: written 2026-11-04 against the #1238 draft branch; not yet run on a real host. The run on
the demo host waits on E29-K01 and #1220. No connection string, password, host address or audit
entry content belongs in this file or in a ticket comment.

The API checks the chain itself at start-up and nightly (`cv_audit_verify_*`, the alerts
`AuditChainVerificationFailed` and `AuditVerifyNotPassing` in
[`07-release-and-prr.md`](../../plan/07-release-and-prr.md)). This tool is the independent,
read-only check an operator or a reviewer runs from a shell: on demand, after an incident, before
a release, and for the pen-test's audit scope item (`04-security-program.md` §13.2 item 10). It
needs no API process and writes nothing.

## What it checks

| Section       | Pass means                                                                                                              | Stable failure codes                                                                                                                |
| ------------- | ----------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `grants`      | `cv_app` holds exactly SELECT and INSERT on `audit_log` and `audit_checkpoints`; `cv_ro` exactly SELECT (C-5.7)         | `grant_mismatch` (extra or missing privileges named), `grant_absent`                                                                |
| `triggers`    | The five guard triggers of `0003_audit_log` exist on their tables and are enabled                                       | `trigger_absent`, `trigger_disabled`                                                                                                |
| `chain`       | Every entry from genesis to the head links to the one before it and recomputes to its stored hash (SR-063)              | `chain_entry_hash_mismatch` (changed), `chain_prev_hash_mismatch` (dropped or moved), `chain_id_order`                              |
| `checkpoints` | Every `audit_checkpoints` head names an entry with the same hash                                                        | `checkpoint_divergence`, `checkpoint_head_missing`, `checkpoint_ahead_of_local` (local tail truncated)                              |
| `mirror`      | Every head in the off-box file names a local entry with the same hash; the file's sha256 is the one the target recorded | `mirror_divergence` (both heads named), `mirror_head_missing`, `mirror_ahead_of_local`, `mirror_file_digest`, `mirror_line_invalid` |

A failure names an entry id, a hash, a role or a privilege, never an entry's fields. The chain
section stops at the first break; checkpoints and the mirror are compared only against an intact
chain.

## Run it

1. Use a read-only login: `cv_ro` is enough. Every session the tool opens is read-only
   (`default_transaction_read_only`), whatever the login.
2. Put the connection string in `CV_AUDIT_VERIFY_DSN` without echoing it, for example read it from
   the host's secret store into the environment of this one command. Never paste it in a shell
   history, a ticket or a chat.
3. Copy the off-box mirror file (the checkpoint job's JSON lines) from its target to a local path,
   and note the sha256 the target recorded for it.
4. Run, on the host or a machine that reaches Postgres over the tailnet:

   ```sh
   cd services/api
   uv run --frozen python -m candleviewer.audit_chain_verify \
     --mirror /path/to/audit-heads.jsonl --mirror-sha256 <recorded sha256>
   ```

   `--batch` (1 to 10 000 entries per read, default 2 000) and `--timeout` (seconds for the whole
   run, default 3 600) bound the load. Each read uses the API's verify statement and its statement
   budget.

5. Read the exit status: `0` every section passed; `1` a section failed (the `FAIL` lines say
   which); `2` nothing could be concluded (no connection string, the database unreachable, a read
   refused or timed out). `2` is never a pass.

Two checks need no database and run in CI or on a laptop: `--check` compares the tool's
expectations with the shipped migrations (the hashed field order of the latest `audit_chain()`,
the REVOKE set and the guard triggers of `0003_audit_log`); `--self-test` runs every check on a
seeded chain with a changed, a dropped and a re-ordered entry, a diverging mirror and a widened
grant.

## When it fails

- `chain_*`, `checkpoint_*` or `mirror_divergence` / `mirror_ahead_of_local`: treat it as
  `AuditChainVerificationFailed` (a security incident, IR-06). Keep the output, name the break by
  its id and kind, and do not write to the audit tables. This tool writes nothing, so it engages
  no trading halt: run the in-app verify (`verifyAuditChain`, Owner) over the named id at once,
  which halts position-opening orders under the enforced posture (`04-security-program.md` §8.1).
  The acknowledgement path is the one in `07-release-and-prr.md` (AuditBreakHaltEngaged).
- `grant_*` or `trigger_*`: the append-only guarantee no longer holds at the database. Re-apply
  `infra/scripts/pg_bootstrap.sql` and the migrations as `cv_owner`, run the tool again, and open
  a security ticket naming the role and privilege the output named.
- `mirror_file_digest` or `mirror_line_invalid` alone: the copy or the target's record differs.
  Copy again from the target; if it persists, the off-box record itself is suspect: escalate as a
  mirror divergence.

## Mirror target and its access control

The checkpoint job (`audit.checkpoint`) appends one JSON line per run (`head_id`, `head_hash`,
`row_count`, `created_at`) to a file outside the Postgres volume. SR-068 needs that file mirrored
off the box daily to an append-only target whose writer cannot delete or rewrite earlier lines,
with the target recording each copy's sha256. The target, its credentials and the daily job are
open decisions on #1238; until they land, this tool compares a mirror file you supply.
