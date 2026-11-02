import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("systemhealthtile.css");

/** [sheet, selector after `.cv-health-tile`, property, ...what its block holds]. */
const RULES: [keyof typeof css, string, string, ...string[]][] = [
  ["normal", "", "display", "display: grid"],
  ["normal", "__body", "overflow-wrap", "overflow-wrap: anywhere"],
  ["normal", "__state", "color", "color: var(--color-text-primary)"],
  ["normal", '__glyph[data-tone="ok"]', "color", "var(--color-status-success-strong)"],
  ["normal", '__glyph[data-tone="warning"]', "color", "var(--color-status-warning-strong)"],
  ["normal", '__glyph[data-tone="danger"]', "color", "var(--color-status-danger-strong)"],
  ["normal", '__glyph[data-tone="stale"]', "color", "var(--color-data-confidence-stale-indicator)"],
  ["normal", '__glyph[data-tone="neutral"]', "color", "var(--color-neutral-default)"],
  ["normal", "__glyph", "width", "width: var(--size-icon)"],
  ["normal", "__ring", "border", "calc(var(--border-hairline) * 1px) solid currentcolor"],
  ["normal", "__ring", "border-radius", "border-radius: var(--radius-circle)"],
  ["normal", "__number", "font", "--type-num-base-font-family", "--color-text-primary"],
  ["normal", "__meta", "font", "--type-ui-caption-font-size", "--color-text-tertiary"],
  ["normal", "__hint", "color", "color: var(--color-text-secondary)"],
  ["normal", "__env", "border", "solid var(--color-border-strong)", "var(--radius-badge)"],
  ["normal", "__env", "font", "--type-ui-caption-font-size", "color: var(--color-text-primary)"],
  ["normal", "__env--live", "border-color", "border-color: var(--color-env-live)"],
  ["normal", "__env--demo", "border-color", "border-color: var(--color-env-demo)"],
  ["forced", "__glyph[data-tone]", "color", "color: CanvasText"],
  ["forced", "__meta", "color", "color: CanvasText"],
  ["forced", "__env", "border-color", "border-color: CanvasText", "color: CanvasText"],
];

describe("systemhealthtile.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it.each(RULES)("%s .cv-health-tile%s sets %s", (sheet, selector, prop, ...want) => {
    const block = find(css[sheet], `.cv-health-tile${selector}`, prop);
    want.forEach((w) => expect(block).toContain(w));
  });

  it("puts the environment modifiers after the badge's border shorthand, which would reset them", () => {
    // A class modifier ties the base rule on specificity, so the later declaration wins.
    const base = css.normal.indexOf(".cv-health-tile__env {");
    expect(base).toBeGreaterThan(-1);
    for (const env of ["live", "demo"])
      expect(css.normal.indexOf(`.cv-health-tile__env--${env} {`)).toBeGreaterThan(base);
  });

  it("names no selector the top bar's badge guard rejects: no CMP-074/075, data-env, EnvBadge", () => {
    // The scan and the pattern are top-bar.test.tsx's "has no hide path" (the environment badge has no
    // hide path, so no shipped selector may name it or its attribute); this sheet's modifiers are classes.
    const selectors = (css.all.match(/[^{}]+(?=\{)/g) ?? []).map((s) =>
      s.replace(/\s+/g, " ").trim(),
    );
    expect(selectors).toEqual(
      expect.arrayContaining([".cv-health-tile__env--live", ".cv-health-tile__env--demo"]),
    );
    for (const selector of selectors) expect(selector).not.toMatch(/CMP-07[45]|data-env|EnvBadge/);
  });

  it("shows a loading tile's words in forced colours only, where CMP-015's fills drop", () => {
    // Normal media keeps them visually hidden, so no pixel moves outside forced colours.
    expect(css.normal).not.toContain("__loading");
    // Forced colours undo the clip pattern part by part (its zero padding and border can stay), on
    // two classes, which outrank `.cv-visually-hidden` whatever order the stylesheets load in.
    const hidden = find(loadCss("controls.css").normal, ".cv-visually-hidden", "clip-path");
    const parts = [...hidden.matchAll(/([a-z-]+)\s*:/g)].map((m) => m[1] ?? "");
    expect(parts).toEqual(expect.arrayContaining(["position", "clip-path", "white-space"]));
    const shown = find(css.forced, ".cv-health-tile__loading.cv-visually-hidden", "clip-path");
    for (const prop of parts.filter((p) => p !== "padding" && p !== "border"))
      expect(shown, prop).toMatch(new RegExp(`(^|[\\s;])${prop}\\s*:`));
    for (const value of ["position: static", "clip-path: none", "overflow: visible"])
      expect(shown).toContain(value);
  });

  it("wraps and never truncates: no ellipsis, clamp or clipping", () => {
    expect(css.all).not.toMatch(/text-overflow|line-clamp|overflow:\s*hidden/);
  });
});
