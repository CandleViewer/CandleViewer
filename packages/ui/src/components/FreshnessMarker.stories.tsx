import type { Meta, StoryObj } from "@storybook/react-vite";
import type { JSX } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import {
  DATA_CONFIDENCE_PRECEDENCE,
  FreshnessMarker,
  freshnessClassName,
} from "./FreshnessMarker.js";
import { Table } from "./Table.js";
import { WatchlistRow, watchlistColumns, type WatchlistRowData } from "./WatchlistRow.js";

/** The design-system face on the stories' wrapper, so a host's own text never falls back to the browser's serif. */
const FONT = "var(--font-family-ui), system-ui, sans-serif";

/**
 * CMP-239's compact presentation (E08-D07 §5): the age chip a dense grid draws once per row, and the class swap a
 * degraded cell takes. The chip form with every state's word is CMP-239's base, built with its first consumer.
 */
const meta: Meta<typeof FreshnessMarker> = {
  title: "Atoms/FreshnessMarker",
  component: FreshnessMarker,
  args: { presentation: "compact", state: "stale", lastUpdatedAgeMs: 7000 },
  decorators: [
    (Story) => (
      <div style={{ fontFamily: FONT }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof FreshnessMarker>;

/** Stale, T1 (E08-D07 D1): the subtle chip, "Stale 7s", read "Stale, 7 seconds". */
export const Stale: Story = {
  play: async ({ canvasElement }) => {
    const chip = canvasElement.querySelector('[data-cmp="CMP-239"]') as HTMLElement;
    await expect(chip).toHaveAttribute("data-level", "subtle");
    await expect(within(chip).getByText("Stale, 7 seconds")).toBeInTheDocument();
  },
};

const SOL: WatchlistRowData = { symbol: "SOLUSDT", priceScale: 2, lastPrice: 142.37 };
const HOST_COLUMNS = ["symbol", "last"] as const;

/**
 * The chip's one interactive host (CMP-161's Status cell, E08-D07 §4.2 board 03): the chip is no control of its own,
 * and the cell holding it shows the row's last update in CMP-049's echo, the chip's tooltip (D7).
 */
function StatusCell(): JSX.Element {
  return (
    <div style={{ width: "24rem" }}>
      <Table<WatchlistRowData>
        grid
        reflow="grid"
        caption="Watchlist Majors, 1 symbol, manual order"
        captionHidden
        columns={watchlistColumns(HOST_COLUMNS)}
        rows={[SOL]}
        rowKey={(row) => row.symbol}
        renderRow={(row, grid) => (
          <WatchlistRow
            grid={grid}
            row={row}
            columns={HOST_COLUMNS}
            freshness={{
              ticker: { state: "stale", ageMs: 7000, detail: "Last update 10:31:02 UTC" },
            }}
          />
        )}
      />
    </div>
  );
}
const echoShown = (): Element | null => document.querySelector(".cv-table__echo:not([hidden])");

/** Hover: the pointer on the chip, in its Status cell: after CMP-016's 300 ms the row's last update shows in the echo. */
export const Hover: Story = {
  render: () => <StatusCell />,
  play: async ({ canvasElement }) => {
    const chip = canvasElement.querySelector('[data-cmp="CMP-239"]');
    if (chip === null) throw new Error("no chip");
    await userEvent.hover(chip);
    // CMP-016 shows a hover echo after 300 ms: give a loaded runner more than waitFor's 1 s default.
    await waitFor(() => expect(echoShown()).toHaveTextContent("Last update 10:31:02 UTC"), {
      timeout: 3000,
    });
  },
};

/**
 * FocusVisible: the chip takes no focus; its Status cell does (Tab, then End along the row): the cell's inset ring
 * around the chip, and the row's last update in the echo at once.
 */
export const FocusVisible: Story = {
  render: () => <StatusCell />,
  play: async ({ canvasElement }) => {
    const chip = canvasElement.querySelector<HTMLElement>('[data-cmp="CMP-239"]');
    await userEvent.tab();
    await userEvent.keyboard("{End}");
    const cell = document.activeElement;
    await expect(cell).toContainElement(chip);
    await expect(chip).not.toHaveAttribute("tabindex");
    await waitFor(() => expect(echoShown()).toHaveTextContent("Last update 10:31:02 UTC"));
  },
};

/** Stale past T2 (15 s): the strong chip. */
export const StaleEscalated: Story = {
  args: { lastUpdatedAgeMs: 15_000, escalated: true },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector('[data-cmp="CMP-239"]')).toHaveAttribute(
      "data-level",
      "strong",
    );
  },
};

/** Flagged by the server (`meta.stale`, E17-D01 L149): "Stale (server)", T1's style until T2. */
export const StaleServer: Story = {
  args: { label: "Stale (server)" },
  play: async ({ canvasElement }) => {
    await expect(canvasElement).toHaveTextContent("Stale (server)");
  },
};

/** The age in its largest whole unit (E08-D07 D34): seconds, then minutes, then hours. */
export const AgeFormats: Story = {
  render: () => (
    <div style={{ display: "flex", gap: "1rem" }}>
      <FreshnessMarker presentation="compact" state="stale" lastUpdatedAgeMs={7000} />
      <FreshnessMarker presentation="compact" state="stale" lastUpdatedAgeMs={125_000} escalated />
      <FreshnessMarker
        presentation="compact"
        state="stale"
        lastUpdatedAgeMs={3_700_000}
        escalated
      />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const shown = [...canvasElement.querySelectorAll('[data-cmp="CMP-239"] [aria-hidden="true"]')];
    await expect(shown.map((node) => node.textContent)).toEqual([
      "Stale 7s",
      "Stale 2m",
      "Stale 1h",
    ]);
  },
};

/**
 * The cell marker: each degraded state is one className on the cell that holds the value, never a node of its own
 * (`freshnessClassName`); `live` adds nothing. The state names beside the cells are this page's, not the marker's.
 */
export const CellClasses: Story = {
  render: () => (
    <table>
      <tbody>
        {DATA_CONFIDENCE_PRECEDENCE.map((state) => (
          <tr key={state}>
            <th scope="row" style={{ textAlign: "start", paddingInlineEnd: "1rem" }}>
              {state}
            </th>
            <td className={freshnessClassName(state)} style={{ paddingInline: "0.5rem" }}>
              64,012.50
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  ),
  play: async ({ canvasElement }) => {
    const cells = [...canvasElement.querySelectorAll("td")];
    await expect(cells.map((cell) => cell.childNodes.length)).toEqual(cells.map(() => 1));
    await expect(cells.at(-1)?.className ?? "").toBe("");
  },
};
