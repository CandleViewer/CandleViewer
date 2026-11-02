# ADR-0041 — The backup engine: a sidecar with read-only and restore roles, age artefacts to an offline key, and a restore halt latch (#3319)

- Status: **proposed** (2026-11-02). Decision deadline: ratification before the first code PR of #3319 (B1) opens;
  no engine code is written before this record is ratified (C-3.4). The options were ruled on 2026-11-02 by the
  delivery orchestrator under the owner's 2026-10-29 delegation (#2701). The seven rows the BQ list marked OWNER
  (BQ-01, BQ-02, BQ-04, BQ-06, BQ-07, BQ-08, BQ-19) are **ruled under the delegation, pending the owner's veto
  through the next owner digest on #2701**; a veto re-opens the decision it names before B1, or, if B1 has merged,
  through an amendment of this record.
- Date: 2026-11-02
- Deciders: Owner (`@basiltt`) through the delivery orchestrator (the delegation on #2701; the BQ rulings on #3319);
  the Security engineer through the `security-review` label (C-10.2); the architect as CODEOWNER of `docs/plan/`.
- Consulted: the #3319 BQ list (21 questions, scouted at `main` `e5b286ed5`) and its rulings; ADR-0003 (the backup
  sidecar), ADR-0009 §7, ADR-0039 (an M2-held key handed out as a capability); `04-security-program.md` SR-090 to
  SR-093; `docs/security/threat-models/e42-admin.md` §6 (the restore path).
- Numbering note: 0031 is reserved by E45-K01 (`ADR-0031-resilience-and-chaos`, not on `main`) and 0040 is the last on
  `main`, so this record takes 0041. ADR-0025, named in an early brief as the backup ADR, is the audit-query ADR; no
  backup ADR existed before this one.
- Related: #3319 (this record is its PR A), #966 (E42-T05: the backups surface, its ports and services), #3084
  (AD-F02, D7: the restore contract and riders A and B), #1255 (E45-T10, the restore drills), #890 (E42-X01: AD-S11,
  AD-F07, AD-T05, AD-I04, AD3, AD7), #2701 (the owner ledger and digest), #5433 (edits the alert file B2 changes).
- Evidence: module paths are under `services/api/candleviewer/`; `22` is `docs/plan/22-api-openapi.yaml`, `21` is
  `docs/plan/21-database-schema.md`, `04` is `docs/plan/04-security-program.md`.

## Context and problem statement

