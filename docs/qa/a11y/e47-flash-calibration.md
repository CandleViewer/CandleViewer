# G005 flash gate calibration (E47-S04)

Standard: WCAG 2.2 SC 2.3.1 (three flashes or below threshold), `docs/plan/05-accessibility-standard.md` §7.
Gate: `A11Y-G005` in `tools/a11y/gates.py`. Motion rules: `docs/design/E05/E05-D03.md` §4 (MR-1, HS-1).
Status: **calibrated against the coalescer and a synthetic harness; the pair-counting rule is ruled (BQ-14 (a)).**

## 1. The threshold and why

- A flash is a change of at least **0.1 relative luminance** (`FLASH_LUMINANCE_DELTA`), the WCAG 2.3.1
  general-flash step.
- The gate **fails at 3 or more flashes in any 1 s window** (`MAX_FLASHES_PER_SECOND = 3`, "limit < 3").
  WCAG's own line is "more than 3 in any one second"; the gate is one stricter, so a surface that merely
  reaches the limit is already a failure.
- Consequence for the coalescer: HS-1 allows one start per cell every 500 ms, so at most 2 starts in any
  1 s window, which passes with margin. A 400 ms interval admits 3 starts in a second and fails the gate
  (and 333 ms admits 4: E05-D03 C-6).

## 2. The fixture

- `packages/fixtures/src/synthetic-ticks.mjs`: a **seeded, deterministic price-tick generator** (no wall
  clock, no `Math.random`; fake-clock timestamps, integer ticks).
- Presets used: `burst` (40 Hz for 5 s) and `steady-40hz` (40 Hz for 60 s); `idle` (0.2 Hz, 60 s) is
  covered by the coalescer's own unit tests.
- It is a rate harness, not a venue payload, so C-13.5 (recorded exchange fixtures) is not engaged (BQ-8).

## 3. The harness

- `apps/web/e2e/a11y/flash-coalescer.collect.ts` drives `createFlashCoalescer`
  (`packages/ui/src/components/flashCoalescer.ts`) with the burst fixture on a fake clock, replays the
  resulting starts on a frame-exact virtual clock (each flash is a paused Web Animation seeked to the
  sample time, so the browser resolves the recipe's easing but no timer jitter moves a start across a 1 s
  window edge) on one element marked `data-flash-audit="price-flash-harness"`, and samples its composited
  luminance at 60 Hz.
- **Two guards keep the pass capture honest.** The collector fails as infra unless every start raises
  luminance by the 0.1 step (an overlay that stops painting would otherwise read 0 flashes and pass), and
  unless no three starts fall within 1 s (a coalescer restarting every frame would hold the overlay bright
  and also read 0).
- **The audit peak is 1.0, on purpose.** The shipped value-flash recipe peaks at 0.25 opacity, which moves
  luminance by less than the 0.1 step, so the real paint could never register. The harness overlays an
  opaque peak so that every start the coalescer lets through is counted: the gate measures the start rate,
  and overstates the paint.
- The negative control is a raw, uncoalesced 5 Hz flash on `data-flash-audit="liquidation-flash-injected"`.
  It must trip G005; the job fails if it does not.
- The sustained check runs 60 s at 40 Hz and asserts the cell is sustained after 10 s and starts nothing
  after that.

## 4. Measured

| Component                    | Measured                          | Limit | Result          |
| ---------------------------- | --------------------------------- | ----- | --------------- |
| `price-flash-harness`        | 2 flashes/s                       | < 3   | pass            |
| `liquidation-flash-injected` | 5 flashes/s                       | < 3   | fail (intended) |
| sustained check (60 s)       | sustained by 10 s; 0 starts after | -     | pass            |

## 5. The counting rule

`count_flashes` takes the luminance samples of one element and keeps every change of at least 0.1 in
relative luminance, the first change of the capture included. WCAG 2.3.1: "a flash is a pair of opposing
changes in relative luminance", so the change count of a window is halved and a dangling half is ignored
(a rise then a fall is one flash; a rise, a fall and a rise is still one). The window slides: every change
opens one, so the gate reports the maximum over any 1 s period, not wall-second buckets. It fails at 3 or
more, one stricter than WCAG's "more than three". Ruled BQ-14 (a); not shortening the harness flash (that
hides it) and not lengthening the window (that deviates from HS-1).

## 6. How CI runs it

- `.github/workflows/_job-a11y.yml` (per PR) and `.github/workflows/a11y-nightly.yml` collect the harness
  report and run `python -m tools.a11y.gates flash <report> --table`, which writes the gate's own table
  (`component | max flashes/s | limit | result`, one row per captured component, named as the collector
  keys it, e.g. `component:price-flash-harness`) to the job step summary; §4 is a curated summary of that
  output. The 60 s sustained check is asserted inside the collector (a failure is `A11Y-INFRA`) and is not
  part of the summary table.
- A second run on the injected 5 Hz report must exit 1 (G005); any other result is `A11Y-INFRA`.
- Older collectors (`flash.collect.ts`, `flash-canvas.collect.ts`) keep their own reports and gates.

## 7. Not in scope here

E47-Q05 (#1357) owns the bench and overhead measurement of the audit. The real consumers (the price flash
of E08-S08, E24's liquidation surface) carry `data-flash-audit` when they are built; see the register.

## 8. Deviations from the ticket (E47-S04, #1318)

| Id    | Ticket said                                             | Shipped                                                                                     | Why                                                                         |
| ----- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| BQ-1  | `Ctrl+Shift+M` does not overwrite the persisted setting | It writes the persisted preference to an explicit on or off and announces once (a)          | E05-D03 §6.5 governs; `05` §3.2 "Session override" wording is the doc's bug |
| BQ-2  | One flash per 400 ms                                    | 500 ms per cell, leading plus trailing, net direction                                       | E05-D03 HS-1 and C-6: 400 ms admits 3 starts a second and fails G005        |
| BQ-4  | A motion token pair the lint enforces                   | Recipe custom properties resolved by `data-motion`; the lint asserts the reduce counterpart | E05-D03 §3, C-7: one mechanism; a literal pair was declined                 |
| BQ-14 | Counted every opposing change as a flash (T02)          | Pairs of opposing changes, first change included                                            | WCAG 2.3.1's definition; ruled (a)                                          |

The write set (packages/ui, apps/web, tools/a11y, docs) and the estimate also differ from the ticket
brief; the ticket was split into a fixture PR and three PRs.
