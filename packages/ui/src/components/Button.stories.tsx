import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";
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
