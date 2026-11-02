import type { Meta, StoryObj } from "@storybook/react-vite";
import type { JSX, ReactNode } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { Icon } from "../icons/Icon.js";
import { CellNumberEditor } from "./CellNumberEditor.js";

/**
 * E29-D02 §7's specimen: the Sub-2 ETHUSDT entry's price, 2,500.00 → 2,495.00 on a 0.01 tick. The wire writes the
 * live value without trailing zeros ("2500"); the cell shows it at the tick's places.
 */
const PRICE = "Price, ETHUSDT Buy on Sub-2";
/** E29-D02 §7's accessible description of the Editing moment. */
const EDITING = "Editing the price. 2,500.00 stays live until you press Enter.";
/** `blotter.amend_in_flight` (PROPOSED, E29-D03): the edit while an amend is already in flight (E29-D02 §8.2). */
const IN_FLIGHT = "An amend is already in flight.";
/** `rbac.view_as` (E09-D09 §3.1) with board 17's fixture: the one notice every write points at (D02:435). */
const VIEW_AS = "Read-only while viewing as alex.";
const NOTICE_ID = "cv-cell-editor-story-notice";
/** E30-D02's `frozen` (E30-D06 `ticket.order.frozen`) with board 16's fixture: a quantity up under the kill switch. */
const FROZEN =
  "Trading frozen by the owner at 14:02 UTC — new orders off. Cancel and close still work.";
const QTY = "Qty, BTCUSDT Buy on Sub-1";

/** A quantity on the 0.001 lot as whole lots: board 16's "a quantity up", compared exactly (never a float). */
const lots = (qty: string): bigint => {
  const [whole = "0", fraction = ""] = qty.split(".");
  return BigInt(`${whole}${fraction.padEnd(3, "0")}`);
};

/** The grid cell the editor fills (E29-D02 §7: "the editor is the cell itself"). */
function Cell({ children }: { readonly children: ReactNode }): JSX.Element {
  return <div style={{ inlineSize: "8rem" }}>{children}</div>;
}

const meta: Meta<typeof CellNumberEditor> = {
  title: "Trading/CellNumberEditor",
  component: CellNumberEditor,
  args: {
    label: PRICE,
    value: "2500",
    step: "0.01",
    unit: "tick",
    onCommit: fn(),
    onEditingChange: fn(),
  },
  render: (args) => (
    <Cell>
      <CellNumberEditor {...args} />
    </Cell>
  ),
};
export default meta;
type Story = StoryObj<typeof CellNumberEditor>;

const valueOf = (canvas: HTMLElement, name = PRICE): HTMLElement =>
  within(canvas).getByRole("spinbutton", { name });

/** At rest: the live value as the cell's text, a read-only spin button, one Tab stop. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const cell = valueOf(canvasElement);
    await expect(cell).toHaveValue("2,500.00");
    await expect(cell).toHaveAttribute("readonly");
  },
};

export const FocusVisible: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(valueOf(canvasElement)).toHaveFocus();
  },
};

/** `Enter` opens the editor; the live value and the step hint hang in the note under it (D02 §7). */
export const Editing: Story = {
  args: { editingDescription: EDITING },
  play: async ({ canvasElement, args }) => {
    valueOf(canvasElement).focus();
    await userEvent.keyboard("{Enter}");
    const editor = valueOf(canvasElement);
    await waitFor(() => expect(editor).toHaveFocus());
    await expect(editor).toHaveValue("2500.00");
    await userEvent.clear(editor);
    await userEvent.type(editor, "2495.00");
    await expect(editor).toHaveAccessibleDescription(expect.stringContaining(EDITING));
    await expect(args.onCommit).not.toHaveBeenCalled();
  },
};

