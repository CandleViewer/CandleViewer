// E17-T04 S1 (23 6.1.1): the normative `heatmap_bucket_selection` unit test of the 16.4 matrix.
import { describe, expect, it } from "vitest";
import {
  HEATMAP_FALLBACK_BUCKET_MS,
  idealBucketMs,
  selectHeatmapBucket,
} from "../../../src/lib/ws/protocol/heatmapBucket";

const WINDOW = 900;
const pick = (cssWidth: number, dpr = 1, windowSeconds = WINDOW) =>
  selectHeatmapBucket({ windowSeconds, cssWidth, dpr });

describe("heatmap_bucket_selection", () => {
  // The 6.1.1 reference table at the shipped `window_seconds: 900`.
  it.each([
    ["4K, 100 % scale", 2380, 1, 1134, 1000],
    ["4K, 150 % scale", 1587, 1.5, 1134, 1000],
    ["2560 x 1440", 1587, 1, 1701, 1000],
    ["1920 x 1080", 1190, 1, 2269, 1000],
    ["MacBook 14 inch", 937, 2, 1441, 1000],
    ["half-width pane, 1920", 595, 1, 4538, 5000],
  ] as const)("%s: css px %i, dpr %f, ideal %i ms selects %i", (_name, css, dpr, ideal, picked) => {
    expect(Math.round(idealBucketMs(WINDOW, css, dpr))).toBe(ideal);
    expect(pick(css, dpr)).toBe(picked);
  });

  it.each([
    [27_000, 100],
    [10_800, 250],
    [5400, 500],
    [5399, 1000],
  ])("%i css px takes the smallest rung at or above ideal_ms: %i ms", (cssWidth, bucket) => {
    expect(pick(cssWidth)).toBe(bucket);
  });

  it("clamps the jump to 5 000 ms at 1 000 ms while ideal_ms <= 2 500, and takes it above", () => {
    expect(idealBucketMs(WINDOW, 1080, 1)).toBe(2500);
    expect(pick(1080)).toBe(1000);
    expect(pick(1079)).toBe(5000);
  });

  it("rule 1: an explicit user bucket is used verbatim, whatever the pane", () => {
    const input = { windowSeconds: WINDOW, cssWidth: 595, dpr: 1, userBucketMs: 250 } as const;
    expect(selectHeatmapBucket(input)).toBe(250);
  });

  it("re-derives on a DPR change (monitor move) and on a window_seconds change", () => {
    expect([pick(595, 1), pick(595, 2)]).toEqual([5000, 1000]);
    expect([pick(595, 1, 300), pick(1190, 1, 120)]).toEqual([1000, 500]);
  });

  it("a pane with no usable width takes 5 000 ms; an unusable window the 500 ms fallback", () => {
    for (const css of [0, -1, Number.NaN, Infinity]) expect(pick(css)).toBe(5000);
    expect([pick(1190, 1, 0), pick(1190, 1, Number.NaN)]).toEqual([
      HEATMAP_FALLBACK_BUCKET_MS,
      500,
    ]);
  });
});
