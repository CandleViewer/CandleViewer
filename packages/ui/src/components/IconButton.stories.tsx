import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { IconButton, type IconButtonProps } from "./IconButton.js";

const VARIANTS = ["primary", "secondary", "ghost", "danger"] as const;
const SIZES = ["sm", "md", "lg"] as const;
const REASON = "Owner only: your role can't use this action.";

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof IconButton> = {
  title: "Atoms/IconButton",
  component: IconButton,
  args: { icon: "chevron-down", label: "Panel settings", onClick: fn() },
};
export default meta;
type Story = StoryObj<typeof IconButton>;

/** The props every cell shares; variant and pressed are set per cell (pressed is secondary and ghost only).
 *  It intentionally does not forward size, density or disabled: each cell fixes those itself. */
const shared = ({
  icon,
  label,
  onClick,
}: IconButtonProps): Pick<IconButtonProps, "icon" | "label" | "onClick"> => ({
  icon,
  label,
  onClick,
});

const row = { display: "flex", gap: "var(--space-inset-sm)", alignItems: "center" } as const;
const col = { display: "grid", gap: "var(--space-inset-sm)", justifyItems: "start" } as const;

export const Default: Story = {};

/** Variant x state grid (axis values of D02 CMP-002; hover, focus and active are the play stories below). */
export const AllVariants: Story = {
  render: (args) => (
    <div style={col}>
      {VARIANTS.map((variant) => (
        <div key={variant} style={row}>
          <IconButton {...shared(args)} variant={variant} />
          <IconButton {...shared(args)} variant={variant} disabled />
          <IconButton {...shared(args)} variant={variant} disabledReason={REASON} />
        </div>
      ))}
    </div>
  ),
};

export const AllSizes: Story = {
  render: (args) => (
    <div style={row}>
      {SIZES.map((size) => (
        <IconButton key={size} {...args} size={size} label={`Settings ${size}`} />
      ))}
    </div>
  ),
};

/** Toggle mode on secondary and ghost: pressed flips `aria-pressed`, the name never changes. */
export const Toggle: Story = {
  args: { pressed: false },
  render: (args) => (
    <div style={row}>
      <IconButton {...shared(args)} pressed />
      <IconButton {...shared(args)} variant="ghost" pressed />
      <IconButton {...shared(args)} variant="ghost" pressed={false} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const buttons = within(canvasElement).getAllByRole("button", { name: "Panel settings" });
    await expect(buttons[0]).toHaveAttribute("aria-pressed", "true");
    await expect(buttons[2]).toHaveAttribute("aria-pressed", "false");
  },
};

export const PressedGated: Story = {
  args: { pressed: true, disabledReason: REASON },
};

export const PressedDisabled: Story = { args: { pressed: true, disabled: true } };

export const Disabled: Story = { args: { disabled: true } };

export const DisabledWithReason: Story = {
  args: { disabledReason: REASON },
  play: async ({ canvasElement, args }) => {
    const button = within(canvasElement).getByRole("button", { name: "Panel settings" });
    await userEvent.tab();
    await expect(button).toHaveFocus();
    await expect(button).toHaveAccessibleDescription(REASON);
    await userEvent.keyboard("{Enter} ");
    await expect(args.onClick).not.toHaveBeenCalled();
  },
};

/** The box is the density-owned control height square, whatever the glyph size. */
export const HitTarget: Story = {
  render: (args) => (
    <div style={row}>
      {SIZES.map((size) => (
        <IconButton key={size} {...args} size={size} label={`Target ${size}`} />
      ))}
    </div>
  ),
  play: async ({ canvasElement }) => {
    for (const button of within(canvasElement).getAllByRole("button")) {
      const { width, height } = button.getBoundingClientRect();
      await expect(width).toBeGreaterThanOrEqual(24);
      await expect(width).toBe(height);
    }
  },
};

/** Gated and pressed buttons under the light and high-contrast themes; axe checks each theme. */
const gatedMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: (args) => (
    <div style={row}>
      {VARIANTS.map((variant) => (
        <IconButton key={variant} {...shared(args)} variant={variant} disabledReason={REASON} />
      ))}
      <IconButton {...shared(args)} pressed />
      <IconButton {...shared(args)} variant="ghost" pressed />
    </div>
  ),
});
export const GatedContrastLight: Story = gatedMatrix("light");
export const GatedContrastHighContrast: Story = gatedMatrix("high-contrast");

export const FocusVisible: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(within(canvasElement).getByRole("button")).toHaveFocus();
  },
};

/** Pressed and focused: the 2px selected outline and the focus ring are near-identical (A7), so check both read. */
export const PressedFocusVisible: Story = {
  args: { pressed: true },
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    const button = within(canvasElement).getByRole("button");
    await expect(button).toHaveFocus();
    await expect(button).toHaveAttribute("aria-pressed", "true");
  },
};

export const Hover: Story = {
  play: async ({ canvasElement }) => userEvent.hover(within(canvasElement).getByRole("button")),
};

export const Active: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.pointer({
      keys: "[MouseLeft>]",
      target: within(canvasElement).getByRole("button"),
    });
  },
};

export const KeyboardActivation: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.tab();
    await expect(within(canvasElement).getByRole("button")).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    await expect(args.onClick).toHaveBeenCalledTimes(2);
  },
};
