import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";
import { Divider, DividerLabel } from "./Divider.js";
import { Text } from "./Typography.js";

const toolbar = { display: "flex", alignItems: "center", gap: "var(--space-inset-sm)" } as const;
const panel = { display: "grid", gap: "var(--space-inset-sm)", maxWidth: "20rem" } as const;

/** Theme and density come from the toolbars; the light and high-contrast stories pin the theme for axe. */
const meta: Meta<typeof Divider> = {
  title: "Atoms/Divider",
  component: Divider,
};
export default meta;
type Story = StoryObj<typeof Divider>;

/** A meaningful rule between two groups (`role="separator"`), plain and inset. */
export const Horizontal: Story = {
  render: () => (
    <div style={panel}>
      <Text>Open orders</Text>
      <Divider />
      <Text>Positions</Text>
      <Divider inset />
      <Text>Inset by space.inset.md at both ends</Text>
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getAllByRole("separator")).toHaveLength(2);
  },
};

/** A vertical rule in a toolbar row: size.control.height at least, `aria-orientation="vertical"`. */
export const Vertical: Story = {
  render: () => (
    <div role="toolbar" aria-label="Drawing tools" style={toolbar}>
      <button type="button" className="cv-control">
        Line
      </button>
      <Divider orientation="vertical" />
      <button type="button" className="cv-control">
        Text
      </button>
      <Divider orientation="vertical" inset />
      <button type="button" className="cv-control">
        Clear
      </button>
    </div>
  ),
};

/** Layout only: removed from the accessibility tree. */
export const Decorative: Story = {
  render: () => (
    <div style={panel}>
      <Text>Above</Text>
      <Divider decorative />
      <Text>Below</Text>
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("separator")).toBeNull();
  },
};

/** CMP-030: the caption names the separator; at 120 px it wraps and the rule shrinks first. */
export const Labelled: Story = {
  render: () => (
    <div style={panel}>
      <DividerLabel label="Take profit" />
      <div style={{ width: "7.5rem" }}>
        <DividerLabel label="Stop loss and trailing" />
      </div>
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("separator", { name: "Take profit" }),
    ).toBeInTheDocument();
  },
};

const All: Story = {
  render: () => (
    <div style={panel}>
      <DividerLabel label="Take profit" />
      <Divider />
      <div style={toolbar}>
        <Text>Left</Text>
        <Divider orientation="vertical" />
        <Text>Right</Text>
      </div>
    </div>
  ),
};

const themed = (theme: string): Story => ({
  ...All,
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
});
export const ContrastLight: Story = themed("light");
export const ContrastHighContrast: Story = themed("high-contrast");
