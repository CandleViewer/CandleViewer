import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { Checkbox } from "./Checkbox.js";

const REASON = "Owner only: your role can't use this action.";

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof Checkbox> = {
  title: "Atoms/Checkbox",
  component: Checkbox,
  args: { label: "Apply to every selected account", onChange: fn() },
};
export default meta;
type Story = StoryObj<typeof Checkbox>;

const col = { display: "grid", gap: "var(--space-inset-sm)", justifyItems: "start" } as const;
const get = (canvas: HTMLElement): HTMLInputElement =>
  within(canvas).getByRole("checkbox", { name: "Apply to every selected account" });

export const Default: Story = {};

export const Checked: Story = { args: { defaultChecked: true } };

export const Indeterminate: Story = {
  args: { indeterminate: true },
  play: async ({ canvasElement, args }) => {
    // The DOM property carries the mixed state (no aria-checked); the next activation emits true.
    const box = get(canvasElement);
    await expect(box).toBePartiallyChecked();
    await userEvent.click(box);
    await expect(args.onChange).toHaveBeenCalledWith(true);
    await expect(box.indeterminate).toBe(true);
  },
};

export const Disabled: Story = { args: { disabled: true } };

export const DisabledWithReason: Story = {
  args: { disabledReason: REASON, defaultChecked: true },
  play: async ({ canvasElement, args }) => {
    const box = get(canvasElement);
    await userEvent.tab();
    await expect(box).toHaveFocus();
    await expect(box).toHaveAccessibleDescription(REASON);
    await userEvent.keyboard(" ");
    await userEvent.click(box);
    await expect(args.onChange).not.toHaveBeenCalled();
    await expect(box.checked).toBe(true);
  },
};

/** Value x state grid (hover, focus-visible and the keyboard are the play stories). */
export const AllStates: Story = {
  render: (args) => (
    <div style={col}>
      {[{}, { defaultChecked: true }, { indeterminate: true }].map((value, i) => (
        <div key={i} style={col}>
          <Checkbox {...args} {...value} />
          <Checkbox {...args} {...value} disabled />
          <Checkbox {...args} {...value} disabledReason={REASON} />
        </div>
      ))}
    </div>
  ),
};

/** A label wider than its box wraps; the box and the lock stay on the first line. */
export const LongLabel: Story = {
  args: {
    label:
      "Apply this change to every selected account in the trade group, including paper accounts",
    disabledReason: REASON,
  },
  decorators: [
    (Story) => (
      <div style={{ width: "14rem" }}>
        <Story />
      </div>
    ),
  ],
};

/** Gated checked and mixed: the glyph is text.primary on the dimmed plate; axe checks it per theme. */
const gatedMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: (args) => (
    <div style={col}>
      <Checkbox {...args} disabledReason={REASON} defaultChecked />
      <Checkbox {...args} disabledReason={REASON} indeterminate />
      <Checkbox {...args} defaultChecked />
      <Checkbox {...args} />
    </div>
  ),
});
export const GatedContrastLight: Story = gatedMatrix("light");
export const GatedContrastHighContrast: Story = gatedMatrix("high-contrast");

export const FocusVisible: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(get(canvasElement)).toHaveFocus();
  },
};

export const Hover: Story = {
  play: async ({ canvasElement }) => userEvent.hover(get(canvasElement)),
};

/** Keyboard table: Space toggles, Enter does nothing, a label click toggles. */
export const KeyboardToggle: Story = {
  play: async ({ canvasElement, args }) => {
    const box = get(canvasElement);
    await userEvent.tab();
    await expect(box).toHaveFocus();
    await userEvent.keyboard(" ");
    await expect(box.checked).toBe(true);
    await userEvent.keyboard("{Enter}");
    await expect(box.checked).toBe(true);
    await userEvent.click(within(canvasElement).getByText("Apply to every selected account"));
    await expect(box.checked).toBe(false);
    await expect(args.onChange).toHaveBeenCalledTimes(2);
  },
};
