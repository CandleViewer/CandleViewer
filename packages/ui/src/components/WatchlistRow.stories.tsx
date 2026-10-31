import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX, type ReactNode } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { Table, type TableProps } from "./Table.js";
import {
  WATCHLIST_DEFAULT_COLUMNS,
  WatchlistRow,
  watchlistColumns,
  type WatchlistColumnId,
  type WatchlistRowData,
  type WatchlistRowProps,
} from "./WatchlistRow.js";

/** The shared 1 Hz clock, frozen (2026-10-30 10:31:09 UTC), and the next funding: 05:28:51 to go (E08-D07 D22). */
const NOW = Date.UTC(2026, 9, 30, 10, 31, 9);
const FUNDING = Date.UTC(2026, 9, 30, 16, 0, 0);

/** E08-D07 §4.1's sample rows: illustrative values, not a market capture. */
const BTC: WatchlistRowData = {
  symbol: "BTCUSDT",
  priceScale: 2,
  lastPrice: 64012.5,
  pctChange24h: 0.42,
  turnover24h: 1.2e9,
  fundingRate: 0.01,
  nextFundingTimeMs: FUNDING,
  openInterestChangePct24h: 2.1,
  spreadBps: 0.0234,
  rec: { kind: "chip", compact: "REC", full: "REC · manual" },
};
const ETH: WatchlistRowData = {
  symbol: "ETHUSDT",
  priceScale: 2,
  lastPrice: 3144.21,
  pctChange24h: -0.18,
  turnover24h: 8.4e8,
  fundingRate: 0.008,
  nextFundingTimeMs: FUNDING,
  openInterestChangePct24h: -0.4,
  spreadBps: 0.03,
  rec: { kind: "chip", compact: "REC", full: "REC · chart open" },
};
const SOL: WatchlistRowData = {
  symbol: "SOLUSDT",
  priceScale: 2,
  lastPrice: 142.37,
  pctChange24h: 2.1,
  turnover24h: 3.1e8,
  fundingRate: 0.021,
  nextFundingTimeMs: FUNDING,
  openInterestChangePct24h: 5.6,
  spreadBps: 0.7,
  rec: { kind: "chip", compact: "—", full: "Not recording" },
};

type RowOptions = Omit<WatchlistRowProps, "grid" | "row" | "columns">;
interface Item {
  readonly data: WatchlistRowData;
  readonly options?: RowOptions;
}
const item = (data: WatchlistRowData, options?: RowOptions): Item =>
  options === undefined ? { data } : { data, options };

type GridProps = Omit<Partial<TableProps<Item>>, "columns" | "rows"> & {
  readonly items: readonly Item[];
  readonly columns?: readonly WatchlistColumnId[];
  readonly oiStale?: boolean;
};

/** SCR-100's composition (the host is apps/web's): CMP-049 in grid mode, one CMP-161 per symbol. */
function WatchlistGrid({
  items,
  columns = WATCHLIST_DEFAULT_COLUMNS,
  oiStale = false,
  ...table
}: GridProps): JSX.Element {
  return (
    <Table<Item>
      grid
      reflow="grid"
      caption={`Watchlist Majors, ${items.length} symbols, manual order`}
      captionHidden
      columns={watchlistColumns(columns, { item: (i: Item) => i.data, oiStale })}
      rows={items}
      rowKey={(i) => i.data.symbol}
      renderRow={(i, grid) => (
        <WatchlistRow grid={grid} row={i.data} columns={columns} nowMs={NOW} {...i.options} />
      )}
      {...table}
    />
  );
}

/** The footer line a host draws under the grid (E08-D07 §4.2; its words are the host's, proposed). */
const Note = ({
  id,
  children,
}: {
  readonly id: string;
  readonly children: ReactNode;
}): JSX.Element => (
  <p id={id} style={{ margin: "0.5rem 0 0" }}>
    {children}
  </p>
);

const meta: Meta = {
  title: "Molecules/WatchlistRow",
  component: WatchlistRow,
  // E08-D07 §4.1's reference panel width: 784 px.
  decorators: [
    (Story) => (
      <div style={{ width: "49rem" }}>
        <Story />
      </div>
    ),
  ],
  render: () => <WatchlistGrid items={[item(BTC), item(ETH), item(SOL)]} />,
};
export default meta;
type Story = StoryObj;

