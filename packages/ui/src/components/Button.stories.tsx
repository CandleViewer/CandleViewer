import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { Button } from "./Button.js";

const VARIANTS = ["primary", "secondary", "ghost", "danger"] as const;
const SIZES = ["sm", "md", "lg"] as const;
const REASON = "Owner only: your role can't use this action.";

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof Button> = {
  title: "Atoms/Button",
  component: Button,
  args: { children: "Save", onClick: fn() },
};
export default meta;
type Story = StoryObj<typeof Button>;

const row = { display: "flex", gap: "var(--space-inset-sm)", alignItems: "center" } as const;
const col = { display: "grid", gap: "var(--space-inset-sm)", justifyItems: "start" } as const;

export const Default: Story = {};

/** Variant x state grid (axis values of D02 CMP-001; hover/focus/active are the play stories below). */
export const AllVariants: Story = {
  render: (args) => (
    <div style={col}>
      {VARIANTS.map((variant) => (
        <div key={variant} style={row}>
          <Button {...args} variant={variant} />
          <Button {...args} variant={variant} loading />
          <Button {...args} variant={variant} disabled />
          <Button {...args} variant={variant} disabledReason={REASON} />
        </div>
      ))}
    </div>
  ),
};

export const AllSizes: Story = {
  render: (args) => (
    <div style={row}>
      {SIZES.map((size) => (
        <Button key={size} {...args} size={size} />
      ))}
    </div>
  ),
};

export const Loading: Story = {
  args: { loading: true },
  play: async ({ canvasElement, args }) => {
    const button = within(canvasElement).getByRole("button", { name: "Save" });
    await expect(button).toHaveAttribute("aria-busy", "true");
    await userEvent.click(button);
    await expect(args.onClick).not.toHaveBeenCalled();
  },
};

export const Disabled: Story = { args: { disabled: true } };

export const DisabledWithReason: Story = {
  args: { disabledReason: REASON },
  play: async ({ canvasElement, args }) => {
    const button = within(canvasElement).getByRole("button", { name: "Save" });
    await userEvent.tab();
    await expect(button).toHaveFocus();
    await expect(button).toHaveAccessibleDescription(REASON);
    await userEvent.keyboard("{Enter} ");
    await expect(args.onClick).not.toHaveBeenCalled();
  },
};

export const FullWidth: Story = { args: { fullWidth: true } };

/** A label wider than its box truncates with an ellipsis; the accessible name stays the full text. */
const LONG_LABEL = "Submit the order to every selected account in the trade group now";
export const LongLabel: Story = {
  args: { children: LONG_LABEL, fullWidth: true },
  decorators: [
    (Story) => (
      <div style={{ width: "10rem" }}>
        <Story />
      </div>
    ),
  ],
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: LONG_LABEL });
    const label = button.querySelector<HTMLElement>(".cv-button__label");
    await expect(label?.scrollWidth).toBeGreaterThan(label?.clientWidth ?? 0);
    await expect(button.scrollWidth).toBeLessThanOrEqual(button.clientWidth);
  },
};

/** Gated primary and danger: the label is text.primary on the dimmed plate; axe checks it per theme. */
const gatedMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: (args) => (
    <div style={row}>
      {(["primary", "danger"] as const).map((variant) => (
        <Button key={variant} {...args} variant={variant} disabledReason={REASON} />
      ))}
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
