import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { SegmentedControl, type SegmentedControlBaseProps } from "./SegmentedControl.js";

const REASON = "Owner only: your role can't change the margin mode.";
const OPTIONS = [
  { value: "market", label: "Market" },
  { value: "limit", label: "Limit" },
  { value: "stop", label: "Stop" },
] as const;
const ICON_OPTIONS = [
  { value: "asc", label: "Ascending", icon: "arrow-up" },
  { value: "desc", label: "Descending", icon: "arrow-down" },
] as const;
const SIX = [
  ...OPTIONS,
  { value: "a", label: "Post-only" },
  { value: "b", label: "Reduce-only" },
  { value: "c", label: "Iceberg" },
] as const;

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof SegmentedControl> = {
  title: "Atoms/SegmentedControl",
  component: SegmentedControl,
  args: { "aria-label": "Order type", options: OPTIONS, value: "market", onChange: fn() },
};
export default meta;
type Story = StoryObj<typeof SegmentedControl>;

const col = { display: "grid", gap: "var(--space-inset-lg)", justifyItems: "start" } as const;
const group = (name: string): JSX.Element => <span>{name}</span>;

/** A host that keeps the value, so the keyboard stories show the real round trip. */
type HostProps = SegmentedControlBaseProps & { readonly "aria-label": string };
function Controlled(props: HostProps): JSX.Element {
  const [value, setValue] = useState(props.value);
  return (
    <SegmentedControl
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

export const Small: Story = { args: { size: "sm" }, render: controlled };

export const IconOnly: Story = {
  args: { options: ICON_OPTIONS, value: "asc", iconOnly: true, "aria-label": "Sort order" },
  render: controlled,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("radio", { name: "Ascending" })).toBeChecked();
    await expect(canvas.queryByText("Ascending")).toBeNull();
  },
};

export const IconAndText: Story = {
  args: { options: ICON_OPTIONS, value: "asc", "aria-label": "Sort order" },
  render: controlled,
};

export const ManyOptions: Story = { args: { options: SIX }, render: controlled };

export const FullWidth: Story = {
  args: { fullWidth: true },
  render: controlled,
  decorators: [
    (Story) => (
      <div style={{ width: "20rem" }}>
        <Story />
      </div>
    ),
  ],
  play: async ({ canvasElement }) => {
    const radios = within(canvasElement).getAllByRole("radio");
    const [a, b] = radios.map((r) => r.getBoundingClientRect().width);
    await expect(Math.abs((a ?? 0) - (b ?? 1))).toBeLessThan(1);
  },
};

/** No selection: the first segment holds the tab stop. */
export const NoSelection: Story = {
  args: { value: undefined },
  render: controlled,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(within(canvasElement).getByRole("radio", { name: "Market" })).toHaveFocus();
  },
};

export const Disabled: Story = {
  args: { disabled: true },
  play: async ({ canvasElement, args }) => {
    const radios = within(canvasElement).getAllByRole("radio");
    await userEvent.tab();
    await expect(document.body).toHaveFocus();
    await userEvent.click(radios[1] as HTMLElement);
    await expect(args.onChange).not.toHaveBeenCalled();
    await expect(radios[0]).toHaveAttribute("aria-checked", "true");
  },
};

export const GatedGroup: Story = {
  args: { disabledReason: REASON },
  play: async ({ canvasElement, args }) => {
    const radios = within(canvasElement).getAllByRole("radio");
    await userEvent.tab();
    await expect(radios[0]).toHaveFocus();
    await expect(radios[0]).toHaveAccessibleDescription(REASON);
    await userEvent.keyboard("{ArrowRight}{ArrowRight}{End} ");
    await userEvent.click(radios[2] as HTMLElement);
    await expect(args.onChange).not.toHaveBeenCalled();
    await expect(radios[0]).toHaveAttribute("aria-checked", "true");
    await expect(radios[0]).toHaveFocus();
  },
};

/** Every drawn state side by side (spec matrix): sizes, content, option counts, disabled, gated. */
export const AllStates: Story = {
  render: (args) => (
    <div style={col}>
      {group("Medium, 3 options")}
      <Controlled {...(args as HostProps)} />
      {group("Small")}
      <Controlled {...(args as HostProps)} size="sm" />
      {group("Icon-only")}
      <Controlled
        {...(args as HostProps)}
        options={ICON_OPTIONS}
        value="asc"
        iconOnly
        aria-label="Sort order"
      />
      {group("Six options")}
      <Controlled {...(args as HostProps)} options={SIX} />
      {group("Disabled")}
      <SegmentedControl {...(args as HostProps)} disabled />
      {group("Disabled with a reason")}
      <SegmentedControl {...(args as HostProps)} disabledReason={REASON} />
    </div>
  ),
};

/** Gated fill and lock: the label stays text.primary on the dimmed fill; axe checks it per theme. */
const gatedMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: (args) => (
    <div style={col}>
      <SegmentedControl {...(args as HostProps)} disabledReason={REASON} />
      <SegmentedControl {...(args as HostProps)} disabledReason={REASON} value="limit" size="sm" />
    </div>
  ),
});
export const GatedContrastLight: Story = gatedMatrix("light");
export const GatedContrastHighContrast: Story = gatedMatrix("high-contrast");

export const FocusVisible: Story = {
  render: controlled,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(within(canvasElement).getByRole("radio", { name: "Market" })).toHaveFocus();
  },
};

export const Hover: Story = {
  render: controlled,
  play: async ({ canvasElement }) =>
    userEvent.hover(within(canvasElement).getByRole("radio", { name: "Limit" })),
};

export const KeyboardNavigation: Story = {
  render: controlled,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.tab();
    await userEvent.keyboard("{ArrowRight}");
    await expect(canvas.getByRole("radio", { name: "Limit" })).toHaveFocus();
    await expect(canvas.getByRole("radio", { name: "Limit" })).toBeChecked();
    await userEvent.keyboard("{End}{ArrowRight}");
    await expect(canvas.getByRole("radio", { name: "Market" })).toBeChecked();
    await userEvent.keyboard("{ArrowLeft}");
    await expect(canvas.getByRole("radio", { name: "Stop" })).toHaveFocus();
    await expect(args.onChange).toHaveBeenLastCalledWith("stop");
  },
};

export const ClickSegment: Story = {
  render: controlled,
  play: async ({ canvasElement }) => {
    const radio = within(canvasElement).getByRole("radio", { name: "Stop" });
    await userEvent.click(within(radio).getByText("Stop"));
    await expect(radio).toBeChecked();
    await expect(radio).toHaveFocus();
  },
};
