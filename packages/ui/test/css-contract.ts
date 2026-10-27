import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";

/** A component stylesheet without comments, split at its forced-colours block. */
export interface Stylesheet {
  readonly all: string;
  readonly normal: string;
  readonly forced: string;
}

export const loadCss = (file: string): Stylesheet => {
  const all = readFileSync(
    resolve(import.meta.dirname, "../src/components", file),
    "utf-8",
  ).replace(/\/\*[\s\S]*?\*\//g, "");
  const [normal = "", forced = ""] = all.split("@media (forced-colors: active)");
  return { all, normal, forced };
};

/**
 * The body of the first block whose selector list includes `selector` and which sets `prop`, as the
 * merged atoms' CSS tests read it: the list splits on top-level commas only (`:not(a, b)` is one selector).
 */
export const find = (css: string, selector: string, prop: string): string => {
  for (const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selectors = (m[1] ?? "").split(/,(?![^(]*\))/).map((s) => s.replace(/\s+/g, " ").trim());
    if (selectors.includes(selector) && new RegExp(`(^|[\\s;])${prop}\\s*:`).test(m[2] ?? ""))
      return m[2] ?? "";
  }
  return "";
};

/**
 * The static-atom baseline: tokens only and no motion. Outside forced colours px appears only as a token
 * multiplier; inside, the literal 1px / 2px system-colour edges are allowed, as in the merged atoms.
 */
export const itIsTokenOnlyAndStatic = (css: Stylesheet): void => {
  it("binds tokens only: no raw colour, and raw px only for forced-colours edges", () => {
    expect(css.normal).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i);
    expect(css.normal.replace(/\* 1px/g, "")).not.toMatch(/\d+px/);
    expect(css.forced.replace(/\* 1px|\b[12]px\b/g, "")).not.toMatch(/\d+px/);
  });
  it("is static: no transition or animation, so reduced motion holds by construction", () => {
    expect(css.all).not.toMatch(/transition|animation/);
  });
};
