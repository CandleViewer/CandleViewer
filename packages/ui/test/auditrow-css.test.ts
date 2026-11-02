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

const ROW = '.cv-audit-row[data-variant="row"]';
const ROW_HIGH = `${ROW}:is([data-severity="error"], [data-severity="critical"])`;

describe("auditrow.css, the grid row (E42-D04 §4 Columns, D2, D14, §15)", () => {
  it("cells start at the top and wrap inside a long value, never truncating", () => {
    const cell = find(normal, `${ROW} > .cv-audit-row__cell`, "vertical-align");
    expect(cell).toContain("vertical-align: top");
    expect(cell).toContain("overflow-wrap: anywhere");
  });

  it("the expander: a bare button the 24 px column's full height, its glyphs size.icon.sm in text.secondary", () => {
    const cell = find(normal, ".cv-audit-row__expander", "padding-inline");
    expect(cell).toContain("padding-inline: 0");
    const toggle = find(normal, ".cv-audit-row__toggle", "background");
    expect(toggle).toContain("background: transparent");
    expect(toggle).toContain("border: 0");
    expect(toggle).toContain("min-block-size: var(--size-target-min)");
    expect(toggle).toContain("color: var(--color-text-secondary)");
    expect(toggle).toContain("cursor: pointer");
    const glyph = find(normal, ".cv-audit-row__toggle-glyph", "width");
    expect(glyph).toContain("width: var(--size-icon-sm)");
    expect(glyph).toContain("height: var(--size-icon-sm)");
    expect(find(normal, '.cv-audit-row__toggle-glyph[data-glyph="check"]', "color")).toContain(
      "color: var(--color-text-primary)",
    );
  });

  it("high severity: a border.thick danger.strong rule on the row's first cell (D2)", () => {
    const rule = find(normal, `${ROW_HIGH} > .cv-audit-row__expander`, "border-inline-start");
    expect(rule).toContain(
      "border-inline-start: calc(var(--border-thick) * 1px) solid var(--color-status-danger-strong)",
    );
    expect(find(normal, `${ROW_HIGH} .cv-audit-row__severity`, "font-weight")).toContain(
      "font-weight: var(--font-weight-semibold)",
    );
  });

  it("the selected row keeps surface.selected; its words carry the state, never the fill (D14)", () => {
    const selected = find(
      normal,
      `${ROW}[aria-selected="true"] > .cv-audit-row__cell`,
      "background",
    );
    expect(selected).toContain("background: var(--color-surface-selected)");
  });

  it("times, IPs and codes in type.num.sm with tabular digits; meta in text.secondary, never tertiary", () => {
    const mono = find(normal, ".cv-audit-row__mono", "font");
    expect(mono).toContain("--type-num-sm-font-family");
    expect(mono).toContain("font-variant-numeric: tabular-nums");
    expect(mono).toContain("color: var(--color-text-secondary)");
    expect(find(normal, ".cv-audit-row__meta", "color")).toContain(
      "color: var(--color-text-secondary)",
    );
    expect(normal).not.toMatch(/\.cv-audit-row__(meta|mono|hidden)[^{]*\{[^}]*text-tertiary/);
  });

  it("the environment chip: a hairline border, LIVE's in env.live", () => {
    const chip = find(normal, ".cv-audit-row__env", "border");
    expect(chip).toContain(
      "border: calc(var(--border-hairline) * 1px) solid var(--color-border-default)",
    );
    expect(chip).toContain("border-radius: var(--radius-badge)");
    expect(find(normal, '.cv-audit-row__env[data-env="live"]', "border-color")).toContain(
      "border-color: var(--color-env-live)",
    );
  });

  it("Role and Action show their long words only in a wide column (E42-D04 §4: 2560), by container query", () => {
    const fit = find(normal, ".cv-audit-row__fit", "container-type");
    expect(fit).toContain("container-type: inline-size");
    expect(normal).toMatch(
      /@container \(min-width: 4\.5rem\) \{\s*\.cv-audit-row__fit\[data-fit="role"\] \.cv-audit-row__short \{\s*display: none;/,
    );
    expect(normal).toMatch(
      /@container \(min-width: 10rem\) \{\s*\.cv-audit-row__fit\[data-fit="action"\] \.cv-audit-row__long\.cv-visually-hidden \{/,
    );
    const long = find(normal, ".cv-audit-row__long.cv-visually-hidden", "clip-path");
    expect(long).toContain("position: static");
    expect(long).toContain("clip-path: none");
  });

  it("forced colours: the rule a CanvasText border (HighlightText when selected), the selected row Highlight", () => {
    expect(
      find(forced, `${ROW_HIGH} > .cv-audit-row__expander`, "border-inline-start-color"),
    ).toContain("border-inline-start-color: CanvasText");
    const selected = find(
      forced,
      `${ROW}[aria-selected="true"] > .cv-audit-row__cell`,
      "background",
    );
    expect(selected).toContain("background: Highlight");
    expect(selected).toContain("color: HighlightText");
    expect(
      find(
        forced,
        `${ROW_HIGH}[aria-selected="true"] > .cv-audit-row__expander`,
        "border-inline-start-color",
      ),
    ).toContain("border-inline-start-color: HighlightText");
    expect(find(forced, ".cv-audit-row__toggle-glyph", "color")).toContain("color: currentcolor");
    expect(find(forced, ".cv-audit-row__env", "border-color")).toContain(
      "border-color: CanvasText",
    );
  });
});

describe("auditrow.css, the diff part (E42-D04 §6, AD-5)", () => {
  it("one dl per field: the status word in its own column before the path, the values under the path", () => {
    expect(find(normal, ".cv-audit-diff", "color")).toContain("color: var(--color-text-primary)");
    const term = find(normal, ".cv-audit-diff__term", "display");
    expect(term).toContain("display: flex");
    expect(term).toContain("margin: 0");
    expect(find(normal, ".cv-audit-diff__status", "min-inline-size")).toMatch(
      /min-inline-size: [\d.]+rem/,
    );
    const path = find(normal, ".cv-audit-diff__path", "font");
    expect(path).toContain("--type-num-sm-font-family");
    expect(
      find(
        normal,
        ".cv-audit-diff__field[data-status] > .cv-audit-diff__desc",
        "margin-inline-start",
      ),
    ).toMatch(/margin-inline-start: calc\([\d.]+rem \+ var\(--space-inset-sm\)\)/);
  });

  it("Before, After and Requested: visible terms in text.secondary beside their values", () => {
    const values = find(normal, ".cv-audit-diff__values", "grid-template-columns");
    expect(values).toContain("display: grid");
    expect(values).toContain("grid-template-columns: max-content minmax(0, 1fr)");
    expect(values).toContain("margin: 0");
    expect(find(normal, ".cv-audit-diff__pair", "display")).toContain("display: contents");
    expect(find(normal, ".cv-audit-diff__values dt", "color")).toContain(
      "color: var(--color-text-secondary)",
    );
  });

  it("numbers and ids in type.num.sm; 'none' in text.tertiary; a kind's lock in text.secondary", () => {
    expect(find(normal, ".cv-audit-diff__value[data-mono]", "font")).toContain(
      "--type-num-sm-font-family",
    );
    expect(find(normal, '.cv-audit-diff__value[data-kind="none"]', "color")).toContain(
      "color: var(--color-text-tertiary)",
    );
    const lock = find(normal, ".cv-audit-diff__lock", "color");
    expect(lock).toContain("color: var(--color-text-secondary)");
    expect(lock).toContain("width: var(--size-icon-sm)");
  });

  it("AD-5's line: the octagon in danger.strong on danger.subtle, its words in text.primary", () => {
    const line = find(normal, ".cv-audit-diff__break", "background");
    expect(line).toContain("background: var(--color-status-danger-subtle)");
    expect(line).toContain("color: var(--color-text-primary)");
    expect(line).toContain("border-radius: var(--radius-control)");
    expect(find(normal, ".cv-audit-diff__break-glyph", "color")).toContain(
      "color: var(--color-status-danger-strong)",
    );
  });

  it("the inline form is a plain list", () => {
    const list = find(normal, '.cv-audit-diff[data-form="inline"]', "list-style");
    expect(list).toContain("list-style: none");
    expect(list).toContain("margin: 0");
    expect(list).toContain("padding: 0");
  });

  it("forced colours: the break line keeps a CanvasText edge; glyphs follow the text", () => {
    const line = find(forced, ".cv-audit-diff__break", "border");
    expect(line).toContain("border: 1px solid CanvasText");
    expect(find(forced, ".cv-audit-diff__break-glyph", "color")).toContain("color: currentcolor");
    expect(find(forced, ".cv-audit-diff__lock", "color")).toContain("color: currentcolor");
  });
});
