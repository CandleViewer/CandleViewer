import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";
import { ProgressBar } from "./ProgressBar.js";

const col = { display: "grid", gap: "var(--space-inset-lg)", width: "20rem" } as const;

/** Theme, density and motion come from the toolbars; every state below renders at each combination. */
const meta: Meta<typeof ProgressBar> = {
  title: "Atoms/ProgressBar",
  component: ProgressBar,
  args: { value: 33 },
  render: (args) => (
    <div style={col}>
      <ProgressBar {...args} />
    </div>
  ),
};
export default meta;
type Story = StoryObj<typeof ProgressBar>;

export const Default: Story = {
  args: { label: "Loading history", valueText: "page 3 of ~9" },
  play: async ({ canvasElement }) => {
    const bar = within(canvasElement).getByRole("progressbar", { name: "Loading history" });
    await expect(bar).toHaveAttribute("aria-valuetext", "page 3 of ~9");
  },
};

export const Empty: Story = { args: { label: "Loading history", value: 0 } };

export const Complete: Story = { args: { label: "Loading history", value: 100 } };

/** Named by the host's heading through `aria-labelledby`; the value text still shows. */
export const Unlabelled: Story = {
  args: { "aria-labelledby": "export-heading", value: 60 },
  render: (args) => (
    <section style={col}>
      <h3 id="export-heading" style={{ margin: 0 }}>
        Exporting trades
      </h3>
      <ProgressBar {...args} />
    </section>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("progressbar")).toHaveAccessibleName(
      "Exporting trades",
    );
  },
};

export const Meter: Story = {
  args: { kind: "meter", label: "Recording budget", value: 31 },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("meter", { name: "Recording budget" }),
    ).toBeTruthy();
  },
};

export const Success: Story = {
  args: { tone: "success", label: "Export finished", value: 100 },
};

export const Warning: Story = {
  args: { kind: "meter", tone: "warning", label: "Recorder disk", value: 85 },
};

export const Danger: Story = {
  args: { kind: "meter", tone: "danger", label: "Recorder disk", value: 97 },
};

export const LongText: Story = {
  args: {
    label: "Backfilling recorded order-book coverage for every subscribed symbol",
    valueText: "page 3 of approximately 9 (BTCUSDT, ETHUSDT, SOLUSDT)",
  },
};

/** The tones side by side, for the theme and density toolbars. */
export const AllTones: Story = {
  render: () => (
    <div style={col}>
      <ProgressBar label="Default" value={33} />
      <ProgressBar label="Success" tone="success" value={100} />
      <ProgressBar label="Warning" kind="meter" tone="warning" value={85} />
      <ProgressBar label="Danger" kind="meter" tone="danger" value={97} />
    </div>
  ),
};

const themed = (theme: string): Story => ({
  ...AllTones,
  globals: { theme },
  play: async () => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
});
export const Light: Story = themed("light");
export const HighContrast: Story = themed("high-contrast");

/** Reduced motion: a new value is a step, not a slide. */
export const ReducedMotion: Story = { ...Default, globals: { motion: "on" } };
