// E11-T04 PR-3 (E11-D05 §5.1, G4): the engine's OkLab against the design side. The vectors are
// D05 §5.2's measured stops (dark and light), not the theme: each row is an input hex, the WCAG
// relative luminance `tools/contrast/color-math.mjs` prints for it, and the OkLab L / a / b the
// D05 audit tool (`docs/design/_tools/e11_d05_ds_audit.py`, the same matrices) prints to four
// decimals. A drifted coefficient or transfer constant fails here.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import {
  linearToSrgb,
  oklabToSrgb,
  relativeLuminance,
  srgbToLinear,
  srgbToOklab,
} from "../../src/theme/oklab.js";
import { parseHexColor } from "../../src/theme/ThemeIngest.js";

// [hex, tools/contrast relativeLuminance, D05 §5.2 L, a, b]
const VECTORS: readonly (readonly [string, number, number, number, number])[] = [
  ["#E5484D", 0.21828565045428178, 0.6256, 0.1779, 0.0756], // dark sell.default
  ["#B83539", 0.1303196085425251, 0.5273, 0.1536, 0.0666], // dark heatmap.ask.1
  ["#11151A", 0.007300827199359924, 0.1938, -0.0033, -0.0115], // dark surface.canvas
  ["#1B7539", 0.13250998831394573, 0.4964, -0.1075, 0.0626], // dark heatmap.bid.1
  ["#2EBD59", 0.3769730304173575, 0.7029, -0.1568, 0.0958], // dark buy.default
  ["#6BD48A", 0.520477447386336, 0.7882, -0.1267, 0.069], // dark heatmap.bid.5
  ["#F5B0B0", 0.5359773464952782, 0.8219, 0.0767, 0.0263], // dark heatmap.ask.5
  ["#C7373C", 0.15200734926586962, 0.5556, 0.1655, 0.0722], // light sell.default
  ["#F6F7F9", 0.9295391205067929, 0.9759, -0.0003, -0.0029], // light surface.canvas
  ["#2E9A55", 0.24347921626749172, 0.6088, -0.1244, 0.068], // light heatmap.bid.1
  ["#0A3018", 0.02244382539524602, 0.2752, -0.0541, 0.0287], // light heatmap.bid.5
  ["#4E1518", 0.02221979885854175, 0.2916, 0.0798, 0.031], // light heatmap.ask.5
];

const rgbOf = (hex: string): readonly [number, number, number] => {
  const c = parseHexColor(hex);
  if (c === null) throw new Error(hex);
  return [c[0], c[1], c[2]];
};

describe("OkLab parity with tools/contrast and the D05 audit (G4)", () => {
  it.each(VECTORS)("%s: luminance and L / a / b match to the printed digits", (hex, y, L, a, b) => {
    const [r, g, bl] = rgbOf(hex);
    expect(relativeLuminance(r, g, bl)).toBeCloseTo(y, 12);
    const lab = new Float64Array(3);
    srgbToOklab(r, g, bl, lab);
    expect([lab[0], lab[1], lab[2]].map((v) => Number((v as number).toFixed(4)))).toEqual([
      L,
      a,
      b,
    ]);
  });

  it.each(VECTORS)("%s: sRGB → OkLab → sRGB round-trips within the D05 1e-6 bar", (hex) => {
    const [r, g, b] = rgbOf(hex);
    const v = new Float64Array(3);
    srgbToOklab(r, g, b, v);
    oklabToSrgb(v[0] as number, v[1] as number, v[2] as number, v);
    expect(Math.max(Math.abs((v[0] as number) - r), Math.abs((v[1] as number) - g))).toBeLessThan(
      1e-6,
    );
    expect(Math.abs((v[2] as number) - b)).toBeLessThan(1e-6);
  });

  it("self-checks (D05 §5.1): white L = 1, black L = 0, a grey has a = b = 0", () => {
    const v = new Float64Array(3);
    srgbToOklab(1, 1, 1, v);
    expect(Math.abs((v[0] as number) - 1)).toBeLessThan(1e-7);
    expect(Math.max(Math.abs(v[1] as number), Math.abs(v[2] as number))).toBeLessThan(1e-7);
    srgbToOklab(0, 0, 0, v);
    expect(v[0]).toBe(0);
    srgbToOklab(128 / 255, 128 / 255, 128 / 255, v);
    expect(Math.max(Math.abs(v[1] as number), Math.abs(v[2] as number))).toBeLessThan(1e-7);
  });

  it("the transfer pair is tools/contrast's: knee at 0.04045 / 0.0031308, clamped to [0, 1]", () => {
    expect(srgbToLinear(0.04045)).toBeCloseTo(0.04045 / 12.92, 15);
    expect(srgbToLinear(1)).toBeCloseTo(1, 15);
    expect(linearToSrgb(0.0031308)).toBeCloseTo(0.0031308 * 12.92, 15);
    expect(linearToSrgb(-0.2)).toBe(0);
    expect(linearToSrgb(1.3)).toBeCloseTo(1, 15);
  });

  it("converters write at the caller's offset and touch nothing else", () => {
    const out = new Float64Array(5).fill(9);
    srgbToOklab(1, 1, 1, out, 1);
    expect([out[0], out[4]]).toEqual([9, 9]);
    expect(out[1]).toBeCloseTo(1, 6);
  });
});

describe("Property: OkLab round trip over seeded sRGB colours", () => {
  // The token round trip is 4.7e-7 (D05 §5.1); over arbitrary colours the ten-digit matrices
  // give about 1.6e-6, three orders under half an 8-bit step, so every byte round-trips exactly.
  it("2000 seeded 8-bit colours round-trip to within 5e-6 per channel", () => {
    const rng = mulberry32(0x0c1a);
    const v = new Float64Array(3);
    let worst = 0;
    for (let n = 0; n < 2000; n += 1) {
      const r = Math.floor(rng() * 256) / 255;
      const g = Math.floor(rng() * 256) / 255;
      const b = Math.floor(rng() * 256) / 255;
      srgbToOklab(r, g, b, v);
      oklabToSrgb(v[0] as number, v[1] as number, v[2] as number, v);
      worst = Math.max(
        worst,
        Math.abs((v[0] as number) - r),
        Math.abs((v[1] as number) - g),
        Math.abs((v[2] as number) - b),
      );
    }
    expect(worst).toBeLessThan(5e-6);
  });
});
