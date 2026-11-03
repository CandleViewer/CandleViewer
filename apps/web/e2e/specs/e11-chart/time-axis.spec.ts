// E11-Q02 (#444). The time axis and the plot's double-click (the time-axis analogue of E11-Q01-C03
// step 4; ticket "time-axis drag, double-click reset"). A time-axis drag changes barSpacing by exp(dx * 0.005)
// about the plot's right edge (wheel.ts); a double-click restores the default spacing (6 px/bar).
import { buildFixture } from "../../support/engine/fixtures";
import { flick } from "../../support/engine/flick";
import { expect, test } from "../../support/engine/test";

const DEFAULT_SPACING = 6; // viewport/Viewport.ts DEFAULT_BAR_SPACING

test.describe("time axis and double-click (analogue of C03 for the time axis, E11-S04) @candidate", () => {
  test("dragging the time axis right widens the bars by exp(100 * 0.005)", async ({
    page,
    harness,
  }) => {
    await harness.open("btcusdt-1m-100k");
    const v0 = await harness.settle();
    const from = await harness.at("time", 300, 12);
    await flick(page, from, { dx: 100, dy: 0 }, 400, 4);
    const v1 = await harness.settle();
    expect(v1.barSpacing / v0.barSpacing).toBeCloseTo(Math.exp(0.5), 2);
  });

  test("double-click on the time axis restores the default spacing", async ({ page, harness }) => {
    await harness.open("btcusdt-1m-100k");
    const p = await harness.at("time", 300, 12);
    await harness.viewportAfter(() => page.mouse.dblclick(p.x, p.y));
    expect((await harness.settle()).barSpacing).toBeCloseTo(DEFAULT_SPACING, 6);
  });

  test("double-click on the plot resets spacing and returns to the latest bar", async ({
    page,
    harness,
  }) => {
    await harness.open("btcusdt-1m-100k");
    const p = await harness.at("plot", 400, 200);
    await page.mouse.move(p.x, p.y);
    await harness.viewportAfter(() => page.mouse.wheel(0, -360)); // away from the default
    await harness.settle();
    await harness.viewportAfter(() => page.mouse.dblclick(p.x, p.y));
    const v = await harness.settle();
    const bars = buildFixture("btcusdt-1m-100k");
    expect(v.barSpacing).toBeCloseTo(DEFAULT_SPACING, 6);
    expect(v.timeEnd).toBeGreaterThan(bars.time[bars.time.length - 1] as number); // the last bar is in view
  });
});
