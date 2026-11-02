import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("auditrow.css");
const { normal, forced } = css;

const HIGH = '.cv-audit-row:is([data-severity="error"], [data-severity="critical"])';

describe("auditrow.css contract (E42-D03 board 10 row K; E42-D04 D2)", () => {
  itIsTokenOnlyAndStatic(css);

  it("list: no marker, margin or padding", () => {
    const list = find(normal, ".cv-audit-rows", "list-style");
    expect(list).toContain("list-style: none");
    expect(list).toContain("margin: 0");
    expect(list).toContain("padding: 0");
  });

  it("row link: at least size.row-height tall, space.inset.sm padX, type.ui.body, no underline at rest", () => {
    const row = find(normal, ".cv-audit-row__link", "min-block-size");
    expect(row).toContain("min-block-size: var(--size-row-height)");
    expect(row).toContain("padding-inline: var(--space-inset-sm)");
    expect(row).toContain("--type-ui-body-font-size");
    expect(row).toContain("color: var(--color-text-primary)");
    expect(row).toContain("text-decoration-line: none");
  });

  it("hover underlines the row's text; no fill, so no new colour pair", () => {
    const hover = find(normal, ".cv-audit-row__link:hover", "text-decoration-line");
    expect(hover).toContain("text-decoration-line: underline");
    expect(hover).not.toMatch(/background/);
  });

  it("wraps between fields and inside a long value, never truncating", () => {
    const text = find(normal, ".cv-audit-row__text", "overflow-wrap");
    expect(text).toContain("overflow-wrap: anywhere");
    expect(text).toContain("min-width: 0");
    expect(css.all).not.toMatch(/text-overflow|white-space:\s*nowrap|-webkit-line-clamp/);
  });

  it("time and code: type.num.sm (font.family.mono) in text.secondary, tabular digits", () => {
    for (const part of [".cv-audit-row__time", ".cv-audit-row__code"]) {
      const mono = find(normal, part, "font");
      expect(mono).toContain("--type-num-sm-font-family");
      expect(mono).toContain("color: var(--color-text-secondary)");
      expect(mono).toContain("font-variant-numeric: tabular-nums");
    }
    expect(find(normal, ".cv-audit-row__subject", "color")).toContain(
      "color: var(--color-text-secondary)",
    );
    expect(find(normal, ".cv-audit-row__sep", "color")).toContain(
      "color: var(--color-text-tertiary)",
    );
  });

  it("high severity: a border.thick danger.strong rule, its width given back, the word semibold", () => {
    const rule = find(normal, `${HIGH} > .cv-audit-row__link`, "border-inline-start");
    expect(rule).toContain(
      "border-inline-start: calc(var(--border-thick) * 1px) solid var(--color-status-danger-strong)",
    );
    expect(rule).toContain(
      "padding-inline-start: calc(var(--space-inset-sm) - var(--border-thick) * 1px)",
    );
    expect(find(normal, `${HIGH} .cv-audit-row__severity`, "font-weight")).toContain(
      "font-weight: var(--font-weight-semibold)",
    );
  });

  it("glyphs: size.icon, inset.xs before the word, the octagon danger.strong, the triangle warning.strong", () => {
    const glyph = find(normal, ".cv-audit-row__glyph", "width");
    expect(glyph).toContain("width: var(--size-icon)");
    expect(glyph).toContain("height: var(--size-icon)");
    expect(glyph).toContain("margin-inline-end: var(--space-inset-xs)");
    expect(glyph).toContain("color: var(--color-status-danger-strong)");
    expect(find(normal, '.cv-audit-row__glyph[data-glyph="warning"]', "color")).toContain(
      "color: var(--color-status-warning-strong)",
    );
  });

  it("forced colours: the row reads as a link, the glyph follows the text, the rule stays a border", () => {
    for (const part of [
      ".cv-audit-row__link",
      ".cv-audit-row__time",
      ".cv-audit-row__code",
      ".cv-audit-row__subject",
      ".cv-audit-row__sep",
    ]) {
      expect(find(forced, part, "color")).toContain("color: LinkText");
    }
    expect(find(forced, ".cv-audit-row__glyph", "color")).toContain("color: currentcolor");
    expect(find(forced, '.cv-audit-row__glyph[data-glyph="warning"]', "color")).toContain(
      "currentcolor",
    );
    expect(find(forced, `${HIGH} > .cv-audit-row__link`, "border-inline-start-color")).toContain(
      "border-inline-start-color: CanvasText",
    );
  });
});
