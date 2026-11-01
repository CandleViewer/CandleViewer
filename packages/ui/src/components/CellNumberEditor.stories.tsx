import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
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

const meta: Meta<typeof CellNumberEditor> = {
  title: "Trading/CellNumberEditor",
  component: CellNumberEditor,
  args: {
    label: PRICE,
    value: "2500",
    step: "0.01",
    unit: "tick",
    editingDescription: EDITING,
    onCommit: fn(),
    onEditingChange: fn(),
  },
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

/** `Enter` opens the editor; the live value stays under it, and the typed value waits for `Enter` (D02 §7). */
export const Editing: Story = {
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

/** A value off the tick is refused with its reason and never rounded; nothing is sent. */
export const Invalid: Story = {
  play: async ({ canvasElement, args }) => {
    valueOf(canvasElement).focus();
    await userEvent.keyboard("{Enter}");
    const editor = valueOf(canvasElement);
    await userEvent.clear(editor);
    await userEvent.type(editor, "2495.003{Enter}");
    await expect(editor).toHaveAttribute("aria-invalid", "true");
    await expect(editor).toHaveValue("2495.003");
    await expect(within(canvasElement).getByText("Enter a multiple of 0.01.")).toBeVisible();
    await expect(args.onCommit).not.toHaveBeenCalled();
  },
};

/**
 * Disabled with a visible reason (T2, E09-D09 §2.2), rendering 2b: the value keeps its name and its Tab stop with
 * `aria-disabled`, the lock leads it, and the reason is its description, echoed on focus. `Enter` opens nothing.
 */
export const DisabledWithReason: Story = {
  args: { disabledReason: IN_FLIGHT },
  play: async ({ canvasElement, args }) => {
    await userEvent.tab();
    const cell = valueOf(canvasElement);
    await expect(cell).toHaveFocus();
    await expect(cell).toHaveAttribute("aria-disabled", "true");
    await expect(cell).not.toBeDisabled();
    await expect(cell).toHaveAccessibleDescription(IN_FLIGHT);
    await expect(within(canvasElement).getByRole("img", { name: "Not available" })).toBeVisible();
    await userEvent.keyboard("{Enter}");
    await expect(args.onEditingChange).not.toHaveBeenCalled();
  },
};

/** Plain disabled, with no reason to give: native, out of the Tab order. */
export const Disabled: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    await expect(valueOf(canvasElement)).toBeDisabled();
  },
};

/** CMP-101's cell use: a quantity on a 0.001 lot; `Shift+↑` steps ten lots. */
export const Quantity: Story = {
  args: { label: "Qty, BTCUSDT Buy on Sub-1", value: "0.15", step: "0.001", unit: "lot" },
  play: async ({ canvasElement }) => {
    const name = "Qty, BTCUSDT Buy on Sub-1";
    valueOf(canvasElement, name).focus();
    await userEvent.keyboard("{F2}");
    await userEvent.keyboard("{Shift>}{ArrowUp}{/Shift}");
    await expect(valueOf(canvasElement, name)).toHaveValue("0.160");
  },
};

/** The longest specimen: a nine-character base and a long fractional price; the digits widen the cell, never cut. */
export const LongText: Story = {
  args: {
    label: "Price, 10000SATSUSDT Buy on Long-label account for testing",
    value: "0.0000123456",
    step: "0.0000000001",
  },
  play: async ({ canvasElement }) => {
    const cell = valueOf(
      canvasElement,
      "Price, 10000SATSUSDT Buy on Long-label account for testing",
    );
    await expect(cell).toHaveValue("0.0000123456");
  },
};

export const Comfortable: Story = {
  args: { density: "comfortable" },
};

/** At rest, open and gated under the light and high-contrast themes; axe checks each theme. */
const themeMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: () => (
    <div style={{ display: "flex", gap: "var(--space-inset-md)", alignItems: "flex-start" }}>
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
