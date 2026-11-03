// E11-Q02 (#444). Automates E11-Q01-C01 step 3 and C13's gutter clause, per the merged E11-D02 (PG04,
// PG05; 26 line 353): a plain wheel over the plot or the time axis zooms time by exp(-px * 0.002) per
// notch, a plain wheel over the price axis scales that axis (and locks it), and Shift+wheel pans.
// Ctrl+wheel is a trackpad pinch, routed as the plain wheel and default-prevented (the engine's
// ruling, E11-S04 README BQ-100, C-23; the design was amended to match, #5645): the ticket's "Ctrl+wheel
// price zoom" yields to it. `+` and `-` are the keyboard path (nav-only/navigation.spec.ts).
import { expect, test } from "../../support/engine/test";

const NOTCH = 120; // px per notch
const FACTOR = Math.exp(NOTCH * 0.002);

test.describe("wheel (E11-Q01-C01, C13; PG04, PG05) @candidate", () => {
  for (const [region, dy] of [
    ["plot", 200],
    ["time", 12],
  ] as const) {
    test(`a wheel over the ${region} zooms time by exp(-px * 0.002) per notch`, async ({
      page,
      harness,
    }) => {
      await harness.open("btcusdt-1m-100k");
      const v0 = await harness.settle();
      const p = await harness.at(region, 400, dy);
      await page.mouse.move(p.x, p.y);
      await harness.viewportAfter(() => page.mouse.wheel(0, -NOTCH));
      expect((await harness.settle()).barSpacing / v0.barSpacing).toBeCloseTo(FACTOR, 2);
    });
  }

  test("Shift+wheel pans: the window moves and its span holds", async ({ page, harness }) => {
    await harness.open("btcusdt-1m-100k");
    const v0 = await harness.settle();
    const p = await harness.at("plot", 400, 200);
    await page.mouse.move(p.x, p.y);
    await page.keyboard.down("Shift");
    await harness.viewportAfter(() => page.mouse.wheel(0, NOTCH));
    await page.keyboard.up("Shift");
    const v1 = await harness.settle();
    expect(v1.timeStart).not.toBe(v0.timeStart);
    expect(v1.barSpacing).toBeCloseTo(v0.barSpacing, 6);
  });

  test("a wheel over the price gutter zooms no time and locks the price scale", async ({
    page,
    harness,
  }) => {
    await harness.open("btcusdt-1m-100k");
    const v0 = await harness.settle();
    const p = await harness.at("price", 30, 200);
    await page.mouse.move(p.x, p.y);
    await page.mouse.wheel(0, -NOTCH);
    await harness.frames(10);
    expect(await harness.settle()).toEqual(v0);
    await expect(harness.chart.getByRole("button", { name: "Price scale locked" })).toBeVisible();
  });

  // The input router sends every wheel without Shift (and without a dominant horizontal delta) down
  // the plain path, so Ctrl and Alt add no binding of their own; the router prevents the page's default
  // (a browser zoom or scroll) on all of them (input-router.ts onWheel).
  for (const key of ["Control", "Alt"] as const) {
    test(`${key}+wheel is the plain wheel: zooms time at the cursor and is default-prevented`, async ({
      page,
      harness,
    }) => {
      await harness.open("btcusdt-1m-100k");
      const v0 = await harness.settle();
      const p = await harness.at("plot", 400, 200);
      await page.mouse.move(p.x, p.y);
      await page.evaluate(() => {
        window.addEventListener(
          "wheel",
          (e) => ((window as { __wheelPrevented?: boolean }).__wheelPrevented = e.defaultPrevented),
          {
            passive: true,
          },
        );
      });
      await page.keyboard.down(key);
      await harness.viewportAfter(() => page.mouse.wheel(0, -NOTCH));
      await page.keyboard.up(key);
      expect((await harness.settle()).barSpacing / v0.barSpacing).toBeCloseTo(FACTOR, 2);
      expect(
        await page.evaluate(() => (window as { __wheelPrevented?: boolean }).__wheelPrevented),
      ).toBe(true);
    });
  }
});
