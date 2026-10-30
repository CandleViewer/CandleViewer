import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  describeFaces,
  fontProblems,
  fontSample,
  readTokenFamilies,
  type DrawnFace,
} from "../../vr/fonts.js";

const TOKENS = resolve(import.meta.dirname, "../../tokens/primitives.tokens.json");
const face = (familyName: string, postScriptName: string): DrawnFace => ({
  familyName,
  postScriptName,
  glyphCount: 7,
});
const EXPECTED = { "font.family.ui": "Inter", "font.family.mono": "JetBrains Mono" };

describe("the pinned fonts", () => {
  it("expects the families the token source names, the faces the CI image installs", () => {
    expect(readTokenFamilies(TOKENS)).toEqual(EXPECTED);
  });

  it("asks Chromium to draw each family in a sample of its own, the family quoted", () => {
    const html = fontSample(EXPECTED);
    expect(html).toContain(`id="family-0" style="font: 16px &quot;Inter&quot;"`);
    expect(html).toContain(`id="family-1" style="font: 16px &quot;JetBrains Mono&quot;"`);
  });

  it("passes only when every family draws in exactly its own face", () => {
    const drawn = {
      "font.family.ui": [face("Inter", "Inter-Regular")],
      "font.family.mono": [face("JetBrains Mono", "JetBrainsMono-Regular")],
    };
    expect(fontProblems(EXPECTED, drawn)).toEqual([]);
    expect(describeFaces(drawn)).toBe(
      "font.family.ui Inter (Inter-Regular); font.family.mono JetBrains Mono (JetBrainsMono-Regular)",
    );
  });

  it("names a substitute, a fallback face beside the family and a family that drew nothing", () => {
    const drawn = {
      "font.family.ui": [face("DejaVu Serif", "DejaVuSerif")],
      "font.family.mono": [
        face("JetBrains Mono", "JetBrainsMono-Regular"),
        face("Noto Sans Mono", "NotoSansMono-Regular"),
      ],
    };
    expect(fontProblems(EXPECTED, drawn)).toEqual([
      "font.family.ui draws DejaVu Serif (DejaVuSerif), not Inter",
      "font.family.mono draws JetBrains Mono (JetBrainsMono-Regular), Noto Sans Mono (NotoSansMono-Regular), not JetBrains Mono",
    ]);
    expect(fontProblems(EXPECTED, { "font.family.ui": [] })).toEqual([
      "font.family.ui draws nothing, not Inter",
      "font.family.mono draws nothing, not JetBrains Mono",
    ]);
  });
});
