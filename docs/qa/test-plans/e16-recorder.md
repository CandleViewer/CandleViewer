# E16 Recorder, retention and disk budget: black-box test plan

Ticket: E16-Q01 (#404). Status: v1.0, a draft for review by the QA lead, one backend engineer and one frontend engineer (the
ticket's DoD). It holds the conventions, the scope, the test matrix, the cases for US-REC-001 to US-REC-008 and the E16-X01 abuse
cases, the time-control strategy, the destructive-test protocol, the fixture catalogue, the entry and exit criteria with the
regression subset, the traceability and the open questions. E16-Q02 to E16-Q06 execute it; this plan contains no code.

## 0. Conventions

- **Expectations come from the specification, not the implementation.** Each case cites its source:
  - `US-REC-nnn/k` is scenario k of that story in `docs/plan/11-user-stories.md` §22;
  - `S01` to `S05` and `T02` to `T10` are the Gherkin of E16-S01 to S05 and E16-T02 to T10 in
    `docs/plan/backlog/E16.json`; `T06.6` is E16-T06's sixth scenario, in ticket order;
  - `22` is `docs/plan/22-api-openapi.yaml`, cited by operation id; `23` is `docs/plan/23-ws-protocol.md`
    (§6.2.2, §15.8);
  - `D02` to `D05` are `docs/design/E16/E16-D02.md` to `E16-D05.md`; `D06` is `E16-D06.md` (its §8 T2 rows,
    §12 C, G and Q rows, §16.4 code routing and §20.3 frozen set); T2 is a gated control with a visible reason, T4 a
    server refusal shown at the point of action;
  - `TM` is `docs/security/threat-models/e16-recorder.md` (abuse cases `AC-01` to `AC-15`), `ADR-15` is
    ADR-0015 and `RB` is `docs/ops/runbooks/recorder-retention.md`.
- **Where the ticket text and the merged design differ**, the case follows the merged design: D06 §12.1 C-r to
  C-z record each difference, the orchestrator ruled "merged wins" (D06 R374 BQ-24), and the E16-D06 hand-off
  comment on #404 corrects this ticket's text. Where merged sources differ from each other, the case says so,
  the difference is a row in section 10, and the case is marked **blocked on** its owner. Nothing is guessed.
- **Environment:** the seeded recorder stack of section 6: a keyless testnet or staging profile, the
  fixture-replay feed, a mock archive host and a mock exchange. Never live (`02` §8, `03` §17). No network, no
  real key, no production data: every credential, TOTP seed and bearer a run uses is synthetic and made per run,
  and no host, key, account, user name or private record id appears in a step, a fixture or an evidence file.
- **Case ids:** `E16-Q01-Cnn`. The line under the id names the layer (`03` §2: `unit`, `contract`,
  `integration`, `e2e`, `perf`, `security`, `a11y`), the role and state it covers (section 2) and what it
  mirrors. **[R]** joins the regression subset and **[R2]** the subset every later R2 epic that reads recorded
  data runs (section 7); **[F]** marks a failure path (the ticket's AC: every Must story has one);
  **blocked on** an owner means that owner must answer first.
- **Oracles, in the ticket's order:** an exact row-and-byte manifest (section 5) > an API response assertion > a UI assertion; a
  UI-only oracle is used only on presentation cases, and the case says so. Every case also names a secondary oracle, an audit
  action (a name `22` declares, else the registry's) or a metric from the E16 tickets' Observability sections: a pass whose secondary
  record is missing fails the case, and a read-only case says "none (a read)".
- **Time and destruction:** sections 4 and 5 bind every case. No case sleeps or relies on more than 5 minutes
  of real elapsed time, and every case that can delete runs on the scratch dataset only.

## 1. Scope and references

**In scope:** the recorder's effective set and auto-record triggers (E16-T02), the writer, WAL spill and
recovery (T03), sessions, gaps and coverage (T04), the nightly roll-off and compaction (T05), retention, the
dry run and the purge (T06), the disk budget and its ladder (T07), the recording REST surface and the
`recorder` WS topic (T08), the alerts and runbook (T09) and the archive import (T10), as seen through SCR-140,
SCR-141, SCR-142, SCR-047, SCR-151 and the REC chip's text on SCR-041, SCR-100 and SCR-103. **Out of scope:**
automation code, the perf and chaos scripts and the a11y audit (section 8).

**Read first:** `03` §9, §11 and §16; `04` §5.8 and §7.2.2 rows 8 to 9c; ADR-0015; `22` tag `recording` and
`/admin/recorder/*`; `23` §6.2.2; D02 to D06; `14` SCR-140 to SCR-142, SCR-047 and SCR-151; `TM`; the E16-X02
record `docs/security/reviews/e16-recorder-review.md` (verdicts only); `RB` and `docs/ops/runbooks/recorder.md`; the
E16-K01 note `docs/plan/notes/e16-storage-measurement.md`.

**Deviations from the ticket** (repeated in the PR): the ticket's path `docs/qa/test-plans/` is new, since plans
live in `docs/qa/` and `qa/plans/` today (a reviewer may relocate it); five scenarios follow the merged design's
reading, not the ticket's: S01.7 (Viewer sees status), S01.8 (polling), S02.1 (the notice), S03.3 (the
client-side inversion check) and S04.7 (a five-minute stale limit), for the reasons in D06 C-r, C-t, C-u, C-w and
C-y (section 10); and the matrix's "disk-warning" covers ladder levels 1 and 2, "disk-critical" level 3 (D02 §3).

## 2. The test matrix

The ticket's dimensions: **role** OWNER, MANAGER, VIEWER (view-as is a session state, C57); **action** view, add, stop, pin,
retention change, purge, compact, import; **state** empty (no rows), recording (`level` 0, a row recording), degraded (a row
`degraded` or gaps in 24 h), disk-warning (ladder levels 1 and 2, D02 §3) and disk-critical (level 3, the write gate closed).

**2.1 Role by action.** A cell is the server's answer (`22` `x-rbac`; `04` §7.2.2 rows 8 to 9c); a case asserts that answer and never a
role name (D06 C-r). "Seed" means the RBAC seed on `main` grants MANAGER `recording:write` while D02 decision 4 holds it owner-only
(OQ-2): the case asserts what the server answers. The admin routes are hidden and `404` for MANAGER and VIEWER (D02 §7).

| Action                | Operation (permission)                                               | Step-up                                    | OWNER | MANAGER                    | VIEWER               | Cases           |
| --------------------- | -------------------------------------------------------------------- | ------------------------------------------ | ----- | -------------------------- | -------------------- | --------------- |
| view                  | the `recording` GETs (`recording:read`), `getDataCoverage`, WS topic | none                                       | yes   | yes, restricted view       | yes, restricted view | C01, C07, C48   |
| add                   | `addRecordedSymbol` (`recording:write`)                              | `recorder` if `pinned` or `retention_days` | yes   | seed                       | `403`, audited       | C02, C03, C54   |
| stop                  | `removeRecordedSymbol`                                               | none                                       | yes   | seed                       | `403`, audited       | C04 to C06, C54 |
| pin                   | `pinRecordedSymbol`, `updateRecordedSymbol`                          | `recorder`                                 | yes   | seed                       | `403`                | C14, C54        |
| retention, one symbol | `updateRecordedSymbol` (`retention_days`)                            | `recorder`                                 | yes   | seed                       | `403`                | C14, C54        |
| retention, global set | `setRetentionPolicies` (`admin:write`)                               | `recorder`                                 | yes   | `403`, audited             | `403`                | C15 to C20, C54 |
| purge                 | `purgeRecordedData`                                                  | `recorder_purge`, no grace                 | yes   | `403`, owner-only, audited | `403`                | C23, C24, C54   |
| compact               | `compactRecorder`                                                    | none                                       | yes   | seed                       | `403`                | C28, C54        |
| import                | `importTradeArchive`                                                 | none                                       | yes   | seed                       | `403`                | C42 to C47, C54 |

**2.2 Action by state.** A cell names the cases that cover it. **n/a**: no such cell (no row to act on). **same**: no source states a
different answer, so the recording column covers it. **none**: no source states the result, so nothing is asserted.

| Action           | empty | recording     | degraded | disk-warning | disk-critical |
| ---------------- | ----- | ------------- | -------- | ------------ | ------------- |
| view             | C01   | C07, C31, C48 | C34, C40 | C32          | C33           |
| add              | C02   | C03           | same     | none         | C33           |
| stop             | n/a   | C04 to C06    | same     | same         | same          |
| pin              | n/a   | C14           | same     | C12          | C33           |
| retention change | C20   | C14 to C19    | same     | C12          | C33           |
| purge            | none  | C23, C24      | same     | same         | C33           |
| compact          | none  | C28           | same     | same         | C33           |
| import           | C42   | C43, C45      | same     | C47          | C47           |

## 3. Cases by user story

Each case starts from a fresh seed of the fixtures it names (section 6) and runs as OWNER unless its header says
otherwise. A case is: preconditions, steps, expected, oracle. A tester who did not write the plan can run any case
from sections 4 to 6 alone. `M(pre)` and `M(post)` are the manifests of section 5.

### 3.1 US-REC-001 Recorded-symbols list (Must)

**E16-Q01-C01 Fresh install records nothing and says so [R]** (`e2e`, `contract`; OWNER · empty; mirrors US-REC-001/1, S01.1, T02.1,
T08.2; D02 §3 `empty`)

- Pre: FX-EMPTY.
- Steps: read `listRecordedSymbols` and `getRecordingStatus`; take `M(pre)`; open `/admin/recorder`.
- Expected: `200` with `items: []` and `symbols: []`, never `404`; no subscription requested and no session; the page shows "Nothing
  is recorded yet", the default statement and one primary action "Record a symbol"; the disk card reads "Nothing recorded · 0 GB of
  {cap} GB" with no projection.
- Oracle: `M(pre)` holds no row for any symbol > the two reads > the page text (a presentation check). 2nd: `recorder_symbols_active`
  is 0 and no `recorder.start` record exists.

**E16-Q01-C02 Add starts recording within 5 s and persists the streams [R]** (`e2e`, `integration`; OWNER · empty to recording;
mirrors US-REC-001/2, S01.2, T02.2; D02 §6.1)

- Pre: FX-EMPTY; the feed replays the recorded BTCUSDT tape and book windows.
- Steps: add BTCUSDT in the dialog with its defaults (four streams, depth 200, retention 30 d); watch the grid; replay 10 minutes of
  event time; send the same add again.
- Expected: `201`; within 5 s the row goes `starting` to `recording` and shows `started_at` in UTC; trades, book deltas and tickers
  rows reach the hot tier and one session opens; the repeat answers `200` with the same row and opens no second session. The corpus
  holds no recorded liquidation frames (FX-G2), so that leg asserts the active subscription (`streams` lists it) only.
- Oracle: `M(post)` per-stream row counts equal the replayed frames' distinct keys > `listRecordedSymbols` and `listRecordingSessions` >
  the grid. 2nd: one `recorder.start`; `recorder_start_latency_seconds` under 5 s.

**E16-Q01-C03 Add refusals leave nothing behind [F]** (`contract`, `e2e`; OWNER · recording; mirrors T08.1; `22` `addRecordedSymbol`;
D02 §6.1; D06 §16.4 rows 2, 4, 5)

- Pre: FX-A, and a stack whose `CV_RECORDER_MAX_SYMBOLS` equals the number of active rows.
- Steps: add an unlisted symbol; add past the cap; add with `pinned: true` and no elevation; add with an unknown body field; add with
  a body over 4 096 bytes; read the button at the cap.
- Expected: `422 validation_failed`; `422 recorder_symbol_limit`; `403 step_up_required`; `422 validation_failed`; `413`; no row, no
  session and no `recorder.start`; a malformed call spends none of the 30-a-minute write budget (TM R-D7). At the cap "Start
  recording" is `aria-disabled` with `recorder.symbol_cap` ("The symbol limit is reached.") in the DOM at mount (D06 T2-02).
- Oracle: status and code per call > `M(pre)` equals `M(post)` > the button's state (a presentation check). 2nd: only the step-up
  refusal writes a record (`auth.step_up_required`); `http_requests_total{route}` counts all.

**E16-Q01-C04 Stop confirms first, lingers, and keeps its data [R]** (`e2e`; OWNER · recording; mirrors US-REC-001/3, S01.5, T08.3;
D02 §6.2, §4.1)

- Pre: FX-A (manual, no chart open); `CV_RECORDER_AUTOSTOP_GRACE_S` set to 90 (section 4).
- Steps: press Stop on ETHUSDT; read the dialog; press "Stop recording"; read the row; wait out `linger_until`.
- Expected: no request before the final press; the dialog says history stops accruing and existing data is kept per the retention
  policy and stays replayable, with "Keep recording" as the default button; `204`; within 5 s the row reads lingering with
  `linger_until`; at the grace end the session closes (`ended_at`) and the row reads "Stopped {date} · gone by {date}"; every recorded
  row stays readable.
- Oracle: `M(pre)` equals `M(post)` (no file or row of ETHUSDT removed) > `listRecordedSymbols` and `listRecordingSessions` > the
  dialog text. 2nd: one `recorder.stop`; `recorder_autostop_total` rises once, after the grace.

**E16-Q01-C05 Stop is refused while a trigger holds the symbol [F]** (`e2e`, `contract`; OWNER · recording; mirrors S01.4, T02.4; D02
§6.3; D06 T2-01; `22` `removeRecordedSymbol`)

- Pre: FX-A with a chart open on ETHUSDT. The open-position variant needs FX-E: **blocked on E29-T06** (OQ-4).
- Steps: read the row's `refusal`; press Stop, Enter and Space; send the `DELETE` without `force`, then with `force=true`; confirm a
  stop on a frame that lags the server's state.
- Expected: `refusal: chart_open`; Stop is `aria-disabled` with the lock and the reason echoed once, politely
  (`recorder.stop_blocked.chart_manual`, "Stop is available once the last chart closes."; `chart_auto` for an auto row;
  `position_auto`, "Recording continues while a position is open.", for the position variant); the plain call answers `409 conflict`;
  `force=true` ends the manual reason, the symbol keeps recording for its chart and its pin is untouched; a lagging confirm answers
  `409` as T4 at the confirm, nothing is re-sent and the confirm stays `loading` until the next frame (D02 §6.3).
- Oracle: statuses > `M` (rows keep arriving) > the reason text. 2nd: `recorder.stop` only for the forced call.

**E16-Q01-C06 Stop never deletes: a pinned row keeps its pin and `purge_data` is refused [F]** (`contract`, `integration`; OWNER ·
recording; mirrors T08.3, T08.4; `22` `removeRecordedSymbol`, `pinRecordedSymbol`; D06 §16.4 row 7)

- Pre: FX-C (pinned, recording).
- Steps: `DELETE` the pinned symbol; `DELETE` it with `purge_data=true`; unpin the stopped row.
- Expected: `204` and the row lists `stopped` with `pinned: true`, its data protected; `purge_data=true` answers
  `422 validation_failed` (rule `use_purge_route`) and deletes nothing; unpinning the stopped row removes the row and retention
  governs its data from then on.
- Oracle: `M(pre)` equals `M(post)` after each of the first two calls > the rows > the UI. 2nd: `recorder.stop`; no `retention.purge`
  and no `data.deleted` record.

**E16-Q01-C07 Non-owners read a restricted view and cannot reach the admin routes [F]** (`security`, `e2e`; MANAGER, VIEWER ·
recording; mirrors S01.7, S02.3, S03.7, AC-07; D02 §7; `23` §6.2.2; D06 §20.3 (vii))

- Pre: FX-A and an open position on a second symbol (FX-E; that half is **blocked on E29-T06**, OQ-4).
- Steps: as each role read `listRecordedSymbols` and `getRecordingStatus`, subscribe to `recorder`, send a bad cursor and an unknown
  id, and open `/admin/recorder` by link.
- Expected: `role_restricted: true`; no symbol recorded only for an open position and no `position_open` as a reason or refusal; a
  symbol absent from the set is unknown, never "not recording"; `400 invalid_cursor`; no body holds a path, mount point or OS text
  (logical ids only); the route answers the 404 surface and no "Admin" item exists; the REC chip reads "Recording status restricted"
  where the server marks it.
- Oracle: bodies and the WS frame scanned for `/`, drive letters and host text > the route's answer > the UI. 2nd: `rbac.denied` for
  each refused write; the permission-failure metric.

**E16-Q01-C08 Socket loss shows stale, never live [F]** (`e2e`; OWNER · recording; mirrors S01.8; D02 §3.1; D06 Q-04)

- Pre: FX-A; `/admin/recorder` open.
- Steps: close the WS and refuse its reconnect for 10 s; move the browser clock past 2 s; let it reconnect.
- Expected: after 2 s without a `recorder` frame the summary reads "Status stale since {hh:mm:ss} UTC" and each row carries a "stale"
  tag with its last words; no figure reads as live; controls stay enabled, since the server decides a press; the first frame after the
  reconnect clears the state. The ticket's polling fallback is not designed (D06 Q-04): that half is **blocked on E16-D02's owner**
  (OQ-8).
- Oracle: UI (a presentation case) > the harness's timestamped frame log. 2nd: `ws_topic_subscribers{topic="recorder"}` drops, then
  recovers.

### 3.2 US-REC-002 Auto-record triggers (Must)

**E16-Q01-C09 A chart records only after the dwell, silently and labelled [R]** (`e2e`, `integration`; OWNER · empty to recording;
mirrors US-REC-002/1, T02.3, S01.3, S02.1, S02.2, S02.5; D02 decision 2, §5.1, §5.4; D05 §4)

- Pre: FX-EMPTY; `CV_RECORDER_AUTOSTART_DELAY_S` 20 (section 4); the hosts SCR-041, SCR-100 and SCR-103.
- Steps: open a chart for SOLUSDT and close it at 8 s; read the set after 40 s. Reopen it past the dwell; read the grid, the three REC
  chips, the Why? popover and SCR-047's status line.
- Expected: the first visit never enters the set; the second adds a row with reason `chart_open`, tag "Auto: chart" and a Why? popover
  naming the trigger; SCR-047 counts down "Recording starts automatically in {m:ss}", then reads "Recording started {hh:mm} UTC" once;
  the REC chip states its state in text on all three hosts, in agreement, from one subscription; no toast or notice appears (decision
  2: the chip and its Stop are the disclosure, so S02.1's notice is not built: OQ-8).
- Oracle: `M` has no SOLUSDT row after the first visit > `listRecordedSymbols` (`reason: chart_open`) and `getRecordingStatus.policy` >
  the chip texts. 2nd: `recorder.start` (reason `chart_open`); `recorder_autostart_total` +1.

**E16-Q01-C10 An open position records at once and cannot be released; blocked on E29-T06** (`integration`; OWNER · recording;
mirrors US-REC-002/2, T02.4; D02 §4.1 "Auto: position"; OQ-4)

- Pre: FX-E.
- Steps: open a position on XRPUSDT; read the set in the same tick; try to stop it; close the position and wait out the grace.
- Expected: XRPUSDT enters the set in that tick with reason `position_open`, cannot leave while the position is open (C05's
  `position_*` reasons), and after the close and the grace stops and falls under the auto policy.
- Oracle: `listRecordedSymbols` > `listRecordingSessions`. 2nd: `recorder_symbols_active{reason="position_open"}`.

**E16-Q01-C11 The grace keeps one session, and a manual entry survives trigger loss [R]** (`integration`; OWNER · recording; mirrors
US-REC-002/3, T02.5, T02.6; D02 §4.1)

- Pre: FX-EMPTY with dwell 20 s and `CV_RECORDER_AUTOSTOP_GRACE_S` 90; FX-A for the manual half.
- Steps: auto-record ETHUSDT from a chart; close it; reopen it 30 s later; later close it and wait out the grace. Then close the chart
  of a manual symbol.
- Expected: reopening inside the grace: recording never stopped, no gap row and the original session stays open; after the grace with
  no trigger left the session closes and the row falls under the auto policy (unpinned, default days); the manual symbol stays in the
  set with reason `manual`.
- Oracle: `listRecordingSessions` (one session id across the reopen) and an empty gap list > `M` (rows continuous) > the row text
  "Recording · stops in {n} min". 2nd: `recorder_autostop_total` rises once, only after the grace.

**E16-Q01-C12 Auto-record is refused at the cap and under disk pressure; the explicit list is not [F]** (`integration`; OWNER ·
disk-warning; mirrors T07.3, T07.6, AC-02; US-REC-002 NFR; D02 §3 `paused`, §4.1; D05 §4)

- Pre: FX-A recording; the cap sized so seeded bytes are 91 % of `cap_bytes` (level 2, section 4); a second run at `max_symbols`.
- Steps: open and hold a chart for an unrecorded symbol; read `getRecordingStatus`, the grid, the REC chip and SCR-047.
- Expected: no auto-record starts; the entry is `idle` with `refusal: disk_pressure` (`symbol_cap` in the second run), the row reads
  "Not recording: disk nearly full" ("…: 20-symbol limit reached"), SCR-047 gives the same cause and the chip has no menu; a warning
  event is raised; manual symbols keep recording without a gap; `accelerate_retention` is true, unpinned rows read "30 d → 15 d
  (accelerated)" and pinned data is untouched.
- Oracle: `M` (no rows for the refused symbol, rows still arriving for FX-A) > `getRecordingStatus` and `getStorageUsage` > the text.
  2nd: `recorder_disk_pressure_level` is 2; `RecorderDiskPressureAutostop` fires.
- Variant b, hysteresis: move the cap so the used share runs 89, 91, 89, 91 percent, then 84, attempting a chart-open each time. The
  refusal engages once at 91 %, holds at 89 % and releases only below 85 % (the `level` series is the oracle).

**E16-Q01-C13 Scripted chart-opening cannot exhaust the disk or forge a trigger [F]** (`security`; VIEWER · recording; mirrors AC-01,
AC-02; TM R-S1, R-D2)

- Pre: FX-EMPTY with dwell 5 s; the registry's instrument list.
- Steps: as VIEWER subscribe a chart for a symbol absent from the registry; then open 200 distinct registry symbols within 5 minutes
  and hold them past the dwell.
- Expected: the unknown symbol is rejected with no row and a rejection metric; at most 20 symbols auto-record and the rest stay
  live-only with the UI note; an alert fires; `level` does not rise because of the run; triggers come from the authenticated
  subscription, never a client-supplied flag.
- Oracle: `M` (distinct recorded symbols at most the cap) > `listRecordedSymbols` > `getStorageUsage.level`. 2nd:
  `recorder_symbols_active{reason="chart_open"}` holds at the cap.

### 3.3 US-REC-003 Retention policy and pinning (Must)

**E16-Q01-C14 Pin and unpin are pessimistic and need a fresh step-up [R]** (`e2e`, `contract`; OWNER · recording; mirrors
US-REC-003/2, S03.5; D02 §6.4; D06 §20.3 (iii); `22` `pinRecordedSymbol`)

- Pre: FX-A (unpinned) for the pin; FX-C (pinned) for the unpin.
- Steps: switch Keep forever on, type the symbol, submit, cancel the step-up once, then complete it; switch it off on FX-C with the
  typed symbol and the step-up; change ETHUSDT's retention from 30 to 7 days in the row detail (the same flow, D02 §6.4).
- Expected: no request before the typed confirm passes; `403 step_up_required` (`action_class: recorder`), then the client re-sends
  the held request once with the same Idempotency-Key; Esc, expiry or a third invalid code drops it ("Not sent", inputs kept); on
  success `pinned: true`, `retention_days: null`, retention "Forever", and the switch moves only after the server answers. Unpin and
  the shortening: the dialog states how many GB recorded before which date become eligible at the next retention run and that nothing
  is deleted now; after the unpin the pin is off and `retention_days` is the default (30).
- Oracle: statuses and one stored change > `M(pre)` equals `M(post)` after the unpin > `getStorageUsage.symbols[].pinned` > the dialog
  text. 2nd: one audit record per change with actor, before and after (OQ-11); `auth.step_up_granted`.

**E16-Q01-C15 Pinned data is never deleted, and the report lists it protected [R] [R2] [F]** (`integration`; OWNER · recording;
mirrors US-REC-003/2, T06.2, S03.4; `22` `setRetentionPolicies`; D03 §9)

- Pre: FX-C (data past every horizon) and FX-A; the set stores trades, 7 d, `drop`.
- Steps: take `M(pre)`; `PUT` the set with `apply_now=true` and poll the job; take `M(post)`; then `PUT` a set with
  `applies_to_pinned: true`.
- Expected: FX-C's delta is empty and the pass report lists it protected with reason `pinned`; SCR-141's pinned list shows its size,
  "Exempt (pinned)" and zero bytes eligible; `applies_to_pinned: true` answers `422 retention_invalid_policy` and stores nothing.
- Oracle: FX-C's delta is exactly empty and every other delta equals the plan > the `retention.run` report > the list. 2nd:
  `retention_protected_total{reason="pinned"}` rises; `retention.change` for the first `PUT`.

**E16-Q01-C16 The 30-day horizon deletes exactly the eligible partitions [R] [R2]** (`integration`; OWNER · recording; mirrors
US-REC-003/1, T06.1; `22` `setRetentionPolicies`; RB "How it works")

- Pre: FX-A with cold partitions dated T-35 to T-8 days, none at T-30 (the boundary); the set stores trades, 30 d, `drop` for ETHUSDT (an explicit row, so the
  horizon is the row's days); the scheduler on.
- Steps: take `M(pre)`; `PUT` with `apply_now=true`; poll the job every 2 s; take `M(post)`; read the audit.
- Expected: trades partitions dated T-35 to T-31 (five) are deleted and T-29 to T-8 kept; freed bytes equal the five partitions'
  manifest sizes; no other stream, symbol or relational row is touched; the next prune time reads "Next retention run: daily at 03:00
  UTC".
- Oracle: `M(pre)` minus `M(post)` equals exactly the five partitions > `getJob` > the footer. 2nd: one `data.deleted` per partition,
  then `retention.run` start and end; `retention_deleted_bytes_total` equals the delta.
- Variant b, the default policy with no explicit row: **blocked on E16-T06's owner** (OQ-1).

**E16-Q01-C17 A preview deletes nothing; its API half is blocked on E16-S03** (`e2e`, `integration`; OWNER · recording; mirrors
US-REC-003/3, T06.3, T06.7, S03.1; D03 §5, §12; OQ-6)

- Pre: FX-A and FX-C; in the editor change trades from "Move to Parquet after 30 d" to "Delete after 7 d".
- Steps: press Preview changes; read the panel; take `M(pre)` and `M(post)`; leave without applying.
- Expected: the panel lists per symbol and stream the range and size that become eligible, the pinned symbol as "Exempt (pinned)" with
  zero bytes, and the consequence sentence (stream, scope, dates, size, timing); nothing is applied and the stored set is unchanged;
  the volume is byte-for-byte identical. Until D03-G1's route is served the size is a client estimate ("about {size}"); the server's
  dry-run report (T06.3) is **blocked on #485**.
- Oracle: `M(pre)` equals `M(post)` for every file hash and row count > `listRetentionPolicies` unchanged > the panel. 2nd: no
  `data.deleted` and no `retention.change`.

**E16-Q01-C18 Destruction needs the preview, the typed word and the step-up, in that order [R] [F]** (`e2e`; OWNER · recording;
mirrors S03.2; D03 §5; D02 §6.4)

- Pre: as C17.
- Steps: press Apply before and after the preview renders; leave the typed field empty, then wrong ("trade"), then `trades`; at the
  step-up press Esc, then repeat and complete it.
- Expected: Apply keeps the validity look and sends no request until the preview has rendered for the current diff and the typed word
  matches exactly (trimmed, case-sensitive); a later edit resets the preview; Enter in the typed field does nothing; Esc at the
  step-up drops the request ("Not sent", inputs kept, nothing stored); on success the footer reads "Retention policy saved. Audited as
  retention.change."
- Oracle: the request log (no `PUT` before the match, one after, with the held request's key) > `listRetentionPolicies` > the text.
  2nd: one `retention.change`, written before the set is stored.

**E16-Q01-C19 Apply schedules rather than blocks [R]** (`e2e`, `contract`; OWNER · recording; mirrors S03.6; `22`
`setRetentionPolicies`; D03 §8)

- Pre: FX-A; the scheduler on, then off.
- Steps: apply a lengthening without `apply_now`; apply a reduction with `apply_now=true`; press Apply now again while it runs; with
  the scheduler off apply now.
- Expected: `200`, "takes effect at the next nightly sweep", nothing deleted yet; with `apply_now` a `retention_sweep` job shows
  "Retention run queued", "running · 42 %" and "succeeded", one polite announcement per terminal state; a second run answers
  `409 job_running` ("A retention run is already running." as T4); with the scheduler off `apply_now` answers `409 conflict` and
  stores nothing.
- Oracle: statuses and the `getJob` state sequence > `M` equal right after the `PUT` > the footer. 2nd: `retention.change` before the
  store; with the audit writer down `503 audit_unavailable` and nothing stored.

**E16-Q01-C20 Server refusals of a policy render at the point of action [F]** (`e2e`, `contract`; OWNER · empty and recording; mirrors
S03.3; D03 §7; D06 §16.4 rows 2, 8)

- Pre: FX-EMPTY, then FX-A.
- Steps: set bars to outlive trades; send `downsample`, `pin` and an unknown field; type 0, 4000 and 7.5 days.
- Expected: `422 retention_invalid_policy` for the derived-stream rule, `downsample` and `pin`; `422 validation_failed` for the
  unknown field; nothing stored; after the press the error summary reads "Bars can't be deleted before the ticks they came from are
  kept — adjust the tiers." with the controls enabled (no client pre-check: D06 C-u); the field errors "Keep at least 1 day.", "At
  most 3650 days (10 years).", "Whole days only." keep Apply in its validity look.
- Oracle: status, code and the stored set > the text. 2nd: a refused call writes no `retention.change`.

**E16-Q01-C21 Data under a replay lease is skipped and retried [R] [R2] [F]** (`integration`; OWNER · recording; mirrors T06.4, AC-12;
US-REC-003 NFR; RB step 3; TM R-D5)

- Pre: FX-A as C16; a replay session over one eligible partition (`createReplaySession`).
- Steps: run the sweep and read the report; destroy the session; run the sweep again.
- Expected: the leased partition is skipped with reason `leased` and logged, its files are byte-identical after pass one and every
  other eligible partition is deleted; after the session ends, pass two deletes it. The TTL half (a lease never outlives its TTL,
  AC-12) needs the recorder's wall clock: **blocked on OQ-3**.
- Oracle: the leased partition's hash equal after pass one and absent after pass two > the `retention.run` report > the session state.
  2nd: `retention_protected_total{reason="leased"}`.

**E16-Q01-C22 An interrupted reaper resumes without a second deletion record [F]** (`integration`; OWNER · recording; mirrors T06.5;
RB "How it works")

- Pre: FX-MANY (ten symbols with eligible partitions).
- Steps: start a sweep; stop the API after three symbols are done; restart; let the next pass run.
- Expected: the next pass resumes from the checkpoint, does not re-scan the three finished symbols and writes no second `data.deleted`
  for a finished item; the final delta equals the full plan.
- Oracle: `M(pre)` minus `M(post)` equals the plan > the count of `data.deleted` equals the partitions deleted. 2nd: `retention.run`
  (partial, then end); `retention_last_success_timestamp` moves.

**E16-Q01-C23 Purge refusals delete nothing, and a bad body spends no code [F]** (`contract`, `security`; OWNER, MANAGER, VIEWER ·
recording; mirrors T06.6, T08.5, AC-04, AC-05, AC-13; `22` `purgeRecordedData`; D06 §16.4)

- Pre: FX-A and FX-C; a valid body (symbol, `confirm_symbol`, `reason`, `before`) and a fresh synthetic step-up per accepted call.
- Steps and expected, one row each; in every row `M(pre)` equals `M(post)` and no job starts:

| Row | Input                                                           | Expected                                                                         |
| --- | --------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| a   | MANAGER, valid body                                             | `403` owner-only, audited, before the body is read or a step-up is asked         |
| b   | VIEWER                                                          | `403`                                                                            |
| c   | OWNER, valid body, no elevation                                 | `403 step_up_required`, `action_class: recorder_purge`                           |
| d   | `confirm_symbol` "BTCUSD" for BTCUSDT                           | `422 purge_confirmation_mismatch`; no code spent, the body is decided first      |
| e   | empty symbol or `*`                                             | `422`                                                                            |
| f   | pinned symbol without `include_pinned`                          | `422 retention_pinned_refused`                                                   |
| g   | `before` later than the server's clock                          | `422 validation_failed`, rule `before_in_future`, the server's time in `message` |
| h   | the audit write forced to fail                                  | `503 audit_unavailable`, no job                                                  |
| i   | same key, another `before`; same key and `before`, another body | `409 idempotency_key_reuse`; `422 idempotency_key_reused`                        |
| j   | a purge while one runs                                          | `409 job_running`                                                                |

- Oracle: status and code per row > `M(pre)` equals `M(post)` > the audit. 2nd: `rbac.denied` for rows a and b; no `retention.purge`
  for any row.

**E16-Q01-C24 An accepted purge deletes exactly its window, audited first [R]** (`integration`, `e2e`; OWNER · recording; mirrors
T06.6, AC-06; US-REC-003; `22` `purgeRecordedData`; D02 §6.5; D06 §20.3 (ii), (viii))

- Pre: FX-A, FX-B and FX-C loaded; the target is ETHUSDT with `before` at 00:00 UTC of day T-20 (a day boundary).
- Steps: open the dialog from the card; fill symbol, `before`, reason and the typed symbol; complete a fresh step-up; poll the job;
  take `M(post)`; read the audit and verify its chain.
- Expected: the typed field mounts empty and the body states the window, the size and "It cannot be undone"; `202` with a `job_id`;
  `retention.purge` with the exact window, partitions, rows and bytes exists before the job starts; the job ends `succeeded` ("Purged
  {size} of ETHUSDT data"); the delta is exactly ETHUSDT's cold partitions dated T-35 to T-21; data at or after `before`, other
  symbols, pinned data and the session, gap and audit rows are untouched; hot day partitions shared with other symbols are skipped
  (`shared_partition`) and left to the roll-off; the audit chain verifies.
- Oracle: `M(pre)` minus `M(post)` equals the window > `getJob.result` (partitions, bytes) > the dialog and outcome text. 2nd:
  `retention.purge` (write-ahead, then closing), one `data.deleted` per partition, `auth.step_up_*`.

**E16-Q01-C25 Destructive actions on a symbol with an open position; blocked on E29-T06 and the `22` owner** (OQ-4; mirrors D06 Q-07):
`22` declares no open-position check on the purge route and D02 keeps positions recording at level 3, so no source states what a
purge, a sweep or a compaction does to a symbol with an open position. The case runs on FX-E and records the observed result as "not
specified", never as a pass, until the owners answer.

### 3.4 US-REC-004 Hot and cold tier management (Must)

**E16-Q01-C26 The roll-off archives, verifies, then drops [R] [R2]** (`integration`; OWNER · recording; mirrors US-REC-004/1,
US-REC-004/3, T05.1, T05.2; RB; `21` §6)

- Pre: FX-A with hot partitions past the hot window; the scheduler on; one pass on demand (section 4).
- Steps: take `M(pre)`; trigger the pass; take `M(post)`; read coverage. Variant b: fail the verify step (OQ-13).
- Expected: Parquet files exist at the documented layout; per symbol-day the Parquet row count and checksum equal the hot partition's
  before it drops, and the watermark advances; coverage splits at it (`parquet` older, `questdb` newer). Variant b [F]: the hot day is
  kept, the partial file quarantined, an alert raised and the pass retried with backoff.
- Oracle: `M` (hot `pre` equals cold `post` per symbol-day; hot `post` absent) > `getDataCoverage`. 2nd:
  `recorder_rolloff_bytes_total{stream}`; variant b `recorder_rolloff_failures_total`. Variant b is **blocked on E16-T05's owner**.

**E16-Q01-C27 A query across both tiers is seamless [R] [R2]** (`integration`; OWNER · recording; mirrors US-REC-004/2, T05.3)

- Pre: FX-A after C26, and a 14-day window that straddles the watermark.
- Steps: read a recorded-data operation over it (`getProfiles`, or any read that returns `DataMeta`); read both tiers from `M(post)`.
- Expected: one merged result in order, no duplicate key and no missing row at the seam; `meta.sources` lists `questdb` and `parquet`,
  and the query detail shows the tiers used.
- Oracle: the result's key set equals the union of both tiers' manifest rows > `meta.sources`. 2nd: none (a read).

**E16-Q01-C28 Compaction merges without deleting and defers leased partitions [F]** (`integration`; OWNER · recording; mirrors S04.5,
T05.4; `22` `compactRecorder`; D04 §6; D06 C-d)

- Pre: FX-A with many small cold files, and a replay session reading one cold partition.
- Steps: `POST /admin/recorder/compact` with an Idempotency-Key and poll; repeat while it runs; repeat the key with another body.
- Expected: `202`; the leased partition is deferred and logged, the rest complete; per symbol-day the row count is equal before and
  after and the file count falls (merge only); `409 job_running` and `422 idempotency_key_reused` for the repeats; the card shows
  queued, running and "Compacted at {hh:mm} UTC" once, with no cancel (D04-G10).
- Oracle: `M` (rows per symbol-day equal; the leased partition's files byte-identical) > `getJob`. 2nd: `recorder.compact`.

**E16-Q01-C29 Raw book data past 180 days is downsampled; the label is blocked** (`integration`; OWNER · recording; mirrors T05.5;
`21` §7; OQ-10)

- Pre: FX-C with `orderbook_delta` partitions older than 180 days.
- Steps: run a roll-off pass; take `M(post)`; read coverage over the range.
- Expected: raw partitions are replaced by 1 s book snapshots and the downsample is recorded; the coverage label "downsampled" is
  **blocked on the E16-T05 and E16-T08 owners**, since `22` `DataCoverage` has no such field.
- Oracle: `M` (raw partition absent, 1 s snapshot partition present). 2nd: `retention.downsample`.

**E16-Q01-C30 SCR-142 never shows an unreachable tier or an old sample as live [F]** (`e2e`; OWNER · degraded; mirrors S04.4, S04.7;
D04 §5)

- Pre: FX-A with the Parquet root made unreadable on the scratch volume (nothing is deleted); SCR-142 open.
- Steps: press Retry on the failed card; restore the root; press Retry. Then move the browser clock 3 minutes with no new report and
  let one in.
- Expected: the card reads "{tier} unreachable since {hh:mm:ss} UTC" with Retry and its last sizes tagged stale, while the other cards
  and the meters keep live figures, with no page error and no `role="alert"`; after 2 × 60 s without a report the stamp reads "Sampled
  {hh:mm:ss} UTC, stale" with the clock glyph and a "stale" tag, figures keep full-opacity text, writes stay enabled (a refusal is T4)
  and the next report clears it (the ticket's five minutes: D06 C-w).
- Oracle: UI (presentation) > the component state in `GET /admin/health` and the report's age from `generated_at`. 2nd: the component
  reads `down`, then healthy; `RecorderDiskBudgetSampleStale` after 300 s (rule test).

### 3.5 US-REC-005 Disk budget and forecasting (Must)

**E16-Q01-C31 Usage and projection are measured and sourced from the sample [R]** (`integration`, `e2e`; OWNER · recording; mirrors
US-REC-005/1, T07.1, S04.1, S04.2; `22` `getStorageUsage`; D04 §3)

- Pre: FX-A, FX-B and FX-SAMPLES (7 days of 60-second samples); the E16-K01 figure in force.
- Steps: read `getStorageUsage` twice 10 s apart; open SCR-142; read the tiers and the per-symbol table.
- Expected: `daily_growth_bytes` comes from the sampled series and lies within 20 % of the E16-K01 GB/day; `projected_full_at` and the
  days of runway show; each of the three tiers shows size and a text health state, every figure with its unit; both reads carry the
  same `generated_at` (sampled every 60 s, never computed per request); fields not yet served (D04-G1 to G3) show their captioned
  stand-ins.
- Oracle: the API (`generated_at` equal; growth against the seeded slope) > the cards. 2nd: `recorder_bytes_per_day{symbol}`;
  `recorder_projected_full_timestamp`.

**E16-Q01-C32 Level 1: the warning is specific and names the actions [R]** (`integration`, `e2e`; OWNER · disk-warning; mirrors
US-REC-005/2, T07.2, S01.6, S04.3; D02 §3 `disk warning`; D04 §5)

- Pre: the cap sized so seeded bytes are 82 % of `cap_bytes`; separately a seeded slope that reaches the cap in 6 days.
- Steps: read `getStorageUsage`; open SCR-140 and SCR-142.
- Expected: `level: 1`, `write_gate: open`; SCR-140's card reads "Near limit · auto-record pauses in about {n} days · clears below 75
  %" with "Recording budget 82.0 % used" and units, as a polite notice with no banner (D06 C-t); SCR-142 adds "Recording pauses before
  trading is affected."; the 6-day slope raises one warning event naming the projected date and listing reduce depth, shorten
  retention and unpin.
- Oracle: `getStorageUsage` > the event payload > the text. 2nd: `recorder_disk_pressure_level` is 1; the 80 % alert.

**E16-Q01-C33 Level 3: recording halts, nothing is deleted, the order path works [R] [F]** (`integration`, `e2e`; OWNER ·
disk-critical; mirrors US-REC-005/3, T07.4, T07.5, S04.3, AC-10; D02 §3 `disk critical`; D04 §5)

- Pre: used share 96 % of `cap_bytes`; FX-C pinned and dominant; FX-E (that half **blocked on E29-T06**); a demo order the harness submits on the
  account-fixture stack (`infra/compose/docker-compose.account-fixture.yml`).
- Steps: replay the feed for a non-pinned symbol; add a symbol; submit and cancel an order; open SCR-140 and SCR-142; take `M(post)`.
- Expected: `level: 3`, `write_gate: closed`; rows of symbols without an open position are dropped and recorded as gaps
  (`backpressure_drop`) while the position's symbol keeps writing; nothing recorded is deleted (`M(pre)` is a subset of `M(post)`),
  pinned data survives and non-pinned auto-recorded ingestion pauses; SCR-140 shows the danger banner "Recording stopped: …", every
  row but the position's reads "Gated · data dropped" (a new add too) and Compact, Purge and Import stay enabled; SCR-142 says
  recording paused and trading unaffected; the order submits and cancels.
- Oracle: `M` (no deletion; gap rows for the dropped windows) > `getStorageUsage` > the banner. 2nd: `RecorderWriteGateClosed`;
  `recorder_rows_dropped_total`. The fill to 90 % then 100 % at scale is E16-Q04's (section 8).
- Variant b, a shared or missing recording volume (SR-096; RB "Recording stays refused"): `level: 3`, `write_gate: closed`,
  `write_gate_reason: volume_refused`, SCR-142 reads "The recording volume was refused at start-up; the gate opens once it is fixed",
  and the API and trading stay up; `CV_ALLOW_SHARED_VOLUME` is refused at boot outside testnet (C55).

**E16-Q01-C34 A disconnect yields one explicit gap and a new session [R] [R2]** (`integration`; OWNER · degraded; mirrors
US-REC-006/1, T04.1; `23`; D05 §2)

- Pre: ETHUSDT recording from the recorded reconnect fixture, re-stamped so the outage lasts 12 minutes of event time.
- Steps: replay the outage and the resubscribe with a fresh snapshot; read the sessions, coverage and the row detail.
- Expected: the open session closes, one `recording_gaps` row with cause `ws_disconnect` covers exactly the outage window and a new
  session opens; the row detail's "Gaps (last 24 h)" lists start, end, duration and reason; nothing is interpolated.
- Oracle: `M` (two `recording_sessions` rows, one `recording_gaps` row, exact bounds) > `listRecordingSessions` and `getDataCoverage`.
  2nd: `recorder_gaps_total{cause="ws_disconnect"}` +1; `recorder_gap_seconds_total{symbol}` equals the window.

**E16-Q01-C35 Coverage reports what exists, with each gap and its cause [R] [R2]** (`contract`, `integration`; OWNER · degraded;
mirrors T04.2, US-REC-006/1; `22` `getDataCoverage`; D05 §3)

- Pre: FX-B (G1 `ws_disconnect` 200 s; G2 `process_restart` 12 min).
- Steps: read coverage for `trades` over the whole span; with an unknown `stream`; with an unlisted symbol.
- Expected: contiguous intervals with tier and rows, each gap separate with its `reason` (`ws_disconnect`, `backend_restart`) and
  never inside an interval; unknown stream `400 validation_failed`, unlisted symbol `422 validation_failed`; the report spans the last
  90 days, older is unknown and never a gap (D05-CG1).
- Oracle: the API against the seeded manifest (bounds, rows) > the chip "Partial: {n} of {m} requested days recorded" (D05 §3's
  formula). 2nd: none (a read).

**E16-Q01-C36 A window before the recording start is refused with its timestamp [R] [R2] [F]** (`contract`, `e2e`; OWNER, VIEWER ·
recording; mirrors T04.3, T08.8, S05.2; `22` `getBars`; D05 §4)

- Pre: a symbol whose recording began yesterday.
- Steps: request bars for a window entirely before the start; open the same window in the chart.
- Expected: `422 no_data_recorded` carrying `recording_started_at`, never an empty success; the chart reads "History starts {date}
  {hh:mm} UTC — recording began then." with "Go to recorded history", the same for every role; the server's message is never shown.
- Oracle: status, code and field > the text. 2nd: none (a read).

**E16-Q01-C37 A crash leaves no open session [F]** (`integration`; OWNER · recording; mirrors T04.4; `24` §13.3.1)

- Pre: FX-A recording with the feed running.
- Steps: kill the API process; restart; read sessions and coverage.
- Expected: the open session closes with `end_reason: process_restart`, a gap from `last_event_ts` to startup is written (REST
  `backend_restart`) and a new session opens when recording resumes; no session stays `recording` without a process.
- Oracle: `M` (`recording_sessions`, `recording_gaps`) > `listRecordingSessions` > `getDataCoverage`. 2nd: `recorder_sessions_open`;
  `recorder_gaps_total{cause="process_restart"}`.

**E16-Q01-C38 Kline backfill never erases the tick gap [R] [R2]** (`integration`; OWNER · degraded; mirrors US-REC-006/3, T04.5,
S05.5; D05 §1.5; OQ-10)

- Pre: FX-B's G2, with the recorded replies `rest/kline_BTCUSDT_1_page{0,1,2}.json` as the backfill source.
- Steps: run the backfill; read bars for the window, trades coverage and the gap row.
- Expected: bars for the window exist and are bar-derived (`sources: exchange_rest`); the gap row is `backfilled` with source kline;
  trades coverage still reports the gap, never shrunk, and tick-level views still draw it. `22`'s `gaps[]` has no `backfilled` marker
  (D05-G1): the API half is **blocked on E16-S05 (#487)**.
- Oracle: `M` (`recording_gaps.backfilled`, the bars rows) > coverage > the chart line. 2nd: none beyond the rows.

**E16-Q01-C39 The daily integrity job reports what it cannot explain; blocked on E16-T04** (OQ-7; mirrors US-REC-006/2): the job
(`recorder/integrity.py`) writes a `seq_jump` gap for an unexplained sequence break and raises `recorder.integrity_anomaly` for data
outside every session, but it has no scheduler wiring and no trigger in `22` at the base. The seed is ready
(`ws/gap_orderbook_ETHUSDT.jsonl`); the oracle once unblocked: `M` (a `seq_jump` gap row) > the system event.

**E16-Q01-C40 Gaps and empty states name their cause, by role [R] [R2]** (`e2e`, `a11y`; OWNER, a session without `recording:write`,
view-as; mirrors S02.4, S05.1, S05.3, S05.4; D05 §2, §4; D06 T2-13, T2-14)

- Pre: FX-B, FX-C and an unrecorded symbol.
- Steps: for each gap reason (`ws_disconnect`, `backend_restart`, `exchange_outage`, `backpressure_drop`, `seq_jump`,
  `retention_purge`, unknown) open a window inside a seeded gap; open a never-recorded symbol's chart in each of the three sessions;
  open SCR-100 with nothing recorded.
- Expected: covered data renders and the gap is a hatched, labelled region with start, end and D05 §2's cause sentence ("Recording was
  interrupted (connection to the exchange lost).") and no interpolation; a never-recorded symbol reads "History starts when you record
  {symbol} — recording has not begun yet."; OWNER sees `Record this symbol`, a session without `recording:write` "Only the owner can
  change recording." and no button, view-as "Read-only while viewing as {user}."; a restricted symbol reads "Recording status
  restricted", never "Not recording"; the watchlist shows the recording-not-started variant.
- Oracle: UI (a presentation case; the data is the seeded manifest). 2nd: none (presentation).

**E16-Q01-C41 A failing coverage request never leaves a spinner, and the empty chart costs no GPU [F]** (`e2e`, `perf`; OWNER · empty;
mirrors S05.6, S05.7; D05 §4; E11-D04)

- Pre: FX-EMPTY with the coverage reply stubbed to `503`.
- Steps: open a chart for an unrecorded symbol; time the first state; read the GL context count before and after.
- Expected: an error state with Retry within 5 s, never a spinner that persists; when the empty state renders no WebGL context for the
  data layer is created (no engine is built for the block).
- Oracle: the browser clock's 5 s bound > the context count (the hook is named by E16-S05's tests). 2nd: none (presentation).

### 3.7 US-REC-007 Historical bulk backfill (Should)

**E16-Q01-C42 An import writes the archive range to the cold tier and reports honestly [R]** (`integration`, `e2e`; OWNER · empty;
mirrors US-REC-007/1, T10.1, S04.6; `22` `importTradeArchive`; D04 §8; OQ-9)

- Pre: FX-D (31 daily BTCUSDT files, 2026-01-01 to 2026-01-31) on the mock archive host.
- Steps: import through the card (symbol, From, To); poll `getJob` every 2 s.
- Expected: `202`; files are downloaded, checksum-validated, converted and written under the cold layout; the job ends `succeeded` and
  the card reads "Import finished: BTCUSDT, 2026-01-01 → 2026-01-31" with the tag "Archive-derived · trades only · no book data"; the
  counts (files processed, rows written, rows discarded as overlap, files skipped with reasons) are `ArchiveImportResult`, PROPOSED in
  D04-G11: **blocked on E16-S04 (#486)**.
- Oracle: `M` (rows written equal the files' rows; documented layout; no duplicate `(symbol, trade_id)`) > `getJob`. 2nd:
  `recorder.import` (accept, then outcome); `import_files_total{result}`.

**E16-Q01-C43 Recorded data wins on overlap [R]** (`integration`; OWNER · recording; mirrors US-REC-007/2, T10.2)

- Pre: FX-D2 (FX-D plus recorded BTCUSDT for 2026-01-20 to 2026-01-31).
- Steps: import 2026-01-01 to 2026-01-31; compare the windows.
- Expected: imported rows inside the recorded window are discarded and counted, the overlap is reported with its exact bounds, the
  recorded rows are unchanged and no duplicate trade exists.
- Oracle: `M` (recorded window byte-identical; imported-only window present; distinct trade ids equal rows) > the job result. 2nd:
  `import_rows_discarded_total` equals the window's count.

**E16-Q01-C44 A corrupt file is skipped and named, and the import continues [F]** (`integration`, `e2e`; OWNER; mirrors US-REC-007/3,
T10.3, S04.6; D04 §8)

- Pre: FX-D with day 14's file failing its checksum.
- Steps: import the range; watch the page during the run and after.
- Expected: day 14 is skipped and named with its reason and the other 30 days are imported; the job ends `succeeded`; the page keeps
  its healthy chrome (no banner, no `role="alert"`) and the card says "Run it again to resume: finished days are skipped."; the reason
  code differs across sources (T10 `import_checksum_failed`, D04 `checksum_mismatch`), so the case asserts a named reason (OQ-9).
- Oracle: `M` (30 files' rows present, day 14 absent) > `getJob` > the page. 2nd: `import_files_total{result="skipped"}`.

**E16-Q01-C45 An interrupted import resumes at the next file [R] [F]** (`integration`; OWNER; mirrors T10.4; US-REC-007 NFR; D04 §6;
D06 Q-07)

- Pre: FX-D with 30 files; the mock host logs requests.
- Steps: start the import; stop the API after file 12 completes (no cancel route: D04-G10); restart; re-send the same request; poll
  the old job id; reload the page with no job id.
- Expected: the import resumes at file 13 and the host log shows files 1 to 12 requested once; `M(post)` equals an uninterrupted run
  and a finished import re-run is a no-op; the old id answers `404 job_unknown`; a press with no job id meets `409 job_running` as T4
  ("An import is already running.") and the card stays enabled.
- Oracle: the host log and `M(post)` > `getJob` > the text. 2nd: `import_duration_seconds`; no second `recorder.import` accept for
  finished days.

**E16-Q01-C46 An imported-only window is labelled archive-derived and has no book data** (`contract`, `e2e`; OWNER; mirrors T10.5,
S04.6; D04 §8; `22` `getDataCoverage`; OQ-9)

- Pre: FX-D imported into an empty cold tier.
- Steps: read coverage for `trades` and `orderbook_delta` over the window; open the chart over it.
- Expected: `trades` covers the window in tier `parquet` and `orderbook_delta` has no interval; the summary shows the tag
  "Archive-derived · trades only · no book data"; the per-interval `source: archive` is PROPOSED (D04-G12): that field is **blocked on
  E16-S04 (#486)**.
- Oracle: the API intervals > `M` (no book rows) > the tag. 2nd: none (a read).

**E16-Q01-C47 Hostile and oversized imports are refused and write nothing outside the root [R] [F]** (`security`, `contract`; OWNER; mirrors AC-08, AC-09, AC-15; TM R-E4, R-T2, R-D3; D06 §16.4 rows 9, 15, 16)

- Pre: the scratch root with a sentinel tree beside it; the mock host serving hostile members.
- Steps and expected, one row each; in every row the sentinel tree and `M` are unchanged and no staging file remains:

| Row | Input                                                               | Expected                                                                        |
| --- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| a   | a range over 366 days, inverted or empty                            | `422 import_range_invalid`; the form says "Choose a range of at most 366 days." |
| b   | a path-like or unlisted symbol                                      | `400` or `422`; no request reaches the host                                     |
| c   | members `..`, absolute, drive-letter, symlink; a decompression bomb | a clean failure with its reason; the bomb stopped at its limits                 |
| d   | the staged file replaced after download                             | hash mismatch, import aborted, file quarantined                                 |
| e   | a range projected above 80 % of the free budget                     | refused before the first file, with the projection                              |
| f   | a second import while one runs                                      | `409 job_running`                                                               |

- Oracle: status and code per row > the sentinel tree and `M` unchanged. 2nd: `recorder.import` outcome for an accepted call;
  `recorder_path_containment_reject_total`.

### 3.8 US-REC-008 Recorder health and control (Must)

**E16-Q01-C48 Health is shown per symbol and the topic streams at 1 Hz [R]** (`contract`, `e2e`; OWNER · recording; mirrors
US-REC-008/1, T08.1, T08.7; `23` §6.2.2, §15.8; D02 §6.7; D06 §7 BG-01)

- Pre: FX-A and FX-B recording.
- Steps: validate every recording path against `22`'s examples; subscribe to `recorder` for two symbols and collect 5 frames; open the
  row detail; watch the summary region for a minute.
- Expected: a snapshot first, then frames about 1 000 ms apart, never merged, each valid against `RecorderUpdate`; per symbol the
  ingest (`rows_last_hour`), `lag_ms`, `last_event_at`, `dropped_messages` (non-zero reads as an incident), `resyncs_last_hour` and
  the disk rate; the summary region changes only on a change of state, at most once per 10 s, never with a per-row number; REST and
  the frame agree.
- Oracle: schema validation and frame timestamps > REST equality > the region's text mutations. 2nd:
  `ws_topic_subscribers{topic="recorder"}`; `recorder_status_cache_age_seconds` is exported.

**E16-Q01-C49 The writer stores every event exactly once [R]** (`integration`; OWNER · recording; mirrors T03.1; `21`)

- Pre: BTCUSDT at depth 200, with the recorded tape and book windows replayed for 10 minutes of event time.
- Steps: replay; wait for the flush; read `M(post)` and the backlog metric.
- Expected: every event appears exactly once in its table (the count equals the replayed frames' distinct
  `(symbol, stream, exch_ts, seq)`); `recorder_write_backlog_rows` is 0 at p95.
- Oracle: `M(post)` against the fixture's distinct-key count > the backlog p95. 2nd: `recorder_rows_dropped_total` unchanged.

**E16-Q01-C50 QuestDB down: spill, replay in order, and exhaustion becomes an explicit gap [F]** (`integration`; OWNER · degraded;
mirrors T03.2, T03.3, T03.4, AC-11; ADR-15 d8)

- Pre: FX-A recording; `CV_RECORDER_WAL_MAX_BYTES` at its 1 MiB floor for the second half.
- Steps: stop QuestDB for 2 minutes of event time and restart it; interrupt the replay halfway and restart it; repeat with the WAL
  bound reached.
- Expected: events spill to the on-disk WAL, `recorder_spill_bytes` rises and no row is dropped; on return the WAL replays in
  `exch_ts` order and is truncated, with no duplicate `(symbol, stream, exch_ts, seq)` after an interrupted replay; at the bound
  further events are dropped, one `recording_gaps` row with cause `backpressure_drop` covers the window, a critical event names the
  symbol and auto-recorded unpinned symbols stop first.
- Oracle: `M` (the row set equals the fixture's keys when nothing dropped, no duplicates, the gap row's bounds when it did) > the
  `recorder_spill_bytes` series. 2nd: `RecorderSpilling` after 5 minutes (rule test); `RecorderMessagesDropped`.

**E16-Q01-C51 Restart a feed; blocked on E16-D02 and the `22` owner** (OQ-5; mirrors US-REC-008/2): `22` has no operation for it and
D02 C-6 draws no control. The story's expectation stands for when it is answered: the subscription is torn down and re-established,
the interruption is recorded as a gap and the action is audited. C34 covers the gap half meanwhile.

**E16-Q01-C52 A silent symbol pages within 90 seconds, and a venue outage pages once [R]** (`integration`; OWNER · degraded; mirrors
US-REC-008/3, T09.1, T09.2; `infra/prometheus/alerts/recorder.yml`; D02 §4.1 Silent)

- Pre: BTCUSDT and ETHUSDT recording, BTCUSDT's writer suspended while ETHUSDT keeps writing.
- Steps: let 60 s of event time pass in the rule test and on the stack; read the alert and the row; then drop the public WS for every
  symbol.
- Expected: `RecorderSilentStop` pages naming BTCUSDT by t+90 s; the row reads "No writes since {hh:mm:ss}" (derived from
  `last_event_at` older than 60 s while the market is active); with the whole connection silent the per-symbol alert does not fan out
  and `IngestionStoppedReporting` pages once.
- Oracle: the rule test with fake time and `ALERTS` on the stack > the row text. 2nd: `RecorderMessagesDropped` untouched.

**E16-Q01-C53 Every alert has a runbook, and the dashboard provisions from code** (`contract`; mirrors T09.3, T09.4)

- Pre and steps: lint the alert rules file; provision the dashboards on a clean Grafana instance on the scratch stack.
- Expected: every rule has a `runbook_url` that resolves to a section of `docs/ops/runbooks/recorder.md`; the recorder dashboard
  appears with every panel populated from live metrics. Oracle: the lint's exit status and anchors > the panels' queries. 2nd: none
  (static).

### 3.9 Cross-cutting cases: roles, the clock gate, the step-up and the keyboard path

**E16-Q01-C54 The role grid holds for every write [R] [F]** (`security`, `contract`; MANAGER, VIEWER; mirrors T08.6, AC-03; TM R-E1;
section 2.2)

- Pre: FX-A and FX-C; a session per role, with a synthetic step-up where the grid allows.
- Steps: send each write of the grid (add, stop, pin, per-symbol retention, global set, purge, compact, import) as each role, and as
  OWNER without elevation.
- Expected: every cell as section 2.2 (VIEWER `403` everywhere; MANAGER `403` on purge and the global set, else the server's answer:
  OQ-2); each `403` is audited; policy, data and manifests are unchanged by any refusal. AC-03's "PATCH `hot_days=0`" is read as a
  shortening `PUT` of the global set (`22` has no `hot_days`), which the MANAGER's `403` answers.
- Oracle: statuses > `M(pre)` equals `M(post)` and the stored set unchanged > one audit row per refusal. 2nd: `rbac.denied`.

**E16-Q01-C55 The test clock cannot be enabled in production [F]** (`unit`, `security`; mirrors AC-14; TM R-E3; section 4.1)

- Pre: the settings loader; no network.
- Steps: boot with `CV_TEST_CLOCK` in live, in demo and on a keyed testnet; the switch without its file and the file without the
  switch; a relative, a `..` and a symlinked file path; `CV_ALLOW_SHARED_VOLUME` in live and in demo; then on a keyless testnet with
  both set, scan `22` and the running API for a route that sets a clock and send clock-shaped headers and parameters.
- Expected: each refused boot fails naming the switch and the rule, never a value; the permitted boot writes
  `system.config.test_clock_enabled` once; no `22` operation sets a clock and no request input moves one.
- Oracle: exit status and error text > the audit record > the route scan. 2nd: `system.config.test_clock_enabled`. E16-X02 verified
  the gate (its record, area 6).

**E16-Q01-C56 The step-up grace and its failure paths behave as the contract says [R] [F]** (`e2e`, `contract`; OWNER; mirrors D06
Q-07; `22` `authStepUp`; D02 §6.4)

- Pre: the keyless testnet stack with the offset clock on (section 4), and a synthetic TOTP.
- Steps: change a symbol's retention (class `recorder`), repeat inside the grace and after moving the clock 301 s; submit two purges
  in a row; enter three invalid codes; cancel with Esc.
- Expected: inside the grace the second `recorder` write passes ("Still trusted for recorder changes · {mm:ss}"), after 301 s a code
  is asked again; every purge asks a fresh code and shows no "Still trusted" line; three invalid codes make the session read-only for
  5 minutes (`403 session_read_only`, T4 on each control); Esc, expiry or the third failure ends the held request "Not sent", inputs
  kept; a lost reply after a successful step-up is never reported as not sent and never re-sent by the client.
- Oracle: the `step_up_required` and success sequence, one executed change per held request > the audit order
  (`auth.step_up_required`, `_granted`, `_failed`, `auth.session_readonly_downgrade`). 2nd: those actions.

**E16-Q01-C57 Gated controls are T2, never hidden, and refusals are T4** (`e2e`, `a11y`; view-as, and a session without
`recording:write`; mirrors D06 T2-01 to T2-17, §20.3 (i); S02.3)

- Pre: FX-A with a chart open on one row.
- Steps: on SCR-140, SCR-141, SCR-142 and the REC chip menu, tab to every write while viewing as another user and as a session without
  `recording:write`; press Enter and Space on each.
- Expected: each gated control keeps its full label, is `aria-disabled="true"` (never `disabled`), stays in the Tab order and carries
  the lock and a reason linked by `aria-describedby`, in the DOM at mount; Enter or Space changes nothing and re-shows the reason
  once, politely; every exit (Cancel, Esc, Retry, links) is enabled; the server's refusal of a write renders as T4 at the point of
  action, never a client decision; no reason names a symbol, a count or a size.
- Oracle: UI (a presentation case; the a11y audit is E16-Q05's) with the server's answer for each refused write. 2nd: `rbac.denied`.

**E16-Q01-C58 The keyboard-only five-task path completes** (`e2e`, `a11y`; OWNER, and a session without `recording:write`; mirrors
D06 §14 KS-01 to KS-11)

- Pre: FX-A with a chart open on one row, and an unrecorded symbol.
- Steps: by keyboard alone: record a symbol; try the blocked Stop and read its reason; shorten retention through the preview and the
  typed confirm; open the purge dialog and stop at the typed field with Esc; as a session without `recording:write` open an unrecorded
  symbol's chart and read the sentence form.
- Expected: all five tasks complete without a pointer; the purge walk sends no request; the blocked Stop re-shows its reason once; the
  sentence form adds no tab stop; focus lands where D06 §14 names it.
- Oracle: the request log > the focus target at each step. 2nd: none (the spoken strings are E16-Q05's).

## 4. Time control

No case sleeps or waits more than 5 minutes. Ages come from seeded data, durations from configuration and jumps from the one gated hook.

**4.1 The `CV_TEST_CLOCK` gate, a precondition.** The hook is a configuration gate and never a production switch: `Settings` accepts
`CV_TEST_CLOCK` and `CV_TEST_CLOCK_FILE` only together, on `CV_ENVIRONMENT=testnet` with no exchange key and an absolute file path with no `..` and no
symlink, and refuses boot otherwise; `CV_ALLOW_SHARED_VOLUME` is gated the same way (E16-FR-11; TM R-E3, AC-14; `07` §4.4). No `22` operation sets a clock.
E16-X02 verified the gate (`docs/security/reviews/e16-recorder-review.md`, area 6, PASS) and C55 re-asserts it. A run that uses the hook owns its Postgres
database, QuestDB namespace and recording volume (C-2.11), writes `system.config.test_clock_enabled` at boot and ends with a fresh stack, never a rewound one.

**4.2 What the hook moves at the base.** The shipped seam (#2086, `auth/testnet_clock.py`) feeds the auth clock only: sessions, the step-up grace, lockouts.
The recorder's retention, roll-off, importer and policy clocks default to real UTC (`recorder_wiring.Clocks`), so the ticket's "advance the recorder's clock"
has no wire yet (OQ-3). The strategy therefore does not depend on it:

| Need                                        | Mechanism                                                                                                                                                                                                                                                                            | Cases                        |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------- |
| a 30-, 7- or 180-day horizon                | seed ages, not clocks: partitions dated T-n days (T = seed time), at least a whole day from the horizon, run within 30 minutes of seeding                                                                                                                                            | C16, C21, C22, C24, C26, C29 |
| the dwell (60 s) and the grace (30 min)     | configuration: `CV_RECORDER_AUTOSTART_DELAY_S` 20 and `CV_RECORDER_AUTOSTOP_GRACE_S` 90 on the scratch stack; the case reads `getRecordingStatus.policy` back and asserts the ratios; the defaults 60 and 1 800 are asserted once, on that read (C09)                                | C04, C09, C11 to C13         |
| a nightly job on demand                     | the sweep: `PUT /recording/retention-policies?apply_now=true` (scheduler on, `CV_RETENTION_ENABLED`, else `409 conflict`), polled at 2 s; compaction, import and purge are jobs; the roll-off runs once when its loop starts, so a restart with the scheduler on triggers it (OQ-13) | C16, C19, C26, C28           |
| the step-up grace (5 min)                   | the testnet offset clock: write 301 s, assert, reset to 0; a margin of one minute, never the exact boundary                                                                                                                                                                          | C56                          |
| UI timers (2 s, 2 × 60 s, 5 s, 10 s)        | the browser clock (`page.clock`), no wait                                                                                                                                                                                                                                            | C08, C30, C41, C48           |
| outages (12 min silent, 2 min QuestDB down) | event time inside the replayed fixtures, not wall time                                                                                                                                                                                                                               | C34, C37, C50                |
| alert windows (60 s, 5 min, 300 s)          | `promtool` rule tests with synthetic series and `eval_time`                                                                                                                                                                                                                          | C30, C50, C52                |
| a lease TTL, or a 24 h lease (AC-12)        | needs the recorder's wall clock: **blocked on OQ-3**                                                                                                                                                                                                                                 | C21                          |

Every case names its clock, and no assertion sits on an exact boundary instant.

## 5. The destructive-test protocol

Every case runs on the scratch stack, which holds no production data; the cases that can delete or rewrite data (C15 to C17, C19, C21 to C24, C26, C28, C29, C47)
follow the protocol below in full.

- **Scratch stack and volume.** Its own Postgres database, QuestDB namespace and recording volume, a separate filesystem of fixed size (SR-096), created for the
  run and destroyed after it; never shared with a demo, staging or live process. Pre-flight, before any request: `getStorageUsage.tiers[]` roots resolve under the
  scratch mount, the profile is keyless testnet or staging, and `CV_RETENTION_ENABLED` is as the case needs. A failed pre-flight stops the case.
- **Manifests.** `M(pre)` and `M(post)` are sorted JSON lines from a read-only tool. Cold tier: every file under the dataset root as relative path, bytes, SHA-256
  and Parquet-footer row count, plus the `_manifests/` tree. Hot tier: a read-only `count()` per table, partition and symbol, with partition bytes. Relational: row
  counts of `recorded_symbols`, `retention_policies`, `recording_sessions` and `recording_gaps`, and the audit chain head.
- **Assertions.** "Nothing was deleted" (dry runs, refusals, leases, pins): `M(pre)` equals `M(post)` file for file and row for row, ignoring only audit growth
  and job rows. "Exactly this was deleted": `M(pre)` minus `M(post)` equals the case's stated set, `M(post)` minus `M(pre)` is empty for the data tiers, and every
  other file keeps its hash and every other count is equal. The audit agrees: one `data.deleted` per removed partition with the manifest's range, rows and bytes,
  `retention.purge` before its job, and the chain verifies. The expected delta is written from the fixture's own manifest and the policy before the run, never from the
  system's report, which is checked against the manifest.
- **Safety stops.** A case aborts and the stack is destroyed if `M(pre)` differs from the fixture's manifest or the scratch marker is missing. A delete outside
  the stated set is P0 (data loss, `03` §11.3) whatever else passes. Each deleting case starts from a fresh seed, and no stack a purge ran on is read by a later case.

## 6. The fixture catalogue

All data is the recorded, redacted corpus `packages/fixtures/bybit/2026-10-05/` (C-13.5), re-stamped to dates relative to the seed time T; no key, account or
production row. Ages are in days before T.

| Handle                | Ticket item                    | Content                                                                                                                                                                                          | Seeded by                                                                                                                                            |
| --------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| FX-EMPTY              | fresh install                  | no recorded symbol, session or data; migrated databases and an empty scratch volume                                                                                                              | stack boot                                                                                                                                           |
| FX-A (ETHUSDT)        | (a) continuously recorded      | manual, recording, one open session since T-35, no gap, unpinned; cold partitions T-35 to T-8 except T-30 (the 30-day boundary), hot T-7 to T                                                    | the seed script tiles `ws/clean_publicTrade_ETHUSDT.jsonl` across days, writes cold partitions with the E07 writer and hot rows over ILP             |
| FX-B (BTCUSDT)        | (b) two gaps of known causes   | 14 days; G1 `ws_disconnect` 200 s at T-10 02:11:00 to 02:14:20; G2 `process_restart` 12 min at T-5 10:00 to 10:12, partly fillable from the recorded klines                                      | as FX-A from `ws/clean_publicTrade_BTCUSDT.jsonl` and `ws/orderbook_BTCUSDT.jsonl`, with the two gap rows and the session bounds written by the seed |
| FX-C (SOLUSDT)        | (c) pinned, past every horizon | pinned; `trades` and `orderbook_delta` partitions at T-800 and T-740 (past 24 months), T-200 (past 180 days), T-40 (past 30 days) and one recent; one stopped row                                | as FX-A, then pinned through the API with a synthetic step-up                                                                                        |
| FX-D, FX-D2 (BTCUSDT) | (d) archive-imported only      | a mock archive host serving 31 daily files, 2026-01-01 to 2026-01-31, with day 14 failing its checksum in a variant and hostile members in another; FX-D2 adds recorded 2026-01-20 to 2026-01-31 | the import itself (C42) into an empty cold tier, with `CV_BYBIT_ARCHIVE_BASE` at the mock                                                            |
| FX-E (XRPUSDT)        | (e) an open position           | an unrecorded symbol with an open demo position and its native stop                                                                                                                              | `rest/trading-position-list.json` and `ws/private-position.jsonl`; **blocked on E29-T06**, no position source on `main` (OQ-4)                       |
| FX-SAMPLES, FX-MANY   | support                        | 7 days of 60-second usage samples for FX-A to FX-C with a known slope; FX-A scaled to ten symbols (C22)                                                                                          | the seed script                                                                                                                                      |

**Fixture gaps** (nothing is filed from here, the filing freeze: D06 C-h). FX-G1: the seed script, the manifest tool and the mock archive host (proposed owners:
E16-Q02 #479 for these, E16-Q04 #481 for the volume-fill and load generators). FX-G2: the corpus holds no recorded `allLiquidation` frames, so liquidations are asserted by subscription
until one is recorded and redacted. FX-G3: the feed adapter that replays corpus frames into the recorder. The backend team agrees this catalogue at the review.

## 7. Entry and exit criteria, and the regression subset

**Entry** (`03` §16). E16-S01 to S05 and E16-T02 to T10 are merged to `main`, CI is green and a deployable build runs on the scratch stack; the fixtures of section 6,
the manifest tool and the mock archive exist and each seed's own manifest passes; the `22` `recording` and `23` §15.8 contract tests are green; C55 passes; every open
question a case depends on is answered, or that case is marked blocked on it.

**Exit** (the epic's QA sign-off, `03` §16). Every case has a recorded result (pass or fail, build sha, environment), a blocked case carrying its question id; no P0
or P1 is open (`03` §11.3: a delete outside a stated set, a deletion without its audit record and any recorder effect on the order path are P0); every **[R]** case is
automated by E16-Q02 or listed manual with an owner, and every **[F]** case ran; every audit action and metric a case names was observed; the charter (E16-Q03), the
drills (E16-Q04) and the a11y audit (E16-Q05) are attached; section 9 has no gap and every section 10 row is answered or accepted by its owner. This plan's sign-off
is necessary, not sufficient: E16-Q06 (#483) assembles the epic's.

**Regression subset.** The [R] cases (31 of 58) run every sprint after exit and on any change to `recorder/`, `storage/cold/`, `storage/retention/`, the recording
routes, `23` §6.2.2 and §15.8, or SCR-140 to SCR-142, SCR-047 and SCR-151: the automated ones in CI's E2E and contract jobs (E16-Q02), the rest in the sprint's QA pass.
A flaky member is quarantined within 24 h with an owner (C-9.3), never retried silently. **[R2]** (C15, C16, C21, C26, C27, C34 to C36, C38, C40) is the subset every later
R2 epic that reads recorded data runs before its own QA sign-off, E18 to E26 (`30` §3): each depends on the recorder's honesty about gaps, coverage, tiers and deletions.

## 8. What this plan references and does not contain

- E16-Q02 (#479): the automation of these cases, the seed script, the manifest tool and the mock archive. E16-Q03 (#480): the exploratory charter on surprise, honesty
  and data-loss traps. E16-Q05 (#482): the a11y audit of SCR-140, SCR-141, SCR-142, SCR-047 and SCR-151 and D06 §13's script (this plan's UI cases are smoke only).
  E16-Q06 (#483): the regression pack and the epic's sign-off.
- E16-Q04 (#481): perf, soak and chaos: 50k msg/s ingest, p95 flush under 50 ms, API p95 under 150 ms, `recorder` at 1 Hz, the measured GB/day of E16-K01, the
  one-slow-stream isolation (T03.5), the disk-pressure drill (AC-10, 90 % then 100 %; by the E16-X02 ruling no new auto-record within 60 s at 90 % and a halt at
  95 %), AC-11 at scale and AC-12's 24 h lease.

## 9. Traceability

Scenarios are numbered in source order. Every scenario of US-REC-001 to US-REC-008, E16-S01 to S05 and E16-T02 to T10 maps to a case (T03.5 to E16-Q04, section 8); a
blocked case still maps, its blocked half marked in the case. Every Must story has an **[F]** case: US-REC-001 C03; 002 C12; 003 C15; 004 C28; 005 C33; 006 C36; 008 C50.

| Source     | Scenario to cases                                                       |
| ---------- | ----------------------------------------------------------------------- |
| US-REC-001 | 1 C01 · 2 C02 · 3 C04                                                   |
| US-REC-002 | 1 C09 · 2 C10 · 3 C11                                                   |
| US-REC-003 | 1 C16 · 2 C14, C15 · 3 C17                                              |
| US-REC-004 | 1 C26 · 2 C27 · 3 C26                                                   |
| US-REC-005 | 1 C31 · 2 C32 · 3 C33                                                   |
| US-REC-006 | 1 C34, C35 · 2 C39 · 3 C38                                              |
| US-REC-007 | 1 C42 · 2 C43 · 3 C44                                                   |
| US-REC-008 | 1 C48 · 2 C51 · 3 C52                                                   |
| E16-S01    | 1 C01 · 2 C02 · 3 C09 · 4 C05 · 5 C04 · 6 C32 · 7 C07 · 8 C08           |
| E16-S02    | 1 C09 · 2 C09 · 3 C07 · 4 C40 · 5 C09                                   |
| E16-S03    | 1 C17 · 2 C18 · 3 C20 · 4 C15 · 5 C14 · 6 C19 · 7 C07                   |
| E16-S04    | 1 C31 · 2 C31 · 3 C32, C33 · 4 C30 · 5 C28 · 6 C42, C44, C46 · 7 C30    |
| E16-S05    | 1 C40 · 2 C36 · 3 C40 · 4 C40 · 5 C38 · 6 C41 · 7 C41                   |
| E16-T02    | 1 C01 · 2 C02 · 3 C09 · 4 C05, C10 · 5 C11 · 6 C11                      |
| E16-T03    | 1 C49 · 2 C50 · 3 C50 · 4 C50 · 5 E16-Q04                               |
| E16-T04    | 1 C34 · 2 C35 · 3 C36 · 4 C37 · 5 C38                                   |
| E16-T05    | 1 C26 · 2 C26 · 3 C27 · 4 C28 · 5 C29                                   |
| E16-T06    | 1 C16 · 2 C15 · 3 C17 · 4 C21 · 5 C22 · 6 C23, C24 · 7 C17              |
| E16-T07    | 1 C31 · 2 C32 · 3 C12 · 4 C33 · 5 C33 · 6 C12                           |
| E16-T08    | 1 C03, C48 · 2 C01 · 3 C04, C06 · 4 C06 · 5 C23 · 6 C54 · 7 C48 · 8 C36 |
| E16-T09    | 1 C52 · 2 C52 · 3 C53 · 4 C53                                           |
| E16-T10    | 1 C42 · 2 C43 · 3 C44 · 4 C45 · 5 C46                                   |

Abuse cases of `TM` §6: AC-01 C13 · AC-02 C12, C13 · AC-03 C54 · AC-04 C23 · AC-05 C23 · AC-06 C24 · AC-07 C07 · AC-08 C47 · AC-09 C47 · AC-10 C33 · AC-11 C50 ·
AC-12 C21 · AC-13 C23 · AC-14 C55 · AC-15 C47.

## 10. Open questions

Each is a question for the owner of the source it names, not a guess. A case it blocks says so; the other cases of the same story run.

- **OQ-1** What the default "30 days" does to `trades` (C16 variant b; blocked on E16-T06's owner and the `21` owner). Reading A (US-REC-003/1, T06.1, ADR-0015
  d3): data older than 30 days is pruned. Reading B (`21` §7, `22` `setRetentionPolicies`, D03 §3, `recorder/retention_defaults.py`): 30 days is the hot window, then
  Parquet, and the total horizon is 24 months. C16 uses an explicit `drop` row, whose horizon `22` defines.
- **OQ-2** Whether MANAGER holds `recording:write` (section 2.1, C54; blocked on the `04`, `22` and seed owners, with E16-S01 (#484) opening the alignment).
  Reading A (D02 decision 4, D06 G-04): owner-only. Reading B (`04` rows 8 and 9, `22`, the RBAC seed): add, stop, pin and a symbol's retention are allowed, the
  pin behind the step-up. The server is the control, so cases assert its answer.
- **OQ-3** Which clock `CV_TEST_CLOCK` moves (C21's TTL half, section 4; blocked on E16-T06's and E16-T07's owners). Reading A (the ticket): the recorder's. Reading B
  (the base, #2086): the auth clock only, with the recorder's clocks on real UTC.
- **OQ-4** No open-position source on `main` (`NoPositionSource`; E29-T06 provides one), so FX-E cannot be seeded (C05, C07, C10, C25, C33; blocked on E29-T06).
- **OQ-5** Restart a feed (C51; blocked on E16-D02's and the `22` owners). Reading A (US-REC-008/2): a control re-establishes the subscription, records a gap and
  audits. Reading B (`22`, D02 C-6): no operation and no control.
- **OQ-6** The dry run (C17's API half; blocked on E16-S03, #485). Reading A (US-REC-003/3, T06.3, S03.1): the server reports what would be deleted. Reading B (`22`,
  D03-G1): no preview route, so the editor estimates in the client.
- **OQ-7** The daily integrity job (C39; blocked on E16-T04's owner): `recorder/integrity.py` is referenced by no wiring module and `22` has no trigger.
- **OQ-8** The ticket text against the merged design (C07, C08, C09, C20, C30; D06 C-r to C-z): the design's reading of S01.7, S01.8, S02.1, S03.3 and S04.7 stands;
  only S01.8's polling fallback is open, as it is not designed (D06 Q-04; blocked on E16-D02's owner).
- **OQ-9** Import and jobs (C28, C42, C44, C46; blocked on E16-S04, #486, and E16-T10's owner for names): the summary shape, a per-interval `source: archive` and a job
  cancel are PROPOSED (D04-G11, D04-G12, D04-G10), and the skip reason codes differ (T10 `import_checksum_failed`, D04 `checksum_mismatch`).
- **OQ-10** Coverage markers (C29, C38; blocked on E16-S05, #487, and E16-T05's and E16-T08's owners): `backfilled` (D05-G1) and a "downsampled" label (T05.5) are on no
  `22` `DataCoverage` field.
- **OQ-11** Audit names (C14, C28; blocked on the `22` owner): `22` declares `recorder.start`, `recorder.stop`, `retention.change`, `retention.purge` and `recorder.import`,
  and none for a pin, an unpin or a compaction (`14` SCR-140 says `recorder.pinned`; the registry holds `recorder.update` and `recorder.compact`; T08 names
  `storage.compaction_triggered`). Those cases assert one record with actor, scope, before and after, and its name once declared.
- **OQ-12** The purge's check order and step-up class (C23; not blocked). T08.5 reads `403` before the `422`; E42's AD-S07-07 reads class `recorder` with the body after the
  gate; `22` (after #4597 and #4622) decides the body first and names `recorder_purge`. This plan follows `22`; E42's plan is to be reconciled.
- **OQ-13** On-demand triggers and fault seams (C26 variant b, section 4; blocked on E16-T05's and E16-T06's owners): the roll-off has no API trigger (it runs when its loop
  starts), `RB` says the retention loop's nightly schedule is not wired yet, and no seam fails the roll-off's verify step.
