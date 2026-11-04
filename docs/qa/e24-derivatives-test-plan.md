# E24 Derivatives metrics — black-box test plan and exploratory charters

Ticket: E24-Q01 (#771). Status: v0.2, slices 1 and 2 of 3 (sections 0 to 10 and the two charters); the closing slice adds the run records and
re-pins the inputs. Draft for the QA lead and an E24 developer to review. Nothing here has been
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
- `BQ n` = numbered question n of the pre-stage comment on #771 (comment 6624000873), whose Recommends this plan follows.
- Copy strings are quoted from the deck by key (`derivatives.oi.native_granularity`), never retyped from memory.
  A tester compares what is on screen to the deck byte for byte; a deviation is a defect (section 7).

**Never invent behaviour.** Where the specification is silent the case says **PROPOSED** and names the owner of
the answer; the open ones are collected in section 10 as questions against the implementing tickets, not guessed.

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
  E24-Q04 and is not duplicated here; the cases that must be repeated with a screen reader are listed in 10.2.

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
| #5273 `feat/e24-liquidations` | `9bf4ec8c2bd5a2ca067c5a77726f63f0f2c0d0dd` | the `/market/liquidations` handler and the cascade fixtures (section 8) |

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
- Tags: **[R]** is in the regression pack for E24-Q05 (10.1); **[A:Q02]**, **[A:X02]**, **[A:Q03]**, **[A:Q04]**
  mean the named ticket automates it and this plan keeps only the manual run; **[SEM]** is one of the six
  semantic checks the ticket names (section 3); **[SEC]** carries a security abuse case or a D11 negative.
- Status words: `PENDING #n` (cannot run until that PR merges); `EXPECTED-BY-MODEL (22 silent)` (the result is the
  threat model's and the contract does not state it yet); `PROPOSED` (the specification is silent; owner named).
- Every case is Pre -> Steps -> Expected. A tester who did not write the plan must reach the precondition using
  only sections 1 and 8, and judge pass or fail without asking.
- Optional **Signal:** names the telemetry that should have caught a defect found by the case, from the five
  metrics of `TM` §8 (`deriv_upstream_schema_rejected_total`, `deriv_range_rejected_total`,
  `deriv_sub_cap_rejected_total`, `deriv_fanout_dropped_total`, `deriv_source_mix_blocked_total`) plus the
  staleness signal. A defect with no signal is reported as an observability finding in the run record.

### 0.6 Section map

2 holds the 55 per-story cases (2.1 to 2.8), the panel-wide cases (2.9) and the route negatives (2.10). Section 3
the six semantic checks, 4 boundaries and the 13 abuse cases, 5 recorder-bounded history and coverage gaps, 6 the
cascade, 7 severity, 8 fixtures and data, 9 the charters, 10 the regression pack, hand-offs, questions and
traceability.

## 1. Seeded actors, symbols and data (summary; full plan in section 8)

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
| SYM-REC-2H | BTCUSDT with a recorder that started 2 hours before the session (`btc_8h_recorder_gap` family, section 8) |

**Finding for the 403 negatives (BQ 16).** `21` `role_permissions` and `04` §7.2.1 give `marketdata:read` to every
role: Owner, Manager and Viewer. There is **no seeded role that lacks it**, so "a role lacking `marketdata:read` ->
403" cannot be reached by a login. The reachable 403 is `mfa_enrollment_required` for ENROL-ONLY. A pure
"authenticated, permission removed" 403 is a contract or unit test with an injected permission set
([A:X02]), and the question is raised to E09 in section 10 rather than a role being invented.

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

- Pre: the REST backfill answers `503` (fault toggle FT-REST-503, section 8). Steps: open SCR-054; wait for the
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
  `funding_history_BTCUSDT_8h` pair, section 8). Steps: watch through zero without touching the page.
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
  `instruments_after` copy with the interval changed; the corpus pair holds 480 in both, section 8). Steps: keep SCR-054 open across the change.
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

- Pre: `liquidations.BTCUSDT` subscribed, fixture `allLiquidation_BTCUSDT_burst` (section 8). Steps: watch ten
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
  recorded window. A window starting on another day uses `…not_today`. Full check: section 5.

**BB-005-04 Empty is never mistaken for zero [R] [SEM] [SEC]** (S05 "Empty is never mistaken for zero")

- Pre: a window entirely outside coverage (`meta.coverage.no_coverage: true`). Steps: open it; then the same
  for SYM-NEVER (frame `liq-never-recorded`).
