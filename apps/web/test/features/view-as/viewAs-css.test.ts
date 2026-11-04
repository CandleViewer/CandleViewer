import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * E42-S03 (SCR-124; E42-D03 §10, §15, D24 F2): the colour rules `viewAs.css` adds, read as text,
 * as `packages/ui/test/button-css.test.ts` reads CMP-001's. jsdom computes no styles and the
 * real-browser contrast gate renders no view-as context before part 5, so this is their guard:
 * Exit's 1 px border (its fill alone is 2.72:1 on the dark banner) and that border's forced-colours
 * twin, which must out-rank CMP-001's own rule there, Exit's hover and press cue there (CMP-001's
 * `Highlight`, which the twin would out-rank too), and the 5:00 and 1:00 glyph colours.
 */
const CSS = readFileSync(
  resolve(import.meta.dirname, "../../../src/features/view-as/viewAs.css"),
  "utf-8",
).replace(/\/\*[\s\S]*?\*\//g, "");
const [normal = "", forced = ""] = CSS.split("@media (forced-colors: active)");

interface Block {
  readonly selectors: readonly string[];
  readonly body: string;
}

function blocks(css: string): Block[] {
  return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
    selectors: (m[1] ?? "").split(",").map((s) => s.replace(/\s+/g, " ").trim()),
    body: m[2] ?? "",
  }));
}

/** The declarations of `prop` under `selector`, in source order. */
const values = (css: string, selector: string, prop: string): string[] =>
  blocks(css)
    .filter((b) => b.selectors.includes(selector))
    .flatMap((b) => [...b.body.matchAll(new RegExp(`(?:^|;)\\s*${prop}\\s*:\\s*([^;]+)`, "g"))])
    .map((m) => (m[1] ?? "").trim());

describe("viewAs.css contract", () => {
  it("Exit: a 1 px text.primary border on CMP-001's primary fill (D24 F2)", () => {
    expect(values(normal, ".cv-view-as__exit .cv-button", "border-color")).toEqual([
      "var(--color-text-primary)",
    ]);
  });

  it("forced colours: Exit's border is ButtonText, the same selector after CMP-001's own rule", () => {
    // CMP-001 opts out of forcing (`forced-color-adjust: none`) at (0,2,0); the banner's rule ties it
    // and loads later, so without its own forced-colours rule a theme token would be drawn there
    expect(values(forced, ".cv-view-as__exit .cv-button", "border-color")).toEqual(["ButtonText"]);
    expect(CSS.indexOf("@media (forced-colors: active)")).toBeGreaterThan(
      CSS.indexOf(".cv-view-as__exit .cv-button"),
    );
  });

  it("forced colours: Exit's hover and press border is Highlight, CMP-001's own cue there", () => {
    // CMP-001's `.cv-button:hover, .cv-button:active` is (0,2,0): the banner's ButtonText rule ties
    // it and, loading later, wins, so only the banner's own (0,3,0) rule keeps the cue
    for (const state of [":hover", ":active"])
      expect(values(forced, `.cv-view-as__exit .cv-button${state}`, "border-color")).toEqual([
        "Highlight",
      ]);
  });

  it("the 5:00 and 1:00 glyphs: the warning and danger strong tokens, nothing else", () => {
    expect(values(normal, '.cv-view-as__glyph[data-glyph="warning"]', "color")).toEqual([
      "var(--color-status-warning-strong)",
    ]);
    expect(values(normal, '.cv-view-as__glyph[data-glyph="danger"]', "color")).toEqual([
      "var(--color-status-danger-strong)",
    ]);
  });

  it("uses tokens only outside forced colours: no hex, rgb or named colour", () => {
    expect(normal).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i);
    for (const m of normal.matchAll(/(?:color|background|border(?:-[a-z-]+)?):\s*([^;]+);/g))
      expect(m[1]).toMatch(/var\(--|transparent|^\d+px solid var\(--/);
  });
});
