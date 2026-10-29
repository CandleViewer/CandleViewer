import { describe, expect, it, vi } from "vitest";
import { createEngine, type EngineTheme } from "../src/compat.js";

const cvd: EngineTheme = {
  palette: "cvd-safe",
  convention: "standard",
  colors: { "color.buy.default": "#0072b2", "color.sell.default": "#e69f00" },
};

describe("engine setTheme", () => {
  it("uploads the palette once per distinct theme", () => {
    const upload = vi.fn();
    const e = createEngine({ uploadPalette: upload });
    e.setTheme(cvd);
    e.setTheme({ ...cvd });
    expect(e.stats().paletteUploads).toBe(1);
    expect(upload).toHaveBeenCalledTimes(1);
    const packed = upload.mock.calls[0]?.[1] as Float32Array;
    expect(packed.length).toBe(8);
    expect(packed[0]).toBeCloseTo(0);
    expect(packed[2]).toBeCloseTo(0xb2 / 255, 3);
  });

  it("re-uploads when the palette or convention changes", () => {
    const e = createEngine();
    e.setTheme(cvd);
    e.setTheme({ ...cvd, convention: "inverted" });
    expect(e.stats().paletteUploads).toBe(2);
  });

  it("packs non-hex colours as black and ignores setTheme after dispose", () => {
    const upload = vi.fn();
    const e = createEngine({ uploadPalette: upload });
    e.setTheme({ ...cvd, colors: { a: "rgb(1,2,3)" } });
    expect((upload.mock.calls[0]?.[1] as Float32Array)[0]).toBe(0);
    e.dispose();
    e.setTheme(cvd);
    expect(e.stats().paletteUploads).toBe(1);
  });
});
