import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { EmptyState } from "./EmptyState.js";
import type { MenuItem } from "./Menu.js";
import {
  PositionsGrid,
  UpdatesPausedChip,
  type PositionsGridGroup,
  type PositionsGridProps,
  type PositionsGridRow,
  type PositionsGridTotals,
} from "./PositionsGrid.js";
import { formatRbacReason } from "./rbacReasons.js";
import type { SplitButtonProps } from "./SplitButton.js";

/**
 * E29-D02 §5.2's fixture accounts (Main, Sub-1, Sub-2; one environment, #911 BQ-7) and their positions, with the
 * accounts' `realised_pnl_today` on the headers and the LIVE total (D-15). Design fixtures, not exchange payloads.
 */
const position = (
  account: string,
  id: string,
  fields: Omit<PositionsGridRow, "key" | "accountId" | "accountLabel" | "hedge" | "sideWord"> &
    Partial<Pick<PositionsGridRow, "hedge">>,
): PositionsGridRow => ({
  key: `${id}|${fields.symbol}|0`,
  accountId: id,
  accountLabel: account,
  hedge: false,
  sideWord: fields.side === "long" ? "Long" : "Short",
  ...fields,
});

const isolated = { value: "isolated" } as const;

const MAIN_BTC = position("Main", "acct-main", {
  symbol: "BTCUSDT",
  baseCoin: "BTC",
  side: "long",
  size: "0.250",
  entry: "63980.0",
  mark: "64012.0",
  unrealisedPnl: "8.00",
  realisedToday: { value: "12.40" },
  r: { value: "0.32" },
  leverage: "10",
  marginMode: isolated,
  liqPrice: "57901.9",
  liq: { tier: "none", distancePct: "9.5", sharePct: "101" },
});
const SUB1_BTC = position("Sub-1", "acct-sub-1", {
  symbol: "BTCUSDT",
  baseCoin: "BTC",
  side: "long",
  size: "0.100",
  entry: "63985.0",
  mark: "64012.0",
  unrealisedPnl: "2.70",
  realisedToday: { value: "0.00" },
  r: { value: "0.32" },
  leverage: "5",
  marginMode: isolated,
  liqPrice: "51507.9",
  liq: { tier: "none", distancePct: "19.5", sharePct: "100" },
});
const SUB1_ETH = position("Sub-1", "acct-sub-1", {
  symbol: "ETHUSDT",
  baseCoin: "ETH",
  side: "short",
  size: "1.50",
  entry: "2480.00",
  mark: "2561.00",
  unrealisedPnl: "-121.50",
  realisedToday: { value: "-18.20" },
  r: { value: "-0.85" },
  leverage: "20",
  marginMode: isolated,
  liqPrice: "2591.60",
  liq: { tier: "near", distancePct: "1.2", sharePct: "27" },
});
const SUB2_SOL = position("Sub-2", "acct-sub-2", {
  symbol: "SOLUSDT",
  baseCoin: "SOL",
  side: "long",
  size: "20.0",
  entry: "152.40",
  mark: "147.80",
  unrealisedPnl: "-92.00",
  realisedToday: { value: "0.00" },
  r: { value: "-0.94" },
  leverage: "25",
  marginMode: isolated,
  liqPrice: "147.07",
  liq: { tier: "critical", distancePct: "0.5", sharePct: "14" },
});
const SUB2_BTC = position("Sub-2", "acct-sub-2", {
  symbol: "BTCUSDT",
  baseCoin: "BTC",
  side: "long",
  size: "0.080",
  entry: "64050.0",
  mark: "64012.0",
  unrealisedPnl: "-3.04",
  realisedToday: { value: "0.00" },
  r: { value: "-0.38" },
  leverage: "10",
  marginMode: isolated,
  liqPrice: "57965.3",
  liq: { tier: "none", distancePct: "9.4", sharePct: "99" },
});
/** D02 §5.2's Watch row (its DEMO line, here in the one environment's Main). */
const MAIN_ETH_WATCH = position("Main", "acct-main", {
  symbol: "ETHUSDT",
  baseCoin: "ETH",
  side: "long",
  size: "2.00",
  entry: "2625.00",
  mark: "2561.00",
  unrealisedPnl: "-128.00",
  realisedToday: { value: "0.00" },
  r: { value: "-0.75" },
  leverage: "20",
  marginMode: isolated,
  liqPrice: "2506.88",
  liq: { tier: "watch", distancePct: "2.1", sharePct: "46" },
});

