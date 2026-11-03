// E11-Q02 (#444), acceptance criterion 2. Automates E11-Q01-C13 on a real page: the timestamp under the
// cursor holds within one pixel across wheel zoom in and back out. Asserted on the rendered
// viewport (`viewportChanged`), not an internal call.
// The plot's edges are engine layout the spec does not read: the anchor's fraction `f` of the window is
// solved from step 1 (start1 = start0 + f * (span0 - span1)), then every step must keep
// `start + f * span` within one pixel (span / chart width, the narrowest a pixel can be).
import { expect, test } from "../../support/engine/test";
import { CHART_SIZE } from "../../support/engine/harness";

test.describe("cursor-anchored zoom (E11-Q01-C13) @candidate", () => {
  test("the timestamp under the cursor stays put through zoom in and back out", async ({
    page,
    harness,
  }) => {
    await harness.open("btcusdt-1m-100k");
    const v0 = await harness.settle();
    const box = await harness.box();
    await page.mouse.move(box.x + 450, box.y + 200);

    // Three notches in (deltaY < 0 grows barSpacing: wheel.ts exp(-px * 0.002)), one viewport each.
    const steps = [v0];
    for (let i = 0; i < 3; i += 1) {
      await harness.viewportAfter(() => page.mouse.wheel(0, -120));
      steps.push(await harness.settle());
    }
    const v1 = steps[1]!;
    expect(v1.barSpacing).toBeGreaterThan(v0.barSpacing); // it zoomed in
    const span = (v: { timeStart: number; timeEnd: number }): number => v.timeEnd - v.timeStart;
    const f = (v1.timeStart - v0.timeStart) / (span(v0) - span(v1));
    const anchor = v0.timeStart + f * span(v0);

    // ...and three notches back out to the start.
    for (let i = 0; i < 3; i += 1) {
      await harness.viewportAfter(() => page.mouse.wheel(0, 120));
      steps.push(await harness.settle());
    }
    for (const v of steps) {
      const onePx = span(v) / CHART_SIZE.width;
      expect(Math.abs(v.timeStart + f * span(v) - anchor)).toBeLessThanOrEqual(onePx);
    }
    const last = steps[steps.length - 1]!;
    expect(last.barSpacing).toBeCloseTo(v0.barSpacing, 3); // the symmetric sweep returns
  });
});
