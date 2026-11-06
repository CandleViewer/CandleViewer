import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { Icon } from "../icons/Icon.js";
import { EmptyState } from "./EmptyState.js";
import type { MenuItem } from "./Menu.js";
import {
  Table,
  type TableColumn,
  type TableProps,
  type TableRowContext,
  type TableSort,
  type TableTreeRow,
} from "./Table.js";
import { Heading } from "./Typography.js";

interface Position {
  readonly id: string;
  readonly symbol: string;
  readonly account: string;
  readonly size: number;
  readonly entry: number;
  readonly pnl: number;
}

const POSITIONS: readonly Position[] = [
  { id: "p1", symbol: "BTCUSDT", account: "Main", size: 0.25, entry: 63118, pnl: 412.5 },
  { id: "p2", symbol: "ETHUSDT", account: "Hedge", size: 3, entry: 2984.4, pnl: -120.75 },
  { id: "p3", symbol: "SOLUSDT", account: "Main", size: 40, entry: 148.32, pnl: 18 },
  { id: "p4", symbol: "XRPUSDT", account: "Swing", size: 1500, entry: 0.5321, pnl: -4.2 },
  { id: "p5", symbol: "DOGEUSDT", account: "Hedge", size: 12000, entry: 0.1294, pnl: 0 },
];

const COLUMNS: readonly TableColumn<Position>[] = [
  { id: "symbol", header: "Symbol", cell: (p) => p.symbol, sortable: true },
  { id: "account", header: "Account", cell: (p) => p.account },
  { id: "size", header: "Size", cell: (p) => p.size, numeric: "qty", sortable: true },
  { id: "entry", header: "Entry price", cell: (p) => p.entry, numeric: "price", precision: 4 },
  { id: "pnl", header: "Unrealised PnL", cell: (p) => p.pnl, numeric: "pnl", sortable: true },
];

const CAPTION = "Open positions";
const BY_PNL: TableSort = { columnId: "pnl", direction: "descending" };

const compare = (a: Position, b: Position, sort: TableSort): number => {
  const key = sort.columnId as keyof Position;
  const x = a[key];
  const y = b[key];
  const order = x < y ? -1 : x > y ? 1 : 0;
  return sort.direction === "ascending" ? order : -order;
};

/** The consumer sorts: the table only asks. */
const sorted = (rows: readonly Position[], sort: TableSort | undefined): readonly Position[] =>
  sort === undefined ? rows : [...rows].sort((a, b) => compare(a, b, sort));

type HostProps = Partial<TableProps<Position>> & { readonly initialSort?: TableSort };

/** A host that owns the sort, as every consumer does. */
function Host({ initialSort = BY_PNL, rows = POSITIONS, ...props }: HostProps): JSX.Element {
  const [sort, setSort] = useState<TableSort | undefined>(initialSort);
  return (
    <Table<Position>
      caption={CAPTION}
      columns={COLUMNS}
      rows={sorted(rows, sort)}
      rowKey={(p) => p.id}
      sort={sort}
      onSortChange={setSort}
      {...props}
    />
  );
}

