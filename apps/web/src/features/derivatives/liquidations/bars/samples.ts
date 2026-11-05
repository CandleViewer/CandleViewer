// E24-S06 (#781): the declared samples the bars' stories and tests share. No recorded `liquidation_notional` capture is
// on `main` (#5341's route is unmerged), so the values are declared samples, never invented payloads: the bar grid is
// 1 h; the recorder began 09:14 UTC (D02 §6 `liq-partial`, D03 S54-45), so the 07:00 and 08:00 bars are before it, the
// 09:00 bar straddles it, 10:00 is a genuine zero and 11:00 holds the recorded sums (D02 §6's 2.9M / 0.8M figures).
// The server serves "0" for every bar without prints, including those BEFORE the recorder began: that is the trap the
// pane masks with coverage (`model.ts`). Sample data only: nothing in the app imports this file.
import type { LiqCoverage } from "../history";
import type { SidePoints } from "./model";

export const HOUR = 3_600_000;
export const NOW = Date.parse("2026-10-21T11:30:00Z");
export const FIRST = Date.parse("2026-10-21T09:14:00Z");
export const H = (hh: number, day = "2026-10-21"): number =>
  Date.parse(`${day}T${String(hh).padStart(2, "0")}:00:00Z`);

export const COVERAGE: LiqCoverage = {
  firstAvailableMs: FIRST,
  coveredFromMs: FIRST,
  coveredToMs: NOW,
  noCoverage: false,
};

/** As served: "0" for every bar without prints, before the recorder began included. */
export const SERVED_LONG: SidePoints = new Map([
  [H(7), "0"],
  [H(8), "0"],
  [H(9), "0"],
  [H(10), "0"],
  [H(11), "2900000.50"],
]);
export const SERVED_SHORT: SidePoints = new Map([
  [H(7), "0"],
  [H(8), "0"],
  [H(9), "0"],
  [H(10), "0"],
  [H(11), "800000.25"],
]);

/** A 1 h chart across a UTC day boundary (the ticket's sc. 2): bars 22:00 .. 02:00, all recorded. */
export const DAY_LONG: SidePoints = new Map([
  [H(22, "2026-10-20"), "125000.10"],
  [H(23, "2026-10-20"), "0"],
  [H(0), "41210.10"],
  [H(1), "9800000.00"],
  [H(2), "0"],
]);
export const DAY_SHORT: SidePoints = new Map([
  [H(22, "2026-10-20"), "0"],
  [H(23, "2026-10-20"), "0"],
  [H(0), "0"],
  [H(1), "1200000.75"],
  [H(2), "310.5"],
]);
export const DAY_COVERAGE: LiqCoverage = {
  firstAvailableMs: Date.parse("2026-10-01T00:00:00Z"),
  coveredFromMs: Date.parse("2026-10-01T00:00:00Z"),
  coveredToMs: NOW,
  noCoverage: false,
};
