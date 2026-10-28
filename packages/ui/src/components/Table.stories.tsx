import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { EmptyState } from "./EmptyState.js";
import { Table, type TableColumn, type TableProps, type TableSort } from "./Table.js";
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
