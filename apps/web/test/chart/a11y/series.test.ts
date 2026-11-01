import { describe, expect, it } from "vitest";
import {
  barFields,
  cvdAt,
  cvdPrefix,
  imbalanceOf,
  levelCount,
  levelsOf,
} from "../../../src/chart/a11y/series";
import { TSV_ROW_CAP, buildTsv } from "../../../src/chart/a11y/tsv";
import { makeSeries } from "./fixture";

describe("series read model (the chart's own arrays, no fetch)", () => {
  const s = makeSeries({ bars: 4 });

  it("reads a bar as exact decimal strings, delta from its footprint", () => {
    expect(barFields(s, 0)).toEqual({
      timeUs: s.candles.time[0],
      open: "64010.0",
      high: "64011.0",
      low: "64009.5",
      close: "64010.5",
      volume: "1.500",
      delta: "0.100",
    });
  });

  it("CVD is the running delta at each close", () => {
    const prefix = cvdPrefix(s);
    expect([0, 1, 3].map((i) => cvdAt(s, prefix, i))).toEqual(["0.100", "0.200", "0.400"]);
  });

  it("levels read price descending with the imbalance word", () => {
    expect(levelCount(s, 2)).toBe(3);
    expect(levelsOf(s, 0)).toEqual([
      { price: "64010.5", bid: "0.100", ask: "0.500", delta: "0.400", imbalance: "Ask-stacked" },
      { price: "64010.0", bid: "0.100", ask: "0.100", delta: "0.000", imbalance: "—" },
      { price: "64009.5", bid: "0.400", ask: "0.100", delta: "-0.300", imbalance: "Bid-stacked" },
    ]);
  });

  it("without footprint: no delta, no CVD, no levels", () => {
    const off = makeSeries({ bars: 2, levels: 0 });
    expect(barFields(off, 1).delta).toBeUndefined();
    expect(cvdPrefix(off)).toBeNull();
    expect(cvdAt(off, null, 1)).toBeUndefined();
    expect(levelCount(off, 1)).toBe(0);
    expect(levelsOf(off, 1)).toEqual([]);
  });

  it("imbalance honours the ratio and an empty side", () => {
    expect(imbalanceOf(1, 3, 3)).toBe("Ask-stacked");
    expect(imbalanceOf(1, 2.9, 3)).toBe("—");
    expect(imbalanceOf(5, 0, 3)).toBe("Bid-stacked");
    expect(imbalanceOf(0, 0, 3)).toBe("—");
  });
});

describe("TSV (E11-D04 §8.3)", () => {
  it("header, ISO time, ASCII numbers, an expanded bar's levels indented", () => {
    const s = makeSeries({ bars: 3 });
    const tsv = buildTsv(s, [0, 1], 1, cvdPrefix(s));
    expect(tsv.text.split("\n")).toEqual([
      "time\topen\thigh\tlow\tclose\tvolume\tdelta\tCVD",
      "2026-10-20T13:00:00Z\t64010.0\t64011.0\t64009.5\t64010.5\t1.500\t0.100\t0.100",
      "2026-10-20T13:01:00Z\t64010.5\t64011.5\t64010.0\t64011.0\t2.500\t0.100\t0.200",
      "\t64011.0\t0.100\t0.500\t0.400\tAsk-stacked",
      "\t64010.5\t0.100\t0.100\t0.000\t",
      "\t64010.0\t0.400\t0.100\t-0.300\tBid-stacked",
      "",
    ]);
    expect(tsv).toMatchObject({ rows: 2, columns: 8, capped: false });
  });

  it("leaves delta and CVD empty without footprint", () => {
    const s = makeSeries({ bars: 1, levels: 0 });
    expect(buildTsv(s, [0], null, null).text.split("\n")[1]?.endsWith("\t1.500\t\t")).toBe(true);
  });

  it("no field holds a tab or a line break, so the format needs no escaping", () => {
    const s = makeSeries({ bars: 8 });
    const lines = buildTsv(s, [0, 1, 2, 3, 4, 5, 6, 7], 3, cvdPrefix(s)).text.split("\n");
    expect(lines.at(-1)).toBe("");
    const header = (lines[0] ?? "").split("\t").length;
    for (const line of lines.slice(1, -1)) {
      expect(line).not.toMatch(/\r/);
      expect(line.split("\t").length).toBeLessThanOrEqual(header);
    }
  });

  it("caps a copy at 10,000 rows", () => {
    const s = makeSeries({ bars: TSV_ROW_CAP + 5, levels: 0 });
    const all = Array.from({ length: TSV_ROW_CAP + 5 }, (_, i) => i);
    const tsv = buildTsv(s, all, null, null);
    expect(tsv).toMatchObject({ rows: TSV_ROW_CAP, capped: true });
    expect(tsv.text.split("\n")).toHaveLength(TSV_ROW_CAP + 2);
  });
});