const many: readonly Position[] = Array.from({ length: 40 }, (_, i) => ({
  id: `m${i}`,
  symbol: `PAIR${String(i + 1).padStart(2, "0")}USDT`,
  account: i % 2 === 0 ? "Main" : "Hedge",
  size: (i + 1) * 0.5,
  entry: 100 + i * 3.25,
  pnl: (i % 5) * 12.5 - 25,
}));

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta = {
  title: "Molecules/Table",
  component: Table,
  render: () => <Host />,
  decorators: [
    (Story) => (
      <div style={{ width: "44rem" }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj;

/** State=populated: sorted by PnL descending, Symbol and Size sortable unsorted; numbers end-aligned in mono. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = canvas.getByRole("table", { name: CAPTION });
    await expect(table).toHaveAttribute("aria-rowcount", "6");
    await expect(canvas.getByRole("columnheader", { name: "Unrealised PnL" })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
    await expect(canvas.getByRole("columnheader", { name: "Symbol" })).toHaveAttribute(
      "aria-sort",
      "none",
    );
    await expect(canvas.getByRole("columnheader", { name: "Account" })).not.toHaveAttribute(
      "aria-sort",
    );
  },
};

/** Keyboard header sort: Enter sorts ascending, then descending; the region says the result once. */
export const Sortable: Story = {
  render: () => <Host initialSort={{ columnId: "symbol", direction: "descending" }} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const button = canvas.getByRole("button", { name: "Size" });
    button.focus();
    await userEvent.keyboard("{Enter}");
    const header = canvas.getByRole("columnheader", { name: "Size" });
    await expect(header).toHaveAttribute("aria-sort", "ascending");
    await waitFor(() =>
      expect(canvas.getByRole("status")).toHaveTextContent("Sorted by Size, ascending"),
    );
    await userEvent.keyboard("{Enter}");
    await expect(header).toHaveAttribute("aria-sort", "descending");
    await expect(button).toHaveFocus();
  },
};

/** State=sorting: the pending column keeps its label and aria-sort; a spinner replaces the glyph; aria-busy. */
export const SortPending: Story = {
  render: () => (
    <Host initialSort={{ columnId: "size", direction: "ascending" }} sortPending="size" />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const button = canvas.getByRole("button", { name: "Size" });
    await expect(button).toHaveAttribute("aria-busy", "true");
    await userEvent.click(button);
    await expect(canvas.getByRole("columnheader", { name: "Size" })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
  },
};

/** State=loading: the header row kept, CMP-015 skeleton rows, the caption's loading words, aria-busy. */
export const Loading: Story = {
  render: () => <Host rows={[]} loading loadingText="Loading positions…" />,
  play: async ({ canvasElement }) => {
    const table = within(canvasElement).getByRole("table", { name: CAPTION });
    await expect(table).toHaveAttribute("aria-busy", "true");
    await expect(table).toHaveAttribute("aria-rowcount", "-1");
  },
};

/** State=empty: the header row kept; CMP-026 `no-data` across every column. */
export const Empty: Story = {
  render: () => (
    <Host
      rows={[]}
      emptyState={
        <EmptyState
          title="No open positions"
          description="Positions appear here when an order fills."
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

/** State=filtered-empty: CMP-026 `filtered-empty` with Clear filters. */
export const FilteredEmpty: Story = {
  render: () => (
    <Host
      rows={[]}
      emptyState={
        <EmptyState
          variant="filtered-empty"
          title="No rows match: Account Swing, PnL negative"
          cta={{ label: "Clear filters", onClick: () => undefined }}
        />
      }
    />
  ),
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", { name: "Clear filters" }),
    ).toBeVisible();
  },
};

/** State=error: the header row kept; CMP-027 with Retry; the table's region says it politely. */
export const ErrorStory: Story = {
  name: "Error",
  render: () => (
    <Host
      rows={[]}
      error={{ message: "Couldn't load positions — store unavailable.", onRetry: () => undefined }}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Retry" })).toBeVisible();
    await waitFor(() =>
      expect(canvas.getByRole("status")).toHaveTextContent(
        "Couldn't load positions — store unavailable.",
      ),
    );
  },
};

const longRows: readonly Position[] = [
  {
    id: "l1",
    symbol: "BTCUSDT",
    account: "Main account with a very long label that does not fit its column",
    size: 0.25,
    entry: 63118,
    pnl: 412.5,
  },
  ...POSITIONS.slice(1),
];

/** Long text: a text cell truncates with an ellipsis and keeps its full text in the DOM; numbers never do. */
export const LongText: Story = {
  render: () => <Host rows={longRows} />,
  play: async ({ canvasElement }) => {
    const cell = within(canvasElement).getByText(
      "Main account with a very long label that does not fit its column",
    );
    await expect(cell.scrollWidth).toBeGreaterThan(cell.clientWidth);
  },
};

/** Scrolling: a bounded box; the region takes a Tab stop named by the caption, the header stays on top. */
export const Scrolling: Story = {
  render: () => (
    <div style={{ height: "16rem", display: "flex", flexDirection: "column" }}>
      <Host rows={many} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const region = await canvas.findByRole("region", { name: CAPTION });
    await userEvent.tab();
    await expect(region).toHaveFocus();
    await userEvent.tab();
    await expect(canvas.getByRole("button", { name: "Symbol" })).toHaveFocus();
  },
};

/** Caption hidden: a heading names the panel, the caption still names the table. */
export const CaptionHidden: Story = {
  render: () => (
    <section aria-labelledby="positions-heading">
      <Heading level={2} variant="heading-sm" id="positions-heading">
        {CAPTION}
      </Heading>
      <Host captionHidden />
    </section>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("table", { name: CAPTION })).toBeVisible();
  },
};

/** Density=compact: 24 px rows (the toolbar sets it for every story; this one pins it). */
export const Compact: Story = {
  render: () => <Host density="compact" />,
};

/** Reflow columns: 44 em of minimums (704 px at 16 px, 1,408 px at 200 %). */
const MIN_EM: Readonly<Record<string, number>> = {
  symbol: 10,
  account: 9,
  size: 7,
  entry: 8,
  pnl: 10,
};
const REFLOW_COLUMNS: readonly TableColumn<Position>[] = COLUMNS.map((column) => ({
  ...column,
  minWidthEm: MIN_EM[column.id] ?? 8,
}));

/** Checks the stacked layout: no sideways overflow, every row with every column's value and its label. */
const stackedFits = async (canvasElement: HTMLElement): Promise<void> => {
  const canvas = within(canvasElement);
  const shell = canvasElement.querySelector<HTMLElement>('[data-cmp="CMP-049"]');
  await waitFor(() => expect(shell).toHaveAttribute("data-layout", "stacked"));
  const region = canvasElement.querySelector<HTMLElement>(".cv-table__region");
  await expect(region?.scrollWidth).toBeLessThanOrEqual(region?.clientWidth ?? 0);
  const table = canvas.getByRole("table", { name: CAPTION });
  const rows = within(table).getAllByRole("row").slice(1);
  await expect(rows).toHaveLength(POSITIONS.length);
  for (const row of rows) {
    const cells = within(row).getAllByRole("cell");
    await expect(cells).toHaveLength(REFLOW_COLUMNS.length);
    for (const [i, cell] of cells.entries()) {
      const label = cell.querySelector(".cv-table__cell-label");
      const value = cell.querySelector(".cv-table__text, [data-cmp='CMP-020']");
      await expect(value?.textContent?.trim()).not.toBe("");
      if (i === 0) await expect(label).toBeNull();
      else await expect(label).toHaveTextContent(REFLOW_COLUMNS[i]?.header ?? "");
      await expect(cell.getBoundingClientRect().right).toBeLessThanOrEqual(
        (region?.getBoundingClientRect().right ?? 0) + 0.5,
      );
    }
  }
};

/**
 * State=reflow (`16` §3 rule 4, conventions 28), compact density: at a root font size of 200 % on the 1280 x 800
 * frame, and at 640 px, the table stacks, one block per row: no sideways overflow and every column's value
 * present with its header label. Back at 100 % on the 1280 px frame it is a table again.
 */
export const Reflow: Story = {
  parameters: { layout: "fullscreen" },
  render: () => (
    // The 1280 x 800 frame (numbers: CSS px that root zoom does not scale); the inner box narrows to 640.
    <div style={{ width: 1280, height: 800 }}>
      <div data-frame="" style={{ width: "100%", height: "100%", overflow: "auto" }}>
        <Host columns={REFLOW_COLUMNS} density="compact" />
      </div>
    </div>
  ),
  play: async ({ canvasElement, step }) => {
    const root = document.documentElement;
    const frame = canvasElement.querySelector<HTMLElement>("[data-frame]");
    const shell = canvasElement.querySelector<HTMLElement>('[data-cmp="CMP-049"]');
    const before = root.style.fontSize;
    try {
      await step("100 % on 1280 px: a table", async () => {
        await waitFor(() => expect(shell).not.toHaveAttribute("data-layout"));
      });
      await step("200 % on 1280 x 800: stacked", async () => {
        root.style.fontSize = "200%";
        await stackedFits(canvasElement);
      });
      await step("200 % at 640 px: stacked", async () => {
        if (frame !== null) frame.style.width = "50%"; // 640 px
        await stackedFits(canvasElement);
      });
      await step("back to 100 % on 1280 px: a table again", async () => {
        if (frame !== null) frame.style.width = "100%";
        root.style.fontSize = before;
        await waitFor(() => expect(shell).not.toHaveAttribute("data-layout"));
        await expect(
          within(canvasElement).getByRole("table", { name: CAPTION }),
        ).not.toHaveAttribute("role");
      });
    } finally {
      root.style.fontSize = before;
    }
  },
};

const BUDGET_MS = 16.7;
const BOUND: readonly Position[] = Array.from({ length: 200 }, (_, i) => ({
  id: `b${i}`,
  symbol: `PAIR${String(i + 1).padStart(3, "0")}USDT`,
  account: ["Main", "Hedge", "Swing"][i % 3] ?? "Main",
  size: (i + 1) * 0.25,
  entry: 100 + i * 1.75,
  pnl: (i % 7) * 9.5 - 30,
}));

/**
 * The frame budget: a first render (a fresh root, the 200-row v0 bound, the DOM commit) stays within one frame,
 * the median of 15 warmed mounts. Tagged `perf`: a wall-clock budget is no pass/fail check on a shared runner,
 * so the storybook project skips it (#269) unless `CV_STORYBOOK_PERF=1`.
 */
export const Perf200Rows: Story = {
  tags: ["perf"],
  render: () => (
    <p>200-row first-render benchmark: the play function mounts and times the table.</p>
  ),
  play: async ({ canvasElement }) => {
    const samples: number[] = [];
    for (let i = 0; i < 20; i += 1) {
      const host = canvasElement.appendChild(document.createElement("div"));
      const root = createRoot(host);
      const start = performance.now();
      flushSync(() =>
        root.render(
          <Table<Position>
            caption={`Bound ${String(i)}`}
            columns={COLUMNS}
            rows={BOUND}
            rowKey={(p) => p.id}
          />,
        ),
      );
      samples.push(performance.now() - start);
      root.unmount();
      host.remove();
    }
    const median = samples.slice(5).sort((a, b) => a - b)[7] ?? Infinity;
    await expect(median).toBeLessThanOrEqual(BUDGET_MS);
  },
};

/** The row menu (D02F G21): an action, a T2 item with its `rbac.owner_only` reason (D09 §2.4, SCR-063), a danger. */
const rowMenu = (p: Position): readonly MenuItem[] => [
  { id: "chart", label: `Open ${p.symbol} chart`, onSelect: () => undefined },
  {
    id: "caps",
    label: "Edit risk caps",
    disabledReason: "Only the owner can change account settings.",
    onSelect: () => undefined,
  },
  {
    id: "close",
    label: "Close position",
    danger: true,
    opensConfirm: true,
    onSelect: () => undefined,
  },
];

/** A host that owns the selection, as every consumer does. */
function SelectHost({
  initial = [],
  ...props
}: HostProps & { readonly initial?: readonly string[] }): JSX.Element {
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set(initial));
  return <Host selected={selected} onRowSelect={setSelected} {...props} />;
}

/** The table's own polite line (a row menu with a T2 item keeps its own reason region, CMP-041). */
const liveLine = (canvasElement: HTMLElement): HTMLElement | null =>
  canvasElement.querySelector<HTMLElement>(".cv-table__live");

/**
 * Selection=multiple (G21): a leading CMP-005 column, two rows selected on `color.action.selected`, the select-all
 * box mixed. The select column makes it a grid: `Space` toggles the focused row and the table says the count once.
 */
export const Selectable: Story = {
  render: () => <SelectHost initial={["p1", "p4"]} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const grid = canvas.getByRole("grid", { name: CAPTION });
    await expect(grid).toHaveAttribute("aria-multiselectable", "true");
    const all = canvas.getByRole("checkbox", { name: "Select all rows" });
    await expect(all).toBePartiallyChecked();
    await expect(canvas.getByRole("checkbox", { name: "Select BTCUSDT" })).toBeChecked();
    await userEvent.tab();
    await userEvent.keyboard("{ArrowDown}{ArrowRight}");
    // Sorted by PnL descending: BTCUSDT, then SOLUSDT.
    await expect(canvas.getByRole("gridcell", { name: "SOLUSDT" })).toHaveFocus();
    await userEvent.keyboard(" ");
    await expect(canvas.getByRole("checkbox", { name: "Select SOLUSDT" })).toBeChecked();
    await waitFor(() => expect(liveLine(canvasElement)).toHaveTextContent("3 selected"));
    await userEvent.click(all);
    await expect(all).toBeChecked();
    await waitFor(() => expect(liveLine(canvasElement)).toHaveTextContent("5 selected"));
  },
};

/**
 * Selection=denied (T2, RBAC): the select column stays so the table's shape holds, every CMP-005 is disabled with the
 * reason and nothing can be selected.
 */
export const SelectDenied: Story = {
  render: () => <SelectHost selectDisabledReason="Your role can't change alerts." />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const all = canvas.getByRole("checkbox", { name: "Select all rows" });
    await expect(all).toHaveAttribute("aria-disabled", "true");
    await expect(all).toHaveAccessibleDescription("Your role can't change alerts.");
    await userEvent.click(canvas.getByRole("checkbox", { name: "Select BTCUSDT" }));
    await expect(canvas.getByRole("checkbox", { name: "Select BTCUSDT" })).not.toBeChecked();
  },
};

/**
 * Mode=grid (the APG Grid pattern), implied by the actions column: one Tab stop, the arrows by cell with the header
 * row in their path, the CMP-039 ring on the focused cell. In a bounded box a focused cell scrolls below the sticky
 * header (`scroll-margin-top` is the header's height), so focus is never hidden under it (WCAG 2.4.11).
 */
export const Grid: Story = {
  render: () => (
    <div style={{ height: "16rem", display: "flex", flexDirection: "column" }}>
      <Host rows={many} rowActions={rowMenu} />
    </div>
  ),
  play: async ({ canvasElement, step }) => {
    const canvas = within(canvasElement);
    const grid = canvas.getByRole("grid", { name: CAPTION });
    const header = grid.querySelector("thead") as HTMLElement;
    const focused = (): HTMLElement => document.activeElement as HTMLElement;
    const cellOfFocus = (): HTMLElement => focused().closest("td, th") as HTMLElement;
    /** The focused cell's top edge is at or below the sticky header's bottom edge. */
    const notUnderHeader = async (): Promise<void> => {
      const top = cellOfFocus().getBoundingClientRect().top;
      await expect(top).toBeGreaterThanOrEqual(header.getBoundingClientRect().bottom - 1);
    };
    await step("one Tab stop: in on the first body cell, out on the next Tab", async () => {
      await userEvent.tab();
      await expect(focused()).toHaveTextContent(/USDT$/);
      await expect(grid.querySelectorAll('[tabindex="0"]')).toHaveLength(1);
    });
    await step("the scroll margin is the header's height", async () => {
      const margin = parseFloat(getComputedStyle(cellOfFocus()).scrollMarginTop);
      await expect(Math.abs(margin - header.getBoundingClientRect().height)).toBeLessThanOrEqual(1);
    });
    await step("Page Down, then back up row by row: focus is never under the header", async () => {
      await userEvent.keyboard("{PageDown}{PageDown}{PageDown}");
      await notUnderHeader();
      for (let i = 0; i < 6; i += 1) {
        await userEvent.keyboard("{ArrowUp}");
        await notUnderHeader();
      }
    });
    await step("End reaches the actions button; Ctrl+Home the header's first cell", async () => {
      await userEvent.keyboard("{End}");
      await expect(focused()).toHaveAccessibleName(/^Actions for PAIR\d\dUSDT$/);
      await userEvent.keyboard("{Control>}{Home}{/Control}");
      await expect(canvas.getByRole("button", { name: "Symbol" })).toHaveFocus();
    });
  },
};

/**
 * Row actions (G21): the trailing `more-horizontal` IconButton "Actions for {row}" opens the CMP-041 row menu, and
 * `Shift+F10` on a focused row opens the same items at the row. "Edit risk caps" is T2 (2a): reachable by the
 * arrows, its reason as the second line, never activated. `Esc` returns focus to the cell it opened from.
 */
export const RowActions: Story = {
  render: () => <Host rowActions={rowMenu} />,
  play: async ({ canvasElement, step }) => {
    const canvas = within(canvasElement);
    const page = within(document.body);
    await step("the actions button opens the row menu; Esc returns to it", async () => {
      const button = canvas.getByRole("button", { name: "Actions for ETHUSDT" });
      button.focus();
      await userEvent.keyboard("{Enter}");
      const menu = await page.findByRole("menu", { name: "Actions for ETHUSDT" });
      await userEvent.keyboard("{ArrowDown}");
      const caps = within(menu).getByRole("menuitem", { name: /Edit risk caps/ });
      await expect(caps).toHaveFocus();
      await expect(caps).toHaveAttribute("aria-disabled", "true");
      await expect(caps).toHaveAccessibleDescription(
        /Only the owner can change account settings\./,
      );
      await userEvent.keyboard("{Enter}");
      await expect(caps).toBeVisible(); // refused: the menu stays open
      await userEvent.keyboard("{Escape}");
      await waitFor(() => expect(button).toHaveFocus());
    });
    await step(
      "Shift+F10 on a focused row opens the same menu; Esc returns to the cell",
      async () => {
        await userEvent.keyboard("{ArrowLeft}");
        const cell = document.activeElement as HTMLElement;
        await userEvent.keyboard("{Shift>}{F10}{/Shift}");
        const menu = await page.findByRole("menu", { name: "Actions for ETHUSDT" });
        await expect(
          within(menu).getByRole("menuitem", { name: "Open ETHUSDT chart" }),
        ).toHaveFocus();
        await userEvent.keyboard("{Escape}");
        await waitFor(() => expect(cell).toHaveFocus());
      },
    );
  },
};

/** A custom row (`renderRow`, CMP-049's row contract): the symbol is the row header, the values its cells. */
const positionRow = (p: Position, grid: TableRowContext): JSX.Element =>
  p.id === "p3" ? (
    // A merged cell: one cell over Account to Unrealised PnL, a native colspan, one cell to the arrows.
    <tr {...grid.rowProps}>
      <th {...grid.cellProps(0, { header: true })}>{p.symbol}</th>
      <td {...grid.cellProps(1, { span: 4 })}>Delisted by the exchange</td>
    </tr>
  ) : (
    <tr {...grid.rowProps}>
      <th {...grid.cellProps(0, { header: true })}>{p.symbol}</th>
      <td {...grid.cellProps(1)}>
        {grid.label(1)}
        {p.account}
      </td>
      <td {...grid.cellProps(2, { numeric: true })}>
        {grid.label(2)}
        {p.size}
      </td>
      <td {...grid.cellProps(3, { numeric: true })}>
        {grid.label(3)}
        {p.entry.toFixed(4)}
      </td>
      <td {...grid.cellProps(4, { numeric: true })}>
        {grid.label(4)}
        {p.pnl.toFixed(2)}
      </td>
    </tr>
  );

/**
 * Grid mode, merged cells (E08-D07 D20, §5): a custom row merges cells into one (a native `colspan`); the arrows
 * treat it as one cell: → reaches it from the row header and stays on it, ← leaves it.
 */
export const MergedCell: Story = {
  render: () => <Host grid renderRow={positionRow} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const header = canvas.getByRole("rowheader", { name: "SOLUSDT" });
    header.focus();
    await userEvent.keyboard("{ArrowRight}");
    const merged = canvas.getByRole("gridcell", { name: "Delisted by the exchange" });
    await expect(merged).toHaveFocus();
    await expect(merged).toHaveAttribute("colspan", "4");
    await userEvent.keyboard("{ArrowRight}");
    await expect(merged).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    await expect(header).toHaveFocus();
  },
};