const account = (
  key: string,
  label: string,
  rows: readonly PositionsGridRow[],
  unrealisedPnl: string,
  realisedToday: string,
): PositionsGridGroup => ({
  key,
  label,
  positionMode: "one-way",
  rows,
  count: rows.length,
  unrealisedPnl,
  realisedToday,
  netSize: null,
});

const BY_ACCOUNT: readonly PositionsGridGroup[] = [
  account("acct-main", "Main · LIVE", [MAIN_BTC], "8.00", "37.40"),
  account("acct-sub-1", "Sub-1 · LIVE", [SUB1_BTC, SUB1_ETH], "-118.80", "3.20"),
  account("acct-sub-2", "Sub-2 · LIVE", [SUB2_SOL, SUB2_BTC], "-95.04", "-6.20"),
];
/**
 * "LIVE total" (D02:142) over the five rows: count, exposure, Net (Σ signed notional: the ETH short's 3,841.50
 * against 30,481.16 long) and the accounts' own realised figures (D-15).
 */
const LIVE_TOTAL: PositionsGridTotals = {
  label: "LIVE total",
  count: 5,
  exposure: "34322.66",
  net: "26639.66",
  unrealisedPnl: "-205.84",
  realisedToday: "34.40",
};

/** Two trade groups and the positions with none (#911 BQ-10); the one-symbol group shows its net size. */
const BY_TRADE_GROUP: readonly PositionsGridGroup[] = [
  {
    key: "4f2a9c1e",
    label: "Trade group 4f2a9c",
    rows: [MAIN_BTC, SUB1_BTC, SUB2_BTC],
    count: 3,
    unrealisedPnl: "7.66",
    realisedToday: "12.40",
    netSize: "0.430",
  },
  {
    key: "9b07d3aa",
    label: "Trade group 9b07d3",
    rows: [SUB1_ETH, SUB2_SOL],
    count: 2,
    unrealisedPnl: "-213.50",
    realisedToday: "-18.20",
    netSize: null,
  },
];

const CAPTION = "Positions";

type HostProps = Partial<PositionsGridProps> & { readonly initiallySelected?: readonly string[] };

/** A host that owns the selection, as SCR-063's panel does. */
function Host({ initiallySelected = [], ...props }: HostProps): JSX.Element {
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set(initiallySelected));
  return (
    <PositionsGrid
      caption={CAPTION}
      groups={BY_ACCOUNT}
      totals={LIVE_TOTAL}
      selected={selected}
      onSelectionChange={setSelected}
      {...props}
    />
  );
}

