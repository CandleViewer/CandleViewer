/**
 * The no-hue-alone check (E47-S02, #1358; `05` §4): a state passes when, with every colour removed, it still carries
 * a channel (text, a glyph, an accessible name or a declared pattern) and no two states of one surface collapse to
 * the same colourless rendering. Colour lives only in class names and CSS, so the colourless rendering is the text
 * content (glyphs included), the `aria-label`s and the `data-cv-pattern`s of the subtree. The Playwright gate on the
 * mounted screens (SCR-050..056) is a carried row; this helper is its unit-level twin.
 */
import { expect } from "vitest";

export function colourless(el: Element): string {
  const parts: string[] = [(el.textContent ?? "").trim()];
  for (const node of [el, ...el.querySelectorAll("*")]) {
    const label = node.getAttribute("aria-label");
    if (label !== null) parts.push(`label:${label}`);
    const pattern = node.getAttribute("data-cv-pattern");
    if (pattern !== null) parts.push(`pattern:${pattern}`);
  }
  return parts.filter((p) => p !== "").join("|");
}

/** Asserts every named state carries a non-colour channel and differs from every other without colour. */
export function expectNoHueAlone(surface: string, states: Readonly<Record<string, Element>>): void {
  const seen = new Map<string, string>();
  for (const [name, el] of Object.entries(states)) {
    const signature = colourless(el);
    expect(signature, `${surface}/${name}: no non-colour channel`).not.toBe("");
    const twin = seen.get(signature);
    expect(twin, `${surface}/${name} differs from ${twin ?? ""} by colour alone`).toBeUndefined();
    seen.set(signature, name);
  }
}

/** The rule for `selector` in `css` declares `pattern` (e.g. a dashed border): the pattern is drawn, not just named. */
export function expectCssPattern(css: string, selector: string, pattern: RegExp): void {
  const bare = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules = [...bare.matchAll(/([^{}]+)\{([^}]*)\}/g)].filter((m) =>
    (m[1] ?? "").split(",").some((s) => s.trim() === selector),
  );
  expect(rules.length, `no rule for ${selector}`).toBeGreaterThan(0);
  expect(rules.some((m) => pattern.test(m[2] ?? ""))).toBe(true);
}