const LIVE_SORT = "Live sort needs every symbol live.";
const GATED: readonly TableColumn<Position>[] = COLUMNS.map((column) =>
  column.id === "size" || column.id === "pnl"
    ? { ...column, sortable: true, sortDisabledReason: LIVE_SORT }
    : column,
) as readonly TableColumn<Position>[];

/**
 * A T2 sort header (E08-D07 §6.6, D5): the button keeps its label, `aria-sort` and focus; the lock before the label,
 * named "Not available", `aria-disabled`, described by the host's one note (in the design-system face, as a host's text
 * is). A press sorts nothing and re-shows the reason in the echo.
 */
export const SortUnavailable: Story = {
  render: () => (
    <div style={{ fontFamily: "var(--font-family-ui), system-ui, sans-serif" }}>
      <Host grid columns={GATED} sortReasonId="sort-note" />
      <p id="sort-note">{LIVE_SORT}</p>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const size = within(canvasElement).getByRole("button", { name: "Not available Size" });
    await expect(size).toHaveAttribute("aria-disabled", "true");
    await expect(size).toHaveAccessibleDescription(LIVE_SORT);
    size.focus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() =>
      expect(document.querySelector(".cv-table__echo:not([hidden])")).toHaveTextContent(LIVE_SORT),
    );
    await expect(
      within(canvasElement).getByRole("columnheader", { name: "Not available Size" }),
    ).toHaveAttribute("aria-sort", "none");
  },
};

