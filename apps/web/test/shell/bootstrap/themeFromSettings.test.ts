import { describe, expect, it } from "vitest";
import {
  themeFromSettings,
  type ThemeSettings,
} from "../../../src/shell/bootstrap/themeFromSettings.js";

// The server's JSON is untyped at runtime, so the invalid-input rows must be able to say what the types forbid.
const loose = (value: unknown): ThemeSettings => value as ThemeSettings;
const appearance = (value: Record<string, unknown>): ThemeSettings => loose({ appearance: value });

describe("themeFromSettings: appearance.theme", () => {
  it.each([
    ["dark", { baseTheme: "dark", matchSystem: false }],
    ["light", { baseTheme: "light", matchSystem: false }],
    ["system", { matchSystem: true }],
  ])("maps %s", (theme, expected) => {
    expect(themeFromSettings(appearance({ theme }))).toStrictEqual(expected);
  });

  it.each(["auto", "DARK", "", 1, null, {}])("leaves the runtime alone for the invalid %j", (v) => {
    expect(themeFromSettings(appearance({ theme: v }))).toStrictEqual({});
  });
});

describe("themeFromSettings: appearance.density", () => {
  it.each([
    ["compact", "compact"],
    ["comfortable", "comfortable"],
    ["spacious", "comfortable"],
  ])("maps %s to %s", (density, expected) => {
    expect(themeFromSettings(appearance({ density }))).toStrictEqual({ density: expected });
  });

  it.each(["cosy", "", 2, null])("leaves the runtime alone for the invalid %j", (v) => {
    expect(themeFromSettings(appearance({ density: v }))).toStrictEqual({});
  });
});

describe("themeFromSettings: appearance.font_scale", () => {
  it.each([
    [0.75, 100],
    [1, 100],
    [1.05, 100],
    [1.06, 112], // 106 %: halfway between 100 and 112, a tie rounds up
    [1.12, 112],
    [1.18, 112],
    [1.185, 125], // 118.5 %: halfway between 112 and 125
    [1.25, 125],
    [1.37, 125],
    [1.375, 150], // 137.5 %: halfway between 125 and 150
    [1.5, 150],
    [2, 150],
  ])("maps the factor %s to %s percent", (fontScale, expected) => {
    expect(themeFromSettings(appearance({ font_scale: fontScale }))).toStrictEqual({
      textScale: expected,
    });
  });

  it.each([Number.NaN, Infinity, -Infinity, 0, -1, 0.74, 2.01, "1.25", null, true, {}])(
    "leaves the runtime alone for the invalid %j",
    (v) => {
      expect(themeFromSettings(appearance({ font_scale: v }))).toStrictEqual({});
    },
  );
});

describe("themeFromSettings: high contrast is one overlay with two inputs", () => {
  // [appearance.high_contrast, accessibility.increased_contrast, highContrast; undefined means "not in the patch"]
  it.each([
    [true, undefined, true],
    [false, undefined, false],
    [undefined, undefined, undefined],
    [false, "on", true], // the two inputs are OR-ed
    [true, "off", true], // "off" and "system" leave the overlay to appearance.high_contrast
    [true, "system", true],
    [false, "off", false],
    [false, "system", false],
    [undefined, "on", true],
    [undefined, "off", false], // the accessibility subtree spoke; an absent appearance flag counts as off
    [undefined, "system", false],
    ["yes", "maybe", undefined], // neither input is valid
  ])("appearance %j + increased_contrast %j gives %j", (flag, tri, expected) => {
    const settings = loose({
      appearance: flag === undefined ? {} : { high_contrast: flag },
      accessibility: tri === undefined ? {} : { increased_contrast: tri },
    });
    const patch = themeFromSettings(settings);
    if (expected === undefined) expect(patch).not.toHaveProperty("highContrast");
    else expect(patch).toHaveProperty("highContrast", expected);
  });

  it("keeps the base theme: high contrast never touches baseTheme or matchSystem", () => {
    const patch = themeFromSettings(appearance({ theme: "light", high_contrast: true }));
    expect(patch).toStrictEqual({ baseTheme: "light", matchSystem: false, highContrast: true });
  });
});

describe("themeFromSettings: reduced motion precedence", () => {
  // [accessibility.reduced_motion, appearance.reduce_motion, motionOverride; undefined means "not in the patch"]
  it.each([
    ["on", false, "on"], // the tri-state wins in both directions
    ["on", true, "on"],
    ["off", true, "off"],
    ["off", false, "off"],
    ["on", undefined, "on"],
    ["off", undefined, "off"],
    ["system", true, "on"], // the boolean is honoured only while the tri-state is "system"
    ["system", false, "system"], // false stays "system": the OS decides
    ["system", undefined, "system"],
    [undefined, true, "on"],
    [undefined, false, "system"],
    [undefined, undefined, undefined],
    ["maybe", true, "on"], // an invalid tri-state counts as absent
    ["maybe", false, "system"],
    ["maybe", undefined, undefined],
    [undefined, "yes", undefined], // an invalid boolean counts as absent
  ])("reduced_motion %j + reduce_motion %j gives %j", (tri, flag, expected) => {
    const settings = loose({
      accessibility: tri === undefined ? {} : { reduced_motion: tri },
      appearance: flag === undefined ? {} : { reduce_motion: flag },
    });
    const patch = themeFromSettings(settings);
    if (expected === undefined) expect(patch).not.toHaveProperty("motionOverride");
    else expect(patch).toHaveProperty("motionOverride", expected);
  });
});

describe("themeFromSettings: whole payloads", () => {
  it("maps the One writer scenario: system theme, spacious density, high contrast", () => {
    expect(
      themeFromSettings({
        appearance: { theme: "system", density: "spacious", high_contrast: true },
      }),
    ).toStrictEqual({ matchSystem: true, density: "comfortable", highContrast: true });
  });

  it("maps every field of a full payload in one patch", () => {
    expect(
      themeFromSettings({
        appearance: {
          theme: "light",
          density: "compact",
          font_scale: 1.25,
          reduce_motion: true,
          high_contrast: false,
        },
        accessibility: { reduced_motion: "off", increased_contrast: "on" },
      }),
    ).toStrictEqual({
      baseTheme: "light",
      matchSystem: false,
      density: "compact",
      textScale: 125,
      highContrast: true,
      motionOverride: "off",
    });
  });

  it.each([
    undefined,
    {},
    { appearance: undefined },
    loose({ appearance: null, accessibility: null }),
    loose({ appearance: "dark", accessibility: 7 }),
    loose({ appearance: [], accessibility: [] }),
    loose({ appearance: { unrelated: 1 }, accessibility: { verbosity: "high" } }),
  ])("returns an empty patch for %j (nothing to say, so nothing is overwritten)", (settings) => {
    expect(themeFromSettings(settings)).toStrictEqual({});
  });

  it("does not modify its input", () => {
    const input = Object.freeze({
      appearance: Object.freeze({ theme: "light" as const, font_scale: 1.5 }),
      accessibility: Object.freeze({ reduced_motion: "on" as const }),
    });
    expect(() => themeFromSettings(input)).not.toThrow();
  });
});