E42-T05 (#966) shipped the backups surface: the contract, the `backups` catalogue (`0028`, `0032`), the admission
lock, the services that record (`admin/backups/runs.py`, `rows.py`, `verify.py`, `deletion.py`, `restore.py`) and
the ports an engine plugs into (`admin/backups/ports.py`: `BackupRunner`, `ScratchVerifier`, `ArtefactRemover`,
`RestoreExecutor`). Every route answers `501` because no component creates, verifies, removes or restores an
artefact (`BACKUPS_CATALOGUED = False` in `backups_wiring.py`). The ports' rule stands: the engine executes; the
services record, so no catalogue write or audit record goes through a port.

Five constraints shape the engine:

- **The key.** SR-091 and SR-092 require artefacts encrypted under a key distinct from the runtime KEK, held offline
  by the Owner, so the backup medium alone discloses nothing. `21` §8.1 and `22` `createBackup` already name age.
  The ticket's Scope said "a DEK wrapped by the KEK", which contradicts SR-091.
- **The database role.** `pg_dump` needs SELECT on every table; a whole-database `pg_restore` needs the rights of the
  objects' owner. `cv_app` has neither, and `pg_owner_dsn` is reserved for one retention purge (`settings.py`).
  An API process that held owner rights for its lifetime would turn any application compromise into a database-wide
  one, audit tables included (C-5.7).
- **The module graph.** M10 (`storage`) may import only M1 (CONSTITUTION §3); the engine's errors and plans live in
  M21 (`admin`). Engine code in `storage/` would be an M10 → M21 edge, a cycle (C-3.1).
- **A restore rewrites the security state.** Flags, kill switches, sessions, keys and the audit chain live in the
  database being replaced (`e42-admin.md` §6), so the trading halt held for a restore must live outside it.
- **The architecture already draws the component.** `20-architecture.md` §8.1 and ADR-0003 place a backup sidecar
  beside Postgres; nothing implements it.

## Decision drivers

1. SR-091 / SR-092 as written: no decryption capability on the host in normal operation.
2. Least privilege for the API process: no owner, restore or dump credential, and no write access to the backup
   volume.
3. No new edge in the monolith's import graph (C-3.1, C-3.2, C-3.4).
4. Every run, verification, deletion and restore recorded write-ahead by the services that already do so (C-2.9).
5. Trading cannot resume against restored state until the Owner says so (C-2.21, C-4.14).
6. Small, reviewable delivery (C-4.8): this record and the contract text first, then two code PRs.

## Considered options

| BQ  | Question                     | Options                                                                                             | Ruled             |
| --- | ---------------------------- | --------------------------------------------------------------------------------------------------- | ----------------- |
| 01  | Artefact key                 | (a) per-artefact DEK wrapped by the KEK; (b) per-artefact key wrapped to an offline backup key pair | (b)               |
| 02  | Automatic verification depth | (a) checksum, no key; (b) restore-into-scratch, key online                                          | (a); deep = drill |
| 03  | Format and placement         | (a) custom AES-GCM chunk framing; (b) age to an X25519 recipient; engine in `storage/` or not       | (b), not          |
| 04  | v1 kinds                     | all five; `pg_dump` and `config_bundle`                                                             | the two           |
| 06  | Key delivery for a restore   | (a) in the API request body; (b) out of band to the engine, one job                                 | (b), sidecar      |
| 07  | Role and placement           | (a) in-process engine, owner DSN in the API; (b) the sidecar, its own roles                         | (b)               |
| 13  | Scenario 4's re-check        | (a) the service's check under the lock; (b) a predicate passed into `remove`                        | (a)               |
| 19  | Restore halt                 | none; a file-backed latch outside Postgres                                                          | the latch         |

## Decision outcome

### 1. The backup sidecar (BQ-07, BQ-03)

The engine runs in **the backup sidecar** of `20-architecture.md` §8.1 and ADR-0003: its own container and image,
which alone carry the Postgres client tools and the age implementation. The API image gains neither.

- **Code.** The sidecar is a separate Python package in `services/api/` beside `candleviewer` and `cvdev`, built into
  its own image and absent from the API wheel and image. It imports no `candleviewer` module and `candleviewer` imports
  none of it; B1 adds an import-linter contract for both directions. It is a separate process, not a module of the
  API monolith, so it adds no row to CONSTITUTION §3 and no edge to its graph. If review holds that it needs a §3 row,
  the CONSTITUTION amendment (C-16.1) opens before B1.
- **No engine code in `storage/`.** The API-side port implementations are thin local-socket clients in
  `admin/backups/` (M21), using the standard library only: no new edge.
- **The channel.** The API reaches the sidecar over a Unix socket on a small volume shared by the two containers
  only, never the backup volume. The socket is reachable only by the API's user (file mode and a peer-credential
  check); the sidecar has no network listener. Requests and answers are versioned, size-bounded and strict (unknown
  fields refused); the vocabulary is `plan`, `run`, `verify`, `remove` and `restore`, keyed by the backup or job id.
  No request or answer carries a credential, a DSN or key material. Its schema is specified in
  `24-internal-schemas.md` by B1, which ships both ends.
- **The sidecar's own floor.** A well-formed request is not proof that it is wanted, so the sidecar keeps its own
  record of the runs it finished (id, kind, digest, `covers_to`, and the outcome of its own header check at each
  verification) on the backup volume and holds three rules no request can lift. A `remove` never takes the newest
  finished artefact of a kind in that record; the sidecar judges "newest" from its own record, never from the request
  or the catalogue. The API answers that refusal as `409 conflict` with rule `engine_retains_backup`
  (`22` `deleteBackup`), a policy conflict rather than a store failure. A removal is a delayed
  purge: the file is renamed to a quarantine name at once and deleted only after a grace period, during which the
  Owner can bring it back from the host. Runs are capped per window, so requests cannot fill the volume. B1 sets the
  grace period and the cap in the sidecar's configuration, not in the API, and tests each rule against a stream of
  well-formed requests.
- **Volumes.** The sidecar mounts the backup volume read-write; the API mounts it read-only (verify's digest pass and,
  once SEC-FU-L1 holds, downloads read it). The sidecar mounts no Postgres or QuestDB data volume.
