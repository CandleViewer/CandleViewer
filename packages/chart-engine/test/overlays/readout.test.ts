// E11-S07 readout model: the ordered O, H, L, C, Vol, Δ fields then providers, exact values at
// the bar under a fractional x (AC1, no interpolation), "unavailable" for a missing volume or
// delta (never 0), the snapped label (AC6), the E06-D03 D1/D5 summaries, and the pooled array
// rebuilt only on a change.
import { describe, expect, it } from "vitest";
import { createCrosshair, resolvePointer } from "../../src/overlays/crosshair.js";
import {
  Readout,
  type ReadoutProvider,
  signedText,
  UNAVAILABLE,
  volumeText,
} from "../../src/overlays/readout.js";
import { MIN_US, source, T0, viewport } from "./fixture.js";

const values = (r: Readout): string[] => r.fields.map((f) => f.value);
const labels = (r: Readout): string[] => r.fields.map((f) => f.label);

/** One bar at 14:05 UTC: O 64,300, H 64,400, L 64,100, C 64,210, Vol 1,204, Δ −128. */
function oneBar(): ReturnType<typeof source> {
  const b = source(1);
  b.time[0] = T0 + 5 * MIN_US;
  b.open[0] = 300;
  b.high[0] = 400;
  b.low[0] = 100;
  b.close[0] = 210;
  (b.volume as Float32Array)[0] = 1204;
  (b.delta as Float32Array)[0] = -128;
  return b;
}

describe("readout fields", () => {
  it("test_build_fractionalX_exactValuesOfTheBarUnderIt", () => {
    const vp = viewport(50, 10, 0.25);
    const bars = source(50, 0.5);
    const s = createCrosshair();
    resolvePointer(s, vp, 0, bars, 31.2, 100, "off"); // index 3.37: bar 3, not 3.37
    expect(s.bar).toBe(3);
    const r = new Readout();
    expect(r.build(bars, s.bar, s.snap)).toBe(true);
    expect(r.fields.map((f) => f.key)).toEqual(["open", "high", "low", "close", "volume", "delta"]);
    expect(labels(r)).toEqual(["O", "H", "L", "C", "Vol", "Δ"]);
    // ticks × 0.5 over 64,000: O 203, H 303, L 103, C 253 → exact, one decimal (tick precision).
    expect(values(r)).toEqual(["64,101.5", "64,151.5", "64,051.5", "64,126.5 ▲", "1,003", "−2"]);
    expect(r.fields.every((f) => f.unit === "" && f.colorToken === "color.text.primary")).toBe(
      true,
    );
    expect(r.timeText).toBe("14 Oct 14:03");
  });

  it("test_build_missingVolumeOrDelta_readsUnavailableNeverZero", () => {
    const bars = source(3);
    bars.volume = null;
    bars.delta = null;
    const r = new Readout();
    r.build(bars, 1, null);
    expect(values(r).slice(4)).toEqual([UNAVAILABLE, UNAVAILABLE]);
    expect(r.full).toBe("14:01, close 64,251, delta unavailable");
    const nan = source(3);
    (nan.delta as Float32Array)[2] = Number.NaN;
    r.build(nan, 2, null);
    expect(values(r)[5]).toBe(UNAVAILABLE);
    expect(values(r)[4]).toBe("1,002");
  });

  it("test_build_snappedField_labelledInFull", () => {
    const r = new Readout();
    r.build(source(5), 3, "high");
    expect(labels(r)).toEqual(["O", "High", "L", "C", "Vol", "Δ"]);
    expect(r.build(source(5), 3, "close")).toBe(true);
    expect(labels(r)[3]).toBe("Close");
  });

  it("test_build_closeGlyph_followsDirection", () => {
    const b = oneBar();
    const r = new Readout();
    r.build(b, 0, null);
    expect(values(r)[3]).toBe("64,210 ▼");
    b.close[0] = 300;
    r.build(b, 0, null);
    expect(values(r)[3]).toBe("64,300");
  });

  it("test_build_providers_0_1_3_appendedInOrder", () => {
    const b = source(5);
    const prov = (key: string, v: string | null): ReadoutProvider => ({
      key,
      label: key.toUpperCase(),
      value: () => v,
    });
    const r = new Readout();
    r.build(b, 2, null);
    expect(r.fields).toHaveLength(6);
    r.setProviders([prov("ema20", "64,003.2")]);
    r.build(b, 2, null);
    expect(r.fields).toHaveLength(7);
    expect(r.fields[6]).toEqual({
      key: "ind:ema20",
      label: "EMA20",
      value: "64,003.2",
      unit: "",
      colorToken: "color.text.primary",
    });
    r.setProviders([
      prov("a", "1"),
      { key: "b", label: "B", unit: "%", colorToken: "color.text.buy", value: (i) => `${i}` },
      prov("c", null),
    ]);
    r.build(b, 2, null);
    expect(r.fields.map((f) => f.key).slice(6)).toEqual(["ind:a", "ind:b", "ind:c"]);
    expect(values(r).slice(6)).toEqual(["1", "2", UNAVAILABLE]);
    expect(r.fields[7]).toMatchObject({ unit: "%", colorToken: "color.text.buy" });
    r.setProviders([]);
    r.build(b, 2, null);
    expect(r.fields).toHaveLength(6);
  });

  it("test_build_outsideData_isEmpty", () => {
    const r = new Readout();
    r.build(source(5), 3, null);
    expect(r.build(source(5), 7, null)).toBe(true);
    expect(r.fields).toHaveLength(0);
    expect([r.timeText, r.full, r.short]).toEqual(["", "", ""]);
    expect(r.build(null, 0, null)).toBe(true);
    expect(r.build(null, 0, null)).toBe(false);
  });
});

