# E11 Chart interaction: black-box test plan (navigation, scales, axes, crosshair)

Ticket: E11-Q01 (#384). Status: v1.0-partial. This file is the plan; the 90-minute exploratory charter is
`docs/qa/charters/E11-charter-2-interaction.md`. It holds the conventions, the scope, the rulings applied, the combination
matrix, the cases for US-CHART-006, 007 and 008 and the Gherkin of E11-S04 to S07, the combination, boundary, failure and
reduced-motion cases, the dry-run record of the merged rows, the time-control rule, the fixture catalogue with its status
table, the entry and exit criteria with the regression subset, the traceability and the open questions. It contains no
code. E11-Q02 (#444) automates it; E11-Q06 (#518) executes the regression subset and posts the sign-off (section 7). The
rows for E11-S06 (#387) and E11-S07 (#388) are written now and stay **blocked on** those tickets until they merge; the PR
that adds this file therefore references #384 without closing it (BQ-Q01-08, section R).

## 0. Conventions

- **READY sha.** Written and every file:line cite checked at `origin/main` `e5b286ed50d3a320d80b24df5030fb09dd405a4a`
  (`e5b286ed5`). E11-S06 (#387) and E11-S07 (#388) are not on `main` at that sha; their rows are written from the Gherkin
  and the merged design (E11-D02, D03, D06) and are re-checked, with the cites re-pinned, when each merges (section 7).
- **Expectations come from the specification, not the implementation.** Each case names its source:
  - `US-CHART-nnn/k` is scenario k of that story in `docs/plan/11-user-stories.md` (`11`): US-CHART-006 at `11`:979,
    007 at `11`:999, 008 at `11`:1019; `/NFR` is the story's NFR line;
  - `S04.k` to `S07.k` is scenario k, in ticket order, of the Gherkin of E11-S04 to E11-S07 in
    `docs/plan/backlog/E11.json` (`E11J`; the tickets start at :547, :573, :599, :626);
  - `26` is `docs/plan/26-chart-engine-design.md`: momentum `26`:227, autoscale and scales `26`:228, the input table
    `26`:337–347, the shipped S04 notes `26`:351 and `26`:353, the `setPriceScale` command `26`:428, the data cursor and
    its announcement cadence `26`:781, motion `26`:785, the test table `26`:818–824;
  - `D02`, `D03`, `D06` are `docs/design/E11/E11-D02.md`, `E11-D03.md`, `E11-D06.md`;
  - `CE` is `packages/chart-engine/`; a cite such as `CE/src/viewport/transform.ts`:218 is a file and a line.
- **Where sources disagree**, the case follows the merged source and says so; the disagreement is a row in section 10.
  No number, string, event name or field that no merged source states is asserted: it is a † or a **blocked on** row
  with an owner.
- **Case ids:** `E11-Q01-Cnn`. The line under the id names the layer (`03` §2: `unit`, `integration`, `e2e`), the
  environment (below), the matrix cell (section 2) and the sources it mirrors. **[R]** joins the regression subset
  (section 7); **[F]** marks a failure path; **blocked on** names the ticket that must ship first. A blocked case is
  still complete (steps, expected, fixture): it becomes executable the day the blocker merges.
- **Oracles, in order** (BQ-Q01-02): (1) the engine state read through the public API: `PriceScale.getState()`
  (`mode`, `requestedMode`, `inverted`, `autoScale`, `logAvailable`, `logReason`, `anchorTick`; `26`:428), the
  `TimeScale` range and `barSpacing`, the `viewport` message, and (once #388 lands) the crosshair event payload
  (`26`:609) > (2) the DOM: the "Price scale locked" badge, the `[data-cv-keyboard-help]` text, the price-scale menu
  items and their reasons, the DOM mirror and `aria-live` text > (3) pixels: a golden image, from the golden-image lane
  of `26`:820, never a human's impression. Every case also names a **2nd record**: a counter, an emitted event or a
  frame stat. A † marks a record nothing emits at the READY sha.
- **Environments.** No live exchange, ever (C-13.5); no account, key or private data in any step or evidence.
  - **E-ENGINE**: the engine's own harness (the vitest projects of `CE`, fake GL, fake clock). Used for the dry run of
    section 7.2 and by E11-Q02 when it automates a case below the browser.
  - **E-PAGE**: a real browser on a page that mounts the built engine. No app route mounts the chart at the READY sha
    (SCR-030 is the first; `apps/web/test/composition-guard.test.ts`), so the page is the bench matrix page
    `CE/bench/matrix/page/matrix.html`, served by `node packages/chart-engine/bench/matrix/run-matrix.mjs --runtime
chromium --headed`, as E11-C1 does. When a route mounts the chart, E-PAGE moves to that route and the menu steps
    (SCR-043, `apps/web/src/features/chart-price-scale/`) become reachable.
- **Performance.** Every interaction case runs on the 100 000-bar fixture (ticket Performance notes). This plan records
  frame stats as evidence only; the ≥ 55 fps and ≤ 1 frame budgets pass or fail in E11-Q03 (#445) (BQ-Q01-10).
- **Keyboard first.** Every pointer case names its keyboard equivalent or the row that covers it (ticket Accessibility
  notes; `05-accessibility-standard.md` §3.1 item 6, `05`:35). Conformance (axe, screen readers, contrast) is E11-Q05.

## 1. Scope and references

**In scope:** E11-S04 (#385) pan, zoom, momentum and keys; E11-S05 (#386) linear, log, percent, indexed and inverted
scales, autoscale, include-drawings, price-only and the lock; E11-S06 (#387) axes, decimation and keyboard rescale;
E11-S07 (#388) crosshair, OHLCV readout, countdown and magnet. Every Gherkin scenario of US-CHART-006, 007 and 008 and
of S04 to S07 is a named case (section 9).

**Out of scope** (ticket): multi-pane and sync (E11-Q02, except where S06.4 names three panes, which is written here
and executed there); performance budgets (E11-Q03); chaos (E11-Q04, `docs/qa/e11-chaos-charter.md`); accessibility
conformance (E11-Q05); epic regression (E11-Q06); the GPU matrix (E11-Q07); series rendering (E12's QA); writing the
automated E2E suite (E11-Q02). US-CHART-010 and US-CHART-014 are in the ticket's References but not its scenarios; they
are out of this plan (owners E11-Q05 and E11-S13 #520), and the one conflict they raise is OQ-6 (BQ-Q01-12).

**Merged code under test** (READY sha): `CE/src/interaction/` (`gestures.ts`, `momentum.ts`, `navigator.ts`,
`velocity.ts`, `wheel.ts`), `CE/src/host/` (`input-router.ts`, `motion.ts`, `scale-badge.ts`), `CE/src/viewport/`
(`Viewport.ts`, `autoscale.ts`, `transform.ts`), `CE/src/worker/runtime.ts`, and the SCR-043 menu
`apps/web/src/features/chart-price-scale/` (`PriceScaleMenu.tsx`, `copy.ts`).

## R. Rulings applied

The before-writing questions BQ-Q01-01 to 12 were not ruled on #384 when this was written; the plan follows their
PROPOSED defaults, corrected by the scout's critic pass. A ruling that differs is applied in a follow-up revision.

| BQ        | Applied default                                                                                                                                                                                                                                                                                     |
| --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BQ-Q01-01 | The plan lives where the ticket says, `packages/chart-engine/test/plans/`; the charter in `docs/qa/charters/` beside E11-C1. No pointer file.                                                                                                                                                       |
| BQ-Q01-02 | `E11-Q01-Cnn` ids, [R] / [F], blocked-on owners, the oracle ladder of section 0.                                                                                                                                                                                                                    |
| BQ-Q01-03 | Keys follow what is merged: `←/→`, `Shift+←/→`, `Home`, `End` pan the view (`26`:353) until E11-S13's data cursor (#520). The crosshair-key cases (C11, C19) are written for the end state (`26`:781) and are blocked on #388 and #520. The hand-over of all three key groups is case C40 and OQ-1. |
| BQ-Q01-04 | The five fixtures the ticket names do not exist. Section 6 specifies each, names an existing source where one suffices, and gives the owner (E11-Q02). No fixture code or payload is added here.                                                                                                    |
| BQ-Q01-05 | The flat-series case C33 is **executable now** with a precise oracle (finite range, no NaN or Infinity, at least two distinct labelled price ticks). The minimum span is not a number of this plan's: it is OQ-3.                                                                                   |
| BQ-Q01-06 | Percent re-anchors to the left-most fully visible bar when the range changes (S05.2, `26`:228).                                                                                                                                                                                                     |
| BQ-Q01-07 | This plan executes nothing in a browser and adds no Playwright spec; the `CE/README.md` rows that give the Playwright run to E11-Q01 (BQ-17 at :123) are OQ-7, routed to E11-Q02.                                                                                                                   |
| BQ-Q01-08 | The PR references #384 and does not close it: S06 and S07 rows are blocked, and ticket AC 5 (execution and sign-off per scenario) is owned by E11-Q06 (#518), which posts the sign-off on #384. #384 closes when #388 merges, the blocked rows are re-checked, and that sign-off is posted.         |
| BQ-Q01-09 | Indexed is a matrix column (it is S05 scope, `26`:228).                                                                                                                                                                                                                                             |
| BQ-Q01-10 | Frame stats are evidence; pass/fail is E11-Q03's.                                                                                                                                                                                                                                                   |
| BQ-Q01-11 | Readout fields that depend on other epics (delta, indicator values, drawings, live bars) have rows blocked on the owning epic; no value is invented.                                                                                                                                                |
| BQ-Q01-12 | US-CHART-010 and 014 are out of scope (section 1); the 014/3 versus `26`:781 conflict is OQ-6 and is not written as a case.                                                                                                                                                                         |

## 2. The combination matrix

Axes (each is individually unit-tested; the defects live in their product, ticket Technical notes):

- **Mode** M: `linear`, `log`, `percent`, `indexed` (`CE/src/api/scales.ts`:12), each upright or **inverted** (I).
- **Autoscale** A: `auto` (on) or `locked` (off; the lock is autoscale's off state, `26`:228).
- **Extents** X: bars only, `include drawings`, `price only`.
- **Zoom anchor** Z: the cursor in mid-plot, the right edge with the latest (forming) bar, the time axis (right-edge anchor).
- **Input** N: pointer drag, wheel (incl. `Shift` and a trackpad pinch), keyboard.
- **Motion** R: normal or reduce.

The matrix is reduced by pairs plus the ticket's six named triples; every cell is a case below.

| Cell | M × I               | A      | X          | Z / N                     | R      | Case(s)         | Status at READY            |
| ---- | ------------------- | ------ | ---------- | ------------------------- | ------ | --------------- | -------------------------- |
| K1   | log                 | auto   | bars       | price-axis drag (→ lock)  | normal | C26             | executable (E-ENGINE half) |
| K2   | percent             | auto   | bars       | pan until ref. off-screen | normal | C27             | executable                 |
| K3   | log × inverted      | auto   | bars       | wheel mid                 | normal | C28             | executable                 |
| K4   | linear              | auto   | bars       | right edge, forming bar   | normal | C29             | forming bar blocked on E12 |
| K5   | any → log mid-glide | auto   | bars       | flick then mode change    | normal | C30             | executable, no test (OQ-5) |
| K6   | linear              | auto   | bars (gap) | crosshair magnet          | normal | C31             | blocked on #388            |
| K7   | indexed             | locked | bars       | keyboard pan              | normal | C32             | executable                 |
| K8   | linear              | auto   | drawings   | pan                       | normal | C02             | engine half executable     |
| K9   | log                 | auto   | price only | wheel                     | reduce | C26 step 6, C42 | executable                 |
| K10  | percent × inverted  | locked | bars       | last-price label          | normal | C21             | blocked on #387            |

## 3. Cases by user story

Each case: **Pre** (fixture and state), **Steps**, **Expected**, **Source** (oracle order, then the 2nd record),
**Verifies** (the E11 ticket). The dry-run result of every merged row is in section 7.2.

### 3.1 US-CHART-006 Pan, zoom, autoscale (Must)

**E11-Q01-C01 Drag pans, wheel zooms, a flick coasts and the 100 000-bar chart keeps up [R]** (`e2e`; E-PAGE ·
linear, auto, bars, N = pointer and wheel, R = normal; mirrors US-CHART-006/1, S04.1)

- Pre: FX-100K loaded (section 6); viewport at the latest bar; frame stats on.
- Steps: (1) drag the plot 300 px left at a steady speed and stop for 200 ms before release; (2) drag 300 px and release
  while moving at ≥ 1 px/ms; (3) wheel 10 notches in over mid-plot, then 10 out; (4) read the `TimeScale` range after
  each step.
- Expected: (1) the range moves by 300 px / `barSpacing` bars and stays there (no coast after > 100 ms still, `26`:227);
  (2) after release the view keeps moving and rests at `x₀ + v₀τ` with τ = 120 ms (`26`:227), no bounce at a clamp;
  (3) `barSpacing` changes by `exp(−px·0.002)` per wheel px (`CE/src/interaction/wheel.ts`:39) and returns to its start
  within one ulp-scale rounding after the symmetric sweep; the bar under the cursor stays put (C13).
- Source: the `TimeScale` range > the frame. 2nd: frame stats (`onFrameStats`) recorded as evidence; ≥ 55 fps and
  ≤ 1 frame latency are judged by E11-Q03 (BQ-Q01-10).
- Keyboard equivalent: C04. Verifies E11-S04.

**E11-Q01-C02 Autoscale fits the visible bars, and the drawings only when asked [R]** (`integration`; E-ENGINE
now, E-PAGE when a drawing can be placed · linear, auto, bars → drawings; mirrors US-CHART-006/2, S05.5; the drawing half
blocked on E14 for a user-placed drawing)

- Pre: FX-100K; a horizontal drawing placed 20 % of the visible price range above its top; `include drawings` off.
- Steps: (1) pan by 50 bars and read the price range; (2) turn `include drawings` on (menu, or `setPriceScale
{ includeDrawings: true }`) and read the range on the next frame.
- Expected: (1) the range is the visible bars' min and max plus 5 % of the window top and bottom (`26`:228) and excludes
  the drawing; (2) on the next frame the range includes the drawing, again with the 5 % margins.
- Source: `PriceScale.getState()` and the range > the drawing's pixel inside the plot. 2nd: one refit per change
  (`26`:228 "at most once per frame"); a refit counter is †.
- Verifies E11-S05.

**E11-Q01-C03 Dragging the price axis locks it; double-click restores auto-fit [R]** (`e2e`; E-PAGE · linear, auto
→ locked, N = pointer; mirrors US-CHART-006/3, S05.4)

- Pre: FX-100K; autoscale on.
- Steps: (1) drag the price axis 80 px down; (2) read the state and look for the badge; (3) pan the plot vertically 40 px;
  (4) double-click the price axis; (5) repeat (1), then activate the badge with `Enter`.
- Expected: (1)–(2) `autoScale` is false and a badge with the accessible name "Price scale locked"
  (`CE/src/host/scale-badge.ts`:10; S05.4) appears on the axis; (3) a vertical plot drag now pans price (`26`:228; it was
  inert while auto, `26`:351); (4) `autoScale` is true, the badge is gone and the range is refitted; (5) the same as (4)
  (D03 D8, `D03`:79: double-click = `Home` = `Enter` on the badge = Reset).
- Source: `getState().autoScale` > the badge node and its name > pixels. 2nd: the `viewport` message's `autoScale`.
- Keyboard equivalent: C04 step 5 (`Ctrl+Home`) and C19 (`Home` on the focused axis, blocked on #387).
- Verifies E11-S05.

**E11-Q01-C04 Every pointer gesture has a keyboard equivalent [R]** (`e2e`; E-PAGE · linear, auto, N = keyboard;
mirrors US-CHART-006/NFR, S04.4; the cursor-bar target of `+/-` is blocked on #520)

- Pre: FX-100K; the chart container focused by `Tab`; no pointer over the plot.
- Steps: press, reading the `TimeScale` range after each: `←`, `→`, `Shift+→`, `Home`, `End`, `+`, `-`, `Ctrl+Home`.
- Expected (as merged, `26`:353): `←`/`→` move the view by one bar, `Shift+→` by ten; `Home` puts bar 0 at the left edge;
  `End` puts the latest bar 12 bars in from the right edge; `+`/`-` zoom by 1.1 about the latest bar (no pointer in the
  plot); `Ctrl+Home` restores the default spacing, shows the latest bar and restores autoscale; `Ctrl` or `Meta` with
  `+`/`-` does nothing (it is the browser's zoom); every jump is a cut, never animated.
- Source: the range and `barSpacing` > `getState().autoScale` after `Ctrl+Home`. 2nd: the `key` input rows
  (`26`:426).
- Note: US-CHART-006/NFR says "Home" resets; S04.4 and `26`:353 make `Home` the first bar and `Ctrl+Home` the reset.
  The case follows the merged S04 (OQ-2). Verifies E11-S04.

### 3.2 US-CHART-007 Log and percentage scales (Must / Should)

**E11-Q01-C05 Log re-projects candles, gridlines, drawings, levels and profiles through one transform [R]**
(`integration`; E-ENGINE now; the golden image and the profile are blocked; mirrors US-CHART-007/1, S05.1)

- Pre: FX-100K; a trend line anchored at two (bar, price) pairs; a horizontal level; a visible-range volume profile.
- Steps: switch the price scale linear → log; read each object's projected y for its anchors; capture a frame.
- Expected: every object's y is the shared transform's (`26`:228: `projectRel` serves the 2D painter, drawings,
  hit-testing and the readout; `26`:772 the GPU twin); the drawing's two anchors stay on the same (bar, price) pairs
  within 0.01 px of the candles' y; the golden image matches its log baseline.
- Source: the projected y of each anchor against the candle y > the golden image. 2nd: none emitted (a read).
- Blocked: the golden image on the golden-image lane (`26`:820); the trend line and level as user objects on E14; the
  profile on its owning epic. Verifies E11-S05.

**E11-Q01-C06 Percent reads as change from the left-edge reference bar's close [R]** (`integration`; E-ENGINE ·
percent; mirrors US-CHART-007/2, S05.2; the crosshair-readout half blocked on #388)

- Pre: FX-100K; percent mode.
- Steps: (1) read `anchorTick` and the axis labels; (2) pan left by half a bar, then by 30 bars, reading `anchorTick`
  after each; (3) once #388 lands, move the crosshair across the range and read the readout.
- Expected: (1) `anchorTick` is the close of the left-most **fully** visible bar (`26`:228); an axis label for price p
  reads `(p − close_ref) / close_ref × 100` %; (2) the reference re-anchors to the new left-most fully visible bar each
  time; (3) the readout shows the same percent as the axis for the hovered price.
- Source: `getState().anchorTick` > the axis labels > the readout. 2nd: the `viewport` message's `anchorTick`.
- Verifies E11-S05 (and E11-S07 for step 3).

**E11-Q01-C07 Log is refused, not faked, on non-positive data [R][F]** (`e2e`; E-ENGINE now, E-PAGE when a route
mounts SCR-043 · linear → log; mirrors US-CHART-007/3, S05.3)

- Pre: FX-NONPOS (a 0 low inside the loaded range); linear mode.
- Steps: (1) open the price-scale menu; (2) try to choose "Logarithmic" by click, `Enter` and `Space`; (3) read the state.
- Expected: (1) "Logarithmic" is present, `aria-disabled`, with the reason "Log scale needs all-positive values; this
  series contains a value <= 0" (D03 §3.5 D4, quoted by `apps/web/src/features/chart-price-scale/copy.ts`); (2) nothing
  changes and the reason is re-said; (3) `mode` stays `linear`, `logAvailable` false, `logReason` `non-positive` (a code,
  never copy); the frame has no artefact (no NaN vertex, no blank plot).
- Source: `getState()` > the menu item's state and reason > pixels. 2nd: the `viewport` message's `logReason`.
- Verifies E11-S05.

**E11-Q01-C08 A scale change is a projection change only** (`integration`; E-ENGINE · linear → log; mirrors S05.6)

- Pre: FX-100K; a spy on data requests (the app's data source, or the worker's inbound `bars` messages).
- Steps: switch linear → log → percent → linear.
- Expected: no data request and no `bars` message is issued; each switch redraws on the next frame
  (`CE/src/worker/runtime.ts`:491–492 marks TRANSFORM only).
- Source: the request spy > the frame count between command and draw. 2nd: frame stats; the one-frame budget is
  E11-Q03's. Verifies E11-S05.

### 3.3 US-CHART-008 Crosshair, OHLCV readout and countdown (Must): blocked on #388

**E11-Q01-C09 The readout shows O, H, L, C, volume, delta, time and each visible indicator's value [R]** (`e2e`;
E-PAGE · mirrors US-CHART-008/1, S07.1; blocked on #388, delta on its order-flow owner, indicators on E13, the active
timezone on E11/E12's timezone setting)

- Pre: FX-REC (450 recorded 1-minute bars, section 6) with one indicator on the pane.
- Steps: hover bar k (k = 0, 1, 224, 449), one at a time; read the readout; read the DataModel row k.
- Expected: each field equals the DataModel row k exactly (no interpolation between bars); the time is the bar's open in
  the active timezone; each visible indicator's value is its value at bar k. A field whose owner has not shipped is
  absent, never zero or blank-filled.
- Source: the DataModel row > the readout text. 2nd: the crosshair event's `barIndex` (`26`:609).
- Verifies E11-S07.

**E11-Q01-C10 The countdown shows seconds to close and warns with the word "closing" in the final 10 s [R]**
(`e2e`; E-PAGE with a fake clock · mirrors US-CHART-008/2, S07.2; blocked on #388 and on live bars, E12)

- Pre: a 1-minute interval; the fake clock at 12 s before close.
- Steps: advance the clock 1 s at a time to 2 s after close, capturing each frame.
- Expected: `0:12`, `0:11`, then `0:10 closing` … `0:01 closing`, then closed, then `0:59` (`D06`:15; D02 D11, the warn
  state adds the word "closing" and the warning token); identical under reduce (no flash); a greyscale render of the
  warn frame still carries the word.
- Source: the countdown text > the token class > pixels (greyscale). 2nd: none (a read).
- Verifies E11-S07.

**E11-Q01-C11 Keyboard crosshair steps bar by bar and announces at the D5 cadence [R]** (`e2e`; E-PAGE · mirrors
US-CHART-008/3, S07.3; blocked on #388 and #520 (the data cursor))

- Pre: FX-100K; the chart focused; an `aria-live` observer recording each announcement with its time.
- Steps: (1) press `→` once; (2) hold `→` so that 30 bars are traversed in 3 s; release; wait 300 ms of fake time.
- Expected: (1) the cursor moves one bar and is announced at once (`leadDelay` 0 ms, `26`:781); (2) the readout updates
  every frame; while held, at most one announcement per 500 ms window (`repeatWindow`), each in the short form (time
  and close) carrying the latest bar; the final bar is announced in the full form within 250 ms of release
  (`trailingFlush`). The count must not exceed the bound S07.3 states (6) unless OQ-4 rules that the lead and trailing
  announcements are outside it.
- Source: the announcement log (text, time) > the cursor bar index. 2nd: the crosshair events (one per bar).
- Verifies E11-S07 (with E11-S13).

### 3.4 E11-S04 Pan, zoom, momentum and keys: the remaining Gherkin (merged)

**E11-Q01-C12 Frame floor on a 1000 px/s pan and a 0.1 → 50 px/bar zoom sweep** (`e2e`; E-PAGE · mirrors S04.1)

- Pre: FX-100K. Steps: pan at 1000 px/s for 5 s (scripted pointer), then wheel-zoom from 0.1 to 50 px/bar.
- Expected (this plan's half): the view tracks the pointer with no stall, `barSpacing` ends at 50 within one notch, no
  frame shows a blank plot. The fps and latency figures are recorded and judged by E11-Q03 against B1 and B2
  (`26`:798).
- Source: the range and `barSpacing` > frame stats (evidence). Verifies E11-S04.

**E11-Q01-C13 Zoom is anchored to the cursor within 0.5 px [R]** (`integration`; E-ENGINE / E-PAGE · Z = mid;
mirrors S04.2)

- Pre: FX-100K; the cursor resting over the 14:00 bar.
- Steps: three wheel notches in; read the 14:00 bar's x after each.
- Expected: within 0.5 px of the cursor x at every step; a wheel with the cursor over the price gutter zooms no time.
- Source: the bar's screen x through the time scale > pixels. Verifies E11-S04.

**E11-Q01-C14 Reduced motion: release stops at once, and the help says inertia is off [R]** (`e2e`; E-PAGE · R =
reduce; mirrors S04.3, US-CHART-006/1 "inertia that respects reduced-motion")

- Pre: FX-100K; the app's resolved motion `reduce` (`data-motion="reduce"` on the document root, or the OS setting;
  the in-app override wins both ways, `26`:785).
- Steps: (1) flick the plot and release; (2) read the range on that frame and 500 ms later (fake clock); (3) read
  `[data-cv-keyboard-help]`.
- Expected: (1)–(2) the view rests at the release position, no glide; (3) the help ends with "Inertia is off while
  reduced motion is on — the chart stops where you release it." (E11-D06 §16, `CE/src/host/motion.ts`:15).
- Source: the range > the help text. 2nd: no momentum frame (the scheduler's animation count, †).
- Verifies E11-S04.

**E11-Q01-C15 A 240 Hz trackpad cannot flood the worker [R]** (`integration`; E-ENGINE · N = wheel; mirrors S04.5)

- Pre: a scripted source of 240 wheel events per second for 1 s, mixed zoom and `Shift` pan.
- Expected: at most one `wheel` input batch per frame reaches the worker; the summed posted delta equals the summed raw
  delta for each class (zoom, pan): no step is lost.
- Source: the posted `input` rows > the raw sum. Verifies E11-S04.

**E11-Q01-C16 A new pointer-down cancels the glide on that frame [R]** (`integration`; E-PAGE · N = pointer, touch;
mirrors S04.6)

- Steps: flick to start a glide; 50 ms later put a finger (or the mouse) down on the plot and drag 40 px.
- Expected: the glide stops on that frame; the drag begins from the current position (no jump back or forward).
- Source: the range at the down frame and after. Verifies E11-S04.

### 3.5 E11-S06 Axes, decimation and keyboard rescale: blocked on #387

**E11-Q01-C17 Time labels decimate instead of colliding, and stay stable while panning** (`e2e`; E-PAGE; mirrors
S06.1; blocked on #387)

- Pre: FX-100K at 400 bars over 1200 px. Steps: render; pan 1 bar per frame for 120 frames, recording the label set.
- Expected: no two labels overlap; each keeps ≥ 1.5 label-heights of clear space; a label present in frames n and n+2
  is present in n+1 (no blink).
- Source: the DOM mirror's tick list (C20) > pixels. Verifies E11-S06.

**E11-Q01-C18 Hairlines are crisp at DPR 1.25** (`e2e`; E-PAGE with DPR 1.25; mirrors S06.2; blocked on #387 and the
golden-image lane)

- Expected: gridlines and the axis rule snap to a device pixel; the golden image shows one-pixel lines with no grey fringe.
- Source: the golden image. Verifies E11-S06.

**E11-Q01-C19 The price axis rescales by keyboard and announces politely [R]** (`e2e`; E-PAGE · N = keyboard; mirrors
S06.3; blocked on #387)

- Steps: focus the price axis; press `↑` five times, then `Home`.
- Expected: the range compresses one step per press; each new range is announced politely, at most twice per second;
  `Home` restores auto-fit and announces "Price scale: auto" (S06.3; the same string is in `copy.ts` `said.auto`).
- Source: `getState()` > the announcements. Verifies E11-S06.

**E11-Q01-C20 Tick labels are in the accessibility tree and match the canvas** (`e2e`; E-PAGE; mirrors S06.5; blocked on
#387)

- Expected: the DOM mirror lists the current price ticks and time labels as a readable list, equal to the drawn labels
  of that frame. Source: the mirror list > the label set drawn (from the frame's text runs). Verifies E11-S06.

**E11-Q01-C21 The last-price label wins over a nearby tick** (`e2e`; E-PAGE; mirrors S06.6; blocked on #387)

- Pre: a series whose last price is within one label height of a regular tick (FX-REC, a bar chosen at execution).
- Expected: the regular tick label is suppressed; the last-price label is drawn in full. Also run in percent × inverted,
  locked (matrix K10). Verifies E11-S06.

**E11-Q01-C22 The time axis is the master clock for three panes** (`e2e`; E-PAGE; mirrors S06.4; blocked on #387;
executed by E11-Q02, which owns multi-pane)

- Expected: a time-axis drag changes every pane's `barSpacing` in the same frame; no pane lags. Verifies E11-S06.

### 3.6 E11-S07 Crosshair: the remaining Gherkin (blocked on #388)

**E11-Q01-C23 The tooltip is aria-hidden and its values are in the mirror** (`e2e`; E-PAGE; mirrors S07.4)

- Expected: while a screen reader is active and the pointer hovers a bar, the tooltip is `aria-hidden` and is not
  announced; the focused bar's values are reachable through the DOM mirror. Pointer hover never moves the selection or
  the mirror's `aria-current` (`26`:781). Verifies E11-S07.

**E11-Q01-C24 Crosshair events are edge-triggered per bar [R]** (`integration`; E-ENGINE / E-PAGE; mirrors S07.5)

- Steps: move the pointer 200 px vertically within one bar's width; count crosshair events.
- Expected: exactly one event for that bar; the readout's price component updates every frame without an event.
- Source: the event count > the readout. Verifies E11-S07.

**E11-Q01-C25 Magnet "strong" snaps to the high and labels it** (`e2e`; E-PAGE; mirrors S07.6)

- Pre: magnet `strong`; the pointer 12 px from a bar's high.
- Expected: the crosshair snaps to the high; the readout labels the value "High" (S07.6; D02 D9, the price pill gains
  the OHLC label). Verifies E11-S07.

### 3.7 Combination cases (ticket Scope; matrix K1–K10)

**E11-Q01-C26 Log + autoscale + manual lock [R]** (`integration`; E-ENGINE now, E-PAGE when mounted · K1, K9)

- Pre: FX-SPIKE (section 6); log; auto.
- Steps: (1) read the range; (2) drag the price axis 60 px; (3) drag the plot vertically 40 px; (4) pan 200 bars so the
  spike enters the window; (5) double-click the price axis; (6) set `price only` and repeat (4) under reduce.
- Expected: (1) the fit's 5 % margins are in log space, so the low never reaches 0 (`26`:228); (2) `autoScale` false,
  the badge present, mode still `log`; (3) the price range shifts by equal log distances at both ends (a log pan, not a
  linear one); (4) a locked scale is **not** refitted when the spike enters; (5) auto-fit restored in log space,
  including the spike; (6) the fit excludes overlays and keeps the log guard (`26`:228).
- Source: `getState()` and the range in log units > the badge > pixels. 2nd: the `viewport` messages.
- Verifies E11-S05.

**E11-Q01-C27 Percent with the reference bar scrolled out of view [R]** (`integration`; E-ENGINE · K2)

- Steps: in percent, pan right until the original reference bar is off-screen; read `anchorTick` and an axis label.
- Expected: the reference re-anchors to the new left-most fully visible bar (BQ-Q01-06, S05.2); labels re-express as
  change from that bar's close; no label refers to the old reference. A fixed off-screen reference is a defect.
- Source: `anchorTick` > labels. Verifies E11-S05.

**E11-Q01-C28 Inverted + log** (`integration`; E-ENGINE · K3)

- Steps: log, then invert; wheel-zoom mid-plot; read the y of the highest and lowest visible prices.
- Expected: the highest price is at the bottom, the lowest at the top; the mapping is the log projection then flipped
  (`26`:228: invert flips the coefficients); the gap between two prices of equal ratio is the same pixel distance
  anywhere on the axis. Verifies E11-S05.

**E11-Q01-C29 Zoom at the extreme right edge with the forming bar** (`e2e`; E-PAGE · K4; the forming-bar half blocked
on E12 live bars)

- Steps: `End`; zoom in with `+` (no pointer in the plot), then wheel at the plot's right edge; append a tick to the
  forming bar between notches.
- Expected: `+` zooms about the latest bar (`26`:353), which stays at the same x; the wheel zooms about the true plot x
  (a cursor over the price gutter zooms no time); the forming bar's update moves no bar horizontally. Verifies E11-S04.

**E11-Q01-C30 Momentum interrupted by a scale change [F]** (`integration`; E-ENGINE / E-PAGE · K5)

- Steps: flick to start a time glide; at 40 ms switch linear → log (and, in a second run, toggle `inverted`).
- Expected (from `26`:227, which lists the only glide terminations: below 0.02 px/ms, a new pointer-down, reduced motion):
  the glide continues and rests at `x₀ + v₀τ` exactly as without the switch; the price range refits under the new mode
  at most once per frame during the glide; no frame has a NaN or a blank plot.
- Source: the rest position against a control run without the switch > `getState()`. 2nd: frame stats.
- Note: no merged test covers this combination (section 7.2); if a ruling says a scale change should end the glide,
  OQ-5 records it. Verifies E11-S04 and E11-S05.

**E11-Q01-C31 Crosshair magnet across a gap in data** (`e2e`; E-PAGE · K6; blocked on #388 and FX-GAP)

- Steps: magnet `strong`; move the pointer across the gap from the bar before it to the bar after it.
- Expected: inside the gap the crosshair resolves to a real bar on one side or the other, never to an interpolated
  value or a phantom bar; which side is the S07 / D02 rule (OQ-8 until #388 states it); the readout names the snapped
  bar's time. Verifies E11-S07.

**E11-Q01-C32 Indexed mode with a lock and keyboard pan** (`integration`; E-ENGINE · K7)

- Steps: indexed; lock (drag the axis); pan with `→` ten times.
- Expected: indexed draws as linear and relabels against the anchor bar's close as 100 (`26`:228); the anchor re-anchors
  on a range change as in percent; the locked range does not refit. Verifies E11-S05.

### 3.8 Boundary cases

**E11-Q01-C33 A flat series (zero price range) gives a sane, labelled axis [R][F]** (`integration`; E-ENGINE now for
the range, E-PAGE for the labels after #387 · linear and log, auto)

- Pre: FX-FLAT (every O, H, L, C equal).
- Steps: load; read the price range; read the price-axis tick labels (`PriceScale` tick window now, the mirror list after
  #387); switch to log and read again.
- Expected: the range is finite, low < high, no NaN or Infinity anywhere in `getState()` or the frame; the axis shows at
  least two distinct labelled price ticks; the flat price sits inside the plot, not on an edge. The minimum span is OQ-3,
  not a number of this plan's.
- Source: the range > the tick labels > pixels. 2nd: none.
- Predicted by the dry run (section 7.2): the range is exactly one tick wide (`CE/src/viewport/transform.ts`:221), which
  likely fails the two-labelled-ticks oracle. File against E11-S05 after OQ-3 is ruled, not before. Verifies E11-S05.

**E11-Q01-C34 One bar, then two bars** (`integration`; E-ENGINE · linear and log)

- Steps: load one bar; pan, zoom, `Home`, `End`, autoscale; then append a second bar and repeat.
- Expected: the bar stays reachable (the left index stays in `[1 − visibleBars, n − 1]`, `CE/src/viewport/Viewport.ts`:59);
  `End` with fewer than 13 bars visible clamps the offset; autoscale gives a finite range (a single bar with H > L fits
  normally; with H = L see C33). Verifies E11-S04 and E11-S05.

**E11-Q01-C35 Non-positive data with log requested, including a 0 arriving mid-session [F]** (`integration`; E-ENGINE
· log)

- Steps: (1) as C07; (2) with log active on positive bars, append a bar with a negative low; (3) load a persisted log
  preference onto a series whose first bars hold a 0.
- Expected: (2) the chart falls back to linear **before** the frame that would draw the bad bar, keeps `requestedMode`
  `log`, and the menu says the D5 fallback once ("Log scale unavailable — switched to linear: this series now contains a
  value <= 0", `copy.ts`); (3) stays linear and keeps the request. Verifies E11-S05.

**E11-Q01-C36 Bar spacing at its minimum and maximum** (`integration`; E-ENGINE)

- Steps: zoom out past the minimum and in past the maximum by wheel, keys and time-axis drag.
- Expected: `barSpacing` clamps at 0.05 and 200 px (`CE/src/viewport/Viewport.ts`:46–47) by every input; further input
  changes nothing and causes no drift of the anchor bar. Verifies E11-S04.

**E11-Q01-C37 The first and the last bar of the series** (`integration`; E-ENGINE / E-PAGE)

- Steps: `Home` then `←` five times; `End` then `→` five times; drag past each end; flick past each end.
- Expected: the view stops at the clamp (`Viewport.ts`:59) with no bounce; the glide stops at the clamp and counts one
  cancel. Verifies E11-S04.

### 3.9 Failure cases

C30 (scale change mid-glide) is the first failure case. The others:

**E11-Q01-C38 Rapid repeated mode switching [F]** (`integration`; E-ENGINE / E-PAGE)

- Steps: send 20 `setPriceScale` mode changes cycling linear, log, percent, indexed within one frame; then 20 across 20
  frames.
- Expected: the state after the burst is the last command's; at most one refit per frame; the menu reports what the
  engine holds, not what was asked; no frame draws a mixed state (gridlines from one mode, candles from another).
- Source: `getState()` > the menu > pixels. Verifies E11-S05.

**E11-Q01-C39 Keyboard and pointer input in the same frame [F]** (`integration`; E-ENGINE)

- Steps: in one frame, post a wheel notch and a `→`; in another, a plot drag of 30 px and `Shift+→`.
- Expected: both apply in that frame (input rows are coalesced per kind, `26`:406 "≤ 1/frame"); the result equals
  applying them one after the other; no delta is lost. The order inside a frame is OQ-1's. Verifies E11-S04.

**E11-Q01-C40 Key ownership hand-over: arrows, Home and End once the data cursor lands** (`e2e`; E-PAGE; blocked on
#520)

- Expected (`26`:781): `←/→` move the cursor, and a step past the visible edge pans by a bar; `Home`/`End` go to the
  oldest loaded bar / the latest bar with auto-follow; `+`/`-` and `Space` change the viewport without announcing. C04
  is re-baselined to this on #520's merge (OQ-1). Verifies E11-S07 / E11-S13.

**E11-Q01-C41 Interaction during a data update storm [F]** (`integration`; E-ENGINE / E-PAGE · auto)

- Steps: while appending and patching 200 bars per second inside the visible window for 10 s (fake clock), pan, wheel
  and drag the price axis.
- Expected: input keeps one batch per kind per frame; autoscale refits on in-window mutations at most once per frame
  (`26`:228, C-29 in `CE/README.md`); a locked scale does not refit; no frame backlog after the storm. Verifies E11-S04
  and E11-S05.

### 3.10 Reduced motion as a first-class path

C14 is the base case. Also:

**E11-Q01-C42 Reduce switched on mid-glide stops the glide where it is [R]** (`integration`; E-ENGINE / E-PAGE · R)

- Steps: flick; at 40 ms set `data-motion="reduce"` (or dispatch `candleviewer:themechange` with `detail.motion` reduce).
- Expected: the glide stops on the next frame where it is (`26`:227 PR 2 note); switching back to normal does not resume
  it; the help text gains the inertia sentence. Verifies E11-S04.

**E11-Q01-C43 Under reduce, every navigation is a cut and the countdown is unchanged** (`e2e`; E-PAGE · R; the countdown
half blocked on #388)

- Expected: `Home`, `End`, `Ctrl+Home`, double-click reset and keyboard zoom jump with no animation (`26`:353 "every jump
  is a cut"); the crosshair hides and reappears at 0 ms (`D06`:14); the countdown strip is identical in both modes
  (`D06`:15). Verifies E11-S04 and E11-S07.

### 3.11 Exploratory charter

`docs/qa/charters/E11-charter-2-interaction.md`: 90 minutes, mission, areas, oracles, session sheet and debrief
(`03` §11.2, `03`:316).

## 4. Time control

No case sleeps. Momentum, the announcement cadence, the countdown and the 100 ms "rested" rule are driven by a fake
clock (E-ENGINE) or by the page's injected frame clock (E-PAGE); waits are on events or frames, never wall time
(C-13.7). Wheel and pointer sequences are scripted with explicit timestamps (as `CE/test/worker/input-router.test.ts`:81
does) so a run is repeatable.

## 5. Destructive and fixture protocol

Nothing in E11 persists user data. A case that changes a persisted preference (log requested, lock) resets it at the end.
Fixtures are read only; a generated fixture is regenerated from its seed, never edited.

## 6. The fixture catalogue

The ticket names five fixtures in `packages/fixtures`. None exists at the READY sha (a grep finds the names only in the
backlog JSON). Each is specified below precisely enough to generate; until it exists, the case uses the stand-in named.
Recorded BTCUSDT data comes only from `packages/fixtures/bybit/` (C-13.5); nothing here is an invented exchange payload.

| Id        | Ticket name             | Status at READY | Specification (owner: E11-Q02 #444)                                                                                                                         | Stand-in today                                                                                   |
| --------- | ----------------------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| FX-100K   | `btcusdt-1m-100k`       | missing         | 100 000 one-minute bars from `CE/bench/fixtures/bars.mjs` `generateBars({ seed: 20260928, count: 100000, symbol: "BTCUSDT" })`, ticks with the bench origin | the same generator call (the bench's fixed dataset; seed default per `run-matrix.mjs`:14)        |
| FX-SPIKE  | `btcusdt-1m-spike`      | missing         | FX-100K with one bar at index 60 000 whose high is +25 % of the series range above the series high; nothing else changed                                    | none; C26 step 4 waits                                                                           |
| FX-GAP    | `btcusdt-1m-gap`        | missing         | FX-100K with bars 50 000–50 059 absent (one hour), times kept, the index map skipping them                                                                  | the generator's `gap: true` bars (price gaps, not time gaps) for decimation; none for the magnet |
| FX-FLAT   | `synthetic-flat`        | missing         | 500 one-minute bars, O = H = L = C = 6 000 000 ticks, volume 1                                                                                              | none; C33 needs it                                                                               |
| FX-NONPOS | `synthetic-nonpositive` | missing         | 500 one-minute bars of FX-FLAT's shape with prices rising 1 tick per bar, bar 250's low set to 0 (and a variant with −1)                                    | the columns the merged autoscale tests build (`CE/test/viewport/autoscale.test.ts`:134, :184)    |
| FX-REC    | (not in the ticket)     | present         | the recorded BTCUSDT 1-minute klines `packages/fixtures/bybit/2026-10-05/rest/kline_BTCUSDT_1_page{0,1,2}.json`, 200, 200 and 50 bars (450)                 | itself; for readout values, which must be real bars                                              |
| FX-MIN    | (not in the ticket)     | present         | `CE/test/interaction/fixtures.ts` `minuteMap()`: a synthetic 1-minute index map, T0 2026-10-30T00:00Z, the 14:00 bar `AT_14`                                | itself; used by the dry run for anchoring and gesture cases                                      |

A case whose fixture is missing is not executable until the fixture lands; section 7 counts those cases as **not run,
fixture missing**, never as passed.

## 7. Entry and exit criteria, the dry run, and the regression subset

### 7.1 Entry and exit

- **Entry:** the build under test is a `main` sha; for a blocked row, its blocker has merged and the row's cites have been
  re-checked at that sha; the row's fixture exists (section 6).
- **Exit (this plan's execution, owned by E11-Q06 #518):** every case is passed, failed with a defect filed (priority
  and owner, linked to the E11 ticket and to this case id), or not run with the reason; a sign-off comment on #384 lists
  each case's result with evidence (ticket AC 5; `02-definition-of-ready-done.md`:77).

### 7.2 Dry run at the READY sha (merged rows only)

Dry run = each merged case traced to the code and the test that would satisfy it. "Traced" means the expected value is
stated and a merged test asserts it in E-ENGINE; "gap" means no merged test asserts it, so the first execution decides.
No browser was run.

| Case | Result  | Code                                                                                | Test that asserts it today                                                                                            |
| ---- | ------- | ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| C01  | traced  | `src/interaction/momentum.ts`:26, `wheel.ts`:39                                     | `test/interaction/gestures.test.ts`:54; `momentum.test.ts`:30, :55, :108; fps: E11-Q03                                |
| C02  | traced  | `src/viewport/autoscale.ts`:48                                                      | `test/viewport/autoscale.test.ts`:44, :104 (drawing as an extent; a user-placed drawing waits for E14)                |
| C03  | traced  | `src/host/scale-badge.ts`:10, :22; `src/interaction/gestures.ts`:29                 | `test/interaction/gestures.test.ts`:67, :232; `test/api/price-scale.test.ts`:83; `test/viewport/autoscale.test.ts`:75 |
| C04  | traced  | `src/interaction/navigator.ts`:63–85                                                | `test/interaction/navigator.test.ts`:32, :43, :53, :71, :81, :95                                                      |
| C05  | partial | `src/viewport/transform.ts` (`projectRel`)                                          | `test/viewport/scales.test.ts`:42, :146, :160; `scenarios.test.ts`:63; golden image and profile: blocked              |
| C06  | traced  | `src/viewport/autoscale.ts` (anchor)                                                | `test/viewport/autoscale.test.ts`:119; `scales.test.ts`:55; readout: blocked on #388                                  |
| C07  | traced  | `src/viewport/autoscale.ts`:36; `apps/web/.../copy.ts`                              | `test/viewport/autoscale.test.ts`:134, :203; `apps/web/test/features/chart-price-scale/PriceScaleMenu.test.tsx`:289   |
| C08  | partial | `src/worker/runtime.ts`:491–492                                                     | no test asserts "no refetch" end to end; the TRANSFORM-only path is read from the code                                |
| C12  | partial | as C01                                                                              | functional half as C01; B1 / B2 are E11-Q03's                                                                         |
| C13  | traced  | `src/viewport/Viewport.ts`:199                                                      | `test/viewport/scenarios.test.ts`:26; `test/interaction/wheel.test.ts`:48                                             |
| C14  | traced  | `src/interaction/gestures.ts`:73; `src/host/motion.ts`:15                           | `test/interaction/gestures.test.ts`:138; `test/api/keyboard-help.test.ts`:24, :44                                     |
| C15  | traced  | `src/host/input-router.ts`:44                                                       | `test/worker/input-router.test.ts`:81                                                                                 |
| C16  | traced  | `src/interaction/gestures.ts`:102                                                   | `test/interaction/gestures.test.ts`:83                                                                                |
| C26  | partial | `src/viewport/transform.ts`:182, :207                                               | parts: `autoscale.test.ts`:75, :88; `scales.test.ts`:192; the three-way product: gap                                  |
| C27  | traced  | as C06                                                                              | `test/viewport/autoscale.test.ts`:119                                                                                 |
| C28  | traced  | `src/viewport/transform.ts` (coefficients)                                          | `test/viewport/scales.test.ts`:71 ("in every mode")                                                                   |
| C29  | partial | `src/interaction/navigator.ts`:56                                                   | `test/interaction/navigator.test.ts`:71; forming bar: E12                                                             |
| C30  | gap     | `src/worker/runtime.ts`:491 (no `gestures.stop()`; `setViewport` at :475 does stop) | none; the expected value is `26`:227's                                                                                |
| C32  | traced  | as C06                                                                              | `test/viewport/scales.test.ts`:55                                                                                     |
| C33  | gap     | `src/viewport/transform.ts`:182–192, :218–226                                       | none for a flat series; predicted: a one-tick window                                                                  |
| C34  | partial | `src/viewport/Viewport.ts`:59                                                       | `test/interaction/navigator.test.ts`:53; one and two bars: gap                                                        |
| C35  | traced  | `src/viewport/autoscale.ts`:120–125                                                 | `test/viewport/autoscale.test.ts`:147, :167, :184; `PriceScaleMenu.test.tsx`:305, :382, :395                          |
| C36  | traced  | `src/viewport/Viewport.ts`:46–51                                                    | `test/viewport/scenarios.test.ts`:38; `transform.test.ts` (imports both bounds)                                       |
| C37  | traced  | `src/viewport/Viewport.ts`:59                                                       | `test/interaction/momentum.test.ts`:66; `navigator.test.ts`:43                                                        |
| C38  | partial | `src/worker/runtime.ts`:491                                                         | `PriceScaleMenu.test.tsx`:409; the 20-in-one-frame burst: gap                                                         |
| C39  | partial | `src/host/input-router.ts`:44                                                       | `test/worker/host.test.ts`:274 (per-kind coalescing); mixed key + pointer: gap                                        |
| C41  | partial | `src/viewport/autoscale.ts`:48                                                      | `test/viewport/autoscale.test.ts`:60; `test/chaos/pressure.test.ts`:185                                               |
| C42  | traced  | `src/interaction/gestures.ts`:73–75                                                 | `test/interaction/gestures.test.ts`:151                                                                               |
| C43  | partial | `src/interaction/navigator.ts`:63                                                   | jumps are `scrollTo` cuts; the crosshair and countdown halves: blocked on #388                                        |

Paths in the table are under `CE/` unless they start with `apps/`. Blocked at READY: C09–C11, C17–C25, C31, C40 (on #387,
#388, #520 as each case says). The gap rows are where this plan adds coverage the unit suites do not have; E11-Q02 owns
their automation.

### 7.3 Regression subset (feeds E11-Q06)

The [R] cases: C01, C02, C03, C04, C05, C06, C07, C09, C10, C11, C13, C14, C15, C16, C19, C24, C26, C27, C33, C42.

## 8. What this plan references and does not contain

It references the story and ticket Gherkin, `26`, the E11 design specs and the merged code and tests by file and line.
It contains no code, no fixture data and no exchange payload. Performance thresholds, conformance audits and the
multi-pane suite are referenced to their owners (section 1).

## 9. Traceability

| Source           | Case(s)  | Source | Case(s)  | Source | Case(s) |
| ---------------- | -------- | ------ | -------- | ------ | ------- |
| US-CHART-006/1   | C01, C14 | S04.1  | C12, C01 | S06.1  | C17     |
| US-CHART-006/2   | C02      | S04.2  | C13      | S06.2  | C18     |
| US-CHART-006/3   | C03      | S04.3  | C14      | S06.3  | C19     |
| US-CHART-006/NFR | C04      | S04.4  | C04      | S06.4  | C22     |
| US-CHART-007/1   | C05      | S04.5  | C15      | S06.5  | C20     |
| US-CHART-007/2   | C06      | S04.6  | C16      | S06.6  | C21     |
| US-CHART-007/3   | C07, C35 | S05.1  | C05      | S07.1  | C09     |
| US-CHART-008/1   | C09      | S05.2  | C06, C27 | S07.2  | C10     |
| US-CHART-008/2   | C10      | S05.3  | C07      | S07.3  | C11     |
| US-CHART-008/3   | C11, C40 | S05.4  | C03      | S07.4  | C23     |
| US-CHART-008/NFR | C09, C11 | S05.5  | C02      | S07.5  | C24     |
|                  |          | S05.6  | C08      | S07.6  | C25     |

Ticket scope bullets: combinations C26–C32; boundaries C33–C37 (single and two bars C34, flat C33, non-positive C35,
spacing C36, first and last bar C37); failures C30, C38, C39, C41; reduced motion C14, C42, C43; charter section 3.11.
Ticket acceptance criteria: AC 1 by this table; AC 2 by section 2 and C26–C28; AC 3 by C33; AC 4 by the case form and
section 6; AC 5 by section 7.1, owned by E11-Q06.

## 10. Open questions

| Id   | Question                                                                                                                                                                                                                                                                                              | Owner                  |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| OQ-1 | Key ownership: today `←/→`, `Home`, `End` move the view (`26`:353); after #520 they move the data cursor (`26`:781). C04 and C40 are re-baselined then. Inside one frame, which applies first, a key or a pointer delta (C39)?                                                                        | E11-S13 #520           |
| OQ-2 | US-CHART-006/NFR names `Home` as reset; S04.4 and the merged keys use `Ctrl+Home` for reset and `Home` for the first bar. Amend the story or the keys?                                                                                                                                                | US-CHART-006 owner     |
| OQ-3 | The minimum price span for a flat series. The merged clamp gives one tick (`transform.ts`:221); the ticket forbids "a collapsed axis". What span (or tick count) is sane?                                                                                                                             | E11-D03 #309 / E11-S05 |
| OQ-4 | S07.3 bounds 30 bars in 3 s at 6 announcements; the D5 cadence (`26`:781) allows the lead announcement, one per 500 ms window and the trailing flush. Do the lead and trailing announcements count toward the 6? The US-CHART-008 NFR "≤ 2/s" is read as D5's parameters, not as a stand-alone count. | E06-D03 / E11-S07 #388 |
| OQ-5 | Should a scale change end an in-flight glide? `26`:227 lists no such termination and the merged runtime does not stop it (`runtime.ts`:491); C30 expects the glide to continue.                                                                                                                       | E11-S04 / E11-D06      |
| OQ-6 | US-CHART-014/3 says the table's focused row follows the crosshair; `26`:781 says pointer hover never moves an open table's row. Not written as a case.                                                                                                                                                | E11-S13 #520 / E11-Q05 |
| OQ-7 | `CE/README.md` BQ-17 (:123) and the S04 rows BQ-111, C-26, G-8 give the Playwright run to E11-Q01; the ticket gives the suite to E11-Q02. Correct the README rows in E11-Q02's PR.                                                                                                                    | E11-Q02 #444           |
| OQ-8 | Magnet across a gap: which side does the crosshair resolve to inside a gap?                                                                                                                                                                                                                           | E11-S07 #388 / E11-D02 |
| OQ-9 | The five named fixtures (section 6) do not exist; E11-Q02 adds them as seeded generators under `packages/fixtures/golden/` or beside the bench dataset.                                                                                                                                               | E11-Q02 #444           |
