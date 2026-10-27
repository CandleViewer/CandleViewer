import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const CSS = readFileSync(
  resolve(import.meta.dirname, "../src/components/typography.css"),
  "utf-8",
).replace(/\/\*[\s\S]*?\*\//g, "");
const MARK = "@media (forced-colors: active)";
const normal = CSS.slice(0, CSS.indexOf(MARK));
const forced = CSS.slice(CSS.indexOf(MARK) + MARK.length);

const blocks = (css: string): Array<{ selectors: string[]; body: string }> =>
  [...css.replace(/^\s*\{/, "").matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
    selectors: (m[1] ?? "").split(/,(?![^(]*\))/).map((s) => s.replace(/\s+/g, " ").trim()),
    body: m[2] ?? "",
  }));

describe("typography.css contract", () => {
  // The AC "tabular numerics enforced centrally": the component's own class sets them for every size.
  it("sets tabular-nums on the NumericText and MonoText base rule", () => {
    const base = blocks(normal).find((b) => b.selectors.includes(".cv-num"));
    expect(base?.selectors).toContain(".cv-mono");
    expect(base?.body).toMatch(/font-variant-numeric:\s*tabular-nums/);
  });

  it("never uses the font shorthand on numbers, which would reset font-variant-numeric", () => {
    for (const b of blocks(normal).filter((x) =>
      x.selectors.some((s) => /cv-(num|mono)/.test(s)),
    )) {
      expect(b.body, b.selectors.join()).not.toMatch(/(^|[\s;])font\s*:/);
      expect(b.body).not.toMatch(/font-variant-numeric:\s*normal/);
    }
  });

  it("binds every type.num step and every type.ui role", () => {
    for (const step of ["xs", "sm", "base", "md", "lg", "xl"]) {
      expect(normal).toContain(`--type-num-${step}-font-size`);
    }
    for (const role of ["caption", "body", "body-strong", "label"]) {
      expect(normal).toContain(`--type-ui-${role}-font-size`);
    }
    for (const role of ["heading-sm", "heading-md", "heading-lg", "display"]) {
      expect(normal).toContain(`--type-ui-${role}-font-size`);
    }
  });

  it("colours by sign with the .default tokens (E1 interim)", () => {
    expect(normal).toMatch(/\[data-sign="positive"\]\s*\{\s*color:\s*var\(--color-buy-default\)/);
    expect(normal).toMatch(/\[data-sign="negative"\]\s*\{\s*color:\s*var\(--color-sell-default\)/);
    expect(normal).toMatch(/\[data-sign="zero"\]\s*\{\s*color:\s*var\(--color-neutral-default\)/);
  });

  it("uses tokens only: no raw colour or pixel values", () => {
    expect(normal).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|\d+px/i);
  });

  it("gives every colouring selector a CanvasText twin in forced colours, with no tokens", () => {
    expect(forced).not.toContain("var(--");
    const twins = blocks(forced).flatMap((b) => (/CanvasText/.test(b.body) ? b.selectors : []));
    for (const b of blocks(normal).filter((x) => /(^|[\s;])color\s*:/.test(x.body))) {
      for (const s of b.selectors) expect(twins, s).toContain(s);
    }
  });
});
