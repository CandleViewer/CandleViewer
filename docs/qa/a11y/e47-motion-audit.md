# E47-Q05 motion/flash audit: method and assumptions

Ticket: #1357 (E47-Q05). Standard: `docs/plan/05-accessibility-standard.md` s7 and s9 item 5.
Decisions: `tools/a11y/motion_audit.py`. Collectors: `apps/web/e2e/a11y/motion-audit.collect.ts`
(frames) and `motion-profile.collect.ts` (reduced-motion work). Counting rule: `e47-flash-calibration.md`.
Status: slice 1 and 2 (decisions, collectors, derivation method). CI wiring and the overhead
benchmarks are later slices; the figures below are PROPOSED until QA signs the derivation.

## 1. Flash audit

- Regions are declared rectangles (D08 FR-2, 341 x 256 CSS px). A region that spans the viewport's
  width or height, or half its area, is `A11Y-INFRA`: averaging over a static screen hides a flash.
- A capture shorter than 1 s is `A11Y-INFRA`. The report carries the measured flashes/s per region.
- Budget per surface: at most 2 per 1 s window (D08 FR-3, FR-6); G005's 3 stays the hard gate.
- Unbuilt surfaces are `pending <ticket>` rows (register MX-10, MX-11, MX-12, MX-14).

## 2. Reduced motion removes work

`motion-profile.collect.ts` runs one scripted interaction (10 cycles of nav-rail collapse and expand,
the Notifications panel and a shell toast) on the real shell under no-preference and under reduce.
The `reduce` check fails if any animation is still running, or if script, style + layout or rAF work
exceeds `REDUCE_WORK_FRACTION` of the motion-safe run, so forcing opacity constant while the loop
runs fails. `paint_ms` is CDP `LayoutDuration + RecalcStyleDuration`; GPU time is not exposed by
`Performance.getMetrics`, so GPU work is not yet measured (a later slice names the trace source).

## 3. Deriving `REDUCE_WORK_FRACTION` (PROPOSED, BQ-05)

Run the profile collector three times, pairing each run's safe and reduced profile, and feed
`python -m tools.a11y.motion_audit derive runs.json`, where the file is
`{"runs": [{"safe": P, "reduced": P}, x3]}` and each `P` is `{"running_animations", "script_ms",
"paint_ms", "raf_callbacks"}` (the collector's `motion-profile.json` is one such pair). Per work key, with `r = reduced / safe`:

- lower bound `mean(r) + 2 * stdev(r)`: the fraction must admit a genuine reduce run;
- upper bound `1 - 3 * cv(safe)`: a run that removes nothing (ratio 1) must still fail through the
  motion-safe run's own noise.

`mean + 2 * stdev` at n = 3 is a weak bound: a t-based 95 % multiplier for 2 degrees of freedom would
be about 4.3. QA decides the multiplier when it signs the PROPOSED fraction.

The proposal is the largest lower bound rounded up to 0.05. If it exceeds the smallest upper bound
the scene is too noisy to separate work from noise and the derivation is `A11Y-INFRA`. The code's
0.5 is a placeholder until the three CI runs are committed beside this file; the unit tests use
fixtures, not measurements.

## 4. A-rows

| Row | Source                                                               | Statement                                                      | Resolution                                                                                                                                     |
| --- | -------------------------------------------------------------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| A-1 | `06` :25 says frame time "<=16.6 ms"; C-14.2 says "<16 ms p95 frame" | 16.6 ms is 1000/60 truncated; the two figures differ by 0.6 ms | The audit and benchmarks assert C-14.2's 16 ms (the Constitution wins, C-16.5), the stricter value. `06`'s 16.6 is left to its owner to align. |
