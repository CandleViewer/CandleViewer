import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(import.meta.dirname, "../src/components");
const strip = (css: string): string => css.replace(/\/\*[\s\S]*?\*\//g, "");
const CSS = strip(readFileSync(resolve(SRC, "focusring.css"), "utf-8"));
const [normal = "", forced = ""] = CSS.split("@media (forced-colors: active)");

const rules = (css: string): { selectors: string[]; body: string }[] =>
  [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
    selectors: (m[1] ?? "").split(",").map((s) => s.replace(/\s+/g, " ").trim()),
    body: m[2] ?? "",
  }));
const body = (css: string, selector: string): string =>
  rules(css)
    .filter((r) => r.selectors.includes(selector))
    .map((r) => r.body)
    .join(";");

describe("focusring.css contract (CMP-039)", () => {
  it("draws the ring on :focus-visible only, never on :focus or :focus-within", () => {
    const ringRules = rules(CSS).filter((r) => /outline/.test(r.body));
    expect(ringRules.length).toBeGreaterThan(0);
    for (const rule of ringRules)
      for (const selector of rule.selectors) expect(selector).toMatch(/:focus-visible(?![\w-])/);
    expect(CSS).not.toMatch(/:focus(?!-visible)/);
  });

  it("is a 2px outline of the focus-ring colour at the border.focus width and a 2px offset", () => {
    const ring = body(normal, ".cv-focus-ring:focus-visible");
    expect(ring).toContain(
      "outline: calc(var(--border-focus) * 1px) solid var(--color-focus-ring)",
    );
    expect(ring).toContain("outline-offset: 2px");
    // The control foundation and the delegated host / target form share the same declaration.
    expect(body(normal, ".cv-control:focus-visible")).toBe(ring);
    expect(body(normal, ".cv-focus-ring-host:focus-visible .cv-focus-ring-target")).toBe(ring);
  });

  it("the inset variant moves the same ring inside the element's bounds", () => {
    const inset = body(normal, ".cv-focus-ring--inset:focus-visible");
    expect(inset).toContain("outline-offset: calc(var(--border-focus) * -1px)");
    expect(inset).not.toContain("outline-color");
  });

  it("is a real outline (forced colours keep it), never a box-shadow; tokens only", () => {
    expect(CSS).not.toContain("box-shadow");
    expect(CSS).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(/i);
    expect(CSS).not.toMatch(/outline\s*:\s*(none|0)\b/);
  });

  it("forced colours: Highlight for every ring form, system colours only", () => {
    expect(forced).not.toMatch(/var\(--/);
    for (const selector of [
      ".cv-focus-ring:focus-visible",
      ".cv-control:focus-visible",
      ".cv-focus-ring-host:focus-visible .cv-focus-ring-target",
    ])
      expect(body(forced, selector)).toContain("outline-color: Highlight");
  });

  it("the merged atoms no longer define a ring of their own", () => {
    for (const file of ["controls.css", "radio.css"]) {
      const css = strip(readFileSync(resolve(SRC, file), "utf-8"));
      expect(css, file).not.toContain("--color-focus-ring");
      expect(css, file).not.toContain("outline-offset");
    }
  });
});
