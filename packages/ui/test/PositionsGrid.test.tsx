// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { expect, fireEvent, fn, userEvent, waitFor, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import {
  GatedAnnounceProvider,
  LiqTierCell,
  POSITIONS_GRID_COLUMNS,
  PositionsGrid,
  UpdatesPausedChip,
  liqSentence,
  type MenuItem,
  type PositionsGridGroup,
  type PositionsGridProps,
  type PositionsGridRow,
  type SplitButtonProps,
} from "../src/components/index.js";
import * as stories from "../src/components/PositionsGrid.stories.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

// CMP-114 PositionsGrid (E29-D04 §2.1, D04H §C.1 and §E; E29-D02 §5; E29-D05 §5–§7) on CMP-049's treegrid.

afterEach(() => {
  vi.restoreAllMocks();
});

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

const row = (
  label: string,
  symbol: string,
  overrides: Partial<PositionsGridRow> = {},
): PositionsGridRow => ({
  key: `${label}|${symbol}|0`,
  accountId: `id-${label}`,
  accountLabel: label,
  symbol,
  baseCoin: symbol.replace(/USDT$/, ""),
  side: "long",
  sideWord: "Long",
  hedge: false,
  size: "0.250",
  entry: "63980.0",
  mark: "64012.0",
  unrealisedPnl: "8.00",
  realisedToday: { value: "12.40" },
  r: { value: "0.32" },
  leverage: "10",
  marginMode: { value: "isolated" },
  liqPrice: "57901.9",
  liq: { tier: "none", distancePct: "9.5", sharePct: "101" },
  ...overrides,
});

const MAIN = row("Main", "BTCUSDT");
const SUB1_BTC = row("Sub-1", "BTCUSDT", { size: "0.100" });
const SUB1_ETH = row("Sub-1", "ETHUSDT", {
  side: "short",
  sideWord: "Short",
  hedge: true,
  size: "1.50",
  entry: "2480.00",
  mark: "2561.00",
  unrealisedPnl: "-121.50",
  realisedToday: { value: null },
  r: { value: null, reason: "no_stop" },
  liqPrice: null,
  marginMode: { value: "cross" },
  liq: { tier: "near", distancePct: null, mmRatePct: "72" },
});
const SUB2_SOL = row("Sub-2", "SOLUSDT", {
  size: "20.0",
  liq: { tier: "critical", distancePct: "0.5", sharePct: "14" },
});

const group = (
  key: string | null,
  label: string,
  rows: readonly PositionsGridRow[],
  extra: Partial<PositionsGridGroup> = {},
): PositionsGridGroup => ({
  key,
  label,
  positionMode: "one-way",
  rows,
  count: rows.length,
  unrealisedPnl: "8.00",
  realisedToday: "37.40",
  netSize: null,
  ...extra,
});

const GROUPS: readonly PositionsGridGroup[] = [
  group("main", "Main · LIVE", [MAIN]),
  group("sub-1", "Sub-1 · LIVE", [SUB1_BTC, SUB1_ETH], { positionMode: "hedge" }),
  group("sub-2", "Sub-2 · LIVE", [SUB2_SOL]),
];
const TOTALS = {
  label: "LIVE total",
  count: 4,
  exposure: "34322.66",
  unrealisedPnl: "-205.84",
  realisedToday: "34.40",
};

type HostProps = Partial<PositionsGridProps> & { readonly onSelect?: (keys: string[]) => void };

/** A host that owns the selection, as SCR-063's panel does. */
function Host({ onSelect, ...props }: HostProps): JSX.Element {
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  return (
    <PositionsGrid
      caption="Positions"
      groups={GROUPS}
      totals={TOTALS}
      selected={selected}
      onSelectionChange={(next) => {
        onSelect?.([...next]);
        setSelected(next);
      }}
      {...props}
    />
  );
}

const page = within(document.body);
const grid = (): HTMLElement => page.getByRole("treegrid", { name: "Positions" });
const rowNamed = (name: string | RegExp): HTMLElement => within(grid()).getByRole("row", { name });
/** The default grid's header cell for a column id (the select column first). */
const headerOf = (id: string): HTMLElement => {
  const found =
    grid().querySelectorAll<HTMLElement>("thead th")[
      ["select", ...POSITIONS_GRID_COLUMNS].indexOf(id)
    ];
  if (found === undefined) throw new Error(`no header ${id}`);
  return found;
};
/**
 * A span's `display` as a browser computes it: `inline`, its initial value, which jsdom leaves empty. Testing Library
 * joins an inline child's trimmed words to the text before it with no space and pads any other child, so an exact name
 * checked without this passes here and can fail in the Storybook project (CI-A11Y-002). `mount`'s cleanup removes it.
 */
const inlineSpans = (): void => {
  document.body.appendChild(document.createElement("style")).textContent =
    "span:not([hidden]) { display: inline; }";
};

