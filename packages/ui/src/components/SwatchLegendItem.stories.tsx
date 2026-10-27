import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";
import { SwatchLegendItem } from "./SwatchLegendItem.js";

const list = { margin: 0, padding: 0, listStyle: "none", width: "12.5rem" } as const;

/** Theme and density come from the toolbars; the light and high-contrast stories pin the theme for axe. */
const meta: Meta<typeof SwatchLegendItem> = {
  title: "Atoms/SwatchLegendItem",
  component: SwatchLegendItem,
  args: { color: "var(--color-heatmap-bid-3)", label: "Bid liquidity", value: 1_200_000 },
  decorators: [
    (Story) => (
      <div role="group" aria-label="Heatmap legend">
        <ul style={list}>
          <Story />
        </ul>
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof SwatchLegendItem>;

/** "1.2M" is shown; "1,200,000" is read. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("listitem")).toHaveTextContent(
      "Bid liquidity1.2M1,200,000",
    );
  },
};

/** The zero stop: no value; the outline keeps the box visible. */
export const WithoutValue: Story = {
  render: () => <SwatchLegendItem color="var(--color-heatmap-zero)" label="Zero intensity" />,
};

/** A directional colour requires its glyph (the non-colour channel). */
export const WithGlyph: Story = {
  render: () => (
    <>
      <SwatchLegendItem
        color="var(--color-buy-default)"
        glyph="▲"
        label="Buy volume"
        value={1.1e6}
      />
      <SwatchLegendItem
        color="var(--color-sell-default)"
        glyph="▼"
        label="Sell volume"
        value={9e5}
      />
      <SwatchLegendItem
        color="var(--color-sell-default)"
        glyph="▼"
        label="Red = sell / ask / down"
      />
    </>
  ),
};

const themed = (theme: string): Story => ({
  ...WithGlyph,
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
});
export const ContrastLight: Story = themed("light");
export const ContrastHighContrast: Story = themed("high-contrast");