const LONG: readonly Position[] = Array.from({ length: 300 }, (_, i) => ({
  id: `w${i}`,
  symbol: `PAIR${String(i + 1).padStart(3, "0")}USDT`,
  account: ["Main", "Hedge", "Swing"][i % 3] ?? "Main",
  size: (i + 1) * 0.25,
  entry: 100 + i * 1.75,
  pnl: (i % 7) * 9.5 - 30,
}));

/** A host that draws a window of a long list: the rows in view and 10 either side (SCR-100 past 60 rows). */
function WindowHost(): JSX.Element {
  const [first, setFirst] = useState(0);
  const offset = Math.max(0, Math.min(first - 10, LONG.length - 40));
  return (
    <div style={{ height: "16rem", display: "flex", flexDirection: "column" }}>
      <Table<Position>
        grid
        caption="Positions, 300"
        columns={COLUMNS}
        rows={LONG.slice(offset, offset + 40)}
        rowKey={(p) => p.id}
        rowWindow={{ offset, total: LONG.length }}
        onRowsInView={(top) => setFirst(top)}
      />
    </div>
  );
}

/**
 * Grid mode, the host's window (E08-D07 D6; `14` SCR-100 "virtualised beyond 60 rows"): 300 rows, 40 drawn between
 * spacer rows; `aria-rowcount` counts them all and `aria-rowindex` is absolute; Ctrl+End draws the last row, then
 * focuses it.
 */
