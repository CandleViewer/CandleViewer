// E11-Q02 (#444, AC1). The keyboard twins of the pointer gestures (E11-Q01-C04; E11-D07 section 8; the
// keys are navigator.ts's, DE-06's plot stop): PG04 `+/-` zoom 1.1 (Shift 1.25), PG10 Ctrl+Home resets,
// Home and End jump, and the arrows pan a bar (Shift: ten) until E11-S13's data cursor takes PG01.
// No pointer event may fire (support/engine/nav-guard.ts); the chart is focused with `focus()`, because
// its Tab stop is E11-S13's (see pending.spec.ts).
import { buildFixture } from "../../../support/engine/fixtures";
import { test, expect } from "../../../support/engine/nav-guard";

const BAR_US = 60e6;
const bars = buildFixture("btcusdt-1m-100k");
const lastBar = bars.time[bars.time.length - 1] as number;

test.describe("keyboard navigation (E11-Q01-C04; PG01, PG04, PG10) @candidate", () => {
  test.beforeEach(async ({ harness }) => {
    await harness.open("btcusdt-1m-100k");
    await harness.settle();
    await harness.focusChart();
  });

  for (const [key, bars_] of [
    ["ArrowLeft", -1],
    ["ArrowRight", 1],
    ["Shift+ArrowLeft", -10],
  ] as const) {
    test(`${key} pans ${Math.abs(bars_)} bar(s)`, async ({ page, harness }) => {
      // Start from one pan left so that a rightward key is not clamped at the latest bar.
      await harness.viewportAfter(() => page.keyboard.press("Shift+ArrowLeft"));
      const v0 = await harness.settle();
      await harness.viewportAfter(() => page.keyboard.press(key));
      const v1 = await harness.settle();
      expect((v1.timeStart - v0.timeStart) / BAR_US).toBeCloseTo(bars_, 2);
      expect(v1.barSpacing).toBeCloseTo(v0.barSpacing, 6);
    });
  }

  test("Home shows the first bar at the left edge and End the latest bar", async ({
    page,
    harness,
  }) => {
    await harness.viewportAfter(() => page.keyboard.press("Home"));
    expect(Math.abs((await harness.settle()).timeStart - (bars.time[0] as number))).toBeLessThan(
      BAR_US,
    );
    await harness.viewportAfter(() => page.keyboard.press("End"));
    const end = await harness.settle();
    expect((end.timeEnd - lastBar) / BAR_US).toBeGreaterThan(0); // the latest bar is in view
  });

  for (const [key, factor] of [
    ["Equal", 1.1],
    ["Minus", 1 / 1.1],
    ["Shift+Equal", 1.25],
  ] as const) {
    test(`${key} zooms time by ${factor.toFixed(3)}`, async ({ page, harness }) => {
      const v0 = await harness.settle();
      await harness.viewportAfter(() => page.keyboard.press(key));
      expect((await harness.settle()).barSpacing / v0.barSpacing).toBeCloseTo(factor, 3);
    });
  }

  test("Ctrl+Home restores the default spacing and the latest bar", async ({ page, harness }) => {
    await harness.viewportAfter(() => page.keyboard.press("Equal"));
    await harness.settle();
    await harness.viewportAfter(() => page.keyboard.press("Control+Home"));
    const v = await harness.settle();
    expect(v.barSpacing).toBeCloseTo(6, 6); // viewport/Viewport.ts DEFAULT_BAR_SPACING
    expect(v.timeEnd).toBeGreaterThan(lastBar);
  });
});
