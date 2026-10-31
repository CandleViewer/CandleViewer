// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";
import { shippedComponentsCss } from "./componentsCss.js";
import { Table, WatchlistRow, watchlistColumns, type WatchlistRowData } from "../src/index.js";
import { mount } from "./theme/mount.js";

const css = loadCss("freshness.css");

/** A state's cell rule: both classes `freshnessClassName` sets, so it out-specifies a host cell's own colour. */
const cell = (state: string): string => `.cv-freshness.cv-freshness--${state}`;

// E08-D07 §7.1 "Stale" and §5 (CMP-239's compact presentation): a class swap, tokens only, one flip (no motion).
describe("freshness.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("a stale cell: the stale tint, demoted text and a 2 px leading bar drawn without moving the text", () => {
    // Whitespace-folded: a long declaration may wrap.
    const stale = find(css.normal, cell("stale"), "background").replace(/\s+/g, " ");
    expect(stale).toContain("var(--color-data-confidence-stale-surface)");
    expect(stale).toContain("color: var(--color-data-confidence-stale-text)");
    expect(stale).toMatch(
      /box-shadow: inset calc\(var\(--border-thick\) \* 1px\) 0 0 0 var\(--color-data-confidence-stale-indicator\)/,
    );
  });

  it("every other degraded state binds its own data-confidence text token", () => {
    for (const state of [
      "reconnecting",
      "disconnected",
      "resyncing",
      "gapped",
      "backfilling",
      "delisted",
    ]) {
      expect(find(css.normal, cell(state), "color")).toContain(
        `var(--color-data-confidence-${state}-text)`,
      );
    }
  });

  it("the T1 chip: warning.subtle fill, a 1 px stale.indicator edge, text.primary, the badge radius", () => {
    const chip = find(css.normal, ".cv-freshness-chip", "background");
    expect(chip).toContain("var(--color-status-warning-subtle)");
    expect(chip).toContain(
      "border: calc(var(--border-hairline) * 1px) solid var(--color-data-confidence-stale-indicator)",
    );
    expect(chip).toContain("color: var(--color-text-primary)");
    expect(chip).toContain("var(--radius-badge)");
  });

  it("the T2 chip: the stale.indicator fill with text.inverse", () => {
    const strong = find(css.normal, '.cv-freshness-chip[data-level="strong"]', "background");
    expect(strong).toContain("var(--color-data-confidence-stale-indicator)");
    expect(strong).toContain("color: var(--color-text-inverse)");
  });

  it("forced colours: the bar becomes a CanvasText edge, the chip keeps a CanvasText border", () => {
    expect(find(css.forced, cell("stale"), "border-inline-start")).toContain("CanvasText");
    expect(find(css.forced, ".cv-freshness-chip", "border")).toContain("CanvasText");
    expect(css.forced).not.toContain("var(--color");
  });
});

/** The top-level rules of a stylesheet (an at-rule's block is skipped whole): each selector and its body. */
function topLevelRules(sheet: string): { readonly selector: string; readonly body: string }[] {
  const text = sheet.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules: { selector: string; body: string }[] = [];
  let depth = 0;
  let start = 0;
  let head = "";
  for (let i = 0; i < text.length; i += 1) {
    if (text[i] === "{") {
      if (depth === 0) {
        head = text.slice(start, i).trim();
        start = i + 1;
      }
      depth += 1;
    } else if (text[i] === "}") {
      depth -= 1;
      if (depth === 0) {
        if (!head.startsWith("@")) {
          for (const selector of head.split(/,(?![^(]*\))/))
            rules.push({ selector: selector.trim(), body: text.slice(start, i) });
        }
        start = i + 1;
      }
    }
  }
  return rules;
}

/** CSS specificity (ids, classes / attributes / pseudo-classes, types) of one selector: enough for these sheets. */
function specificity(selector: string): [number, number, number] {
  let rest = selector.replace(/::[\w-]+/g, "").replace(/:where\((?:[^()]|\([^()]*\))*\)/g, "");
  const total: [number, number, number] = [0, 0, 0];
  rest = rest.replace(/:(?:is|not|has)\(((?:[^()]|\([^()]*\))*)\)/g, (_, args: string) => {
    const best = args
      .split(/,(?![^(]*\))/)
      .map((arg) => specificity(arg.trim()))
      .sort((a, b) => b[0] - a[0] || b[1] - a[1] || b[2] - a[2])[0] ?? [0, 0, 0];
    total[0] += best[0];
    total[1] += best[1];
    total[2] += best[2];
    return " ";
  });
  total[0] += (rest.match(/#[\w-]+/g) ?? []).length;
  total[1] += (rest.match(/\.[\w-]+|\[[^\]]*\]|:[\w-]+(?:\([^)]*\))?/g) ?? []).length;
  total[2] += rest
    .replace(/\[[^\]]*\]|[.#:][\w-]+(?:\([^)]*\))?/g, " ")
    .split(/[\s>+~]+/)
    .filter((part) => /^[a-z][\w-]*$/i.test(part)).length;
  return total;
}

/** The `color` the cascade gives `element` from `sheet`'s top-level rules: highest specificity, then the last. */
function cascadedColor(sheet: string, element: Element): string | undefined {
  let winner: { readonly spec: [number, number, number]; readonly value: string } | undefined;
  for (const { selector, body } of topLevelRules(sheet)) {
    const value = /(?:^|;)\s*color\s*:\s*([^;]+)/.exec(body)?.[1]?.trim();
    if (value === undefined || selector.includes("::")) continue;
    let matches = false;
    try {
      matches = element.matches(selector);
    } catch {
      matches = false;
    }
    if (!matches) continue;
    const spec = specificity(selector);
    const [a, b, c] = winner?.spec ?? [-1, -1, -1];
    if (spec[0] > a || (spec[0] === a && (spec[1] > b || (spec[1] === b && spec[2] >= c))))
      winner = { spec, value };
  }
  return winner?.value;
}

// CR-4702A-01: copy-css concatenates by file name, so freshness.css precedes table.css in the shipped bundle; at
// equal specificity `.cv-table__cell`'s text.primary won and a stale OI cell kept its live colour in the app.
describe("freshness.css in the shipped components.css", () => {
  it("a stale OI cell of CMP-161 takes the stale text colour over CMP-049's cell colour", async () => {
    const btc: WatchlistRowData = {
      symbol: "BTCUSDT",
      priceScale: 2,
      openInterestChangePct24h: 2.1,
    };
    const columns = ["symbol", "oi_chg_24h_pct"] as const;
    const host = await mount(
      createElement(Table<WatchlistRowData>, {
        grid: true,
        caption: "Watchlist",
        columns: watchlistColumns(columns),
        rows: [btc],
        rowKey: (row) => row.symbol,
        renderRow: (row, grid) =>
          createElement(WatchlistRow, {
            grid,
            row,
            columns,
            freshness: { oiBaseline: { state: "stale" } },
          }),
      }),
    );
    const oi = host.querySelector('[data-column="oi_chg_24h_pct"]') as HTMLElement;
    expect(["cv-table__cell", "cv-freshness--stale"].map((c) => oi.classList.contains(c))).toEqual([
      true,
      true,
    ]);
    expect(cascadedColor(shippedComponentsCss(), oi)).toBe(
      "var(--color-data-confidence-stale-text)",
    );
  });
});
