# ADR-0037 — Journal-first audit lane for auth and risk-reducing records (EX-07 exit)

- Status: **accepted**: ratified 2026-10-20 by main-orchestrator under the owner's delegation, #2701
  issuecomment-6291902866; the owner may revoke there. It was accepted on an interim basis by main-orchestrator
  on 2026-10-17, on #3009. Amendment 1 (2026-10-21) records the lane's exit: the flag removed, EX-07 and EX-08
  retired, and the carries left open. Amendment 2 (2026-10-22) records the login routes' adoption of the façade
  (#2914's PR C): EX-10 retired, Q2 answered.
- Date: 2026-10-17 (review round 4 folded the same day)
- Deciders: Owner (`@basiltt`) through main-orchestrator, under the owner's delegation (the ratification above).
  Questions pending: main-orchestrator (Q3), the E27 owner (Q4) and Security (Q6); the
  Security engineer reviews through the `security-review` label. Author: hpe-worker-1.
- Numbering note: 0031 is reserved by E45-K01 (`ADR-0031-resilience-and-chaos`, not on `main`) and 0036 is the
  last on `main`, so this record takes the next free number.
- Related: #3009; #2914 (rulings D1 to D4; its slice D adds EX-07 and RR-16, the sink-refusal residual;
  #2661 holds RR-15 on `main`); #2267 item 4 (E27 KV-D04) and #892 (E27-Q03); #2119 (the break-glass
  journal); #2615 (the durable audit volume); #2251, #2872; ADR-0009 Amendment 4, ADR-0010.
- Evidence: `main` at `8485277db`; module paths are under `services/api/candleviewer/`. EX-07, RR-16,
  `auth_audit_outcome_lost_total` and F1 (#2914's logout shape: one intent row naming the target sessions,
  then one outcome row per session revoked) are on #2914's branch, not yet on `main`
  (`origin/fix/e09-2914-session-audit-residue` at `3e69eb814`; to be cited by its PR number once one opens).

## Context and problem statement

