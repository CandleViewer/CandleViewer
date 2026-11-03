/**
 * E42-S08 (#1137): the goldens' charts, frozen. `frozen/` holds B01 `order` (v8, a parallel root),
 * B04 `oco` and B18 `kill_switch`, derived from the committed charts on 2026-11-02 by a script (no
 * server serves an export yet, #2701), structure only: without the six CV policy keys (an export
 * drops them) and without the actions, context, tags and entries the inspector never reads. The
 * golden lists, the layout's and the drawing's pins and the e2e's world read these, so a routine
 * bump of a committed chart (a version, an arm, the lock's hash) moves none of them; the loops over
 * all twenty charts still read the live files.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

export type FrozenChart = "B01.order" | "B04.oco" | "B18.kill_switch";

const FROZEN = resolve(import.meta.dirname, "frozen");

/** A frozen chart as `exportStatechart`'s `stately` serves it. */
export function frozenChart(name: FrozenChart): unknown {
  const chart: unknown = JSON.parse(readFileSync(resolve(FROZEN, `${name}.json`), "utf8"));
  return chart;
}