export const WindowedRows: Story = {
  render: () => <WindowHost />,
  play: async ({ canvasElement }) => {
    const table = within(canvasElement).getByRole("grid", { name: "Positions, 300" });
    await expect(table).toHaveAttribute("aria-rowcount", "301");
    within(table).getAllByRole("gridcell")[0]?.focus();
    await userEvent.keyboard("{Control>}{End}{/Control}");
    await waitFor(() =>
      expect(document.activeElement?.closest("tr")).toHaveAttribute("aria-rowindex", "301"),
    );
  },
};

/*
 * The treegrid variant (E29-D04 §2.7; D04H A-6.2 to A-6.6): account groups at level 1 holding their positions at
 * level 2, `aria-posinset` / `aria-setsize` from the model (E29-D05 §5.3 F-03), a group row's one merged cell its
 * rowheader and its tree cell. The host flattens the tree and owns which groups are open.
 */
type TreeEntry =
  | {
      readonly kind: "group";
      readonly id: string;
      readonly account: string;
      readonly count: number;
    }
  | { readonly kind: "position"; readonly id: string; readonly position: Position }
  | { readonly kind: "total"; readonly id: string; readonly count: number; readonly pnl: number };

const ACCOUNTS = ["Main", "Hedge", "Swing"] as const;