describe("PositionsGrid (CMP-114): the treegrid", () => {
  it("marks one root with data-cmp and draws CMP-049's treegrid, named by its caption", async () => {
    const host = await mount(<Host />);
    expect(host.querySelectorAll('[data-cmp="CMP-114"]')).toHaveLength(1);
    expect(host.querySelectorAll('[data-cmp="CMP-049"]')).toHaveLength(1);
    expect(grid()).toHaveAttribute("aria-multiselectable", "true");
    // Header, 3 group rows, 4 positions, the totals row.
    expect(grid()).toHaveAttribute("aria-rowcount", "9");
  });

  it("groups at level 1, open, in their set; positions at level 2, in their group's (F-03)", async () => {
    await mount(<Host />);
    const rows = within(grid()).getAllByRole("row").slice(1, -1);
    expect(rows.map((r) => r.getAttribute("aria-level"))).toEqual([
      "1",
      "2",
      "1",
      "2",
      "2",
      "1",
      "2",
    ]);
    expect(rows[2]).toHaveAttribute("aria-expanded", "true");
    expect(rows[2]).toHaveAttribute("aria-posinset", "2");
    expect(rows[2]).toHaveAttribute("aria-setsize", "3");
    expect(rows[4]).toHaveAttribute("aria-posinset", "2");
    expect(rows[4]).toHaveAttribute("aria-setsize", "2");
    expect(rows[4]).not.toHaveAttribute("aria-expanded");
  });

  it("a row's name is its symbol, side, size and account (N-02); its box's, 'Select BTCUSDT Long on Main' (N-01)", async () => {
    await mount(<Host />);
    const main = rowNamed("BTCUSDT · Long · 0.250 BTC · Main");
    expect(main).toHaveAttribute("aria-selected", "false");
    expect(
      within(main).getByRole("checkbox", { name: "Select BTCUSDT Long on Main" }),
    ).not.toBeChecked();
    // The rowheader is the symbol (D02 D-1).
    expect(within(main).getByRole("rowheader", { name: "BTCUSDT" }).tagName).toBe("TH");
  });

  it("an account the directory does not name shows its id in place of a label", async () => {
    await mount(<Host groups={[group("x", "x", [{ ...MAIN, accountLabel: null }])]} />);
    expect(rowNamed("BTCUSDT · Long · 0.250 BTC · id-Main")).toBeInTheDocument();
  });

  it("draws the cells in D02 §5.1's words: side glyph hidden, hedge suffix, base coin, grouped figures, ×, margin", async () => {
    await mount(<Host />);
    const eth = rowNamed(/^ETHUSDT · Short/);
    const cells = within(eth).getAllByRole("gridcell");
    const text = cells.map((c) => c.textContent);
    expect(text).toContain("▼ Short · hedge");
    expect(eth.querySelector('[data-side="short"]')).toHaveAttribute("aria-hidden", "true");
    expect(text).toContain("1.50 ETH");
    expect(text).toContain("2,480.00");
    expect(text).toContain("10×");
    expect(text).toContain("Cross");
    // A null liquidation price is "—", read as Bybit's absence.
    expect(within(eth).getByText("no liquidation price from Bybit")).toHaveClass(
      "cv-visually-hidden",
    );
  });

  it("a null leverage or margin mode is a dash with its spoken reason (D-7)", async () => {
    await mount(
      <Host
        groups={[
          group("main", "Main · LIVE", [{ ...MAIN, leverage: null, marginMode: { value: null } }]),
        ]}
      />,
    );
    const main = rowNamed(/^BTCUSDT · Long · 0\.250/);
    for (const id of ["leverage", "margin"]) {
      const cell = main.querySelector<HTMLElement>(
        `[data-cv-c="${headerOf(id).getAttribute("data-cv-c") ?? ""}"]`,
      );
      expect(cell?.querySelector('[aria-hidden="true"]')?.textContent).toBe("—");
      expect(cell?.querySelector(".cv-visually-hidden")?.textContent).toBe("no value");
    }
  });

  it("one node carries a row's description, never two with one id; with no tier column, a hidden one", async () => {
    const sentence =
      "Critical — near liquidation: 14 % of the entry buffer left, 0.5 % from liquidation";
    await mount(<Host columns={[...POSITIONS_GRID_COLUMNS, "status"]} />);
    const both = rowNamed(/^SOLUSDT/);
    const id = both.getAttribute("aria-describedby") ?? "";
    expect(document.querySelectorAll(`[id="${id}"]`)).toHaveLength(1);
    expect(document.getElementById(id)?.closest("[data-part]")).toHaveAttribute(
      "data-part",
      "LiqTierCell",
    );
    expect(both).toHaveAccessibleDescription(sentence);
  });

  it("a host that hides both tier columns keeps the sentence as the row's description, out of its cells' names", async () => {
    await mount(<Host columns={["side", "size"]} />);
    const sol = rowNamed(/^SOLUSDT/);
    expect(sol).toHaveAccessibleDescription(
      "Critical — near liquidation: 14 % of the entry buffer left, 0.5 % from liquidation",
    );
    expect(document.getElementById(sol.getAttribute("aria-describedby") ?? "")).toHaveAttribute(
      "hidden",
    );
    expect(within(sol).getByRole("rowheader")).toHaveAccessibleName("SOLUSDT");
  });

  it("sets the plain numeric cells in type.num.base; CMP-116's cells and the words keep their own (D02 §12)", async () => {
    await mount(<Host />);
    const main = rowNamed(/^BTCUSDT · Long · 0\.250/);
    const cellOf = (id: string): HTMLElement | null =>
      main.querySelector<HTMLElement>(
        `[data-cv-c="${headerOf(id).getAttribute("data-cv-c") ?? ""}"]`,
      );
    const num = (id: string): boolean =>
      cellOf(id)?.classList.contains("cv-positions-grid__num") ?? false;
    expect(["size", "entry", "mark", "liq_price", "liq_dist", "leverage"].map(num)).toEqual([
      true,
      true,
      true,
      true,
      true,
      true,
    ]);
    expect(["account", "side", "upnl", "r", "rpnl_today", "margin"].map(num)).toEqual([
      false,
      false,
      false,
      false,
      false,
      false,
    ]);
  });

  it("every signed money cell is a CMP-116 badge; R and rPnL today read their absence", async () => {
    await mount(<Host />);
    const eth = rowNamed(/^ETHUSDT · Short/);
    const badges = eth.querySelectorAll('[data-cmp="CMP-116"]');
    expect(badges).toHaveLength(3);
    expect(within(eth).getByText("loss 121.50 USDT")).toBeInTheDocument();
    expect(within(eth).getByText("R unavailable: no stop price")).toBeInTheDocument();
    const main = rowNamed(/^BTCUSDT · Long · 0\.250/);
    expect(within(main).getByText("profit 0.32 R")).toBeInTheDocument();
    expect(within(main).getByText("profit 12.40 USDT")).toBeInTheDocument();
  });

  it.each([
    ["no_stop", "R unavailable: no stop price"],
    ["no_price", "R unavailable"],
    ["zero_distance", "R unavailable"],
    [undefined, "R unavailable"],
  ] as const)(
    "a null R with reason %s reads %j: D02's words only where the row has no stop (BQ-8)",
    async (reason, reading) => {
      const r = { value: null, ...(reason === undefined ? {} : { reason }) };
      await mount(<Host groups={[group("main", "Main · LIVE", [{ ...MAIN, r }])]} />);
      const main = rowNamed(/^BTCUSDT · Long · 0\.250/);
      const cell = main.querySelector<HTMLElement>(
        `[data-cv-c="${headerOf("r").getAttribute("data-cv-c") ?? ""}"]`,
      );
      expect(cell?.querySelector(".cv-visually-hidden")?.textContent).toBe(reading);
      expect(cell?.querySelector('[aria-hidden="true"]')?.textContent).toBe("—");
    },
  );

  it("pins the select column, Account and Symbol, and the Actions column when it shows", async () => {
    await mount(<Host rowActions={() => undefined} />);
    const pins = [...grid().querySelectorAll("thead th")].map((th) =>
      th.hasAttribute("data-pin-end") ? "end" : th.getAttribute("data-pin-start"),
    );
    expect(pins.slice(0, 4)).toEqual(["0", "1", "2", null]);
    expect(pins.at(-1)).toBe("end");
  });

  it("takes D02 §5.1's widths per density, in em of a 16 px table", async () => {
    const compact = await mount(<Host />);
    const widths = [...compact.querySelectorAll("col")].map((col) => col.style.width);
    expect(widths.slice(0, 4)).toEqual(["1.5em", "6em", "6em", "5em"]);
    const comfortable = await mount(<Host density="comfortable" />);
    const wider = [...comfortable.querySelectorAll("col")].map((col) => col.style.width);
    expect(wider.slice(0, 4)).toEqual(["2em", "6.5em", "6.5em", "5.5em"]);
  });

  it("keeps Account and Symbol first, whatever the host's columns", async () => {
    await mount(<Host columns={["upnl", "symbol", "side"]} />);
    const names = [...grid().querySelectorAll("thead th")].map((th) => th.textContent);
    expect(names).toEqual(["Select", "Account", "Symbol", "uPnL (USDT)", "Side"]);
  });

  it("sorts through CMP-049: sortable headers but Status, with aria-sort", async () => {
    const onSortChange = vi.fn();
    await mount(
      <Host sort={{ columnId: "upnl", direction: "descending" }} onSortChange={onSortChange} />,
    );
    const upnl = within(grid()).getByRole("columnheader", { name: "uPnL (USDT)" });
    expect(upnl).toHaveAttribute("aria-sort", "descending");
    await userEvent.click(within(upnl).getByRole("button"));
    expect(onSortChange).toHaveBeenCalledWith({ columnId: "upnl", direction: "ascending" });
  });

  /** Ten accounts of nine positions: 100 rows, windowed. */
  const MANY = Array.from({ length: 10 }, (_, g) =>
    group(
      `a${String(g)}`,
      `Account ${String(g)} · LIVE`,
      Array.from({ length: 9 }, (_, i) => row(`A${String(g)}`, `P${String(i)}USDT`)),
    ),
  );

  // Measured 1.8 to 6.2 s at a load of 21 to 31 on 8 cores (four runs here), 4.3 s at most in the delta lens' runs
  // at 23 to 38: past the 5 s default on a loaded host, so a measured 30 s ceiling, as the story loop's below.
  it(
    "windows past 50 rows; a key past the window asks for its row and lands there",
    { timeout: 30_000 },
    async () => {
      await mount(<Host groups={MANY} totals={undefined} />);
      expect(grid()).toHaveAttribute("aria-rowcount", "101");
      // The first window: 30 rows before the region reports, and 10 past them.
      expect(within(grid()).getAllByRole("row")).toHaveLength(41);
      act(() =>
        within(rowNamed("P0USDT · Long · 0.250 P0 · A0")).getAllByRole("gridcell")[1]?.focus(),
      );
      await userEvent.keyboard("{Control>}{End}{/Control}");
      expect(document.activeElement?.closest("tr")).toHaveAttribute("aria-rowindex", "101");
    },
  );

  /**
   * A laid-out region of 240 px under a 24 px header, rows 24 px tall: nine rows in view. `scrollTo` scrolls it by
   * whole rows and reports the scroll, as the region's own event does.
   */
  const layOut = (): { readonly scrollTo: (row: number) => void } => {
    let scroll = 0;
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
      this: HTMLElement,
    ) {
      const height = this.tagName === "TR" || this.tagName === "THEAD" ? 24 : 0;
      const top = this.tagName === "TBODY" ? 24 - scroll : 0;
      return {
        top,
        height,
        bottom: top + height,
        left: 0,
        right: 0,
        width: 0,
        x: 0,
        y: top,
      } as DOMRect;
    });
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(240);
    vi.spyOn(HTMLElement.prototype, "scrollTop", "get").mockImplementation(() => scroll);
    return {
      scrollTo: (row) => {
        scroll = row * 24;
        act(() => {
          grid().closest(".cv-table__region")?.dispatchEvent(new Event("scroll"));
        });
      },
    };
  };

  // Measured 2.3 to 10.7 s at a load of 21 to 31 on 8 cores (four runs here), 10.6 s in the delta lens' runs at
  // 23 to 38: twice the 5 s default on a loaded host, so a measured 30 s ceiling, as the story loop's below.
  it(
    "keeps the focused row mounted when the region scrolls the window away from it (G-01)",
    { timeout: 30_000 },
    async () => {
      const region = layOut();
      await mount(<Host groups={MANY} totals={undefined} />);
      // The mount's measured view (rows 0 to 8) sits inside the first window: nothing is drawn again.
      expect(within(grid()).getAllByRole("row")).toHaveLength(41);
      const first = rowNamed("P0USDT · Long · 0.250 P0 · A0");
      const cell = within(first).getAllByRole("gridcell")[1];
      act(() => cell?.focus());
      region.scrollTo(50);
      // Rows 50 to 58 are past the drawn rows: the window draws 40 to 68, and the focused row stays outside it.
      expect(document.activeElement).toBe(cell);
      expect(first.isConnected).toBe(true);
      expect(first).toHaveAttribute("aria-rowindex", "3");
      const drawn = within(grid()).getAllByRole("row").slice(1);
      expect(drawn).toHaveLength(30);
      expect(drawn[0]).toBe(first);
      expect(drawn[1]).toHaveAttribute("aria-rowindex", "42");
    },
  );

  // Measured 2.7 s before its top-edge steps and 3.2 to 4.3 s with them (three runs), at a load of 21 to 31 on 8 cores;
  // 10.4 s in the delta lens' runs at 23 to 38: twice the 5 s default on a loaded host, so a measured 30 s ceiling, as
  // the story loop's below.
  it(
    "re-windows while half the overscan is still drawn past the view, before any undrawn row shows",
    { timeout: 30_000 },
    async () => {
      const region = layOut();
      await mount(<Host groups={MANY} totals={undefined} />);
      // Rows 26 to 34 in view: five drawn rows (35 to 39) still lie past them, so the window holds.
      region.scrollTo(26);
      expect(within(grid()).getAllByRole("row")).toHaveLength(41);
      // Rows 27 to 35: within five of the drawn end, the window re-centres on them (17 to 45) while 39 is drawn.
      region.scrollTo(27);
      const drawn = (): HTMLElement[] => within(grid()).getAllByRole("row").slice(1);
      let rows = drawn();
      expect(rows).toHaveLength(29);
      expect(rows[0]).toHaveAttribute("aria-rowindex", "19");
      expect(rows.at(-1)).toHaveAttribute("aria-rowindex", "47");
      // The top edge keeps the same margin: rows 22 to 30 leave five drawn rows (17 to 21) above, so the window holds.
      region.scrollTo(22);
      rows = drawn();
      expect(rows).toHaveLength(29);
      expect(rows[0]).toHaveAttribute("aria-rowindex", "19");
      expect(rows.at(-1)).toHaveAttribute("aria-rowindex", "47");
      // Rows 21 to 29: within five of the drawn start, the window re-centres on them (11 to 39) while 17 to 20 show.
      region.scrollTo(21);
      rows = drawn();
      expect(rows).toHaveLength(29);
      expect(rows[0]).toHaveAttribute("aria-rowindex", "13");
      expect(rows.at(-1)).toHaveAttribute("aria-rowindex", "41");
      // Back at the top, the list's own first row is no edge to keep clear of.
      region.scrollTo(0);
      expect(drawn()[0]).toHaveAttribute("aria-rowindex", "2");
    },
  );
});

