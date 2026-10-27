import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(import.meta.dirname, "../src/components");
const CSS = readFileSync(resolve(SRC, "segmented.css"), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");
const [normal = "", forced = ""] = CSS.split("@media (forced-colors: active)");

interface Block {
  readonly selector: string;
  readonly body: string;
  readonly at: number;
}
const parse = (css: string): Block[] =>
  [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].flatMap((m, at) =>
    (m[1] ?? "")
      .split(/,(?![^(]*\))/)
      .map((s) => ({ selector: s.replace(/\s+/g, " ").trim(), body: m[2] ?? "", at })),
  );
const NORMAL = parse(normal);
const FORCED = parse(forced);

type Spec = readonly [number, number, number];
const cmp = (x: Spec, y: Spec): number => x[0] - y[0] || x[1] - y[1] || x[2] - y[2];
function specificity(selector: string): Spec {
  let [a, b, c] = [0, 0, 0];
  const rest = selector.replace(/:(?:not|is)\(([^)]*)\)/g, (_m, arg: string) => {
    const top = arg
      .split(",")
      .map((x) => specificity(x.trim()))
      .reduce<Spec>((m, x) => (cmp(x, m) > 0 ? x : m), [0, 0, 0]);
    a += top[0];
    b += top[1];
    c += top[2];
    return "";
  });
  a += (rest.match(/#[\w-]+/g) ?? []).length;
  b += (rest.match(/\.[\w-]+|\[[^\]]*\]|(?<!:):(?!:)[\w-]+/g) ?? []).length;
  c += (rest.match(/::[\w-]+/g) ?? []).length;
  return [a, b, c];
}

const sets = (body: string, prop: string): boolean =>
  new RegExp(`(?:^|;|\\s)${prop}\\s*:`).test(body);
/** The declared value of `prop` for exactly this selector. */
const decl = (blocks: Block[], selector: string, prop: string): string | undefined =>
  blocks
    .filter((b) => b.selector === selector)
    .map((b) => new RegExp(`(?:^|;|\\s)${prop}\\s*:\\s*([^;]+)`).exec(b.body)?.[1]?.trim())
    .find((v) => v !== undefined);
const at = (blocks: Block[], selector: string, prop: string): number =>
  blocks.find((b) => b.selector === selector && sets(b.body, prop))?.at ?? -1;

/** Which of two rules that can both match one element wins: higher specificity, then the later one. */
function winner(css: Block[], x: string, y: string, prop: string): string {
  expect(at(css, x, prop), `${x} sets ${prop}`).toBeGreaterThanOrEqual(0);
  expect(at(css, y, prop), `${y} sets ${prop}`).toBeGreaterThanOrEqual(0);
  const order = cmp(specificity(x), specificity(y)) || at(css, x, prop) - at(css, y, prop);
  return order > 0 ? x : y;
}

const OPT = ".cv-segmented__option";
const RING = `${OPT}::after`;
const F = ".cv-segmented";
// Normal-mode selectors that carry colour.
const N_CHECKED_FILL = `${OPT}[data-checked]::before`;
const N_HOVER = `${OPT}:hover:not([data-checked], [data-disabled], [data-gated])`;
// Forced twins.
const FOPT = `${F} ${OPT}`;
const F_FILL = `${FOPT}::before`;
const F_CHECKED_FILL = `${FOPT}[data-checked]::before`;
const F_CHECKED_RING = `${FOPT}[data-checked]::after`;
const F_HOVER = `${FOPT}:hover:not([data-checked], [data-disabled], [data-gated])`;
const F_DIS_FILL = `${F}[data-disabled] ${OPT}[data-checked]::before`;
const F_GATED_FILL = `${F}[data-gated] ${OPT}[data-checked]::before`;
const F_DIS_RING = `${F}[data-disabled] ${OPT}[data-checked]::after`;
const F_GATED_RING = `${F}[data-gated] ${OPT}[data-checked]::after`;
const F_DIS_TEXT = `${F}[data-disabled] ${OPT}[data-checked]`;
const F_GATED_TEXT = `${F}[data-gated] ${OPT}[data-checked]`;

describe("segmented.css contract", () => {
  it("each segment is at least one control tall and wide; labels never wrap or truncate", () => {
    expect(decl(NORMAL, OPT, "min-height")).toBe("var(--size-control-height)");
    expect(decl(NORMAL, OPT, "min-width")).toBe("var(--size-control-height)");
    expect(decl(NORMAL, OPT, "white-space")).toBe("nowrap");
    expect(normal).not.toContain("text-overflow");
    expect(decl(NORMAL, `${F}[data-size="sm"] ${OPT}`, "padding-inline")).toBe(
      "var(--space-inset-sm)",
    );
  });

  it("colours come from tokens, never a literal", () => {
    expect(normal).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(decl(NORMAL, N_CHECKED_FILL, "background")).toBe("var(--color-action-selected)");
    expect(decl(NORMAL, `${OPT}[data-checked]::after`, "border-color")).toBe(
      "var(--color-border-selected)",
    );
    expect(decl(NORMAL, `${RING}`, "border")).toContain("--border-thick");
    expect(decl(NORMAL, `${N_HOVER}::before`, "background")).toBe("var(--color-surface-hover)");
    expect(decl(NORMAL, F, "background")).toBe("var(--color-surface-raised)");
  });

  it("the selected outline is a pseudo-element, so the focus ring (the element's own outline) never fights it", () => {
    expect(decl(NORMAL, `${OPT}:focus-visible`, "outline")).toContain("var(--color-focus-ring)");
    expect(decl(NORMAL, `${OPT}[data-checked]`, "outline")).toBeUndefined();
    expect(decl(NORMAL, OPT, "outline")).toBe("none");
  });

  it("gated: only the checked fill dims; the label, the lock and the outline never take the opacity", () => {
    expect(decl(NORMAL, `${F}[data-gated] ${N_CHECKED_FILL}`, "opacity")).toBe(
      "var(--opacity-disabled)",
    );
    expect(decl(NORMAL, `${F}[data-gated]`, "opacity")).toBeUndefined();
    expect(decl(NORMAL, `${F}[data-gated] ${OPT}`, "opacity")).toBeUndefined();
    expect(decl(NORMAL, `${OPT}[data-checked]::after`, "opacity")).toBeUndefined();
    expect(decl(NORMAL, ".cv-segmented__lock", "color")).toBe("var(--color-text-secondary)");
    expect(decl(NORMAL, `${OPT}[data-checked]`, "color")).toBe("var(--color-text-primary)");
    // Plain disabled dims the whole track.
    expect(decl(NORMAL, `${F}[data-disabled]`, "opacity")).toBe("var(--opacity-disabled)");
  });

  it("gated: the track plate dims too (the track itself goes transparent), the labels never", () => {
    const plate = `${F}[data-gated]::before`;
    expect(decl(NORMAL, `${F}[data-gated]`, "background")).toBe("transparent");
    expect(decl(NORMAL, `${F}[data-gated]`, "border-color")).toBe("transparent");
    expect(decl(NORMAL, plate, "background")).toBe("var(--color-surface-raised)");
    expect(decl(NORMAL, plate, "border-color")).toBe("var(--color-border-default)");
    expect(decl(NORMAL, plate, "opacity")).toBe("var(--opacity-disabled)");
    expect(decl(NORMAL, `${F}::before`, "z-index")).toBe("-1");
    expect(decl(NORMAL, F, "isolation")).toBe("isolate");
    expect(decl(NORMAL, F, "position")).toBe("relative");
    // The forced plate is system colours at full strength.
    expect(decl(FORCED, plate, "opacity")).toBe("1");
    expect(decl(FORCED, plate, "background")).toBe("ButtonFace");
    expect(decl(FORCED, plate, "border-color")).toBe("GrayText");
    expect(decl(FORCED, `${F}[data-gated]`, "background")).toBe("ButtonFace");
  });

  it("the lock is text.secondary, a row item after the options with its own inline padding", () => {
    expect(decl(NORMAL, ".cv-segmented__lock", "color")).toBe("var(--color-text-secondary)");
    expect(decl(NORMAL, ".cv-segmented__lock", "padding-inline")).toBe("var(--space-inset-xs)");
    expect(decl(NORMAL, ".cv-segmented__lock", "align-self")).toBe("center");
  });

  it("a focused segment is raised above a hovered neighbour so the ring is never painted over", () => {
    expect(decl(NORMAL, `${OPT}:focus-visible`, "z-index")).toBe("1");
    expect(decl(NORMAL, OPT, "position")).toBe("relative");
  });

  it("the selected label is body-strong and a hidden copy reserves that width", () => {
    const strong = (v: string | undefined): boolean => (v ?? "").includes("--type-ui-body-strong-");
    expect(strong(decl(NORMAL, `${OPT}[data-checked] .cv-segmented__label`, "font"))).toBe(true);
    const copy = ".cv-segmented__label::after";
    expect(decl(NORMAL, copy, "content")).toBe("attr(data-label)");
    expect(decl(NORMAL, copy, "visibility")).toBe("hidden");
    expect(decl(NORMAL, copy, "height")).toBe("0");
    expect(strong(decl(NORMAL, copy, "font"))).toBe(true);
    expect(decl(NORMAL, ".cv-segmented__label", "flex-direction")).toBe("column");
  });

  it("hover reaches only an unselected, enabled, ungated segment", () => {
    expect(N_HOVER).toContain(":not([data-checked], [data-disabled], [data-gated])");
    expect(decl(NORMAL, N_HOVER, "color")).toBe("var(--color-text-primary)");
  });

  it("forced colours: system colours only, no token leaks", () => {
    expect(forced).not.toMatch(/var\(--/);
    expect(decl(FORCED, F, "forced-color-adjust")).toBe("none");
    expect(decl(FORCED, FOPT, "forced-color-adjust")).toBe("none");
    expect(decl(FORCED, F_CHECKED_FILL, "background")).toBe("Highlight");
    expect(decl(FORCED, `${FOPT}[data-checked]`, "color")).toBe("HighlightText");
    expect(decl(FORCED, F_HOVER, "border-color")).toBe("Highlight");
    expect(decl(FORCED, `${FOPT}:focus-visible`, "outline-color")).toBe("Highlight");
  });

  it("forced colours: hover sets the fill again, not only the border", () => {
    expect(decl(FORCED, `${F_HOVER}::before`, "background")).toBe("ButtonFace");
    expect(winner(FORCED, `${F_HOVER}::before`, F_FILL, "background")).toBe(`${F_HOVER}::before`);
  });

  it("forced colours: every colour a normal rule sets has a forced twin at equal or higher specificity", () => {
    const colourProps = ["background", "border-color", "color", "outline-color"];
    for (const n of NORMAL) {
      for (const prop of colourProps) {
        if (!sets(n.body, prop)) continue;
        const last =
          n.selector
            .replace(/:not\([^)]*\)/g, "")
            .split(" ")
            .pop() ?? "§";
        const covered = FORCED.some(
          (f) =>
            sets(f.body, prop) &&
            cmp(specificity(f.selector), specificity(n.selector)) >= 0 &&
            f.selector.replace(/:not\([^)]*\)/g, "").endsWith(last),
        );
        expect(covered, `${n.selector} { ${prop} } has no forced twin`).toBe(true);
      }
    }
  });

  it("forced colours: disabled and gated win over checked, hover and the base fill", () => {
    for (const prop of ["background"]) {
      expect(winner(FORCED, F_DIS_FILL, F_CHECKED_FILL, prop)).toBe(F_DIS_FILL);
      expect(winner(FORCED, F_GATED_FILL, F_CHECKED_FILL, prop)).toBe(F_GATED_FILL);
      expect(winner(FORCED, F_DIS_FILL, F_FILL, prop)).toBe(F_DIS_FILL);
      expect(winner(FORCED, F_GATED_FILL, F_FILL, prop)).toBe(F_GATED_FILL);
    }
    expect(winner(FORCED, F_DIS_RING, F_CHECKED_RING, "border-color")).toBe(F_DIS_RING);
    expect(winner(FORCED, F_GATED_RING, F_CHECKED_RING, "border-color")).toBe(F_GATED_RING);
    expect(winner(FORCED, F_DIS_TEXT, `${FOPT}[data-checked]`, "color")).toBe(F_DIS_TEXT);
    expect(winner(FORCED, F_GATED_TEXT, `${FOPT}[data-checked]`, "color")).toBe(F_GATED_TEXT);
    expect(decl(FORCED, F_DIS_TEXT, "color")).toBe("GrayText");
    expect(decl(FORCED, F_DIS_RING, "border-color")).toBe("GrayText");
    expect(decl(FORCED, F_DIS_FILL, "background")).toBe("ButtonFace");
    expect(decl(FORCED, `${F}[data-disabled]`, "opacity")).toBe("1");
    expect(decl(FORCED, `${F}[data-disabled]`, "border-color")).toBe("GrayText");
    // Gated keeps the selection at full strength as a 2px ButtonText border, with the labels at ButtonText.
    expect(decl(FORCED, F_GATED_RING, "border-color")).toBe("ButtonText");
    expect(decl(FORCED, F_GATED_TEXT, "color")).toBe("ButtonText");
    expect(decl(FORCED, F_GATED_FILL, "background")).toBe("ButtonFace");
    expect(decl(FORCED, F_GATED_FILL, "opacity")).toBe("1");
    expect(decl(FORCED, `${F}[data-gated]`, "border-color")).toBe("GrayText");
    expect(decl(FORCED, ".cv-segmented .cv-segmented__lock", "color")).toBe("ButtonText");
  });

  it("forced colours: the lock keeps ButtonText over the disabled and gated label colours", () => {
    // The lock only renders when gated; its forced rule must not lose to a gated-text rule that greys it.
    expect(decl(FORCED, F_GATED_TEXT, "color")).not.toBe("GrayText");
  });
});
