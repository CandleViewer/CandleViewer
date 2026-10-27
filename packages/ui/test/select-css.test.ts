import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(import.meta.dirname, "../src/components");
const read = (name: string): string =>
  readFileSync(resolve(SRC, name), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");
const CSS = read("select.css");

interface Block {
  readonly selectors: readonly string[];
  readonly body: string;
  readonly index: number;
}

function blocks(css: string, offset = 0): Block[] {
  return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
    selectors: (m[1] ?? "").split(/,(?![^(]*\))/).map((s) => s.replace(/\s+/g, " ").trim()),
    body: m[2] ?? "",
    index: offset + m.index,
  }));
}

const MARK = "@media (forced-colors: active)";
const split = CSS.indexOf(MARK);
const normal = blocks(CSS.slice(0, split)).filter((b) => !b.selectors[0]?.startsWith("@"));
const forced = blocks(CSS.slice(split + MARK.length).replace(/^\s*\{/, ""), split);
const PAINT = /(^|[\s;])(color|background|border-color)\s*:/;
const prop = (b: Block, name: string): string | undefined =>
  new RegExp(`(?:^|[\\s;])${name}\\s*:\\s*([^;]+)`).exec(b.body)?.[1]?.trim();
const rule = (list: Block[], selector: string): Block =>
  list.find((b) => b.selectors.includes(selector)) as Block;
const twins = (selector: string): Block[] => forced.filter((b) => b.selectors.includes(selector));

describe("select.css forced-colours cascade", () => {
  const painting = normal
    .filter((b) => PAINT.test(b.body))
    .flatMap((b) => b.selectors.map((s) => [s, b] as const));

  it("finds the rules and the forced block", () => {
    expect(split).toBeGreaterThan(0);
    expect(painting.length).toBeGreaterThanOrEqual(5);
    expect(forced.length).toBeGreaterThanOrEqual(6);
  });

  // Same selector, later in the file: equal specificity, so the forced rule wins the cascade.
  it.each(painting.map(([s]) => s))("%s has a forced twin with the same selector", (selector) => {
    const block = painting.find(([s]) => s === selector)?.[1] as Block;
    for (const name of ["color", "background", "border-color"]) {
      const value = prop(block, name);
      if (value === undefined || ["inherit", "transparent"].includes(value)) continue;
      expect(twins(selector).some((t) => prop(t, name) !== undefined)).toBe(true);
    }
  });

  it("no forced paint uses a token variable, and every twin comes after its normal rule", () => {
    for (const b of forced.filter((x) => PAINT.test(x.body))) {
      expect(b.body).not.toContain("var(--color");
    }
    for (const [selector, block] of painting) {
      for (const t of twins(selector)) expect(t.index).toBeGreaterThan(block.index);
    }
  });

  it("the active option is Highlight on HighlightText; disabled is GrayText at full opacity, and wins", () => {
    const active = twins(".cv-select__option[data-active]")[0] as Block;
    expect(prop(active, "background")).toBe("Highlight");
    expect(prop(active, "color")).toBe("HighlightText");
    const off = twins('.cv-select__option[aria-disabled="true"]')[0] as Block;
    expect(prop(off, "color")).toBe("GrayText");
    expect(prop(off, "opacity")).toBe("1");
    for (const list of [normal, forced]) {
      expect(rule(list, '.cv-select__option[aria-disabled="true"]').index).toBeGreaterThan(
        rule(list, ".cv-select__option[data-active]").index,
      );
    }
  });

  it("the popup keeps a real border and sets system colours by hand", () => {
    const popup = twins(".cv-select__popup")[0] as Block;
    expect(prop(popup, "border-color")).toBe("CanvasText");
    expect(prop(popup, "background")).toBe("Canvas");
    expect(prop(popup, "forced-color-adjust")).toBe("none");
  });

  it("the placeholder and a disabled chevron grey; the lock and chevron are FieldText otherwise", () => {
    expect(prop(twins(".cv-select__value[data-placeholder]")[0] as Block, "color")).toBe(
      "GrayText",
    );
    expect(prop(twins(".cv-field[data-disabled] .cv-select__chevron")[0] as Block, "color")).toBe(
      "GrayText",
    );
    expect(prop(twins(".cv-select__lock")[0] as Block, "color")).toBe("FieldText");
  });
});

describe("select.css popup", () => {
  const popup = rule(normal, ".cv-select__popup");

  it("uses the overlay surface, popover shadow and card radius, never a raw colour", () => {
    expect(popup.body).toContain("background: var(--color-surface-overlay)");
    expect(popup.body).toContain("box-shadow: var(--elevation-popover)");
    expect(popup.body).toContain("border-radius: var(--radius-card)");
    expect(CSS).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(/i);
  });

  it("is at most ten rows tall then scrolls, at least the field's width", () => {
    expect(popup.body).toMatch(/max-block-size:\s*calc\(\s*10 \* var\(--size-row-height\)/);
    expect(popup.body).toContain("overflow-y: auto");
    expect(popup.body).toContain("min-inline-size: 100%");
  });

  it("is absolute under a relative anchor and clears the focus ring on both sides", () => {
    expect(rule(normal, ".cv-select__anchor").body).toContain("position: relative");
    expect(popup.body).toContain("position: absolute");
    expect(popup.body).toContain("(var(--border-focus) + 2) * 1px");
    expect(rule(normal, '.cv-select__popup[data-placement="below"]').body).toContain(
      "top: calc(100% + var(--cv-select-gap))",
    );
    expect(rule(normal, '.cv-select__popup[data-placement="above"]').body).toContain(
      "bottom: calc(100% + var(--cv-select-gap))",
    );
  });

  it("fades only when motion is allowed, over the fast token", () => {
    const raw = readFileSync(resolve(SRC, "select.css"), "utf-8");
    expect(raw).toMatch(
      /prefers-reduced-motion: no-preference\)\s*\{[^@]*var\(--motion-duration-fast\)/,
    );
  });

  it("no hover rule exists: the pointer moves the active option, so the highlight and aria agree", () => {
    expect(CSS).not.toContain(":hover");
  });
});