describe("PositionsGrid (CMP-114): LiqTierCell (D02 §5.3)", () => {
  it.each([
    ["watch", "△ Watch 2.1", "Watch: 46 % of the entry buffer left, 2.1 % from liquidation"],
    [
      "near",
      "! Near 1.2",
      "Near liquidation: 27 % of the entry buffer left, 1.2 % from liquidation",
    ],
    [
      "critical",
      "!! Critical 0.5",
      "Critical — near liquidation: 14 % of the entry buffer left, 0.5 % from liquidation",
    ],
  ] as const)(
    "%s: glyph, word and distance, the D5 label as its sentence",
    async (tier, shown, sentence) => {
      const distance = tier === "watch" ? "2.1" : tier === "near" ? "1.2" : "0.5";
      const share = tier === "watch" ? "46" : tier === "near" ? "27" : "14";
      const host = await mount(
        <LiqTierCell liq={{ tier, distancePct: distance, sharePct: share }} sentenceId="s" />,
      );
      const cell = host.querySelector<HTMLElement>('[data-part="LiqTierCell"]');
      expect(cell).toHaveAttribute("data-tier", tier);
      const visible = cell?.querySelector('[aria-hidden="true"]');
      expect(visible?.textContent).toBe(shown);
      expect(host.querySelector("#s")).toHaveTextContent(sentence);
      expect(host.querySelector("#s")).toHaveClass("cv-visually-hidden");
    },
  );

  it("no tier shows the distance alone; no liquidation price a dash read as Bybit's absence", async () => {
    const host = await mount(<LiqTierCell liq={{ tier: "none", distancePct: "9.5" }} />);
    expect(host.textContent).toBe("9.5");
    const none = await mount(<LiqTierCell liq={{ tier: "none", distancePct: null }} />);
    expect(within(none).getByText("—")).toHaveAttribute("aria-hidden", "true");
    expect(within(none).getByText("no liquidation price from Bybit")).toBeInTheDocument();
  });

  it("the status form (the dock's Status) keeps the glyph and the word, not the distance", async () => {
    const host = await mount(
      <LiqTierCell liq={{ tier: "near", distancePct: "1.2", sharePct: "27" }} form="status" />,
    );
    expect(host.querySelector('[aria-hidden="true"]')?.textContent).toBe("! Near");
    const none = await mount(
      <LiqTierCell liq={{ tier: "none", distancePct: "9.5" }} form="status" />,
    );
    expect(none.textContent).toBe("");
  });

  it("names the account's margin rate for a cross position, and the distance alone where only it is known", () => {
    expect(liqSentence({ tier: "near", distancePct: "1.2", mmRatePct: "72" })).toBe(
      "Near liquidation: account margin rate 72 %, 1.2 % from liquidation",
    );
    expect(liqSentence({ tier: "critical", distancePct: "0.8" })).toBe(
      "Critical — near liquidation: 0.8 % from liquidation",
    );
    expect(liqSentence({ tier: "watch", distancePct: null })).toBe("Watch");
    expect(liqSentence({ tier: "none", distancePct: "9.5" })).toBeUndefined();
  });

  it("a tiered row is described by its sentence and echoes it; a Critical row carries the accent's hook", async () => {
    await mount(<Host />);
    const sol = rowNamed(/^SOLUSDT/);
    expect(sol).toHaveAccessibleDescription(
      "Critical — near liquidation: 14 % of the entry buffer left, 0.5 % from liquidation",
    );
    expect(sol).toHaveAttribute("data-liq", "critical");
    const cell = sol.querySelector('[data-part="LiqTierCell"]')?.closest("td");
    expect(cell).toHaveAttribute("data-cv-echo", expect.stringMatching(/^Critical/));
    expect(rowNamed(/^BTCUSDT · Long · 0\.250/)).not.toHaveAttribute("aria-describedby");
  });
});

