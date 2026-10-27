import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { RadioGroup, type RadioGroupBaseProps } from "./RadioGroup.js";

const REASON = "Owner only: your role can't change the sizing rule.";
const LOCK_REASON = "Unavailable for LIVE market orders.";
const OPTIONS = [
  { value: "fixed", label: "Fixed size" },
  { value: "percent", label: "Percent of equity" },
  { value: "risk", label: "Risk-based" },
] as const;

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof RadioGroup> = {
  title: "Atoms/RadioGroup",
  component: RadioGroup,
  args: {
    "aria-label": "Sizing rule",
    options: OPTIONS,
    value: "fixed",
    onChange: fn(),
  },
};
export default meta;
type Story = StoryObj<typeof RadioGroup>;

const col = { display: "grid", gap: "var(--space-inset-lg)", justifyItems: "start" } as const;
const group = (name: string): JSX.Element => <span>{name}</span>;

/** A host that keeps the value, so the keyboard stories show the real round trip. */
type HostProps = RadioGroupBaseProps & { readonly "aria-label": string };
function Controlled(props: HostProps): JSX.Element {
  const [value, setValue] = useState(props.value);
  return (
    <RadioGroup
      {...props}
      value={value}
      onChange={(next) => {
        setValue(next);
        props.onChange?.(next);
      }}
    />
  );
}
const controlled: Story["render"] = (args) => <Controlled {...(args as HostProps)} />;

export const Default: Story = { render: controlled };

export const Horizontal: Story = { args: { orientation: "horizontal" }, render: controlled };

/** No selection: the first enabled radio holds the tab stop. */
export const NoSelection: Story = {
  args: { value: undefined },
  render: controlled,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(within(canvasElement).getByRole("radio", { name: "Fixed size" })).toHaveFocus();
  },
};

export const Disabled: Story = { args: { disabled: true } };

export const GatedGroup: Story = {
  args: { disabledReason: REASON },
  play: async ({ canvasElement, args }) => {
    const radios = within(canvasElement).getAllByRole("radio");
    await userEvent.tab();
    await expect(radios[0]).toHaveFocus();
    await expect(radios[0]).toHaveAccessibleDescription(REASON);
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{End} ");
    await userEvent.click(radios[2] as HTMLElement);
    await expect(args.onChange).not.toHaveBeenCalled();
    await expect(radios[0]).toHaveAttribute("aria-checked", "true");
    await expect(radios[2]).toHaveAttribute("aria-checked", "false");
  },
};

const LOCKED = [
  OPTIONS[0],
  OPTIONS[1],
  { value: "market", label: "Skip confirmation", disabledReason: LOCK_REASON },
  { value: "legacy", label: "Legacy sizing", disabled: true },
] as const;

/** An option-level reason: arrow-reachable, never checked; a plain-disabled option is skipped. */
export const OptionLocked: Story = {
  args: { options: LOCKED },
  render: controlled,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.tab();
    await userEvent.keyboard("{ArrowDown}{ArrowDown}");
    const locked = canvas.getByRole("radio", { name: "Skip confirmation" });
    await expect(locked).toHaveFocus();
    await expect(locked).toHaveAttribute("aria-checked", "false");
    await expect(locked).toHaveAccessibleDescription(LOCK_REASON);
    await expect(canvas.getByRole("radio", { name: "Percent of equity" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await userEvent.keyboard("{ArrowDown}");
    await expect(canvas.getByRole("radio", { name: "Fixed size" })).toHaveFocus();
  },
};

const LONG =
  "Size every leg from the account equity of the trade group, after the exchange minimum is applied";
export const LongLabel: Story = {
  args: { options: [{ value: "a", label: LONG }, OPTIONS[1]], value: "a" },
  decorators: [
    (Story) => (
      <div style={{ width: "14rem" }}>
        <Story />
      </div>
    ),
  ],
  play: async ({ canvasElement }) => {
    const row = within(canvasElement).getByRole("radio", { name: LONG });
    await expect(row.scrollWidth).toBeLessThanOrEqual(row.clientWidth);
    await expect(row.clientHeight).toBeGreaterThan(40);
  },
};

/** Every drawn state side by side (spec matrix): default, horizontal, plain disabled, gated group, option lock. */
export const AllStates: Story = {
  render: (args) => (
    <div style={col}>
      {group("Default")}
      <Controlled {...(args as HostProps)} />
      {group("Horizontal")}
      <Controlled {...(args as HostProps)} orientation="horizontal" />
      {group("Disabled")}
      <RadioGroup {...(args as HostProps)} disabled />
      {group("Disabled with a reason")}
      <RadioGroup {...(args as HostProps)} disabledReason={REASON} />
      {group("Option with a reason")}
      <Controlled {...(args as HostProps)} options={LOCKED} />
    </div>
  ),
};

/** Gated plate and lock: the label stays text.primary on the dimmed ring; axe checks it per theme. */
const gatedMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: (args) => (
    <div style={col}>
      <RadioGroup {...(args as HostProps)} disabledReason={REASON} />
      <RadioGroup {...(args as HostProps)} options={LOCKED} />
    </div>
  ),
});
export const GatedContrastLight: Story = gatedMatrix("light");
export const GatedContrastHighContrast: Story = gatedMatrix("high-contrast");

export const FocusVisible: Story = {
  render: controlled,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(within(canvasElement).getByRole("radio", { name: "Fixed size" })).toHaveFocus();
  },
};

export const Hover: Story = {
  render: controlled,
  play: async ({ canvasElement }) =>
    userEvent.hover(within(canvasElement).getByRole("radio", { name: "Percent of equity" })),
};

export const KeyboardNavigation: Story = {
  render: controlled,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.tab();
    await userEvent.keyboard("{ArrowDown}");
    await expect(canvas.getByRole("radio", { name: "Percent of equity" })).toHaveFocus();
    await expect(canvas.getByRole("radio", { name: "Percent of equity" })).toBeChecked();
    await userEvent.keyboard("{End}{ArrowRight}");
    await expect(canvas.getByRole("radio", { name: "Fixed size" })).toBeChecked();
    await userEvent.keyboard("{ArrowUp}");
    await expect(canvas.getByRole("radio", { name: "Risk-based" })).toHaveFocus();
    await expect(args.onChange).toHaveBeenLastCalledWith("risk");
  },
};

export const ClickWholeRow: Story = {
  render: controlled,
  play: async ({ canvasElement }) => {
    const row = within(canvasElement).getByRole("radio", { name: "Risk-based" });
    await userEvent.click(within(row).getByText("Risk-based"));
    await expect(row).toBeChecked();
  },
};
