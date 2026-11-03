// E11-Q02 (#444). Pinch-zoom via synthesised touch ("pinch-zoom via synthesised touch" in the
// ticket; E11-Q01 C04's pointer rows). gestures.ts zooms by d1/d0 per finger move about the
// midpoint, so the product over a pinch is the final over the initial finger distance.
import { pinch } from "../../support/engine/pinch";
import { expect, test } from "../../support/engine/test";

test.describe("pinch (E11-Q01-C01) @candidate", () => {
  test("spreading two fingers from 100 to 200 px doubles the bar spacing", async ({
    page,
    harness,
  }) => {
    await harness.open("btcusdt-1m-100k");
    const v0 = await harness.settle();
    const mid = await harness.at("plot", 400, 200);
    await harness.viewportAfter(() => pinch(page, mid, 100, 200, 12));
    const v1 = await harness.settle();
    expect(v1.barSpacing / v0.barSpacing).toBeCloseTo(2, 1);
  });
});
