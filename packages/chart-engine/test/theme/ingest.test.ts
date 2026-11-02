// E11-T04 PR-2 (AC4; BQ-T04-03, BQ-T04-04): the token object becomes a frozen engine theme, or
// ENGINE_THEME_INVALID names the bad key and nothing is installed.
import { describe, expect, it } from "vitest";
import { ENGINE_THEME_INVALID } from "../../src/theme/codes.js";
import { SLOT_COUNT, SLOT_INDEX, THEME_SLOTS } from "../../src/theme/slots.js";
import {
  PACKED_THEME_LENGTH,
  ThemeIngestError,
  ThemeState,
  ingestTheme,
  packTheme,
  parseHexColor,
} from "../../src/theme/ThemeIngest.js";
import { fullColors, hexFor, validInput } from "./fixture.js";

function caught(fn: () => unknown): ThemeIngestError {
  try {
    fn();
  } catch (e) {
    if (e instanceof ThemeIngestError) return e;
    throw e;
  }
  throw new Error("expected a ThemeIngestError");
}

describe("parseHexColor", () => {
  it.each([
    ["#ffffff", [1, 1, 1, 1]],
    ["#000000", [0, 0, 0, 1]],
    ["#FF8000", [1, 128 / 255, 0, 1]],
    ["#f80", [1, 136 / 255, 0, 1]],
    ["#11223380", [0x11 / 255, 0x22 / 255, 0x33 / 255, 0x80 / 255]],
  ])("%s resolves to straight sRGB 0..1", (hex, rgba) => {
    expect(parseHexColor(hex)).toEqual(rgba);
  });

  it.each([
    "",
    "fff",
    "#ff",
    "#ffff",
    "#fffff",
    "#ggg",
    "#1234567",
    "rgb(1,2,3)",
    " #fff",
    "#fff ",
  ])("%j is rejected", (v) => {
    expect(parseHexColor(v)).toBeNull();
  });

  it("a non-string is rejected", () => {
    expect(parseHexColor(0xffffff)).toBeNull();
    expect(parseHexColor(null)).toBeNull();
  });

  it("the parsed colour is frozen", () => {
    expect(Object.isFrozen(parseHexColor("#123"))).toBe(true);
  });
});

describe("ingestTheme: a complete token object", () => {
  it("resolves every slot, ignoring unknown keys", () => {
    const theme = ingestTheme(validInput({ colors: { ...fullColors(), "color.other": "#fff" } }));
    expect(Object.keys(theme.slots)).toEqual([...THEME_SLOTS]);
    expect(theme.slots["color.chart.axis"]).toEqual(parseHexColor(hexFor(0)));
    expect(theme).toMatchObject({ name: null, palette: "default", convention: "standard" });
  });

  it("carries the optional name, palette and convention", () => {
    const t = ingestTheme(
      validInput({ name: "high-contrast", palette: "cvd-safe", convention: "inverted" }),
    );
    expect(t).toMatchObject({ name: "high-contrast", palette: "cvd-safe", convention: "inverted" });
  });

  it("is deep-frozen", () => {
    const theme = ingestTheme(validInput());
    expect(Object.isFrozen(theme)).toBe(true);
    expect(Object.isFrozen(theme.slots)).toBe(true);
    for (const s of THEME_SLOTS) expect(Object.isFrozen(theme.slots[s])).toBe(true);
    expect(() => {
      (theme.slots as Record<string, unknown>)["color.chart.axis"] = [0, 0, 0, 1];
    }).toThrow(TypeError);
  });

  it("does not alias the caller's colour map", () => {
    const colors = fullColors();
    const theme = ingestTheme(validInput({ colors }));
    colors["color.chart.axis"] = "#000000";
    expect(theme.slots["color.chart.axis"]).toEqual(parseHexColor(hexFor(0)));
  });
});