describe("PositionsGrid (CMP-114): GroupHeaderRow (D02 §5.5)", () => {
  it("reads the label, the mode, the count, uPnL and rPnL today in its one rowheader", async () => {
    await mount(<Host />);
    const header = within(grid()).getByRole("rowheader", { name: /^Sub-1 · LIVE/ });
    expect(header).toHaveAttribute("colspan", "14");
    expect(header.closest("tr")).toHaveAttribute("data-part", "GroupHeaderRow");
    expect(header).toHaveAccessibleName(
      "Sub-1 · LIVE · Hedge · 2 positions · uPnL profit 8.00 USDT · rPnL today profit 37.40 USDT",
    );
    expect(header.querySelector('[data-cmp="CMP-129"]')).toHaveTextContent("Hedge");
    expect(
      within(grid()).getByRole("rowheader", { name: /^Main · LIVE · One-way · 1 position · / }),
    ).toBeInTheDocument();
  });

  it("shows the net size only for a group on one symbol (#911 BQ-12)", async () => {
    await mount(
      <Host
        groups={[
          group("tg", "Trade group 4f2a9c", [MAIN, SUB1_BTC], {
            netSize: "0.350",
            positionMode: undefined,
          }),
          group(null, "No trade group", [SUB1_ETH], { positionMode: undefined }),
        ]}
      />,
    );
    expect(
      within(grid()).getByRole("rowheader", { name: /^Trade group 4f2a9c/ }),
    ).toHaveTextContent("Trade group 4f2a9c · 2 positions · net 0.350 BTC · uPnL");
    expect(
      within(grid()).getByRole("rowheader", { name: /^No trade group/ }),
    ).not.toHaveTextContent("net");
  });

  it("← closes a group and → opens it again by its header, focus kept; a click toggles too", async () => {
    await mount(<Host />);
    const header = within(grid()).getByRole("rowheader", { name: /^Sub-1 · LIVE/ });
    act(() => header.focus());
    await userEvent.keyboard("{ArrowLeft}");
    expect(header.closest("tr")).toHaveAttribute("aria-expanded", "false");
    expect(within(grid()).queryByRole("row", { name: /^ETHUSDT/ })).toBeNull();
    expect(header).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}");
    expect(header.closest("tr")).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(header);
    expect(header.closest("tr")).toHaveAttribute("aria-expanded", "false");
  });

  it("controlled: the host's closed groups, and the next set asked of it", async () => {
    const onCollapsedChange = vi.fn();
    await mount(<Host collapsed={new Set(["main"])} onCollapsedChange={onCollapsedChange} />);
    const main = within(grid()).getByRole("rowheader", { name: /^Main · LIVE/ });
    expect(main.closest("tr")).toHaveAttribute("aria-expanded", "false");
    act(() => main.focus());
    await userEvent.keyboard("{ArrowRight}");
    expect(onCollapsedChange).toHaveBeenCalledWith(new Set());
    // The host did not apply it: the group stays closed.
    expect(main.closest("tr")).toHaveAttribute("aria-expanded", "false");
  });

  it("an account's state marker follows the header's figures, in its name (D02 §5.5, §10.2; BQ-14)", async () => {
    await mount(
      <Host groups={[group("main", "Main · LIVE", [MAIN], { marker: <span>checking</span> })]} />,
    );
    expect(
      within(grid()).getByRole("rowheader", { name: /^Main · LIVE · One-way · 1 position · / }),
    ).toHaveAccessibleName(
      "Main · LIVE · One-way · 1 position · uPnL profit 8.00 USDT · rPnL today profit 37.40 USDT · checking",
    );
  });

  it("a group of the positions with no trade group is keyed apart", async () => {
    await mount(<Host groups={[group(null, "No trade group", [MAIN])]} />);
    const header = within(grid()).getByRole("rowheader", { name: /^No trade group/ });
    act(() => header.focus());
    await userEvent.keyboard("{ArrowLeft}");
    expect(header.closest("tr")).toHaveAttribute("aria-expanded", "false");
  });
});