const meta: Meta = {
  title: "Trading/PositionsGrid",
  component: PositionsGrid,
  render: () => <Host />,
  decorators: [
    (Story) => (
      <div style={{ width: "80rem", fontFamily: "var(--font-family-ui), system-ui, sans-serif" }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj;

/** The grid alone, for a play's queries: the preview's own mount probe is a labelled `<output>` outside it. */
const gridOf = (canvas: HTMLElement): HTMLElement => {
  const root = canvas.querySelector<HTMLElement>('[data-cmp="CMP-114"]');
  if (root === null) throw new Error("no CMP-114 rendered");
  return within(root).getByRole("treegrid", { name: CAPTION });
};

/**
 * Board 01 (`CMP-114/row-default`, `group-header`, `totals-row`): grouped by account, every group open, the select
 * column and the pinned Account and Symbol, tiers as glyph, word and distance, the pinned "LIVE total" with Net in its
 * tooltip and description (D-15).
 */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const grid = gridOf(canvasElement);
    await expect(grid).toHaveAttribute("aria-multiselectable", "true");
    await expect(
      within(grid).getByRole("row", { name: "BTCUSDT · Long · 0.250 BTC · Main" }),
    ).toHaveAttribute("aria-level", "2");
    const total = within(grid).getByRole("rowheader", { name: /^LIVE total/ });
    await expect(total).toBeVisible();
    await expect(total.closest("tr")).toHaveAccessibleDescription("Net 26,639.66 USDT");
  },
};

/**
 * Group by account (D02 §5.5): Sub-1 closed (▸, `aria-expanded="false"`); → on its header opens it, focus kept, and
 * → again moves to its first position.
 */
export const GroupedByAccount: Story = {
  play: async ({ canvasElement }) => {
    const grid = gridOf(canvasElement);
    const header = within(grid).getByRole("rowheader", { name: /^Sub-1 · LIVE/ });
    header.focus();
    await userEvent.keyboard("{ArrowLeft}");
    await waitFor(() => expect(header.closest("tr")).toHaveAttribute("aria-expanded", "false"));
    await expect(within(grid).queryByRole("row", { name: /ETHUSDT · Short/ })).toBeNull();
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() => expect(header.closest("tr")).toHaveAttribute("aria-expanded", "true"));
    await userEvent.keyboard("{ArrowRight}");
    await expect(document.activeElement?.closest("tr")).toHaveAccessibleName(
      "BTCUSDT · Long · 0.100 BTC · Sub-1",
    );
  },
};

/** Group by trade group (#911 BQ-10): one group on one symbol shows its net size; the other, on two, does not. */
export const GroupedByTradeGroup: Story = {
  render: () => <Host groups={BY_TRADE_GROUP} />,
  play: async ({ canvasElement }) => {
    const grid = gridOf(canvasElement);
    await expect(
      within(grid).getByRole("rowheader", { name: /^Trade group 4f2a9c .* net 0\.430 BTC/ }),
    ).toBeVisible();
    await expect(
      within(grid).getByRole("rowheader", { name: /^Trade group 9b07d3/ }),
    ).not.toHaveTextContent("net");
  },
};

/**
 * The tiers (`CMP-114/liq-watch`, `liq-near`, `liq-critical`; D02 §5.3): glyph, word and distance, the D5 label the
 * row's description and the cell's echo; Critical adds the 2 × 12 px leading accent at the start of the row.
 */
export const LiqWarningRows: Story = {
  render: () => (
    <Host
      groups={[
        account("acct-main", "Main · LIVE", [MAIN_ETH_WATCH], "-128.00", "0.00"),
        account("acct-sub-1", "Sub-1 · LIVE", [SUB1_ETH], "-121.50", "-18.20"),
        account("acct-sub-2", "Sub-2 · LIVE", [SUB2_SOL], "-92.00", "-6.20"),
      ]}
      totals={undefined}
    />
  ),
  play: async ({ canvasElement }) => {
    const grid = gridOf(canvasElement);
    const critical = within(grid).getByRole("row", { name: /^SOLUSDT/ });
    await expect(critical).toHaveAttribute("data-liq", "critical");
    await expect(critical).toHaveAccessibleDescription(
      "Critical — near liquidation: 14 % of the entry buffer left, 0.5 % from liquidation",
    );
    await expect(within(grid).getByRole("row", { name: /^ETHUSDT · Short/ })).toHaveTextContent(
      "! Near 1.2",
    );
  },
};

/** `CMP-114/row-selected`: two rows selected, the box checked and `color.surface.selected`; Space toggles a row. */
export const Selected: Story = {
  render: () => <Host initiallySelected={[SUB1_ETH.key, SUB2_SOL.key]} />,
  play: async ({ canvasElement }) => {
    const grid = gridOf(canvasElement);
    const row = within(grid).getByRole("row", { name: /^ETHUSDT · Short/ });
    await expect(row).toHaveAttribute("aria-selected", "true");
    await expect(
      within(grid).getByRole("checkbox", { name: "Select ETHUSDT Short on Sub-1" }),
    ).toBeChecked();
    const cell = within(within(grid).getByRole("row", { name: /^BTCUSDT · Long · 0\.250/ }))
      .getAllByRole("gridcell")
      .at(1);
    cell?.focus();
    await userEvent.keyboard(" ");
    await expect(
      within(grid).getByRole("row", { name: /^BTCUSDT · Long · 0\.250/ }),
    ).toHaveAttribute("aria-selected", "true");
  },
};

/** `CMP-114/updates-paused-chip` (D02 §9.1): the toolbar's chip over the grid, and its critical twin (NO SL held). */
export const Updating: Story = {
  render: () => (
    <div style={{ display: "grid", gap: "var(--space-stack-sm)" }}>
      <div style={{ display: "flex", gap: "var(--space-inset-sm)" }}>
        <UpdatesPausedChip newRows={2} closedRows={1} onApply={fn()} />
        <UpdatesPausedChip newRows={1} closedRows={0} noSl onApply={fn()} />
      </div>
      <Host />
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", { name: "Updates paused · 2 new · 1 closed" }),
    ).toBeVisible();
    await expect(
      within(canvasElement).getByRole("button", { name: "Updates paused · 1 new" }),
    ).toHaveAttribute("data-tone", "critical");
  },
};

