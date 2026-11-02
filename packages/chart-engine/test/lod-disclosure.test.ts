// E12-S09 BQ-08 (part of AC4; E12-D06 §6.1 / §13): the L2 aggregation words. N is the bars per
// device column rounded half up; the words carry the level, so the state is never colour-only.
// The chip, its announcements and the mirror row are PR 2's (the app, E11-S13).
import { describe, expect, it } from "vitest";
import { lodDisclosure } from "../src/lod-disclosure.js";

const l2 = (barsPerColumn: number, aggregated = barsPerColumn > 1) => ({
  candles: 2,
  barsPerColumn,
  aggregated,
});

describe("lodDisclosure", () => {
  it("says nothing at L0 and L1 (nothing is aggregated)", () => {
    expect(lodDisclosure({ candles: 0, barsPerColumn: 0.1, aggregated: false })).toBeNull();
    expect(lodDisclosure({ candles: 1, barsPerColumn: 0.4, aggregated: false })).toBeNull();
  });

  it("L2: '1 column = N bars', N rounded half up (s = 0.6 at DPR 1 reads 2)", () => {
    expect(lodDisclosure(l2(1 / 0.6))).toEqual({
      chip: "Zoomed out · 1 column = 2 bars",
      mirror: "2 bars per column",
    });
    expect(lodDisclosure(l2(2.5))?.chip).toBe("Zoomed out · 1 column = 3 bars");
    expect(lodDisclosure(l2(20))?.mirror).toBe("20 bars per column");
  });

  it("the N = 1 boundary: singular while aggregated rounds to 1", () => {
    expect(lodDisclosure(l2(1.2))).toEqual({
      chip: "Zoomed out · 1 column = 1 bar",
      mirror: "1 bar per column",
    });
  });

  it("L2 with nothing merged, or a non-finite ratio: the PROPOSED 'high–low only'", () => {
    const hl = { chip: "Zoomed out · high–low only", mirror: "high–low only" };
    expect(lodDisclosure(l2(0.8))).toEqual(hl);
    expect(lodDisclosure(l2(Number.NaN, true))).toEqual(hl);
    expect(lodDisclosure(l2(0.2, true))).toEqual(hl);
  });
});
