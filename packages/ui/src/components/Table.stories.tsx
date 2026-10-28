import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
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
