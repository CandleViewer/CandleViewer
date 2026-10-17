# ADR-0037 — Journal-first audit lane for auth and risk-reducing records (EX-07 exit)

- Status: **proposed**. The design PR of #3009, docs only. main-orchestrator accepts or amends it under the
  owner's delegation before S1a merges; the owner ratifies it before S3 merges, the first slice that changes what
  a user sees during an audit outage. EX-07 expires on 2026-11-15; Rollout has the dates.
- Date: 2026-10-17 (review round 2 folded the same day)
- Deciders: Owner (`@basiltt`) through main-orchestrator. Questions pending: hcl-worker-1 (Q2), the E27 owner
  (Q4); the Security engineer reviews through the `security-review` label. Author: hpe-worker-1.
- Numbering note: 0031 is reserved by E45-K01 (`ADR-0031-resilience-and-chaos`, not on `main`) and 0036 is the
  last on `main`, so this record takes the next free number.
- Related: #3009; #2914 (rulings D1 to D4; its slice D adds EX-07 and RR-15); #2267 item 4 (E27 KV-D04) and
  #892 (E27-Q03); #2119 (the break-glass journal); #2615 (the durable audit volume); #2251, #2872; ADR-0009
  Amendment 4, ADR-0010.
- Evidence: `main` at `31d6b7ddf`; module paths are under `services/api/candleviewer/`. EX-07, RR-15,
  `auth_audit_outcome_lost_total` and F1 (#2914's logout shape: one intent row naming the target sessions,
  then one outcome row per session revoked) are on #2914's branch, not yet on `main`
  (`origin/fix/e09-2914-session-audit-residue` at `dfeb852e`).

## Context and problem statement

`AuditWriter.emit()` appends a record to the local WAL with an fsync before it returns, and one flusher task
moves it into `audit_log` (`audit/writer.py:1-26`). It refuses with `AuditUnavailable` or `AuditWriterStopped`
when the WAL stays at its cap after compaction, when the WAL cannot be written, when the flusher has died (until
the next restart), and while the writer is not running (`audit/writer.py:358-387`, `audit/wal.py:166-180`). The
caller must then refuse the audited action. Sessions live in Postgres, so the auth records below arise while
Postgres is up and the sink still refuses: the WAL at its cap while it catches up after an outage, a dead
flusher until someone restarts cv-api (possibly hours), the writer stopping. Three kinds of record suffer:

1. **Auth outcome records**, written after the action took effect: one `auth.session_revoked` per session that
   `POST /auth/logout` revoked, `auth.refresh_reuse_detected` for the concurrent-refresh race, a disabled user's
   refused refresh (`auth.session_refreshed`, `denied`, reason `user_disabled`) and, once #2914 item 2 lands,
   the login-route outcome rows. A refusal loses the record. #2914's branch counts and alerts it
   (`auth_audit_outcome_lost_total{action}`), but `04-security-program.md` §8.3 rule 2 also asks for a durable
   retry. EX-07 (§16.2 on #2914's branch, not yet on `main`) waives that half until 2026-11-15; from then on the
   required `governance` check (`tools/ci/check_accepted_risk_expiry.py`) fails every PR.
2. **Risk-reducing write-ahead records**: `auth.logout` before a sign-out, `auth.session_revoked` before
   `DELETE /me/sessions/{id}`, and `auth.refresh_reuse_detected` before a reused token's family is revoked.
   While the sink refuses, these routes answer `503` and revoke nothing. That is residual RR-15 (§16.1 on #2914's
   branch, not yet on `main`), which the D2 ruling on #2914 keeps until the journal-first lane exists.
3. **E27 KV-D04** (#2267 item 4, measured by E27-Q03, #892): the same refusal stops every credential borrow,
   stop and cancel signatures included.

Nothing on `main` can hold these records durably while the sink refuses:

- The break-glass journal (`audit/journal.py`, #2119) admits only `auth.break_glass_*` (`:28-29`, decision R3).
  The offline CLI writes it while cv-api is stopped, and cv-api folds it in at boot only
  (`audit/service.py:72-83`).
- The Postgres `outbox` is down whenever Postgres is, and writing it would bypass `ingest()`.
- An in-memory queue is lost on restart, and a dead flusher recovers only through a restart.
- In compose, the `api` root filesystem is read-only with only `/tmp` writable
  (`infra/compose/docker-compose.yml:117-119`), and `CV_AUDIT_WAL_PATH` is relative (`settings.py:336`). Until
  #2615 gives the audit WAL a durable volume, nothing on disk survives a container restart there.

## Decision drivers

1. **No loss.** A record the lane accepted survives a sink outage and a restart, and it reaches `audit_log`
   exactly once and in order.
2. **Independence** from the main WAL's failure modes: its cap, a dead flusher, a stopped writer, a broken
   WAL file.
3. **Tamper evidence while a record waits**, under a key that the journal's volume does not hold.
4. **Bounded** (C-2.18): an unauthenticated flood cannot crowd out a sign-out, a revocation or, later, a stop.
5. **One entry into the chain**: `AuditWriter.ingest()` and the `AuditEmission` model, so every existing model
   rule applies (C-2.9). No bespoke serializer and no direct insert.
6. **No new boot dependency**: the lane boots, verifies and keeps its records while Postgres is unreachable, and
   it adds no KEK dependency to sign-out.
7. **Built once**: KV-D04 adds stops, cancels and revocation without a second mechanism.
8. **Sliceable** into PRs of at most 800 counted LOC that land before 2026-11-15.

## Considered options

- **(a)** Generalise the break-glass journal (`audit/journal.py`).
- **(b)** A new host-local journal module in `audit/`.
- **(c)** Reuse the audit WAL (`audit/wal.py`) as the durable lane.
- **(d)** The Postgres `outbox`.
- **(e)** An in-memory retry queue.
- **(f)** Reserved WAL headroom for risk-reducing records (#2914 item 3, option D).

## Decision (proposed)

Option (b), built from the proven patterns of (a) and (c) without sharing their files.

1. **Journal-first, with the sink as the fallback.** A record whose action has a row in the lane registry is
   appended to the lane journal first, and one drain task moves it into the chain. If the lane refuses (full,
   busy, too large, an I/O error, not running) or does not answer within `APPEND_WAIT_S`, the same
   `AuditEmission`, with the same `record_id`, goes to `AuditWriter.ingest()` directly. Only when that refuses
   too does the caller get `AuditUnavailable`, so its handling stays as it is today: a write-ahead record
   answers `503` and nothing changes; an outcome record is counted as lost and alerted. A record the lane
   accepted counts as written for §8.3 rules 1 and 2, whose order is the write order (each record durable
   before the next step), not chain position. Journal-first rather than sink-first: one path per action, and a
   stall of the main WAL's lock (a compaction, a batch read) cannot hold up a lane record; a disk stall on the
   shared volume delays both. The façade takes the caller's deadline, which the lane wait and the fallback
   share, and `APPEND_WAIT_S` stays below every caller's own audit bound.
2. **A façade with `emit()`'s shape.** `AuditService.lane.emit(action, *, ...)` takes the keyword arguments of
   `AuditWriter.emit()` and builds the record with `AuditWriter.build()`: the part of `emit()` that validates
   the action, redacts `before_state` and `after_state` and constructs the `AuditEmission`, moved out of
   `emit()` in S2a with no change in behaviour. A call site changes its receiver, not its error handling.
3. **A closed lane registry.** `LANE_ACTIONS` in `audit/actions.py` (the single source, C-16.5) maps each
   admitted action to its class and the outcomes it may carry. The class follows the action, never the caller.
   #3009 registers:

   | Action                        | Class      | Outcomes  | Why                                                                |
   | ----------------------------- | ---------- | --------- | ------------------------------------------------------------------ |
   | `auth.logout`                 | `reserved` | any       | the sign-out intent (RR-15)                                        |
   | `auth.session_revoked`        | `reserved` | any       | logout's outcome rows (EX-07); revoke-my-session's intent (RR-15)  |
   | `auth.refresh_reuse_detected` | `reserved` | any       | reuse containment: its intent (RR-15) and the race outcome (EX-07) |
   | `auth.session_refreshed`      | `shared`   | `denied`  | a disabled user's refused refresh (EX-07)                          |
   | the six login outcome actions | `shared`   | any       | #2914 item 2, ruling D1                                            |
   | `audit.lane_started`          | `reserved` | `success` | the lane's first record                                            |
   | `audit.lane_resumed`          | `reserved` | `success` | one per boot, with the head `seq` and `mac` (an anchor)            |

   The six login outcome actions are `auth.login`, `auth.login_failed`, `auth.account_locked`,
   `auth.mfa_failed`, `auth.recovery_codes_exhausted` and `auth.recovery_code_used`. The write-ahead records of
   a mint never use the lane: `auth.session_refreshed` with `success`, `auth.mfa_verified`, the carried-session
   record and `auth.session_created`. Refresh and sign-in stay fail closed while the sink refuses, so RR-15
   narrows to them. S1b adds `LANE_ACTIONS` and registers `audit.lane_started`; S2a registers
   `audit.lane_resumed` and `audit.lane_anomaly`, which only the drain writes; each updates §15.5's closed list.

4. **Bounds and overflow (C-2.18).** Bytes, frame size and lock waiters are capped, `shared` gets a share of the
   bytes and `reserved` waiters are served first; the values live only in `24-internal-schemas.md` §15.6
   (Limits). Past a bound an append is refused at once and the façade falls back (decision 1). An accepted
   frame is never dropped.
5. **Frames.** Append-only segment files of MAC'd, hash-linked frames, each with a contiguous `seq`, the lane
   id, a key id, the class and the record, plus a MAC'd confirmation marker. An append returns only after its
   fsync. The format, the scan and drain rules and the fsync points are `24-internal-schemas.md` §15.6.
6. **The key.** `CV_AUDIT_LANE_KEY_HEX`, 32 bytes in hex, is an application secret like `CV_AUTH_CSRF_KEY_HEX`
   (ADR-0009 Amendment 4, "Unchanged"). It is provisioned as a secret file (compose `secrets:`, mode `0400`,
   uid 10001), not as an `environment:` entry, so it stays out of `docker inspect` and the process environment.
   The composition root decodes it (`app.py:434`, the `build_csrf_codec` pattern at `:493-530`) and passes the
   bytes to `AuditService`; `audit` never imports `secrets` (C-3.2), and the key is not an exchange credential
   (C-2.7). It must differ from the TOTP, recovery-code and CSRF keys and from the pepper.
   `CV_AUDIT_LANE_PREVIOUS_KEY_HEX` only verifies, and it is retired only once no frame or marker under its key
   id remains (an empty lane and a marker rewritten under the new key); otherwise the drain holds (decision 8).
   The key is required whenever a real audit backend is wired: cv-api refuses to boot without it. It is not kept
   under the KEK: M2's keyring is unwrapped from Postgres (`auth_keys`) once the KEK is verified (ADR-0009
   Amendment 4), so a KEK failure, or a boot while Postgres is unreachable, would take the lane away, and with
   it sign-out during an audit outage.
7. **Drain and confirmation.** One supervised drain task scans the frames by the transition table in
   `24-internal-schemas.md` §15.6 and hands each authentic record to `AuditWriter.ingest()`, which returns a
   commit token: the record's place in the WAL's append order. `AuditWriter.committed_through()` reports the
   highest token committed to Postgres, and the marker moves past a record only once its token is committed. It
   never waits for the writer to be idle, which a busy WAL may never be. A segment is deleted only when it lies
   wholly behind the marker. At boot the drain re-ingests from the marker, not from what it handed over before
   the restart, so a WAL lost between `ingest()` and the commit is covered. A duplicate is a no-op, by
   `ON CONFLICT (record_id) DO NOTHING` (`storage/repositories/audit_sqlalchemy.py:43-52`).
8. **Nothing unverified enters the chain, and nothing is skipped silently.** Material that is not authentic (a
   MAC failure, a foreign lane, a repeated `seq`, a chain break, corrupt bytes, missing frames) is grouped into
   runs. Each run becomes one `audit.lane_anomaly` row, critical except for a torn tail (warning), handed over
   before the next authentic frame, which re-anchors the chain whatever its `prev`; the run's bytes are copied
   to `quarantine/`. An authentic record that `ingest()` refuses for good
   (`UnknownAuditAction`, or a `ValidationError`, which is not an `AuditError`) becomes a `record_invalid` row,
   is quarantined, and the drain moves on; a transient refusal is retried, and while the writer's flusher is
   dead the drain waits for a restart instead. An anomaly row's `record_id` is an HMAC under the lane key over
   the lane, the reason, the `seq` range and the digest of the quarantined bytes, set by the drain and not
   through the public `build()`, so two rows share an id only when they are byte-identical. An unknown key id
   or format version holds the drain and pages, saying the façade has fallen back. S2c's offline release
   command, run under `lane.lock` while cv-api is stopped, quarantines the held run, and the next boot records
   it as a `released` row.
9. **Placement and access.** `<dir of CV_AUDIT_WAL_PATH>/lane/`, beside `breakglass/`, on #2615's durable
   audit volume. The path is absolute and free of `..` and symlinks (the `anchored_journal_dir` rule,
   `audit/journal.py:50-60`); the directory is `0700` and its files `0600`, owned by the cv-api user (uid
   10001, `infra/images/Dockerfile.api:66`); every open uses `O_NOFOLLOW`. The running cv-api holds `lane.lock`
   exclusively, so a second process on the same volume refuses to boot. No route or WS topic opens the lane, and
   the only CLI that does is S2c's release command; the break-glass CLI keeps its own journal (R3).
10. **Module boundaries.** Two new files inside M19, `audit/lane_journal.py` (S1a, S1b) and `audit/lane.py`
    (S2a, S2b), with no new third-party dependency. There is no new module or import edge, so C-3.4 does not
    apply; this record exists for C-12.1 and the security decision.
11. **Failure while running.** A failed write truncates the segment back to its last good boundary and refuses
    the append, with `seq` not advanced. A failed fsync, or a dead drain task, stops the lane until a restart,
    and an fsync is never retried on the same file descriptor. The façade then falls back, and
    `AuditLaneRefusing` pages. Every file operation runs in a worker thread (§15.6).
12. **A C-4.13 flag that gates no invariant (C-4.14).** The lane spans eight PRs, so it ships behind
    `audit.lane_journal_first`: boolean, default off, Owner-only, in the flag catalogue with `restrictive` off
    (the value while the flag store cannot be read), owned by `@basiltt`, and removed by S4. S2b adds it there and
    to `21-database-schema.md` §10.7, and the composition root injects its resolver into `AuditService`, because
    `audit` may not import `admin`; a change is audited like any flag's (`flags.change`). Off, the façade hands
    every record straight to `AuditWriter.ingest()`, which is today's audited, fail-closed path: the flag picks
    between two audited destinations and never turns audit off. The journal and drain run whenever a real audit
    backend is wired, so records journaled while the flag was on still drain after it goes off. S3 wires the call
    sites; the Owner turns the flag on in staging, then in live; S4 removes the flag and EX-07 together, so no
    state exists in which the flag disables a control that no exception covers. ADR-0036's decision 10 chose a
    boot-fixed switch because its code is absent from the release image; this code ships.

## How E27 KV-D04 joins the lane

KV-D04 (#2267 item 4) needs stops, cancels and revocation to stay audited while the WAL refuses or stalls. It
adds no mechanism:

- E27 adds `reserved` rows to `LANE_ACTIONS` for its risk-reducing records (stop placement, cancel, SL amend,
  flatten, and the kill-switch and revocation records), and the composition root wires M2's injected audit
  port for those borrows to `AuditService.lane.emit`: the same files, lock, drain, key, metrics and alerts.
- The class follows the action. Where one action covers risk-reducing and other purposes
  (`security.credential_borrowed`), E27 registers the risk-reducing purposes under their own action ids in
  `audit/actions.py`, so the registry decides and a call site cannot (Q4).
- Latency and deadlines: a lane append waits for the lane lock and one fsync, never for the main WAL lock, and
  `reserved` waiters go first. M2's audit await has its own bound (KV-D04 in `E27-accounts.md`), so the lane's
  wait stays below it and the fallback gets what is left. #892 measures a borrow's latency through the lane
  against a direct `emit()`, under a WAL stall and under a login flood; E27 then updates KV-D04 and drill AC-27
  ("the borrow is refused and alerts") for the purposes it moves.

## Consequences

- Good: EX-07 exits. Sign-out, revoke-my-session and reuse containment work while the sink refuses, and RR-15
  narrows to refresh and sign-in. §8.3 rule 2 gets one durable-retry mechanism, which its pointer names. Lane
  frames are MAC'd and hash-linked, stronger than the WAL's CRC; the exclusive `lane.lock` also keeps a second
  cv-api off the shared WAL; and the journal runs in production even while the flag is off, carrying its own
  `audit.lane_started` and `audit.lane_resumed` records.
- Bad: a lane record costs two fsyncs (the lane, then the WAL through the drain) and reaches `audit_log` a
  moment after an `emit()` record would; tests that read rows after a lane write await
  `AuditService.lane.flush()`. Across the lane and the direct path, chain position is arrival order, and
  `event_ts` (set once by `build()`, kept by `ingest()`) is the order of record (U21).
- Bad: one more secret to provision and rotate, and a flag to remove; from S2b a real-backend stack without the
  key refuses to boot.
- Risk: the lane and the WAL share #2615's volume, so a full or read-only volume refuses both and callers behave
  as today. A second docker volume on the same WSL disk would not change that (Q5).
- Risk: once ingested, a record waits in the CRC-only WAL like every `emit()` record; the lane's MAC does not
  reach that far (Q6).
- Risk: retiring an action, or changing `AuditEmission` incompatibly, while the lane holds records turns them
  into `record_invalid` rows; S4's release-checklist row requires an empty lane for such a deploy.
- Residual: someone with cv-api's uid or root can read the key and forge, destroy or roll back frames (RR-01).
  Deleting the newest frames or the whole lane, or restoring an older copy, leaves no trace on the volume. The
  evidence is off it: one `audit.lane.appended` log line per accepted frame (`seq`, class, action and a `mac`
  prefix), `cv_audit_lane_last_seq` with `AuditLaneSeqRegressed`, the chain's `audit.lane_resumed` rows, and
  `AuditLaneCreated`.

## Rollout, slices and the EX-07 exit

One branch per slice (`feat/e09-3009-<slug>`), at most 800 counted LOC each, labelled `security-review` (the
`audit/` and `infra/` paths), with `Refs #3009` and a `Partial:` line; only S4 carries the closing line. The
estimates take the break-glass journal slice (426 LOC: 131 source, 255 test) and the WAL with the writer (820
source, 1,378 test lines) as analogues; a slice that grows past 800 splits again before review.

<!-- prettier-ignore -->
| # | Slice and its tests | LOC | After | PR open by |
| --- | --- | --- | --- | --- |
| S0 | This record, the STRIDE entry, the frame schema, the §8.3 and §16.2 pointers (docs) | this PR | — | 2026-10-18 |
| S1a | The frame codec, the marker, the scan transition table and quarantine. Unit: a round trip; every row of the table; each tamper case detected with its reason (a changed byte in `rec`, `seq`, `prev`, `cls` or `lane`; a frame removed, reordered, duplicated or spliced from another lane; a segment deleted; the marker forged or rolled forward or back; an unknown `kid` or `v`); re-anchoring after each kind of run; one row per run; a torn tail against a `len` edit; anomaly ids equal only for byte-identical runs; a hypothesis property: random damage never ingests an inauthentic frame and never loses an authentic one | 650-750 | S0 accepted | 2026-10-21 |
| S1b | Appends: segments, rotation, the fsync points in worker threads, append failures, quotas, waiter caps with `reserved` first, compaction; `LANE_ACTIONS` and `audit.lane_started`. Unit: a fault at each fsync point; a caller cancelled during an fsync keeps the lock (#2250); quotas; waiter priority; a hypothesis property: random appends, crashes and confirmations keep `seq` contiguous | 650-750 | S1a | 2026-10-23 |
| S2a | `AuditWriter.build()`, the commit token and `committed_through()`, the drain's private anomaly builder; the drain at boot and while running, per-record confirmation, anomaly and `record_invalid` rows, the dead-flusher wait, drain death; `audit.lane_resumed`, `audit.lane_anomaly`. Unit: a writer that refuses N times, with a restart in between, gets each `record_id` once and in order; a poison frame is quarantined and passed; a busy writer still confirms per record. Postgres integration: a refusing sink, appends, a restart, the sink back; each record once, the chain verifies, confirmed segments gone | 700-800 | S1b | 2026-10-27 |
| S2b | The façade and its fallback under the caller's deadline; `AuditService` wiring (start: writer, break-glass fold-in, lane; stop: the lane first); the flag (decision 12); the key settings from a secret file, and the boot refusals (no key, an unanchored directory, `lane.lock` held); key provisioning (compose secret, `.env.example` placeholder, CI) and a line in ADR-0009's key inventory. Unit: the fallback paths, the boot refusals, flag off equals today's path. Chaos (C-13.6 scenarios 10 and 12): Postgres stopped until a small `max_wal_bytes` fills, SIGKILL during an append and during a drain; nothing lost or duplicated; a frame tampered between restarts gives one row, and a second restart no second row | 650-800 | S2a | 2026-10-29 |
| S2c | The offline release command (under `lane.lock`, cv-api stopped) and its runbook row. Unit and integration: an unknown-`kid` frame is held, released and recorded as one `released` row; the command refuses while cv-api runs | 300-450 | S2b | 2026-10-31 |
| S3 | The rows: `api/sessions.py` (the logout intent and outcomes, revoke-my-session, the reuse intent and race outcome, the disabled user's denial), and the login outcome rows if #2914's PR C has landed (otherwise PR C adopts the façade, Q2). Unit per row with #2872's `_RefusingWriter`: flag on, sink refusing, lane accepting, so logout and revoke answer `204`, a reused token's family is revoked, the outcome rows land after a restart and nothing is counted lost; both refusing, today's answers and counters; flag off, today's behaviour. Integration: a sign-out during an audit outage, a restart, the rows exactly once; `test_auth_e2e_pg.py` awaits `lane.flush()` | 450-650 | S2c; #2914 slice D merged; Q1 decided | 2026-11-03 |
| S4 | Metrics (`cv_audit_lane_depth`, `_bytes{class}`, `_oldest_age_seconds`, `_last_seq`, `_appended_total{class}`, `_drained_total`, `_refused_total{class,reason}`, `_drain_failures_total{reason}`, `_anomalies_total{reason}`, `_quarantine_bytes`, `_created_total`, and `cv_audit_writer_refused_total{domain}`, the action's first dotted segment: the write-ahead refusal signal asked for on #3009 at 2026-10-17 01:50Z). Alerts that page, never muted by quiet hours: `AuditSinkRefusing`, `AuditLaneBacklogAged`, `AuditLaneRefusing`, `AuditLaneAnomaly` (a torn tail alone is a ticket), `AuditLaneDrainHeld` (it says the façade has fallen back), `AuditLaneSeqRegressed`, `AuditLaneCreated`; a ticket: `AuditLaneQuarantineGrowing`. Promtool tests, `07-release-and-prr.md` entries and `docs/ops/runbooks/auth-rbac.md` rows, key rotation and `_PREVIOUS_` retirement among them. The drill: an outage with sign-outs and a restart, then a tampered frame. The exit: the flag and EX-07 removed, RR-15 narrowed, RR-01 extended to the lane's residuals, §8.3's sentences updated, the counter-coverage test checking the registry, and the release-checklist row of the Consequences | 700-800, or S4a and S4b | S3; #2615 merged | 2026-11-05 |

**Schedule risks.** S3 needs #2914's slice D, which has no PR yet; S4 needs #2615, which has no owner (Q10);
S2b's `AuditService` edits overlap the draft PRs #2443 and #2467, which also change `audit/service.py` (C-4.15:
whichever lands second rebases); and the E42-T02 fold train, rationed CI and the stack-depth cap limit how many
slices can be in review at once. If S4 cannot open by 2026-11-05, hpe-worker-1 says so on #3009 by 2026-10-25.
S4 merges by 2026-11-10; if it has not, hpe-worker-1 asks the owner that day, on #2701, for EX-07's
re-decision, since its row says to re-decide, never extend.

**`infra/` impact.** No new volume: `lane/` sits on #2615's audit volume (an absolute `CV_AUDIT_WAL_PATH`), and
cv-api creates it, directory `0700` and files `0600`, as uid 10001 on the read-only root filesystem. S2b
provisions the key as a compose secret (`/run/secrets`, `0400`, uid 10001; `.env.example` holds a placeholder
only, C-12.2), one key per environment (C-2.11), in the same PR that makes it mandatory. S4 adds the alert rules
under `infra/prometheus/alerts/` with promtool tests. Backups of the audit volume include `lane/`; a restored
lane drains again without duplicates, and an older copy shows as a lower head in the `audit.lane_resumed` rows.

## Why not the alternatives

- **(a) Generalise the break-glass journal.** Its file admits only `auth.break_glass_*` (decision R3), has a
  different writer (the offline CLI, with cv-api stopped and `instance.lock` held exclusively) and is folded in
  at boot only. Two writers in one file break R3, and changing its CRC-only frames reopens merged slices of a
  P0 Story (#2119). The lane keeps its patterns: the anchored directory, `O_NOFOLLOW`, entry through
  `ingest()`, and an unusable journal kept as evidence.
- **(c) Reuse the audit WAL**, weighed as a second `AuditWal` instance like the break-glass journal's, with a MAC
  envelope inside each record and a MAC'd marker beside its cursor. Rejected because compaction rewrites the
  uncommitted remainder into a new file and resets the cursor (`audit/wal.py:214-233`), so acknowledged bytes are
  rewritten and the chain's anchor must live outside the file; the cursor is a plain byte offset, so rolling it
  forward skips frames silently; `AuditWalCorrupt` stops the reader instead of quarantining and moving on; a
  complete last frame that fails its check counts as a torn tail and is truncated (`audit/wal.py:102-111`), so
  an altered newest frame would vanish without a trace; and it has no record bound or class quota. The lane
  keeps its framing idea, its fsync before return and its truncate-before-append rule.
- **(d) The Postgres `outbox`.** It is down whenever Postgres is, and a direct insert bypasses `ingest()`.
- **(e) An in-memory queue.** It is lost on restart, so it is not the durable retry rule 2 asks for, and
  #3009's done-means requires surviving a restart.
- **(f) Reserved WAL headroom.** It covers only the cap: a dead flusher or a stopped writer still refuses, so it
  needs a bypass inside `audit/writer.py`, and it does nothing for a stalled WAL.
- **Revoke first, record if possible** (#2914 item 3, option B): rejected by the D2 ruling, because an
  unrecorded revocation breaks C-2.9 and U19.
- **Sink first, journal on refusal:** two paths per action, a mode switch while the journal drains, and no help
  when the WAL's lock stalls rather than refuses.

## Open questions

- **Q1, owner and Security, before S3.** Confirm the narrowed RR-15: sign-out, revoke-my-session and reuse
  containment proceed journal-first, while refresh and sign-in stay fail closed. Should the Owner's revocation
  of another user's session (`revokeUserSession`) and a user's disablement (SR-029) join now, since ending a
  compromised Manager's session matters more than self sign-out?
- **Q2, hcl-worker-1.** If #2914's PR C lands after S3, does it call the façade itself? Does F1 stay as it is
  on the branch? Is `cv_audit_writer_refused_total{domain}` the write-ahead refusal signal you asked for, or do
  the `503` sites also need a per-action counter?
- **Q3, main-orchestrator.** Are §15.6's limits enough for a dead flusher left for hours, or should S2b's chaos
  run size them first? The one `reserved` source reachable without a session is a rotated-token replay,
  bounded by the refresh route's per-address and per-session throttles (`api/sessions.py:266-272`).
- **Q4, E27 (KV-D04).** Separate action ids for the risk-reducing borrow purposes, or a purpose rule in the
  registry?
- **Q5, owner.** Accept the shared volume (the lane does not cover a full or read-only audit volume), or add a
  reserve, such as a ballast file, in a later ticket?
- **Q6, Security.** Give the main WAL the lane's frame MAC in a follow-up ticket?
- **Q7, owner.** Should other outcome records lost without a retry today (for example the ones
  `cv_credential_outcome_audit_failures_total` counts) join the registry, or get a §16.2 exception?
- **Q8, owner.** `quarantine/` keeps PII (`actor_ip`, user and session ids) for good. Do account erasure and
  the retention job reach it, or does it follow `audit_log`'s indefinite retention (C-12.8)?
- **Q9, Security.** Should a replay against an already-revoked family get its own `shared` action id, keeping
  only the first containment intent `reserved`?
- **Q10, main-orchestrator.** Who owns #2615, which S4 needs? hpe-worker-1 can carry it in S4 if nobody has
  claimed it by 2026-10-28.

## Validation

- S1a to S4 carry the named tests above; the integration and chaos lanes run in CI.
- #3009's done-means maps to the slices: the EX-07 rows are written journal-first (S3); a refusing sink and a
  restart lose none of them (S2a, S2b, S3); EX-07 is removed and RR-15 updated (S4); unit, Postgres-integration
  and chaos tests pass, and the journal's tamper evidence is tested (S1a, S2a, S2b).
- The decision is taken when main-orchestrator records the interim acceptance on #3009 and the owner ratifies
  it (status line).

## References

- `docs/plan/04-security-program.md` §8.1, §8.3, §16.1 (RR-15) and §16.2 (EX-07, both on #2914's branch)
- `docs/plan/24-internal-schemas.md` §15.4 and §15.6; `docs/plan/21-database-schema.md` §10.7
- `docs/security/threat-models/e09-auth-rbac.md` §3.6.1 and §3.6.2; `docs/security/threat-models/E27-accounts.md`
  KV-D04 and AC-27
- `docs/plan/27-adrs/ADR-0009-secrets-and-key-management.md` Amendment 4;
  `docs/plan/27-adrs/ADR-0010-auth-and-rbac.md`; `docs/plan/27-adrs/ADR-0036-dev-only-account-fixture-transport.md`
  decision 10
- `audit/writer.py`, `audit/wal.py`, `audit/journal.py`, `audit/service.py`, `audit/models.py`,
  `admin/breakglass.py`, `admin/flags/catalogue.py`, `api/sessions.py`
- #3009, #2914, #2267, #892, #2119, #2615, #2443, #2467, #2251, #2872