const grid = (canvasElement: HTMLElement): HTMLElement => within(canvasElement).getByRole("grid");
const cellOf = (canvasElement: HTMLElement, symbol: string, column: string): HTMLElement => {
  const header = within(grid(canvasElement)).getByRole("rowheader", {
    name: new RegExp(`^${symbol}`),
  });
  return header.closest("tr")?.querySelector(`[data-column="${column}"]`) as HTMLElement;
};

/** Live (E08-D07 §4.2 board 01): D9's formats, the symbol the row header, one Tab stop and the APG grid keys. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("grid", { name: /Watchlist Majors/ })).toHaveAttribute(
      "aria-rowcount",
      "4",
    );
    await expect(cellOf(canvasElement, "BTCUSDT", "last")).toHaveTextContent("64,012.50");
    await userEvent.tab();
    await expect(canvas.getByRole("rowheader", { name: /^BTCUSDT/ })).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}{ArrowDown}");
    await expect(cellOf(canvasElement, "ETHUSDT", "last")).toHaveFocus();
  },
};

/** A rise: 24h % and OI Δ with "+", the ▲ coloured by the sign (DS-CR-2's fallback: the glyph alone). */
export const Gainer: Story = {
  render: () => <WatchlistGrid items={[item(SOL)]} />,
  play: async ({ canvasElement }) => {
    const glyph = cellOf(canvasElement, "SOLUSDT", "chg_24h_pct").querySelector(".cv-wl__glyph");
    await expect(glyph).toHaveAttribute("data-sign", "positive");
    await expect(cellOf(canvasElement, "SOLUSDT", "chg_24h_pct")).toHaveTextContent("▲ +2.10%");
  },
};

/** A fall: "▼" and U+2212; Last, Funding % and Spread never coloured (D9). */
export const Loser: Story = {
  render: () => <WatchlistGrid items={[item(ETH)]} />,
  play: async ({ canvasElement }) => {
    await expect(cellOf(canvasElement, "ETHUSDT", "chg_24h_pct")).toHaveTextContent("▼ −0.18%");
    await expect(
      cellOf(canvasElement, "ETHUSDT", "funding_rate").querySelector("[data-sign]"),
    ).toBeNull();
  },
};

/** Optional columns (D8): prices at the instrument's scale, sizes to 3 significant figures. */
export const CustomColumns: Story = {
  render: () => (
    <WatchlistGrid
      columns={[
        "symbol",
        "last",
        "mark_price",
        "bid1_price",
        "ask1_price",
        "volume_24h",
        "open_interest_value",
      ]}
      items={[
        item({
          ...BTC,
          markPrice: 64010.1,
          bid1Price: 64012.4,
          ask1Price: 64012.6,
          volume24h: 18_734.2,
          openInterestValue: 6.12e9,
        }),
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["Symbol", "Last", "Mark", "Bid", "Ask", "Volume 24h", "OI USDT", "Status"]);
  },
};

/** A stale OI Δ cell (D21): the class swap on the cell alone, described by the footer line; the row stays live. */
export const StaleCell: Story = {
  render: () => (
    <>
      <WatchlistGrid
        items={[
          item(BTC, { freshness: { oiBaseline: { state: "stale", noteId: "oi-note-cell" } } }),
          item(ETH),
        ]}
      />
      <Note id="oi-note-cell">OI Δ 24h stale: baseline last read 12 min ago</Note>
    </>
  ),
  play: async ({ canvasElement }) => {
    const oi = cellOf(canvasElement, "BTCUSDT", "oi_chg_24h_pct");
    await expect(oi).toHaveClass("cv-freshness--stale");
    await expect(oi).toHaveAccessibleDescription("OI Δ 24h stale: baseline last read 12 min ago");
  },
};

/** A stale OI Δ column (E08-D07 board 02): every OI cell marked, ⚠ on the header, one footer line. */
export const StaleColumn: Story = {
  render: () => {
    const stale = { freshness: { oiBaseline: { state: "stale", noteId: "oi-note" } } } as const;
    return (
      <>
        <WatchlistGrid oiStale items={[item(BTC, stale), item(ETH, stale), item(SOL, stale)]} />
        <Note id="oi-note">OI Δ 24h stale: baseline last read 12 min ago</Note>
      </>
    );
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("columnheader", { name: "OI Δ 24h % stale" }),
    ).toBeInTheDocument();
  },
};

