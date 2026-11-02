/**
 * The no-hue-alone check (E47-S02, #1358; `05` §4, SC 1.4.1): a state passes when, with every colour removed, a
 * sighted user still sees a channel (text, a glyph, a drawn pattern) and no two states of one surface look alike.
 *
 * Two signatures, kept apart (lens r1 code m6 / a11y M-3):
 * - visual: the rendered text, glyphs included (`aria-hidden` hides from AT, not from the eye), minus visually hidden
 *   text, plus each `data-cv-pattern` only when the stylesheet really draws it for that element. This is the one the
 *   check compares. An `aria-label` never reaches a sighted user, so it is not in it.
 * - AT: the accessible names (`aria-label`s); assert it separately where the name must differ too.
 *
 * jsdom has no layout or computed colour, so a difference drawn only by CSS colour cannot be seen here: the Playwright
 * grayscale snapshot on the mounted screens (SCR-050..056) stays a carried gate; this helper is its unit-level twin.
 */
import { expect } from "vitest";

const HIDDEN = "cv-visually-hidden";

function visibleText(el: Element): string {
  let text = "";
  for (const node of el.childNodes) {
    if (node.nodeType === 3) text += node.textContent ?? "";
    else if (node instanceof Element && !node.classList.contains(HIDDEN)) text += visibleText(node);
  }
  return text;
}

/** The rule declarations for `.cls` in `css` (comments stripped). */
function declarationsFor(css: string, cls: string): string[] {
  const bare = css.replace(/\/\*[\s\S]*?\*\//g, "");
  return [...bare.matchAll(/([^{}]+)\{([^}]*)\}/g)]
    .filter((m) => (m[1] ?? "").split(",").some((sel) => sel.trim() === `.${cls}`))
    .map((m) => m[2] ?? "");
}

/** What a sighted user sees without colour. Throws when a declared pattern is not drawn by `css`. */
export function visualSignature(el: Element, css = ""): string {
  const parts: string[] = [visibleText(el).trim()];
  for (const node of [el, ...el.querySelectorAll("[data-cv-pattern]")]) {
    const pattern = node.getAttribute("data-cv-pattern");
    if (pattern === null) continue;
    const drawn = [...node.classList].some((cls) =>
      declarationsFor(css, cls).some((d) => d.includes(pattern)),
    );
    if (!drawn) throw new Error(`pattern "${pattern}" is declared but not drawn by the stylesheet`);
    parts.push(`pattern:${pattern}`);
  }
  return parts.filter((p) => p !== "").join("|");
}

/** What AT hears beyond the text: the subtree's `aria-label`s. */
export function atSignature(el: Element): string {
  return [el, ...el.querySelectorAll("[aria-label]")]
    .map((node) => node.getAttribute("aria-label"))
    .filter((label): label is string => label !== null)
    .join("|");
}

/** Asserts every named state is seen without colour and looks different from every other. */
export function expectNoHueAlone(
  surface: string,
  states: Readonly<Record<string, Element>>,
  css = "",
): void {
  const seen = new Map<string, string>();
  for (const [name, el] of Object.entries(states)) {
    const signature = visualSignature(el, css);
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
