import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(import.meta.dirname, "../src/components");
const CSS = readFileSync(resolve(SRC, "fields.css"), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");

interface Block {
  readonly selectors: readonly string[];
  readonly body: string;
  readonly index: number;
}

function blocks(css: string, offset = 0): Block[] {
  return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
    // Split on commas outside parentheses: `:not(a, b)` is one selector.
    selectors: (m[1] ?? "").split(/,(?![^(]*\))/).map((s) => s.replace(/\s+/g, " ").trim()),
    body: m[2] ?? "",
    index: offset + m.index,
  }));
}

const MARK = "@media (forced-colors: active)";
const split = CSS.indexOf(MARK);
const normal = blocks(CSS.slice(0, split));
// The media wrapper's own `{` swallows the first rule in a flat scan: strip it before reading the rules.
const forced = blocks(CSS.slice(split + MARK.length).replace(/^\s*\{/, ""), split);

/** Declarations that paint: a forced-colours leak is any of these surviving without a system-colour twin. */
const PAINT = /(^|[\s;])(color|background|border-color)\s*:/;
const paints = (b: Block): boolean => PAINT.test(b.body);
const forcedFor = (selector: string): Block[] =>
  forced.filter((b) => b.selectors.includes(selector));
const prop = (b: Block, name: string): string | undefined =>
  new RegExp(`(?:^|[\\s;])${name}\\s*:\\s*([^;]+)`).exec(b.body)?.[1]?.trim();

describe("fields.css forced-colours cascade", () => {
  const painting = normal.filter(paints).flatMap((b) => b.selectors.map((s) => [s, b] as const));

  it("finds the normal rules and the forced block", () => {
    expect(split).toBeGreaterThan(0);
    expect(painting.length).toBeGreaterThan(8);
    expect(forced.length).toBeGreaterThan(8);
  });

  // A forced rule with the same selector has the same specificity and sits later, so it wins the cascade.
  it.each(painting.map(([s]) => s))("%s has a forced twin with the same selector", (selector) => {
    const normalBlock = painting.find(([s]) => s === selector)?.[1] as Block;
    // `inherit` and `transparent` carry no token colour: nothing to leak.
    const leaking = ["color", "background", "border-color"].filter((name) => {
      const value = prop(normalBlock, name);
      return value !== undefined && !["inherit", "transparent"].includes(value);
    });
    const twins = forcedFor(selector);
    if (leaking.length === 0) return;
    expect(twins.length).toBeGreaterThan(0);
    for (const name of leaking) expect(twins.some((t) => prop(t, name) !== undefined)).toBe(true);
  });

  it("no forced paint uses a token variable", () => {
    for (const b of forced.filter(paints)) expect(b.body).not.toContain("var(--color");
  });

  it("forced state rules keep the normal cascade order (invalid, gated, disabled)", () => {
    const order = (list: Block[], sel: string): number =>
      list.find((b) => b.selectors.includes(sel))?.index ?? -1;
    for (const list of [normal, forced]) {
      const inv = order(list, ".cv-field[data-invalid]");
      const gated = order(list, ".cv-field[data-gated]");
      const dis = order(list, ".cv-field[data-disabled]");
      expect(inv).toBeGreaterThan(order(list, ".cv-field[data-readonly]"));
      expect(gated).toBeGreaterThan(inv);
      expect(dis).toBeGreaterThan(gated);
    }
  });

  it("gated greys the border by hand, keeps the value FieldText; disabled greys both", () => {
    const gated = forcedFor(".cv-field[data-gated]")[0] as Block;
    expect(prop(gated, "border-color")).toBe("GrayText");
    expect(prop(gated, "color")).toBe("FieldText");
    const off = forcedFor(".cv-field[data-disabled]")[0] as Block;
    expect(prop(off, "border-color")).toBe("GrayText");
    expect(prop(off, "color")).toBe("GrayText");
    expect(prop(off, "opacity")).toBe("1");
  });

  it("the focus ring and hover step to Highlight", () => {
    expect(prop(forcedFor(".cv-field:focus-within")[0] as Block, "outline-color")).toBe(
      "Highlight",
    );
    const hover = forcedFor(
      ".cv-field:hover:not([data-gated], [data-readonly], [data-disabled], [data-invalid])",
    );
    expect(prop(hover[0] as Block, "border-color")).toBe("Highlight");
  });
});

describe("fields.css well", () => {
  const rule = (selector: string): Block =>
    normal.find((b) => b.selectors.includes(selector)) as Block;

  it("invalid is a 2px thick-token boundary in danger, padding compensated", () => {
    const invalid = rule(".cv-field[data-invalid]");
    expect(invalid.body).toContain("--cv-field-bw: calc(var(--border-thick) * 1px)");
    expect(invalid.body).toContain("border-color: var(--color-status-danger-default)");
    expect(rule(".cv-field").body).toContain("--cv-field-pad: calc(var(--space-inset-sm) - ");
  });

  it("gated is a raised well with tertiary text, never opacity.disabled", () => {
    const gated = rule(".cv-field[data-gated]");
    expect(gated.body).toContain("background: var(--color-surface-raised)");
    expect(gated.body).toContain("color: var(--color-text-tertiary)");
    expect(gated.body).not.toContain("opacity");
  });

  it("an empty message line takes no room, and is never display:none (it is a live region)", () => {
    expect(rule(".cv-field__message:not(:empty)").body).toContain("padding-block-start");
    expect(CSS).not.toContain("display: none");
  });
});