/** A value off the tick is refused with E30's words and never rounded; nothing is sent, and the ring stays. */
export const Invalid: Story = {
  args: { editingDescription: EDITING },
  play: async ({ canvasElement, args }) => {
    valueOf(canvasElement).focus();
    await userEvent.keyboard("{Enter}");
    const editor = valueOf(canvasElement);
    await userEvent.clear(editor);
    await userEvent.type(editor, "2495.003{Enter}");
    await expect(editor).toHaveAttribute("aria-invalid", "true");
    await expect(editor).toHaveValue("2495.003");
    await expect(
      within(canvasElement).getByText("Price must be a multiple of 0.01."),
    ).toBeVisible();
    await expect(args.onCommit).not.toHaveBeenCalled();
  },
};

/**
 * Disabled with a visible reason (T2, E09-D09 §2.2; E29-D04 §4.1): the value keeps its look, its name and its Tab
 * stop, with `aria-disabled` and the reason as its description, and no glyph among the numerals. `Enter` opens
 * nothing: it re-shows the reason 2a under the cell, the lock leading it.
 */
export const DisabledWithReason: Story = {
  args: { disabledReason: IN_FLIGHT },
  play: async ({ canvasElement, args }) => {
    await userEvent.tab();
    const cell = valueOf(canvasElement);
    await expect(cell).toHaveFocus();
    await expect(cell).toHaveValue("2,500.00");
    await expect(cell).toHaveAttribute("aria-disabled", "true");
    await expect(cell).not.toBeDisabled();
    await expect(cell).toHaveAccessibleDescription(IN_FLIGHT);
    await expect(within(canvasElement).queryByRole("img", { name: "Not available" })).toBeNull();
    await userEvent.keyboard("{Enter}");
    await expect(args.onEditingChange).not.toHaveBeenCalled();
    await expect(within(canvasElement).getByRole("img", { name: "Not available" })).toBeVisible();
    await expect(within(canvasElement).getByText(IN_FLIGHT)).toBeVisible();
  },
};

/**
 * One notice, many pointers (G-T2.5; board 17): the panel-header notice carries the reason once, and the cell points
 * at it with `disabledReasonId`, its value unchanged and no reason of its own. `Enter` is refused like any press on a
 * T2 control (G-T2.3): the reason is re-shown 2a under the cell, an `aria-hidden` copy, and the description stays the
 * notice alone.
 */
export const PointsAtNotice: Story = {
  args: { disabledReason: VIEW_AS, disabledReasonId: NOTICE_ID },
  render: (args) => (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-stack-md)" }}>
      <p
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--space-inset-xs)",
          margin: 0,
          color: "var(--color-text-secondary)",
        }}
      >
        <Icon name="lock" decorative={false} label="Not available" />
        <span id={NOTICE_ID}>{VIEW_AS}</span>
      </p>
      <Cell>
        <CellNumberEditor {...args} />
      </Cell>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const cell = valueOf(canvasElement);
    await expect(cell).toHaveValue("2,500.00");
    await expect(cell).toHaveAttribute("aria-describedby", NOTICE_ID);
    await expect(cell).toHaveAccessibleDescription(VIEW_AS);
    await expect(within(canvasElement).getAllByText(VIEW_AS)).toHaveLength(1);
    // The press opens nothing: the reason shows once more under this cell (the frame the visual run keeps)
    cell.focus();
    await userEvent.keyboard("{Enter}");
    await expect(within(canvasElement).getAllByText(VIEW_AS)).toHaveLength(2);
    const note = canvasElement.querySelector(".cv-cell-editor__note");
    await expect(note).toBeVisible();
    await expect(note).toHaveTextContent(VIEW_AS);
    await expect(note).toHaveAttribute("aria-hidden", "true"); // a re-show: the notice stays the description
    await expect(cell).toHaveAttribute("readonly");
    await expect(cell).toHaveAttribute("aria-describedby", NOTICE_ID);
    await expect(cell).toHaveAccessibleDescription(VIEW_AS);
  },
};

/**
 * T2 on the commit (board 16): a quantity cut passes the kill switch, so the editor opens, and `Enter` on a quantity
 * up sends nothing; the reason shows 2a under the editor, the lock leading it, with no `aria-invalid`. `Esc` restores.
 */
