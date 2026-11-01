// E11-T04 PR-2 (BQ-T04-03, BQ-T04-07; E11-D05 §4, §7): the slot list, the contrast pair table and
// the pattern registry are fixed data: names unique, classes per D05, ids never renamed.
import { describe, expect, it } from "vitest";
import { DASHES, PATTERNS, patternById } from "../../src/theme/patterns.js";
import { ENGINE_SLOT_PAIRS, SLOT_COUNT, SLOT_INDEX, THEME_SLOTS } from "../../src/theme/slots.js";

describe("THEME_SLOTS", () => {
  it("are unique, indexed in order and carry D05's eighteen color.chart.* aliases", () => {
    expect(new Set(THEME_SLOTS).size).toBe(SLOT_COUNT);
    THEME_SLOTS.forEach((s, i) => expect(SLOT_INDEX[s]).toBe(i));
    expect(THEME_SLOTS.filter((s) => s.startsWith("color.chart.")).length).toBe(18);
    expect(Object.isFrozen(SLOT_INDEX)).toBe(true);
  });

  it("carry no CVD-safe heatmap stop (G16: no engine route yet)", () => {
    expect(THEME_SLOTS.some((s) => s.startsWith("color.cvd."))).toBe(false);
  });
});

describe("ENGINE_SLOT_PAIRS", () => {
  it("lists every drawn slot (the pane fill and the zero stop are backgrounds only)", () => {
    const seen = new Set(ENGINE_SLOT_PAIRS.flatMap((p) => [p.fg, p.bg]));
    expect(THEME_SLOTS.filter((s) => !seen.has(s))).toEqual(["color.heatmap.zero"]);
  });

  it("marks D05 Q4's eight decorative slots decorative, measured on the ninth", () => {
    const decorative = ENGINE_SLOT_PAIRS.filter((p) => p.cls === "decorative").map((p) => p.fg);
    expect(decorative.sort()).toEqual(
      [
        "color.chart.grid.major",
        "color.chart.grid.minor",
        "color.chart.watermark",
        "color.chart.pane.bg.focused",
        "color.chart.rule",
        "color.chart.hatch.texture",
        "color.chart.pill.bg",
        "color.chart.pill.border",
      ].sort(),
    );
    // The ninth, color.chart.pane.bg.default, is the background every other pair is measured on.
    expect(ENGINE_SLOT_PAIRS.some((p) => p.fg === "color.chart.pane.bg.default")).toBe(false);
  });

  it("gates every pill text and the axis as text", () => {
    const text = ENGINE_SLOT_PAIRS.filter((p) => p.cls === "text").map((p) => `${p.fg}/${p.bg}`);
    expect(text).toEqual([
      "color.chart.axis/color.chart.pane.bg.default",
      "color.chart.pill.text.default/color.chart.pill.bg",
      "color.chart.pill.text.inverse/color.chart.crosshair",
      "color.chart.pill.text.inverse/color.candle.up",
      "color.chart.pill.text.inverse/color.candle.down",
      "color.chart.pill.text.on-marker/color.chart.marker.goto",
    ]);
  });

  it("measures the crosshair over both grid lines (D05 §4.1's tightest non-text margin)", () => {
    const over = ENGINE_SLOT_PAIRS.filter((p) => p.fg === "color.chart.crosshair").map(
      (p) => `${p.bg}:${p.cls}`,
    );
    expect(over).toEqual([
      "color.chart.pane.bg.default:non-text",
      "color.chart.grid.major:non-text",
      "color.chart.grid.minor:non-text",
    ]);
  });

  it("is frozen, pairs included", () => {
    expect(Object.isFrozen(ENGINE_SLOT_PAIRS)).toBe(true);
    for (const p of ENGINE_SLOT_PAIRS) expect(Object.isFrozen(p)).toBe(true);
  });
});

describe("the pattern registry (D05 §7)", () => {
  it("registers the eight ids in order with stable indices", () => {
    expect(PATTERNS.map((p) => `${p.index}:${p.id}`)).toEqual([
      "0:pattern.hatch.estimated",
      "1:pattern.dashed.estimated",
      "2:pattern.hatch.gap",
      "3:pattern.hatch.absent",
      "4:pattern.dashed.tested",
      "5:pattern.outline.imbalance",
      "6:glyph.notch.delta",
      "7:indicator.reduced-detail",
    ]);
  });

  it("carries D05's geometry and ink", () => {
    expect(patternById("pattern.hatch.estimated")).toMatchObject({
      angleDeg: 45,
      pitchPx: 2,
      opacity: 0.3,
      ink: "fill",
    });
    expect(patternById("pattern.hatch.gap")).toMatchObject({
      pitchPx: 6,
      ink: "color.chart.hatch.texture",
      edgeInk: "color.chart.boundary",
      dash: "dash.4-4",
    });
    expect(patternById("pattern.dashed.tested")).toMatchObject({ opacity: 0.7, dash: "dash.4-3" });
    expect(patternById("pattern.outline.imbalance")).toMatchObject({
      lineWidthPx: 1.5,
      ink: "color.footprint.imbalance",
    });
    expect(patternById("indicator.reduced-detail")?.kind).toBe("dom");
  });

  it("no pattern means a side or direction", () => {
    for (const p of PATTERNS) expect(p.meaning).not.toMatch(/buy|sell|bid|ask|up|down|side/);
  });

  it("every slot ink names a registered slot", () => {
    for (const p of PATTERNS) {
      for (const ink of [p.ink, p.edgeInk]) {
        if (ink !== null && ink.startsWith("color.")) expect(SLOT_INDEX).toHaveProperty([ink]);
      }
    }
  });

  it("an unregistered id is undefined: it is never drawn", () => {
    expect(patternById("pattern.hatch.new")).toBeUndefined();
  });

  it("the dash index is D05 §7.2's, frozen", () => {
    expect(DASHES.map((d) => `${d.index}:${d.id}=${d.onPx}/${d.offPx}`)).toEqual([
      "0:dash.4-4=4/4",
      "1:dash.2-6=2/6",
      "2:dash.2-2=2/2",
      "3:dash.4-3=4/3",
      "4:dash.3-3=3/3",
    ]);
    expect(Object.isFrozen(DASHES) && DASHES.every((d) => Object.isFrozen(d))).toBe(true);
    expect(Object.isFrozen(PATTERNS) && PATTERNS.every((p) => Object.isFrozen(p))).toBe(true);
    for (const p of PATTERNS) {
      if (p.dash !== null) expect(DASHES.map((d) => d.id)).toContain(p.dash);
    }
  });
});
