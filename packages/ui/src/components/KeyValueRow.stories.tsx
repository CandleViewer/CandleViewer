import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";
import { KeyValueRow } from "./KeyValueRow.js";
import { NumericText, Text } from "./Typography.js";

const list = { margin: 0, width: "18rem" } as const;

/** Theme and density come from the toolbars; the light and high-contrast stories pin the theme for axe. */
const meta: Meta<typeof KeyValueRow> = {
  title: "Atoms/KeyValueRow",
  component: KeyValueRow,
  args: {
    label: "Liquidation",
    value: <NumericText value={61234.5} format="price" />,
  },
  decorators: [
    (Story) => (
      <dl style={list}>
        <Story />
      </dl>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof KeyValueRow>;

export const Default: Story = {
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByRole("term")).toHaveTextContent("Liquidation");
    await expect(c.getByRole("definition")).toHaveTextContent("61,234.50");
  },
};

/** The value one step up: a number in type.num.md (PROPOSED heuristic). */
export const Emphasis: Story = { args: { emphasis: true } };

export const TextValue: Story = { args: { label: "Key label", value: "Main desk, read only" } };

/** "—" in color.text.secondary, read as the state word, never as a dash or a zero. */
export const Missing: Story = {
  args: { label: "Funding", value: undefined },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("definition")).toHaveTextContent("—no value");
  },
};

/** The freshness slot: a CMP-239 FreshnessMarker once it exists; a stand-in word here. */
export const Stale: Story = {
  args: {
    label: "Mark price",
    freshness: (
      <Text variant="caption" tone="secondary">
        stale
      </Text>
    ),
  },
};

/** The value under its label, for a narrow host or 150 % text. */
export const Stacked: Story = { args: { layout: "stacked", label: "Order id", value: "ord-7f3a" } };

const All: Story = {
  render: () => (
    <>
      <KeyValueRow label="Liquidation" value={<NumericText value={61234.5} format="price" />} />
      <KeyValueRow label="Size" value={<NumericText value={1} format="qty" />} emphasis />
      <KeyValueRow label="Funding" value={null} />
      <KeyValueRow label="Account" value="Main desk" layout="stacked" />
    </>
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
