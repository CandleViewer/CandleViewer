import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(import.meta.dirname, "../src/components");
const CSS = readFileSync(resolve(SRC, "radio.css"), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");
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

/** The declared value of `prop`, per selector, in file order. */
const decl = (blocks: Block[], selector: string, prop: string): string | undefined =>
  blocks
    .filter((b) => b.selector === selector)
    .map((b) => new RegExp(`(?:^|;|\\s)${prop}\\s*:\\s*([^;]+)`).exec(b.body)?.[1]?.trim())
    .find((v) => v !== undefined);
const at = (blocks: Block[], selector: string, prop: string): number =>
  blocks.find((b) => b.selector === selector && new RegExp(`(?:^|;|\\s)${prop}\\s*:`).test(b.body))
    ?.at ?? -1;

/** Which of two rules that can both match one element wins: higher specificity, then the later one. */
function winner(css: Block[], x: string, y: string, prop: string): string {
  expect(at(css, x, prop), `${x} sets ${prop}`).toBeGreaterThanOrEqual(0);
  expect(at(css, y, prop), `${y} sets ${prop}`).toBeGreaterThanOrEqual(0);
  const order = cmp(specificity(x), specificity(y)) || at(css, x, prop) - at(css, y, prop);
  return order > 0 ? x : y;
}

const RING = ".cv-radio__ring";
const DIS = `.cv-radio[data-disabled] .cv-radio__mark ${RING}`;
const GATED = `.cv-radio[data-gated] .cv-radio__mark ${RING}`;
const CHECKED = `.cv-radio[data-checked] ${RING}`;
const HOVER = `.cv-radio:hover:not([data-disabled], [data-gated]) ${RING}`;

describe("radio.css contract", () => {
  it("the specificity helper counts ids, classes, attributes, pseudo-classes and :not()", () => {
    expect(specificity(HOVER)).toEqual([0, 4, 0]);
    expect(specificity(`${RING}::after`)).toEqual([0, 1, 1]);
    expect(specificity("#a.b[c]:d")).toEqual([1, 3, 0]);
  });

  it("the row is at least one control tall and the label wraps instead of truncating", () => {
    expect(decl(NORMAL, ".cv-radio", "min-height")).toBe("var(--size-control-height)");
    expect(decl(NORMAL, ".cv-radio__mark", "min-height")).toBe("var(--size-control-height)");
    expect(normal).not.toContain("text-overflow");
    expect(normal).not.toContain("nowrap");
  });

  it("colours come from tokens, never a literal", () => {
    expect(normal).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(decl(NORMAL, CHECKED, "background")).toBe("var(--color-action-primary-default)");
    expect(decl(NORMAL, RING, "border")).toContain("var(--color-text-tertiary)");
    expect(decl(NORMAL, `${RING}::after`, "background")).toBe("var(--color-text-on-action)");
  });

  it("the gated ring dims but the label does not; plain disabled dims the whole row", () => {
    expect(decl(NORMAL, GATED, "opacity")).toBe("var(--opacity-disabled)");
    expect(decl(NORMAL, ".cv-radio[data-gated]", "opacity")).toBeUndefined();
    expect(decl(NORMAL, ".cv-radio[data-disabled]", "opacity")).toBe("var(--opacity-disabled)");
  });

  it("forced colours: system colours only, no token leaks", () => {
    expect(forced).not.toMatch(/var\(--/);
    expect(decl(FORCED, ".cv-radio", "forced-color-adjust")).toBe("none");
    expect(decl(FORCED, CHECKED, "background")).toBe("Highlight");
    expect(decl(FORCED, `.cv-radio ${RING}::after`, "background")).toBe("HighlightText");
    expect(decl(FORCED, HOVER, "border-color")).toBe("Highlight");
    expect(decl(FORCED, ".cv-radio:focus-visible .cv-radio__ring", "outline-color")).toBe(
      "Highlight",
    );
  });

  it("forced colours: every colour a normal state sets has a forced twin at equal or higher specificity", () => {
    const colourProps = ["background", "border-color", "color", "outline-color"];
    for (const n of NORMAL) {
      for (const prop of colourProps) {
        if (!new RegExp(`(?:^|;|\\s)${prop}\\s*:`).test(n.body)) continue;
        const twin = FORCED.find(
          (f) => f.selector === n.selector && new RegExp(`(?:^|;|\\s)${prop}\\s*:`).test(f.body),
        );
        const covered = FORCED.some(
          (f) =>
            new RegExp(`(?:^|;|\\s)${prop}\\s*:`).test(f.body) &&
            cmp(specificity(f.selector), specificity(n.selector)) >= 0 &&
            f.selector.replace(/:not\([^)]*\)/g, "").endsWith(n.selector.split(" ").pop() ?? "§"),
        );
        expect(twin !== undefined || covered, `${n.selector} { ${prop} } has no forced twin`).toBe(
          true,
        );
      }
    }
  });

  it("forced colours: disabled and gated win over checked, hover and the base ring", () => {
    for (const prop of ["border-color", "background"]) {
      expect(winner(FORCED, DIS, CHECKED, prop)).toBe(DIS);
      expect(winner(FORCED, GATED, CHECKED, prop)).toBe(GATED);
      expect(winner(FORCED, DIS, `.cv-radio ${RING}`, prop)).toBe(DIS);
      expect(winner(FORCED, GATED, `.cv-radio ${RING}`, prop)).toBe(GATED);
    }
    // The dot: checked is HighlightText, disabled GrayText and gated CanvasText must still win.
    const dot = (s: string): string => `${s}::after`;
    expect(winner(FORCED, dot(DIS), dot(`.cv-radio ${RING}`), "background")).toBe(dot(DIS));
    expect(winner(FORCED, dot(GATED), dot(`.cv-radio ${RING}`), "background")).toBe(dot(GATED));
    // Disabled label is GrayText, and the gated ring undoes the normal-mode opacity.
    expect(decl(FORCED, ".cv-radio[data-disabled]", "color")).toBe("GrayText");
    expect(decl(FORCED, GATED, "opacity")).toBe("1");
    expect(decl(FORCED, DIS, "border-color")).toBe("GrayText");
    expect(decl(FORCED, GATED, "border-color")).toBe("GrayText");
    expect(decl(FORCED, dot(GATED), "background")).toBe("CanvasText");
    // Hover cannot reach a refused row at all: its rule excludes both.
    expect(HOVER).toContain(":not([data-disabled], [data-gated])");
  });

  it("forced colours: the normal-mode rule never out-specifies its forced override", () => {
    // Normal checked (0,3,0) is overridden by the forced checked twin (0,3,0, later); the base ring forced
    // rule (0,2,0) is out-specified by the normal checked rule, which is why the forced checked rule exists.
    expect(winner(FORCED, CHECKED, CHECKED, "background")).toBe(CHECKED);
    expect(cmp(specificity(CHECKED), specificity(`.cv-radio ${RING}`))).toBeGreaterThan(0);
  });
});