/** The groups in order, each with its positions, from a flat list. */
const groupsOf = (positions: readonly Position[]): readonly (readonly [string, Position[]])[] =>
  ACCOUNTS.map((account) => [account, positions.filter((p) => p.account === account)] as const)
    .filter(([, members]) => members.length > 0)
    .map(([account, members]) => [account, [...members]] as const);

/** The visible tree, flattened, and each entry's place in it (from the model, never the DOM). */
function flatten(
  positions: readonly Position[],
  open: ReadonlySet<string>,
): { readonly entries: readonly TreeEntry[]; readonly places: ReadonlyMap<string, TableTreeRow> } {
  const groups = groupsOf(positions);
  const entries: TreeEntry[] = [];
  const places = new Map<string, TableTreeRow>();
  groups.forEach(([account, members], g) => {
    const id = `group:${account}`;
    const expanded = open.has(account);
    entries.push({ kind: "group", id, account, count: members.length });
    places.set(id, { level: 1, expanded, posinset: g + 1, setsize: groups.length });
    if (!expanded) return;
    members.forEach((position, i) => {
      entries.push({ kind: "position", id: position.id, position });
      places.set(position.id, { level: 2, posinset: i + 1, setsize: members.length });
    });
  });
  return { entries, places };
}

const positionsWord = (n: number): string => (n === 1 ? "1 position" : `${String(n)} positions`);

/** The tree's columns: CMP-049 draws their headers (numbers end-aligned); the custom rows draw every cell. */
const treeColumns = (
  columns: readonly TableColumn<Position>[],
): readonly TableColumn<TreeEntry>[] =>
  columns.map((column) => ({
    id: column.id,
    header: column.header,
    cell: (entry: TreeEntry) => entry.id,
    ...(column.numeric === undefined ? {} : { align: "end" as const }),
    ...(column.widthEm === undefined ? {} : { widthEm: column.widthEm }),
  }));

/** A group's one merged cell is its rowheader and its tree cell: → and ←, or a click, open and close it. */
const treeEntryRow = (entry: TreeEntry, grid: TableRowContext): JSX.Element => {
  if (entry.kind === "group") {
    const open = grid.rowProps["aria-expanded"] === true;
    return (
      <tr {...grid.rowProps}>
        <th {...grid.cellProps(0, { header: true, span: COLUMNS.length })}>
          <Icon name={open ? "chevron-down" : "chevron-right"} />
          {` ${entry.account} · ${positionsWord(entry.count)}`}
        </th>
      </tr>
    );
  }
  if (entry.kind === "total")
    return (
      <tr {...grid.rowProps}>
        <th {...grid.cellProps(0, { header: true, span: 4 })}>
          {`Total · ${positionsWord(entry.count)}`}
        </th>
        <td {...grid.cellProps(4, { numeric: true })}>{entry.pnl.toFixed(2)}</td>
      </tr>
    );
  const p = entry.position;
  return (
    <tr {...grid.rowProps}>
      <th {...grid.cellProps(0, { header: true })}>{p.symbol}</th>
      <td {...grid.cellProps(1)}>{p.account}</td>
      <td {...grid.cellProps(2, { numeric: true })}>{p.size}</td>
      <td {...grid.cellProps(3, { numeric: true })}>{p.entry.toFixed(4)}</td>
      <td {...grid.cellProps(4, { numeric: true })}>{p.pnl.toFixed(2)}</td>
    </tr>
  );
};