describe("PositionsGrid (CMP-114): TotalsRow (D02 §5.2, D-15)", () => {
  it("is CMP-049's trailing rowgroup, led by its rowheader with the count and the exposure", async () => {
    await mount(<Host />);
    const groups = within(grid()).getAllByRole("rowgroup");
    const totals = groups.at(-1);
    expect(totals).toHaveClass("cv-table__totals");
    const header = within(totals ?? grid()).getByRole("rowheader");
    expect(header).toHaveTextContent("LIVE total · 4 open · Exposure 34,322.66 USDT");
    expect(header.closest("tr")).toHaveAttribute("data-part", "TotalsRow");
  });

  it("puts uPnL and rPnL today under their own columns, never a summed size", async () => {
    await mount(<Host />);
    const totals = grid().querySelector<HTMLElement>(".cv-table__totals tr");
    const at = (id: string): string | null => headerOf(id).getAttribute("data-cv-c");
    const cellAt = (c: string | null): HTMLElement | null =>
      totals?.querySelector<HTMLElement>(`[data-cv-c="${c ?? ""}"]`) ?? null;
    expect(cellAt(at("upnl"))).toHaveTextContent("loss 205.84 USDT");
    expect(cellAt(at("rpnl_today"))).toHaveTextContent("profit 34.40 USDT");
    expect(totals?.textContent).not.toContain("BTC");
    // The label spans the columns before uPnL; every column is covered once.
    const spans = [...(totals?.children ?? [])].map((cell) =>
      Number(cell.getAttribute("colspan") ?? 1),
    );
    expect(spans.reduce((sum, n) => sum + n, 0)).toBe(14);
  });

  it("without the money columns the label spans every column", async () => {
    await mount(<Host columns={["side", "size"]} />);
    const totals = grid().querySelector<HTMLElement>(".cv-table__totals tr");
    expect(totals?.children).toHaveLength(1);
    expect(totals?.firstElementChild).toHaveAttribute("colspan", "5");
  });

  it("an exposure the host cannot sum reads as a dash", async () => {
    await mount(<Host totals={{ ...TOTALS, exposure: null }} />);
    expect(grid().querySelector(".cv-table__totals th")).toHaveTextContent("Exposure — USDT");
  });

  it("D-15's Net is the row's tooltip and description, the label's name its own", async () => {
    inlineSpans();
    await mount(<Host totals={{ ...TOTALS, net: "-1234.5" }} />);
    const header = within(grid()).getByRole("rowheader", {
      name: "LIVE total · 4 open · Exposure 34,322.66 USDT",
    });
    expect(header.closest("tr")).toHaveAccessibleDescription("Net −1,234.5 USDT");
    expect(header).toHaveAttribute("data-cv-echo", "Net −1,234.5 USDT");
  });

  it("without Net, and every total in its column, the row has no tooltip and no description", async () => {
    await mount(<Host />);
    const header = within(grid()).getByRole("rowheader", { name: /^LIVE total/ });
    expect(header.closest("tr")).not.toHaveAttribute("aria-describedby");
    expect(header).not.toHaveAttribute("data-cv-echo");
  });

  it("a total whose column is not shown moves to the tooltip and description, read as CMP-116 reads it", async () => {
    await mount(<Host columns={["side", "size"]} totals={{ ...TOTALS, realisedToday: null }} />);
    const header = within(grid()).getByRole("rowheader", { name: /^LIVE total/ });
    expect(header.closest("tr")).toHaveAccessibleDescription(
      "uPnL loss 205.84 USDT · rPnL today no value",
    );
    expect(header).toHaveAttribute("data-cv-echo", "uPnL −205.84 USDT · rPnL today — USDT");
  });
});