/** A stale row, T1 (board 03): the tint and demoted text, values kept, one chip "Stale 7s", its time in the echo. */
export const StaleRow: Story = {
  render: () => (
    <WatchlistGrid
      items={[
        item(BTC),
        item(SOL, {
          freshness: {
            ticker: { state: "stale", ageMs: 7000, detail: "Last update 10:31:02 UTC" },
          },
        }),
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    await expect(cellOf(canvasElement, "SOLUSDT", "last")).toHaveAccessibleDescription(
      "Stale, 7 seconds",
    );
    await expect(cellOf(canvasElement, "SOLUSDT", "status")).toHaveTextContent("Stale 7s");
  },
};

/** A stale row past T2 (15 s): the strong chip. */
export const StaleRowEscalated: Story = {
  render: () => (
    <WatchlistGrid
      items={[
        item(BTC),
        item(SOL, { freshness: { ticker: { state: "stale", ageMs: 15_000, escalated: true } } }),
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    await expect(
      cellOf(canvasElement, "SOLUSDT", "status").querySelector('[data-cmp="CMP-239"]'),
    ).toHaveAttribute("data-level", "strong");
  },
};

/** Flagged by the server (D1): "Stale (server)" in T1's style; the exchange-feed-down words in its echo (D28). */
export const StaleServer: Story = {
  render: () => (
    <WatchlistGrid
      items={[
        item(ETH, {
          freshness: {
            ticker: {
              state: "stale",
              ageMs: 3000,
              server: true,
              detail: "Exchange feed down — the server is restoring the connection",
            },
          },
        }),
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    await expect(cellOf(canvasElement, "ETHUSDT", "status")).toHaveTextContent("Stale (server)");
  },
};
/**
 * Disconnected (board 04): one attribute on the panel demotes every row (DS-CR-1's fallback: text.primary at
 * opacity.muted on surface.sunken); no chip; values kept; the panel status describes every cell.
 */
export const DisconnectedRow: Story = {
  render: () => {
    const options = { describedBy: "panel-status" };
    return (
      <div data-cv-feed="disconnected">
        <p id="panel-status" style={{ margin: "0 0 0.5rem" }}>
          Disconnected — last data 00:12 ago
        </p>
        <WatchlistGrid items={[item(BTC, options), item(ETH, options), item(SOL, options)]} />
      </div>
    );
  },
  play: async ({ canvasElement }) => {
    await expect(cellOf(canvasElement, "BTCUSDT", "last")).toHaveAccessibleDescription(
      "Disconnected — last data 00:12 ago",
    );
    await expect(cellOf(canvasElement, "BTCUSDT", "last")).toHaveTextContent("64,012.50");
  },
};

/** Initialising (D7): "—" named "no value yet" until the first value; past T1 the chip "No data yet". */
export const Initialising: Story = {
  render: () => (
    <WatchlistGrid
      items={[
        item({ symbol: "ARBUSDT", priceScale: 4 }, { rowState: "initialising" }),
        item(
          { symbol: "OPUSDT", priceScale: 4 },
          { rowState: "initialising", freshness: { ticker: { state: "stale", ageMs: 6000 } } },
        ),
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    await expect(cellOf(canvasElement, "ARBUSDT", "last")).toHaveAccessibleName("no value yet");
    await expect(cellOf(canvasElement, "OPUSDT", "status")).toHaveTextContent("No data yet");
  },
};

/** Not live (D7, §4.6): "—" and the chip "Not live"; why, in its echo on focus and hover. */
export const NotLive: Story = {
  render: () => (
    <WatchlistGrid
      items={[
        item(BTC),
        item(ETH, {
          rowState: "not-live",
          notLiveDetail: "At most 40 symbols are live on one connection; other panels use 30.",
        }),
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    const status = cellOf(canvasElement, "ETHUSDT", "status");
    await expect(status).toHaveTextContent("Not live");
    // Keyboard focus shows a cell's words in the echo at once: in on BTCUSDT, down a row, to its end.
    await userEvent.tab();
    await userEvent.keyboard("{ArrowDown}{End}");
    await expect(status).toHaveFocus();
    await waitFor(() =>
      expect(document.querySelector(".cv-table__echo:not([hidden])")).toHaveTextContent(
        "At most 40 symbols are live on one connection; other panels use 30.",
      ),
    );
  },
};

/**
 * Delisted (board 07, D20): struck after the lock (named "Not available"), the live cells merged, Rec kept;
 * activation is T2.
 */
export const Delisted: Story = {
  render: () => (
    <WatchlistGrid
      items={[
        item(BTC),
        item(
          {
            ...SOL,
            symbol: "LUNAUSDT",
            rec: { kind: "chip", compact: "—", full: "Not recording" },
          },
          { rowState: "delisted", onActivate: () => undefined },
        ),
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    const header = within(canvasElement).getByRole("rowheader", { name: "Not available LUNAUSDT" });
    await expect(header).toHaveAttribute("aria-disabled", "true");
    await expect(header).toHaveAccessibleDescription("Delisted by the exchange");
    header.focus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() =>
      expect(document.querySelector(".cv-table__echo:not([hidden])")).toHaveTextContent(
        "Delisted by the exchange",
      ),
    );
  },
};

/** The active row (D11): `aria-current`, the selected fill and the 2 px bar, described "Shows in group A". */
export const Active: Story = {
  render: () => (
    <WatchlistGrid
      items={[item(BTC, { active: true, description: "Shows in group A" }), item(ETH), item(SOL)]}
    />
  ),
  play: async ({ canvasElement }) => {
    const header = within(canvasElement).getByRole("rowheader", { name: /^BTCUSDT/ });
    await expect(header.closest("tr")).toHaveAttribute("aria-current", "true");
    await expect(header).toHaveAccessibleDescription("Shows in group A");
  },
};

/** The Rec slot (E16-S02 fills it; E08-D07 §4.2's compact forms): the full text is each chip's name. */
export const RecStates: Story = {
  render: () => {
    const rec = (symbol: string, value: WatchlistRowData["rec"]): Item =>
      item(value === undefined ? { ...BTC, symbol } : { ...BTC, symbol, rec: value });
    return (
      <WatchlistGrid
        columns={["symbol", "last", "rec"]}
        items={[
          rec("BTCUSDT", { kind: "chip", compact: "REC", full: "REC · manual" }),
          rec("ETHUSDT", { kind: "chip", compact: "REC 24m", full: "REC · stops in 24 min" }),
          rec("SOLUSDT", { kind: "chip", compact: "REC", full: "REC degraded", warning: true }),
          rec("XRPUSDT", {
            kind: "chip",
            compact: "REC…",
            full: "Starting · initial book snapshot",
          }),
          rec("DOGEUSDT", {
            kind: "chip",
            compact: "—",
            full: "Not recording · limit reached",
            warning: true,
          }),
          rec("ADAUSDT", { kind: "chip", compact: "—", full: "Not recording" }),
          rec("AVAXUSDT", { kind: "restricted" }),
          rec("LINKUSDT", undefined),
        ]}
      />
    );
  },
  play: async ({ canvasElement }) => {
    await expect(cellOf(canvasElement, "ETHUSDT", "rec")).toHaveAccessibleName(
      "REC · stops in 24 min",
    );
    await expect(cellOf(canvasElement, "AVAXUSDT", "rec")).toHaveAccessibleName(
      "Recording status restricted",
    );
  },
};

const READ_ONLY = "Read-only — your role can't change watchlists.";

/** Read-only (§4.2, D13): `Del` and `Alt+↑/↓` change nothing and re-show the notice's sentence in the echo. */
export const ReadOnly: Story = {
  render: () => {
    const gated = {
      onRemove: () => undefined,
      removeReason: READ_ONLY,
      onMove: () => undefined,
      moveReason: { up: READ_ONLY, down: READ_ONLY },
    };
    return (
      <>
        <p id="read-only" style={{ margin: "0 0 0.5rem" }}>
          {READ_ONLY}
        </p>
        <WatchlistGrid items={[item(BTC, gated), item(ETH, gated)]} />
      </>
    );
  },
  play: async ({ canvasElement }) => {
    cellOf(canvasElement, "BTCUSDT", "last").focus();
    await userEvent.keyboard("{Delete}");
    await waitFor(() =>
      expect(document.querySelector(".cv-table__echo:not([hidden])")).toHaveTextContent(READ_ONLY),
    );
    await expect(within(canvasElement).getAllByRole("row")).toHaveLength(3);
  },
};

/** Comfortable density (D30): 32 px rows and `type.num.base` numbers. */
export const Comfortable: Story = {
  render: () => <WatchlistGrid density="comfortable" items={[item(BTC), item(ETH), item(SOL)]} />,
};

/**
 * A long symbol the cell cuts with an ellipsis (E08-D07 §4.1): the whole symbol stays its text and its name, and
 * keyboard focus shows it in the echo.
 */
export const LongSymbol: Story = {
  render: () => (
    <WatchlistGrid
      items={[item({ ...BTC, symbol: "1000000BABYDOGEUSDT", priceScale: 7, lastPrice: 0.0021437 })]}
    />
  ),
  play: async ({ canvasElement }) => {
    const symbol = within(canvasElement).getByRole("rowheader", { name: /^1000000BABYDOGEUSDT/ });
    await userEvent.tab();
    await expect(symbol).toHaveFocus();
    await waitFor(() =>
      expect(document.querySelector(".cv-table__echo:not([hidden])")).toHaveTextContent(
        "1000000BABYDOGEUSDT",
      ),
    );
  },
};

/**
 * 200 % (D30): the grid reflows to one card per symbol and keeps its roles, its one Tab stop and its keys. At a root
 * font size of 200 % on the 1280 x 800 frame the columns' minimums no longer fit the 784 px panel.
 */
export const Reflow200: Story = {
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story) => (
      <div style={{ width: 1280, height: 800 }}>
        <Story />
      </div>
    ),
  ],
  // The 784 px panel in CSS px that root zoom does not scale, so the columns' minimums outgrow it at 200 %.
  render: () => (
    <div style={{ width: 784 }}>
      <WatchlistGrid items={[item(BTC), item(ETH), item(SOL)]} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const root = document.documentElement;
    const before = root.style.fontSize;
    try {
      root.style.fontSize = "200%";
      const shell = canvasElement.querySelector('[data-cmp="CMP-049"]');
      await waitFor(() => expect(shell).toHaveAttribute("data-layout", "stacked"));
      await expect(within(canvasElement).getByRole("grid")).toBeInTheDocument();
      await expect(within(canvasElement).getAllByRole("rowheader")).toHaveLength(3);
    } finally {
      root.style.fontSize = before;
    }
  },
};

const ALTS: readonly Item[] = Array.from({ length: 120 }, (_, i) =>
  item({
    symbol: `ALT${String(i + 1).padStart(3, "0")}USDT`,
    priceScale: 4,
    lastPrice: 1 + i * 0.0125,
    pctChange24h: ((i % 9) - 4) * 0.37,
    turnover24h: 2.5e6 * (i + 1),
    fundingRate: 0.01,
    nextFundingTimeMs: FUNDING,
    openInterestChangePct24h: ((i % 7) - 3) * 0.51,
    spreadBps: 1.2 + (i % 5) * 0.1,
  }),
);

/** A host that windows a long list, as SCR-100 does past 60 rows: the rows in view and 10 either side. */
function WindowedHost(): JSX.Element {
  const [first, setFirst] = useState(0);
  const offset = Math.max(0, Math.min(first - 10, ALTS.length - 40));
  return (
    <div style={{ height: "20rem", display: "flex", flexDirection: "column" }}>
      <WatchlistGrid
        items={ALTS.slice(offset, offset + 40)}
        caption="Watchlist Alts, 120 symbols, manual order"
        rowWindow={{ offset, total: ALTS.length }}
        onRowsInView={(top) => setFirst(top)}
      />
    </div>
  );
}

/** Virtualised (`14` SCR-100 "Performance"): 120 symbols, 40 rows drawn; absolute row indices; keys cross the window. */
export const Windowed: Story = {
  render: () => <WindowedHost />,
  play: async ({ canvasElement }) => {
    const table = grid(canvasElement);
    await expect(table).toHaveAttribute("aria-rowcount", "121");
    within(table)
      .getByRole("rowheader", { name: /^ALT001USDT/ })
      .focus();
    await userEvent.keyboard("{Control>}{End}{/Control}");
    await waitFor(() =>
      expect(document.activeElement?.closest("tr")).toHaveAttribute("aria-rowindex", "121"),
    );
  },
};
