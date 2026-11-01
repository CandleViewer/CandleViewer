// E11-T04 PR-2 (AC2; BQ-T04-05): density is one record per mode — E11-D05 §6's four members plus
// the axis gap — selected whole; no API sets one member.
import { describe, expect, it } from "vitest";
import {
  DENSITY_MODES,
  DensityState,
  SIZE_CLASS_PX,
  densityRecord,
  type DensityRecord,
} from "../../src/theme/Density.js";
import { ThemeIngestError } from "../../src/theme/ThemeIngest.js";

const MEMBERS = ["cellPadPx", "fontSizeClass", "axisFontSizeClass", "lodBias"] as const;

describe("densityRecord", () => {
  it.each([
    ["comfortable", 4, 1, 2, 1, 96, 48],
    ["compact", 2, 0, 1, 0, 80, 40],
    ["dense", 1, 0, 0, 0, 64, 32],
  ] as const)("%s = D05 §6", (mode, cellPadPx, font, axisFont, lodBias, timePx, pricePx) => {
    expect(densityRecord(mode)).toEqual({
      mode,
      cellPadPx,
      fontSizeClass: font,
      axisFontSizeClass: axisFont,
      lodBias,
      axisGap: { timePx, pricePx },
    });
  });

  it("covers the three modes, and the class → px map is 10 / 11 / 13", () => {
    expect(DENSITY_MODES).toEqual(["comfortable", "compact", "dense"]);
    expect(SIZE_CLASS_PX).toEqual([10, 11, 13]);
  });

  it("comfortable → dense changes all four members together", () => {
    const a = densityRecord("comfortable");
    const b = densityRecord("dense");
    for (const m of MEMBERS) expect(b[m], m).not.toBe(a[m]);
  });

  it("compact → dense keeps lodBias 0: dense buys density with padding, never legibility", () => {
    expect(densityRecord("dense").lodBias).toBe(densityRecord("compact").lodBias);
    expect(densityRecord("dense").lodBias).toBe(0);
  });

  it("lodBias is never negative", () => {
    for (const m of DENSITY_MODES) expect(densityRecord(m).lodBias).toBeGreaterThanOrEqual(0);
  });

  it("the record is deep-frozen and the same object per mode", () => {
    const r = densityRecord("compact");
    expect(Object.isFrozen(r)).toBe(true);
    expect(Object.isFrozen(r.axisGap)).toBe(true);
    expect(densityRecord("compact")).toBe(r);
    expect(() => {
      (r as { cellPadPx: number }).cellPadPx = 9;
    }).toThrow(TypeError);
  });

  it.each(["", "Dense", "cozy", 1, null, "toString", "__proto__"])(
    "%j → ENGINE_THEME_INVALID",
    (m) => {
      expect(() => densityRecord(m)).toThrow(ThemeIngestError);
      expect(() => densityRecord(m)).toThrow('ENGINE_THEME_INVALID: invalid "density"');
    },
  );
});

describe("DensityState: one call swaps the whole record", () => {
  it("defaults to comfortable (§8 ChartOptions.density) and swaps whole records", () => {
    const s = new DensityState();
    expect(s.current).toBe(densityRecord("comfortable"));
    expect(s.set("dense")).toBe(densityRecord("dense"));
    expect(s.current).toBe(densityRecord("dense"));
  });

  it("a bad mode leaves the record unchanged", () => {
    const s = new DensityState();
    s.set("compact");
    expect(() => s.set("x" as never)).toThrow(ThemeIngestError);
    expect(s.current).toBe(densityRecord("compact"));
  });

  it("exposes no per-member setter (type-level and at run time)", () => {
    const s = new DensityState();
    const r: DensityRecord = s.current;
    expect(() => {
      // @ts-expect-error -- members are readonly: no API sets one member alone (D6 rule 1)
      r.lodBias = 3;
    }).toThrow(TypeError);
    expect(() => {
      // @ts-expect-error -- `current` is a getter only
      s.current = densityRecord("dense");
    }).toThrow(TypeError);
    expect(Object.getOwnPropertyNames(DensityState.prototype).sort()).toEqual(
      ["constructor", "current", "set"].sort(),
    );
  });
});
