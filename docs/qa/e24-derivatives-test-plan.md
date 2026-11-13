# E24 Derivatives metrics — black-box test plan and exploratory charters

Ticket: E24-Q01 (#771). Status: v0.1, slice 1 of 3 (sections 0 to 2); sections 3 to 10 and the two charters follow in
the next slice (part 2). Draft for the QA lead and an E24 developer to review. Nothing here has been
executed: the panel is not built yet (section 0.4), so every case is **not yet run**.

## 0. Conventions

### 0.1 Sources and how a step cites them

**Expectations are derived from the specification, not the implementation.** Each case names its source:

- `US` = `docs/plan/11-user-stories.md` §14 (`US-DERIV-001` to `US-DERIV-008`, 24 scenarios).
- `S01` to `S08` = the Gherkin of the ticket `E24-S01` to `E24-S08` in `docs/plan/backlog/E24.json` (53 scenarios,
  a refinement of the 24 above: table alternative, stale shading, announcements, the zone acknowledgement).
- `22` = `docs/plan/22-api-openapi.yaml` (`/market/open-interest`, `/market/funding`, `/market/liquidations`,
  `/market/metrics`); `23` = `docs/plan/23-ws-protocol.md` (§14.8 `TickerUpdate`, §14.9 `LiquidationBatch`, the
  error table); `24` = `docs/plan/24-internal-schemas.md` §7.2 (the derivatives descriptors).
- `TM` = `docs/security/threat-models/E24-derivatives.md` (D1 to D18, abuse cases AC1 to AC13, gaps G1 and G2).
- `D02`, `D03`, `D04` = `docs/design/E24/E24-D0n.md` (on `main`). `D05` = the hand-off pack
  `docs/design/E24/E24-D05.md` and its copy deck `E24-D05-copy-deck.jsonl` (**not on `main`**, section 0.3).
  A frame is written `SCR-054/<frame>`, a state row `S54-nn`, an announcement rule `LR-n` (D05 §6, §9.2).
- Copy strings are quoted from the deck by key (`derivatives.oi.native_granularity`), never retyped from memory.
  A tester compares what is on screen to the deck byte for byte; a deviation is a defect (severity rules in part 2).

**Never invent behaviour.** Where the specification is silent the case says **PROPOSED** and names the owner of
the answer; the open ones are collected as questions against the implementing tickets in part 2, not guessed.

### 0.2 Environment and rules of the run

- **Staging / demo only, recorded fixtures only, no network.** Never against live
  (C-2.11, demo/live isolation); no call to `*.bybit.com` or `*.bytick.com` (C-13.5, `40-testing.md`).
  The stack is the seeded stack of the E49 harness (`docs/qa/e49-exploratory-harness.md` §2, tier B): public
  data is replayed from `packages/fixtures`, so a funding rollover or a cascade is reproduced, never waited for.
- **Time is a fake clock.** The countdown cases (BB-003-xx, SM-5) run on the stack's controllable clock and a
  controllable clock offset, never on wall time and never by sleeping until a settlement.
- No real API key, token or `.env` value appears in any step or evidence (C-2.7). Sessions are seeded test
  sessions (section 1). Evidence that shows a token is redacted before it is attached.
- **Read-only surface.** Every E24 operation is a `GET` or a read-only subscription (`TM` §6), so no case here
  writes an audit row, with two exceptions the stories name: the **zone acknowledgement** is audited (S07
  "Enabling requires acknowledgement"), and a settings change emits the standard `settings.change` entry (S02
  "Absolute versus delta"). Those cases check the audit row; every other case checks that none was written.
- **Keyboard smoke** (per surface): complete the case's primary action keyboard-only. The full a11y audit is
  E24-Q04 and is not duplicated here; the cases that must be repeated with a screen reader are listed in part 2.

### 0.3 Inputs and their pins

Part of the contract and the design are still in open PRs. Each is pinned at its head sha, read with
`git show <branch>:<path>`, and every case that leans on one says "if #N merges as is" (`32-design-specs.md` R6).
When one merges, the closing slice re-pins it to its merge commit and re-reads the affected cases.

<!-- prettier-ignore -->
| Input | Pin (head sha read) | What the plan takes from it |
|---|---|---|
| `main` | `1361424334dc4248843f240f6f6bdf261d74ad98` | `22` / `23` / `24`, D02 to D04, `03` §11, the E24 threat model, the fixture corpus |
| #5617 `design/e24-d05-handoff` | `fd598be52a047372add08d54d05d257997f8a7bd` | D05 §6 frames and `S54-nn` rows, §9 live regions, §10 `deriv.*` defaults, §11 budgets, §12 analytics |
| #5616 `design/e24-d05-deck` | `cc1adea82cbe0b52bc59feb3f125fafd701950fc` | the copy deck keys quoted in the cases |
| #5699 `feat/e24-funding-contract` | `7ba5674736593d040f617d0eff79c41fab8fcf8d` | funding `meta.coverage`, `annualised_pct`, `upper_funding_rate` / `lower_funding_rate`, `FundingEstimate` |
| #5341 `feat/e24-market-metrics` | `021c79460d6c0a488fa3854a1db98fb2f622faf9` | the derivatives metric codes, the 1 500-bar and 400-day window, `null` versus `"0"`, the 422 for an unserved code |
| #5273 `feat/e24-liquidations` | `9bf4ec8c2bd5a2ca067c5a77726f63f0f2c0d0dd` | the `/market/liquidations` handler and the cascade fixtures (fixture plan in part 2) |

The story branches (`feat/e24-oi-delta-quadrant`, `feat/e24-funding-tick` and the others) were read as inputs for
oracles only. They are never an expectation: a plan that copies the implementation proves nothing.

### 0.4 What can be run when

<!-- prettier-ignore -->
| Surface | State at the pin | Consequence for this plan |
|---|---|---|
| `GET /market/open-interest` | on `main` (E24-T01 closed) | cases runnable now against the API |
| `GET /market/funding` | on `main`; #5699 extends the contract | runnable; `meta.coverage` and `annualised_pct` cases are "if #5699 merges as is" |
| `GET /market/liquidations` | contract on `main`, handler in #5273 (open) | cases `PENDING #5273` |
| `GET /market/metrics` | contract on `main`, handler in #5341 (open) | cases `PENDING #5341` |
| SCR-054 panes (S01 to S08) | no OI, funding, liquidation or basis pane merged | every UI case is "not yet run"; the closing slice runs them |

### 0.5 Case ids, tags and status

- Ids: `BB-<nnn>-<nn>` is a black-box scenario of `US-DERIV-<nnn>` (`BB-PNL-nn`: panel-wide); `NG-nn` a negative; `BD-nn` a boundary;
  `SM-n` a semantic check; `CV-nn` a coverage case; `CS-nn` a cascade case; `CH-n` a charter. **Ids are stable:**
  Q02 and Q05 reference them, a case is never renumbered, an addition takes the next number.
- Tags: **[R]** is in the regression pack for E24-Q05 (the regression pack in part 2); **[A:Q02]**, **[A:X02]**, **[A:Q03]**, **[A:Q04]**
  mean the named ticket automates it and this plan keeps only the manual run; **[SEM]** is one of the six
  semantic checks the ticket names (part 2); **[SEC]** carries a security abuse case or a D11 negative.
- Status words: `PENDING #n` (cannot run until that PR merges); `EXPECTED-BY-MODEL (22 silent)` (the result is the
  threat model's and the contract does not state it yet); `PROPOSED` (the specification is silent; owner named).
- Every case is Pre -> Steps -> Expected. A tester who did not write the plan must reach the precondition using
  only section 1 and the fixture plan (part 2), and judge pass or fail without asking.
- Optional **Signal:** names the telemetry that should have caught a defect found by the case, from the five
  metrics of `TM` §8 (`deriv_upstream_schema_rejected_total`, `deriv_range_rejected_total`,
  `deriv_sub_cap_rejected_total`, `deriv_fanout_dropped_total`, `deriv_source_mix_blocked_total`) plus the
  staleness signal. A defect with no signal is reported as an observability finding in the run record.

### 0.6 Section map

This part holds sections 0 to 2: 2.1 to 2.8 the 55 per-story cases, 2.9 the panel-wide cases, 2.10 the route
negatives. **Part 2** (the next slice) holds sections 3 to 10: the semantic checks (`SM-n`), the boundaries (`BD-nn`)
and the abuse cases (`NG-09` onward), recorder-bounded history (`CV-nn`), the cascade (`CS-nn`), severity, the
fixture and fault-toggle plan (`FX-*`, `FT-*`), the charters (`CH-n`), the regression pack, the hand-offs, the open
questions and the traceability. Ids and names that this part uses before part 2 defines them are marked "(part 2)".

## 1. Seeded actors, symbols and data (summary; the full data plan is in part 2)

<!-- prettier-ignore -->
| Handle | Meaning |
|---|---|
| OWNER | Owner role, TOTP enrolled; holds `marketdata:read` (`21` `role_permissions`: `owner: ["*"]`) |
| MGR-A | Manager with grants on ACC-1 and ACC-2; holds `marketdata:read` (scope `none`: not account-scoped) |
| VIEWER-V | Viewer; holds `marketdata:read` (`04` §7.2.1). Used for read-only checks, **not** for the 403 case below |
| ENROL-ONLY | a session that has not enrolled TOTP yet: REST `403 mfa_enrollment_required` outside its allow-list (`22` `Forbidden`); on the WS it is refused **at `auth`** (`bye mfa_enrollment_required`, close `4403`, audited `auth.mfa_enrollment_required`; `23` §4.3), so it never reaches a `sub` |
| NO-TOKEN, BAD-TOKEN, EXPIRED-TOKEN | no `Authorization`; a malformed one; one past `expires_in`: `401` (`22` `Unauthorized`) |
| ACC-1 with a BTCUSDT long | a demo position for the charge line (S03 "Imminent settlement"); ACC-2 with none |
| SYM-8H | BTCUSDT, `funding_interval_minutes` 480 |
| SYM-4H | the 4 h symbol of the corpus (`funding_history_ETHUSDT_4h`; the golden case `btc_4h_paired` pairs it with the BTCUSDT grid) |
| SYM-NEVER | a listed symbol the recorder has never recorded (SOLUSDT in the D05 frames) |
| SYM-REC-2H | BTCUSDT with a recorder that started 2 hours before the session (`btc_8h_recorder_gap` family, fixture plan in part 2) |

**Finding for the 403 negatives (BQ 16).** `21` `role_permissions` and `04` §7.2.1 give `marketdata:read` to every
role: Owner, Manager and Viewer. There is **no seeded role that lacks it**, so "a role lacking `marketdata:read` ->
403" cannot be reached by a login. The reachable 403 is `mfa_enrollment_required` for ENROL-ONLY. A pure
"authenticated, permission removed" 403 is a contract or unit test with an injected permission set
([A:X02]), and the question is raised to E09 in part 2 rather than a role being invented.

## 2. Scenarios by user story

Each case covers one or more scenarios of the story ticket (`S0n`) and names the user-story scenario (`US`) it
refines. All 24 `US` scenarios map to a case (table); the extra `S0n` scenarios, one `US` scenario with no `S0n`
twin (BB-003-08), one accessibility-note check (BB-002-06) and one PROPOSED case (BB-003-09) are the rest.

<!-- prettier-ignore -->
| Story | Ticket | `US` scenarios -> cases | Cases |
|---|---|---|---|
| US-DERIV-001 OI pane | E24-S01 | OI series -> 001-01; Interval alignment -> 001-02; Backfill failure -> 001-03 | BB-001-01..07 |
| US-DERIV-002 OI delta, quadrants | E24-S02 | Quadrants -> 002-01, 002-02; Absolute vs delta -> 002-03; Missing OI -> 002-04 | BB-002-01..06 |
| US-DERIV-003 Funding, countdown | E24-S03 | Current and countdown -> 003-01; History -> 003-08; Interval variation -> 003-03 | BB-003-01..09 |
| US-DERIV-004 Predicted, annualised | E24-S04 | Annualised -> 004-01, 004-02; Predicted -> 004-03; Unavailable -> 004-04 | BB-004-01..06 |
| US-DERIV-005 Liquidation feed | E24-S05 | Feed -> 005-01; No REST history -> 005-02; Burst -> 005-05 | BB-005-01..07 |
| US-DERIV-006 Liquidation bars | E24-S06 | Bars -> 006-01; Threshold filter -> 006-03; Empty history -> 006-04 | BB-006-01..06 |
| US-DERIV-007 Estimated zones | E24-S07 | Estimated zones -> 007-03; Methodology -> 007-04; Disabled by default -> 007-01 | BB-007-01..07 |
| US-DERIV-008 Basis, ratio | E24-S08 | Basis pane -> 008-01; Long/short ratio -> 008-03; Source unavailable -> 008-04 | BB-008-01..07 |

### 2.1 US-DERIV-001 Open interest pane (E24-S01)

Frames: `SCR-054/default-layout` (S54-1), `backfilling` (S54-71), `oi-backfill-failed` (S54-17), `oi-empty` (S54-18),
`stale-t1` / `stale-t2` (S54-72, S54-73). Routes: `GET /market/open-interest`; topic `ticker.{symbol}`.

**BB-001-01 Backfill then live [R] [A:Q02]** (US "OI series"; S01 "Backfill then live")

- Pre: SYM-8H, 5m chart, replay stack running the golden `btc_8h_slice`. Steps: open SCR-054; watch the network
  log; let three ticker frames arrive.
- Expected: one `GET /market/open-interest` (`interval=5min`) fills the history; later points come from
  `ticker.BTCUSDT` (`open_interest`, `open_interest_value`) with **no** second REST fetch; the series is one
  continuous line on the shared time axis. A point older than the last backfilled point is dropped, not drawn.

**BB-001-02 Interval alignment and the granularity note** (US "Interval alignment"; S01 same)

- Pre: as above. Steps: switch the chart from 5m to 1m; then to 15m.
- Expected: on 1m, points sit on bar boundaries and the pane shows `derivatives.oi.native_granularity`
  ("Native granularity 5 min"); on 15m the note is absent (the chart is no finer than the source). No point is
  interpolated between two stored points. `22` `OpenInterestPageMeta.coverage.native_interval` is `5min`.

**BB-001-03 Backfill failure [R] [A:Q02]** (US "Backfill failure"; S01 same; frame `oi-backfill-failed`)

- Pre: the REST backfill answers `503` (fault toggle FT-REST-503, defined in part 2). Steps: open SCR-054; wait for the
  failure; keep the ticker stream running; activate **Retry**.
- Expected: live OI keeps extending; the missing history is an explicit **gap**, never a straight line through
  it; `derivatives.oi.retry` ("Couldn't load OI history · Retry") with `derivatives.retry.last_loaded` shows the
  last successful time; the pane is never blank. Retry re-issues one request and, on success, fills the gap.
  Signal: a client error event carrying the status (S01 Observability).

**BB-001-04 Stale data** (S01 "Stale data"; D05 §6 row 5)

- Pre: ticker stream running. Steps: stop the ticker replay for more than 2 s (FT-FEED-PAUSE); resume it.
- Expected: the pane is shaded stale with the last-good time in text (`derivatives.chip.stale.t1`, then `.t2`);
  the shading clears on the next update. The state is conveyed in text, not only by shading. The 2 s threshold
  is S01's; the T1 / T2 tiers and their ages are D05 §6 row 5 (if #5617 merges as is). Signal: staleness.

**BB-001-05 No history recorded** (S01 "No history recorded"; frame `oi-empty`, S54-18)

- Pre: SYM-NEVER, the exchange returns no OI history. Steps: open SCR-054 for it.
- Expected: `derivatives.oi.empty` ("No open-interest history for SOLUSDT yet. Live OI is streaming now.") and the
  live series, not a blank canvas; `meta.coverage.from` and `to` are `null` (`22`), never `0`.

**BB-001-06 Table alternative [A:Q04]** (S01 "Table alternative")

- Pre: BB-001-01 state. Steps: with the keyboard only, reach and open the pane's table alternative.
- Expected: reachable without a pointer, visible focus; columns are the deck's `derivatives.table.oi.columns`
  with unit in each header; each row has timestamp, value, unit **and source** (`rest` or `ws_ticker`, SM-3).

**BB-001-07 No client-side computation** (S01 "No client-side computation")

- Pre: any state with a header readout (current OI, 1 h change). Steps: compare the readout with the raw
  response of `/market/metrics` (`open_interest`, `open_interest_delta`) or the ticker frame.
- Expected: every derived figure equals the server value formatted only; the unit comes from the descriptor,
  not from the component. A figure that differs from the response by more than formatting is a defect (P1).
  `/market/metrics` part: `PENDING #5341`.

### 2.2 US-DERIV-002 OI delta and quadrant colouring (E24-S02)

Frames: `SCR-054/oi-no-sample` (S54-16). Metric: `open_interest_delta`, `oi_price_quadrant`
(`long_buildup`, `short_covering`, `short_buildup`, `long_unwind`; `24` §7.2). Setting `deriv.oi.mode`
(default `absolute`) and `deriv.oi.quadrant_colouring` (default on) (D05 §10).

**BB-002-01 Quadrant classification renders** (US "Quadrants"; S02 "Quadrant classification renders")

- Pre: a window with a bar where price and OI both rose (golden `btc_8h_slice`). Steps: open it with
  quadrant colouring on; hover the bar.
- Expected: the bar is drawn as `long_buildup` with its distinct **pattern**; the legend (`derivatives.oi.key`)
  names it in words; the crosshair reads `derivatives.oi.crosshair` form ("OI Δ +1,240 BTC · long build-up").

**BB-002-02 All four quadrants [R] [A:Q02]** (US "Quadrants"; S02 "All four quadrants"; S02 "Colour is never the only encoding")

- Pre: a window holding all four combinations. Steps: view it in colour, then in greyscale, then in a
  colour-vision-deficiency simulation.
- Expected: `long_buildup`, `short_covering`, `short_buildup`, `long_unwind` are distinguishable in greyscale by
  pattern and by the text key; the pattern table is D03's, applied through one lookup (S02 technical notes).

**BB-002-03 Absolute versus delta** (US "Absolute vs delta toggle"; S02 "Absolute versus delta")

- Pre: OWNER. Steps: switch to delta-per-bar; reload; sign out and in as OWNER on a new session.
- Expected: the pane shows `open_interest_delta` per bar (`derivatives.oi.delta.label`), not the level; the choice
  survives the reload and the new session (`settings` key `deriv.oi.mode`); one `settings.change` audit row per
  change, with actor, role, before and after, `traceId` (section 0.2). Analytics `oi_panel.metric_toggled`
  carries `{mode, quadrant_colouring}` (D05 §12).

**BB-002-04 Missing OI for a bar [R] [SEM] [SEC]** (US "Missing OI for a bar"; S02 "Missing OI for a bar"; frame `oi-no-sample`, S54-16)

- Pre: golden `btc_8h_no_oi` (six 5 min samples dropped across one bar), quadrant colouring on.
- Steps: view the bar; read the legend; read the table alternative; compare with `/market/metrics`.
- Expected: the bar is drawn **neutral-hatched** and is **not classified**: no quadrant style, no ▲▼ tip, no
  quadrant name in the crosshair or the table (`derivatives.table.oi.unclassified`, "unclassified (no OI
  sample)"); the legend states the count (`derivatives.oi.unclassified`, "3 unclassified (no OI sample)"). The
  metrics response has `null` for the delta and the quadrant, **never `0`** (`PENDING #5341`). Full check: SM-4.

**BB-002-05 Crosshair readout** (S02 "Crosshair readout")

- Pre: BB-002-01 state. Steps: put the crosshair on a classified bar, then on an unclassified one.
- Expected: classified: the delta with its unit and the quadrant as text; unclassified: the delta absent and the
  unclassified wording, never "0".

**BB-002-06 Unclassified count is announced politely** (S02 Accessibility notes; D05 §9.2) [A:Q04]

- Pre: a screen reader on; the window of BB-002-04. Steps: pan so the unclassified count changes materially.
- Expected: one polite announcement (`derivatives.announce.unclassified`, PROPOSED in the deck; owner E24-D04),
  not one per frame. Wording is the deck's; if it stays PROPOSED the case records the string observed.

### 2.3 US-DERIV-003 Funding rate, history and countdown (E24-S03)

Frames: `countdown-1h-plus`, `countdown-under-1h`, `settlement` (S54-23 to S54-25), `funding-next-unknown` (S54-19),
`imminent-pay` / `imminent-receive` / `imminent-no-position` / `imminent-two-accounts` / `imminent-under-1-min` /
`imminent-stale` (S54-26 to S54-31), `funding-retry` (S54-37), `funding-empty` (S54-38). Metrics `funding_rate`,
`time_to_funding_ms`. Setting `deriv.funding.style` (D05 §10: `line`, PROPOSED).

**BB-003-01 Current rate and countdown, one value in two places [R] [SEM]** (US "Current and countdown"; S03 "Current rate and countdown")

- Pre: SYM-8H subscribed, clock offset 0. Steps: read the symbol header and the funding pane at the same
  instant, then again 30 s later.
- Expected: both show the same rate and the same time to the next settlement, character for character, because
  they are one component instance and one shared 1 s tick (D05 §11), not two timers. The target is the ticker's
  `next_funding_time_ms`, never a multiple of the interval (`22` as extended by #5699, if it merges as is).

**BB-003-02 Second accuracy under clock skew [R] [SEM]** (S03 "Second accuracy under clock skew"; US NFR)

- Pre: set the local clock **3 s ahead** of the exchange (FT-CLOCK-OFFSET); the synced offset is measured by
  the clock sync (E17). Steps: watch the countdown to zero.
- Expected: the countdown uses the synced offset and reaches `00:00:00` within **one second** of the true
  settlement time of the replay clock. A countdown that reaches zero three seconds early is P1 (SM-5).

**BB-003-03 History uses the instrument's interval, 4 h [R] [SEM]** (US "Interval variation"; S03 "History uses the instrument's interval")

- Pre: SYM-4H, a chart range of one UTC day. Steps: open the pane; read the interval wording; count the steps.
- Expected: the stepped history shows **six** settlements per day; the interval is stated
  (`derivatives.funding.interval_4h`, "settles every 4 h"); the countdown target is the next 4 h settlement; no
  `480` or "8 h" appears anywhere, including the session anchor. Full check: SM-6.

**BB-003-04 Imminent settlement, with and without a position** (S03 "Imminent settlement"; D05 §6 row 4)

- Pre: under 5 minutes to settlement; ACC-1 holds a BTCUSDT long, ACC-2 none. Steps: view the header in the
  frames below by switching the account context; then a state with no position.
- Expected: `imminent-pay` / `imminent-receive` show the charge line from `FundingEstimate` (server-computed,
  "about", predicted: `derivatives.countdown.imminent.pay`, PROPOSED words reading; the merged "≈" reading
  is `….q1_symbol`, D05-Q1); with **no position** the charge line is **omitted**, the plain line
  `derivatives.countdown.imminent.no_position` remains, and no "0 USDT" appears (`FundingEstimate` is `null`).
  Two accounts show the summed form (S54-29). Whether "≈" counts as words is D05's open question Q1, the owner's (D05 §8.3); the
  case records which reading is built and passes on either, if the string equals the deck row for that reading.

**BB-003-05 Source failure keeps the countdown running** (S03 "Source failure"; frame `funding-retry`, S54-37)

- Pre: the funding history request answers `503` (FT-REST-503). Steps: open the pane; wait; activate Retry.
- Expected: `derivatives.funding.retry` with `last_loaded`; not a blank chart; the countdown **keeps running**
  from the last known next-settlement time; Retry on success fills the history.

**BB-003-06 Settlement rollover [R] [SEM]** (S03 "Settlement rollover"; frame `settlement`, S54-25)

- Pre: FT-ROLLOVER: the replay clock set 20 s before a settlement on SYM-8H (the `server_time` and
  `funding_history_BTCUSDT_8h` pair, fixture plan in part 2). Steps: watch through zero without touching the page.
- Expected: at zero the pane requests the newly settled rate, **appends** it to the history, and restarts the
  countdown for the next interval with no manual refresh; the header and pane stay equal (BB-003-01); the new
  point is shown as **settled** (SM-2), not as the previous predicted value. Full check: SM-5.

**BB-003-07 Announcement policy [A:Q04]** (S03 "Announcement policy"; D05 §9.2 LR-n)

- Pre: a screen reader on; countdown under 6 minutes. Steps: listen through the last 6 minutes.
- Expected: spoken **only** at 5 minutes and 1 minute (`derivatives.announce.funding.5m`, `.1m`, and the
  `.no_position` forms when flat); at 300 000 ms and 60 000 ms on the fake clock; never every second.

**BB-003-08 History renders as stepped line or bars** (US "History"; S03 scope: `deriv.funding.style`)

- Pre: SYM-8H, a 3-day chart range. Steps: switch the style between line and bars; reload.
- Expected: settled history over the chart's range on the shared time axis; the choice persists; the crosshair
  reads `derivatives.funding.crosshair` ("+0.0100 % · settled 08:00 UTC"). The default `line` is PROPOSED (D05
  §10; owner E24-D02). Table alternative lists settlement timestamps, rates and units (S03 scope), checked as
  BB-001-06 does.

**BB-003-09 The interval changes while the pane is open [SEM]** (US "Interval variation"; D02 frame "Interval changed")

- Pre: a symbol whose `fundingInterval` changes in instrument info mid-session (FT-INTERVAL-CHANGE: an
  `instruments_after` copy with the interval changed; the corpus pair holds 480 in both; part 2). Steps: keep SCR-054 open across the change.
- Expected: the header and pane restate the new interval (D02 sample: "settles every 1 h · changed 08:04 UTC");
  annualisation switches factor with it; settled points before the change keep their own spacing. Status:
  **PROPOSED**, awaits D02 G5 (the frame is tagged "awaits G5"); owner E24-S03 (#778). Not run until G5 lands.

### 2.4 US-DERIV-004 Predicted and annualised funding (E24-S04)

Frames: `funding-predicted` (S54-33), `funding-predicted-na` (S54-22). Setting `deriv.funding.annualised` (default off).
Item flags `predicted`, `estimated` (`22`); with #5699, `annualised_pct`.

**BB-004-01 Annualised toggle, formula in the tooltip** (US "Annualised toggle"; S04 "Annualised toggle")

- Pre: SYM-8H. Steps: enable annualisation; open the tooltip.
- Expected: rates and the history series switch to the annualised value **from the server**
  (`annualised_pct`, never a client multiplication; if #5699 merges as is); the tooltip shows the formula with the
  symbol's numbers (`derivatives.tooltip.funding.annualised`: "0.0100 % × (525600 / 480) = 10.95 % p.a.").

**BB-004-02 Annualisation is interval-correct, 4 h [R] [SEM]** (S04 "Annualisation is interval-correct")

- Pre: SYM-4H, rate `0.0001`. Steps: enable annualisation; read the value and the tooltip.
- Expected: factor `525600/240`, **not** `525600/480`: `0.0001 x 2190 x 100 = 21.9 %`. The tooltip substitutes
  `240`. A value of 10.95 % is the 8 h factor on a 4 h symbol: P1 (SM-6).

**BB-004-03 Predicted is visually and textually distinct [R] [SEM] [SEC]** (US "Predicted rate"; S04 "Predicted is visually and textually distinct")

- Pre: the current unsettled rate (item `predicted: true`, `estimated: true`). Steps: view it in colour and in
  greyscale; read its text; activate the badge; read the table alternative.
- Expected: a style that differs from settled points in greyscale; the word **predicted** in text
  (`derivatives.funding.predicted`, "predicted (estimated)"); a CMP-227 EstimatedBadge that links the SCR-058
  methodology; the table has a settled / predicted column as text. Predicted styled as settled is P1 (SM-2).
  Signal: the flag trace (`TM` §5); no metric exists, so it is an observability finding if missed.

**BB-004-04 Predicted unavailable [R] [SEM]** (US "Unavailable"; S04 "Predicted unavailable"; frame `funding-predicted-na`, S54-22)

- Pre: a window with no predicted rate published (FT-NO-PREDICTED, the ticker frame without `fundingRate`).
  Steps: view the header and the pane; wait for another ticker frame; compare to an earlier predicted value.
- Expected: the field reads `n/a` (`derivatives.header.funding.na`, "Funding n/a · settles every 8 h"); **no point
  is added** to the history; **no previously seen predicted value is reused or carried forward**. Full check: SM-2.

**BB-004-05 Toggle persistence** (S04 "Toggle persistence")

- Pre: BB-004-01 state. Steps: reload; switch symbol from SYM-8H to SYM-4H.
- Expected: annualisation restored; the tooltip shows the formula for the **current** symbol (480, then 240).

**BB-004-06 Screen-reader name [A:Q04]** (S04 "Screen reader")

- Pre: a screen reader on; the predicted value focused. Steps: read it out.
- Expected: the accessible name contains both "predicted" and "estimated" as words ("≈" does not count, D05 §8.3).

### 2.5 US-DERIV-005 Liquidation feed (E24-S05)

Routes: `GET /market/liquidations` (`PENDING #5273`); topic `liquidations.{symbol}` with option `min_notional_usd`
(`23` §14.9; at most one push per symbol per 500 ms). Frames: `liq-partial` (S54-45), `liq-cascade` (S54-43),
`liq-cascade-partial` (S54-44), `liq-never-recorded` (S54-46), `liq-history-failed` (S54-49), `liq-coverage-retry` (S54-50).

**BB-005-01 Feed renders prints** (US "Feed"; S05 "Feed renders prints")

- Pre: `liquidations.BTCUSDT` subscribed, fixture `allLiquidation_BTCUSDT_burst` (fixture plan, part 2). Steps: watch ten
  prints arrive.
- Expected: each print shows side **in text** (the liquidated side, per `derivatives.liq.legend`, never "Buy" /
  "Sell"), size, price, notional and time, in the columns of `derivatives.liq.feed.columns`.

**BB-005-02 No REST history is disclosed** (US "No REST history"; S05 "No REST history is disclosed")

- Pre: BTCUSDT. Steps: open the feed; read the pane.
- Expected: `derivatives.liq.completeness` ("Bybit publishes liquidations in 500 ms batches; every print is
  included — history is limited to what the recorder captured"); counts are described as **lower bounds** (the
  batch `note`, `TM` D7).

**BB-005-03 Partial history chip** (S05 "Partial history chip"; frame `liq-partial`, S54-45)

- Pre: SYM-REC-2H; request a 24 h window. Steps: open the pane.
- Expected: the chip names the first available timestamp (`derivatives.liq.partial_chip`, "No history before 09:14
  UTC. Bybit publishes no liquidation history; earlier prints were not recorded."); the feed shows only the
  recorded window. A window starting on another day uses `…not_today`. Full check: the coverage cases in part 2.

**BB-005-04 Empty is never mistaken for zero [R] [SEM] [SEC]** (S05 "Empty is never mistaken for zero")

- Pre: a window entirely outside coverage (`meta.coverage.no_coverage: true`). Steps: open it; then the same
  for SYM-NEVER (frame `liq-never-recorded`).
- Expected: the no-coverage state with its reason (`derivatives.liq.before_coverage`, "Not recorded before 09:14
  UTC — this is not 'no liquidations'", or `derivatives.liq.never_recorded`); never an empty list that reads as
  "no liquidations". Full check: SM-1.

**BB-005-05 Burst coalescing [R] [A:Q03]** (US "Burst"; S05 "Cascade")

- Pre: the burst fixture replayed at its recorded rate. Steps: watch the feed during the burst.
- Expected: prints coalesce into **250 ms buckets** with a burst-rate counter; no frames dropped; the DOM node
  count stays bounded (at most 40 bucket rows virtualised; D05 §11). Full cascade cases: part 2 (CS-01..).

**BB-005-06 Threshold filter** (S05 "Threshold filter")

- Pre: a subscription with `min_notional_usd` set. Steps: set it, watch, clear it.
- Expected: smaller prints are excluded **server-side** (the subscription option, not a client filter); the
  active filter is stated in the pane (`derivatives.liq.filter`, "Showing prints ≥ 50,000 USDT").

**BB-005-07 Announcements under load [A:Q04]** (S05 "Announcements under load"; D05 §9.2)

- Pre: a screen reader on; the cascade replay. Steps: listen for 30 s.
- Expected: at most **one** summary per 5 000 ms naming the burst rate (`derivatives.announce.cascade.longs` /
  `.shorts` / `.both`), nothing per print.

### 2.6 US-DERIV-006 Liquidation bars (E24-S06)

Metric `liquidation_notional` (`side=long|short|both`) via `/market/metrics` (`PENDING #5341`) and the recorded
prints. Settings `deriv.liq.min_notional_usd` (default `0`), `deriv.liq.mode` (default `bars`). Frames
`liq-history-failed` (S54-49), `liq-cascade-partial` (S54-44).

**BB-006-01 Split histogram** (US "Bars"; S06 "Split histogram")

- Pre: SYM-8H with recorded prints on both sides. Steps: open the liquidation sub-pane.
- Expected: per-bar long and short notional as a split histogram, both sides labelled **in text**
  (`derivatives.liq.legend`: "Short liquidated ▲ above · Long liquidated ▼ below"); readout with units.

**BB-006-02 Bucketing alignment across a UTC day** (S06 "Bucketing alignment")

- Pre: a 1h chart spanning 00:00 UTC. Steps: sum the visible buckets; compare with the recorded prints for the
  window.
- Expected: buckets align to the bar grid **and** the day boundary; the sum of the buckets equals the sum of the
  recorded prints: none counted twice, none dropped.

**BB-006-03 Threshold filter** (US "Threshold filter"; S06 "Threshold filter")

- Pre: OWNER. Steps: set a minimum notional (range PROPOSED 0 to 1 000 000 000 USDT, D05 §10; owner E24-D03, its G3, with the message `derivatives.settings.range`); reload.
- Expected: smaller events are excluded **server-side**; the filter is stated in the legend; it persists
  (`deriv.liq.min_notional_usd`); an out-of-range value is refused with `derivatives.settings.range`.

**BB-006-04 Empty history boundary [R] [SEM]** (US "Empty history"; S06 "Empty history boundary")

- Pre: SYM-REC-2H. Steps: open the 1h chart for the last day.
- Expected: bars exist only for the recorded 2 hours; a vertical **boundary marker** labels the first available
  timestamp (`derivatives.liq.boundary`, "Recorded from 09:14 UTC"). Full check: the coverage cases in part 2.

**BB-006-05 Zero versus unknown [R] [SEM] [SEC]** (S06 "Zero versus unknown")

- Pre: SYM-REC-2H, a bar inside the recorded window with no liquidations, and a bar before the boundary.
- Steps: compare the two bars, the crosshair and the table.
- Expected: the first is a genuine **zero** (drawn, readout `0` with unit); the second is **unknown** (not
  drawn as zero; text "not recorded"). `/market/metrics`: inside the window `"0"`, before it `null`. Full check: SM-1.

**BB-006-06 Mode switch, neither mode estimated** (S06 "Mode switch")

- Pre: recorded data. Steps: switch bars to the realised-density heatmap and back; reload.
- Expected: the same recorded data in both (`derivatives.liq.heatmap.legend`, "Realised liquidations
  (recorded)"); the mode persists; **neither** carries an "(estimated)" badge: the heatmap is exact recorded
  density, not the zone estimate of S07.

### 2.7 US-DERIV-007 Estimated liquidation zones (E24-S07)

Setting `deriv.liq.zones_enabled` (default **off**). Frames `zones-acknowledgement`, `zones-enabled` (D02 §9).
The one area where a missing label is a security finding (S07 Security notes; `TM` D4).

**BB-007-01 Disabled by default [R] [SEC]** (US "Disabled by default"; S07 "Disabled by default")

- Pre: a fresh account (no `settings` row). Steps: open SCR-054; read the network log and the DOM.
- Expected: zones off; **no zone geometry requested or rendered**; the toggle shows off.

**BB-007-02 Enabling requires acknowledgement, audited [R] [SEC]** (S07 "Enabling requires acknowledgement")

- Pre: BB-007-01 state. Steps: turn zones on; read the dialog; cancel; turn on again; confirm.
- Expected: the dialog states the estimate is not exchange data (`derivatives.zones.dialog.callout`, "This is an
  estimate, not exchange-provided fact."); **Cancel** leaves zones off and writes nothing; **Confirm**
  (`derivatives.zones.dialog.confirm`, "Show estimated zones") enables them and writes **one audit row** with
  actor, role, action, before and after, `traceId`. A Confirm that enables with no audit row is a defect (P1).

**BB-007-03 Badge on every zone [R] [SEM] [SEC] [A:Q02]** (US "Estimated zones"; S07 "Badge on every zone")

- Pre: zones enabled. Steps: tab through every zone and the legend row; read each accessible name.
- Expected: every zone **and** the legend row carry a focusable CMP-227 EstimatedBadge whose name contains the
  word "estimated"; each is a band label like "82,400–82,520 (estimated)" (D02 `zones-enabled`) with hatch, never a
  solid fill; Enter opens SCR-058's liquidation-cluster section. A zone with no badge is **P1 and a security
  finding**, not a UI defect.

**BB-007-04 Methodology disclosure** (US "Methodology disclosure"; S07 "Methodology disclosure")

- Pre: zones enabled. Steps: open the drawer from a badge.
- Expected: the method, its inputs, **which inputs are assumed** rather than exchange-published, the thresholds
  in force, the failure modes, and the sentence "this is an estimate, not exchange-provided fact".

**BB-007-05 Missing badge fails the build** (S07 "Missing badge is a P1") [A:Q02]

- Pre: a build with the badge removed from a zone (mutation). Steps: run the catalogue-level badge test.
- Expected: the test fails and the build is rejected. Manual part: confirm the test exists and fails on the mutation.

**BB-007-06 Not available to automated actions [SEC]** (S07 "Not available to automated actions")

- Pre: the rule editor (E35); a rule condition on the zone metric. Steps: save the rule.
- Expected: rejected by default with an explanation; no rule can act on an estimated zone without an explicit
  override. Owner of the rule-side behaviour: E35; here only the observable refusal.

**BB-007-07 Method descoped** (S07 "Method descoped")

- Pre: only if E24-K01 concluded no method is defensible (its finding decides; the ticket JSON is the record).
  Steps: open SCR-054.
- Expected: no zone overlay; the **toggle is absent**, not disabled; the realised-liquidation density stays; the
  descoping is recorded on the epic. Status: **PROPOSED applicability**, owner E24-K01 / the epic; mark "n/a" in
  the run if a method shipped.

### 2.8 US-DERIV-008 Basis, mark/index and long/short ratio (E24-S08)

Metrics `basis`, `premium_pct` (`source=last|mark`; `PENDING #5341`). Settings `deriv.basis.source` (default `mark`),
`deriv.basis.annualised` (default off, PROPOSED). Frames `basis-retry` (S54-8), `ratio-unavailable` (S54-9).

**BB-008-01 Basis pane** (US "Basis pane"; S08 "Basis pane")

- Pre: SYM-8H with ticker snapshots. Steps: open the basis pane; toggle annualised.
- Expected: mark, index and their spread render together with units on every figure (`derivatives.basis.pane`,
  "Basis % (mark − index)"); the annualised toggle changes the value, with the factor from the server.

**BB-008-02 Source selector** (S08 "Source selector")

- Pre: BB-008-01 state. Steps: switch `source` from last to mark; reload.
- Expected: series and readout **recompute server-side** (a new `/market/metrics` request with
  `params={"basis":{"source":"mark"}}`, `PENDING #5341`); the choice persists; the active source is stated
  (`derivatives.header.basis.source.mark` / `.last`).

**BB-008-03 Long/short ratio at its native period** (US "Long/short ratio"; S08 "Long/short ratio")

- Pre: the adapter supplies the ratio for the symbol. Steps: open the ratio.
- Expected: the global account ratio at its native period with the period **in words** ("5 min,
  exchange-published"). PROPOSED applicability: if the adapter cannot supply it for USDT perps, BB-008-05 applies
  and the limitation is recorded in E24-T05 (S08 scope).

**BB-008-04 Source unavailable, retry** (US "Source unavailable"; S08 "Source unavailable"; frame `basis-retry`, S54-8)

- Pre: the ratio source answers `503` (FT-REST-503). Steps: open the pane; Retry.
- Expected: `derivatives.basis.retry` with `last_loaded`; not a blank chart, **not a flat line, not zero**.

**BB-008-05 Ratio not published** (S08 "Ratio not published"; frame `ratio-unavailable`, S54-9)

- Pre: the exchange publishes no ratio for the instrument. Steps: open the pane.
- Expected: the surface **states the source is unavailable**; no empty or fabricated series.

**BB-008-06 Axis and crosshair sync [A:Q02]** (S08 "Axis and crosshair sync")

- Pre: the price pane and the basis series. Steps: pan, zoom, move the crosshair on price.
- Expected: the basis series follows the same time axis; the crosshair readout of basis and premium updates in
  lockstep with price.

**BB-008-07 No client-side computation** (S08 "No client-side computation")

- Steps: compare basis, premium and annualised basis with the `/market/metrics` values.
- Expected: formatting only (as BB-001-07). `PENDING #5341`.

### 2.9 Panel-wide cases (SCR-054 as a whole)

These belong to no single story; their ids are `BB-PNL-nn` (stable like the rest). Source: D05 §6 rows 5, 6, 9, 14,
§10, §11, §12 (if #5617 merges as is), and the global stale convention #4 (S01 "Stale data").

**BB-PNL-01 Default layout** (D05 §6 row 6; frame `default-layout`, S54-1)

- Pre: OWNER, fresh account, SYM-8H. Steps: open SCR-054.
- Expected: OI, funding and liquidations sit together under the price pane on one time axis; the nine `deriv.*`
  keys are at the D05 §10 defaults (`oi.mode` `absolute`, `oi.quadrant_colouring` on, `liq.mode` `bars`,
  `liq.min_notional_usd` `0`, `liq.zones_enabled` **off**, `funding.style` `line` (PROPOSED), `funding.annualised`
  off, `basis.source` `mark`, `basis.annualised` off (PROPOSED)). A default that differs is a defect.

**BB-PNL-02 Stale precedence per sub-pane [R]** (D05 §6 row 5 and its precedence line)

- Pre: all sub-panes live. Steps: stop the feed to one sub-pane at a time, then disconnect the socket, then fail
  one REST source while the feed is stale; record what each pane shows.
- Expected: per sub-pane, first match wins, in the order disconnected, stale T2, stale T1, Delayed, the source's
  retry band, its loading band; the history markers and the partial chip keep their own slots; the last-good time
  is in text. One pane's staleness does not shade another's. Signal: staleness.

**BB-PNL-03 Units and side on every figure, narrow width** (D05 §6 row 9; frame `narrow-360`, S54-63)

- Pre: a 360 px-wide window. Steps: open every sub-pane and read every figure.
- Expected: every figure carries its unit and, for liquidations, the liquidated side as a word; nothing is clipped
  to the point a number loses its unit. A bare number is P1 when its unit changes its meaning (SM-6, severity rules in part 2).

**BB-PNL-04 Collapse and restore** (S01 scope "collapse/expand persistence"; `derivatives.announce.collapse`)

- Pre: OWNER. Steps: collapse the OI pane; reload; restore.
- Expected: the state persists; one polite announcement each way ("OI pane collapsed" / "OI pane restored"); the
  other panes keep their own state.

**BB-PNL-05 Disconnected and delisted** (D05 §6 row 5; frames `disconnected`, `delisted`, S54-75, S54-76)

- Pre: FT-SOCKET-DROP, then a symbol delisted in instrument info. Steps: observe each.
- Expected: `disconnected` shows the last-good time and recovers on reconnect with REST reconciliation (the
  exchange is the truth); `delisted` is a distinct state, not a stale one, and a stale rate is never shown as
  current. `derivatives.funding.unavailable` ("Funding unavailable for SOLUSDT: the instrument is not available
  right now.") is the funding wording.

**BB-PNL-06 Analytics carry no identifiers** (D05 §12)

- Pre: the analytics sink visible. Steps: trigger `oi_panel.metric_toggled`, `oi_panel.interval_changed`,
  `liquidation.print_clicked`, `funding.countdown_alert_set`.
- Expected: the four events fire when D05 §12 says, with the properties it names (`{mode, quadrant_colouring}`,
  `{interval}` PROPOSED); **no property carries an account id or a position**.

**BB-PNL-07 Reduced motion** (D05 §7 M-01 to M-07)

- Pre: `prefers-reduced-motion` on. Steps: change an OI value, receive a print, enter and leave stale, collapse.
- Expected: M-02 and M-03 and M-05 are removed or instant as the table says; the countdown tick and bucket
  arrival are cuts either way. A transition that remains is a P3 deviation.

### 2.10 Route authentication negatives: 401 and 403 on every route (D11, AC10) [SEC]

`TM` D11 (:82, :162) requires, on every E24 operation: no token -> 401, a session without the permission -> 403.
`22` declares `x-rbac: { permissions: [marketdata:read], scope: none }` on all four. Run each row with the three
principals below; the status is the **contract's** (`22` `Unauthorized` / `Forbidden`), the body is
`application/problem+json`, and **no market data appears in any 401 or 403 body**. Owner of the automation:
E24-X02 (AC10); this plan runs them manually once (ticket Security notes).

<!-- prettier-ignore -->
| ID | Route or topic | NO-TOKEN / BAD-TOKEN / EXPIRED-TOKEN | ENROL-ONLY | Status |
|---|---|---|---|---|
| NG-01 | `GET /market/open-interest?symbol=BTCUSDT` | 401 `unauthenticated` | 403 `mfa_enrollment_required` | runnable |
| NG-02 | `GET /market/funding?symbol=BTCUSDT` | 401 | 403 `mfa_enrollment_required` | runnable |
| NG-03 | `GET /market/liquidations?symbol=BTCUSDT` | 401 | 403 `mfa_enrollment_required` | `PENDING #5273` |
| NG-04 | `GET /market/metrics?symbol=BTCUSDT&metric=open_interest` | 401 (`22` lists no `401` here: open question to E24-T04, in part 2) | 403 | `PENDING #5341` |
| NG-05a | WS `ticker.BTCUSDT`: a `sub` before `auth_ok`; an `auth` with a malformed token or one **already expired at `auth`** | `err not_authenticated` for the `sub`; `err auth_failed` for the `auth` (`23` §4.3, error table) | `auth` refused: `bye mfa_enrollment_required`, close `4403`, an `auth.mfa_enrollment_required` audit row; no `sub` is reachable | runnable |
| NG-05b | WS `ticker.BTCUSDT`: a session that **expires mid-session** and is not re-`auth`ed | `bye token_expired`, close `4401`; the subscription is not continued on the expired identity (`23` §4.3) | n/a | runnable |
| NG-06a | as NG-05a on `liquidations.BTCUSDT` | as NG-05a | as NG-05a | `PENDING #5273` |
| NG-06b | as NG-05b on `liquidations.BTCUSDT` | as NG-05b | n/a | `PENDING #5273` |
| NG-07 | an idle-locked session on each of NG-01..04 | 401 `session_idle_locked`, unlock via `POST /auth/unlock` | n/a | runnable |
| NG-08 | **a session with the permission removed** (authenticated, `marketdata:read` absent) on NG-01..04 and, after `auth_ok`, on NG-05a and NG-06a | n/a | REST 403; WS `forbidden` on the `sub` ("missing permission for the topic family", `23` error table) | [A:X02] only: no seeded role lacks it (section 1; open question to E09, in part 2) |

Steps for NG-01..04: issue the request with each principal; record status, `type`, `code`, and that the body
holds no series, no `items`, no coverage. Steps for NG-05a and NG-06a: open a socket, send `sub` before `auth`, then `auth` with a malformed token, then with one
already expired, then as ENROL-ONLY; record the `err` or `bye` frame, the close code and that no `snap` arrives. Steps for
NG-05b and NG-06b: authenticate, advance the fake clock past `token_expires_at_ms` with no re-`auth`, and record the `bye`
and `4401` (the gateway checks the expiry before every frame and on its own timer). Expected for all: the status above, a problem body,
no data, and **no state change** (the read stays read-only, `TM` §6). Signal: none exists for 401/403 in the five
metrics: log a missing authentication-failure log line (`traceId`, no token, C-12.6) as an observability finding.
**An endpoint that answers 200 without a token is P0 (security breach, `03` §11.3).**