/**
 * The 360 px dock (D02 §11.5): Symbol · Side · Size · uPnL · Status, the account in its header; the base coin and
 * the uPnL unit leave the cells and stay in the names (the unit in its header's tooltip too). The totals row keeps
 * its label, count and uPnL; its exposure, Net and rPnL today move to its tooltip and description, never cut.
 */
export const Narrow: Story = {
  decorators: [
    (Story) => (
      <div style={{ width: "22.5rem" }}>
        <Story />
      </div>
    ),
  ],
  render: () => <Host variant="narrow" />,
  play: async ({ canvasElement }) => {
    const grid = gridOf(canvasElement);
    await expect(within(grid).getByRole("columnheader", { name: "uPnL (USDT)" })).toBeVisible();
    await expect(within(grid).queryByRole("columnheader", { name: "Account" })).toBeNull();
    await expect(within(grid).getByRole("columnheader", { name: "Status" })).toBeVisible();
    const total = within(grid).getByRole("rowheader", { name: "LIVE total · 5 open" });
    await expect(total.closest("tr")).toHaveAccessibleDescription(
      "Exposure 34,322.66 USDT · Net 26,639.66 USDT · rPnL today profit 34.40 USDT",
    );
  },
};

/** D02 §10.1 Empty: the host's CMP-026 with the deck's title and cause (E29-D06 `blotter.ui.empty`). */
export const Empty: Story = {
  render: () => (
    <Host
      groups={[]}
      totals={undefined}
      emptyState={
        <EmptyState
          title="No open positions"
          description="Positions you open on any account appear here."
        />
      }
    />
  ),
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("heading", { name: "No open positions" }),
    ).toBeVisible();
  },
};

/** Loading: CMP-049's skeleton rows under the header row, `aria-busy` (D02 §10.1). */
export const Loading: Story = {
  render: () => <Host groups={[]} totals={undefined} loading loadingText="Loading positions…" />,
  play: async ({ canvasElement }) => {
    await expect(gridOf(canvasElement)).toHaveAttribute("aria-busy", "true");
  },
};

/** `rbac.permission` for the Viewer's two lines (E09-D09 §3.1, §3.2's verbs; D02 §10.4). */
const CANT_CHANGE = formatRbacReason("rbac.permission", { verb: "change positions" });
const CANT_ORDER = formatRbacReason("rbac.permission", { verb: "place orders" });

/** The ▾ items (D02 §8.1): for a Viewer every one but Chart is T2 (E29-D04 §4.2), each its second line (interim). */
const viewerItems = (): MenuItem[] =>
  ["Close 25 %", "Close 50 %", "Close custom size…", "Close at limit…", "Reverse…", "SL/TP…"]
    .map((label): MenuItem => ({ id: label, label, onSelect: fn(), disabledReason: CANT_CHANGE }))
    .concat({ id: "chart", label: "Chart", onSelect: fn() });