`AuditWriter.emit()` appends a record to the local WAL with an fsync before it returns, and one flusher task
moves it into `audit_log` (`audit/writer.py:1-27`). It refuses with `AuditUnavailable` or `AuditWriterStopped`
when the WAL stays at its cap after compaction, when the WAL cannot be written, when the flusher has died (until
the next restart), and while the writer is not running (`audit/writer.py:359-388`, `audit/wal.py:166-180`). The
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
   While the sink refuses, these routes answer `503` and revoke nothing. That is residual RR-16 (§16.1 on
   #2914's branch, not yet on `main`, where #2661 holds RR-15), which the D2 ruling on #2914 keeps until the
   journal-first lane exists.
3. **E27 KV-D04** (#2267 item 4, measured by E27-Q03, #892): the same refusal stops every credential borrow,
   stop and cancel signatures included.

Nothing on `main` can hold these records durably while the sink refuses:

- The break-glass journal (`audit/journal.py`, #2119) admits only `auth.break_glass_*` (`:28-29`, decision R3).
  The offline CLI writes it while cv-api is stopped, and cv-api folds it in at boot only
  (`audit/service.py:72-83`).
- The Postgres `outbox` is down whenever Postgres is, and writing it would bypass `ingest()`.
- An in-memory queue is lost on restart, and a dead flusher recovers only through a restart.
- In compose, the `api` root filesystem is read-only with only `/tmp` writable
  (`infra/compose/docker-compose.yml:125-127`), and `CV_AUDIT_WAL_PATH` is relative (`settings.py:347`). Until
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

## Decision

Option (b), built from the proven patterns of (a) and (c) without sharing their files.

1. **Journal-first, with the sink as the fallback.** A record whose action has a row in the lane registry is
   appended to the lane journal first, and one drain task moves it into the chain. If the lane refuses (any
   reason in §15.6's closed set, `held` included) or does not answer within `APPEND_WAIT_S`, the same
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
   `emit()` in S2a1 with no change in behaviour. A call site changes its receiver, not its error handling.
3. **A closed lane registry.** `LANE_ACTIONS` in `audit/actions.py` (the single source, C-16.5) maps each
   admitted action to its class and the outcomes it may carry. The class follows the action, never the caller.
   #3009 registers:

   | Action                        | Class      | Outcomes  | Why                                                                |
   | ----------------------------- | ---------- | --------- | ------------------------------------------------------------------ |
   | `auth.logout`                 | `reserved` | any       | the sign-out intent (RR-16)                                        |
   | `auth.session_revoked`        | `reserved` | any       | logout's outcome rows (EX-07); revoke-my-session's intent (RR-16)  |
   | `auth.refresh_reuse_detected` | `reserved` | any       | reuse containment: its intent (RR-16) and the race outcome (EX-07) |
   | `auth.refresh_reuse_replayed` | `shared`   | `denied`  | a replay against a family already contained (decision 13)          |
   | `auth.session_refreshed`      | `shared`   | `denied`  | a disabled user's refused refresh (EX-07)                          |
   | the six login outcome actions | `shared`   | any       | #2914 item 2, ruling D1                                            |
   | `audit.lane_started`          | `reserved` | `success` | the lane's first record                                            |
   | `audit.lane_resumed`          | `reserved` | `success` | one per boot, with the head `seq` and `mac` (an anchor)            |

   The six login outcome actions are `auth.login`, `auth.login_failed`, `auth.account_locked`,
   `auth.mfa_failed`, `auth.recovery_codes_exhausted` and `auth.recovery_code_used`. The write-ahead records of
   a mint never use the lane: `auth.session_refreshed` with `success`, `auth.mfa_verified`, the carried-session
   record and `auth.session_created`. Refresh and sign-in stay fail closed while the sink refuses, so RR-16
   narrows to them. S1b adds `LANE_ACTIONS`; S2a2, the slice that first emits them, registers
   `audit.lane_started`, `audit.lane_resumed` and `audit.lane_anomaly` and adds them to §15.5's closed list.
   S2a1 adds `auth.disabled_user_session_revoked` (`reserved`, `success`): the backstop revocation's outcome
   record, whose EX-08 (#3120) exits with this lane.

4. **Bounds and overflow (C-2.18).** Bytes, frame size and lock waiters are capped, `shared` gets a share of the
   bytes and `reserved` waiters are served first; the values live only in `24-internal-schemas.md` §15.6
   (Limits). Past a bound an append is refused at once and the façade falls back (decision 1). An accepted
   frame is never dropped.
5. **Frames.** Append-only segment files of MAC'd, hash-linked frames, each with a contiguous `seq`, the lane
   id, a key id, the class and the record, plus a MAC'd confirmation marker. An append returns only after its
   fsync. The format, the scan and drain rules and the fsync points are `24-internal-schemas.md` §15.6.
6. **The key.** A 32-byte application secret like `CV_AUTH_CSRF_KEY_HEX` (ADR-0009 Amendment 4, "Unchanged"), read
   once at boot from the file that `CV_AUDIT_LANE_KEY_FILE` names, by default a compose secret under
   `/run/secrets` (mode `0400`, uid 10001), so it stays out of `docker inspect` and the process environment. The
   path is checked like `CV_TEST_CLOCK_FILE`, and the content rules are §15.6's; there is no environment form, and
   S2b refuses boot when `CV_AUDIT_LANE_KEY_HEX` or `CV_AUDIT_LANE_PREVIOUS_KEY_HEX` is set. The composition root reads it (the pattern of
   `kek_handle`, `settings.py:366`, and of `build_csrf_codec`, `app.py:494-531`) and passes the bytes to
   `AuditService`; `audit` never imports `secrets` (C-3.2), and the key is not an exchange credential (C-2.7). S2b
   refuses boot when it equals the TOTP, recovery-code or CSRF key or the pepper, and when a key file, current
   or previous, lies under the directory of `CV_AUDIT_WAL_PATH`: a key must never sit on the volume whose frames
   it authenticates.
   `CV_AUDIT_LANE_PREVIOUS_KEY_FILE` only verifies, and it is retired only once no frame or marker under its key
   id remains (an empty lane and a marker rewritten under the new key); otherwise the drain holds (decision 8).
   The key is required whenever a real audit backend is wired: cv-api refuses to boot without it. It is not kept
   under the KEK: M2's keyring is unwrapped from Postgres (`auth_keys`) once the KEK is verified (ADR-0009
   Amendment 4), so a KEK failure, or a boot while Postgres is unreachable, would take the lane away, and with it
   sign-out during an audit outage.
7. **Drain and confirmation.** One supervised drain task scans the frames by the transition table in
   `24-internal-schemas.md` §15.6 and hands each authentic record to `AuditWriter.ingest()`, which returns a
   commit token: the record's place in the WAL's append order. `AuditWriter.committed_through()` reports the
   highest token committed to Postgres, and the marker moves past a record only once its token is committed. It
   never waits for the writer to be idle, which a busy WAL may never be. A segment is deleted only when it lies
   wholly behind the marker. At boot the drain re-ingests from the marker, not from what it handed over before
   the restart, so a WAL lost between `ingest()` and the commit is covered. A duplicate is a no-op, by
   `ON CONFLICT (record_id) DO NOTHING` (`storage/repositories/audit_sqlalchemy.py:43-52`).
8. **Nothing unverified enters the chain, and nothing is skipped silently.** Material that is not authentic or
   not in sequence (a MAC failure, a foreign lane, a repeated `seq`, a chain break, corrupt bytes, missing
   frames) is grouped into runs by the scan transition table in §15.6, which is normative. Each run becomes one
   `audit.lane_anomaly` row, critical except for a torn tail (warning), handed over before the next frame in
   sequence, which re-anchors the chain whatever its `prev`; the run's bytes are copied to `quarantine/`. An
   authentic frame out of sequence is quarantined too, because a chain break or a repeated `seq` is what a
   rollback or splice of authentic frames looks like. A record that `ingest()` refuses for good
   (`UnknownAuditAction`, or a `ValidationError`, which is not an `AuditError`) gets its own `record_invalid`
   row and is quarantined, and the scan moves past it as past any frame in sequence; a transient refusal is
   retried, and while the writer's flusher is dead the drain waits for a restart instead. An anomaly row's
   `record_id` is an HMAC under the lane key over the lane, the reason, the `seq` range and the digest of the
   quarantined bytes, set by the drain and not through the public `build()`, so two rows share an id only when
   they are byte-identical. An unknown key id or format version holds: the lane stops and refuses every append
   with `held`, so the façade falls back, and `AuditLaneDrainHeld` pages. The hold ends with a restart after the
   previous key is restored, or after S2c's offline release command, run under `lane.lock` while cv-api is
   stopped, has quarantined the held frames, which the next boot records as one `released` row.
9. **Placement and access.** `<dir of CV_AUDIT_WAL_PATH>/lane/`, beside `breakglass/`, on #2615's durable
   audit volume. The path is absolute and free of `..` and symlinks (the `anchored_journal_dir` rule,
   `audit/journal.py:50-60`); the directory is `0700` and its files `0600`, owned by the cv-api user (uid
   10001, `infra/images/Dockerfile.api:76`); every open uses `O_NOFOLLOW`. The running cv-api holds `lane.lock`
   exclusively, so a second process on the same volume refuses to boot. It takes the lock through directory
   descriptors (`audit/lane_lock.py`, SEC-REM-03, #4005): the audit directory is opened
   `O_DIRECTORY | O_NOFOLLOW`, then `lane/` and `lane.lock` relative to it, so a symlink swapped in after a check
   is never followed. Only those opens are anchored to descriptors; the lane's other file operations still name
   paths under `lane/`, the residual RR-01 accepts (`24-internal-schemas.md` §15.6 Directory). No route or WS
   topic opens the lane, and the only CLI that does is S2c's release command, in `admin/`, which takes
   `lane.lock` the same way; the break-glass CLI keeps its own journal (R3).
10. **Module boundaries.** Four new files inside M19, `audit/lane_journal.py` (S1a–S1c), `audit/lane.py`
    (S2a2, S2b), `audit/metrics.py` (S4a-1, #3758) and `audit/lane_lock.py` (S4b-2b, #4005), and S2c's release
    command, `admin/lane_release.py`, in M21, beside `admin/breakglass.py`, over the existing edge from `admin` to
    `audit`; the key loader, `audit_lane_wiring.py` (S2b-1), is composition-root wiring, not a module (decision 6).
    No new third-party dependency. There is no new module or import edge, so C-3.4 does not apply; this record
    exists for C-12.1 and the security decision.
11. **Failure while running.** A failed write truncates the segment back to its last good boundary and refuses
    the append, with `seq` not advanced. A failed fsync or a dead drain task stops the lane until a restart and
    refuses appends with `stopped`; a hold (decision 8) stops it the same way and refuses them with `held`. An
    fsync is never retried on the same file descriptor. The façade then falls back, and `AuditLaneRefusing`
    pages. Every file operation runs in a worker thread (§15.6).
12. **A C-4.13 flag that gated no invariant (C-4.14), removed in S4b-1c.** The lane spanned many PRs, so from
    S2b-2a until S4b-1c it shipped behind `audit.lane_journal_first`: boolean, default off, Owner-only,
    `restrictive` off (what the flag service answered while the flag store could not be read; the façade's own
    read is below), owned by `@basiltt`, its description ending `removal #3009`, because #3009 was the removal
    ticket. S2b added it to the catalogue (`admin/flags/catalogue.py`; C-4.13 still names
    `services/api/config/flags.py`, which does not exist) and to `21-database-schema.md` §10.7. Its `gates`
    category was `FEATURE_ROLLOUT`, like `engine.webgl_v2`. `FlagSpec` refuses `AUDIT` at import
    (`admin/flags/registry.py:57-66`, `:125-131`), and that category was not this flag's: both of its positions
    wrote the same record durably, through the writer's own rules, before the action proceeded. Off, the façade
    handed every record straight to `AuditWriter.ingest()`, the audited, fail-closed path of before; on, the lane
    took it first. The composition root injected the resolver into `AuditService`, because `audit` may not import
    `admin`; it read the flag's stored value with no principal (`user_id=None`, no roles), so no user or role
    override applied, although `FlagSpec.overridable` was true for this flag and `admin/flags/resolver.py:53-64`
    honours overrides. The façade's read was cached and refreshed in the background (READY-21, S2b-2a row): off,
    the catalogue default, before the first successful read, and afterwards the last value read, which it kept
    while the store could not be read; the admin API then showed the fail-closed off. S4a exported that value as a
    gauge, `cv_audit_lane_journal_first` (SR-S2B2A-02), which S4b-1b removed: the evidence that journal-first is
    in force is `cv_audit_lane_appended_total{class}` moving past a boot's own frames (`audit.lane_resumed`, plus
    `audit.lane_started` on a new lane) and `audit.lane.appended` lines naming record actions. A change was
    audited like any flag's (`flags.change`). The journal and drain ran whenever a real audit backend was wired,
    so records journaled while the flag was on still drained after it went off. Order: S3 wired the call sites,
    for the Owner to turn the flag on in staging; live got the lane only when S4b-1c removed the flag, after S4a's
    alerts and runbook rows had landed (C-11.2 item 9), so the flag was never turned on in live by hand. No state
    existed in which the flag disabled a control that no exception covered. S4b-1c removed the catalogue spec,
    `LaneFlag` in `flags_wiring.py` (first added at `c429880a`; its last form is at `4a971175^`) and the façade's
    guard, so every record that a call site hands to the façade and `LANE_ACTIONS` admits now goes to the lane
    first; the removed flag's stored row stays inert, and a `PUT` to its key answers an audited `404`
    (`21-database-schema.md` §3.9, "Stored value and writer"). ADR-0036's decision 10 chose a boot-fixed switch
    because its code is absent from the release image; this code ships.
13. **A replay of a contained family is `shared` (Q9).** Ruled (a) by main-orchestrator on 2026-10-21 (#3009
    S4b-1a). Only a family's first containment intent is `reserved` (`auth.refresh_reuse_detected`, `critical`). A
    rotated refresh token presented again once this process has contained its family, that token or another rotated
    member, writes `auth.refresh_reuse_replayed` (`shared`, `denied`, `warning`) ahead through the lane instead, so
    a flood of replays fills the `shared` share and falls back to the writer, and never spends a `reserved` byte or
    waiter: Q3's one `reserved` source reachable without a session, besides the recovery's unplanned revocation
    (Amendment 2), becomes one frame per family. No store query says
    a family was contained, so the refresh route keeps an in-process memo (`ContainedFamilies`, `api/sessions.py`),
    filled, once the service has revoked a family (a refresh that lost a claim race revoked none), from
    `RefreshReuseDetected.revoked_session_ids` and the presented session, and bounded by a capacity and a TTL. A family
    it no longer holds, after an eviction, the TTL or a restart, takes the `reserved` intent once more:
    the safe direction, as often as the refresh throttles allow. Each replay the session service refuses is counted
    on the existing `auth_refresh_reuse_total` (route refusals cannot reach `cv_audit_lane_anomalies_total`, which
    counts the drain's anomalies), and the first replay refusal per family per window is logged
    (`auth.refresh_reuse.replay_refused`, the session id only), so a flood is visible. The `401`, and the `503` when
    the lane and the sink both refuse, are unchanged. The action id, the `warning` severity and the memo do not
    depend on the lane taking the row: the route never reads a flag, and a lane that refuses it or is not wired
    hands it to the writer, as decision 1 says. A replay flood shares the `shared` class (64 waiters; its bound is
    decision 4's) with the login routes' outcome rows, which #2914's PR C put on the façade (Amendment 2), and a
    disabled user's refused refresh.

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

- Good: EX-07 exits. Sign-out, revoke-my-session and reuse containment work while the sink refuses, and RR-16 narrows
  to refresh and sign-in, and the idle lock's extend and unlock (#4052). §8.3 rule 2 gets one durable-retry mechanism,
  which its pointer names. Lane frames are MAC'd and hash-linked, stronger than the WAL's CRC; the exclusive
  `lane.lock` also keeps a second cv-api off the shared WAL; and the journal runs wherever a real audit backend is
  wired, carrying its own `audit.lane_started` and `audit.lane_resumed` records.
- Bad: a lane record costs two fsyncs (the lane, then the WAL through the drain) and reaches `audit_log` a
  moment after an `emit()` record would; tests that read rows after a lane write await
  `AuditService.lane.flush()`. Across the lane and the direct path, chain position is arrival order, and
  `event_ts` (set once by `build()`, kept by `ingest()`) gives the write order. That is in tension with U21,
  which makes the chain, not a clock, the ordering authority; it is accepted because within the lane `seq`
  order is the write order and every break in it leaves an anomaly row.
- Bad: one more secret to provision and rotate, and a flag to remove, which S4b-1c did; from S2b a real-backend
  stack without the key refuses to boot.
- Risk: the lane and the WAL share #2615's volume, so a full or read-only volume refuses both and callers behave
  as today. A second docker volume on the same WSL disk would not change that (Q5).
- Risk: once ingested, a record waits in the CRC-only WAL like every `emit()` record; the lane's MAC does not
  reach that far (Q6).
- Risk: retiring an action, or changing `AuditEmission` incompatibly, while the lane holds records turns them
  into `record_invalid` rows; S4b's release-checklist row requires an empty lane for such a deploy.
- Residual: someone with cv-api's uid or root can read the key and forge, destroy or roll back frames (RR-01).
  Deleting the newest frames or the whole lane, or restoring an older copy, leaves no trace on the volume. The
  evidence is off it: one `audit.lane.appended` log line per accepted frame (`seq`, class, action and a `mac`
  prefix), `cv_audit_lane_last_seq` with `AuditLaneSeqRegressed`, the chain's `audit.lane_resumed` rows, and
  `AuditLaneCreated`.

## Rollout, slices and the EX-07 exit

One branch per slice (`feat/e09-3009-<slug>`), at most 800 counted LOC each, labelled `security-review` (the
`audit/` and `infra/` paths), with `Refs #3009` and a `Partial:` line; only S4b's last PR, S4b-2a, carries the
closing line. The analogues are the break-glass journal slice (131 source and 255 test lines) and the WAL with the writer (820 and
1,378): tests run about 1.7 to 1.9 times the source, so a slice stays under 800 only with about 285 source lines
or fewer. The estimates below are source plus tests at that ratio. The dates assume the seams named here (S2a1
and S2a2, S4a and S4b) but no further split. A slice whose counted LOC would pass 800 splits at its contingency
seam, named now so that a split is never improvised: S1a, the codec and parse order before the scan and
quarantine; S1b, the quotas and waiters (S1c); S2a2, the scan, hand-over and rows before the dead-flusher wait,
drain death and hold; S2b, the key files and boot refusals before the façade, the flag and the chaos runs; S4a,
the metrics before the alerts. S2b carries the most, so it is the likeliest to split, and S2a2 and S2b split there (S2a2a, S2a2b, S2a2c; S2b-1, S2b-2a, S2b-2b1, S2b-2b2, S2b-2b3); a
split moves every date after it, and Schedule risks says when that is reported.

<!-- prettier-ignore -->
| # | Slice and its tests | LOC | After | PR open by |
| --- | --- | --- | --- | --- |
| S0 | This record, the STRIDE entry, the frame schema, the §8.3 and §16.2 pointers (docs) | this PR | — | 2026-10-18 |
| S1a | The frame codec and parse order, the marker, the scan transition table and quarantine. Unit: a round trip; every row of the table; each tamper case detected with its reason (a changed byte in `rec`, `seq`, `prev`, `cls` or `lane`; a frame removed, reordered, duplicated or spliced from another lane; a segment deleted; the marker forged, rolled forward, rolled back or ahead of the data; an unknown `kid` or `v`); re-anchoring after each kind of run; a run, then a `record_invalid` frame, then a frame with a wrong `prev`, which is quarantined (`anchored` is true after the `record_invalid` frame); one row per run; a torn tail against a `len` edit; anomaly ids equal only for byte-identical runs; a hypothesis property: random damage never hands over a frame that is not authentic and in sequence, and never loses one that is | 260 + 480 | S0 accepted | 2026-10-21 |
| S1b | Appends: segments, rotation, lane creation (frame 1's record comes from the caller), fsync point 1 in worker threads, append failures, rulings R1 and R2 on #3009; `LANE_ACTIONS`. Unit: a fault at each fsync point of the write side; a caller cancelled during an fsync keeps the lock (#2250); a held boot opens no segment | 798 counted | S1a | 2026-10-23 |
| S1c | Split from S1b at its seam, then by the design owner's second cut on #3009: quotas, waiter caps with `reserved` first, and the drain's file operations (confirmation, compaction and quarantine, fsync points 2 to 4). Unit: quotas, also across a restart and a confirmation; waiter priority; a fault at each of fsync points 2 to 4; a hypothesis property: random appends, crashes and confirmations keep `seq` contiguous | 761 counted | S1b | 2026-10-23 |
| S2a1 | The writer API: `AuditWriter.build()`, the commit token that `ingest()` returns, `committed_through()`; the existing writer suites stay untouched and green. Unit: tokens are monotonic and committed in WAL order across a compaction and a flusher restart; `build()` then `ingest()` equals `emit()` | 105 + 220 | S1b | 2026-10-24 |
| S2a2a | Split from S2a2 at its seam: the boot and running scans, hand-over, per-record confirmation, anomaly and `record_invalid` rows through the package-private anomaly builder in `audit/writer.py` (its only caller); lane creation with `audit.lane_started`, and `audit.lane_resumed`; it registers the three `audit.lane_*` actions. Unit: a writer that refuses N times, with a restart in between, gets each `record_id` once and in order; a poison frame gets one row and is passed; an anomaly row carries the run's `record_id` and passes the same validation as `build()`; a busy writer still confirms per record. Postgres integration: a refusing sink, appends, a restart, the sink back; each record once, the chain verifies, confirmed segments gone | 275 + 500 | S2a1 | 2026-10-27 |
| S2a2b | The rest of S2a2: the dead-flusher wait, drain death, the hold, `lane.flush()`, the running scan's damage handling, the drain's wake rules, the boot rows that go past both caps (counted; two frames a boot at most), and the S1c reviews' carry list. Unit: a hold refuses appends with `held` and writes no `audit.lane_resumed`; while the flusher is dead the drain waits for a restart; a dead drain stops the lane; `flush()` returns once every earlier frame is confirmed, or times out; a lane at either cap restarts, writes its boot row and drains once the sink answers, while an ordinary append is still refused `full` | 195 + 590 | S2a2a | 2026-10-27 |
| S2a2c | Split from S2a2b at its 800-line cap: the drain's pacing, which the coordinator ruled on #3009 on 2026-10-18 (S2a2a's security review): no hand-over while the writer holds `DRAIN_PAUSE_DEPTH` records not yet in Postgres, so a catch-up leaves live `emit()` callers most of the WAL, and a counter of the pauses for S4a; with it, the writer's `buffer_depth` counts only this process's records (an S2a1 file), and the S2a2b re-check's pins, a boot row cancelled or refused stopping the lane among them. Unit: a backlog over the depth goes over in batches that stop at it and resume as the WAL drains; a live `emit()` still fits during a catch-up; each pause counts once | 310 counted | S2a2b | 2026-10-27 |
| S2b-1 | Split from S2b at its seam: the key files and the boot refusals that need no open lane (no key, `CV_AUDIT_LANE_KEY_HEX` or `CV_AUDIT_LANE_PREVIOUS_KEY_HEX` set, a key equal to the TOTP, recovery-code or CSRF key or the pepper as the environment configures them, since a keyring key generated inside M2 never leaves it (#2152), a key file under the directory of `CV_AUDIT_WAL_PATH`) and a line in ADR-0009's key inventory; nothing calls the loader at boot until S2b-2a. Unit: the key file's checks, a permission test (mode `0400` and owner), each of those refusals, the key in no log line or refusal | 785 counted | S1a | 2026-10-29 |
| S2b-2a | Split from S2b-2 at its seam: the façade and its fallback under the caller's deadline; `AuditService` wiring (start: writer, break-glass fold-in, lane; stop: the lane first), which runs S2b-1's loader at boot; the flag (decision 12); the boot refusals that need the lane's directory (an unanchored directory, `lane.lock` held), while a lane that cannot be opened, or whose `lane.lock` fails otherwise (counted), holds and boot goes on. The flag's read is cached and refreshed in the background, so it never spends a caller's deadline; it keeps the last value read while the flag store cannot be read, and a boot during an outage runs on the flag's catalogue default, off during rollout (ruling READY-21). As S2b-1 reads them, an empty `CV_AUDIT_LANE_KEY_HEX=` line in `.env` is dropped by pydantic-settings and not refused, because it carries no key material, while a non-empty value, current or previous, refuses boot (`test_an_environment_key_in_the_env_file_is_refused_at_load`). Unit: the fallback paths, those two refusals and the hold, flag off equals today's path, the stop order | 797 counted | S2a2b, S2a2c, S2b-1 | 2026-10-29 |
| S2b-2b1 | Split from S2b-2b at its seam: S2b-2a's review carries. `FeatureFlagsRuntime.stop()` cancels the flag's refresh and starts no other (SR-S2B2A-01); `AuditService.stop()` closes the lane within half its grace, logs a close that fails or overruns as critical and stops the writer all the same, and releases each lock only once what it guards has stopped, so `lane.lock` outlives a lane operation that may still run (#2250) (SR-S2B2A-03); the hard-link probe at boot (§15.6 Failures while running), whose failure holds the lane (counted); a rate-limited `audit.lane.fallback` WARNING; decision 12's cached read (SR-S2B2A-02). From S2a2c's re-check: a `start()` cancelled while the shielded open runs stops the lane (S2A2C-R2-1); the writer counts a dead batch's confirmed records in `buffer_depth` after a restart (SEC-S2A2C-R2-1); a warning line per boot row past a cap (SEC-S2A2B-R2-3). Unit: the refresh cancelled at stop, its cadence and single flight; each step of `stop()` past a failed one; the probe's hold; the façade's keywords against `emit()`'s; the fallback log; the cancelled open; a paused drain that still confirms, and a pause after a refused hand-over that counts again; the segment cap alone refusing a second `audit.lane_resumed`; the bundled S2b-2a tests split, one behaviour each | 795 counted | S2b-2a | 2026-10-29 |
| S2b-2b2 | The rest of S2b-2b: key provisioning (compose secret, `.env.example` placeholder, CI); an absolute `CV_AUDIT_WAL_PATH` in compose, which #2615 set (#3290). Unit: a compose test that the key is a file secret, absent from `environment:`, with the mode and owner proven (non-Swarm compose may ignore `mode` and `uid`). Chaos (C-13.6 scenarios 10 and 12, and 13's disk-full fault on the audit volume): Postgres stopped until a small `max_wal_bytes` fills, SIGKILL during an append and during a drain, the volume full; nothing lost or duplicated; a frame tampered between restarts gives one row, and a second restart no second row. CI: the image step that loads a provisioned key and refuses `/dev/null`, and #3285 item 3's image half (the audit mount point `10001:10001`, `0700`). From its review: scenario 10's refused record is a sign-out as large as the hand-overs the WAL refuses, so the duplicate check counts it (SEC-S2B2B2-01); `audit_lane_wiring.py` in `pr.yml`'s `image` filter (SEC-S2B2B2-02); the key file's host placement in `docs/ops/runbooks/auth-rbac.md` §3 (SEC-S2B2B2-03) | 752 counted | S2b-2b1 | 2026-10-29 |
| S2b-2b3 | Split from S2b-2b2 at its seam: S2b-2b1's review carries. `AuditService` keeps the lane from before its `open()`, so a `stop()` after a boot cancelled there waits for that open within its bound and, past it, keeps `lane.lock`; the lane's close outcome outlives the `stop()` that saw it, so a later one never releases `lane.lock` after a failed close (SR-S2B2B1-01); `FeatureFlagsRuntime.start()` reopens the lane flag that `stop()` closed (SR-S2B2B1-02); the hard-link probe's critical log names the errno. Unit: both lock corners, the flag closed before the engine goes and reopened by a restart, the probe only under `lane.lock`, one boot read; a wider margin in the overrun test (SR-S2B2B1-03) | 184 counted | S2b-2b2 | 2026-10-29 |
| S2c | The offline release command in `admin/` (under `lane.lock`, cv-api stopped) and its runbook row. Unit and integration: an unknown-`kid` frame is held, released and recorded as one `released` row with the operator, ticket and `operator_reason`; a note with a bad MAC or another hold is ignored; the command refuses while cv-api runs | 796 counted, in one PR with S3 and S4a-2 | S2b-2b3 | 2026-10-31 |
| S3 | The rows: `api/sessions.py` (the logout intent and outcomes, revoke-my-session, the reuse intent and race outcome, the disabled user's denial), and the login outcome rows if #2914's PR C has landed (otherwise PR C adopts the façade, Q2). Unit per row with #2872's `_RefusingWriter`: flag on, sink refusing, lane accepting, so logout and revoke answer `204`, a reused token's family is revoked, the outcome rows land after a restart and nothing is counted lost; both refusing, today's answers and counters; flag off, today's behaviour; a `shared` flood leaves room for a sign-out (`test_login_flood_leaves_room_for_logout`). Integration: a sign-out during an audit outage, a restart, the rows exactly once; `test_auth_e2e_pg.py` awaits `lane.flush()` | 650 counted, in S2c's PR | S2b-2a; #2914 slice D merged; Q1 decided | 2026-11-03 |
| S4a | Metrics (`cv_audit_lane_depth`, `_bytes{class}`, `_oldest_age_seconds`, `_last_seq`, `_appended_total{class}`, `_drained_total`, `_refused_total{class,reason}`, `_drain_failures_total{reason}`, `_anomalies_total{reason}`, `_quarantine_bytes`, `_created_total`, `_paused_batches_total` (S2a2c's `AuditLane.paused_batches`), `_boot_overshoot_frames_total` (S2a2b's `LaneJournal.boot_overshoot_frames`, alerted on with a restart alert, since a crash loop can die before a scrape), `_lock_failures_total` and `_link_failures_total` (S2b-2a's `AuditService.lane_lock_failures` and S2b-2b1's `lane_link_failures`: boots that held the lane), the gauge `cv_audit_lane_journal_first` (removed in S4b-1b; the flag's effective value, which the admin API cannot show while the flag store is down; SR-S2B2A-02), `_state{state}` (`open`, `held` or `stopped`, which the hold and stop alerts read, so a quiet lane alerts too: review L6), and `cv_audit_writer_refused_total{domain}`, the action's first dotted segment: the write-ahead refusal signal asked for on #3009 at 2026-10-17 01:50Z), each with its catalogue entry, golden row, §12.1 row and label allow-list entry as in #3057. Alerts that page, never muted by quiet hours, once the Owner grants them (#2701; until then each ships as a ticket that says so): `AuditSinkRefusing`, `AuditLaneBacklogAged`, `AuditLaneRefusing`, `AuditLaneAnomaly` (a torn tail alone is a ticket, `AuditLaneTornTail`), `AuditLaneDrainHeld` (it says the façade has fallen back), `AuditLaneSeqRegressed`, `AuditLaneCreated`; tickets: `AuditLaneQuarantineGrowing` and the restart alert `AuditLaneBootOvershoot`. Promtool tests, `07-release-and-prr.md` entries and `docs/ops/runbooks/auth-rbac.md` rows, key rotation and `_PREVIOUS_` retirement among them. Split at its seam: S4a-1 the metrics, S4a-2 the alerts and runbook rows | S4a-1 799 (#3758); S4a-2 730, its review folds 464 and S4a-1's 179 counted, in S2c's PR | S3 | 2026-11-04 |
| S4b | Split by main-orchestrator into six PRs, in this order. S4b-2b (#4005): `lane.lock` taken through directory descriptors (SEC-REM-03, decision 9) and a boot that passes a damaged newest segment (§15.6 row 16). S4b-1a (#4019): a replay of a contained family takes the `shared` row (Q9, decision 13). S4b-1b (#4021): the backstop's record through the lane, the `cv_audit_lane_journal_first` gauge removed, RR-01 extended to the lane's key and frames, and the release-checklist row of the Consequences. S4b-1c (#4037): the flag removed (decision 12) and a lost backstop record counted. S4b-1d: the exit records, EX-07 and EX-08 removed, EX-10 added for the login routes' refusal rows, RR-16 narrowed, RR-01 extended to an ingested record, §8.3's sentences updated, the counter-coverage test checking the registry, this record accepted, and Amendment 1. S4b-2a: the drill, an outage with sign-outs and a login flood, a restart, a tampered frame and a rolled-back copy (AC-LANE-01, -04 and -09), with the closing line | 300 planned; each PR counts its own | S4a; #2615 merged | 2026-11-05 |

**Schedule risks.** S3 needed #2914's slice D, merged as #3229 on 2026-10-17; S4b needed #2615, which #3290
closed on 2026-10-17, so S4b no longer waits on it (Q10 is answered). The E42-T02 fold train, rationed CI and
the stack-depth cap limit how many slices can be in review at once. If S4b cannot open by 2026-11-05, or a
contingency split threatens that date,
hpe-worker-1 says so on #3009 by 2026-10-25. S4b merges by 2026-11-10; if it has not, hpe-worker-1 asks the owner
that day, on #2701, for EX-07's re-decision, since its row says to re-decide, never extend; S4b-1d removed
that row, so only the drill's date remains.

**`infra/` impact.** No new volume: `lane/` sits on #2615's audit volume (an absolute `CV_AUDIT_WAL_PATH`), and
cv-api creates it, directory `0700` and files `0600`, as uid 10001 on the read-only root filesystem. S2b-2a
makes the key mandatory on a real backend, and S2b-2b2 provisions it as a compose file secret at
`/run/secrets/cv_audit_lane_key`: the host file `0400` and uid 10001, which compose without Swarm mounts as it is;
`.env.example` holds an empty path placeholder only (C-12.2), and unset the source is `/dev/null`, which a real
backend refuses; one key per environment (C-2.11). Compose runs the fake backend, so no compose stack needed the
key in between, and CI's image step loads a key provisioned that way. S4a adds the alert rules
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
  keeps its framing idea and its fsync before return, but not its truncate-before-append rule: where the WAL
  cuts a torn tail before the next append, the lane seals the segment and rotates to a new one.
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

- **Q1, owner and Security, before S3.** Confirm the narrowed RR-16: sign-out, revoke-my-session and reuse
  containment proceed journal-first, while refresh and sign-in stay fail closed. Should the Owner's revocation
  of another user's session (`revokeUserSession`) and a user's disablement (SR-029) join now, since ending a
  compromised Manager's session matters more than self sign-out? Answered 2026-10-20 with the ratification:
  the narrowed set only. `revokeUserSession` (`users.session_revoked`, `api/users.py`) and a user's
  disablement stay on the writer; their joining is a carry (Amendment 1).
- **Q2, hcl-worker-1.** If #2914's PR C lands after S3, does it call the façade itself? Does F1 stay as it is
  on the branch? Is `cv_audit_writer_refused_total{domain}` the write-ahead refusal signal you asked for, or do
  the `503` sites also need a per-action counter? Answered by #2914's PR C (Amendment 2): yes, per call site; F1
  stays as S3 shipped it; that series is the signal, and no per-action counter is added.
- **Q3, main-orchestrator.** Are §15.6's limits enough for a dead flusher left for hours, or should S2b's chaos
  run size them first? The one `reserved` source reachable without a session, besides the recovery's unplanned
  revocation (Amendment 2), is a rotated-token replay,
  bounded by the refresh route's per-address and per-session throttles (`api/sessions.py:266-272`).
- **Q4, E27 (KV-D04).** Separate action ids for the risk-reducing borrow purposes, or a purpose rule in the
  registry?
- **Q5, owner.** Accept the shared volume (the lane does not cover a full or read-only audit volume), or add a
  reserve, such as a ballast file, in a later ticket? Answered 2026-10-20 with the ratification: the shared
  volume is accepted (RR-16), and the reserve is a carry (Amendment 1).
- **Q6, Security.** Give the main WAL the lane's frame MAC in a follow-up ticket?
- **Q7, owner.** Should other outcome records lost without a retry today (for example the ones
  `cv_credential_outcome_audit_failures_total` counts) join the registry, or get a §16.2 exception? The
  2026-10-20 ratification's answer, "the §16.2 exception per family" (#3910's record), is superseded by the
  2026-10-21 rulings. Answered by main-orchestrator 2026-10-21 for S4b-1d, recorded on #3009
  (issuecomment-6308870301): no §16.2 rows for the lane's callers. The lane covers every outcome record the
  session routes and the backstop write. The login routes' rows are registered but not yet lane-written (Q2;
  Amendment 1's carry), and EX-07 excluded them; a later ruling the same day gives them one narrow row, EX-10
  (04 §16.2), until #2914's PR C (issuecomment-6321348055): EX-10 is now that answer, for the login family
  alone. The records that counter counts, outside auth, stay with E27 KV-D04 (How E27 KV-D04 joins the lane).
  EX-10 left §16.2 with #2914's PR C (Amendment 2).
- **Q8, owner.** `quarantine/` keeps PII (`actor_ip`, user and session ids) for good. Do account erasure and
  the retention job reach it, or does it follow `audit_log`'s indefinite retention (C-12.8)? Answered
  2026-10-20 with the ratification: it follows `audit_log`'s indefinite retention.
- **Q9, Security.** Should a replay against an already-revoked family get its own `shared` action id, keeping
  only the first containment intent `reserved`? Answered: yes, `auth.refresh_reuse_replayed` (main-orchestrator
  2026-10-21, ruling (a)); decision 13.
- **Q10, main-orchestrator.** Who owns #2615, which S4b needs? hpe-worker-1 can carry it in S4b if nobody has
  claimed it by 2026-10-28. Answered: #2615 was closed by #3290 on 2026-10-17.

## Validation

- S1a to S4b carry the named tests above; the integration and chaos lanes run in CI.
- #3009's done-means maps to the slices: the EX-07 rows are written journal-first (S3); a refusing sink and a
  restart lose none of them (S2a2, S2b, S3); EX-07 is removed and RR-16 updated (S4b-1d); unit, Postgres-integration
  and chaos tests pass, and the journal's tamper evidence is tested (S1a, S2a2, S2b).
- The decision was taken on 2026-10-20, when main-orchestrator ratified it under the owner's delegation (status
  line).

## Amendment 1 (2026-10-21, #3009 S4b-1d: the lane's exit and the carries it leaves)

**The exit.** Journal-first is unconditional since S4b-1c removed the flag (decision 12): every record that a
call site hands to the façade and `LANE_ACTIONS` admits goes to the lane first, with the writer as its fallback.
S4b-1c also counts a lost backstop record on
`auth_audit_outcome_lost_total{action="auth.disabled_user_session_revoked"}`, which `AuthAuditOutcomeLost`
alerts on, as main-orchestrator ruled on #3009 (Info-1, from #4021's security review). So EX-07 and EX-08 leave
`04-security-program.md` §16.2 together in S4b-1d, with no narrowed EX-08: the lane is §8.3 rule 2's durable
retry for every outcome record the session routes and the backstop write, and a record that the lane and the
writer both lose is counted and alerted. The login routes' rows are registered but not yet lane-written (Q2),
and EX-07 excluded them: their adoption is a carry below. §8.3 now says so, and reads rule 1 by analogy for the
backstop's record, which has no intent ahead of it because refusing that revocation would leave a disabled
user's session alive (SR-029). RR-16 narrows to what remains: refresh, sign-in, and the idle lock's extend and
unlock (#4052) fail closed while the sink refuses, and sign-out and revoke-my-session while the lane refuses
too, as a full or read-only audit volume makes it (Q5); a double refusal still loses an outcome row, now counted
and alerted (#4021's Low-2). RR-01 takes residual 4 of the threat model's §3.6.2, a lane record waiting in the
CRC-only WAL after ingest (Q6), beside residuals 1 and 2. Q7 adds no §16.2 rows for the lane's callers; EX-10
covers the login routes (until Amendment 2). The counter-coverage tests now check, for each action the counter
covers, that it is a `LANE_ACTIONS` row and that both runbook entries name it
(`tests/unit/auth/test_audit_outcome_lost_alerts.py`).

**Built, not carried.** SEC-REM-03, and with it the one helper for the lock that S2c's review left unfolded: #4005
takes `lane.lock` through directory descriptors, for cv-api and the release command alike (decision 9). S2c's n3:
#4005's scan fails fast when a release note does not move it past its hold
(`test_a_note_that_does_not_move_the_scan_forward_fails_fast`). From #3910's review: N1, which #4005 built
(`test_lane_journal_scan.py` pins `gap_again.end == (7, 0)`), and c8-F1, which #4021 built (`test_lane_metrics.py`
pins an empty lane's `oldest_age_seconds` at exactly 0). F3 needs nothing: the S3 row has read 650 counted, the
figure `count_loc` gives, since #3910 merged.

**Carries, recorded and not built.** Filing has been frozen since 2026-10-19, so these are recorded here
instead of as issues; #3009 closes with S4b-2a, and this ledger outlives it. Each names where it was raised, an
owner and the trigger that brings it back.

- **Compose's previous-key input** (#3910, S4a-2's C3). Compose gives the `api` service one lane key secret and no
  `CV_AUDIT_LANE_PREVIOUS_KEY_FILE`, so a key rotation under compose is blocked (`docs/ops/runbooks/auth-rbac.md`
  §13). Owner: E09 security. Trigger: the first lane key rotation in a compose deployment.
- **The Q5 reserve.** A reserve on the audit volume, such as a ballast file, so that a full volume still leaves
  the lane room (the threat model's §3.6.2 residual 3, RR-16). Owner: the Owner (Q5, #2701), with E09 security.
  Trigger: the first lane and sink refusal caused by a full or read-only audit volume, or RR-16's review.
- **The Q1 follow-up.** The Owner's revocation of another user's session (`users.session_revoked`,
  `api/users.py`) and a user's disablement (`users.disable`, `admin/user_disable.py`) joining the lane: a
  registry row and a lane port at each call site. Owner: the Owner decides on #2701, and E09 security builds it.
  Trigger: that decision, or such a revocation or disablement refused with `503` during an audit outage.
- **The login routes' adoption of the façade** (#2914's PR C, Q2). `LANE_ACTIONS` registers the six login
  outcome actions (decision 3), but `api/auth.py` writes every record through `AuditService.writer`, so none
  reaches the lane yet; EX-07 excluded them too. Adopting it means calling `AuditService.lane`, with the
  `LaneNotWired` guard `api/sessions.py` uses. Its constraint: `auth.login` is registered `shared` for any
  outcome, yet it is also a write-ahead record of the enrolment-only mint (`_enrolment_only_sign_in`), as
  `auth.recovery_code_used` is of the recovery mint. So is `auth.session_revoked`, `reserved` for any outcome:
  `/auth/mfa/recovery` and `/auth/mfa/enroll/confirm` write it ahead of their mints, so a wholesale move of
  `api/auth.py` to the façade would put those rows in the `reserved` class too. Decision 3's list of a mint's
  records names none of the three. U42's control (admission by action and outcome, which excludes mints) holds
  today only because `api/auth.py` stays on the writer, so PR C splits those actions or keeps the mints' call
  sites on the writer. Until PR C, a refused mint's row that the writer cannot write (`_audit_refusal`) is
  logged only, neither journaled nor counted, as is a refusal row of `/auth/mfa/recovery`: exception EX-10
  (04 §16.2, expires 2026-11-15) records that gap. Two more rows of `api/auth.py` are PR C's, and EX-10 lists
  neither. First, `/auth/mfa/recovery` writes an `unplanned` `auth.session_revoked` row through the writer,
  after its commit and `revoke_all`, for each session minted since its plan: an outcome row. One that the
  writer refuses ends the request in the `unminted` `401` and stops the loop, so no later row is tried;
  nothing journals it or counts it on `auth_audit_outcome_lost_total`, and the log line
  `auth.recovery.completed_unminted` names the planned (`ending`) sessions only, so no record or line names the
  unplanned ones. `auth.session_revoked` is not one of EX-10's six actions. PR C names the unplanned ids in
  that line and takes the row onto the façade like any outcome row. Second, `/auth/mfa/verify` writes
  `auth.session_created` after `mint()`, not ahead of it, although decision 3 lists it among a mint's
  write-ahead records: a refused write is not caught, so the route answers `500` (`internal_error`) with the
  session row minted and never delivered, and no record of it. PR C writes it ahead of the mint, as
  `_enrolment_only_sign_in` does, or amends decision 3. Owner: hcl-worker-1, with E09 security. Trigger: PR C.
  **Built** by #2914's PR C, with both rows: Amendment 2.
- **SEC-REM-01** (#3910). When the lane's alerts become pages, they need `absent()` guards on
  `cv_audit_lane_state`, `cv_audit_lane_anomalies_total` and `process_start_time_seconds`: a lane read that fails
  at a scrape drops every lane family, and the young-process arms read the start time. Owner: the Owner (#2701).
  Trigger: the page promotion.
- **SEC-REM-02** (#3910). A second release of the same hold, after its first `released` row committed, is
  deduplicated by the keyed `record_id`, so the second operator's words never reach `audit_log`. S4b-2a lands it
  as one sentence in `docs/ops/runbooks/auth-rbac.md` §12. Owner: E09 security. Trigger: S4b-2a, whose merge
  closes it; should S4b-2a drop the sentence, the next change to that section.
- **S3-I3** (content not recorded in the repo; S3's security review in #3910), an Info neither folded nor carried
  there. Owner: E09 security. Trigger: the next change to the session routes' lane rows (`api/sessions.py`).
- **S2c's review Q4** (#3910): the optional Q4 fix of S2c's code review and its word tightenings, not folded
  there (the review's Q4, not this record's). Owner: E09 security. Trigger: the next change to the release
  command (`admin/lane_release.py`).
- **S4a-1's N1, N5 and N6** (#3758), from S4a-1's code review: one `os.stat` for a quarantine copy's size (N1),
  N5's zip and stand-in guards, and a test's shape (N6). Owner: E09 security. Trigger: the next change to the
  lane's metrics (`audit/metrics.py`).
- **c8-L-1** (#3910, an optional Low). A smaller fake `WAIT_S` (5 to 10 fake seconds, not 600) in
  `test_lane_release.py` and `test_lane_metrics.py`, the modules #3910's commit 8 moved to `VirtualTimeLoop`, so
  a retrying stall is reported sooner: it takes about 23 real seconds today, bounded and never silent.
  (`test_lane_drain.py` keeps its 600: a test there waits through 121.5 fake seconds of backoff.) Owner: E09
  security. Trigger: the next change to either module.
- **c8-F2** (#3910). One shared `until()`, `workers()` and `failed()` in `tests/unit/audit/audit_waits.py`, of
  which `test_lane_drain.py`, `test_lane_release.py` and `test_lane_metrics.py` each keep a copy today. Owner:
  E09 security. Trigger: the next change to one of those modules.
- **The `ReexportCollector` scrape guard.** `ReexportCollector.collect()` (`observability/metrics.py`) serves
  the default registry's families with no guard, so one collector that raises at a scrape fails the whole
  scrape, where `ScrapeCollector` loses only its own families (SR-S4A1-01, #3758; #3910 guarded it). Owner:
  backend-platform. Trigger: the next change to `observability/metrics.py`, or a scrape that fails.
- **F2** (#3910), promtool constants not yet pinned (AuditLaneSeqRegressed's `[1d]`, the young `< 900` windows,
  AuditLaneBootOvershoot's `[1h]` and AuditLaneTornTail's young-arm `reason` selector), in
  `infra/alertmanager/gen_promtool_tests.py` and the regenerated `infra/prometheus/tests/system_alerts.test.yml`.
  S4b-2a's drill reads the lane's series those rules select from the real exposition, and keeps promtool
  synthetic; `process_start_time_seconds`, which the young arms read, comes from the default registry and is not
  drilled. The pins were not built there because the drill already takes the PR past C-4.8's preferred 400 lines, so
  they stay a carry. Owner: E09 security. Trigger: the next change to those rules or to `gen_promtool_tests.py`.
- **The boot-side recovery of a volume an earlier build wedged** (`24-internal-schemas.md` §15.6, Failures while
  running; from #4005): frames in a segment named below one the drain had passed are not recovered; a boot that
  scans such a segment first, as row 2 does, would recover them. No live volume holds such frames; a staging
  volume is checked by hand (§15.6). Owner: E09 security. Trigger: a lane restored from a backup taken before
  #4005, or a boot that meets such a segment.
- **The refresh race** (from #4019's security review, a Low). A refresh that claims the live head while a
  containment walk runs mints a successor the walk misses (`SessionService.refresh`'s rotated branch, where the
  family walk runs before `link_rotation`); the next presentation of a held member revokes it under the
  `warning` replay row although a live session flipped. No row is lost, and the `401` and the revocation stand.
  The fix is for `RefreshReuseDetected` to carry the newly revoked ids, so that a replay that revokes something
  writes the `critical` row. With it, the same review's Info: on the concurrent-refresh race path a family's
  only `critical` row is the outcome row, so a double refusal that loses it leaves the family with `warning`
  replay rows only; that loss is counted on `auth_audit_outcome_lost_total{action="auth.refresh_reuse_detected"}`
  and alerted by `AuthAuditOutcomeLost`. Owner: E09 security. Trigger: the next change to
  `SessionService.refresh` or to the reuse handler in `api/sessions.py`.

## Amendment 2 (2026-10-22, #2914's PR C: the login routes on the façade; Q2 answered)

**Built.** `api/auth.py` hands its outcome and refusal rows to `AuditService.lane` through one helper,
`_outcome`, with the `LaneNotWired` guard and the one warning per router of `api/sessions.py`
(`auth.login_audit.lane_unavailable`): `/auth/login`'s `auth.login_failed`, `auth.account_locked` and the
password step's `auth.login` (no session exists yet), `/auth/mfa/verify`'s `auth.mfa_failed`, a refused mint's
`auth.login_failed` (`_audit_refusal`, at the sign-in, the MFA step and the confirm), `/auth/mfa/recovery`'s
refusal rows (`failed()`) and its `unplanned` `auth.session_revoked` rows, and the confirm's `auth.mfa_failed`
rows. Each write, the lane's wait and the fallback together, is bounded by the audit timeout (`AUDIT_TIMEOUT_S`),
as the session routes' outcome rows are. A row the lane and the writer both refuse, or whose write times out or
is cancelled, or that has no sink, is counted on `auth_audit_outcome_lost_total{action}`, whose closed set gains
`auth.login`, `auth.login_failed`, `auth.account_locked`, `auth.mfa_failed` and `auth.recovery_codes_exhausted`,
and logged as `auth.login_audit.outcome_lost` with the action and the error class only; the answer stands. Any
other error is a defect, counted and raised. Before, such a refused row was logged only (`_audit_refusal`,
`failed()`), turned the answer into a `500` (`/auth/login`, the MFA step's and the confirm's `auth.mfa_failed`),
or, for an `unplanned` row, ended the recovery in its `unminted` `401`; now the recovery goes on, and
`auth.recovery.completed_unminted` names the `unplanned` ids among its `revoked_session_ids`. So EX-10 leaves
`04-security-program.md` §16.2, and Amendment 1's carry for the login routes is built.

**U42: the call site chooses, and no action is split.** The write-ahead records stay on the writer by call site,
as unlock's do (Q1): the carried-session record; `auth.login` and `auth.session_created` of the enrolment-only
sign-in; `auth.mfa_verified` and `auth.session_created` of `/auth/mfa/verify`; the recovery's planned
`auth.recovery_code_used`, `auth.session_revoked` and `auth.session_created`; `auth.mfa_enroll`; and the
confirm's planned `auth.mfa_enrolled`, `auth.recovery_codes_regenerated`, `auth.session_revoked` and
`auth.session_created`. Decision 3's table and `LANE_ACTIONS` do not change, and its sentence on a mint's
write-ahead records holds per call site, for `auth.login`, `auth.recovery_code_used` and `auth.session_revoked`
too. `auth.recovery_code_used` keeps its registry row although no route hands it to the façade: its one record
is the recovery mint's write-ahead record, so the counter's set leaves it out as well.
`test_a_mints_write_ahead_record_never_reaches_the_lane_so_its_refusal_mints_nothing`
(`tests/security/auth/test_login_audit_lane.py`) pins it for 11 of those records, all but the carried-session
record and `auth.mfa_enroll` (neither is a lane action, and older tests cover both): with the writer refusing
any one of the 11 and a lane that takes every row it admits, each mint answers its refusal, mints and revokes
nothing, and hands the lane nothing.

**`/auth/mfa/verify`'s `auth.session_created`** is written ahead of the mint now, on the writer, naming the id
the mint then uses, as `_enrolment_only_sign_in` does; decision 3 stands unamended. A refusal answers the
operation's `401` (`audit sink not active`, as for the carried-session record) and mints nothing, and a user
disabled since the password step gets the refusal row that voids it, as does a mint that fails in the store
(an `auth.mfa_failed` row, reason `unminted`, and the error log `auth.mfa_verify.unminted`; the `500` stands).
`auth.mfa_verified`, the first of the route's write-ahead records, answers a refusal with the same `401` (it
was a `500`), so a sign-in answers `401` throughout an outage of the sink, with nothing minted and the TOTP
step spent.

**The recovery's `unplanned` rows** are `reserved`, as the class follows the action. They are reachable without
a session, but only past a recovery code the same request spent (one use each, ten per user) and only for a
session minted while that recovery ran, so they add no flood source beside Q3's.

**Q2's answers.** PR C calls the façade itself, per call site (`_outcome`). F1 stays as S3 shipped it
(`api/sessions.py`). `cv_audit_writer_refused_total{domain}` is the write-ahead refusal signal asked for: a
refused write-ahead record of the login routes counts on `domain="auth"`, and its route answers `503` or `401`,
so no per-action counter is added.

## References

- `docs/plan/04-security-program.md` §8.1, §8.3, §16.1 (RR-01, and RR-16, the sink-refusal residual) and §16.2
  (EX-07 and EX-08, until S4b-1d removed them, and EX-10, until #2914's PR C did)
- `docs/plan/24-internal-schemas.md` §15.4 and §15.6; `docs/plan/21-database-schema.md` §10.7
- `docs/security/threat-models/e09-auth-rbac.md` §3.6.1 and §3.6.2; `docs/security/threat-models/E27-accounts.md`
  KV-D04 and AC-27
- `docs/plan/27-adrs/ADR-0009-secrets-and-key-management.md` Amendment 4;
  `docs/plan/27-adrs/ADR-0010-auth-and-rbac.md`; `docs/plan/27-adrs/ADR-0036-dev-only-account-fixture-transport.md`
  decision 10
- `audit/writer.py`, `audit/wal.py`, `audit/journal.py`, `audit/service.py`, `audit/models.py`,
  `admin/breakglass.py`, `admin/flags/catalogue.py`, `api/sessions.py`
- #3009, #2914, #2267, #892, #2119, #2615, #2443, #2467, #2251, #2872
