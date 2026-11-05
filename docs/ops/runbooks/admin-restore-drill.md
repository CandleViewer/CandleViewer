# Runbook: restore drill and the admin restore path (E42-T06)

Status: written 2026-11-03 against `main` at `d023df0f6`; not yet drilled (E48-Q02 rehearses it).
Owner: accounts-admin (E42-T06, #1085). Contributed to E48-T03's runbook set as RB-08 (restore) and as input to E48-T04's
disaster-recovery playbook. The audit-chain step is [`admin-audit-integrity.md`](admin-audit-integrity.md).

Conventions: REST paths are relative to `$API`, your API base URL; `$TOKEN` is an Owner access token, sent as
`Authorization: Bearer $TOKEN`. Every state-changing call (`POST`, `PUT`, `PATCH`, `DELETE`) also sends the session's
CSRF token twice, as `X-CSRF-Token: $CSRF` and as `Cookie: __Host-cv_csrf=$CSRF`: there is no bearer exemption, and a
write without both answers `403 csrf_token_invalid` (SR-041). `$CSRF` is your own session's `__Host-cv_csrf` cookie
value, set at sign-in and re-issued by `GET $API/auth/session` when it is missing or no longer valid. All three come
from your own session and environment, never from this page. No secret, key material, host address or exploit detail
belongs in this file (C-12.2); the backup key of any drill is never written here. Paths under `candleviewer/` mean
`services/api/candleviewer/`. Where a procedure needs something that does not exist, it says **BLOCKED — not
implemented** with its tracking reference and offers no substitute command. This file links the restore procedures
instead of copying them.

## What exists today, and what does not

- **Runs today:** the E07 scripted drill: `docs/security/drills/E07-backup-restore-drill.md` (the procedure and its records),
  `infra/scripts/restore_drill.sh`, and `services/api/tests/integration/storage/test_restore_drill.py`, which the CI
  `integration` job runs on every PR (its JSON report is the `restore-drill-report` artefact). It uses fixtures and a
  throwaway key, restores Postgres and one Parquet partition into a scratch environment, and checks the audit chain and the
  partition checksums. It proves the mechanism, not a real deployment's backups.
- **Documented, run by an operator:** the restore procedures and the monthly scratch-namespace drill are
  [`21-database-schema.md`](../../plan/21-database-schema.md) §8.2 and §8.4. The targets (RPO and RTO per store) and the rule
  that a missed target is a **fail**, logged as a P1 finding with a remediation ticket, are
  [`07-release-and-prr.md`](../../plan/07-release-and-prr.md) §5.3; they are not copied here.
- **Contracted, not available: the admin area's backups.** The Backups screen (SCR-146) and the operations `listBackups`,
  `getBackup`, `createBackup`, `verifyBackup`, `issueBackupDownload`, `downloadBackup`, `deleteBackup` and `restoreBackup` are in
  the contract. On `main` every `/admin/backups*` route answers `501 not_implemented` until a backup engine sets
  `BACKUPS_CATALOGUED` (`candleviewer/backups_wiring.py:81`; the engine is #3319), and `restoreBackup` is not mounted
  (the `POST /admin/backups/{backupId}/restore` row of `services/api/tests/contract/rbac/matrix.yaml`) until the
  Owner's D7 decision and #3084 (BK-14).
  **The console restore is BLOCKED — not implemented.**

## Trigger

A scheduled drill (`21` §8.4: monthly; a PRR gate item), a release train that touches the data layer, or a real restore
after data loss or corruption.

## Detection

- `BackupLastSuccessStale` in [`07-release-and-prr.md`](../../plan/07-release-and-prr.md) §9 reads
  `cv_backup_last_success_age_seconds{kind}` (`20-architecture.md` §12.1). That series has no sample until the engine
  records runs, so the alert cannot fire today.
- The drill's own evidence: the CI `integration` job's report, and the drill record the operator writes.
- Records of the admin backups surface, once served: `backup.run`, `backup.verified`, `backup.deleted`, `backup.restore`.

## Prerequisites

A scratch environment that holds no live credentials and no path to the exchange; the backup set under test; an Owner for the
audit-chain check. A real restore additionally needs maintenance mode on first
([`admin-maintenance-mode.md`](admin-maintenance-mode.md)).

## Steps

1. **Confirm the scripted drill is green.**
   **Do:** read the latest CI `integration` run of `test_restore_drill.py` and its `restore-drill-report`.
   **Expect:** the restore completed, the chain verified and the partition checksums matched; a red run is a finding, not a
   note.
2. **Restore into a scratch environment.**
   **Do:** follow `21` §8.2 (Postgres to a target time, QuestDB, the Parquet lake) on the scratch host only, timing from
   the decision to restore: its QuestDB step deletes the database directory before it copies the snapshot back. Two of
   its lines run tools that do not exist, `candleviewer.tools.audit_verify` and `candleviewer.tools.cold_verify`:
   **BLOCKED — not implemented** (no ticket yet), so leave those two lines out. The audit chain is step 3's check, and the
   partition checksums are what the scripted drill checks (step 1). The post-restore reconciliation `21` §8.3 names
   (`candleviewer.tools.post_restore`) does not exist either: **BLOCKED — not implemented** (#5629; the reconciliation
   it stands for is E45-T01's).
   **Expect:** a booting, queryable instance within the RTO of `07` §5.3 and data loss within its RPO.
3. **Verify the audit chain on the restored instance.**
   **Do:** `POST $API/admin/audit/verify` against the scratch API, as in [`admin-audit-integrity.md`](admin-audit-integrity.md)
   step 1.
   **Expect:** `verified: true` and `entries_checked` above 0; a break is that runbook's incident, in the scratch environment
   first.
4. **Judge and record.**
   **Do:** mark the result **pass or fail** against each target of `07` §5.3 and log it in
   [`32-risk-register.md`](../../plan/32-risk-register.md) as that section requires. Recording it as a `backups` row with
   `verify_method='restore_smoke'` (`21` §8.4) waits for the catalogue: **BLOCKED — not implemented** (#3319).
   **Expect:** a dated record that names the figures, the method and any gap.
5. **After a real restore: trading stays off until re-enabled on purpose.**
   **Do:** the contract force-disables trading for the restore and requires an explicit re-enable afterwards, so a restore
   never resumes order flow against stale OMS state (`22` `restoreBackup`); the model's step 7 holds the halt outside the
   database being replaced (`docs/security/threat-models/e42-admin.md` §6). Re-enable only after the chain verifies and
   the reconciliation (E45-T01) has run, the order E48-T04's playbook fixes.
   **Expect:** no order accepted until then. Restoring from the console is **BLOCKED — not implemented** (D7, #3084), so
   today this step is the operator's, outside the admin area.

## Verification

The scratch instance boots and answers readiness; the chain verifies; the counts of `orders` and `executions` match the source
within the expected window; and the figures are marked pass or fail against the targets and recorded.

## Rollback, and what cannot be undone

A scratch drill is thrown away: nothing in it needs undoing, and nothing from it ever points at the live deployment or its
credentials. A real restore replaces the live data and **cannot be undone** from the restored state: take and keep a copy of
what is being replaced first, and keep the evidence of the failure that made the restore necessary (`auth-rbac.md` §5 for an
audit break). The contract's order for the console restore (maintenance on, no run in progress, a usable backup, the position
acknowledgements, a `backups` step-up with no grace that is spent before the preconditions are checked) is `22`
`restoreBackup`; none of it is served.

## Known gaps

| Gap                                                                                                     | Reference                           |
| ------------------------------------------------------------------------------------------------------- | ----------------------------------- |
| Every `/admin/backups*` route answers `501`: no backup engine, no catalogue                             | #3319 (`BACKUPS_CATALOGUED`)        |
| `restoreBackup` is not mounted                                                                          | D7 (Owner), #3084 (BK-14)           |
| The post-restore reconciliation tool named in `21` §8.3 does not exist                                  | #5629; E45-T01 (the reconciliation) |
| The `audit_verify` and `cold_verify` tools named in `21` §8.2 do not exist                              | no ticket yet                       |
| The drill's own record row (`backups`, `restore_smoke`) cannot be written until the catalogue is served | #3319                               |
| No drill has been run on a real deployment's backups                                                    | E48-Q02, E48-T04                    |

## Execution record

Not executed: no staging host exists (#1778 item A). The scripted drill ran green in CI (its record is
`docs/security/drills/E07-backup-restore-drill.md`); the operator's drill and the console restore are E48-Q02's and E48-T04's.
Every statement above was read against the code and the contract at `d023df0f6`.
