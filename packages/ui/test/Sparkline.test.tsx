// @vitest-environment jsdom
import { describe, it } from "vitest";
import { expect, within } from "storybook/test";
import { Sparkline } from "../src/components/index.js";
import {
  SPARKLINE_MAX_POINTS,
  sparklineDomain,
  sparklinePoints,
  sparklineSeries,
  sparklineSummary,
} from "../src/components/Sparkline.js";
import { mount } from "./theme/mount.js";

const ramp = (n: number, from: number, to: number): number[] =>
  Array.from({ length: n }, (_, i) => from + ((to - from) * i) / Math.max(1, n - 1));

describe("Sparkline (CMP-024)", () => {
  it("is a static img named by its trend summary; the line is hidden and nothing is focusable", async () => {
    const host = await mount(<Sparkline data={ramp(20, 100, 103.2)} />);
    const img = within(host).getByRole("img", { name: "up 3.2% over 20 bars" });
    expect(img).toHaveAttribute("data-cmp", "CMP-024");
    expect(img).toHaveAttribute("data-trend", "up");
    expect(img).toHaveAttribute("focusable", "false");
    expect(img).not.toHaveAttribute("tabindex");
    expect(host.querySelector("polyline")).toHaveAttribute("aria-hidden", "true");
    expect(host.querySelector("[aria-live], [role='status']")).toBeNull();
  });

  it.each([
    ["empty", [], "no data", "flat"],
    ["a single point", [42], "no trend over 1 bar", "flat"],
    ["a flat series", [50, 50, 50, 50], "unchanged over 4 bars", "flat"],
    ["a change that rounds to 0.0%", [100, 100.04], "unchanged over 2 bars", "flat"],
    ["an up series", ramp(12, 100, 103.4), "up 3.4% over 12 bars", "up"],
    ["a down series", ramp(20, 200, 193.6), "down 3.2% over 20 bars", "down"],
    ["a negative first value", [-10, -5], "up 50.0% over 2 bars", "up"],
    ["a zero first value", [0, 3], "up over 2 bars", "up"],
  ])("names %s: %s", (_label, data, name, trend) => {
    expect(sparklineSummary(data)).toEqual({ name, trend });
  });

  it("skips non-finite values and keeps the latest 200 points", () => {
    expect(sparklineSeries([1, Number.NaN, 2, Number.POSITIVE_INFINITY, 3])).toEqual([1, 2, 3]);
    const long = ramp(250, 0, 249);
    const kept = sparklineSeries(long);
    expect(kept).toHaveLength(SPARKLINE_MAX_POINTS);
    expect(kept[0]).toBe(50);
    expect(sparklineSummary(long).name).toMatch(/over 200 bars$/);
  });

  it("E22: a near-flat price series is widened to ±0.5 % of its first value", () => {
    const near = (d: { lo: number; hi: number }, lo: number, hi: number): void => {
      expect(d.lo).toBeCloseTo(lo, 9);
      expect(d.hi).toBeCloseTo(hi, 9);
    };
    near(sparklineDomain([100, 100.1, 100.05]), 99.55, 100.55);
    // A trend wider than the floor keeps its own min..max.
    expect(sparklineDomain([100, 104])).toEqual({ lo: 100, hi: 104 });
    // Deep Stats sets its own ratio per data kind; 0 turns the floor off.
    expect(sparklineDomain([10, 10.1], 0)).toEqual({ lo: 10, hi: 10.1 });
    near(sparklineDomain([10, 10.1], 0.1), 9.05, 11.05);
    expect(sparklineDomain([])).toEqual({ lo: 0, hi: 0 });
  });

  it("E22: the near-flat line stays in the middle band instead of spanning the margins", () => {
    const ys = sparklinePoints([100, 100.1, 100], 64, 16)
      .split(" ")
      .map((p) => Number(p.split(",")[1]));
    // Unfloored, 100..100.1 would span the full 2.4–13.6 band; floored it moves by about a tenth of it.
    expect(Math.max(...ys) - Math.min(...ys)).toBeLessThan(1.2);
    const free = sparklinePoints([100, 100.1, 100], 64, 16, 0)
      .split(" ")
      .map((p) => Number(p.split(",")[1]));
    expect(Math.max(...free) - Math.min(...free)).toBeCloseTo(11.2, 5);
  });

  it("draws the full width inside the 0.15–0.85 height margins", () => {
    expect(sparklinePoints([1, 3, 2], 64, 16, 0)).toBe("0,13.6 32,2.4 64,8");
    expect(sparklinePoints([], 64, 16)).toBe("");
    // One point: a level stroke at mid-height across the box.
    expect(sparklinePoints([7], 64, 16)).toBe("0,8 64,8");
    // A zero series has no span and no floor: a level line.
    expect(sparklinePoints([0, 0], 64, 16)).toBe("0,8 64,8");
  });

  it("an empty series draws no line but keeps its name", async () => {
    const host = await mount(<Sparkline data={[]} />);
    expect(within(host).getByRole("img", { name: "no data" })).toBeTruthy();
    expect(host.querySelector("polyline")).toBeNull();
  });

  it("takes the host's box: viewBox follows width and height, the stroke never scales", async () => {
    const host = await mount(<Sparkline data={[1, 2]} width={256} height={64} />);
    const svg = within(host).getByRole("img");
    expect(svg).toHaveAttribute("width", "256");
    expect(svg).toHaveAttribute("viewBox", "0 0 256 64");
    expect(svg).toHaveAttribute("preserveAspectRatio", "none");
    const line = host.querySelector("polyline");
    expect(line).toHaveAttribute("stroke-width", "1.5");
    expect(line).toHaveAttribute("vector-effect", "non-scaling-stroke");
  });

  it("colorBySign marks the trend for the stroke tokens; off by default", async () => {
    const off = await mount(<Sparkline data={[1, 2]} />);
    expect(off.querySelector("svg")).not.toHaveAttribute("data-color-by-sign");
    for (const [data, trend] of [
      [[1, 2], "up"],
      [[2, 1], "down"],
      [[1, 1], "flat"],
    ] as const) {
      const host = await mount(<Sparkline data={data} colorBySign />);
      const svg = host.querySelector("svg");
      expect(svg).toHaveAttribute("data-color-by-sign", "");
      expect(svg).toHaveAttribute("data-trend", trend);
    }
  });

  it("renders 200 points as one 200-vertex polyline", async () => {
    const host = await mount(<Sparkline data={ramp(200, 100, 110)} />);
    const points = host.querySelector("polyline")?.getAttribute("points")?.split(" ") ?? [];
    expect(points).toHaveLength(200);
    expect(within(host).getByRole("img")).toHaveAccessibleName("up 10.0% over 200 bars");
  });
});
