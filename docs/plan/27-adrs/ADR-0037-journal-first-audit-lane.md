# ADR-0037 — Journal-first audit lane for auth outcome records (EX-07 exit)

- Status: **proposed**. The design PR of #3009, docs only. main-orchestrator accepts or amends it under the
  owner's delegation before S1 merges; the owner ratifies it before S3 merges, the first slice that changes what
  a user sees during an audit outage. EX-07 expires on 2026-11-15, and the S4 PR opens by 2026-11-08
  (orchestrator note on #3009, 2026-10-16 23:40Z).
- Date: 2026-10-17
- Deciders: Owner (`@basiltt`) through main-orchestrator. Consulted: hcl-worker-1 (the #2914 rows, EX-07 and
  RR-15); the Security engineer through the `security-review` label. Author: hpe-worker-1 (the audit chain lane).
- Numbering note: 0031 is reserved by E45-K01 (`ADR-0031-resilience-and-chaos`, not on `main`) and 0036 is the
  last on `main`, so this record takes the next free number.
- Related: #3009; #2914 (rulings D1 to D4; its slice D adds EX-07 and RR-15); #2267 item 4 (E27 KV-D04) and
  #892 (E27-Q03); #2119 (the break-glass journal); #2615 (the durable audit volume); #2251, #2872; ADR-0009
  Amendment 4, ADR-0010.
- Evidence: `main` at `47ade3a2`; module paths are under `services/api/candleviewer/`. EX-07, RR-15 and the
  #2914 code are read from `origin/fix/e09-2914-session-audit-residue` at `dfeb852e` (no PR open yet).

## Context and problem statement

`AuditWriter.emit()` appends a record to the local WAL with an fsync before it returns, and one flusher task
moves it into `audit_log` (`audit/writer.py:1-26`). It refuses with `AuditUnavailable` or `AuditWriterStopped`
when the WAL stays at its cap after compaction (Postgres has been down long enough), when the WAL cannot be
written, when the flusher has died, and while the writer is not running (`audit/writer.py:358-387`,
`audit/wal.py:166-180`). The caller must then refuse the audited action. Three kinds of record suffer:

1. **Auth outcome records**, written after the action took effect: one `auth.session_revoked` per session that
   `POST /auth/logout` revoked, `auth.refresh_reuse_detected` for the concurrent-refresh race, a disabled user's
   refused refresh (`auth.session_refreshed`, `denied`, reason `user_disabled`) and, once #2914 item 2 lands,
   the login-route outcome rows. A refusal loses the record. It is counted and alerted
   (`auth_audit_outcome_lost_total{action}`), but `04-security-program.md` §8.3 rule 2 also asks for a durable
   retry. EX-07 (§16.2, added by #2914 slice D) waives that half until 2026-11-15; from then on the required
   `governance` check (`tools/ci/check_accepted_risk_expiry.py`) fails every PR.
2. **Risk-reducing write-ahead records**: `auth.logout` before a sign-out, `auth.session_revoked` before
   `DELETE /me/sessions/{id}`, and `auth.refresh_reuse_detected` before a reused token's family is revoked.
   While the sink refuses, these routes answer `503` and revoke nothing. That is residual RR-15 (§16.1), which
   the D2 ruling on #2914 keeps until the journal-first lane exists.
3. **E27 KV-D04** (#2267 item 4, measured by E27-Q03, #892): the same refusal stops every credential borrow,
   stop and cancel signatures included.

Nothing on `main` can hold these records durably while the sink refuses:

- The break-glass journal (`audit/journal.py`, #2119) admits only `auth.break_glass_*` (`:28-29`, decision R3).
  The offline CLI writes it while cv-api is stopped, and cv-api folds it in at boot only
  (`audit/service.py:72-83`).
- The Postgres `outbox` is down in the main case: the WAL reaches its cap because Postgres is down.
- An in-memory queue is lost on restart.
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
   rule applies (C-3.3). No bespoke serializer and no direct insert.
6. **Available without Postgres or the KEK**, because the main case is cv-api restarting while Postgres is
   down.
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
   accepted counts as written for §8.3 rules 1 and 2: the destination changes, the order of intent, side effect
   and outcome does not. Journal-first rather than sink-first: one path per action keeps the lane's order equal
   to the write order, and a stalled WAL, not only a refusing one, cannot hold up a risk-reducing record.
2. **A façade with `emit()`'s shape.** `AuditService.lane.emit(action, *, ...)` takes the keyword arguments of
   `AuditWriter.emit()` and builds the record with `AuditWriter.build()`: the part of `emit()` that validates
   the action, redacts `before_state` and `after_state` and constructs the `AuditEmission`, moved out of
   `emit()` in S2 with no change in behaviour. A call site changes its receiver, not its error handling.
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
   | `audit.lane_started`          | `reserved` | `success` | the lane's own first record                                        |

   The six login outcome actions are `auth.login`, `auth.login_failed`, `auth.account_locked`,
   `auth.mfa_failed`, `auth.recovery_codes_exhausted` and `auth.recovery_code_used`. The write-ahead records of
   a mint never use the lane: `auth.session_refreshed` with `success`, `auth.mfa_verified`, the carried-session
   record and `auth.session_created`. Refresh and sign-in stay fail closed while the sink refuses, so RR-15
   narrows to them.

4. **Bounds and overflow (C-2.18).** At most `LANE_MAX_BYTES` (32 MiB) of unconfirmed frames, of which
   `shared` may use half and `reserved` all; at most `MAX_FRAME_BYTES` (64 KiB) per frame; waiters on the lane
   lock capped per class (192 `reserved`, 64 `shared`), with `reserved` served first. Past a bound an append is
   refused at once and the façade falls back (decision 1). An accepted frame is never dropped.
5. **Frames.** Append-only segment files of MAC'd, hash-linked frames, each with a contiguous `seq`, the lane
   id, a key id, the class and the record, plus a MAC'd confirmation marker. An append returns only after its
   fsync. The format, the fsync points and the drain protocol are `24-internal-schemas.md` §15.6.
6. **The key.** `CV_AUDIT_LANE_KEY_HEX`, 32 bytes in hex, comes from the runtime environment or a secret file
   like `CV_AUTH_CSRF_KEY_HEX` and `CV_AUTH_PEPPER` (ADR-0009 Amendment 4, "Unchanged"). The composition root
   decodes it (`app.py:434`, the `build_csrf_codec` pattern at `:493-530`) and passes the bytes to
   `AuditService`; `audit` never imports `secrets` (C-3.2), and the key is not an exchange credential (C-2.7).
   It must differ from the TOTP, recovery-code and CSRF keys and from the pepper.
   `CV_AUDIT_LANE_PREVIOUS_KEY_HEX` only verifies, for rotation. The key is required whenever a real audit
   backend is wired: cv-api refuses to boot without it. It is not kept under the KEK: an M2 keyring lives in
   Postgres (`auth_keys`), which is down in the lane's main case, and a KEK failure would then also take
   sign-out away.
7. **Drain and confirmation.** One supervised drain task verifies frames in `seq` order, hands each record to
   `AuditWriter.ingest()`, then waits for `AuditWriter.flush()` (every accepted record is committed to
   Postgres) before it advances the marker. A segment is deleted only when every frame in it is at or below the
   marker. At boot the drain re-ingests from the marker, not from what it handed over before the restart, so a
   WAL lost between `ingest()` and the commit is covered. A duplicate is a no-op, by
   `ON CONFLICT (record_id) DO NOTHING` (`storage/repositories/audit_sqlalchemy.py:43-52`).
8. **Nothing unverified enters the chain, and nothing is skipped silently.** A frame that fails its MAC, a
   `seq` gap, corrupt bytes or a lost marker becomes one critical `audit.lane_anomaly` record in its chain
   position, before the next authentic frame. It is built by `AuditWriter.build()` with a `record_id` derived
   from the lane id, the reason and the first affected `seq`, and handed to `AuditWriter.ingest()`, so a repeat
   after a crash is a no-op. The unverifiable bytes are copied to `quarantine/` and kept. An unknown key id or format version holds the drain and pages instead:
   those frames are probably authentic and wait for the operator. An incomplete last frame (a torn tail) was
   never acknowledged; it is copied to `quarantine/` and truncated.
9. **Placement and access.** `<dir of CV_AUDIT_WAL_PATH>/lane/`, beside `breakglass/`, on #2615's durable
   audit volume. The path is absolute and free of `..` and symlinks (the `anchored_journal_dir` rule,
   `audit/journal.py:50-60`); the directory is `0700` and its files `0600`, owned by the cv-api user (uid
   10001, `infra/images/Dockerfile.api:66`); every open uses `O_NOFOLLOW`. The running cv-api holds `lane.lock`
   exclusively, so a second process on the same volume refuses to boot. No route, WS topic or CLI opens the
   lane, and the break-glass CLI keeps its own journal (R3).
10. **Module boundaries.** Two new files inside M19, `audit/lane_journal.py` (S1) and `audit/lane.py` (S2),
    using only the standard library (`hmac`, `hashlib`, `os`, `fcntl`). There is no new module or import edge,
    so C-3.4 does not apply; this record exists for C-12.1 and the security decision.

## How E27 KV-D04 joins the lane

KV-D04 (#2267 item 4) needs stops, cancels and revocation to stay audited while the WAL refuses or stalls. It
adds no mechanism:

- E27 adds `reserved` rows to `LANE_ACTIONS` for its risk-reducing records (stop placement, cancel, SL amend,
  flatten, and the kill-switch and revocation records), and the composition root wires M2's injected audit
  port for those borrows to `AuditService.lane.emit`: the same files, lock, drain, key, metrics and alerts.
- The class follows the action. Where one action covers risk-reducing and other purposes
  (`security.credential_borrowed`), E27 registers the risk-reducing purposes under their own action ids in
  `audit/actions.py`, so the registry decides and a call site cannot (Q4).
- Latency: a lane append waits for the lane lock and one fsync, never for the main WAL lock, and `reserved`
  waiters go first. #892 measures a borrow's latency through the lane against a direct `emit()`, under a WAL
  stall and under a login flood; E27 then updates KV-D04 and drill AC-27 ("the borrow is refused and alerts")
  for the purposes it moves.

## Consequences

- Good: EX-07 exits. Sign-out, revoke-my-session and reuse containment work while the sink refuses, and RR-15
  narrows to refresh and sign-in. §8.3 rule 2 gets one durable-retry mechanism, which its pointer names. Lane
  frames are MAC'd and hash-linked, stronger than the WAL's CRC, and the exclusive `lane.lock` also keeps a
  second cv-api off the shared WAL.
- Bad: a lane record costs two fsyncs (the lane, then the WAL through the drain) and reaches `audit_log` a
  moment after an `emit()` record would; tests that read rows after a lane write await
  `AuditService.lane.flush()`. Across the lane and the direct path, chain position is arrival order, and
  `event_ts` (set once by `build()`, kept by `ingest()`) is the order of record (U21).
- Bad: one more secret to provision and rotate; a real-backend stack without it refuses to boot.
- Risk: the lane and the WAL share #2615's volume, so a full or read-only volume refuses both and callers
  behave as today. A second docker volume on the same WSL disk would not change that (Q5).
- Risk: once ingested, a record waits in the CRC-only WAL like every `emit()` record; the lane's MAC does not
  reach that far (Q6).
- Residual: someone with cv-api's uid or root can read the key and forge or destroy frames (RR-01). Destroying
  the newest frames or the whole lane leaves no trace on the volume. The off-volume evidence is one
  `audit.lane.appended` log line per accepted frame (`seq` and class only), `cv_audit_lane_appended_total` and
  the `AuditLaneCreated` alert on `cv_audit_lane_created_total`.

## Rollout, slices and the EX-07 exit

One branch per slice (`feat/e09-3009-<slug>`), each at most 800 counted LOC with its tests, labelled
`security-review` (the `audit/` and `infra/` paths), with `Refs #3009` and a `Partial:` line; only S4 carries the
closing line.

| #   | Slice                                                                                | After                    | PR open by |
| --- | ------------------------------------------------------------------------------------ | ------------------------ | ---------- |
| S0  | This record, the STRIDE entry, the frame schema, the §8.3 and §16.2 pointers (docs)  | —                        | 2026-10-18 |
| S1  | `audit/lane_journal.py` and `LANE_ACTIONS`, unit tested                              | S0 accepted              | 2026-10-22 |
| S2  | `AuditWriter.build()`; the `audit/lane.py` façade and drain; `AuditService` and keys | S1                       | 2026-10-28 |
| S3  | The EX-07 and RR-15 rows on the lane                                                 | S2; #2914 slice D merged | 2026-11-03 |
| S4  | Metrics, alerts, runbook rows, the drill; EX-07 removed, RR-15 narrowed; `infra/`    | S3; #2615 merged         | 2026-11-06 |

If the E42-T02 fold train pushes S4 past 2026-11-08, hpe-worker-1 says so on #3009 by 2026-10-25.

- **S1, the journal.** The frame codec, segments, the marker, append with its fsync, quotas and waiter caps
  (`reserved` first), scan and verify, quarantine, compaction, and the registry. Unit tests: a round trip; a
  fault at each fsync point (write, fsync, rename, directory fsync); a torn tail; tamper cases, each detected
  with its reason (a changed byte in `rec`, `seq`, `prev`, `cls` or `lane`; a frame removed, reordered,
  duplicated or spliced from another lane; a segment deleted; the marker forged, rolled forward or rolled
  back; an unknown `kid` or `v`); quotas (`shared` stops at half, `reserved` still fits); a caller cancelled
  during the fsync never releases the lock early (#2250); a hypothesis property: random appends, crashes and
  confirmations keep `seq` contiguous and yield every authentic frame once.
- **S2, the drain into `ingest()`.** `build()` moved out of `emit()`, with an optional `record_id` for the
  anomaly records (the writer tests prove no change); the façade and its fallback; the drain at boot and while
  running, confirmation through `flush()`, backoff and anomaly records; `AuditService` order (start: writer,
  break-glass fold-in, lane; stop: the lane first); the two key settings and the boot refusals (no key, an
  unanchored directory, `lane.lock` held). Unit: a fake writer that refuses N times then accepts, with a restart
  in between, gets each `record_id` once and in order; a `flush()` timeout keeps the marker. Postgres
  integration (`@pytest.mark.integration`): a refusing sink, lane appends, a process restart, the sink back;
  each record is in `audit_log` once, the chain verifies and confirmed segments are gone. Chaos (C-13.6
  scenarios 10 and 12): Postgres stopped until a small `max_wal_bytes` fills; SIGKILL during an append and
  during a drain; nothing lost or duplicated. Tamper evidence: a frame altered on disk between restarts yields
  one `audit.lane_anomaly` row and a quarantine file, and a second restart adds no second row.
- **S3, the rows.** In `api/sessions.py`: the logout intent and outcome rows, revoke-my-session, the reuse
  intent and the race outcome, and the disabled user's denial; the login outcome rows too if #2914's PR C has
  landed, otherwise PR C adopts the façade (Q2). Unit, per row, with #2872's `_RefusingWriter`: with the sink
  refusing and the lane accepting, logout and revoke answer `204`, a reused token's family is revoked, the
  outcome rows land after a restart and nothing is counted lost; with both refusing, today's answers and
  counters. Integration: a sign-out during an audit outage, a restart, the rows exactly once;
  `test_auth_e2e_pg.py` awaits `lane.flush()`. The forbidden-role and IDOR cases stay as they are.
- **S4, observability and the exit.** Metrics: `cv_audit_lane_depth`, `cv_audit_lane_bytes{class}`,
  `cv_audit_lane_oldest_age_seconds`, `cv_audit_lane_appended_total{class}`, `cv_audit_lane_drained_total`,
  `cv_audit_lane_refused_total{class,reason}`, `cv_audit_lane_drain_failures_total{reason}`,
  `cv_audit_lane_anomalies_total{reason}`, `cv_audit_lane_created_total`, and
  `cv_audit_writer_refused_total{domain}`, the write-ahead refusal signal asked for on #3009 (2026-10-17 01:50Z)
  that KV-D04 shares. Alerts, whose pages quiet hours never mute: `AuditSinkRefusing`, `AuditLaneBacklogAged`,
  `AuditLaneRefusing`, `AuditLaneAnomaly` (a torn tail alone is a ticket) and `AuditLaneDrainHeld` page;
  `AuditLaneCreated` is a ticket. Each has a promtool test, a `07-release-and-prr.md` entry and a row in
  `docs/ops/runbooks/auth-rbac.md`. The drill, recorded in the alert drill matrix: an audit outage with
  sign-outs and a restart, then a tampered frame. The exit: EX-07's row and the §16.2 sentence that points
  here go, RR-15 narrows, §8.3's session-route sentence is updated, and
  `test_the_exception_and_both_runbooks_name_every_action_the_counter_covers` now requires the lane registry
  to cover every action the counter covers. `auth_audit_outcome_lost_total` and its alerts stay, for records
  that both paths refused.

**`infra/` impact.** No new volume: `lane/` sits on #2615's audit volume (an absolute `CV_AUDIT_WAL_PATH`), and
cv-api creates it, directory `0700` and files `0600`, as uid 10001 on the read-only root filesystem. The key is
provisioned with the other auth keys (runtime environment or secret file; `.env.example` holds a placeholder
only, C-12.2), one key per environment (C-2.11). Alert rules go under `infra/prometheus/alerts/` with promtool
tests. Backups of the audit volume include `lane/`, and a restored lane drains again without duplicates.

## Why not the alternatives

- **(a) Generalise the break-glass journal.** Its file admits only `auth.break_glass_*` (decision R3), has a
  different writer (the offline CLI, with cv-api stopped and `instance.lock` held exclusively) and is folded in
  at boot only. Two writers in one file break R3, and changing its CRC-only frames reopens merged slices of a
  P0 Story (#2119). The lane keeps its patterns: the anchored directory, `O_NOFOLLOW`, entry through
  `ingest()`, and an unusable journal kept as evidence.
- **(c) Reuse the audit WAL.** Its frames carry a CRC, not a MAC; it has no `seq`, class quotas or record
  bound; and it is built for one owner's lock (`AuditWal` is "not safe for concurrent writers"). A second
  instance would still need a keyed envelope, a second cursor and quotas, and changing its format touches the
  C-2.9 main path. The lane reuses its framing idea, its fsync before return and its torn-tail rule.
- **(d) The Postgres `outbox`.** It is down exactly when the WAL is at its cap, and a direct insert bypasses
  `ingest()`.
- **(e) An in-memory queue.** It is lost on restart, so it is not the durable retry rule 2 asks for, and
  #3009's done-means requires surviving a restart.
- **(f) Reserved WAL headroom.** It covers only the cap: a dead flusher or a stopped writer still refuses, so it
  needs a bypass inside `audit/writer.py`, and it does nothing for a stalled WAL.
- **Revoke first, record if possible** (#2914 item 3, option B): rejected by the D2 ruling, because an
  unrecorded revocation breaks C-2.9 and U19.
- **Sink first, journal on refusal:** two paths per action, a mode switch while the journal drains, and no help
  when the WAL stalls rather than refuses.

## Open questions

- **Q1, owner and Security.** Confirm the narrowed RR-15: sign-out, revoke-my-session and reuse containment
  proceed journal-first, while refresh and sign-in stay fail closed. Should the Owner's revocation of another
  user's session (`revokeUserSession`) and a user's disablement (SR-029) join later?
- **Q2, hcl-worker-1.** If #2914's PR C lands after S3, does it call the façade itself? Does F1's logout shape
  (one intent row, outcome rows after) stay as it is on the branch? Is `cv_audit_writer_refused_total{domain}`
  the write-ahead refusal signal you asked for, or do the `503` sites also need a per-action counter?
- **Q3, main-orchestrator.** Are the 32 MiB cap and the `shared` half enough, or should S2's chaos run size
  them first?
- **Q4, E27 (KV-D04).** Separate action ids for the risk-reducing borrow purposes, or a purpose rule in the
  registry?
- **Q5, owner.** Accept the shared volume (the lane does not cover a full or read-only audit volume), or add a
  reserve, such as a ballast file, in a later ticket?
- **Q6, Security.** Give the main WAL the lane's frame MAC in a follow-up ticket?
- **Q7, owner.** Should other outcome records lost without a retry today (for example the ones
  `cv_credential_outcome_audit_failures_total` counts) join the registry, or get a §16.2 exception?

## Validation

- S1 to S4 carry the named tests above. The integration and chaos lanes run in CI, since the author's host
  has no Docker.
- #3009's done-means maps to the slices: the EX-07 rows are written journal-first (S3); a refusing sink and a
  restart lose none of them (S2, S3); EX-07 is removed and RR-15 updated (S4); unit, Postgres-integration and
  chaos tests pass, and the journal's tamper evidence is tested (S1, S2).
- The decision is taken when main-orchestrator records the interim acceptance on #3009 and the owner ratifies
  it (status line).

## References

- `docs/plan/04-security-program.md` §8.1, §8.3, §16.1 (RR-15) and §16.2 (EX-07, from #2914)
- `docs/plan/24-internal-schemas.md` §15.4 and §15.6
- `docs/security/threat-models/e09-auth-rbac.md` §3.6.1 and §3.6.2; `docs/security/threat-models/E27-accounts.md`
  KV-D04 and AC-27
- `docs/plan/27-adrs/ADR-0009-secrets-and-key-management.md` Amendment 4;
  `docs/plan/27-adrs/ADR-0010-auth-and-rbac.md`
- `audit/writer.py`, `audit/wal.py`, `audit/journal.py`, `audit/service.py`, `audit/models.py`,
  `admin/breakglass.py`, `api/sessions.py`
- #3009, #2914, #2267, #892, #2119, #2615, #2251, #2872
