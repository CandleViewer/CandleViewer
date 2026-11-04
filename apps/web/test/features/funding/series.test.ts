// E24-S03 (#778) slice 1: the stepped series' width comes from the served interval, never the spacing.
import { describe, expect, it } from "vitest";
import { buildFundingSeries } from "../../../src/features/funding/series";
import { recordedSettled } from "./support/fundingFixtures";

const points = (which: "BTCUSDT_8h" | "ETHUSDT_4h") =>
  recordedSettled(which).map((i) => ({ tMs: Date.parse(i.t), rate: i.funding_rate }));
const build = (
  settled: ReturnType<typeof points>,
  intervalMinutes: number | null,
  more: Partial<Parameters<typeof buildFundingSeries>[0]> = {},
) => buildFundingSeries({ settled, intervalMinutes, coverage: null, ...more });
const H = 3_600_000;

describe("funding series", () => {
  it("steps each settlement over the interval before it, at the served width", () => {
    const s = build(points("BTCUSDT_8h"), 480);
    expect(s.intervalMs).toBe(8 * H);
    for (const step of s.steps) expect(step.toMs - step.fromMs).toBe(8 * H);
    expect(s.steps[0]).toMatchObject({ rate: "0.00012", toMs: points("BTCUSDT_8h")[0]?.tMs });
  });

  it("keeps the width when a settlement is missing, so a hole is never stretched over", () => {
    const missing = points("BTCUSDT_8h").filter((_, i) => i !== 1);
    const s = build(missing, 480);
    expect(s.steps.map((x) => x.toMs - x.fromMs)).toEqual([8 * H, 8 * H, 8 * H]);
  });

  it("renders six settlements a day for a 4 h symbol and assumes no 8 h", () => {
    const s = build(points("ETHUSDT_4h"), 240);
    expect(s.steps.every((x) => x.toMs - x.fromMs === 4 * H)).toBe(true);
    expect(86_400_000 / (s.intervalMs ?? 0)).toBe(6);
  });

  it("draws no step when the interval is not served, and keeps the points for the table", () => {
    const s = build(points("BTCUSDT_8h"), null);
    expect(s.steps).toEqual([]);
    expect(s.settled).toHaveLength(4);
  });

  it("keeps the coverage gaps apart from the steps, never filled", () => {
    const gap = { fromMs: 0, toMs: 1 };
    const coverage = { noCoverage: false, gaps: [gap] };
    const s = build([], 480, { coverage });
    expect(s.gaps).toEqual([gap]);
    expect(s.steps).toEqual([]);
  });
});
