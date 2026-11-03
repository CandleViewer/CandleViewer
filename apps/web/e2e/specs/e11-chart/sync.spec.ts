// E11-Q02 (#444, AC3). Sync groups (CMP-196, E11-S09, #446, open): no `engine.sync.propagations_per_frame`
// counter and no multi-chart harness exist yet, so every row is a fixme naming #446. #446, #388, #403
// (SCR-049's grid; the 4-chart row is the engine property) and #5480 are blockers of the closing PR,
// which leaves no fixme. Not written: the same-frame and once-per-frame checks (AC3), because `frame`
// events arrive at 1 per second and those need a per-frame signal from #446 (BQ-09, to file there).
import { test } from "../../support/engine/test";

const PENDING = [
  "time-range sync across 2, 3 and 4 panes",
  "crosshair sync across 2 to 4 panes",
  "CMP-196 levels sync across panes; the price scale itself is never synced",
  "time-range and crosshair sync across 2 chart instances",
  "a subscriber applying a sync does not re-publish: no echo (AC3)",
  "four charts share one worker (SCR-049's engine property; grid UI is #403)",
] as const;

test.describe("sync groups (CMP-196) @candidate", () => {
  for (const title of PENDING) test.fixme(`${title} (pending #446)`, async () => undefined);
});
