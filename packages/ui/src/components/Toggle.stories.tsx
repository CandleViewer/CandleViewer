import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { Toggle } from "./Toggle.js";

const REASON = "Owner only: your role can't use this action.";

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof Toggle> = {
  title: "Atoms/Toggle",
  component: Toggle,
  args: { label: "One-click trading", onChange: fn() },
};
export default meta;
type Story = StoryObj<typeof Toggle>;

const col = { display: "grid", gap: "var(--space-inset-sm)", justifyItems: "start" } as const;
const get = (canvas: HTMLElement, name = "One-click trading"): HTMLElement =>
  within(canvas).getByRole("switch", { name });

export const Default: Story = {};

export const Checked: Story = { args: { defaultChecked: true } };

export const LabelLeft: Story = { args: { labelPosition: "left" } };

export const LabelHidden: Story = {
  args: { labelPosition: "hidden" },
  play: async ({ canvasElement }) => {
    await expect(get(canvasElement)).toHaveAttribute("aria-label", "One-click trading");
  },
};

/** Critical (1-click-arm look, D02 D4 proposed): leading warning glyph, bold label, amber armed track. */
export const Critical: Story = {
  args: { critical: true },
  render: (args) => (
    <div style={col}>
      <Toggle {...args} />
      <Toggle {...args} defaultChecked />
    </div>
  ),
};

export const Disabled: Story = { args: { disabled: true } };

export const DisabledWithReason: Story = {
  args: { disabledReason: REASON, defaultChecked: true },
  play: async ({ canvasElement, args }) => {
    const toggle = get(canvasElement);
    await userEvent.tab();
    await expect(toggle).toHaveFocus();
    await expect(toggle).toHaveAccessibleDescription(REASON);
    await userEvent.keyboard("{Enter} ");
    await expect(args.onChange).not.toHaveBeenCalled();
    await expect(toggle).toHaveAttribute("aria-checked", "true");
  },
};

/** Checked x gated x critical grid. */
export const AllStates: Story = {
  render: (args) => (
    <div style={col}>
      {[false, true].map((checked) => (
        <div key={String(checked)} style={col}>
          <Toggle {...args} defaultChecked={checked} />
          <Toggle {...args} defaultChecked={checked} disabled />
          <Toggle {...args} defaultChecked={checked} disabledReason={REASON} />
          <Toggle {...args} defaultChecked={checked} critical />
          <Toggle {...args} defaultChecked={checked} critical disabled />
          <Toggle {...args} defaultChecked={checked} critical disabledReason={REASON} />
        </div>
      ))}
    </div>
  ),
};

/** A label wider than its box wraps; the track and the lock stay on the first line. */
export const LongLabel: Story = {
  args: {
    label: "Send every order to all selected accounts in the trade group without asking again",
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

/** Gated on and off, plus critical armed: axe checks the knob and label on the dimmed plate per theme. */
const gatedMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: (args) => (
    <div style={col}>
      <Toggle {...args} disabledReason={REASON} />
      <Toggle {...args} disabledReason={REASON} defaultChecked />
      <Toggle {...args} critical defaultChecked />
      <Toggle {...args} critical defaultChecked disabled />
      <Toggle {...args} critical defaultChecked disabledReason={REASON} />
      <Toggle {...args} defaultChecked />
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

/** Keyboard table: Tab focuses, Space and Enter each toggle, a label click toggles. */
export const KeyboardToggle: Story = {
  play: async ({ canvasElement, args }) => {
    const toggle = get(canvasElement);
    await userEvent.tab();
    await expect(toggle).toHaveFocus();
    await userEvent.keyboard(" ");
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    await userEvent.keyboard("{Enter}");
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await userEvent.click(within(canvasElement).getByText("One-click trading"));
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    await expect(args.onChange).toHaveBeenLastCalledWith(true);
    await expect(args.onChange).toHaveBeenCalledTimes(3);
  },
};
