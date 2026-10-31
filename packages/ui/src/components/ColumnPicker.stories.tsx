import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { ColumnPicker, type ColumnPickerColumn } from "./ColumnPicker.js";

/** SCR-100's columns (E08-D07 D8): the defaults, then two optional ones; Symbol is locked. */
const COLUMNS: readonly ColumnPickerColumn[] = [
  {
    id: "symbol",
    label: "Symbol",
    visible: true,
    lockedReason: "The symbol column is always shown.",
  },
  { id: "last", label: "Last", visible: true },
  { id: "chg_24h_pct", label: "24h %", visible: true },
  { id: "turnover_24h", label: "Turnover USDT", visible: true },
  { id: "funding_rate", label: "Funding %", visible: true },
  { id: "next_funding", label: "Funding in", visible: true },
  { id: "oi_chg_24h_pct", label: "OI Δ 24h %", visible: true },
  { id: "spread_bps", label: "Spread bps", visible: true },
  { id: "rec", label: "Rec", visible: true },
  { id: "mark_price", label: "Mark", visible: false },
  { id: "index_price", label: "Index", visible: false },
];
const READ_ONLY = "Read-only — your role can't change watchlists.";
/** The design-system face on the stories' wrapper, so a host's own text never falls back to the browser's serif. */
const FONT = "var(--font-family-ui), system-ui, sans-serif";

const hide = (
  all: readonly ColumnPickerColumn[],
  id: string,
  visible: boolean,
): ColumnPickerColumn[] =>
  all.map((column) => (column.id === id ? { ...column, visible } : column));

/** The list a dialog's Columns tab holds (SCR-101), its host owning the columns. */
function ListHost({
  writeReason,
  writeReasonId,
}: {
  readonly writeReason?: string;
  readonly writeReasonId?: string;
}): JSX.Element {
  const [columns, setColumns] = useState(COLUMNS);
  return (
    <ColumnPicker
      label="Columns"
      columns={columns}
      {...(writeReason === undefined ? {} : { writeReason })}
      {...(writeReasonId === undefined ? {} : { writeReasonId })}
      onChange={(id, visible) => setColumns((all) => hide(all, id, visible))}
      onReorder={(id, to) =>
        setColumns((all) => {
          const moving = all.find((column) => column.id === id);
          if (moving === undefined) return all;
          const rest = all.filter((column) => column.id !== id);
          return [...rest.slice(0, to), moving, ...rest.slice(to)];
        })
      }
    />
  );
}

/** The menu SCR-100's footer "Columns" opens: show and hide (reordering is the dialog's). */
function MenuHost({ writeReason }: { readonly writeReason?: string }): JSX.Element {
  const [columns, setColumns] = useState(COLUMNS);
  return (
    <ColumnPicker
      variant="menu"
      label="Columns"
      columns={columns}
      {...(writeReason === undefined ? {} : { writeReason })}
      onChange={(id, visible) => setColumns((all) => hide(all, id, visible))}
    />
  );
}

const meta: Meta = {
  title: "Molecules/ColumnPicker",
  component: ColumnPicker,
  decorators: [
    (Story) => (
      <div style={{ width: "20rem", fontFamily: FONT }}>
        <Story />
      </div>
    ),
  ],
  render: () => <ListHost />,
};
export default meta;
type Story = StoryObj;

/** The list: a box per column and "Move {column} up/down"; the movable range's ends are T2 (2b). */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("group", { name: "Columns" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Move Last up" })).toHaveAccessibleDescription(
      "Already first.",
    );
    await expect(canvas.getByRole("checkbox", { name: "Mark" })).not.toBeChecked();
  },
};

/** A move keeps focus on its button and says the new position once ("Funding % moved to position 4 of 11."). */
export const Reordering: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Move Funding % up" }));
    await expect(canvas.getByRole("button", { name: "Move Funding % up" })).toHaveFocus();
    await waitFor(() =>
      expect(canvasElement.querySelector('[role="status"]')).toHaveTextContent(
        "Funding % moved to position 4 of 11.",
      ),
    );
  },
};

/**
 * The locked column: checked, T2 with its reason shown under the row (2a), its lock leading the label, named "Not
 * available"; never hidden or moved (E08-D07 §4.3 Columns).
 */
export const Locked: Story = {
  play: async ({ canvasElement }) => {
    const symbol = within(canvasElement).getByRole("checkbox", { name: "Not available Symbol" });
    await expect(symbol).toBeChecked();
    await expect(symbol).toHaveAttribute("aria-disabled", "true");
    await expect(symbol).toHaveAccessibleDescription("The symbol column is always shown.");
    await expect(
      within(canvasElement).getByText("The symbol column is always shown."),
    ).toBeVisible();
  },
};

/**
 * Read-only (D13) with no host notice, rendering 2a (E09-D09 §2.2): the list shows the sentence once itself, before its
 * boxes; every box's lock leads its label, named "Not available", and every box and move button is T2, described by
 * that line.
 */
export const ReadOnly: Story = {
  render: () => <ListHost writeReason={READ_ONLY} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const boxes = canvas.getAllByRole("checkbox");
    await expect(boxes.every((box) => box.getAttribute("aria-disabled") === "true")).toBe(true);
    await expect(canvas.getByText(READ_ONLY)).toBeVisible();
    await expect(
      canvas.getByRole("checkbox", { name: "Not available Mark" }),
    ).toHaveAccessibleDescription(READ_ONLY);
  },
};

/**
 * Read-only (D13) as SCR-101 draws it: the host's one notice, which every gated box and move button points at
 * (E09-D09 §2.2 "one notice, many pointers"; `writeReasonId`).
 */
export const ReadOnlyNotice: Story = {
  render: () => (
    <>
      <p id="columns-read-only" style={{ margin: "0 0 0.5rem" }}>
        {READ_ONLY}
      </p>
      <ListHost writeReason={READ_ONLY} writeReasonId="columns-read-only" />
    </>
  ),
  play: async ({ canvasElement }) => {
    const mark = within(canvasElement).getByRole("checkbox", { name: "Not available Mark" });
    await expect(mark).toHaveAttribute("aria-describedby", "columns-read-only");
    await expect(within(canvasElement).getAllByText(READ_ONLY)).toHaveLength(1);
  },
};

/** Hover: the pointer on "Move Funding % up": CMP-016's echo names it after the hover delay (CMP-002, D10). */
export const Hover: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.hover(within(canvasElement).getByRole("button", { name: "Move Funding % up" }));
    await waitFor(() =>
      expect(document.querySelector('[data-cmp="CMP-016"]:not([hidden])')).toHaveTextContent(
        "Move Funding % up",
      ),
    );
  },
};

/** FocusVisible: Tab past the locked Symbol box (T2, still a Tab stop) to the Last box, with the focus ring. */
export const FocusVisible: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.tab();
    await expect(canvas.getByRole("checkbox", { name: "Not available Symbol" })).toHaveFocus();
    await userEvent.tab();
    await expect(canvas.getByRole("checkbox", { name: "Last" })).toHaveFocus();
  },
};

/** The menu: a Columns button opening the columns as checkable items (CMP-041 `menuitemcheckbox`). */
export const Menu: Story = {
  render: () => <MenuHost />,
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Columns" }));
    const menu = await within(document.body).findByRole("menu", { name: "Columns" });
    await expect(within(menu).getAllByRole("menuitemcheckbox")).toHaveLength(COLUMNS.length);
  },
};

/** The menu, read-only: its button is T2 with the notice's sentence and opens nothing. */
export const MenuReadOnly: Story = {
  render: () => <MenuHost writeReason={READ_ONLY} />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Columns" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  },
};
