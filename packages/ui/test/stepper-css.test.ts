import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(import.meta.dirname, "../src/components");
const CSS = readFileSync(resolve(SRC, "stepper.css"), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");

interface Block {
  readonly selectors: readonly string[];
  readonly body: string;
  readonly index: number;
}

const blocks = (css: string, offset = 0): Block[] =>
  [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
    // Commas inside parentheses (`:not(a, b)`) do not split a selector.
    selectors: (m[1] ?? "").split(/,(?![^(]*\))/).map((s) => s.replace(/\s+/g, " ").trim()),
    body: m[2] ?? "",
    index: offset + m.index,
  }));

const MARK = "@media (forced-colors: active)";
const split = CSS.indexOf(MARK);
const normal = blocks(CSS.slice(0, split));
const forced = blocks(CSS.slice(split + MARK.length).replace(/^\s*\{/, ""), split);

const PAINTS = ["color", "background", "border-color"] as const;
const prop = (b: Block, name: string): string | undefined =>
  new RegExp(`(?:^|[\\s;])${name}\\s*:\\s*([^;]+)`).exec(b.body)?.[1]?.trim();
const rule = (list: Block[], selector: string): Block =>
  list.find((b) => b.selectors.includes(selector)) as Block;
const painting = normal.flatMap((b) =>
  b.selectors
    .map((selector) => [selector, b] as const)
    .filter(() => PAINTS.some((p) => prop(b, p))),
);
const HOVER = ".cv-stepper__btn:hover:not(:disabled, [aria-disabled])";

describe("stepper.css forced-colours cascade", () => {
  it("finds the rules", () => {
    expect(split).toBeGreaterThan(0);
    expect(painting.length).toBeGreaterThan(3);
  });

  // Same selector, later: equal specificity, so the forced rule wins for every property the normal rule paints.
  it.each(painting.map(([s]) => s))("%s has a forced twin that paints the same properties", (s) => {
    const base = painting.find(([name]) => name === s)?.[1] as Block;
    const twins = forced.filter((b) => b.selectors.includes(s));
    expect(twins.length).toBeGreaterThan(0);
    for (const p of PAINTS.filter((name) => prop(base, name) !== undefined)) {
      expect(twins.some((t) => prop(t, p) !== undefined)).toBe(true);
    }
  });

  it("no forced paint uses a token variable", () => {
    for (const b of forced) expect(b.body).not.toContain("var(--color");
  });

  it("hover (which sets the fill and the colour) resets both inside forced colours", () => {
    expect(prop(rule(normal, HOVER), "background")).toContain("--color-surface-hover");
    const hover = rule(forced, HOVER);
    expect(prop(hover, "background")).toBe("ButtonFace");
    expect(prop(hover, "color")).toBe("ButtonText");
    expect(prop(hover, "border-color")).toBe("Highlight");
  });

  it("the states keep the cascade order hover, gated, disabled, in both blocks", () => {
    for (const list of [normal, forced]) {
      expect(rule(list, ".cv-stepper__btn[aria-disabled]").index).toBeGreaterThan(
        rule(list, HOVER).index,
      );
      expect(rule(list, ".cv-stepper__btn:disabled").index).toBeGreaterThan(
        rule(list, ".cv-stepper__btn[aria-disabled]").index,
      );
    }
  });

  it("gated greys the border and keeps ButtonText; disabled greys both and resets the dimming", () => {
    const gated = rule(forced, ".cv-stepper__btn[aria-disabled]");
    expect(prop(gated, "border-color")).toBe("GrayText");
    expect(prop(gated, "color")).toBe("ButtonText");
    const off = rule(forced, ".cv-stepper__btn:disabled");
    expect(prop(off, "border-color")).toBe("GrayText");
    expect(prop(off, "color")).toBe("GrayText");
    expect(prop(off, "opacity")).toBe("1");
    expect(prop(rule(forced, ".cv-stepper__btn"), "forced-color-adjust")).toBe("none");
  });
});

describe("stepper.css rendering", () => {
  it("the value is mono, tabular and end-aligned, on a selector that out-specifies the well", () => {
    const num = rule(normal, ".cv-field__input.cv-field__input--num");
    expect(num.body).toContain("var(--type-num-base-font-family)");
    expect(prop(num, "font-variant-numeric")).toBe("tabular-nums");
    expect(prop(num, "text-align")).toBe("end");
    // `font` resets the variant, so the variant must come after it.
    expect(num.body.indexOf("font-variant-numeric")).toBeGreaterThan(num.body.indexOf("font:"));
  });

  it("the buttons rest in secondary text, tertiary when gated, dimmed when plainly disabled", () => {
    expect(prop(rule(normal, ".cv-stepper__btn"), "color")).toBe("var(--color-text-secondary)");
    expect(prop(rule(normal, ".cv-stepper__btn[aria-disabled]"), "color")).toBe(
      "var(--color-text-tertiary)",
    );
    const off = rule(normal, ".cv-stepper__btn:disabled");
    expect(off.body).toContain("opacity: var(--opacity-disabled)");
    expect(CSS).not.toContain("display: none");
  });
});