- **Database roles.** A read-only **`cv_backup`** role (CONNECT, USAGE on the schema, SELECT on every table and
  sequence; no INSERT, UPDATE, DELETE, TRUNCATE or DDL) runs dumps. A separate **`cv_restore`** role, with the rights
  of the objects' owner, is used only by restore jobs. `cv_restore` is created `NOLOGIN`: the Owner's host-side step
  that delivers the identity for a restore job also enables its login with `VALID UNTIL` the job's deadline, which the
  sidecar caps at a configured maximum and shows at the intake with the job's id, digest and `covers_to`, and the
  runbook's closing step sets it back to `NOLOGIN` and ends any open session of the role; the expiry is the backstop
  if that step is missed, so the sidecar's stored password opens nothing between jobs. This relies on `pg_hba.conf`
  requiring `scram-sha-256` for `cv_restore`, since `VALID UNTIL` applies to password authentication only and an
  expiry closes no open session. The API refuses to start when its own login is a member of `cv_backup`, `cv_restore`
  or the owner role (a synchronous fail-closed check, C-2.21). Both credentials exist only in the sidecar, as password
  files on secret mounts readable by its user alone. The API process never holds an owner, restore or dump DSN and
  never uses `cv_app` for this (`21` §1.1). The roles' grants land in B1's single revision (C-5.3); passwords never
  appear in a migration.
- **The sidecar records nothing.** It never connects as `cv_app`, writes no catalogue row and no audit record; the
  E42-T05 services record every step, as the ports require.

### 2. Artefact format and key (BQ-01, BQ-03, BQ-05)

- **Format.** One file per artefact in the **age v1 format, encrypted to one X25519 recipient**: age's per-file key
  is the per-artefact DEK, wrapped to the recipient in the age header. No custom framing. A `pg_dump` artefact is the
  `-Fc` output (already a single file; no tar); a `config_bundle` artefact is a tar of the allow-listed files.
- **The key pair.** The **offline backup key pair** is distinct from the exchange-key KEK (SR-091, SR-092) and from
  every other key. The sidecar holds only the public recipient, which is configuration, not a secret, so a run, a
  scheduled run and the automatic verification need no secret. The identity (private half) is held offline by the
  Owner and reaches the sidecar only for a restore or a restore drill (section 4). The recipient's fingerprint (the
  SHA-256 over the lower-case Bech32 `age1…` recipient string as ASCII, written `age-x25519-sha256:<64 lower-case hex
digits>`) is pinned in the sidecar's configuration; the sidecar refuses to run while the recipient it would encrypt
  to does not match it. `encryption_ref` on the catalogue row is that fingerprint as the sidecar's plan reports it, a
  public value that keeps the column's class (`21` §12); a plan without one stays refused as `503