/**
 * `CMP-114/t2-viewer` (E29-D04 §4.1; D02 §10.4; G-T2.1 to G-T2.6): a Viewer's Close ▾ keeps its role and full label,
 * `aria-disabled`, the `lock` leading it, described by the panel's one notice line (one notice, many pointers); a
 * press sends nothing. Selection, sorting and grouping stay enabled: they send nothing.
 */
export const T2Viewer: Story = {
  render: () => (
    <div>
      <div>
        <p id="viewer-positions">{CANT_CHANGE}</p>
        <p id="viewer-orders">{CANT_ORDER}</p>
      </div>
      <Host
        rowActions={(row): SplitButtonProps => ({
          primary: { label: "Close", onClick: fn() },
          items: viewerItems(),
          menuLabel: `More close actions, ${row.symbol} ${row.sideWord} on ${row.accountLabel ?? ""}`,
          disabledReason: CANT_CHANGE,
          disabledReasonId: "viewer-positions",
        })}
      />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const grid = gridOf(canvasElement);
    const close = within(grid).getAllByRole("button", { name: "Not available Close" })[0];
    await expect(close).toHaveAttribute("aria-disabled", "true");
    await expect(close).not.toBeDisabled();
    await expect(close).toHaveAccessibleDescription(CANT_CHANGE);
    await expect(
      within(grid).getByRole("checkbox", { name: "Select BTCUSDT Long on Main" }),
    ).not.toHaveAttribute("aria-disabled");
  },
};

/**
 * Reduced motion (E29-D04 §3.6; D04H §D): with `data-motion="reduce"` every reading is at frame 0; the grid has no
 * motion of its own (Mo-8 and Mo-10 are cuts), so nothing runs either way.
 */
export const ReducedMotion: Story = {
  globals: { motion: "reduce" },
  render: () => <Host groups={[BY_ACCOUNT[2] ?? account("x", "x", [], "0", "0")]} />,
  play: async ({ canvasElement }) => {
    const grid = gridOf(canvasElement);
    await expect(within(grid).getByRole("row", { name: /^SOLUSDT/ })).toHaveTextContent(
      "!! Critical 0.5",
    );
    const running = grid.getAnimations?.({ subtree: true }) ?? [];
    await expect(running).toHaveLength(0);
  },
};

/** Every state under the light and high-contrast themes; axe checks each theme. */
const themeMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: () => (
    <div style={{ display: "grid", gap: "var(--space-stack-sm)" }}>
      <UpdatesPausedChip newRows={2} closedRows={1} onApply={fn()} />
      <Host
        groups={[
          account("acct-main", "Main · LIVE", [MAIN_BTC, MAIN_ETH_WATCH], "-120.00", "37.40"),
          account("acct-sub-1", "Sub-1 · LIVE", [SUB1_ETH], "-121.50", "3.20"),
          account("acct-sub-2", "Sub-2 · LIVE", [SUB2_SOL], "-92.00", "-6.20"),
        ]}
        initiallySelected={[SUB1_ETH.key]}
      />
    </div>
  ),
});
export const ContrastLight: Story = themeMatrix("light");
export const ContrastHighContrast: Story = themeMatrix("high-contrast");