- Expected: the no-coverage state with its reason (`derivatives.liq.before_coverage`, "Not recorded before 09:14
  UTC — this is not 'no liquidations'", or `derivatives.liq.never_recorded`); never an empty list that reads as
  "no liquidations". Full check: SM-1.

**BB-005-05 Burst coalescing [R] [A:Q03]** (US "Burst"; S05 "Cascade")

- Pre: the burst fixture replayed at its recorded rate. Steps: watch the feed during the burst.
- Expected: prints coalesce into **250 ms buckets** with a burst-rate counter; no frames dropped; the DOM node
  count stays bounded (at most 40 bucket rows virtualised; D05 §11). Full cascade cases: section 6 (CS-01..).

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
  timestamp (`derivatives.liq.boundary`, "Recorded from 09:14 UTC"). Full check: section 5.

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
  to the point a number loses its unit. A bare number is P1 when its unit changes its meaning (SM-6, section 7).

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
| NG-04 | `GET /market/metrics?symbol=BTCUSDT&metric=open_interest` | 401 (`22` lists no `401` here: see Q-4) | 403 | `PENDING #5341` |
| NG-05a | WS `ticker.BTCUSDT`: a `sub` before `auth_ok`; an `auth` with a malformed token or one **already expired at `auth`** | `err not_authenticated` for the `sub`; `err auth_failed` for the `auth` (`23` §4.3, error table) | `auth` refused: `bye mfa_enrollment_required`, close `4403`, an `auth.mfa_enrollment_required` audit row; no `sub` is reachable | runnable |
| NG-05b | WS `ticker.BTCUSDT`: a session that **expires mid-session** and is not re-`auth`ed | `bye token_expired`, close `4401`; the subscription is not continued on the expired identity (`23` §4.3) | n/a | runnable |
| NG-06a | as NG-05a on `liquidations.BTCUSDT` | as NG-05a | as NG-05a | `PENDING #5273` |
| NG-06b | as NG-05b on `liquidations.BTCUSDT` | as NG-05b | n/a | `PENDING #5273` |
| NG-07 | an idle-locked session on each of NG-01..04 | 401 `session_idle_locked`, unlock via `POST /auth/unlock` | n/a | runnable |
| NG-08 | **a session with the permission removed** (authenticated, `marketdata:read` absent) on NG-01..04 and, after `auth_ok`, on NG-05a and NG-06a | n/a | REST 403; WS `forbidden` on the `sub` ("missing permission for the topic family", `23` error table) | [A:X02] only: no seeded role lacks it (section 1, Q-5) |

Steps for NG-01..04: issue the request with each principal; record status, `type`, `code`, and that the body
holds no series, no `items`, no coverage. Steps for NG-05a and NG-06a: open a socket, send `sub` before `auth`, then `auth` with a malformed token, then with one
already expired, then as ENROL-ONLY; record the `err` or `bye` frame, the close code and that no `snap` arrives. Steps for
NG-05b and NG-06b: authenticate, advance the fake clock past `token_expires_at_ms` with no re-`auth`, and record the `bye`
and `4401` (the gateway checks the expiry before every frame and on its own timer). Expected for all: the status above, a problem body,
no data, and **no state change** (the read stays read-only, `TM` §6). Signal: none exists for 401/403 in the five
metrics: log a missing authentication-failure log line (`traceId`, no token, C-12.6) as an observability finding.
**An endpoint that answers 200 without a token is P0 (security breach, `03` §11.3).**

## 3. Semantic checks (the defects automation misses)

The epic's defects are mostly **semantic**: a number that is plausible but wrong, or an absence that reads as a
zero (ticket Context). Each check below is run **across the layers** that carry the fact (engine value, REST
body, WS frame, DOM text, table alternative, announcement) and passes only if every layer agrees. The flag trace
is `TM` §5: engine -> REST schema -> WS envelope -> component props -> DOM. A check that fails reports **the
layer where the fact was lost**, which is the finding's location (section 7).

### SM-1 Zero versus unknown (liquidations, open interest, funding) [SEM] [SEC]

- Why: presenting "no recorded data" as "no liquidations" is `TM` D-class (T) (S05 / S06 Security notes). Cases:
  BB-005-04, BB-006-04, BB-006-05, BB-002-04, CV-01..CV-04.
- Fixture: FX-RECORDER-GAP (the recorder started 2 h ago, with one mid-window gap), section 8.
- Steps:
  1. `GET /market/liquidations` for a window **inside** coverage with no prints, then for a window **before**
     `first_available_ts`, then for SYM-NEVER. Record `items`, `meta.coverage.no_coverage`, `first_available_ts`.
  2. `GET /market/metrics?metric=liquidation_notional` for a bar inside the recorded window with no prints and
     a bar before the boundary (`PENDING #5341`).
  3. The same two bars in the pane, the crosshair and the table alternative (D05 §9.3: "zero and unknown as words").
  4. Repeat for `open_interest_delta` on a bar with no OI sample (BB-002-04) and for funding before the first
     stored settlement (`funding-empty`).
- Expected: inside coverage an empty page has `no_coverage: false` and the bar reads a **genuine zero** (`"0"`,
  drawn, "0" with its unit); before coverage `no_coverage: true` and the bar is **unknown** (`null`, not drawn as
  zero, worded "not recorded", never "0"). OI: `null`, never `0`. Funding: an empty page with `no_coverage: false`
  means no funding settled in the window (`22` as extended by #5699, if it merges as is). **Never** a
  zero-height bar, an empty list or a flat line for an unknown span.
- Fail: any layer that shows unknown as zero, or zero as unknown. P1 (section 7). Signal: none exists; report a
  missing signal as an observability finding.

### SM-2 Predicted versus settled funding [SEM] [SEC]

- Why: `TM` D3 (risk High): a predicted rate rendered as settled. Cases: BB-003-06, BB-004-03, BB-004-04, BB-PNL-05.
- Oracle by layer: REST item flags `predicted` and `estimated` (`22` `/market/funding`); with #5699 (if it
  merges as is) `annualised_pct` is also set on the predicted item, "an estimate as that item is". **WS: no
  oracle in the contract.** `23` §14.8 `TickerUpdate` carries `funding_rate` and `next_funding_time_ms` with no
  predicted or settled flag, and `additionalProperties` is false (`TM` gap G2, still open at the pin). The case
  therefore asserts the model's fallback (`TM` §5, "document that ticker funding is always predicted"):
  **PROPOSED**, owner E24-S03 / E24-T02, depends on G2's resolution (Q-3).
- Steps:
  1. Take the fixture's predicted item (`predicted: true`, `estimated: true`) and its settled neighbour. Follow
     each from `/market/funding` to the DOM; record the word, the badge, the style (colour and greyscale).
  2. **Flag-stripped payload:** replay the same response with `predicted` and `estimated` removed (a mutated copy
     made at run time, never committed). Record what the pane does.
  3. **Rollover:** run BB-003-06; compare the point appended at settlement with the previous predicted value.
  4. **Unavailable:** BB-004-04; confirm `n/a` and no carried-forward value.
- Expected: a predicted value always has the word "predicted" and "estimated" in text and the distinct style, and
  appears in the settled series **never**; a settled point never carries the badge; with the flags stripped the
  pane does **not** render the item as settled (S04 Security notes: it "fails closed"; the exact rendering is
  PROPOSED, owner E24-S04); after a rollover the appended point is the REST-settled value, not the earlier
  prediction; `n/a` adds no point and reuses no value.
- Fail: predicted styled or worded as settled, at any layer: P1. A missing "predicted" word on a predicted
  string is a provenance defect (D05 §8.3: refused wordings include "exchange-published" and "Bybit's predicted").

### SM-3 Open-interest provenance: `ws_ticker` versus `rest` [SEM] [SEC]

- Why: `TM` D5 / AC11: a `ws_ticker` point at 1 s mixed with a `rest` point at 5 min. Cases: BB-001-01,
  BB-001-02, BB-001-06, NG-18. `22` gives every item its `interval` and `source`, and `open_interest_value` is
  `null` on a `rest` point (the venue's history carries no USD value and none is computed).
- Steps:
  1. `GET /market/open-interest?interval=1s` and `?interval=5min` for the same symbol and window. Record, per
     item, `interval` and `source`; record `meta.coverage.native_interval` and `meta.coverage.source`.
  2. In the pane, change the chart interval across 1m, 5m and 15m while the ticker streams.
  3. Hover a point from each source; open the table alternative.
  4. Try to **make the server mix**: request an interval that spans both sources (`TM` AC11); watch
     `deriv_source_mix_blocked_total`.
- Expected: no item list contains both sources; each point is labelled `rest` or `ws_ticker` in the tooltip **and**
  the table (S01 Security notes); a USD value is shown only for `ws_ticker` points (the deck's
  `derivatives.oi.usdt_history_na`, PROPOSED, covers the rest: "No USDT value for history · shown in BTC
  (contracts)"); the live extension is never presented as REST history; `source_mix_blocked` increments on the
  attempt in step 4. Fail: a spliced series, an unlabelled source, or an invented USD value: P1.

### SM-4 No quadrant without an OI sample [SEM] [SEC]

- Why: the client "must not infer a quadrant when the engine returned None" (S02 Security notes; the ticket
  names Q01 as the owner of this negative). Cases: BB-002-04, BB-002-06.
- Fixture: FX-NO-OI (`btc_8h_no_oi`: six 5 min samples dropped across one bar) and FX-STALE-OPEN
  (`btc_8h_15m_stale_open`: "a stale open gives delta None, never 0").
- Steps:
  1. Metrics for the window: `open_interest_delta` and `oi_price_quadrant` on the unsampled bar and on the bars
     either side. `PENDING #5341`: `null` for both, "never 0".
  2. Pane: hatch, legend count, crosshair, table. Quadrant colouring on, then off.
  3. **Inference attempt:** edit a copy of the response so the unsampled bar's quadrant is _absent_ rather than
     `null`, and another where its delta is `"0"`. Record both renderings.
  4. A bar with a close sample but a stale open (FX-STALE-OPEN).
- Expected: the bar is hatched, **excluded from classification**, counted in the legend ("3 unclassified (no OI
  sample)"), and never takes a neighbour's quadrant or one inferred from price alone; absent and `null` render
  alike; a delta of `"0"` is a real zero and is classified, so it must be a value the engine sent. The legend
  count equals the number of unsampled bars in view; the table row says "unclassified (no OI sample)".
- Fail: any quadrant, pattern or name on an unsampled bar: P1.

### SM-5 Countdown across a rollover and a clock-offset change [SEM]

- Why: S03's NFR is "accurate to the second using the synced clock offset"; a wrong countdown misleads about a
  real cost (S03 Security notes). Cases: BB-003-01, -02, -06, -07, BB-PNL-05.
- Fixture and toggles: FX-ROLLOVER, FT-CLOCK-OFFSET, FT-FEED-PAUSE (section 8). Everything runs on the fake clock.
- Steps:
  1. **Rollover, healthy feed:** start 20 s before a settlement; watch through zero. Record the header, the pane,
     the history length, the next target.
  2. **Offset step:** with 90 s left, change the clock offset from +3 s to -2 s (and back). Record the displayed
     value before and after the step and when it reaches zero relative to the replay clock.
  3. **Rollover with a stale ticker:** pause the ticker across the settlement (the target is not republished).
  4. **One timer:** inspect the DOM: one node carries the countdown in the header and the pane (D05 §11: one
     shared 1 s timer, one text node); count node updates over 10 s.
  5. **Announcements across the rollover:** with a screen reader or the live-region log, run 6 minutes before and
     6 minutes after a settlement.
- Expected: at zero the pane requests the settled rate, appends it, restarts the next interval, the header and
  the pane still agree; after the offset step the display re-bases on the new offset at once (no negative value,
  no frozen value) and still reaches zero within 1 s of the true time; announcements fire at 300 000 ms and
  60 000 ms **once per interval** and re-arm for the next one, never per second; one timer, one node. Step 3 is
  **PROPOSED**: the contract says the countdown "keeps running from the last known next-settlement time"
  (S03 "Source failure") and names a `settlement` frame (S54-25), but not what is shown once zero passes with no
  new target; owner E24-S03 (Q-8). A hidden browser tab that throttles timers must re-base within 1 s on return:
  also PROPOSED, same owner.
- Fail: a countdown more than 1 s off, a second timer, a stuck zero, a per-second announcement: P1 for the first
  three (integrity), P2 for the announcement (a11y, Q04's).

### SM-6 The 4 h interval honoured everywhere [SEM]

- Why: "no 8-hour assumption anywhere" (S03); "the interval is read from instrument metadata and used
  everywhere, including session anchors" (US-DERIV-003). Cases: BB-003-03, BB-004-02, BB-004-05, BB-003-09.
- Fixture: FX-4H (SYM-4H).
- Steps: on SYM-4H list every place the interval is used, and check each against `funding_interval_minutes: 240`:
  (a) the history step and the six settlements per UTC day; (b) the countdown target and the settlement markers
  on the time axis; (c) the pane and header wording (`derivatives.funding.interval_4h`); (d) the annualisation
  factor `525600/240 = 2190` and the tooltip; (e) the table alternative; (f) the **session anchor** (a
  per-session reset that aligns to settlement: where one exists in the build, record it; none is specified in
  this epic's contracts, so the check is **PROPOSED**, owner E24-S03); (g) the "Alert me 5 min before
  settlement" control; (h) a text search of the DOM for "8 h", "480" and "525600/480" on this symbol.
- Expected: every use shows 4 h; (h) finds none. Repeat (c) and (d) on a 1 h symbol if the fixture gains one
  (D02 names SOLUSDT at 1 h).
- Fail: any 8 h residue: P1 (a wrong cost figure). Signal: the CI guard against a re-introduced constant (E24-T02).

## 4. Boundary and abuse cases

### 4.1 Boundaries (checked before the store is read)

`22` states every bound below "checked before the store is read": a rejected request makes **no** store query
(observable as no change in the read-path query log and `deriv_range_rejected_total` +1, `TM` §8). Each pair is
the last accepted value and the first rejected one. Run on `GET /market/open-interest` (`OI`),
`/market/funding` (`FN`), `/market/liquidations` (`LQ`), `/market/metrics` (`MT`).

<!-- prettier-ignore -->
| ID | Route | Case | Expected (source) |
|---|---|---|---|
| BD-01 | OI | `to - from` = 400 d, then 400 d + 1 s | 200; then 400 `invalid_time_range` (`22` Bounds) |
| BD-02 | OI, FN, LQ | `from` = `to`; `from` later than `to` | 400 `invalid_time_range` ("`from` must be before `to`") |
| BD-03 | LQ | `to - from` = 31 d, then 31 d + 1 s | 200; then 400 `invalid_time_range` (`22` Bounds) |
| BD-04 | FN | `to - from` = 400 d, then 400 d + 1 s | **EXPECTED-BY-MODEL (22 silent)**: 200; then 400 `invalid_time_range`; the number is the model's proposal (400 d), not the contract's (Q-1, Q-2) |
| BD-05 | OI, FN, LQ | `limit` = 1, 500; then 0, 501, -1, `abc`, `1.5` | 200 for 1 and 500; else 400 `validation_failed` (`22`: "`limit` is 1–500, default 100") |
| BD-06 | OI, FN, LQ | `cursor` of 512 characters, then 513 | a 512-character one is judged on its content; 513 is 400 `invalid_cursor` |
| BD-07 | OI | `interval` = each of `1s`, `5min`, `15min`, `30min`, `1h`, `4h`, `1d`; then `2min`, empty | 200 for the enum; else 400 `validation_failed` (**PROPOSED** code: `22` states the enum, not the error; owner E24-T01) |
| BD-08 | OI, FN, LQ, MT | `symbol` malformed (`btcusdt`, `BTC`), then well-formed but unlisted (`ZZZUSDT`) | 400 `validation_failed`; then 422 `validation_failed` (`22` Bounds) |
| BD-09 | LQ | `cluster_window_ms` = 0, 60000; then -1, 60001 | 200; then 400 `validation_failed` (REST range 0-60000; WS takes 0-5000, BD-17) |
| BD-10 | LQ | `min_notional_usd` = `0`, a large decimal; then `-1`, `abc` | PROPOSED: negative and non-decimal are 400 `validation_failed`; owner E24-T03 (the contract names the type, not the range) |
| BD-11 | MT | `metric` repeated 1, 12 times; then 13 | 200; then 400 (`maxItems: 12`, AC5) `PENDING #5341` |
| BD-12 | MT | `params` of 2048 bytes; then 2049 | 200 or a parameter error on content; then 400 (`maxLength: 2048`) `PENDING #5341` |
| BD-13 | MT | `param` of 24 characters; then 25 | as BD-12 (`maxLength: 24`) `PENDING #5341` |
| BD-14 | MT | a **made-up** `metric=foo`, then a **registered but unserved** code | 400 `validation_failed` (not in the `MetricCode` enum); then 422 `validation_failed` ("a code this server does not compute yet", if #5341 merges as is) |
| BD-15 | MT | a window of 1 500 bars, then 1 501; 400 d, then 400 d + 1 s | 200; then 400 `invalid_time_range` (if #5341 merges as is) |
| BD-16 | MT | a bar-scoped derivatives metric with `bar_type` other than `time` | PROPOSED: refused, `validation_failed`; owner E24-T04 (#5341 says "bar-scoped on `bar_type=time` only", not the code) |
| BD-17 | WS | `liquidations.BTCUSDT` with `cluster_window_ms` = 5000, then 5001 | accepted; then `invalid_options` with `field` (`23` topic registry range 0-5000) |
| BD-18 | WS | a `sub` frame larger than `max_inbound_frame_bytes` (262 144 B = 256 KiB; 8 192 B until `auth_ok`): once between that cap and 260 KiB, once above 260 KiB | between: the gateway sends `bye frame_too_big`, then closes `1009`; above 260 KiB (the transport limit, `SERVER_WS_MAX_SIZE`): the transport closes `1009` with **no** `bye`, before the gateway sees the frame (`23` §3.6, §4.4). Neither is `frame_malformed` |

Each row is also run **together**: a request with the first rejected value of two parameters at once must answer
one 400 with the first problem named and no store read (the bounds are validated, never truncated, `TM` D12 / D17).

### 4.2 Abuse cases AC1 to AC13: owner and what this plan does with each

All 13 appear (ticket AC "Abuse cases included"). The **Owner** is the threat model's `TM` §7 column. The **Q01
disposition** is the BQ 2 ruling: a manual run here (R), a manual smoke once with the automation in X02 (S), named
and handed on (H), or a manual DOM check with the automation in Q02 (D). Every run is on the fixture-replay stack,
no live exchange (C-13.5); the steps are written for a plain HTTP client and a WebSocket client (`websocat`-style).

<!-- prettier-ignore -->
| ID | AC | Abuse case | Expected (honest state or 4xx) | Owner (`TM`) | Q01 |
|---|---|---|---|---|---|
| NG-09 | AC1 | `GET /market/liquidations?from=1970-01-01T00:00:00Z&to=now` | 400 `invalid_time_range`, **no store read** | X02, Q01 | R |
| NG-10 | AC2 | `limit` = 501, 0, -1, `abc` on each history route | 400 `validation_failed` (BD-05) | Q01 | R |
| NG-11 | AC3 | `from` later than `to` on each history route | 400 `invalid_time_range` (BD-02) | Q01 | R |
| NG-12 | AC4 | a **tampered** cursor (one byte changed), an **expired** one (older than 1 h), one from another route or symbol, and one of 513 characters | 400 `invalid_cursor` each, no items, no store read | Q01 | R |
| NG-13 | AC5 | `/market/metrics` with 13 `metric` values; `params` of 2049 bytes; an unknown metric code | 400 (BD-11, -12, -14) `PENDING #5341` | X02 | S |
| NG-14 | AC6 | one connection subscribes `liquidations.*` for 41 distinct symbols | the 41st `sub_ok` result is `subscription_limit` (`23` `max_symbols_per_connection`: 40); the first 40 are **unaffected** and keep streaming; `deriv_sub_cap_rejected_total` +1 | X02 | S |
| NG-15 | AC7 | 201 subscriptions on one connection; one `sub` frame of 51 topics | the 201st is `subscription_limit`; the 51-topic frame is refused **whole** with `too_many_topics` (`field: topics`), no entry read | X02 | S |
| NG-16 | AC8 | a simulated 1 000-print cascade in 1 s | per-client rate at most 20 frames/s, queues bounded, no resync | Q03 | H |
| NG-17 | AC9 | an upstream frame with an extra field, a missing field, the wrong symbol, a negative size | rejected, `deriv_upstream_schema_rejected_total` +1, **store unchanged** | X02 | S |
| NG-01..08 | AC10 | each route and topic with no token, a bad or expired token, an enrolment-only session | 401 / 403; on the WS `not_authenticated`, `auth_failed`, `bye token_expired` (4401), `bye mfa_enrollment_required` (4403) (section 2.10) | X02 (+ Q01 by D11) | R |
| NG-18 | AC11 | OI at 1 s (`ws_ticker`) and at 5 min (`rest`) for one symbol | never merged into one series; `source` visible; `deriv_source_mix_blocked_total` (SM-3) | Q01, T06 | R |
| NG-19 | AC12 | a funding point with `settled=false` (`predicted: true`) through every layer | the badge is visible in the DOM (SM-2) | Q02 | D |
| NG-20 | AC13 | scan every response and frame captured in this plan for key- or token-like fields | none | X02 | S |

Steps (all in one place; the table gives the target and the result).

- **NG-09, NG-11:** send the request; record status, `type`, `code`; confirm the read-path query log (or the
  store's query counter on the harness) did not move. The body is `application/problem+json` and holds no items.
- **NG-12:** make a first page (`limit=2`), take `meta.next_cursor`; (a) flip one character; (b) set the fake
  clock past the 1 h expiry; (c) use the cursor on another symbol or another route; (d) append to 513 characters.
  Each is 400 `invalid_cursor` (`22`: "malformed, foreign or expired").
- **NG-14, NG-15:** connect, `auth`, then `sub` with `snapshot: true`. For NG-14 subscribe 41 symbols one at a
  time, recording each `sub_ok` result; for NG-15 first 200 subscriptions (a mix of topics within the per-family
  caps), then one more; then one frame with 51 topics. Confirm the earlier subscriptions still deliver.
- **NG-17:** the mutation is a **run-time copy** of the fixture line in the test's temp directory, never committed
  (C-13.5): add a field, remove `symbol`, swap the symbol, make `size` negative. **PROPOSED** procedure, owner E24-X02.
- **NG-20:** grep the saved responses for `api_key`, `secret`, `token`, `signature`, `authorization`, `cookie`
  (case-insensitive) and for 32+ character base64 runs outside the cursor field; the cursor is opaque by design.
  Any hit is a finding (D10, section 7).

### 4.3 Further negatives (derived from the threat model and the stories)

<!-- prettier-ignore -->
| ID | Requirement | Check |
|---|---|---|
| NG-21 | **Flag-stripped payloads** never become "settled" or "exact" | strip `predicted`, `estimated` (funding), `note` (liquidations batch) and `source` / `interval` (OI) from a copy of each response and each WS frame; no layer renders the stripped item as settled, exact, or from an assumed source (SM-2, SM-3, BB-005-02) |
| NG-22 | **Coverage-less liquidation queries** answer honestly | a window wholly before `first_available_ts`, one for SYM-NEVER, and one while coverage metadata is unavailable: `no_coverage: true` or the `liq-coverage-retry` state (S54-50), never an empty list read as zero (CV-02, CV-03, CV-07) |
| NG-23 | **A rejected request writes nothing** and leaks nothing | after each 4xx in this section the body holds no data, no stack trace, no SQL, no file path; the store and the settings are unchanged |
| NG-24 | **Every operation is a read** (`TM` §6) | enumerate the four REST operations and two topics: all `GET` or read-only `sub`; a `POST`, `PUT`, `PATCH` or `DELETE` on any of the four routes is 405 or 404, never 200. Automation: E24-X02 |
| NG-25 | The 401/403 body leaks no series (D11) | covered by section 2.10's "no data in the body" check; this row is the reminder that it applies to **every** case above |
| NG-26 | **A feature flag or setting never hides the honesty affordance** | with `deriv.liq.zones_enabled` off the zones are not requested (BB-007-01); with it on, the badge cannot be turned off by any setting or the table toggle (BB-007-03) |

## 5. Recorder-bounded history and coverage gaps

There is no REST history for liquidations: depth is bounded by recorder uptime (`22`, `21` §4.6). The same
honesty rule covers OI and funding, whose stores are backfilled and may have holes. `meta.coverage` is the
oracle: for liquidations `first_available_ts`, `covered_from`, `covered_to`, `no_coverage`; for OI `from`, `to`,
`native_interval`, `source`, `gaps[]`; for funding (if #5699 merges as is) the liquidation four plus `gaps[]`, at
most 64, both edges exclusive, a span being a gap when `to - from` exceeds one `funding_interval_minutes`.
A span that holds no stored point is **reported, never filled**.

<!-- prettier-ignore -->
| ID | Case | Expected (source) |
|---|---|---|
| CV-01 | Liquidations, window **starts before** `first_available_ts` (SYM-REC-2H, 24 h window) | `covered_from` = `first_available_ts`, `no_coverage: false`; the pane shows only the recorded window and the chip `derivatives.liq.partial_chip` naming the time in UTC (BB-005-03); the boundary marker `derivatives.liq.boundary` on the bars (BB-006-04) |
| CV-02 | Liquidations, window **ends before** `first_available_ts` | `no_coverage: true`, empty page; the pane says `derivatives.liq.before_coverage` ("Not recorded before 09:14 UTC — this is not 'no liquidations'"), no empty list (SM-1) |
| CV-03 | A listed symbol the recorder has **never** recorded | `first_available_ts: null`, `no_coverage: true`; `derivatives.liq.never_recorded`; live prints still stream (`derivatives.liq.streaming`) |
| CV-04 | A **mid-window gap** in the liquidation recording (the connection to Bybit dropped) | the span is unknown, not zero (SM-1); the deck wording is `derivatives.liq.gap` ("Not recorded 17:02–17:09 UTC · connection to Bybit dropped"). **The contract gives liquidations no `gaps[]`** (only OI and, with #5699, funding): where the pane learns the span is **PROPOSED**, owner E24-T03 / E24-S06 (Q-9). The run records what the pane does |
| CV-05 | OI gaps (`btc_8h_recorder_gap`: a head span with no OI and no ticker) | `gaps[]` lists spans with more than one interval between `rest` points, or more than 10 s between `ws_ticker` points; the pane draws an explicit **gap**, not a straight line, and the readout says unknown (BB-001-03) |
| CV-06 | Funding gaps and `no_coverage` (if #5699 merges as is) | `gaps[]` bounded by the stored neighbour settlements or the covered edges (both exclusive); more than 64 gaps: the oldest are joined into one span that never leaves a missing settlement out; `no_coverage: true` means "not recorded", `false` with an empty page means no funding settled |
| CV-07 | Coverage **metadata unavailable** or the history request fails | `liq-coverage-retry` (`derivatives.liq.coverage_retry`, "Recording metadata is not available yet; retry shortly.") or `liq-history-failed` with `derivatives.retry.last_loaded`; never a blank pane, never "no liquidations" |
| CV-08 | First request for an **uncovered** (symbol, interval) | the server queues a bounded background backfill and answers at once with what is stored (`22` OI); the pane shows `backfilling` then fills with **no duplicated or reordered point**; a second identical request does not queue a second backfill |
| CV-09 | **Recorder restart** inside the window | `first_available_ts` does not move; the boundary marker does not move; the gap is reported as a gap |
| CV-10 | **Paging across the coverage edge** (`limit=2`, walk every page) | no item twice, none skipped, the same `meta.coverage` on every page, `has_more` false on the last (`22` `Page`) |
| CV-11 | Time labels | every boundary and gap label is in UTC with the date when it is not today (`…not_today`, "No history before 21 Oct 09:14 UTC…"); the local clock offset never moves a label |

## 6. The cascade

A liquidation cascade is the epic's stress case: hundreds of events per second, up to 500 prints/s for 10 s
(5 000 prints) in D05 §11, with the burst counter, 250 ms buckets, at most 40 rows in view and an announcement at
most once per 5 000 ms. **Q03 measures** the budgets (the 2 ms script budget, the fan-out rate, AC8) and
**Q02 automates** the badge and the chip; this plan runs the cascade by hand to judge **what the user is told**,
and a second charter (CH-2) explores it. Fixture: FX-CASCADE (`allLiquidation_BTCUSDT_burst`, section 8) at its
recorded rate; `PENDING #5273` for the fixture and the handler.

<!-- prettier-ignore -->
| ID | Case | Expected (source) |
|---|---|---|
| CS-01 | Replay the burst at the recorded rate; watch the feed | prints coalesce into 250 ms buckets with a burst counter (`liq-cascade`, S54-43, "1 240 prints/s" form); counts described as lower bounds (BB-005-02); **no DOM node per print** (node count flat while prints arrive) |
| CS-02 | Coalescing loses nothing | the sum of notional in the shown buckets equals the sum of the recorded prints for the replayed span, per side; a coalesced bucket is not a dropped print |
| CS-03 | Cascade during a **partial history** (SYM-REC-2H) | `liq-cascade-partial` (S54-44): the chip and the burst counter coexist; the cascade is not mistaken for the recorded window's start |
| CS-04 | Announcements | at most one summary per 5 000 ms (`derivatives.announce.cascade.longs`, `.shorts` PROPOSED, `.both` PROPOSED); none per print; the wording follows the dominant side (BB-005-07) |
| CS-05 | A cascade **and** an imminent settlement at once | each sub-pane keeps its own polite `role="status"` node (D05 §9.2 LR-1..LR-8): the countdown at 300 000 / 60 000 ms and the cascade summary neither starve nor duplicate each other |
| CS-06 | Pause and resume the feed (`derivatives.liq.feed.pause`, `.resume`, `.new`) | while paused a "N new" count grows; on resume the buffer is **bounded** (S05 Security notes: "the bounded buffer"), never an unbounded list; what is shown for the dropped ones is **PROPOSED**, owner E24-S05 |
| CS-07 | A slow consumer | throttle the client link until the server closes with `slow_consumer` (`23` error table, close `4429`); on reconnect the pane resubscribes with a snapshot (last 100, `23` §14.9) and shows the unknown span as unknown (SM-1), not as a lull |
| CS-08 | Cascade ends | the burst counter returns to idle, no "burst" state lingers, the node count and script time return to the pre-burst level (no leak) |
| CS-09 | `min_notional_usd` during the cascade | the server filters before send (fewer frames); the filter is stated in the pane (BB-005-06); raising it mid-cascade takes effect without a resubscribe loop |
| CS-10 | A cascade across a bar boundary and 00:00 UTC | the bars of S06 count every print once (BB-006-02); no print in two buckets, none dropped |
| CS-11 | Cascade while the **ticker** is stale | the liquidation pane stays live and the stale shading applies per sub-pane only (BB-PNL-02) |
| CS-12 | AC8: 1 000 prints in 1 s | **handed to E24-Q03** (NG-16); not run here beyond CS-01 |

## 7. Severity rules and defect taxonomy

The scale is `03-testing-strategy.md` §11.3 (P0 to P3, with its triage SLAs and fix-before gates); nothing here
adds a level. This section is the **epic's mapping** onto it, for the ticket's taxonomy and BQ 10. The unit of
judgement is whether the panel shows the user a fact the system does not hold.

<!-- prettier-ignore -->
| Sev | Defect class in E24 | Examples (case) | Why |
|---|---|---|---|
| **P0** | An E24 endpoint or topic answers **without a valid token**, or leaks a secret, token or key-like field | NG-01..08 answer 200; NG-20 hits | security breach (`03` §11.3 P0); the data is public but the gate is not |
| **P1** | A **fabricated value**: a number the system does not hold | a quadrant on a bar with no OI sample (SM-4); a carried-forward predicted rate shown as current (SM-2); an invented USD value on a `rest` OI point (SM-3) | "a pane renders incorrect but non-trading data" (`03` §11.3 P1); ticket taxonomy |
| **P1** | A **missing or wrong provenance label**: predicted styled or worded as settled; a missing `(estimated)` badge on a zone; a lower-bound count shown as exact; an OI point with no source | BB-004-03, BB-007-03, BB-005-02, SM-3 | `TM` D3 and D4 (risk High); S07 treats a missing badge as a **security finding**, not a UI defect |
| **P1** | **Absence read as zero**, or zero read as absence | an empty liquidation list for an uncovered window; a zero-height bar before the boundary; `0` for a `null` delta (SM-1, SM-4) | `TM` (T) in S05 / S06 |
| **P1** | A **wrong unit** or a figure with no unit | USDT shown as BTC contracts; a bare number at 360 px (BB-PNL-03) | ticket taxonomy |
| **P1** | A **wrong funding interval or countdown**: 8 h used on a 4 h symbol; the factor `525600/480` on `240`; a countdown more than 1 s off; a second timer | SM-5, SM-6, BB-004-02 | integrity surface about a real cost (S03 Security notes) |
| **P1** | **Stale data styled as current**: no shading after the threshold, or a shading that never clears | BB-001-04, BB-PNL-02 | the same class as fabricated; PROPOSED level, owner the QA lead (E08-Q01 rates its ingestion form P0) |
| **P1** | A **rejected request that still reads the store**, or an unbounded request that is served | BD-01..BD-18, NG-09..NG-12 | `TM` D12 (risk High) |
| **P2** | An **accessibility** gap on an honesty affordance: a badge with no accessible name containing "estimated", a per-second announcement, no table alternative | BB-004-06, BB-003-07, BB-001-06 | `03` P2 "a11y AA violation"; Q04 owns the audit |
| **P2** | A cascade defect that does not misstate data: a DOM node per print, a lingering burst state, an unbounded buffer | CS-01, CS-06, CS-08 | partial breakage; budgets are Q03's |
| **P3** | **Copy or spacing deviation** from the deck or the board that keeps the provenance word | a spacing deviation; "Retry" wording | ticket taxonomy; `03` P3 |

Rules of application.

- **Copy that drops a provenance word is P1, not P3.** A deviation that keeps "predicted", "estimated" or "about"
  where D05 §8.3 requires it is P3; one that removes it is the P1 above (and a refused wording, "exchange-published"
  on a predicted row, is P1).
- **Severity follows the worst layer**: report once, at the layer where the fact was lost (engine, REST, WS,
  props, DOM; `TM` §5), and name every layer that propagated it.
- A finding on **public market data** is never rated above P1 unless it is the P0 row: the epic holds no order,
  account or key path (`TM` §6).
- **Defect record**: case id, build and fixture ids, steps, expected versus observed, the layer, severity, the
  **signal that should have caught it** (or "none" as an observability finding), evidence (response bodies with
  tokens redacted; screenshots with greyscale where relevant).
- **Disposition** of every finding from a charter or a case (ticket AC "Charters executed"): a defect ticket
  with its severity, or a recorded non-issue with its reason. Nothing stays "noted".
- These rules live in this plan, not in `03`. Zero open P0/P1 against the epic's tickets is the Definition of Done
  gate (`E24-S01..S08` DoD).

## 8. Fixture and test-data plan

Every fixture is obtainable before the execution window (ticket AC "Fixtures are obtainable"): it either **exists
in the store** (a path) or has a **procedure** to produce it. **No fixture is committed by this ticket**: that
would widen its scope, and a capture needs the capture tool (C-13.5). **Honesty about provenance:** the files
below are "documented-shape (exception #1778 A)" corpus entries, **not live captures**, except the
`recorded_*` ticker and trade files; the golden README says the corpus is "NOT a recorded symbol-day". The plan
calls them corpus fixtures, never recorded ones.

<!-- prettier-ignore -->
| Id | Need | State | Where, or the procedure |
|---|---|---|---|
| FX-NORMAL | a normal session: OI, funding, tickers on one grid | exists | `packages/fixtures/golden/derivatives/` case `btc_8h_slice` (UTC day boundary and the 8 h settlement at `1700006400000` inside the window); `bybit/2026-10-05/rest/open_interest_BTCUSDT_5min_page0.json`, `…_page1.json`, `funding_history_BTCUSDT_8h.json`; `ws/tickers_BTCUSDT.jsonl` |
| FX-4H | a symbol funding every 4 h | exists | case `btc_4h_paired` (BTCUSDT grid with the ETHUSDT 4 h settled rows); `rest/funding_history_ETHUSDT_4h.json`; its `expected_btc_4h_paired.json.gz` is the oracle for the engine, not for the pane |
| FX-NO-OI | bars with no OI sample | exists | case `btc_8h_no_oi` (six 5 min samples dropped); `btc_8h_15m_stale_open` (three dropped: a stale open gives a `None` delta) |
| FX-RECORDER-GAP | a recorder gap, a head span with no OI and no ticker | exists | case `btc_8h_recorder_gap`; the loader's `drops` transform (`golden/derivatives/README.md`) produces variants. **A liquidation recorder gap and a 2 h-old recorder** are not in the corpus: produced by the same `drops` transform on FX-CASCADE once it exists (procedure; owner E24-T06) |
| FX-CASCADE | a liquidation cascade at a recorded rate | **not on `main`** | `ws/allLiquidation_BTCUSDT_burst.jsonl` and `ws/docs-all-liquidation.jsonl` exist on #5273 `feat/e24-liquidations` (head `9bf4ec8c2bd5a2ca067c5a77726f63f0f2c0d0dd`). Procedure until it merges: none; the cases `PENDING #5273`. The parity cascade cases are the golden README's "follow-up once #5273 lands" |
| FX-ROLLOVER | a settlement boundary on a controllable clock | **procedure** | the replay stack's fake clock set 20 s before the settlement at `1700006400000`, with `rest/server_time.json` and `funding_history_BTCUSDT_8h.json`. **Residual gap (Q-8):** no corpus ticker frame is known to carry the **post-settlement** `nextFundingTime`; if none does, a mutated copy of `ws/tickers_BTCUSDT.jsonl` supplies it at run time (never committed) |
| FX-BACKFILL-FAIL | a failed REST backfill | **procedure** | `rest/error_503.json` exists but is the kline route's; the replay stack's fault toggle FT-REST-503 answers the **OI, funding and ratio** routes with that body. No new file |
| FX-NO-PREDICTED | a ticker with no `fundingRate` | **procedure** | a run-time copy of `ws/tickers_BTCUSDT.jsonl` with the field removed |
| FX-NEVER-RECORDED | a listed symbol never recorded | **procedure** | a seeded store with no rows for SOLUSDT; the symbol is listed in `rest/instruments_before.json` |
| FX-INTERVAL-CHANGE | a funding interval that changes mid-session | **procedure** | `instruments_before.json` and `instruments_after.json` are the shape, but **both hold `fundingInterval` 480 for every symbol**; the change is a run-time copy of `instruments_after` with one symbol at 60 (D02 uses SOLUSDT at 1 h). `PROPOSED`, awaits D02 G5 |

### 8.1 Fault toggles

These are switches on the seeded stack, not fixtures. Whether the harness has each one is **unverified at the
pin**: `docs/qa/e49-exploratory-harness.md` §2 says the tier-B stack needs "an injected-fault switch for the 03 §9
scenarios", not which ones exist. A missing toggle is raised as a gap on its owner **before** the execution
window (Q-7), as the E35 plan does.

<!-- prettier-ignore -->
| Toggle | Effect | Used by |
|---|---|---|
| FT-REST-503 | the history REST routes answer `503` with the `error_503` body | BB-001-03, BB-003-05, BB-008-04, CV-07 |
| FT-FEED-PAUSE | the ticker and print replay stops, then resumes | BB-001-04, BB-PNL-02, SM-5, CS-11 |
| FT-CLOCK-OFFSET | the client clock offset against the replay clock, steppable | BB-003-02, SM-5 |
| FT-ROLLOVER | the replay clock jumps to a set time before a settlement | BB-003-06, SM-5 |
| FT-SOCKET-DROP | the WS connection closes and reconnects | BB-PNL-05, CS-07 |
| FT-NO-PREDICTED | the ticker omits `fundingRate` | BB-004-04, SM-2 |
| FT-INTERVAL-CHANGE | instrument info changes `fundingInterval` | BB-003-09, SM-6 |

### 8.2 Seeds and sessions

- **Users and sessions:** OWNER, MGR-A, VIEWER-V, ENROL-ONLY, the three token states (section 1). Named seeds
  `test-` / `fixture-` per the E49 harness (03 §13); no Demo, testnet or live key is used.
- **A position for the charge line:** one BTCUSDT long on ACC-1 with a native SL (C-2.6), none on ACC-2.
- **Settings:** a fresh account (no `deriv.*` row) for BB-PNL-01 and BB-007-01.
- **Not reachable with these seeds**, to be raised before execution: a role without `marketdata:read` (Q-5); the
  fault toggles above (Q-7); the post-settlement ticker frame (Q-8).

## 9. Exploratory charters (session-based, 90 minutes)

Format and rules: `03` §11.2 (mission, areas, oracles, debrief; 60 to 120 minutes) and the E08 and E49 charters.
Both charters ship **ready to run, status "not yet run"**: there is no running panel, and no screen reader or
browser on the build host, so execution waits for E24-S02, E24-S04, E24-D05 and a seeded stack (section 0.4). The
run record is added to the same file by the closing slice. If no human or staging is available then, the closing
slice follows the E08 precedent (an in-process run with an honest "not probed" list) and the QA lead rules whether
that meets "Charters executed" (Q-10). Fixtures: section 8; no network; Demo only.

<!-- prettier-ignore -->
| | Mission | Sessions | Areas | Evidence to capture |
|---|---|---|---|---|
| CH-1 | Find a place where the panel implies data we do not have (`docs/qa/charters/E24-charter-1-implied-data.md`) | **two** 90-minute sessions, split by sub-pane: 1A OI and funding; 1B liquidations and basis | zero versus unknown, predicted versus settled, provenance, quadrant without a sample, countdown, 4 h interval, empty states, retry states, units, copy | response and DOM pairs, greyscale captures, the layer where the fact was lost, the signal that would have caught it |
| CH-2 | Make the cascade behaviour misstate or lose what happened (`docs/qa/charters/E24-charter-2-cascade.md`) | **one** 90-minute session | the feed, the bars and the burst counter under the burst fixture, the partial-history chip during a cascade, announcements, pause and resume, reconnect, slow consumer | node counts, bucket sums against the recorded prints, announcement log with timestamps, the reconnect gap |

Reading of the ticket (BQ 7): "2 x 90 min" is **two sessions of CH-1**, and "a second charter for the cascade" is
CH-2. If the owner meant CH-1 and CH-2 as the two sessions, only the file split changes (Q-11).

Seed ideas are in each charter. Per-session notes use the E35 template extended with the **Signal** line:

```
Charter: CH-n[A|B]   Tester:   Date:   Build (sha):   Start/End:
Setup (fixture and toggle ids):
Tested:
Found (defect ids, or non-issue with reason):
Signal that would have caught each finding (or "none": an observability finding):
Obstacles:
Not probed:
Next:
Evidence links:
```

## 10. Regression pack, hand-offs, questions and traceability

### 10.1 Regression pack for E24-Q05 (manual, target under 3 hours)

Members tagged **[R]** in sections 2 to 6: the 19 panel cases BB-001-01, 001-03, 002-02, 002-04, 003-01, 003-02,
003-03, 003-06, 004-02, 004-03, 004-04, 005-04, 005-05, 006-04, 006-05, 007-01, 007-02, 007-03 and BB-PNL-02,
plus the negatives NG-01..NG-04, NG-05a and NG-06a (one 401 and one 403 per route and topic), NG-09, NG-12 and NG-18, and the six semantic
checks SM-1..SM-6 (they re-run the panel cases above across layers, so they add the cross-layer reads, not new
setup). About 7 minutes per panel case and 4 per negative: about 2.7 hours. Q05 references these ids and does not
restate them. Ids are never renumbered (section 0.5).

### 10.2 Hand-offs to the other E24 tickets

<!-- prettier-ignore -->
| To | What | Cases |
|---|---|---|
| **E24-Q02** (E2E) | automates the panel flows and the badge assertions; AC12 | BB-001-01..03, 002-02, 003-03, 003-06, 004-03, 005-03, 005-04, 006-05, 007-03, 007-05, 008-06, NG-19 |
| **E24-Q03** (perf) | AC8 (1 000 prints in 1 s; D05 §11: 500 prints/s for 10 s, 250 ms buckets, at most 2 ms script per frame, at most 40 rows virtualised), the fan-out amplification test, read p95 under 150 ms (budget #13) | NG-16, CS-12, BB-005-05; no timing is measured in this plan |
| **E24-Q04** (a11y) | the **screen-reader repeats**: the countdown announced at 5 minutes and 1 minute only (BB-003-07); the predicted name containing "predicted" and "estimated" (BB-004-06); one cascade summary per 5 s (BB-005-07, CS-04); the zone badge name (BB-007-03); the unclassified count (BB-002-06); the table alternatives (BB-001-06, BB-003-08) and the D04 §13 checklist Q-1..Q-7 (D05 §9.6) | listed |
| **E24-X02** (security) | automates AC1, AC5..AC10, AC13 and the non-GET enumeration (NG-24); the "permission removed" 403 (NG-08) | NG-01..NG-24 |
| **E24-T06** (parity) | the source and interval never merged (SM-3), the `drops` procedure for a liquidation gap | NG-18, FX-RECORDER-GAP |
| **E24-Q05** (sign-off) | assembles the pack in 10.1 with the Q02, Q03 and T06 results | 10.1 |

### 10.3 Questions raised against the implementing tickets (specification ambiguities)

None of these is guessed in a case; each case that depends on one says so. The orchestrator posts them on the
owning tickets (this ticket does not edit another ticket's contract, C-4.9).

<!-- prettier-ignore -->
| # | Question | Raised against |
|---|---|---|
| Q-1 | What is the funding window cap? The model proposes 400 d (`TM` §3 G1); `22` states none for `/market/funding`, and `deriv_limits.py` holds a constant for OI and liquidations only. BD-04 assumes 400 d | E24-T02 (#666), E24-S03 (#778) |
| Q-2 | `/market/funding` has no Bounds paragraph and no `400` response in `22` (only 401, 403, 404, 503), yet the handler answers 400 `invalid_time_range`; #5699 adds `meta.coverage` but still no bounds text. BD-04 and NG-10..NG-12 for funding are **EXPECTED-BY-MODEL (22 silent)** | E24-T02 (#666), E24-S03 (#778, #5699) |
| Q-3 | G2: `TickerUpdate.funding_rate` has no predicted or settled flag (`23` §14.8; #5699 does not touch `23`). SM-2's WS oracle is the model's fallback "ticker funding is always predicted", PROPOSED. Does a `23` PR settle it? | E24-S03 (#778), E24-T02 (#666) |
| Q-4 | `/market/metrics` lists no `401` (400, 403, 422, 503) and no `invalid_time_range` text on main; #5341 adds the latter. NG-04 expects 401 as on the other three routes. A `22` omission to correct, not a spec for 200-only | E24-T04 (#723) |
| Q-5 | No seeded role lacks `marketdata:read` (Owner, Manager and Viewer all hold it, `21` and `04` §7.2.1), so the "role lacking the permission" 403 has no login. NG-08 is an injected-permission test. Is one needed as a seed, or is the contract test enough? | E09 (auth and RBAC) |
| Q-6 | Residual of NG-05: the WS refuses an enrolment-only session at `auth` (`23` §4.3), so only a `sub` **after** `auth_ok` by a session lacking the permission reaches `forbidden` (NG-08). Confirm `forbidden` applies to both the `ticker` and the `liquidations` topic families | E17 (WS gateway) |
| Q-7 | Which fault toggles exist on the tier-B stack (section 8.1)? `e49-exploratory-harness.md` §2 names an "injected-fault switch" without a list | E49 harness owner / infra |
| Q-8 | After a settlement with no republished target (stale ticker), what does the countdown show once zero passes? Is there a corpus ticker frame with the post-settlement `nextFundingTime`? | E24-S03 (#778), fixtures owner |
| Q-9 | Liquidations have no `gaps[]` in `22`; where does the pane learn the span in `derivatives.liq.gap` ("Not recorded 17:02–17:09 UTC")? CV-04 | E24-T03 (#667), E24-S06 (#781) |
| Q-10 | May the closing slice run the charters in-process (the E08 precedent) when no staging or screen reader exists? | orchestrator and QA lead |
| Q-11 | "2 x 90 min" plus "a second charter for the cascade": two sessions of CH-1 and one of CH-2 (this plan), or CH-1 and CH-2 as the two? | the ticket owner |
| Q-12 | The `deriv.funding.style` default (`line`) and `deriv.basis.annualised` (off) are PROPOSED in D05 §10; BB-PNL-01 asserts them only if #5617 merges as is | E24-D02 / E24-D05 |
| Q-13 | 401/403 negatives are in the model (`TM:162`, "requested on #771") but not in the ticket body's Scope. Add one Scope bullet and one AC scenario to E24-Q01 (via the ticket-JSON recipe, in its own commit)? | the orchestrator |

### 10.4 Traceability

<!-- prettier-ignore -->
| Story | Plan scenarios | Automated coverage |
|---|---|---|
| US-DERIV-001 | BB-001-01..07, SM-3, CV-05, CV-08 | E24-Q02 (E2E); T01 contract tests |
| US-DERIV-002 | BB-002-01..06, SM-4 | E24-Q02; S02 unit and visual tests |
| US-DERIV-003 | BB-003-01..09, SM-5, SM-6 | E24-Q02; S03 unit tests (fake clock) |
| US-DERIV-004 | BB-004-01..06, SM-2, SM-6 | E24-Q02 (AC12); T04 flag-preservation test; S04 component tests |
| US-DERIV-005 | BB-005-01..07, CV-01..CV-04, CS-01..CS-12, NG-14 | E24-Q02 (chip); E24-Q03 (AC8) |
| US-DERIV-006 | BB-006-01..06, SM-1, CV-01, CV-04 | E24-Q02; T04 bucketing tests |
| US-DERIV-007 | BB-007-01..07 | E24-Q02 (badge on every zone); S07 catalogue-level badge test |
| US-DERIV-008 | BB-008-01..07 | E24-Q02 |
| Panel-wide | BB-PNL-01..07 | E24-Q02, E24-Q04 |
| Route negatives (D11, AC10) | NG-01..NG-08 | E24-X02 |
| Abuse cases AC1..AC13 | NG-09..NG-20 (AC10: NG-01..08) | AC1, AC5..AC10, AC13: E24-X02; AC8: E24-Q03; AC12: E24-Q02 |
| Boundaries | BD-01..BD-18 | E24-X02; the contract suite |
| Other negatives | NG-21..NG-26 | E24-X02 (NG-24) |

Ticket acceptance criteria: **Coverage of every story** is the table in section 2 (all 24 `US` scenarios and the 53
`S0n` scenarios); **Semantic checks present** is section 3 (SM-1..SM-6, with BB-002-04, BB-003-06 and BB-004-04);
**Abuse cases included** is section 4.2 (all 13, each with its owner); **Charters executed** is section 9 and the
closing slice; **Fixtures are obtainable** is section 8.

Out of scope here (the ticket's): automation (E24-Q02, E24-Q03), the a11y audit (E24-Q04), the design sweep
(E24-D06), and unit tests, which live with their stories.
