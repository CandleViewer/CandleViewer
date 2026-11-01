// E11-T04 PR-3 property (seeded mulberry32 loops, as the PR-2 ingest property): over random
// complete themes, every LUT entry on a stop position reproduces that stop's bytes, the inverted
// convention is a pure intensity-row swap and a delta row over `DELTA_STOPS_INVERTED` (the twin's
// ±1 ends swapped, as the host delivers them), entries between two stops stay between their
// lightnesses, and a reused writer carries no state from one theme into the next.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import {
  ColorLutWriter,
  DELTA_STOPS_INVERTED,
  LUT_BYTES,
  LUT_ROW,
  LUT_ROW_BYTES,
  LUT_WIDTH,
  RAMP_STOPS,
  deltaT,
  intensityT,
} from "../../src/theme/ColorLut.js";
import { srgbToOklab } from "../../src/theme/oklab.js";
import { ingestTheme, type EngineTheme } from "../../src/theme/ThemeIngest.js";
import { THEME_SLOTS } from "../../src/theme/slots.js";

const CASES = 150;
const SLOW = 20_000; // a loaded shared runner (C-9.3), as the PR-2 property

function randomTheme(rng: () => number, convention: "standard" | "inverted"): EngineTheme {
  const hex = (): string =>
    `#${Math.floor(rng() * 0x1000000)
      .toString(16)
      .padStart(6, "0")}`;
  const colors: Record<string, string> = Object.fromEntries(THEME_SLOTS.map((s) => [s, hex()]));
  if (convention === "inverted") {
    // The host's DIRECTIONAL_PAIRS remap: the ±1 ends arrive swapped, color.heatmap.* does not.
    const buy = colors["color.buy.default"] as string;
    colors["color.buy.default"] = colors["color.sell.default"] as string;
    colors["color.sell.default"] = buy;
  }
  return ingestTheme({ palette: "default", convention, colors });
}

const L = (bytes: Uint8Array, o: number, v: Float64Array): number => {
  srgbToOklab(
    (bytes[o] as number) / 255,
    (bytes[o + 1] as number) / 255,
    (bytes[o + 2] as number) / 255,
    v,
  );
  return v[0] as number;
};

describe("Property: LUT rows over random themes", () => {
  it(
    `${CASES} seeded themes: stops exact, swap pure, entries bounded by their stops`,
    () => {
      const rng = mulberry32(0x1c07);
      const writer = new ColorLutWriter();
      const std = new Uint8Array(LUT_BYTES);
      const inv = new Uint8Array(LUT_BYTES);
      const v = new Float64Array(3);
      const violations: string[] = [];
      for (let n = 0; n < CASES; n += 1) {
        const seed = rng();
        const theme = randomTheme(mulberry32(Math.floor(seed * 2 ** 32)), "standard");
        const twin = randomTheme(mulberry32(Math.floor(seed * 2 ** 32)), "inverted");
        writer.writeAll(theme, std);
        writer.writeAll(twin, inv);
        const rows = [
          [std, theme, LUT_ROW.bid, RAMP_STOPS.bid, intensityT],
          [std, theme, LUT_ROW.ask, RAMP_STOPS.ask, intensityT],
          [std, theme, LUT_ROW.delta, RAMP_STOPS.delta, deltaT],
          [inv, twin, LUT_ROW.delta, DELTA_STOPS_INVERTED, deltaT],
        ] as const;
        for (const [buf, th, row, stops, tOf] of rows) {
          const base = row * LUT_ROW_BYTES;
          let k = 0;
          for (let i = 0; i < LUT_WIDTH; i += 1) {
            const t = tOf(i);
            while (k < stops.length - 2 && t > (stops[k + 1] as (typeof stops)[number])[1]) k += 1;
            const [s0, t0] = stops[k] as (typeof stops)[number];
            const [s1, t1] = stops[k + 1] as (typeof stops)[number];
            const o = base + i * 4;
            const got = Array.from(buf.subarray(o, o + 4));
            for (const [slot, ts] of [
              [s0, t0],
              [s1, t1],
            ] as const) {
              const want = th.slots[slot].map((c) => Math.round(c * 255));
              if (t === ts && got.join() !== want.join())
                violations.push(`${n} ${row}/${i} ${slot}`);
            }
            const bytes = (slot: typeof s0): Uint8Array =>
              Uint8Array.from(th.slots[slot].map((c) => Math.round(c * 255)));
            const lo = Math.min(L(bytes(s0), 0, v), L(bytes(s1), 0, v));
            const hi = Math.max(L(bytes(s0), 0, v), L(bytes(s1), 0, v));
            const l = L(buf, o, v);
            // L is linear along each OkLab segment; 0.004 allows the 8-bit rounding of the entry.
            if (l < lo - 0.004 || l > hi + 0.004) violations.push(`${n} ${row}/${i} L ${l}`);
          }
        }
        const r = (b: Uint8Array, row: number): string =>
          b.subarray(row * LUT_ROW_BYTES, (row + 1) * LUT_ROW_BYTES).join();
        if (
          r(inv, LUT_ROW.bid) !== r(std, LUT_ROW.ask) ||
          r(inv, LUT_ROW.ask) !== r(std, LUT_ROW.bid)
        ) {
          violations.push(`${n} swap`);
        }
        const ends = (b: Uint8Array, i: number): string =>
          b
            .subarray(
              LUT_ROW.delta * LUT_ROW_BYTES + i * 4,
              LUT_ROW.delta * LUT_ROW_BYTES + i * 4 + 4,
            )
            .join();
        if (ends(inv, 0) !== ends(std, 255) || ends(inv, 255) !== ends(std, 0)) {
          violations.push(`${n} delta ends`);
        }
        const again = writer.writeAll(theme, new Uint8Array(LUT_BYTES));
        if (again.join() !== std.join()) violations.push(`${n} writer state leaked`);
      }
      expect(violations).toEqual([]);
    },
    SLOW,
  );
});
