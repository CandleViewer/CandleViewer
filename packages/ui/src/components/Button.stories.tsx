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
/** A host's 2a caption: the reason under its control, text.secondary in the caption type (E09-D09 §2.2). */
const caption = {
  color: "var(--color-text-secondary)",
  font: "var(--type-ui-caption-font-weight) var(--type-ui-caption-font-size) / var(--type-ui-caption-line-height) var(--type-ui-caption-font-family)",
} as const;

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

/** Buy and sell: the word and the arrow lead in every state, so the side is never colour alone (05 4.1). */
export const BuySellPair: Story = {
  render: (args) => (
    <div style={col}>
      <div style={row}>
        <Button {...args} variant="buy">
          Buy / Long
        </Button>
        <Button {...args} variant="sell">
          Sell / Short
        </Button>
      </div>
      <div style={row}>
        <Button {...args} variant="buy" loading>
          Buy / Long
        </Button>
        <Button {...args} variant="sell" loading iconRight="chevron-right">
          Sell / Short
        </Button>
      </div>
      <div style={row}>
        <Button {...args} variant="buy" disabled>
          Buy / Long
        </Button>
        <Button {...args} variant="sell" disabledReason={REASON}>
          Sell / Short
        </Button>
      </div>
    </div>
  ),
  play: async ({ canvasElement }) => {
    for (const button of within(canvasElement).getAllByRole("button"))
      await expect(button.querySelector(".cv-button__icon svg")).not.toBeNull();
  },
};

export const WithIcons: Story = {
  args: { iconLeft: "chevron-down", iconRight: "chevron-right" },
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
    // The CMP-016 reason echo: shown on keyboard focus, aria-hidden, Esc hides it and focus stays.
    const echo = document.body.querySelector<HTMLElement>(".cv-tooltip");
    await expect(echo).not.toBeNull();
    await waitFor(() => expect(echo?.hidden).toBe(false));
    await expect(echo).toHaveTextContent(REASON);
    await expect(echo).toHaveAttribute("aria-hidden", "true");
    await userEvent.keyboard("{Escape}");
    await expect(echo?.hidden).toBe(true);
    await expect(button).toHaveFocus();
  },
};

/**
 * Disabled with the reason shown by the host (E09-D09 §2.2 rendering 2a, `disabledReasonId`): a caption under the
 * button, its one description; the lock leads the label, named "Not available"; no echo of its own.
 */
export const DisabledWithReasonInline: Story = {
  args: { disabledReason: REASON, disabledReasonId: "button-reason" },
  render: (args) => (
    <div style={{ ...col, gap: "var(--space-stack-xs)" }}>
      <Button {...args} />
      <span id="button-reason" style={caption}>
        {REASON}
      </span>
    </div>
  ),
  play: async ({ canvasElement, args }) => {
    const button = within(canvasElement).getByRole("button", { name: "Not available Save" });
    await userEvent.tab();
    await expect(button).toHaveFocus();
    await expect(button).toHaveAccessibleDescription(REASON);
    await userEvent.keyboard("{Enter}");
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

/** Gated primary, danger, buy and sell: the label is text.primary on the dimmed plate; axe checks it per theme. */
const gatedMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: (args) => (
    <div style={row}>
      {(["primary", "danger", "buy", "sell"] as const).map((variant) => (
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