describe("PositionsGrid (CMP-114): selection (D-3)", () => {
  it("the box and Space on a cell toggle the row; Ctrl+A selects every position, closed groups' too", async () => {
    const onSelect = vi.fn();
    await mount(<Host onSelect={onSelect} collapsed={new Set(["sub-2"])} />);
    const main = rowNamed(/^BTCUSDT · Long · 0\.250/);
    await userEvent.click(within(main).getByRole("checkbox"));
    expect(onSelect).toHaveBeenLastCalledWith([MAIN.key]);
    expect(main).toHaveAttribute("aria-selected", "true");
    const account = within(main).getAllByRole("gridcell")[1];
    act(() => account?.focus());
    await userEvent.keyboard(" ");
    expect(onSelect).toHaveBeenLastCalledWith([]);
    await userEvent.keyboard("{Control>}a{/Control}");
    expect(onSelect).toHaveBeenLastCalledWith([MAIN.key, SUB1_BTC.key, SUB1_ETH.key, SUB2_SOL.key]);
  });

  it("Space on a group header or the totals selects nothing and never scrolls; Ctrl+A there selects all", async () => {
    const onSelect = vi.fn();
    await mount(<Host onSelect={onSelect} />);
    const header = within(grid()).getByRole("rowheader", { name: /^Main · LIVE/ });
    act(() => header.focus());
    await userEvent.keyboard(" ");
    expect(onSelect).not.toHaveBeenCalled();
    // Handled, so the region does not scroll a page as an unhandled Space would (CMP-049's rule).
    expect(fireEvent.keyDown(header, { key: " " })).toBe(false);
    const totalCell = grid().querySelector<HTMLElement>(".cv-table__totals th");
    expect(fireEvent.keyDown(totalCell as HTMLElement, { key: " " })).toBe(false);
    expect(onSelect).not.toHaveBeenCalled();
    const total = grid().querySelector<HTMLElement>(".cv-table__totals th");
    act(() => total?.focus());
    await userEvent.keyboard("{Control>}A{/Control}");
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("without onSelectionChange there is no select column and no multiselection", async () => {
    await mount(<PositionsGrid caption="Positions" groups={GROUPS} />);
    expect(grid()).not.toHaveAttribute("aria-multiselectable");
    expect(page.queryAllByRole("checkbox")).toHaveLength(0);
    expect(rowNamed(/^BTCUSDT · Long · 0\.250/)).not.toHaveAttribute("aria-selected");
  });
});

/** The ▾ items of a Positions row (D02 §8.1). */
const closeItems = (reason?: string): MenuItem[] =>
  ["Close 25 %", "Reverse…", "SL/TP…"]
    .map((label): MenuItem => ({
      id: label,
      label,
      onSelect: fn(),
      ...(reason === undefined ? {} : { disabledReason: reason }),
    }))
    .concat({ id: "chart", label: "Chart", onSelect: fn() });

describe("PositionsGrid (CMP-114): the Actions column (CMP-057) and T2", () => {
  const VIEWER = "Your role can't change positions.";

  /** A Viewer's grid (D02 §10.4): one notice, every Close described by it (G-T2.5). */
  function Viewer({ onClose }: { readonly onClose: () => void }): JSX.Element {
    return (
      <>
        <p id="notice">{VIEWER}</p>
        <Host
          rowActions={(r): SplitButtonProps => ({
            primary: { label: "Close", onClick: onClose },
            items: closeItems(VIEWER),
            menuLabel: `More close actions, ${r.symbol} ${r.sideWord} on ${r.accountLabel ?? ""}`,
            disabledReason: VIEWER,
            disabledReasonId: "notice",
          })}
        />
      </>
    );
  }

  it("the T2 test: role and full label, aria-disabled never disabled, the notice in the DOM at mount, nothing sent", async () => {
    const onClose = vi.fn();
    const announce = vi.fn();
    const host = await mount(
      <GatedAnnounceProvider announce={announce}>
        <Viewer onClose={onClose} />
      </GatedAnnounceProvider>,
    );
    const closes = within(grid()).getAllByRole("button", { name: "Not available Close" });
    expect(closes).toHaveLength(4);
    for (const close of closes) {
      expect(close).toHaveAttribute("aria-disabled", "true");
      expect(close).not.toBeDisabled();
      expect(close).toHaveAttribute("aria-describedby", "notice");
      expect(close).toHaveAccessibleDescription(VIEWER);
    }
    // One notice, many pointers: the reason's words are in the DOM once.
    expect(within(host).getAllByText(VIEWER)).toHaveLength(1);
    await userEvent.click(closes[0] as HTMLElement);
    expect(onClose).not.toHaveBeenCalled();
    expect(announce).toHaveBeenCalledTimes(1);
    expect(announce).toHaveBeenCalledWith(VIEWER);
  });

  it("the T2 control stays in the roving grid: Enter reaches it, Enter on it sends nothing, ↑ / ↓ keep moving", async () => {
    const onClose = vi.fn();
    await mount(<Viewer onClose={onClose} />);
    const main = rowNamed(/^BTCUSDT · Long · 0\.250/);
    const cell = main.querySelector<HTMLElement>(".cv-positions-grid__actions");
    act(() => cell?.focus());
    await userEvent.keyboard("{Enter}");
    const close = within(main).getByRole("button", { name: "Not available Close" });
    expect(close).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(onClose).not.toHaveBeenCalled();
    await userEvent.keyboard("{ArrowRight}");
    expect(within(main).getByRole("button", { name: /^More close actions/ })).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(close).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(cell).toHaveFocus();
  });

  it("the row menu (Shift+F10) repeats the primary first, its gate as the item's second line", async () => {
    await mount(<Viewer onClose={vi.fn()} />);
    const main = rowNamed(/^BTCUSDT · Long · 0\.250/);
    act(() => within(main).getAllByRole("gridcell")[1]?.focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    const menu = await page.findByRole("menu", { name: "Actions for BTCUSDT Long on Main" });
    const items = within(menu).getAllByRole("menuitem");
    expect(items[0]).toHaveAccessibleName(/\bClose$/);
    expect(items[0]).toHaveAttribute("aria-disabled", "true");
    expect(within(menu).getByRole("menuitem", { name: "Chart" })).not.toHaveAttribute(
      "aria-disabled",
    );
  });

  it("an allowed Close sends from the actions cell; busy keeps its label and is never T2", async () => {
    const onClose = vi.fn();
    await mount(
      <Host
        rowActions={(r): SplitButtonProps => ({
          primary: { label: "Close", busyLabel: "Closing…", onClick: onClose },
          items: closeItems(),
          menuLabel: `More close actions, ${r.symbol}`,
          busy: r.symbol === "SOLUSDT",
        })}
      />,
    );
    await userEvent.click(
      within(rowNamed(/^BTCUSDT · Long · 0\.250/)).getByRole("button", { name: "Close" }),
    );
    expect(onClose).toHaveBeenCalledTimes(1);
    const busy = within(rowNamed(/^SOLUSDT/)).getByRole("button", { name: "Closing…" });
    expect(busy).toHaveAttribute("aria-busy", "true");
    expect(busy).not.toHaveAttribute("aria-disabled");
  });

  it("a group header leaves its Actions cell empty (Flatten account… mounts with BQ-3's ticket)", async () => {
    await mount(<Host rowActions={() => undefined} />);
    const header = within(grid()).getByRole("rowheader", { name: /^Main · LIVE/ });
    expect(header.closest("tr")?.querySelectorAll("button")).toHaveLength(0);
  });

  it("the row menu's Close is busy with the primary: its busy label, aria-busy, and it sends nothing; a gate wins", async () => {
    const onClose = vi.fn();
    await mount(
      <Host
        rowActions={(r): SplitButtonProps => ({
          primary: { label: "Close", busyLabel: "Closing…", onClick: onClose },
          items: closeItems(),
          menuLabel: `More close actions, ${r.symbol}`,
          busy: r.symbol !== "BTCUSDT",
          ...(r.symbol === "ETHUSDT"
            ? { disabledReason: "Your role can't change positions." }
            : {}),
        })}
      />,
    );
    const menuOf = async (row: HTMLElement, name: string): Promise<HTMLElement> => {
      act(() => within(row).getAllByRole("gridcell")[1]?.focus());
      await userEvent.keyboard("{Shift>}{F10}{/Shift}");
      return page.findByRole("menu", { name });
    };
    const sol = await menuOf(rowNamed(/^SOLUSDT/), "Actions for SOLUSDT Long on Sub-2");
    const busy = within(sol).getAllByRole("menuitem")[0];
    expect(busy).toHaveAccessibleName("Closing…");
    expect(busy).toHaveAttribute("aria-busy", "true");
    expect(busy).not.toHaveAttribute("aria-disabled");
    // CMP-041 moves focus in from a passive effect, which can run after the menu is found.
    await waitFor(() => expect(busy).toHaveFocus());
    await userEvent.keyboard("{Enter}");
    await userEvent.click(busy as HTMLElement);
    expect(onClose).not.toHaveBeenCalled();
    await userEvent.keyboard("{Escape}");
    // Busy and gated: the reason wins, as on the button (CMP-057, CMP-041).
    const eth = await menuOf(rowNamed(/^ETHUSDT · Short/), "Actions for ETHUSDT Short on Sub-1");
    const gated = within(eth).getAllByRole("menuitem")[0];
    expect(gated).toHaveAccessibleName("Close");
    expect(gated).toHaveAttribute("aria-disabled", "true");
    expect(gated).not.toHaveAttribute("aria-busy");
    // Gated, Enter sends nothing either.
    await waitFor(() => expect(gated).toHaveFocus());
    await userEvent.keyboard("{Enter}");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("a group header offers no row menu: Shift+F10 and a right-click there open nothing", async () => {
    await mount(
      <Host
        rowActions={(r): SplitButtonProps => ({
          primary: { label: "Close", onClick: vi.fn() },
          items: closeItems(),
          menuLabel: `More close actions, ${r.symbol}`,
        })}
      />,
    );
    const header = within(grid()).getByRole("rowheader", { name: /^Main · LIVE/ });
    act(() => header.focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    expect(page.queryByRole("menu")).toBeNull();
    await userEvent.pointer({ keys: "[MouseRight]", target: header });
    expect(page.queryByRole("menu")).toBeNull();
    // A position's row still opens its own.
    await userEvent.pointer({
      keys: "[MouseRight]",
      target: within(rowNamed(/^BTCUSDT · Long · 0\.250/)).getAllByRole(
        "gridcell",
      )[1] as HTMLElement,
    });
    expect(
      await page.findByRole("menu", { name: "Actions for BTCUSDT Long on Main" }),
    ).toBeInTheDocument();
  });
});

describe("PositionsGrid (CMP-114): the narrow dock (D02 §11.5)", () => {
  it("Symbol · Side · Size · uPnL · Status; the units in the names; no Actions column", async () => {
    const host = await mount(<Host variant="narrow" rowActions={() => undefined} />);
    const names = within(grid())
      .getAllByRole("columnheader")
      .map((th) => th.textContent);
    expect(names).toEqual(["Select", "Symbol", "Side", "Size", "uPnL (USDT)", "Status"]);
    expect(host.querySelector('[data-cmp="CMP-114"]')).toHaveAttribute("data-variant", "narrow");
    const eth = rowNamed(/^ETHUSDT · Short/);
    expect(eth.textContent).toContain("▼ Short");
    expect(eth.textContent).not.toContain("hedge");
    expect(within(eth).getByText(" ETH", { normalizer: (s) => s })).toHaveClass(
      "cv-visually-hidden",
    );
    expect(eth.querySelector('[data-part="LiqTierCell"]')?.textContent).toContain("! Near");
    expect(host.querySelector(".cv-positions-grid__actions")).toBeNull();
  });

  it("the totals keep their label, count and uPnL; the exposure and rPnL today are the row's tooltip and description", async () => {
    inlineSpans();
    await mount(<Host variant="narrow" />);
    // The name is the label and the count alone: no figure is cut where the label cell ends (D-8).
    const header = within(grid()).getByRole("rowheader", { name: "LIVE total · 4 open" });
    expect(header.querySelector(".cv-positions-grid__totals-span")?.textContent).toBe("· 4 open");
    const row = header.closest("tr");
    expect(row).toHaveAccessibleDescription(
      "Exposure 34,322.66 USDT · rPnL today profit 34.40 USDT",
    );
    expect(header).toHaveAttribute(
      "data-cv-echo",
      "Exposure 34,322.66 USDT · rPnL today +34.40 USDT",
    );
    expect(row?.querySelector('[data-cmp="CMP-116"]')).toHaveTextContent("loss 205.84 USDT");
  });

  it("the uPnL header keeps (USDT) in its name and in its tooltip (D-7, §11.5)", async () => {
    vi.useFakeTimers();
    try {
      await mount(<Host variant="narrow" />);
      const upnl = within(grid()).getByRole("columnheader", { name: "uPnL (USDT)" });
      expect(upnl.querySelector(".cv-table__label")?.firstChild?.textContent).toBe("uPnL");
      act(() => {
        fireEvent.pointerOver(upnl);
      });
      act(() => {
        vi.advanceTimersByTime(300);
      });
      const echo = document.querySelector('.cv-table__echo[data-cmp="CMP-016"]');
      expect(echo).not.toHaveAttribute("hidden");
      expect(echo).toHaveTextContent("uPnL (USDT)");
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps the row menu: Shift+F10 on a row opens its actions, Close first (D-12, §11.5)", async () => {
    const onClose = vi.fn();
    const host = await mount(
      <Host
        variant="narrow"
        rowActions={(r): SplitButtonProps => ({
          primary: { label: "Close", onClick: onClose },
          items: closeItems(),
          menuLabel: `More close actions, ${r.symbol}`,
        })}
      />,
    );
    expect(host.querySelector(".cv-positions-grid__actions")).toBeNull();
    expect(within(grid()).queryByRole("button", { name: "Close" })).toBeNull();
    act(() =>
      within(rowNamed(/^BTCUSDT · Long · 0\.250/))
        .getAllByRole("gridcell")[1]
        ?.focus(),
    );
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    const menu = await page.findByRole("menu", { name: "Actions for BTCUSDT Long on Main" });
    expect(
      within(menu)
        .getAllByRole("menuitem")
        .map((item) => item.textContent),
    ).toEqual(["Close", "Close 25 %", "Reverse…", "SL/TP…", "Chart"]);
    // CMP-041 moves focus in from a passive effect, which can run after the menu is found.
    await waitFor(() => expect(within(menu).getAllByRole("menuitem")[0]).toHaveFocus());
    await userEvent.keyboard("{Enter}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("PositionsGrid (CMP-114): UpdatesPausedChip (D02 §9.1)", () => {
  it("names the held rows and applies them on a press", async () => {
    const onApply = vi.fn();
    const host = await mount(<UpdatesPausedChip newRows={2} closedRows={1} onApply={onApply} />);
    const chip = within(host).getByRole("button", { name: "Updates paused · 2 new · 1 closed" });
    expect(chip).toHaveAttribute("data-part", "UpdatesPausedChip");
    expect(chip).not.toHaveAttribute("data-tone");
    await userEvent.click(chip);
    expect(onApply).toHaveBeenCalledTimes(1);
  });

  it("drops a part with nothing held; a held NO SL row makes it critical; density passes through", async () => {
    const host = await mount(
      <UpdatesPausedChip newRows={0} closedRows={3} noSl density="comfortable" onApply={vi.fn()} />,
    );
    const chip = within(host).getByRole("button", { name: "Updates paused · 3 closed" });
    expect(chip).toHaveAttribute("data-tone", "critical");
    expect(chip).toHaveAttribute("data-density", "comfortable");
    const bare = await mount(<UpdatesPausedChip newRows={0} closedRows={0} onApply={vi.fn()} />);
    expect(within(bare).getByRole("button", { name: "Updates paused" })).toBeInTheDocument();
  });
});

describe("PositionsGrid (CMP-114): states", () => {
  it("loading: CMP-049's skeleton under the header, aria-busy and the host's words", async () => {
    await mount(<Host groups={[]} totals={undefined} loading loadingText="Loading positions…" />);
    expect(grid()).toHaveAttribute("aria-busy", "true");
    expect(page.getByText("Loading positions…")).toBeInTheDocument();
  });

  it("empty: the host's empty state across the columns, and no totals", async () => {
    await mount(<Host groups={[]} emptyState={<p>No open positions</p>} />);
    expect(page.getByText("No open positions")).toBeInTheDocument();
    expect(grid().querySelector(".cv-table__totals")).toBeNull();
  });

  // Measured 1.9 to 4.1 s at a load of 21 to 31 on 8 cores (four runs here), 9.6 s in the delta lens' runs at 23 to
  // 38: axe walks the whole grid, twice the 5 s default on a loaded host, so a measured 30 s ceiling, as the story
  // loop's below.
  it(
    "has no serious or critical axe violation, with selection, tiers, totals and gated actions",
    { timeout: 30_000 },
    async () => {
      const host = await mount(
        <>
          <p id="n">Your role can&apos;t change positions.</p>
          <Host
            rowActions={(r): SplitButtonProps => ({
              primary: { label: "Close", onClick: vi.fn() },
              items: closeItems(),
              menuLabel: `More close actions, ${r.symbol}`,
              disabledReason: "Your role can't change positions.",
              disabledReasonId: "n",
            })}
          />
        </>,
      );
      expect(await seriousViolations(host)).toEqual([]);
    },
  );
});

describe("PositionsGrid stories", () => {
  const all = composeStories(stories);
  // Theme stories wait on the preview's theme runtime, and the bench is a perf story: mounted, not played.
  const played = new Set([
    "Default",
    "GroupedByAccount",
    "GroupedByTradeGroup",
    "LiqWarningRows",
    "Selected",
    "Updating",
    "Narrow",
    "Empty",
    "Loading",
    "T2Viewer",
    "ReducedMotion",
  ]);

  // Each story mounts, plays and runs axe: at most 3.8 s apiece at a load of 23 on 8 cores, 17.8 s for the slowest at
  // 35 to 45 (the code lens' run), so a measured 30 s ceiling, as the Table story test's own.
  it.each(Object.keys(all).filter((name) => name !== "Perf500Rows"))(
    "%s renders, plays, and has no serious or critical axe violation at its root",
    { timeout: 30_000 },
    async (name) => {
      const Story = all[name as keyof typeof all];
      const canvasElement = await mount(<Story />);
      const play = stories[name as keyof typeof stories].play as
        ((context: { canvasElement: HTMLElement }) => Promise<void>) | undefined;
      if (played.has(name)) await play?.({ canvasElement });
      const root = canvasElement.querySelector('[data-cmp="CMP-114"]');
      expect(root).not.toBeNull();
      expect(await seriousViolations(root ?? canvasElement)).toEqual([]);
    },
  );

  it("the bench is tagged perf, so the storybook project skips it unless asked", () => {
    expect(stories.Perf500Rows.tags).toContain("perf");
  });
});
