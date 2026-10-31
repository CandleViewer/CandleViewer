import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("watchlistrow.css");

// E08-D07 §7.1 (token map), §7.3 (DS-CR-1 and DS-CR-2 fallbacks while open), D30 (forced colours), §8 (one flip).
describe("watchlistrow.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("rows: the grid body on surface.raised, no zebra; hover surface.hover; the active row surface.selected", () => {
    expect(find(css.normal, ".cv-wl-row:nth-child(n)", "background")).toContain(
      "var(--color-surface-raised)",
    );
    expect(find(css.normal, ".cv-wl-row:hover", "background")).toContain(
      "var(--color-surface-hover)",
    );
    expect(find(css.normal, '.cv-wl-row[aria-current="true"]', "background")).toContain(
      "var(--color-surface-selected)",
    );
  });

  it("numbers: tabular type.num.sm when compact, type.num.base when comfortable", () => {
    const num = find(css.normal, ".cv-wl__num", "font");
    expect(num).toContain("var(--type-num-sm-font-family)");
    expect(num).toContain("font-variant-numeric: tabular-nums");
    expect(find(css.normal, '[data-density="comfortable"] .cv-wl__num', "font")).toContain(
      "var(--type-num-base-font-family)",
    );
  });

  it("the sign's colour rides on the ▲/▼ glyph only (DS-CR-2's fallback); values stay live text", () => {
    expect(find(css.normal, '.cv-wl__glyph[data-sign="positive"]', "color")).toContain(
      "var(--color-buy-default)",
    );
    expect(find(css.normal, '.cv-wl__glyph[data-sign="negative"]', "color")).toContain(
      "var(--color-sell-default)",
    );
    expect(find(css.normal, ".cv-wl__value", "color")).toBe("");
  });

  it("a stale row: the stale tint and demoted text on its cells, the glyph's hue dropped", () => {
    expect(
      find(
        css.normal,
        '.cv-wl-row[data-freshness="stale"]:not([aria-current="true"]) > *',
        "background",
      ),
    ).toContain("var(--color-data-confidence-stale-surface)");
    expect(find(css.normal, '.cv-wl-row[data-freshness="stale"] > *', "color")).toContain(
      "var(--color-data-confidence-stale-text)",
    );
    expect(find(css.normal, '.cv-wl-row[data-freshness="stale"] .cv-wl__glyph', "color")).toContain(
      "inherit",
    );
  });

  it("delisted: the symbol struck in delisted.text; the merged cell's glyph delisted.indicator", () => {
    const symbol = find(
      css.normal,
      '.cv-wl-row[data-row-state="delisted"] .cv-wl__symbol-text',
      "text-decoration",
    );
    expect(symbol).toContain("line-through");
    expect(
      find(css.normal, '.cv-wl-row[data-row-state="delisted"] .cv-wl__symbol', "color"),
    ).toContain("var(--color-data-confidence-delisted-text)");
    expect(find(css.normal, ".cv-wl__delisted", "color")).toContain(
      "var(--color-data-confidence-delisted-text)",
    );
    expect(find(css.normal, ".cv-wl__delisted-glyph", "color")).toContain(
      "var(--color-data-confidence-delisted-indicator)",
    );
  });

  it("disconnected (one container attribute): sunken, text.primary at opacity.muted on the text alone, no chip", () => {
    // Whitespace-folded: a long declaration may wrap.
    const row = find(
      css.normal,
      '[data-cv-feed="disconnected"] .cv-wl-row > *',
      "background",
    ).replace(/\s+/g, " ");
    expect(row).toContain("var(--color-surface-sunken)");
    expect(row).toMatch(
      /color-mix\( ?in srgb, var\(--color-text-primary\) calc\(var\(--opacity-muted\) \* 100%\), transparent ?\)/,
    );
    expect(css.all).not.toMatch(/(^|[\s;{])opacity\s*:/);
    expect(
      find(css.normal, '[data-cv-feed="disconnected"] .cv-wl__status > [data-cmp]', "display"),
    ).toContain("display: none");
  });

  it("the dash and the state tags in text.secondary; Rec's ⚠ warning.strong and its lock text.secondary", () => {
    expect(find(css.normal, ".cv-wl__dash", "color")).toContain("var(--color-text-secondary)");
    expect(find(css.normal, ".cv-wl__tag", "color")).toContain("var(--color-text-secondary)");
    expect(find(css.normal, ".cv-wl__rec-warning", "color")).toContain(
      "var(--color-status-warning-strong)",
    );
    expect(find(css.normal, ".cv-wl__rec-lock", "color")).toContain("var(--color-text-secondary)");
  });

  it("forced colours: tags keep a CanvasText border; glyphs CanvasText", () => {
    expect(find(css.forced, ".cv-wl__tag", "border")).toContain("CanvasText");
    expect(find(css.forced, ".cv-wl__glyph", "color")).toContain("CanvasText");
    expect(css.forced).not.toContain("var(--color");
  });
});
