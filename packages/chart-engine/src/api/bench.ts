// The real-engine bench entry (E11-T06): `dist/bench-engine.js`, loaded only by the engine bench
// page (`bench/engine/page/`). It is not `src/index.ts` (the frozen §8 surface) and no app imports
// it, so a production chart can never be opened in bench mode, and its frames never mark.
import { openChart } from "./chart.js";
import type { Chart, ChartOptions } from "./types.js";

export { STAGE_MARK_NAMES } from "../scene/stage-marks.js";

/** `createChart` in bench mode: a `frameStats` event per frame and 06 §4.3's stage marks. */
export function createBenchChart(opts: ChartOptions): Chart {
  return openChart(opts, true);
}
