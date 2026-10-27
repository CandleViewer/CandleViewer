import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const CSS = readFileSync(
  resolve(import.meta.dirname, "../src/components/slider.css"),
  "utf-8",
).replace(/\/\*[\s\S]*?\*\//g, "");
const [normal = "", forced = ""] = CSS.split("@media (forced-colors: active)");

interface Block {
  readonly selectors: readonly string[];
  readonly body: string;
  readonly index: number;
}
const blocks = (css: string): Block[] =>
  [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
    // Split on top-level commas only: `:not(a, b)` is one selector.
    selectors: (m[1] ?? "").split(/,(?![^(]*\))/).map((s) => s.replace(/\s+/g, " ").trim()),
    body: m[2] ?? "",
    index: m.index,
  }));

/** (ids, classes + attributes + pseudo-classes, types); `:not()` counts its most specific argument. */
const specificity = (selector: string): [number, number, number] => {
  let rest = selector;
  let a = 0;
  let b = 0;
  rest = rest.replace(/:not\(([^)]*)\)/g, (_m, inner: string) => {
    b += Math.max(...inner.split(",").map((s) => specificity(s.trim())[1]));
    return "";
  });
  b += (rest.match(/\.[\w-]+|\[[^\]]+\]|:[\w-]+/g) ?? []).length;
  a += (rest.match(/#[\w-]+/g) ?? []).length;
  return [a, b, 0];
};
const weight = (s: string): number => specificity(s)[0] * 100 + specificity(s)[1];

const COLOUR = /(^|[\s;])(background|color|border-color|outline-color|opacity)\s*:/;
const painting = (css: string): Array<{ selector: string; block: Block }> =>
  blocks(css).flatMap((block) =>
    COLOUR.test(block.body) ? block.selectors.map((selector) => ({ selector, block })) : [],
  );

describe("slider.css contract", () => {
  it("forced colours repeat every painting selector with a same-selector rule, later", () => {
    const forcedPaint = painting(forced);
    for (const { selector, block } of painting(normal)) {
      const twin = forcedPaint.filter((f) => f.selector === selector);
      expect(twin.length, `${selector} has no forced-colours twin`).toBeGreaterThan(0);
      for (const prop of ["background", "color", "opacity"]) {
        if (new RegExp(`(^|[\\s;])${prop}\\s*:`).test(block.body)) {
          expect(
            twin.some((f) => new RegExp(`(^|[\\s;])${prop}\\s*:`).test(f.block.body)),
            `${selector} ${prop}`,
          ).toBe(true);
        }
      }
    }
  });

  it("forced colours use system colours only, never a token", () => {
    expect(forced).not.toContain("var(--");
    expect(forced.match(/forced-color-adjust: none/g)).not.toBeNull();
  });

  it("in forced colours disabled is last and never weaker than a rule that can apply with it", () => {
    const paint = painting(forced);
    const isDisabled = (p: { selector: string }): boolean =>
      p.selector.startsWith(".cv-slider[data-disabled]");
    // Hover is written for an enabled slider only (`:not([data-gated], [data-disabled])`).
    const last = (p: { selector: string }): string => p.selector.split(" ").pop() ?? "";
    const others = (d: { selector: string }) =>
      paint.filter((p) => !isDisabled(p) && !p.selector.includes(":not(") && last(p) === last(d));
    const disabled = paint.filter(isDisabled);
    expect(disabled.length).toBeGreaterThan(0);
    for (const d of disabled) {
      for (const other of others(d)) {
        expect(d.block.index, `${d.selector} after ${other.selector}`).toBeGreaterThan(
          other.block.index,
        );
        expect(weight(d.selector), `${d.selector} vs ${other.selector}`).toBeGreaterThanOrEqual(
          weight(other.selector),
        );
      }
    }
  });

  it("in forced colours a plain disabled slider greys every part, and a gated one keeps the thumb", () => {
    const grey = (part: string, prop: string): Block | undefined =>
      blocks(forced).find(
        (b) =>
          b.selectors.includes(`.cv-slider[data-disabled] .cv-slider__${part}`) &&
          b.body.includes(`${prop}: GrayText`),
      );
    expect(grey("track", "background")).toBeDefined();
    expect(grey("fill", "background")).toBeDefined();
    expect(grey("thumb", "background")).toBeDefined();
    expect(grey("mark", "color")).toBeDefined();
    const thumb = blocks(forced).find((b) =>
      b.selectors.includes(".cv-slider[data-gated] .cv-slider__thumb"),
    );
    expect(thumb?.body).toContain("background: ButtonText");
  });

  it("a gated rule out-specifies the base thumb rule, in both modes", () => {
    for (const css of [normal, forced]) {
      const all = painting(css);
      const base = all.find((p) => p.selector === ".cv-slider__thumb");
      const gated = all.find((p) => p.selector === ".cv-slider[data-gated] .cv-slider__thumb");
      expect(weight(gated?.selector ?? "")).toBeGreaterThan(weight(base?.selector ?? ""));
      expect(gated?.block.index).toBeGreaterThan(base?.block.index ?? Infinity);
    }
  });

  it("gated dims only the track (the thumb stays full strength); plain disabled dims the whole control", () => {
    const find = (sel: string): Block | undefined =>
      blocks(normal).find((b) => b.selectors.includes(sel));
    expect(find(".cv-slider[data-gated] .cv-slider__track")?.body).toContain(
      "opacity: var(--opacity-disabled)",
    );
    expect(find(".cv-slider[data-gated] .cv-slider__thumb")?.body).toContain(
      "background: var(--color-text-primary)",
    );
    expect(find(".cv-slider[data-gated] .cv-slider__thumb")?.body).not.toContain("opacity");
    expect(find(".cv-slider[data-disabled]")?.body).toContain("opacity: var(--opacity-disabled)");
  });

  it("hover never applies to a gated or disabled slider", () => {
    const hover = blocks(normal).find((b) => b.selectors.some((s) => s.includes(":hover")));
    expect(hover?.selectors[0]).toContain(":not([data-gated], [data-disabled])");
    expect(hover?.body).toContain("var(--color-text-secondary)");
  });

  it("the whole rail is the pointer target: control height, touch-action none, no pointer-events off", () => {
    const rail = blocks(normal).find((b) => b.selectors.includes(".cv-slider__rail"));
    expect(rail?.body).toContain("height: var(--size-control-height)");
    expect(rail?.body).toContain("touch-action: none");
    expect(CSS).not.toContain("pointer-events");
  });

  it("the slider moves with no transition or animation, so reduced motion is respected by construction", () => {
    expect(CSS).not.toMatch(/transition|animation/);
  });

  it("the lock follows the rail and the marks are not part of the pointer target", () => {
    expect(CSS).toContain(".cv-slider__glyph");
    expect(CSS).toContain(".cv-slider__marks");
  });
});
