import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(import.meta.dirname, "../src/components");
const read = (name: string): string =>
  readFileSync(resolve(SRC, name), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");

interface Block {
  readonly selectors: readonly string[];
  readonly body: string;
}

function blocks(css: string): Block[] {
  return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
    selectors: (m[1] ?? "").split(/,(?![^(]*\))/).map((s) => s.replace(/\s+/g, " ").trim()),
    body: m[2] ?? "",
  }));
}

const split = (name: string): readonly [string, string] => {
  const [normal = "", forced = ""] = read(name).split("@media (forced-colors: active)");
  return [normal, forced];
};
const decl = (css: string, selector: string, prop: string): string | undefined =>
  blocks(css)
    .filter((b) => b.selectors.includes(selector))
    .map((b) => new RegExp(`${prop}\\s*:\\s*([^;]+)`).exec(b.body)?.[1])
    .find((v) => v !== undefined);

type Spec = readonly [number, number, number];

/** Specificity of one compound-or-complex selector (ids, classes/attributes/pseudo-classes, types/pseudo-elements). */
function specificity(selector: string): Spec {
  let [a, b, c] = [0, 0, 0];
  const rest = selector.replace(/:(?:not|is)\(([^)]*)\)/g, (_m, arg: string) => {
    const inner = arg.split(",").map((x) => specificity(x.trim()));
    const top = inner.reduce<Spec>((m, x) => (cmp(x, m) > 0 ? x : m), [0, 0, 0]);
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
const cmp = (x: Spec, y: Spec): number => x[0] - y[0] || x[1] - y[1] || x[2] - y[2];

/** Index of the block (in file order) that declares `prop` for exactly this selector; throws when absent. */
function rule(css: string, selector: string, prop: string): { at: number; value: string } {
  const list = blocks(css);
  const at = list.findIndex(
    (b) => b.selectors.includes(selector) && new RegExp(`(^|;|\\s)${prop}\\s*:`).test(b.body),
  );
  if (at < 0) throw new Error(`no rule sets ${prop} for ${selector}`);
  const value = new RegExp(`${prop}\\s*:\\s*([^;]+)`).exec(list[at]?.body ?? "")?.[1] ?? "";
  return { at, value };
}

/**
 * The cascade outcome for two states that can both hold on one element: the winner must carry the higher
 * specificity, or an equal one declared later. `loserCss` may be the normal block (always earlier).
 */
function wins(
  winnerCss: string,
  winner: string,
  loserCss: string,
  loser: string,
  prop: string,
  value: string,
): void {
  const w = rule(winnerCss, winner, prop);
  const l = rule(loserCss, loser, prop);
  expect(w.value).toBe(value);
  const order = cmp(specificity(winner), specificity(loser));
  const later = winnerCss === loserCss ? w.at > l.at : winnerCss !== loserCss;
  expect(order > 0 || (order === 0 && later)).toBe(true);
}

const [toggle, toggleForced] = split("toggle.css");
const [choice, choiceForced] = split("choice.css");

describe("toggle.css contract", () => {
  it("gated: the knob is text.primary and the plate dims by opacity.disabled", () => {
    expect(decl(toggle, '.cv-switch[aria-disabled="true"] > .cv-switch__knob', "background")).toBe(
      "var(--color-text-primary)",
    );
    expect(decl(toggle, '.cv-switch[aria-disabled="true"]::before', "opacity")).toBe(
      "var(--opacity-disabled)",
    );
  });

  it("the track is off text.tertiary, on action.primary, armed warning.strong with an inverse knob", () => {
    expect(decl(toggle, ".cv-switch", "--cv-switch-track")).toBe("var(--color-text-tertiary)");
    expect(decl(toggle, '.cv-switch[aria-checked="true"]', "--cv-switch-track")).toBe(
      "var(--color-action-primary-default)",
    );
    const armed = '.cv-choice[data-critical] .cv-switch[aria-checked="true"]';
    expect(decl(toggle, armed, "--cv-switch-track")).toBe("var(--color-status-warning-strong)");
    expect(decl(toggle, armed, "--cv-switch-knob")).toBe("var(--color-text-inverse)");
  });

  it("motion uses the fast token and the standard easing, never a literal duration", () => {
    expect(toggle).toContain(
      "transform var(--motion-duration-fast) cubic-bezier(var(--motion-easing-standard))",
    );
    expect(toggle).not.toMatch(/transition:[^;]*\d+m?s/);
  });

  it("forced colours: system colours only, gated knob stays CanvasText, repeated for critical", () => {
    expect(decl(toggleForced, ".cv-switch", "forced-color-adjust")).toBe("none");
    expect(decl(toggleForced, '.cv-switch[aria-checked="true"]', "background")).toBe("Highlight");
    expect(
      decl(toggleForced, '.cv-switch[aria-checked="true"] > .cv-switch__knob', "background"),
    ).toBe("HighlightText");
    expect(
      decl(toggleForced, '.cv-switch[aria-disabled="true"] > .cv-switch__knob', "background"),
    ).toBe("CanvasText");
    expect(
      decl(
        toggleForced,
        '.cv-choice[data-critical] .cv-switch[aria-checked="true"] > .cv-switch__knob',
        "background",
      ),
    ).toBe("HighlightText");
    expect(toggleForced).not.toMatch(/var\(--color/);
  });
});

describe("choice.css contract", () => {
  it("every colour a state sets is repeated for forced colours", () => {
    expect(decl(choice, ".cv-choice__lock", "color")).toBe("var(--color-text-secondary)");
    expect(decl(choiceForced, ".cv-choice__lock", "color")).toBe("CanvasText");
    expect(decl(choiceForced, ".cv-choice[data-disabled] .cv-choice__lock", "color")).toBe(
      "GrayText",
    );
    expect(decl(choiceForced, ".cv-choice", "color")).toBe("CanvasText");
    expect(decl(choiceForced, ".cv-choice[data-disabled]", "color")).toBe("GrayText");
  });

  it("the row is at least one control tall so the hit target holds at both densities", () => {
    expect(decl(choice, ".cv-choice", "min-height")).toBe("var(--size-control-height)");
  });
});

describe("forced colours: the cascade outcome, not only the declarations", () => {
  const onT = '.cv-switch[aria-checked="true"]';
  const armedT = '.cv-choice[data-critical] .cv-switch[aria-checked="true"]';

  it("toggle: a disabled switch is GrayText and Canvas whether on, off or armed", () => {
    for (const prop of ["border-color", "background"]) {
      const value = prop === "background" ? "Canvas" : "GrayText";
      wins(
        toggleForced,
        ".cv-choice[data-disabled] .cv-switch[aria-checked]",
        toggleForced,
        onT,
        prop,
        value,
      );
      wins(
        toggleForced,
        ".cv-choice[data-disabled][data-critical] .cv-switch[aria-checked]",
        toggleForced,
        armedT,
        prop,
        value,
      );
    }
  });

  it("toggle: a disabled knob is GrayText over the on and armed knobs", () => {
    wins(
      toggleForced,
      ".cv-choice[data-disabled] .cv-switch[aria-checked] > .cv-switch__knob",
      toggleForced,
      `${onT} > .cv-switch__knob`,
      "background",
      "GrayText",
    );
    wins(
      toggleForced,
      ".cv-choice[data-disabled][data-critical] .cv-switch[aria-checked] > .cv-switch__knob",
      toggleForced,
      `${armedT} > .cv-switch__knob`,
      "background",
      "GrayText",
    );
  });

  it("toggle: a gated armed switch keeps Canvas, GrayText and a CanvasText knob over the armed rules", () => {
    const gated = '.cv-choice[data-critical] .cv-switch[aria-disabled="true"][aria-checked]';
    wins(toggleForced, gated, toggleForced, armedT, "background", "Canvas");
    wins(toggleForced, gated, toggleForced, armedT, "border-color", "GrayText");
    wins(
      toggleForced,
      `${gated} > .cv-switch__knob`,
      toggleForced,
      `${armedT} > .cv-switch__knob`,
      "background",
      "CanvasText",
    );
  });

  it("specificity helper: not() takes its argument, attributes count as classes", () => {
    expect(specificity(".a:hover:not([b], [c]) .d[e] > .f")).toEqual([0, 6, 0]);
    expect(specificity(".a::before")).toEqual([0, 1, 1]);
  });
});
