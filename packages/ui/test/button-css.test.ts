import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { recipeSafe } from "./css-contract.js";

const SRC = resolve(import.meta.dirname, "../src/components");
const BUTTON = readFileSync(resolve(SRC, "button.css"), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");
const SPINNER = readFileSync(resolve(SRC, "spinner.css"), "utf-8");

interface Block {
  readonly selectors: readonly string[];
  readonly body: string;
  readonly index: number;
}

function blocks(css: string): Block[] {
  return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
    selectors: (m[1] ?? "").split(/,(?![^(]*\))/).map((s) => s.replace(/\s+/g, " ").trim()),
    body: m[2] ?? "",
    index: m.index,
  }));
}

const [normal = "", forced = ""] = BUTTON.split("@media (forced-colors: active)");
const find = (css: string, selector: string, prop: string): Block | undefined =>
  blocks(css).find(
    (b) => b.selectors.includes(selector) && new RegExp(`${prop}\\s*:`).test(b.body),
  );

describe("button.css contract", () => {
  it("gated colour: text.primary on every variant, out-specifying the variant colour rules", () => {
    const gated = find(normal, ".cv-button[data-gated][data-variant]", "color");
    expect(gated?.body).toContain("color: var(--color-text-primary)");
    // (0,3,0) against the variant rules' (0,2,0): wins whatever the source order.
    for (const v of ["primary", "danger"]) {
      const variant = find(normal, `.cv-button[data-variant="${v}"]`, "color");
      expect(variant?.body).toContain("--color-text-on-action");
      expect(gated?.index).toBeGreaterThan(variant?.index ?? Infinity);
    }
  });

  it("ghost label: text.secondary at rest, text.primary on hover and active, gated kept primary", () => {
    const rest = find(normal, '.cv-button[data-variant="ghost"]', "color");
    expect(rest?.body).toContain("color: var(--color-text-secondary)");
    for (const state of ["hover", "active"]) {
      const sel = `.cv-button[data-variant="ghost"]:${state}:not(:disabled, [aria-disabled], [aria-busy])`;
      expect(find(normal, sel, "color")?.body).toContain("color: var(--color-text-primary)");
    }
    const gated = find(normal, ".cv-button[data-gated][data-variant]", "color");
    expect(gated?.body).toContain("color: var(--color-text-primary)");
    expect(gated?.index).toBeGreaterThan(rest?.index ?? Infinity);
  });

  it("buy and sell: fills, text.inverse label, hover tokens and an active step back to the default", () => {
    for (const v of ["buy", "sell"]) {
      expect(find(normal, `.cv-button[data-variant="${v}"]`, "--cv-button-bg")?.body).toContain(
        `--color-${v}-default`,
      );
      const hover = `.cv-button[data-variant="${v}"]:hover:not(:disabled, [aria-disabled], [aria-busy])`;
      expect(find(normal, hover, "--cv-button-bg")?.body).toContain(`--color-${v}-hover`);
      const active = hover.replace(":hover", ":active");
      expect(find(normal, active, "--cv-button-bg")?.body).toContain(`--color-${v}-default`);
    }
    expect(find(normal, '.cv-button[data-variant="buy"]', "color")?.body).toContain(
      "color: var(--color-text-inverse)",
    );
  });

  it("buy and sell stay out-specified by the gated and forced-colours rules, and never truncate", () => {
    const side = find(normal, '.cv-button[data-variant="sell"]', "color");
    const gated = find(normal, ".cv-button[data-gated][data-variant]", "color");
    expect(gated?.index).toBeGreaterThan(side?.index ?? Infinity);
    expect(find(normal, ".cv-button[data-side] > .cv-button__label", "overflow")?.body).toContain(
      "overflow: visible",
    );
    // Forced colours reach buy and sell through the shared [data-variant] rule, so they need no rule of their own.
    expect(forced).not.toMatch(/data-variant="(buy|sell)"/);
  });

  it("forced colours: every variant label is ButtonText and gated keeps ButtonText", () => {
    const all = find(forced, ".cv-button[data-variant]", "color");
    expect(all?.body).toContain("color: ButtonText");
    const gated = find(forced, ".cv-button[data-gated][data-variant]", "color");
    expect(gated?.body).toContain("color: ButtonText");
    expect(gated?.index).toBeGreaterThan(
      find(forced, ".cv-button:disabled", "color")?.index ?? Infinity,
    );
  });

  it("forced colours: ghost hover and active keep the ButtonText label", () => {
    for (const state of ["hover", "active"]) {
      const rule = find(
        forced,
        `.cv-button[data-variant="ghost"]:${state}:not(:disabled, [aria-disabled], [aria-busy])`,
        "color",
      );
      expect(rule?.body).toContain("color: ButtonText");
    }
  });

  it("the validity look: the fill and the label at the disabled opacity, the focus ring kept whole", () => {
    // Never the whole control's opacity: the focus outline must keep its contrast (WCAG 2.4.7).
    const plate = find(normal, ".cv-button[data-unavailable]::before", "opacity");
    expect(plate?.body).toContain("background: var(--cv-button-bg)");
    expect(plate?.body).toContain("opacity: var(--opacity-disabled)");
    const words = find(
      normal,
      ".cv-button[data-unavailable] > :is(.cv-button__label, .cv-button__icon)",
      "opacity",
    );
    expect(words?.body).toContain("opacity: var(--opacity-disabled)");
    expect(find(normal, ".cv-button[data-unavailable]", "opacity")).toBeUndefined();
    const fill = find(normal, ".cv-button[data-unavailable][data-variant]", "background");
    expect(fill?.body).toContain("background: transparent");
    // Forced colours: the words grey, as plain disabled's do; no plate.
    expect(find(forced, ".cv-button[data-unavailable][data-variant]", "color")?.body).toContain(
      "color: GrayText",
    );
    expect(find(forced, ".cv-button[data-unavailable]::before", "content")?.body).toContain(
      "content: none",
    );
  });

  it("the label never wraps and truncates with an ellipsis", () => {
    const label = find(normal, ".cv-button__label", "white-space");
    for (const d of ["white-space: nowrap", "overflow: hidden", "text-overflow: ellipsis"])
      expect(label?.body).toContain(d);
    expect(label?.body).toContain("min-width: 0");
  });

  it("the spinner turns at twice the slow motion token, not a hard-coded second", () => {
    expect(SPINNER).toContain("animation: var(--cv-recipe-spinner)");
    expect(recipeSafe("spinner")).toBe(
      "cv-spin calc(var(--motion-duration-slow) * 2) linear infinite",
    );
    expect(SPINNER).not.toMatch(/cv-spin\s+\d/);
  });
});
