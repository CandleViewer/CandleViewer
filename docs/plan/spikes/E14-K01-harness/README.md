# E14-K01 harness (throwaway)

Spike harness for E14-K01 (#356): keyboard-only drawing creation and the canvas-surrogate accessibility pattern.
It is **throwaway** (the E11-K01 precedent): nothing here is product code, nothing imports it, and it is not
promoted without a `feat/` ticket (C-4.5). It imports nothing from `packages/chart-engine` or `apps/web`. The
findings are in [`../E14-K01.md`](../E14-K01.md).

## What it is, and what it stands in for

The shipped engine has no data cursor and `getVisibleWindow()` / `getFocusedUnit()` return `null` (E11-S13 owns them),
and there is no drawings layer yet (E14-T03). So this is a **stand-in** built on the event shapes only
(BQ-04, default option b):

- a **synthetic scene**: a seeded fixture of 500 drawings (50 and 200 are prefixes of it), the tool mix of the
  registry (one-, two- and three-anchor tools and polylines), spread over about 1,000 bars, with a 100-bar-wide viewport;
- a **synthetic cursor and viewport** that emit the `crosshair` and `viewportChanged` shapes;
- a **synthetic main-thread load**: a 100k-bar series autoscaled and redrawn on a 2D canvas each frame (not the engine);
- the **three strategies** over the same scene (BQ-06): `a` one surrogate per drawing (all in one roving group),
  `b` one `application` host with a grid summary and `aria-activedescendant`, `c` surrogates for the visible, selected
  and focused drawings only, `aria-setsize` the full count;
- a **keyboard drawing flow** with D02's keys, a **live-region announcer** with the BQ rate policy, and probes.

Numbers transfer in kind. Anything that needs the real engine is re-read when E11-S13 and E14-T03 ship.

## Files

| File                       | Role                                                                                                                              |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `run.mjs`                  | The Node driver: serves this folder on `127.0.0.1`, runs the matrix, the scripts and the probes, writes `../E14-K01-results.json` |
| `page.html`, `harness.mjs` | The page: scene, strategies, keyboard flow, announcer, probes                                                                     |
| `fixture.mjs`              | The seeded RNG, the fixture and the harness's own simplified name grammar (not D07's template engine)                             |
| `../E14-K01-results.json`  | Generated. Every number in the finding comes from it; its `measures` block holds the ready-to-paste strings                       |

## What is measured, and how

| Item                                                           | How                                                                                                                                                                                                                    | Evidence class                                                                                   |
| -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| DOM nodes                                                      | `querySelectorAll('*')` under the mirror root                                                                                                                                                                          | exact                                                                                            |
| AT-tree build                                                  | Chromium's tree through `Accessibility.enable` + `getFullAXTree` after a rebuild and two frames, n builds, p50 / p95 / max                                                                                             | a **proxy** for NVDA / VoiceOver; the equivalence is unverified                                  |
| Drag cost                                                      | `performance.mark` / `measure` around the reconcile of a synthetic drag with edge-pan (every surrogate re-positioned each frame), under the redraw load, with a tree attached (the conservative condition) and without | headless Chromium on a contended host: a gate met is conservative, a gate missed is inconclusive |
| Window cap                                                     | a capped window of K drawings in the 500-case, K swept; largest K under both gates                                                                                                                                     | as above                                                                                         |
| Reachability, Tab order, focus kept across pan / zoom / resize | real key presses through Playwright, focus read after each key                                                                                                                                                         | exact                                                                                            |
| Keyboard script                                                | create, nudge (object and anchor), delete, undo, one-, three- and N-anchor flows, cancel ladder, locked refusal; asserts zero pointer events and the `aria-label` strings                                              | exact                                                                                            |
| Sink                                                           | markup-like labels; asserts text-only DOM, no element from a label, no handler fired; scan for HTML setters                                                                                                            | exact                                                                                            |
| Live regions                                                   | a 60 s session (real time) through the announcer; writes per second, dropped values                                                                                                                                    | exact for the harness policy                                                                     |
| 24 px target, obscured fraction                                | rectangle geometry                                                                                                                                                                                                     | geometry only                                                                                    |

**Not measurable here:** NVDA and VoiceOver latency and "announced by NVDA" (no readers on this host), recorded
videos, equality of a surrogate rectangle with the engine's pickable bounds (the stand-in builds both from the same
bounds), the real engine's frame time.

## Run it

Run from `apps/web` (it resolves `@playwright/test` from there), one process at a time, not while another heavy job
holds a slot. No network, no new dependency.

```sh
node ../../docs/plan/spikes/E14-K01-harness/run.mjs
```

Options: `--seed 356` (the default; ticket number), `--at-n 40` AT-tree builds per cell, `--frames 400` drag frames per
cell (after 30 warm-up frames), `--session-s 60`, `--out <dir>`, `--smoke` (tiny n, writes to `$TMPDIR`),
`--chromium <path>` when the browser build on the host differs from the one Playwright pins. A full run is about
ten minutes.

The decision rule, the gates (AT build under 100 ms, drag under 2 ms, both at the 500 case, on p95) and the tie-break
are constants at the top of `run.mjs`, written before the run. The tie-break (among survivors prefer the strategy that
gives every drawing its own named node) is accessibility, not cost, as BQ-06 is ruled; it is one line to change.

## Known simplifications

- The window query is a linear scan; the real query is the engine's (E11-S13). Its cost is reported separately (`query`).
- Existing surrogates are not re-ordered in the DOM while a drawing moves (re-ordering would move the focused node);
  `aria-posinset` is updated instead. The finding must say that a reorder never moves focus.
- The closing key of the polyline (`Shift+Enter`) and the hotkeys `Alt+C` and `Alt+P` are harness-only and are not proposals.
