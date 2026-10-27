import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(import.meta.dirname, "../src/components");
const read = (name: string): string =>
  readFileSync(resolve(SRC, name), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");
const CSS = read("select.css");

interface Block {
  readonly selectors: readonly string[];
  readonly body: string;
  readonly index: number;
}

function blocks(css: string, offset = 0): Block[] {
  return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
    selectors: (m[1] ?? "").split(/,(?![^(]*\))/).map((s) => s.replace(/\s+/g, " ").trim()),
    body: m[2] ?? "",
    index: offset + m.index,
  }));
}

const MARK = "@media (forced-colors: active)";
const split = CSS.indexOf(MARK);
const normal = blocks(CSS.slice(0, split)).filter((b) => !b.selectors[0]?.startsWith("@"));
const forced = blocks(CSS.slice(split + MARK.length).replace(/^\s*\{/, ""), split);
const PAINT = /(^|[\s;])(color|background|border-color)\s*:/;
const prop = (b: Block, name: string): string | undefined =>
  new RegExp(`(?:^|[\\s;])${name}\\s*:\\s*([^;]+)`).exec(b.body)?.[1]?.trim();
const rule = (list: Block[], selector: string): Block =>
  list.find((b) => b.selectors.includes(selector)) as Block;
const twins = (selector: string): Block[] => forced.filter((b) => b.selectors.includes(selector));

describe("select.css forced-colours cascade", () => {
  const painting = normal
    .filter((b) => PAINT.test(b.body))
    .flatMap((b) => b.selectors.map((s) => [s, b] as const));

  it("finds the rules and the forced block", () => {
    expect(split).toBeGreaterThan(0);
    expect(painting.length).toBeGreaterThanOrEqual(5);
    expect(forced.length).toBeGreaterThanOrEqual(6);
  });

  // Same selector, later in the file: equal specificity, so the forced rule wins the cascade.
  it.each(painting.map(([s]) => s))("%s has a forced twin with the same selector", (selector) => {
    const block = painting.find(([s]) => s === selector)?.[1] as Block;
    for (const name of ["color", "background", "border-color"]) {
      const value = prop(block, name);
      if (value === undefined || ["inherit", "transparent"].includes(value)) continue;
      expect(twins(selector).some((t) => prop(t, name) !== undefined)).toBe(true);
    }
  });

  it("no forced paint uses a token variable, and every twin comes after its normal rule", () => {
    for (const b of forced.filter((x) => PAINT.test(x.body))) {
      expect(b.body).not.toContain("var(--color");
    }
    for (const [selector, block] of painting) {
      for (const t of twins(selector)) expect(t.index).toBeGreaterThan(block.index);
    }
  });

  it("the active option is Highlight on HighlightText; disabled is GrayText at full opacity, and wins", () => {
    const active = twins(".cv-select__option[data-active]")[0] as Block;
    expect(prop(active, "background")).toBe("Highlight");
    expect(prop(active, "color")).toBe("HighlightText");
    // The ring is a colour too: it takes the system pair, so it never fades into the Highlight fill.
    expect(prop(active, "outline-color")).toBe("HighlightText");
    const off = twins('.cv-select__option[data-kind="disabled"]')[0] as Block;
    expect(prop(off, "color")).toBe("GrayText");
    expect(prop(off, "opacity")).toBe("1");
    for (const list of [normal, forced]) {
      expect(rule(list, '.cv-select__option[data-kind="disabled"]').index).toBeGreaterThan(
        rule(list, ".cv-select__option[data-active]").index,
      );
    }
  });

  it("unavailable and T2 options keep the reason at full opacity; every line stays legible on the active fill", () => {
    const label = '.cv-select__option[data-kind="unavailable"] .cv-select__label';
    expect(prop(rule(normal, label), "opacity")).toBe("var(--opacity-disabled)");
    expect(prop(twins(label)[0] as Block, "color")).toBe("GrayText");
    expect(prop(rule(normal, ".cv-select__reason"), "color")).toBe("var(--color-text-secondary)");
    expect(prop(rule(normal, ".cv-select__reason"), "opacity")).toBeUndefined();
    expect(prop(twins(".cv-select__reason")[0] as Block, "color")).toBe("CanvasText");
    const locked = '.cv-select__option[data-kind="locked"] .cv-select__label';
    // T2 keeps its label and lock in CanvasText, never GrayText (conventions 29); plain disabled is the GrayText one.
    expect(prop(twins(locked)[0] as Block, "color")).toBe("CanvasText");
    expect(
      prop(
        twins('.cv-select__option[data-kind="locked"] .cv-select__optlock')[0] as Block,
        "color",
      ),
    ).toBe("CanvasText");
    expect(prop(twins('.cv-select__option[data-kind="disabled"]')[0] as Block, "color")).toBe(
      "GrayText",
    );
    // The active twin is last and equal in weight, so it beats the kind twins on the Highlight fill.
    const onFill = twins(".cv-select__option[data-active] .cv-select__reason")[0] as Block;
    expect(prop(onFill, "color")).toBe("HighlightText");
    for (const selector of [label, locked]) {
      expect(onFill.index).toBeGreaterThan((twins(selector)[0] as Block).index);
    }
    expect(onFill.selectors).toContain(".cv-select__option[data-active] .cv-select__label");
  });

  it("only plain disabled dims the whole row: the unavailable and T2 rows keep the active fill and ring", () => {
    expect(rule(normal, '.cv-select__option[data-kind="disabled"]').body).toContain("opacity");
    for (const kind of ["unavailable", "locked"]) {
      const row = normal.find((b) =>
        b.selectors.includes(`.cv-select__option[data-kind="${kind}"]`),
      );
      expect(row?.body).not.toContain("opacity");
      expect(row?.body).not.toMatch(/background|outline/);
    }
  });

  it("the popup keeps a real border and sets system colours by hand", () => {
    const popup = twins(".cv-select__popup")[0] as Block;
    expect(prop(popup, "border-color")).toBe("CanvasText");
    expect(prop(popup, "background")).toBe("Canvas");
    expect(prop(popup, "forced-color-adjust")).toBe("none");
  });

  it("the placeholder and a disabled chevron grey; the lock and chevron are FieldText otherwise", () => {
    expect(prop(twins(".cv-select__value[data-placeholder]")[0] as Block, "color")).toBe(
      "GrayText",
    );
    expect(prop(twins(".cv-field[data-disabled] .cv-select__chevron")[0] as Block, "color")).toBe(
      "GrayText",
    );
    expect(prop(twins(".cv-select__lock")[0] as Block, "color")).toBe("FieldText");
  });
});

describe("select.css popup", () => {
  const popup = rule(normal, ".cv-select__popup");

  it("uses the overlay surface, popover shadow and card radius, never a raw colour", () => {
    expect(popup.body).toContain("background: var(--color-surface-overlay)");
    expect(popup.body).toContain("box-shadow: var(--elevation-popover)");
    expect(popup.body).toContain("border-radius: var(--radius-card)");
    expect(CSS).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(/i);
  });

  it("is at most ten rows tall then scrolls, at least the field's width", () => {
    expect(popup.body).toMatch(/max-block-size:\s*min\(\s*calc\(\s*10 \* var\(--size-row-height\)/);
    expect(popup.body).toContain("overflow-y: auto");
    expect(popup.body).toContain("min-inline-size: 100%");
  });

  it("caps to the room on its side (conv. 28), one row at least, and to the viewport's inline end", () => {
    expect(popup.body).toMatch(
      /max\(\s*var\(--size-row-height\),\s*calc\(var\(--cv-select-room, 100vh\) - var\(--cv-select-gap\) - var\(--space-inset-xs\)\)/,
    );
    expect(popup.body).toContain("max-inline-size: min(100vw, var(--cv-select-wide, 100vw))");
  });

  it("the open chevron turns up with a transform only: no paint, so no forced twin is owed", () => {
    const open = rule(normal, '.cv-select__trigger[aria-expanded="true"] .cv-select__chevron');
    expect(prop(open, "transform")).toBe("rotate(180deg)");
    expect(PAINT.test(open.body)).toBe(false);
  });

  it("a long label wraps instead of widening the popup", () => {
    expect(rule(normal, ".cv-select__body").body).toContain("overflow-wrap: anywhere");
  });

  it("is absolute under a relative anchor and clears the focus ring on both sides", () => {
    expect(rule(normal, ".cv-select__anchor").body).toContain("position: relative");
    expect(popup.body).toContain("position: absolute");
    expect(popup.body).toContain("(var(--border-focus) + 2) * 1px");
    expect(rule(normal, '.cv-select__popup[data-placement="below"]').body).toContain(
      "top: calc(100% + var(--cv-select-gap))",
    );
    expect(rule(normal, '.cv-select__popup[data-placement="above"]').body).toContain(
      "bottom: calc(100% + var(--cv-select-gap))",
    );
  });

  it("fades only when motion is allowed, over the fast token", () => {
    const raw = readFileSync(resolve(SRC, "select.css"), "utf-8");
    expect(raw).toMatch(
      /prefers-reduced-motion: no-preference\)\s*\{[^@]*var\(--motion-duration-fast\)/,
    );
  });

  it("the active option carries CMP-039's inset ring (H8): 2px focus ring drawn 2px inside, control radius", () => {
    const active = rule(normal, ".cv-select__option[data-active]");
    expect(prop(active, "background")).toBe("var(--color-surface-hover)");
    expect(prop(active, "outline")).toBe(
      "calc(var(--border-focus) * 1px) solid var(--color-focus-ring)",
    );
    expect(prop(active, "outline-offset")).toBe("calc(var(--border-focus) * -2px)");
    expect(prop(active, "border-radius")).toBe("var(--radius-control)");
  });

  it("the ring is on the active option only: no other option state sets an outline", () => {
    const rings = normal.filter(
      (b) =>
        b.selectors.some((x) => x.startsWith(".cv-select__option")) &&
        prop(b, "outline") !== undefined,
    );
    expect(rings.map((b) => b.selectors)).toEqual([[".cv-select__option[data-active]"]]);
  });

  it("no hover rule exists: the pointer moves the active option, so the highlight and aria agree", () => {
    expect(CSS).not.toContain(":hover");
  });
});

describe("select.css two-line options", () => {
  it("a reason row has block padding, so the inset ring clears the text", () => {
    expect(prop(rule(normal, ".cv-select__option[data-lines]"), "padding-block")).toBe(
      "var(--space-inset-xs)",
    );
  });

  it("the lock sits inside the label line, so the label column is shared; long labels clamp to two lines", () => {
    expect(prop(rule(normal, ".cv-select__line"), "display")).toBe("flex");
    const label = rule(normal, ".cv-select__label");
    expect(prop(label, "-webkit-line-clamp")).toBe("2");
    expect(prop(label, "overflow")).toBe("hidden");
  });
});
