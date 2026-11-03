// E11-Q02 (#444). Multi-pane (E11-S09, #446, open). Only what the merged engine supports is real: two
// stacked panes mount and render. Splitters, collapse and ratio persistence are #446's: fixme rows, and
// #446 is a blocker of the closing PR, which leaves no fixme.
import { expect, test } from "../../support/engine/test";

test.describe("multi-pane (E11-S09) @candidate", () => {
  test("a two-pane stack (0.7 / 0.3) loads, renders frames and raises no engine error", async ({
    harness,
  }) => {
    await harness.open("btcusdt-1m-100k", { panes: 2 });
    const v = await harness.settle();
    expect(v.barSpacing).toBeGreaterThan(0);
    expect(await harness.count("error")).toBe(0);
  });

  for (const title of [
    "dragging a splitter changes the pane ratio and the heights follow",
    "a focused splitter resizes by the specified keyboard step and announces the value (AC6)",
    "the keyboard end state equals the dragged end state (AC6)",
    "a pane collapses and restores to its previous ratio",
    "the height ratios persist across a reload",
  ]) {
    test.fixme(`${title} (pending #446)`, async () => undefined);
  }
});