describe("ingestTheme: ENGINE_THEME_INVALID names the key", () => {
  it.each(THEME_SLOTS.filter((_, i) => i % 7 === 0))("a missing %s", (slot) => {
    const colors = fullColors();
    delete colors[slot];
    const err = caught(() => ingestTheme(validInput({ colors })));
    expect(err).toMatchObject({ code: ENGINE_THEME_INVALID, key: slot, reason: "missing" });
    expect(err.message).toBe(`ENGINE_THEME_INVALID: missing "${slot}"`);
  });

  it("an invalid slot value", () => {
    const err = caught(() =>
      ingestTheme(validInput({ colors: { ...fullColors(), "color.candle.up": "green" } })),
    );
    expect(err).toMatchObject({ key: "color.candle.up", reason: "invalid" });
  });

  it("the first bad slot in THEME_SLOTS order is the one named", () => {
    const colors = fullColors();
    delete colors["color.heatmap.ask.5"];
    colors["color.chart.rule"] = "nope";
    expect(caught(() => ingestTheme(validInput({ colors }))).key).toBe("color.chart.rule");
  });

  it("an array colors object is refused at the first slot", () => {
    const empty = [] as unknown as Record<string, string>;
    expect(caught(() => ingestTheme(validInput({ colors: empty }))).key).toBe(THEME_SLOTS[0]);
    // Own slot keys still count on an array, so every slot stays required, nothing more.
    const filled = Object.assign([], fullColors()) as unknown as Record<string, string>;
    expect(ingestTheme(validInput({ colors: filled })).slots["color.candle.up"]).toBeDefined();
  });

  it("an inherited key does not count as present", () => {
    const colors = Object.create(fullColors()) as Record<string, string>;
    expect(caught(() => ingestTheme(validInput({ colors }))).key).toBe(THEME_SLOTS[0]);
  });

  it.each([
    [null, "theme", "invalid"],
    ["dark", "theme", "invalid"],
    [{ convention: "standard", colors: {} }, "palette", "missing"],
    [{ palette: "neon", convention: "standard", colors: {} }, "palette", "invalid"],
    [{ palette: "default", colors: {} }, "convention", "missing"],
    [{ palette: "default", convention: 1, colors: {} }, "convention", "invalid"],
    [{ palette: "default", convention: "standard", name: "sepia", colors: {} }, "name", "invalid"],
    [{ palette: "default", convention: "standard" }, "colors", "missing"],
    [{ palette: "default", convention: "standard", colors: null }, "colors", "invalid"],
    [{ palette: "default", convention: "standard", colors: "x" }, "colors", "invalid"],
  ])("%j → %s %s", (input, key, reason) => {
    expect(caught(() => ingestTheme(input))).toMatchObject({ key, reason });
  });
});

describe("ThemeState installs all of a theme or nothing", () => {
  it("starts empty and installs a valid theme", () => {
    const state = new ThemeState();
    expect(state.current).toBeNull();
    const t = state.apply(validInput());
    expect(state.current).toBe(t);
  });

  it("a failing apply leaves the installed theme untouched", () => {
    const state = new ThemeState();
    const before = state.apply(validInput());
    const colors = fullColors();
    delete colors["color.chart.focus.ring"];
    expect(() => state.apply(validInput({ colors }))).toThrow(/color\.chart\.focus\.ring/);
    expect(state.current).toBe(before);
  });
});

describe("packTheme", () => {
  it("writes every slot's quad in THEME_SLOTS order into the caller's buffer", () => {
    const theme = ingestTheme(validInput());
    const out = new Float32Array(PACKED_THEME_LENGTH + 4);
    expect(packTheme(theme, out, 4)).toBe(out);
    expect(PACKED_THEME_LENGTH).toBe(SLOT_COUNT * 4);
    const i = SLOT_INDEX["color.candle.down"] * 4 + 4;
    expect(Array.from(out.subarray(i, i + 4))).toEqual(
      Array.from(new Float32Array(theme.slots["color.candle.down"])),
    );
    expect(Array.from(out.subarray(0, 4))).toEqual([0, 0, 0, 0]);
  });

  it("refuses a buffer that is too short", () => {
    const theme = ingestTheme(validInput());
    expect(() => packTheme(theme, new Float32Array(PACKED_THEME_LENGTH), 1)).toThrow(RangeError);
  });

  it.each([-1, 0.5, Number.NaN])("refuses offset %s instead of dropping writes", (offset) => {
    const theme = ingestTheme(validInput());
    const out = new Float32Array(PACKED_THEME_LENGTH + 8);
    expect(() => packTheme(theme, out, offset)).toThrow(RangeError);
    expect(out.every((v) => v === 0)).toBe(true);
  });
});
