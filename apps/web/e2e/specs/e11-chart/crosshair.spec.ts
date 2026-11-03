// E11-Q02 (#444). Crosshair, readout, countdown and magnet (E11-S07, #388, open). The engine emits no
// public `crosshair` event today (`ChartEvents.crosshair` is typed, never emitted), so nothing here
// can be asserted on a public event yet: every row is a fixme naming #388 and its E11-Q01 case id.
// #388 (and #5480 for the keyboard crosshair) is a blocker of the closing PR, which leaves no fixme.
import { test } from "../../support/engine/test";

const PENDING = [
  "pointer movement emits crosshair events, edge-triggered per bar (C24)",
  "the readout shows O, H, L, C and volume for the hovered fixture bar (C09)",
  "the countdown shows seconds to close and warns in the final 10 s, on the page clock (C10)",
  "magnet strong snaps to the high and labels it (C25)",
  "the magnet snaps across the btcusdt-1m-gap hole (C31)",
  "the tooltip is aria-hidden and its values are in the mirror (C23)",
  "keyboard crosshair steps bar by bar (C11; also needs the data cursor, #5480)",
] as const;

test.describe("crosshair (E11-S07) @candidate", () => {
  for (const title of PENDING) test.fixme(`${title} (pending #388)`, async () => undefined);
});