type TreeHostProps = Partial<TableProps<TreeEntry>> & {
  readonly positions?: readonly Position[];
  readonly initiallyOpen?: readonly string[];
  readonly withTotals?: boolean;
  /** A window of this many entries, with the focused row kept mounted outside it (G-01). */
  readonly windowSize?: number;
};

/** The treegrid's host: it flattens the open groups, windows them when asked and finds any row by key. */
function TreeHost({
  positions = POSITIONS,
  initiallyOpen = [],
  withTotals = false,
  windowSize,
  ...props
}: TreeHostProps): JSX.Element {
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set(initiallyOpen));
  const [first, setFirst] = useState(0);
  const { entries, places } = flatten(positions, open);
  const toggle = (account: string): void => {
    const next = new Set(open);
    if (next.has(account)) next.delete(account);
    else next.add(account);
    setOpen(next);
  };
  const size = windowSize ?? entries.length;
  const offset = Math.max(0, Math.min(first - 10, entries.length - size));
  const totals: readonly TreeEntry[] = withTotals
    ? [
        {
          kind: "total",
          id: "total",
          count: positions.length,
          pnl: positions.reduce((sum, p) => sum + p.pnl, 0),
        },
      ]
    : [];
  return (
    <Table<TreeEntry>
      treegrid
      caption={CAPTION}
      columns={treeColumns(COLUMNS)}
      rows={entries.slice(offset, offset + size)}
      rowKey={(entry) => entry.id}
      treeRow={(entry) => places.get(entry.id) ?? { level: 1, posinset: 1, setsize: 1 }}
      onExpandedChange={(entry) => {
        if (entry.kind === "group") toggle(entry.account);
      }}
      renderRow={treeEntryRow}
      totalRows={totals}
      {...(windowSize === undefined
        ? {}
        : {
            rowWindow: { offset, total: entries.length },
            onRowsInView: (top: number) => setFirst(top),
            rowByKey: (key: string) => {
              const index = entries.findIndex((entry) => entry.id === key);
              const row = entries[index];
              return row === undefined ? undefined : { row, index };
            },
          })}
      {...props}
    />
  );
}

/** The cell a play's keys act on, and its row's place. */
const focusedRow = (): HTMLElement | null =>
  (document.activeElement as HTMLElement | null)?.closest("tr") ?? null;

/**
 * Variant=treegrid, collapsed (the APG Treegrid pattern): three account groups at level 1, each `aria-expanded` false;
 * → on a group's cell opens it, → again moves to its first child, ← moves back to the parent, ← closes it.
 */
export const Treegrid: Story = {
  render: () => <TreeHost />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const tree = canvas.getByRole("treegrid", { name: CAPTION });
    const main = within(tree).getByRole("rowheader", { name: /Main · 2 positions/ });
    await expect(main.closest("tr")).toHaveAttribute("aria-expanded", "false");
    main.focus();
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() => expect(main.closest("tr")).toHaveAttribute("aria-expanded", "true"));
    await expect(main).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}");
    await expect(focusedRow()).toHaveAttribute("aria-level", "2");
    await userEvent.keyboard("{ArrowLeft}");
    await expect(main).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    await waitFor(() => expect(main.closest("tr")).toHaveAttribute("aria-expanded", "false"));
  },
};

/** Variant=treegrid, expanded: every group open; levels, set positions and absolute row indices from the model. */
export const TreegridExpanded: Story = {
  render: () => <TreeHost initiallyOpen={ACCOUNTS} />,
  play: async ({ canvasElement }) => {
    const tree = within(canvasElement).getByRole("treegrid", { name: CAPTION });
    const rows = within(tree).getAllByRole("row").slice(1);
    await expect(rows.map((row) => row.getAttribute("aria-level"))).toEqual([
      "1",
      "2",
      "2",
      "1",
      "2",
      "2",
      "1",
      "2",
    ]);
    await expect(rows[4]).toHaveAttribute("aria-posinset", "1");
    await expect(rows[4]).toHaveAttribute("aria-setsize", "2");
    await expect(rows[6]).toHaveAttribute("aria-posinset", "3");
    await expect(rows[6]).toHaveAttribute("aria-setsize", "3");
    await expect(rows[7]).toHaveAttribute("aria-rowindex", "9");
  },
};

/** Twelve positions on three accounts: a list wide and long enough to scroll both ways in a small box. */
const WIDE_COLUMNS: readonly TableColumn<Position>[] = COLUMNS.map((column) => ({
  ...column,
  widthEm: column.id === "symbol" || column.id === "pnl" ? 10 : 9,
}));
const TWELVE: readonly Position[] = Array.from({ length: 12 }, (_, i) => ({
  id: `t${String(i)}`,
  symbol: `PAIR${String(i + 1).padStart(2, "0")}USDT`,
  account: ACCOUNTS[i % 3] ?? "Main",
  size: (i + 1) * 0.5,
  entry: 100 + i * 3.25,
  pnl: (i % 5) * 12.5 - 25,
}));

/**
 * Pinned columns (E29-D04 §2.7; E29-D05 §6.2 F-01): the symbol and the account stay at the region's start and the
 * last column at its end while the treegrid scrolls sideways; a focused cell scrolls clear of them.
 */
