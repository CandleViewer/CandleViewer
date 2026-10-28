import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { Tabs, type TabItem, type TabsBaseProps } from "./Tabs.js";

const REASON = "Your role can't view algos.";
const BLOTTER: readonly TabItem[] = [
  { id: "positions", label: "Positions" },
  { id: "working", label: "Working orders" },
  { id: "fills", label: "Fills" },
  { id: "groups", label: "Trade groups" },
  { id: "algos", label: "Algos" },
];
const GATED: readonly TabItem[] = BLOTTER.map((tab) =>
  tab.id === "algos" ? { ...tab, disabledReason: REASON } : tab,
);
const ICONS: readonly TabItem[] = [
  { id: "positions", label: "Positions", icon: "chevron-right" },
  { id: "search", label: "Search", icon: "search" },
  { id: "info", label: "Details", icon: "info" },
];
const ORDER_TYPES: readonly TabItem[] = [
  { id: "market", label: "Market" },
  { id: "limit", label: "Limit" },
  { id: "stop", label: "Stop" },
];
const SETTINGS: readonly TabItem[] = [
  { id: "general", label: "General" },
  { id: "appearance", label: "Appearance" },
  { id: "keyboard", label: "Keyboard shortcuts and command palette" },
  { id: "accounts", label: "Accounts" },
];

/** A panel with nothing focusable: it takes tabindex="0" itself (J10). */
const textPanel = (id: string): JSX.Element => <p>Content of the {id} section.</p>;

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof Tabs> = {
  title: "Molecules/Tabs",
  component: Tabs,
  args: {
    "aria-label": "Blotter",
    tabs: BLOTTER,
    value: "positions",
    onChange: fn(),
    renderPanel: textPanel,
  },
};
export default meta;
type Story = StoryObj<typeof Tabs>;

/** A host that keeps the value, so the keyboard stories show the real round trip. */
type HostProps = TabsBaseProps & { readonly "aria-label": string };
function Controlled(props: HostProps): JSX.Element {
  const [value, setValue] = useState(props.value);
  return (
    <Tabs
      {...props}
      value={value}
      onChange={(next) => {
        setValue(next);
        props.onChange(next);
      }}
    />
  );
}
const controlled: Story["render"] = (args) => <Controlled {...(args as HostProps)} />;

export const Default: Story = {
  render: controlled,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("tablist", { name: "Blotter" })).toBeVisible();
    await expect(canvas.getByRole("tab", { name: "Positions" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(canvas.getByRole("tabpanel", { name: "Positions" })).toHaveAttribute(
      "tabindex",
      "0",
    );
  },
};

export const Hover: Story = {
  render: controlled,
  play: async ({ canvasElement }) =>
    userEvent.hover(within(canvasElement).getByRole("tab", { name: "Fills" })),
};

export const FocusVisible: Story = {
  render: controlled,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(within(canvasElement).getByRole("tab", { name: "Positions" })).toHaveFocus();
  },
};

export const Selected: Story = { args: { value: "fills" }, render: controlled };

export const Vertical: Story = {
  args: { tabs: SETTINGS, value: "general", orientation: "vertical", "aria-label": "Settings" },
  render: controlled,
  decorators: [
    (Story) => (
      <div style={{ width: "24rem" }}>
        <Story />
      </div>
    ),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("tablist")).toHaveAttribute("aria-orientation", "vertical");
    await userEvent.tab();
    await userEvent.keyboard("{ArrowDown}");
    await expect(canvas.getByRole("tab", { name: "Appearance" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  },
};

export const WithIcons: Story = {
  args: { tabs: ICONS, "aria-label": "Inspector" },
  render: controlled,
};

export const GatedTab: Story = {
  args: { tabs: GATED },
  render: controlled,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const algos = canvas.getByRole("tab", { name: "Algos" });
    await expect(algos).toHaveAttribute("aria-disabled", "true");
    await expect(algos).toHaveAccessibleDescription(REASON);
    await userEvent.tab();
    await userEvent.keyboard("{End}");
    await expect(algos).toHaveFocus();
    await expect(algos).toHaveAttribute("aria-selected", "false");
    await expect(canvas.getByRole("status")).toBeEmptyDOMElement();
    await userEvent.keyboard("{Enter}");
    await expect(canvas.getByRole("status")).toHaveTextContent(REASON);
    await expect(args.onChange).not.toHaveBeenCalledWith("algos");
  },
};

export const ManualActivation: Story = {
  args: { tabs: ORDER_TYPES, value: "market", activation: "manual", "aria-label": "Order type" },
  render: controlled,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.tab();
    await userEvent.keyboard("{ArrowRight}");
    await expect(canvas.getByRole("tab", { name: "Limit" })).toHaveFocus();
    await expect(canvas.getByRole("tab", { name: "Market" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(args.onChange).not.toHaveBeenCalled();
  },
};

/** Conventions 49: more tabs than fit; the strip scrolls in one row and hides no tab. */
export const Overflow: Story = {
  render: controlled,
  decorators: [
    (Story) => (
      <div style={{ width: "12rem" }}>
        <Story />
      </div>
    ),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const tops = canvas.getAllByRole("tab").map((tab) => tab.getBoundingClientRect().top);
    await expect(new Set(tops).size).toBe(1);
    await userEvent.tab();
    await userEvent.keyboard("{End}");
    await waitFor(() => expect(canvas.getByRole("tablist").scrollLeft).toBeGreaterThan(0));
  },
};

/** Every cell side by side (spec matrix): horizontal, icons, gated, manual, vertical. */
export const AllStates: Story = {
  render: (args) => (
    <div style={{ display: "grid", gap: "var(--space-inset-lg)" }}>
      <Controlled {...(args as HostProps)} />
      <Controlled {...(args as HostProps)} tabs={ICONS} aria-label="Inspector" />
      <Controlled {...(args as HostProps)} tabs={GATED} aria-label="Blotter, gated" />
      <Controlled
        {...(args as HostProps)}
        tabs={ORDER_TYPES}
        value="market"
        activation="manual"
        aria-label="Order type"
      />
      <Controlled
        {...(args as HostProps)}
        tabs={SETTINGS}
        value="general"
        orientation="vertical"
        aria-label="Settings"
      />
    </div>
  ),
};

/** The gated label and the reason line per theme; axe checks the contrast. */
const gatedMatrix = (theme: string): Story => ({
  globals: { theme },
  args: { tabs: GATED },
  render: controlled,
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
});
export const GatedContrastLight: Story = gatedMatrix("light");
export const GatedContrastHighContrast: Story = gatedMatrix("high-contrast");
