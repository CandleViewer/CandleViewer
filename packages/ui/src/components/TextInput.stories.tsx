import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { Icon } from "../icons/Icon.js";
import { TextInput } from "./TextInput.js";

const REASON = "Owner only: your role can't edit this field.";
const ERROR = "Enter your username.";

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof TextInput> = {
  title: "Atoms/TextInput",
  component: TextInput,
  args: { "aria-label": "Username", defaultValue: "trader_01", onChange: fn() },
};
export default meta;
type Story = StoryObj<typeof TextInput>;

const col = { display: "grid", gap: "var(--space-inset-md)", width: "16rem" } as const;
const input = (canvasElement: HTMLElement): HTMLInputElement =>
  within(canvasElement).getByRole("textbox") as HTMLInputElement;

export const Default: Story = {};

export const Empty: Story = {
  args: { defaultValue: "", placeholder: "e.g. trader_01" },
};

export const WithPrefixSuffix: Story = {
  args: { "aria-label": "Search", defaultValue: "", prefix: <Icon name="info" />, suffix: "USDT" },
  play: async ({ canvasElement }) => {
    await expect(input(canvasElement)).toHaveAccessibleDescription(/^\s*USDT$/);
  },
};

export const Hover: Story = {
  play: async ({ canvasElement }) => userEvent.hover(input(canvasElement)),
};

/** The ring shows on a pointer click as well as on Tab. */
export const FocusVisible: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(input(canvasElement)).toHaveFocus();
  },
};

export const Invalid: Story = {
  args: { invalid: true, errorMessage: ERROR },
  play: async ({ canvasElement }) => {
    const field = input(canvasElement);
    await expect(field).toHaveAttribute("aria-invalid", "true");
    await expect(field).toHaveAccessibleDescription(ERROR);
  },
};

export const Disabled: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(input(canvasElement)).not.toHaveFocus();
  },
};

/** T2: focusable and read-only, the lock leads the value, keys change nothing and the reason is announced once. */
export const DisabledWithReason: Story = {
  args: { disabledReason: REASON },
  play: async ({ canvasElement, args }) => {
    const field = input(canvasElement);
    await userEvent.tab();
    await expect(field).toHaveFocus();
    await expect(field).toHaveAttribute("aria-disabled", "true");
    await expect(field).toHaveAccessibleDescription(REASON);
    await userEvent.keyboard("abc{Enter}");
    await expect(field).toHaveValue("trader_01");
    await expect(args.onChange).not.toHaveBeenCalled();
    await expect(within(canvasElement).getByRole("status")).toHaveTextContent(REASON);
  },
};

export const ReadOnly: Story = {
  args: { readOnly: true },
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(input(canvasElement)).toHaveFocus();
    await expect(input(canvasElement)).toHaveAttribute("readonly");
  },
};

/** A value wider than the well scrolls inside it and never wraps. */
export const LongValue: Story = {
  args: { defaultValue: "a_very_long_account_label_that_does_not_fit_in_the_well_at_all" },
  decorators: [
    (Story) => (
      <div style={{ width: "10rem" }}>
        <Story />
      </div>
    ),
  ],
  play: async ({ canvasElement }) => {
    const field = input(canvasElement);
    await expect(field.scrollWidth).toBeGreaterThan(field.clientWidth);
  },
};

export const AllStates: Story = {
  render: (args) => (
    <div style={col}>
      <TextInput {...args} aria-label="Default" />
      <TextInput {...args} aria-label="Empty" defaultValue="" placeholder="e.g. trader_01" />
      <TextInput
        {...args}
        aria-label="Prefix and suffix"
        prefix={<Icon name="info" />}
        suffix="USDT"
      />
      <TextInput {...args} aria-label="Invalid" invalid errorMessage={ERROR} />
      <TextInput {...args} aria-label="Disabled" disabled />
      <TextInput {...args} aria-label="Gated" disabledReason={REASON} />
      <TextInput {...args} aria-label="Gated with a prefix" prefix="$" disabledReason={REASON} />
      <TextInput {...args} aria-label="Read only" readOnly />
      <TextInput
        {...args}
        aria-label="Gated and invalid"
        invalid
        errorMessage={ERROR}
        disabledReason={REASON}
      />
      <TextInput
        {...args}
        aria-label="Invalid and read only"
        invalid
        errorMessage={ERROR}
        readOnly
      />
      <TextInput
        {...args}
        aria-label="Invalid and disabled"
        invalid
        errorMessage={ERROR}
        disabled
      />
    </div>
  ),
};

/**
 * Gated, invalid and read-only under light and high contrast. axe checks the danger cues, the read-only value and the
 * placeholder per theme; it skips `aria-disabled` nodes, so the gated value's contrast (5.62, 5.92 and 11.21:1,
 * D02F a11y audit row 88) is not asserted here.
 */
const themed = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: (args) => (
    <div style={col}>
      <TextInput {...args} aria-label="Gated" disabledReason={REASON} />
      <TextInput {...args} aria-label="Invalid" invalid errorMessage={ERROR} />
      <TextInput {...args} aria-label="Read only" readOnly />
      <TextInput {...args} aria-label="Search" defaultValue="" placeholder="Search" suffix="USDT" />
    </div>
  ),
});
export const GatedContrastLight: Story = themed("light");
export const GatedContrastHighContrast: Story = themed("high-contrast");
