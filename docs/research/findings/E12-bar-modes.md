# E12-bar-modes — how traders choose, parameterise and trust non-time bars

**Ticket:** E12-D01 (#138) · **Epic:** E12 · **Sprint:** 01 · **Status:** In Review — owner walkthrough pending
**Method:** heuristic evaluation (Nielsen + `05-accessibility-standard.md` trading heuristics) +
written session protocol, per the **Agent-delivery adaptation** on this ticket (owner decision
2026-09-25: moderated usability/participant sessions → documented heuristic evaluation, written
protocol ready for the owner to run later, owner walkthrough checklist posted on the issue).
**No participants were run and none are fabricated.** All findings below are labelled `(heuristic)`
where they stand in for what a session would have produced; anything grounded in an existing
contract (OpenAPI/WS schema, screens/component catalogue) is labelled `(contract)`.

## 0. Validity limitation (read first)

This report substitutes a structured **heuristic evaluation** — run by the design agent against
Nielsen's 10 heuristics plus the CandleViewer trading-specific heuristics in
`docs/plan/05-accessibility-standard.md` §3 — for the moderated 4–6 session study the ticket's body
describes. No Owner or manager session has been run yet. Per the adaptation clause this satisfies
the ticket's DoD _provisionally_; the reduced-evidence limitation is explicit and the **owner must
accept it** (see §7 Owner walkthrough) before E12-D02 leaves Ready. The **written discussion guide**
and **stimulus set description** in §1–§2 are ready for the owner (or a recruited external trader) to
run for real; if real sessions are later run, replace the `(heuristic)` labels with `(session: <id>)`
and re-file this ticket for CDO/owner sign-off with the upgraded evidence.

## 1. Research plan (ready to run)

**Objective:** decide, once, the user-facing vocabulary and trust affordances for non-time bars so
E12-D02..E12-D08 do not each invent a variant.

**Covers:** US-CHART-002 (intervals), US-CHART-003 (volume/tick bars, Must), US-CHART-004
(range/delta/Renko/P&F, Should/Could), US-CHART-005 (sub-minute/custom intervals), US-CHART-010
(go-to-date / recorded-history boundary).

**Participants (when run for real):** Owner (P1) + available Account Managers (P2), up to 2 external
perp/order-flow traders if recruitable. 4–6 sessions, ~45 min each, remote screen-share.

**Structure per session (protocol):**

1. Warm-up (5 min): "Walk me through the last time you changed a chart's bar type or interval on any
   platform. What did you type first?"
2. Today's tools (10 min): which bar modes they use today, on which platform (TradingView, exchange
   native, Bookmap, Sierra Chart, ATAS…), and the first parameter value they reach for per mode.
3. Discovery task (10 min): shown a static chart screenshot with no legend, asked "is this chart's
   x-axis time, or something else? How do you know?" — repeated across 3 candidate banner/affordance
   treatments (Stimulus A below).
4. Trust probes (15 min), each shown as a static board of 3 candidate treatments:
   - Partial-history marker ("tick data begins here") — Stimulus B.
   - Rebuild progress + cancel affordance when a parameter changes — Stimulus C.
   - LOD/aggregation indicator on deep zoom-out — Stimulus D.
     For each: "what do you think just happened? What would you expect to happen to your drawings,
     indicators and alerts?"
5. Keyboard/screen-reader pass (5 min, at least one session): change bar mode using only the
   keyboard and (if the participant uses one) a screen reader; note where the "separate labelled
   group" and description text (CMP-220) succeed or fail.
6. Wrap-up (5 min): tolerance for a rebuild taking N seconds before they'd consider it "stuck".

**Pilot:** run internally (owner) once before any external session; record what changed in the guide
afterward, in `docs/research/findings/E12-bar-modes.md` §8 "Pilot revisions" (kept blank here until run).

## 2. Stimulus set (descriptions — neutral tool, no CandleViewer branding)

All four stimuli must be built in a neutral prototyping tool (no product chrome) and checked against
`docs/plan/05-accessibility-standard.md` for contrast and non-colour redundancy **before** showing
them to anyone (own DoD gate, independent of whether a real session runs).

- **Stimulus A — non-time x-axis affordance**, 3 variants: (A1) persistent header pill reading the
  bar-mode name + param, always visible; (A2) a one-line banner on the axis itself
  ("axis: 1 000 ticks/bar, not time"), dismissible; (A3) the axis' tick labels replaced with bar
  index + a corner badge only. All three drawn against the two density extremes named in the
  ticket's Technical notes (100k-bar zoomed-out LOD board, and a 1 500-contract quiet-symbol board
  where bars are minutes apart).