backup_engine_invalid` (E42-T05 BK-8).
- **Custody of the identity.** There is one recipient, so losing the identity loses every backup encrypted to it. The
  Owner holds the identity offline, never on the host that runs CandleViewer, and keeps an escrow copy sealed in a
  second place under their sole control; both are recorded in `21` §8.1's secrets row. Rotation: a new key pair is
  made offline, its fingerprint replaces the pinned one, and runs from then on are encrypted to it; the old identity
  is kept, with its escrow copy, while any artefact encrypted to it is kept (every artefact, since v1 prunes nothing).
  A suspected exposure of the identity rotates at once and is an incident. The restore drill of `21` §8.4 (monthly, a
  PRR gate item) opens a current artefact with the held identity, so a lost or wrong identity shows up there, not at a
  restore.
- **The implementation** of the format is the reference age tool, pinned by SHA-256 and recorded in `PINS.md`, given
  the identity through an anonymous pipe, never a path on disk; never a Python binding, which cannot overwrite the
  identity (#3319 ruling 4). "One supervised child per job" means one process group per job joined by kernel pipes,
  with no shell. Its dependency review (licence, pin, maintainer) lands in B1 under `security-review`.
- **Origin (v1).** The artefact's origin is the SHA-256 digest bound in the append-only `backup.run` record (ticket
  Notes; SR-E42-05); no artefact signature in v1. A restore compares the digest on the opened handle immediately
  before the decrypt (`e42-admin.md` §6 step 4).

### 3. Kinds, runs, verification and removal (BQ-02, BQ-04, BQ-10, BQ-11, BQ-13, BQ-14, BQ-16, BQ-17, BQ-21)

- **Kinds.** v1 runs `pg_dump` and `config_bundle`. A run of `pg_basebackup`, `questdb_snapshot` or `parquet_sync` is
  refused before any record with `409 conflict`, rule `kind_not_supported` (`22` `createBackup`). SR-090's other
  kinds (WAL archive, Parquet, the tailnet ACL export) and the relational RPO of at most 5 minutes (`21` §8.1,
  `20-architecture.md` §11.2) stay unmet; they are plan gaps recorded on #2701, and they gate E45-T10's drill and the
  release gate.
- **`config_bundle`** is backed up and verified, never restored by the engine (a manual runbook step). Its allow-list
  excludes `.env` files, DSNs, secret mounts and any KEK or age identity, and a test proves the exclusion (C-12.2).
- **Coverage.** The run reports `covers_from` and `covers_to`, and the `stage: finished` record binds them. For
  `pg_dump`, `covers_to` is the server's time read **before** the dump's snapshot is taken, never after, so a
  revocation at the boundary is treated as after the backup point. `retention_until` is set from `21` §8.1 when the
  run finishes.
- **Child processes.** No shell: one supervised child per job, stdout read into a bounded queue, written with
  `O_EXCL | O_NOFOLLOW` to a temporary name in the backup root, `fsync`, then renamed; files mode `0600`; no plaintext
  on disk at any point; a cancel or deadline ends the child and removes the temporary file. Database credentials reach
  a child through a password file or the child's environment only, never its argument list; its stderr is never
  logged (an exit code and a fixed error code are).
- **Scheduled runs.** The scheduler is one supervised task in the API, not in the sidecar, so every run passes the
  services that record it. It starts runs through `BackupRuns.start_scheduled(kind)` with the system actor label
  `system:<name>` (the `audit/break_halt.py` convention: no route can assume it), `triggered_by: schedule`, cadence
  and retention from `21` §8.1 with no new figures, and a skip when a run or restore is running. `pre_migration`,
  `pre_release` and `pre_restore` runs are out of v1.
- **Verification depth.** The automatic verification (`createBackup` with `verify: true`, BK-9d) and `verifyBackup`
  run at **`checksum`** depth and need no key: the file's SHA-256 against the catalogue and the digest bound in
  `backup.run`, then a well-formed age v1 header with exactly one X25519 stanza. An X25519 stanza names no recipient,
  so this check cannot show which key a file is for; the recipient is fixed when the file is written, by the pinned
  fingerprint (section 2). The API computes the digest over its read-only mount; the sidecar checks the header. It
  proves the bytes are the ones the run produced; it does not prove they restore. The **`restore_smoke`** depth
  decrypts with the Owner's identity into a scratch database: it is the per-release restore drill (SR-093, `21` §8.4),
  the restorability proof.
- **The chained verification** runs as the system actor after the run's `finished` record, through
  `BackupVerifications`. A chain refused (a restore running, the lock wait spent) is recorded as `backup.verified`
  with `stage: refused`, `outcome: failure` and the rule as `reason`; the run's outcome is unchanged.
- **Removal.** The service's last-usable check under the backups admission lock is the control (BQ-13 option (a)); a
  second read of the same data under the same lock adds nothing. Scenario 4 is proven end to end through
  `BackupDeletion` with the real remover, and a test asserts every `remove` goes through it. Pruning past
  `retention_until` is out of v1: the value is recorded, nothing is pruned, and the unbounded growth of the backup
  volume is a plan gap on #2701.

### 4. Security model

- **Key custody (C-2.7, C-3.2, C-12.2).** No backup key material enters the API process or M2. The exchange-key KEK
  never wraps or opens a backup. In the sidecar, identity handling is confined to one module, with the discipline M2
  applies to the KEK: memory only, never logged, printed, serialised, put in an exception or `repr`. If the engine is
  ever moved in-process, the keyring is built only in `admin/wiring.py` (the `protected-secrets` import-linter
  contract), never in `backups_wiring.py`, and this record is amended first.
- **Out-of-band delivery, one job (BQ-06).** For a restore or a restore drill the Owner supplies the identity to the
  sidecar for one named job, through a host-side intake that is not the API, not a network listener and not a shared
  volume. The identity never travels in an API body, an environment variable or `.env` file, an argument list, a log,
  an audit record, a catalogue row, a support bundle or the backup volume. The sidecar refuses an identity for a job
  it is not waiting for, a second identity for a job, and one that arrives after the job's deadline. Before it
  accepts the identity, the intake shows the Owner the job's backup id, the artefact's digest and its `covers_to`,
  read from the sidecar's own run record, not from the API's request; the Owner confirms them, and the identity is
  bound to that job and that digest.
- **Zeroisation.** The identity is held in a mutable buffer bound to its job and overwritten when the job ends,
  fails, is cancelled or passes its deadline; core dumps are disabled for the sidecar. Copies a library or runtime
  makes internally cannot be proven overwritten; that residual is stated in B1's security review. Tests generate
  age identities and DSNs per test under `tmp_path` with no network (C-13.5), and log-capture and `repr` tests prove
  that neither the identity nor a DSN is ever printed.
- **Restore authorisation and audit (C-2.9).** `restoreBackup` stays Owner-only (`backups:write`, a no-grace
  `backups` step-up spent per request), its preconditions checked under the admission lock, and `backup.restore`
  written ahead (E42-T05). The merged contract and guard win over the ticket's scenario 3 (BQ-12): an acknowledged
  position is admitted as the contract says. The executor is built to the port and **left unwired**: production
  wiring constructs it only when #3084 lands its contract and riders. At start it refuses unless the restore halt
  latch is engaged and the pre-restore chain head is written outside the target (`e42-admin.md` §6 steps 6 and 7).
  The sidecar refuses a `restore` unless it reads the latch engaged for that job, holds the identity for that job,
  and the artefact's digest on the opened handle equals the one the request carries from `backup.run`, the one the
  sidecar recorded when it finished the run, and the one the Owner confirmed at the intake.
- **What a restore does (BQ-08).** The whole database is restored, never a table on its own for audit or key tables
  (C-5.7; threat AD3). Key tables restore as opaque ciphertext: the engine streams bytes, parses no row and decrypts
  or re-wraps nothing; M2's KEK check and the withdrawal self-check (C-2.8) still gate trading after it. The chain is
  re-verified afterwards (SR-093) against the pre-restore head (D7 rider B). A key revoked after `covers_to` must not
  come back usable: D7 (#3084) refuses that restore.
- **The restore halt latch (BQ-19).** A file-backed latch held outside Postgres, on the `AuditBreakHalt` pattern, on
  the audit volume (never the backup or Postgres volume), which the sidecar mounts read-only. The composition root
  folds it into `oms_wiring.HaltingKillSwitch` (C-2.21): while engaged, every position-opening order is refused and
  protective writes still pass (C-2.6). It is engaged before anything touches the target and its state survives the
  database being replaced. It fails closed (an unreadable latch counts as engaged), stays engaged on any failed step,
  and refuses backup runs while engaged. It is released only by an Owner acknowledgement, recorded ahead of the
  release, after step 8 of `e42-admin.md` §6 completes. No flag, setting or role bypasses it (C-4.14). An artefact
  verification failure marks that backup unusable only; it does not halt trading. B2 registers the latch's engage and
  acknowledge records in the audit registry and in `24-internal-schemas.md`.
- **Downloads** stay `501` until SEC-FU-L1 is identified and met (BQ-20).

### 5. Ticket corrections (C-rows for the PRs)

1. Scope "DEK wrapped by the KEK" → a per-artefact key wrapped to the offline backup key pair (BQ-01).
2. "Automatic restore-into-scratch verification" → `checksum` depth; `restore_smoke` is the drill (BQ-02).
3. "Postgres via `pg_dump` + tar" → `pg_dump -Fc`, one file; v1 kinds `pg_dump` and `config_bundle` (BQ-04).
4. "Writes `backup.verify`" → the existing `backup.verified` record, written by the services (ports rule).
5. Scenario 3 "no position open" → the merged contract's acknowledged positions (BQ-12).
6. Scenario 4 "the engine re-checks" → the service's check under the lock, proven end to end (BQ-13).

## Consequences

Positive:

- SR-091 and SR-092 hold as written: neither the host keychain nor the API can open a backup.
- The internet-facing process gains no database-wide privilege and mounts the backup volume read-only. It can still
  ask the sidecar to run or remove a backup; the sidecar's floor (section 1) bounds what such requests can do, and a
  restore needs the Owner's confirmation at the intake.
- The monolith's module graph is unchanged; the engine's dependencies (Postgres client, age) stay out of the API
  image.
- A restore cannot silently re-enable trading against restored flags.

Negative and risks:

- A new trust boundary (the socket) and a second image to build, scan and pin (C-9.1 container and licence checks).
- Automatic verification proves integrity, not restorability; the drill carries that proof, so a drill missed is a
  gap the PRR gate must catch.
- `cv_restore` holds the owner's rights; it is `NOLOGIN` outside a restore job, and its credential's confinement to
  the sidecar is a control to review in B1.
- v1 leaves SR-090's other kinds, the 5-minute RPO and pruning unmet (plan gaps on #2701).
- Python cannot prove an identity zeroised everywhere (stated residual).
- Within the floor, the API can still request runs up to the cap and removals that the grace period delays but does
  not refuse; for any removal the newest-artefact rule allows, the grace period is the control (stated residual; B1's
  security review owns the figures, and B2 alerts on every quarantine).
- One recipient: losing the identity and its escrow copy loses every backup (section 2's custody rule and the
  per-release drill are the controls).

## Rollout

| PR  | Content                                                                                                                                                                           | Links                    |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| A   | this record; `21` and `22` text (contract first, C-6.1)                                                                                                                           | `Refs #3319`, `Partial:` |
| B1  | grants revision for `cv_backup` / `cv_restore`; the sidecar and its image; the socket clients; run, verify, remove                                                                | `Refs #3319`, `Partial:` |
| B2  | scheduler and `start_scheduled`; BK-9d and the refused chain; the unwired executor; the latch; `absent()` guards for the v1 kinds (after #5433); the flip of `BACKUPS_CATALOGUED` | `Closes #3319`           |

Each code PR stays at or under about 1,500 counted lines with `large-pr-approved` asked in advance, and all three
carry `security-review`. Code branch: `feat/e45-backup-engine` (C-4.4). Alert thresholds are measured and proposed in
B2, not changed silently.

## Why not the alternatives

- **KEK-wrapped DEK (BQ-01 a).** A stolen volume plus the host keychain would open every backup, contradicting SR-091
  and SR-092 and the existing `test_sr092_backup_key.py`.
- **Custom AES-GCM framing (BQ-03 a).** A bespoke format to review and maintain where the plan already names age.
- **In-process engine (BQ-07 a).** Puts an owner-level DSN in the API for its whole life and adds the Postgres client
  to its image; ruled out on least privilege.
- **Key in the request body (BQ-06 a).** It would cross the API, its request logging and its process memory.
- **A predicate in `remove` (BQ-13 b).** A port change to merged code for a second read of the same data under the
  same lock.
- **No latch.** A restored `maintenance.mode`, kill-switch or live-gate row would reopen order entry as of
  `covers_to`.

## Validation

- B1: import-linter contracts (sidecar ↔ `candleviewer` independence; `storage` free of `admin` and `secrets`); the
  role privilege matrix for `cv_backup` and `cv_restore`; SR-092 extended to the age format (the KEK and a wrong
  identity cannot open an artefact); log-capture and `repr` tests for identities and DSNs; the `config_bundle`
  exclusion test; scenarios 1, 2 and 4.
- B2: scheduler with a fake clock; BK-9d and the refused chain; latch tests (fail closed, survives a replace, Owner
  release only, protective writes pass); scenario 3; promtool tests for the `absent()` guards.
- The SR-093 restore drill (E45-T10) is the end-to-end proof of restorability.

## References

- `CONSTITUTION.md` §3, C-2.6, C-2.7, C-2.9, C-2.21, C-3.1, C-3.2, C-3.4, C-4.14, C-5.3, C-5.7, C-6.1, C-12.2.
- `04-security-program.md` SR-090 to SR-093; `21` §1.1, §3.10.3, §8; `22` `createBackup`, `verifyBackup`,
  `restoreBackup`; `20-architecture.md` §8.1, §11.2; ADR-0003, ADR-0009, ADR-0039.
- `docs/security/threat-models/e42-admin.md` §6.
