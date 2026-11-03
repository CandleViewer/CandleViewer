// E11-Q02 (#444). Automates E11-Q01-C01 steps (1) and (2): a drag pans by the dragged pixels and
// stays; a fast release coasts past them and rests. Source of truth: the viewport the engine
// reported (`viewportChanged`), never an internal call (E11-Q01 plan C01 "Source").
import { expect, test } from "../../support/engine/test";
import { flick } from "../../support/engine/flick";

const BAR_US = 60e6;

test.describe("drag-to-pan (E11-Q01-C01) @candidate", () => {
  test("a steady 300 px drag moves the window by 300 px of bars and stays there", async ({
    page,
    harness,
  }) => {
    await harness.open("btcusdt-1m-100k");
    const before = await harness.settle();
    const box = await harness.box();
    const barSpacing = before.barSpacing;
    expect(barSpacing).toBeGreaterThan(0);

    // Rightward: the view opens on the latest bar, where a leftward drag would be clamped.
    await flick(page, { x: box.x + 300, y: box.y + 200 }, { dx: 300, dy: 0 }, 600, 14);
    const after = await harness.settle();

    const movedBars = (before.timeStart - after.timeStart) / BAR_US;
    expect(movedBars).toBeCloseTo(300 / barSpacing, 0); // within half a bar
    // "Stays there": no coast after a release that came after a still hold.
    await harness.frames(30);
    expect(await harness.viewport()).toEqual(after);
  });

  test("a fast release keeps moving past the drag and then rests", async ({ page, harness }) => {
    await harness.open("btcusdt-1m-100k");
    const before = await harness.settle();
    const box = await harness.box();

    // 300 px in 150 ms is 2 px/ms, above the plan's 1 px/ms; released while moving.
    await flick(page, { x: box.x + 300, y: box.y + 200 }, { dx: 300, dy: 0 }, 150);
    const rested = await harness.settle();

    const movedBars = (before.timeStart - rested.timeStart) / BAR_US;
    expect(movedBars).toBeGreaterThan(300 / before.barSpacing + 1); // coasted beyond the drag
    await harness.frames(30);
    expect(await harness.viewport()).toEqual(rested); // and came to rest, no bounce
  });
});
