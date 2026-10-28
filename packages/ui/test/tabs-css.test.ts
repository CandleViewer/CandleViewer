import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("tabs.css");
const { normal, forced } = css;

describe("tabs.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("strip: one row that scrolls, never wraps, over a 1px border.default line", () => {
    const list = find(normal, ".cv-tabs__list", "flex-wrap");
    expect(list).toContain("flex-wrap: nowrap");
    expect(list).toContain("overflow-x: auto");
    expect(list).toContain("min-height: var(--size-control-height)");
    expect(list).toContain(
      "border-block-end: calc(var(--border-hairline) * 1px) solid var(--color-border-default)",
    );
    expect(find(normal, ".cv-tabs__tab", "white-space")).toContain("white-space: nowrap");
  });

  it("tab: control-height and 24px-or-more target, label type, text.secondary, inset.sm then inset.md", () => {
    const t = find(normal, ".cv-tabs__tab", "min-height");
    expect(t).toContain("min-height: var(--size-control-height)");
    expect(t).toContain("min-width: var(--size-control-height)");
    expect(t).toContain("--type-ui-label-font-size");
    expect(t).toContain("color: var(--color-text-secondary)");
    expect(t).toContain("padding-inline: var(--space-inset-sm)");
    expect(t).toContain("gap: var(--space-inset-xs)");
    expect(find(normal, '[data-density="comfortable"] .cv-tabs__tab', "padding-inline")).toContain(
      "var(--space-inset-md)",
    );
  });

  it("selected: a 2px border.selected rule and text.primary, no fill", () => {
    const rule = find(normal, ".cv-tabs__tab::after", "border-block-end");
    expect(rule).toContain("calc(var(--border-thick) * 1px) solid transparent");
    expect(rule).toContain("inset-block-end: 0");
    expect(find(normal, ".cv-tabs__tab[data-selected]::after", "border-color")).toContain(
      "var(--color-border-selected)",
    );
    const sel = find(normal, ".cv-tabs__tab[data-selected]", "color");
    expect(sel).toContain("color: var(--color-text-primary)");
    expect(sel).not.toMatch(/background/);
  });

  it("vertical: the rule on the trailing edge and labels wrap", () => {
    expect(
      find(
        normal,
        '.cv-tabs[data-orientation="vertical"] .cv-tabs__tab::after',
        "border-inline-end",
      ),
    ).toContain("calc(var(--border-thick) * 1px) solid transparent");
    expect(
      find(normal, '.cv-tabs[data-orientation="vertical"] .cv-tabs__tab', "white-space"),
    ).toContain("white-space: normal");
  });

  it("hover: surface.hover and text.primary on an unselected, ungated tab", () => {
    const hover = find(
      normal,
      ".cv-tabs__tab:hover:not([data-selected], [data-gated])",
      "background",
    );
    expect(hover).toContain("background: var(--color-surface-hover)");
    expect(hover).toContain("color: var(--color-text-primary)");
  });

  it("focus: the CMP-039 ring, inset so the scrolling strip never clips it", () => {
    const ring = find(normal, ".cv-tabs__tab:focus-visible", "outline");
    expect(ring).toContain(
      "outline: calc(var(--border-focus) * 1px) solid var(--color-focus-ring)",
    );
    expect(ring).toContain("outline-offset: calc(var(--border-focus) * -1 * 1px)");
  });

  it("gated: text.tertiary label and lock, never opacity or text.disabled; reason caption in text.secondary", () => {
    expect(find(normal, ".cv-tabs__tab[data-gated]", "color")).toContain(
      "color: var(--color-text-tertiary)",
    );
    expect(css.all).not.toMatch(/opacity|text-disabled/);
    const reason = find(normal, ".cv-tabs__reason", "font");
    expect(reason).toContain("--type-ui-caption-font-size");
    expect(reason).toContain("color: var(--color-text-secondary)");
  });

  it("forced colours: the rule Highlight, labels ButtonText, the ring Highlight, gated GrayText", () => {
    expect(find(forced, ".cv-tabs__tab[data-selected]::after", "border-color")).toContain(
      "Highlight",
    );
    expect(find(forced, ".cv-tabs__tab", "color")).toContain("ButtonText");
    expect(find(forced, ".cv-tabs__tab:focus-visible", "outline-color")).toContain("Highlight");
    expect(find(forced, ".cv-tabs__tab[data-gated]", "color")).toContain("GrayText");
    expect(find(forced, ".cv-tabs__list", "border-color")).toContain("CanvasText");
  });
});
