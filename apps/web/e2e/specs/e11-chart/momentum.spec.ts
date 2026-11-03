// E11-Q02 (#444). E11-Q01-C16 (a new pointer-down cancels the glide) and C14 (reduced motion: a
// release stops at once). Both compare the rested window with one read right after the release,
// so what is asserted is whether the view kept moving, never how far.
import { flick } from "../../support/engine/flick";
import { expect, test } from "../../support/engine/test";

test.describe("momentum (E11-Q01-C14, C16) @candidate", () => {
  test("a pointer-down during the glide stops it on that frame (C16)", async ({
    page,
    harness,
  }) => {
    await harness.open("btcusdt-1m-100k");
    const from = await harness.at("plot", 300, 200);
    await flick(page, from, { dx: 300, dy: 0 }, 150);
    // The glide is live: the window still moves after the release (else this test would pass vacuously).
    const atRelease = await harness.viewport();
    const gliding = await harness.viewportAfter(async () => undefined);
    expect(gliding.timeStart).not.toBe(atRelease.timeStart);
    await page.mouse.move(from.x, from.y);
    await page.mouse.down();
    const held = await harness.settle();
    await harness.frames(30);
    expect(await harness.viewport()).toEqual(held);
    await page.mouse.up();
  });

  test("under reduced motion a fast release does not coast (C14)", async ({ page, harness }) => {
    await harness.open("btcusdt-1m-100k", { motion: "reduce" });
    const v0 = await harness.settle();
    const from = await harness.at("plot", 300, 200);
    await flick(page, from, { dx: 300, dy: 0 }, 150);
    const rested = await harness.settle();
    // Exactly the dragged 300 px of bars, with no glide beyond it (half a bar of slack).
    expect((v0.timeStart - rested.timeStart) / 60e6).toBeCloseTo(300 / v0.barSpacing, 0);
  });
});