export const StickyLeadColumns: Story = {
  render: () => (
    <div style={{ width: "26rem", height: "14rem", display: "flex", flexDirection: "column" }}>
      <TreeHost
        positions={TWELVE}
        initiallyOpen={ACCOUNTS}
        columns={treeColumns(WIDE_COLUMNS)}
        stickyFirstColumn={2}
        stickyLastColumn
      />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const tree = within(canvasElement).getByRole("treegrid", { name: CAPTION });
    const region = canvasElement.querySelector<HTMLElement>(".cv-table__region");
    const symbol = within(tree).getByRole("columnheader", { name: "Symbol" });
    await expect(symbol).toHaveAttribute("data-pin-start", "0");
    await expect(within(tree).getByRole("columnheader", { name: "Account" })).toHaveAttribute(
      "data-pin-start",
      "1",
    );
    await expect(
      within(tree).getByRole("columnheader", { name: "Unrealised PnL" }),
    ).toHaveAttribute("data-pin-end", "");
    if (region === null || region.scrollWidth <= region.clientWidth) return; // no layout to scroll (jsdom)
    const before = symbol.getBoundingClientRect().left;
    region.scrollLeft = region.scrollWidth;
    await waitFor(() => expect(symbol.getBoundingClientRect().left).toBeCloseTo(before, 0));
  },
};

/** The trailing totals rowgroup (D04H A-6.4): pinned, after every body row, led by its rowheader; ↓ reaches it. */
export const TotalsRowgroup: Story = {
  render: () => (
    <div style={{ height: "14rem", display: "flex", flexDirection: "column" }}>
      <TreeHost positions={TWELVE} initiallyOpen={ACCOUNTS} withTotals />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const tree = within(canvasElement).getByRole("treegrid", { name: CAPTION });
    const groups = within(tree).getAllByRole("rowgroup");
    const totals = groups[groups.length - 1];
    if (totals === undefined) throw new Error("no totals rowgroup");
    const header = within(totals).getByRole("rowheader", { name: "Total · 12 positions" });
    await expect(header.closest("tr")).toHaveAttribute("aria-rowindex", "17");
    await expect(tree).toHaveAttribute("aria-rowcount", "17");
    const rows = within(tree).getAllByRole("row");
    within(rows[rows.length - 2] ?? tree)
      .getAllByRole("gridcell")[0]
      ?.focus();
    await userEvent.keyboard("{ArrowDown}");
    await expect(focusedRow()).toHaveAttribute("aria-rowindex", "17");
  },
};

/** 288 rows: three accounts of 95 positions each, and their group rows. */
const MANY_TREE: readonly Position[] = Array.from({ length: 285 }, (_, i) => ({
  id: `f${String(i)}`,
  symbol: `PAIR${String(i + 1).padStart(3, "0")}USDT`,
  account: ACCOUNTS[i % 3] ?? "Main",
  size: (i + 1) * 0.25,
  entry: 100 + i * 1.75,
  pnl: (i % 7) * 9.5 - 30,
}));

/**
 * G-01 (E29-D05 §5.3): the focused row stays mounted when the window scrolls away from it, the one drawn row outside
 * the window, at its absolute `aria-rowindex`; focus never falls to the page.
 */
export const FocusedRowOutsideWindow: Story = {
  render: () => (
    <div style={{ height: "14rem", display: "flex", flexDirection: "column" }}>
      <TreeHost positions={MANY_TREE} initiallyOpen={ACCOUNTS} windowSize={40} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const tree = within(canvasElement).getByRole("treegrid", { name: CAPTION });
    const second = within(tree).getAllByRole("row")[2];
    within(second ?? tree)
      .getAllByRole("gridcell")[0]
      ?.focus();
    const row = focusedRow();
    await expect(row).toHaveAttribute("aria-rowindex", "3");
    const region = canvasElement.querySelector<HTMLElement>(".cv-table__region");
    if (region === null || region.scrollHeight <= region.clientHeight) return; // no layout to scroll (jsdom)
    region.scrollTop = region.scrollHeight;
    await waitFor(() => expect(tree.querySelector('tr[aria-rowindex="289"]')).not.toBeNull());
    await expect(row?.isConnected).toBe(true);
    await expect(focusedRow()).toBe(row);
    await expect(row).toHaveAttribute("aria-rowindex", "3");
  },
};

/** The treegrid's states under the light and high-contrast themes; axe checks each theme. */
const treeTheme = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: () => <TreeHost initiallyOpen={["Main"]} withTotals />,
});
export const ContrastLight: Story = treeTheme("light");
export const ContrastHighContrast: Story = treeTheme("high-contrast");

/**
 * A row's write in flight (`rowBusy`, E42-D03 U-7): ETHUSDT's ⋯ is CMP-002 `busy`, "Closing ETHUSDT…", the same
 * focusable control; neither its menu nor the context menu opens until the words go; the other rows are as before.
 */
export const RowActionsBusy: Story = {
  render: () => (
    <Host
      rowActions={rowMenu}
      rowBusy={(p) => (p.symbol === "ETHUSDT" ? "Closing ETHUSDT…" : undefined)}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const busy = canvas.getByRole("button", { name: "Closing ETHUSDT…" });
    await expect(busy).toHaveAttribute("aria-busy", "true");
    busy.focus();
    await userEvent.keyboard("{Enter}");
    await expect(within(document.body).queryByRole("menu")).toBeNull();
    await expect(busy).toHaveFocus();
    await expect(canvas.getByRole("button", { name: "Actions for BTCUSDT" })).not.toHaveAttribute(
      "aria-busy",
    );
  },
};
