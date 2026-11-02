import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("adminlayout.css");
const { normal, forced } = css;
const PILL = ".cv-adminlayout__item > .cv-link";

describe("adminlayout.css contract (CMP-087; E42-D03 §4, §15, board 10 row F)", () => {
  itIsTokenOnlyAndStatic(css);

  it("band: the raised fill, inset.lg, and the 4 px rule as a border of twice border.thick", () => {
    const band = find(normal, ".cv-adminlayout__band", "background");
    expect(band).toContain("background: var(--color-surface-raised)");
    expect(band).toContain("padding: var(--space-inset-lg)");
    expect(band).toContain(
      "border-block-end: calc(var(--border-thick) * 2 * 1px) solid var(--color-text-tertiary)",
    );
    expect(normal).not.toMatch(/background[^;]*--color-text-tertiary/);
    expect(find(normal, ".cv-adminlayout__label", "color")).toContain("var(--color-text-primary)");
    expect(find(normal, ".cv-adminlayout__grace", "color")).toContain(
      "var(--color-text-secondary)",
    );
  });

  it("wraps and never truncates: the band, the strip's flow and each item's text", () => {
    expect(find(normal, ".cv-adminlayout__band", "flex-wrap")).toContain("flex-wrap: wrap");
    expect(find(normal, ".cv-adminlayout__strip", "padding-block")).toContain(
      "var(--space-inset-sm)",
    );
    const item = find(normal, ".cv-adminlayout__item", "margin-inline-end");
    expect(item).toContain("margin-inline-end: var(--space-inset-sm)");
    expect(item).toContain("max-width: 100%");
    expect(find(normal, ".cv-adminlayout__text", "overflow-wrap")).toContain("anywhere");
    expect(css.all).not.toMatch(/text-overflow|line-clamp|overflow:\s*hidden|nowrap/);
  });

  it("items: the tone pill, a control-height target, primary text, no underline", () => {
    const pill = find(normal, PILL, "background");
    expect(pill).toContain("background: var(--cv-adminlayout-fill)");
    expect(pill).toContain("color: var(--color-text-primary)");
    expect(pill).toContain("min-height: var(--size-control-height)");
    expect(pill).toContain("text-decoration-line: none");
    expect(css.all).not.toMatch(/:hover|opacity|cursor/);
  });

  it.each([
    ["", "warning"],
    ['[data-severity="critical"]', "danger"],
    ['[data-severity="info"]', "info"],
  ])("tone %s: the %s subtle fill and its strong glyph (warning by default)", (attr, tone) => {
    const block = find(normal, `.cv-adminlayout__item${attr}`, "--cv-adminlayout-fill");
    expect(block).toContain(`--cv-adminlayout-fill: var(--color-status-${tone}-subtle)`);
    expect(block).toContain(`--cv-adminlayout-strong: var(--color-status-${tone}-strong)`);
  });

  it.each([
    ["live", "var(--color-env-live)"],
    ["demo", "var(--color-env-demo)"],
  ])("environment badge %s: a class modifier that sets the border colour token", (env, token) => {
    const block = find(normal, `.cv-adminlayout__env--${env}`, "border-color");
    expect(block).toContain(`border-color: ${token}`);
  });

  it("puts the environment modifiers after the badge's border shorthand, which would reset them", () => {
    // A class modifier ties the base rule on specificity, so the later declaration wins.
    const base = normal.indexOf(".cv-adminlayout__env {");
    expect(base).toBeGreaterThan(-1);
    for (const env of ["live", "demo"])
      expect(normal.indexOf(`.cv-adminlayout__env--${env} {`)).toBeGreaterThan(base);
  });

  it("names no selector the top bar's badge guard rejects: no CMP-074/075, data-env, EnvBadge", () => {
    // The scan and the pattern are top-bar.test.tsx's "has no hide path" (the environment badge has no
    // hide path, so no shipped selector may name it or its attribute); this sheet's modifiers are classes.
    const selectors = (css.all.match(/[^{}]+(?=\{)/g) ?? []).map((s) =>
      s.replace(/\s+/g, " ").trim(),
    );
    expect(selectors).toEqual(
      expect.arrayContaining([".cv-adminlayout__env--live", ".cv-adminlayout__env--demo"]),
    );
    for (const selector of selectors) expect(selector).not.toMatch(/CMP-07[45]|data-env|EnvBadge/);
  });

  it("forced colours: the rule is a CanvasText border, pills keep an edge, fills drop", () => {
    expect(find(forced, ".cv-adminlayout__band", "border-block-end-color")).toContain("CanvasText");
    expect(find(forced, PILL, "border-color")).toContain("border-color: LinkText");
    expect(find(forced, ".cv-adminlayout__env", "border-color")).toContain("CanvasText");
    expect(css.all).not.toMatch(/forced-color-adjust/);
    expect(forced).not.toMatch(/background/);
  });
});