- **Stimulus B — partial-history marker**: a vertical dashed line + label ("recorded tick history
  begins here — bars before this line are estimated from klines") vs. a left-edge fade + tooltip vs.
  a fixed banner at top of pane. Co-occurrence case: same board also showing a rebuild in progress
  (tests the precedence rule, §4).
- **Stimulus C — rebuild progress + cancel**: (C1) indeterminate spinner + "Rebuilding 1M ticks…" +
  Cancel button; (C2) determinate progress bar with count + ETA; (C3) toast + chart stays on old
  bars until ready, "Applying new parameter…" Each has a static (non-animated) equivalent per the
  Accessibility notes (reduced motion).
- **Stimulus D — LOD/aggregation indicator**: (D1) corner badge "aggregated (LOD ×32)"; (D2) axis
  tick note; (D3) no indicator (control, expected to fail the discovery task — recorded as the
  anti-pattern in §5).

## 3. Bar-mode vocabulary (recommended; binds `bar_type`/`param` from `22-api-openapi.yaml`) `(contract)` + `(heuristic)` for the description/default column

| `bar_type` (API) | User-facing label  | One-line description                                                                               | Param unit label                                         | Recommended designed default (heuristic — confirm with real sessions)       |
| ---------------- | ------------------ | -------------------------------------------------------------------------------------------------- | -------------------------------------------------------- | --------------------------------------------------------------------------- |
| `time`           | **Time**           | "One bar per fixed clock interval."                                                                | interval (e.g. `5m`)                                     | unchanged — existing interval ladder                                        |
| `tick`           | **Tick**           | "One bar per fixed number of trades, regardless of size."                                          | trades / bar                                             | `1000` trades                                                               |
| `volume`         | **Volume**         | "One bar per fixed amount of base-asset volume traded."                                            | base-asset volume / bar                                  | `50` (BTCUSDT-scale; unit shown as the instrument's base asset, e.g. "BTC") |
| `range`          | **Range**          | "A bar closes once its high-low range reaches a fixed number of ticks."                            | ticks / bar                                              | `40` ticks                                                                  |
| `delta`          | **Delta**          | "A new bar starts once cumulative signed (buy − sell) volume reaches a fixed size."                | base-asset volume (absolute cumulative buy − sell) / bar | `25` (BTCUSDT-scale, in the base asset)                                     |
| `renko`          | **Renko**          | "Fixed-size price bricks; a new brick only forms once price moves a full brick size."              | brick size in ticks, or ATR-based                        | `30` ticks, or `atr:14`                                                     |
| `pnf`            | **Point & Figure** | "Column-based reversal chart; a new column needs a full box move, a reversal needs N boxes back."  | `box:reversal` (ticks:boxes)                             | `10:3`                                                                      |
| `heikin_ashi`    | **Heikin-Ashi**    | "Smoothed candles on a normal time axis — not a non-time mode; no x-axis affordance is triggered." | underlying time interval                                 | unchanged — same as Time                                                    |

Corrected 2026-10-22 by E12-D03 (#201): Delta is base-asset volume, not ticks (E12-D02 OQ-9), and Range closes on
the bar's high-low span (`bars/threshold_builders.py`; US-CHART-004), as the shipped builders do.

Naming note `(heuristic)`: "Point & Figure" abbreviated to "P&F" in the compact `IntervalPicker`
menu row (CMP-220) but spelled out in the row's own description text and in SCR-045's data table
per the a11y requirement that non-time modes carry a one-line accessible description — an
abbreviation alone is not sufficient as an accessible name.

## 4. Precedence rule for co-occurring states `(heuristic)`

When two trust-affecting states apply to the same visible chart region at once, resolve in this
order (most disruptive to correctness first):

1. **Rebuilding** (parameter/mode change in flight) — always shown; it supersedes the partial-history
   marker's visual weight because the user's immediate question is "can I trust what's on screen right
   now", not "how far back does history go".
2. **Partial history** (`recording_started_at` boundary reached) — shown as soon as rebuild completes,
   persists as long as the visible window includes bars before the boundary.
3. **LOD / aggregation** (deep zoom-out) — shown continuously whenever active; lowest precedence
   because it is the least likely to be mistaken for a data-correctness problem, but never suppressed
   by the other two — it uses a different UI slot (corner badge vs. banner/marker) so it can coexist.

Rule: rebuilding and partial-history markers use the same UI slot (top-of-pane banner) and rebuilding
wins that slot; the partial-history marker still applies to the axis fade/dashed-line treatment
underneath so it is not fully hidden, only de-emphasised. LOD uses a separate corner-badge slot and is
never hidden by the other two.

## 5. Anti-patterns (do not do this)

- **D3 (no LOD indicator) is rejected** `(heuristic)`: relying on the user to infer aggregation from
  bar width alone fails the discovery task by construction — record any implementation that omits an
  LOD indicator at deep zoom as a regression against this finding.
- **Colour-only non-time indication is rejected**: axis colour change alone (e.g. tinting the axis)
  is not an acceptable substitute for a text affordance — fails the non-colour-redundancy check in
  `05-accessibility-standard.md` and this ticket's own Accessibility notes.
- **Animation-only "rebuilding" indication is rejected**: a spinner with no text/percentage and no
  static equivalent fails `prefers-reduced-motion` compliance; C1/C2 above both need a text label
  regardless of motion state.
- **Silent wait past the feasibility threshold is rejected**: see §6 — any UI that shows nothing for
  longer than the stated threshold is an anti-pattern regardless of how "instant" the mock implies.
- **Reusing the partial-history slot for delisted/never-recorded (SCR-047) is rejected**: those are
  three distinct reasons per SCR-047's own acceptance checklist; collapsing them into one banner text
  loses the actionable difference (record vs. wait vs. pick another symbol).

## 6. Feasibility / silent-wait threshold `(contract)`

Per `US-CHART-005` (timeframe switch ≤200 ms from cache) and SCR-042 (≤600 ms first paint uncached),
and `US-CHART-003`'s NFR of ≤10 s to rebuild 1M prints:

- **≤600 ms:** no progress UI needed — feels instant, matches SCR-042's own uncached first-paint budget.
- **600 ms – 2 s:** show a lightweight indeterminate indicator (no cancel needed yet).
- **>2 s:** the maximum acceptable silent wait — a rebuild running longer than 2 s **must** show C2's
  determinate progress + cancel (Stimulus C2), because the 10 s NFR ceiling means some rebuilds will
  routinely exceed the "feels instant" zone and users need a way out rather than a hung-looking chart.
- Any candidate treatment implying a rebuild of 1M prints without a progress affordance is infeasible
  and is rejected per the ticket's own Performance notes.

This **2 s threshold is the number E12-D08 and the engineering stories should implement** as the point
the rebuild UI switches from indeterminate-no-cancel to determinate-with-cancel.

## 7. Analytics events `(contract)` + `(heuristic)` for the new one

Existing, reused as-is: `chart.interval_changed`, `chart.bar_mode_changed` (SCR-042),
`chart.symbol_changed` (SCR-041), `chart.empty_state_shown` with `{reason}` (SCR-047).

**Recommended new event** `(heuristic)`: `chart.bar_rebuild_cancelled` — `{bar_type, param, elapsed_ms,
prints_rebuilt}` — fired when a user cancels a rebuild past the 2 s progress-UI threshold in §6; lets
E12 engineering measure how often the threshold is actually hit and whether 2 s should move.

## 8. Screen-reader / keyboard findings `(heuristic)`

- `CMP-220 IntervalPicker`'s requirement that bar modes form a separately labelled, announced group
  is necessary but not sufficient: the per-mode one-line description (§3 table) must be exposed as
  part of the accessible name or description of each menu item, not left as visual-only helper text,
  or a screen-reader user gets the label ("Range") with no cue that it changes x-axis meaning.
- Each recommended state is announced as follows:
  - **Rebuilding** — a polite `aria-live` message ("Rebuilding chart, N% complete") plus a static row
    in the diagnostics/SCR-045 table equivalent; never assertive (would interrupt a screen reader
    mid-navigation for a non-urgent, cancellable operation).
  - **Partial history** — text in the accessible name/description of the marker element (not a
    tooltip-only string) plus a row in the SCR-045 data table stating the recording-start timestamp.
  - **LOD/aggregation** — a row in the SCR-045 data table ("aggregation: ×32") since it is a continuous
    ambient state, not an event — a live-region announcement would be noisy per the trading-specific
    "do not flood a screen reader with ambient state" heuristic.
- Reduced motion: the rebuild indicator's static equivalent is the determinate progress bar itself
  (a numeric percentage updated at ≤2 Hz) — no additional design needed, C2 already satisfies this.

## 9. Corrections filed against existing catalogues `(heuristic)`

- **`14-screens-catalogue.md` SCR-042**: add an explicit row to the acceptance checklist for "the
  precedence rule when rebuilding and partial-history markers co-occur is documented and implemented"
  — currently the checklist covers parameter inputs and favourites but not state co-occurrence. Filed
  as a follow-up note on this ticket for the SCR-042 owner to fold in when E12-D02/D03 touch that file.
- **`15-component-catalogue.md` CMP-220 IntervalPicker**: the existing a11y note ("bar modes are a
  separate labelled group with an explanatory note") should be tightened to require the explanatory
  note be part of the accessible name/description, not adjacent visual text only — see §8. Filed as a
  follow-up note for CMP-220's next edit.
- No corrections are raised against SCR-047 or CMP-222/CMP-181/CMP-226 — evidence gathered (heuristic
  walkthrough) did not contradict their current wording.

## 10. Handoff

- Comment posted on **E12-D02** (wireframes): vocabulary table (§3), stimulus descriptions (§2),
  precedence rule (§4) and the 2 s threshold (§6) are ready to consume for wireframing SCR-030/SCR-042.
- Comment posted on **E12-D09** (design-system contribution): the anti-patterns (§5) and screen-reader
  requirements (§8) should inform any new CMP-220/CMP-226-adjacent token or component work.

## 11. Pilot revisions

Not yet run — blank until the owner or a recruited participant runs the pilot session per §1.

## 12. Reduced-sample / evidence-quality statement

**No sessions have been run.** This report is a heuristic evaluation substitute per the ticket's
Agent-delivery adaptation clause, not a session-based finding. The Owner must explicitly accept this
reduced evidence (owner walkthrough checklist posted on issue #138) before treating E12-D02 as
unblocked, per the ticket's own
Acceptance criteria ("Reduced sample" scenario) — the CDO/Owner substitution applies.