/** The bench's synthetic book (#911 BQ-22: synthetic rows for the bench only): 20 accounts of 24 positions. */
function benchGroups(tick: number): readonly PositionsGridGroup[] {
  return Array.from({ length: 20 }, (_, g) => {
    const id = `acct-${String(g).padStart(2, "0")}`;
    const rows = Array.from({ length: 24 }, (_, i) => {
      const mark = (1000 + g * 10 + i + tick / 10).toFixed(1);
      const pnl = ((i % 7) * 9.5 - 30 + tick / 100).toFixed(2);
      return position(`Account ${String(g)}`, id, {
        symbol: `PAIR${String(i).padStart(2, "0")}USDT`,
        baseCoin: `PAIR${String(i).padStart(2, "0")}`,
        side: i % 2 === 0 ? "long" : "short",
        size: ((i + 1) * 0.25).toFixed(3),
        entry: (1000 + g * 10 + i).toFixed(1),
        mark,
        unrealisedPnl: pnl,
        realisedToday: { value: "0.00" },
        r: { value: ((i % 5) * 0.1 - 0.2).toFixed(2) },
        leverage: "10",
        marginMode: isolated,
        liqPrice: (900 + g * 10 + i).toFixed(1),
        liq: {
          tier: i % 11 === 0 ? "critical" : i % 7 === 0 ? "near" : "none",
          distancePct: (i / 4).toFixed(1),
          sharePct: String(10 + i),
        },
      });
    });
    return account(id, `Account ${String(g)} · LIVE`, rows, "0.00", "0.00");
  });
}

/** The frame budget (E29-S01 T Perf; #911 BQ-21): 16 ms, the spec's number. */
const BUDGET_MS = 16;

/**
 * #911 BQ-21's in-page bench over 500 rows (20 groups of 24 positions and their headers): the median first render of
 * the grid's window, measured with `performance.measure` from a mark before the mount, within one frame; then a 10 Hz
 * burst, every drawn row's values new at each tick, each commit measured the same way within one frame. Tagged
 * `perf`: a wall-clock budget is no pass/fail check on a shared runner, so the storybook project skips it (#269)
 * unless `CV_STORYBOOK_PERF=1`. The bound is the spec's number: `budget()` (perf-calibration.mjs) reads
 * `node:perf_hooks` and `node:process`, which a page cannot load.
 */
export const Perf500Rows: Story = {
  tags: ["perf"],
  render: () => <p>500-row benchmark: the play function mounts and times the grid.</p>,
  play: async ({ canvasElement }) => {
    const book = benchGroups(0);
    const measure = (name: string, run: () => void): number => {
      performance.mark(`${name}:start`);
      run();
      const duration = performance.measure(name, `${name}:start`).duration;
      performance.clearMarks(`${name}:start`);
      performance.clearMeasures(name);
      return duration;
    };
    const frame = { height: "40rem", display: "flex", flexDirection: "column" } as const;
    const firstRenders: number[] = [];
    for (let i = 0; i < 20; i += 1) {
      const host = canvasElement.appendChild(document.createElement("div"));
      Object.assign(host.style, frame);
      const root = createRoot(host);
      firstRenders.push(
        measure("cv:positions-grid:first-render", () =>
          flushSync(() =>
            root.render(<PositionsGrid caption={`Bench ${String(i)}`} groups={book} />),
          ),
        ),
      );
      root.unmount();
      host.remove();
    }
    const median = firstRenders.slice(5).sort((a, b) => a - b)[7] ?? Infinity;

    const host = canvasElement.appendChild(document.createElement("div"));
    Object.assign(host.style, frame);
    const root = createRoot(host);
    flushSync(() => root.render(<PositionsGrid caption="Burst" groups={book} />));
    const burst: number[] = [];
    // Three warm-up ticks, then one second at 10 Hz: every drawn row's mark and PnL change at each tick.
    for (let tick = 1; tick <= 13; tick += 1) {
      const next = benchGroups(tick);
      const ms = measure("cv:positions-grid:tick", () =>
        flushSync(() => root.render(<PositionsGrid caption="Burst" groups={next} />)),
      );
      if (tick > 3) burst.push(ms);
    }
    root.unmount();
    host.remove();
    // Both halves are measured before either is judged, so a miss reports the two figures.
    const worst = Math.max(...burst);
    const figures = `first render median ${median.toFixed(1)} ms, burst worst ${worst.toFixed(1)} ms`;
    await expect(median, figures).toBeLessThanOrEqual(BUDGET_MS);
    await expect(worst, figures).toBeLessThanOrEqual(BUDGET_MS);
  },
};