describe("readout summaries (E06-D03 D1/D5)", () => {
  it("test_summaries_fullAndShortForms", () => {
    const r = new Readout();
    r.build(oneBar(), 0, null);
    expect(r.full).toBe("14:05, close 64,210, delta −128");
    expect(r.short).toBe("14:05, 64,210");
    const b = oneBar();
    b.time[0] = T0 + 12 * MIN_US;
    b.close[0] = 232;
    (b.delta as Float32Array)[0] = 200;
    r.build(b, 0, null);
    expect(r.short).toBe("14:12, 64,232");
    expect(r.full).toBe("14:12, close 64,232, delta +200");
  });

  it("test_summaries_timeZone_shiftsWallClock", () => {
    const r = new Readout("Asia/Kolkata"); // UTC+5:30
    r.build(oneBar(), 0, null);
    expect(r.short).toBe("19:35, 64,210");
    expect(r.timeText).toBe("14 Oct 19:35");
  });

  it("test_signedAndVolumeText", () => {
    expect(signedText(0, 0)).toBe("0");
    expect(signedText(-0.0001, 2)).toBe("0.00");
    expect(signedText(1.5, 1)).toBe("+1.5");
    expect(volumeText(Math.fround(1.2))).toBe("1.2");
    expect(volumeText(12_345.6789)).toBe("12,345.68"); // float32 holds 7 significant digits
    expect(volumeText(0.0001234)).toBe("0.000"); // capped at 3 decimals
    const b = source(1);
    (b.delta as Float32Array)[0] = -1.2; // float32 noise never reaches the text
    const r = new Readout();
    r.build(b, 0, null);
    expect(values(r)[5]).toBe("\u22121.2");
  });
});

describe("readout pooling", () => {
  it("test_build_repeated_noRebuildSameArrayAndObjects", () => {
    const b = source(10);
    const r = new Readout();
    r.build(b, 4, null);
    const arr = r.fields;
    const objs = [...r.fields];
    const n = r.rebuilds;
    for (let k = 0; k < 100; k += 1) expect(r.build(b, 4, null)).toBe(false);
    expect(r.rebuilds).toBe(n);
    expect(r.fields).toBe(arr);
    r.build(b, 5, null); // a different bar rewrites the same objects
    expect(r.fields).toBe(arr);
    r.fields.forEach((f, i) => expect(f).toBe(objs[i]));
  });

  it("test_build_dataChangeAtBar_rebuilds", () => {
    const b = source(10);
    const r = new Readout();
    r.build(b, 4, null);
    b.close[4] = 260; // a forming-bar patch
    expect(r.build(b, 4, null)).toBe(true);
    expect(values(r)[3]).toBe("64,260 ▲");
    (b.volume as Float32Array)[4] = 7;
    expect(r.build(b, 4, null)).toBe(true);
    b.close[5] = 1; // another bar: no rebuild
    expect(r.build(b, 4, null)).toBe(false);
    r.invalidate(); // a provider's value moved
    expect(r.build(b, 4, null)).toBe(true);
    b.tickSize = 0.5;
    expect(r.build(b, 4, null)).toBe(true);
  });
});