export const CommitGated: Story = {
  args: {
    label: QTY,
    value: "0.1",
    step: "0.001",
    unit: "lot",
    commitGate: (qty: string) => (lots(qty) > lots("0.1") ? FROZEN : undefined),
  },
  play: async ({ canvasElement, args }) => {
    valueOf(canvasElement, QTY).focus();
    await userEvent.keyboard("{F2}");
    const editor = valueOf(canvasElement, QTY);
    await userEvent.clear(editor);
    await userEvent.type(editor, "0.150{Enter}");
    await expect(editor).toHaveValue("0.150");
    await expect(editor).not.toHaveAttribute("aria-invalid");
    await expect(editor).toHaveAccessibleDescription(expect.stringContaining(FROZEN));
    await expect(within(canvasElement).getByRole("img", { name: "Not available" })).toBeVisible();
    await expect(args.onCommit).not.toHaveBeenCalled();
  },
};

/** Plain disabled, with no reason to give: native, out of the Tab order (no use on SCR-063, #912 BQ-9). */
export const Disabled: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    await expect(valueOf(canvasElement)).toBeDisabled();
  },
};

/** CMP-101's cell use: a quantity on a 0.001 lot; `Shift+↑` steps ten lots. */
export const Quantity: Story = {
  args: { label: QTY, value: "0.15", step: "0.001", unit: "lot" },
  play: async ({ canvasElement }) => {
    valueOf(canvasElement, QTY).focus();
    await userEvent.keyboard("{F2}");
    await userEvent.keyboard("{Shift>}{ArrowUp}{/Shift}");
    await expect(valueOf(canvasElement, QTY)).toHaveValue("0.160");
  },
};

const LONG = "Price, 10000SATSUSDT Buy on Long-label account for testing";

/** The longest specimen, open: a long fractional price and its hint; the digits widen the cell, the note wraps. */
export const LongText: Story = {
  args: {
    label: LONG,
    value: "0.0000123456",
    step: "0.0000000001",
    editingDescription: "Editing the price. 0.0000123456 stays live until you press Enter.",
  },
  play: async ({ canvasElement }) => {
    await expect(valueOf(canvasElement, LONG)).toHaveValue("0.0000123456");
    valueOf(canvasElement, LONG).focus();
    await userEvent.keyboard("{Enter}");
    await expect(valueOf(canvasElement, LONG)).not.toHaveAttribute("readonly");
    await expect(
      within(canvasElement).getByText("Step 0.0000000001 · ↑/↓ one tick · Shift ten"),
    ).toBeVisible();
  },
};

/** The well takes the comfortable control height: the density re-points `size.control.height` (D04H §B, DR-9). */
export const Comfortable: Story = {
  args: { density: "comfortable" },
};

/** At rest, open and gated with its reason re-shown, under the light and high-contrast themes; axe checks each. */
const themeMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
    valueOf(canvasElement, "Qty, SOLUSDT Buy on Main").focus();
    await userEvent.keyboard("{Enter}");
    await expect(within(canvasElement).getByText(IN_FLIGHT)).toBeVisible();
  },
  render: () => (
    <div style={{ display: "flex", flexDirection: "column", gap: "4rem", inlineSize: "8rem" }}>
      <CellNumberEditor label={PRICE} value="2500" step="0.01" unit="tick" onCommit={fn()} />
      <CellNumberEditor
        label="Price, BTCUSDT Buy on Sub-1"
        value="63950"
        step="0.1"
        unit="tick"
        editing
        editingDescription="Editing the price. 63,950.0 stays live until you press Enter."
        onCommit={fn()}
      />
      <CellNumberEditor
        label="Qty, SOLUSDT Buy on Main"
        value="20"
        step="0.1"
        unit="lot"
        disabledReason={IN_FLIGHT}
        onCommit={fn()}
      />
    </div>
  ),
});
export const ContrastLight: Story = themeMatrix("light");
export const ContrastHighContrast: Story = themeMatrix("high-contrast");
