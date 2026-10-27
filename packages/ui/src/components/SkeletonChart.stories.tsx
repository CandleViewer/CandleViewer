import type { JSX } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import { SkeletonChart, type SkeletonChartProps } from "./SkeletonChart.js";

/** CMP-029 in its chart region: busy, named, with the host's words over it, outside the hidden node. */
const pane = (args: SkeletonChartProps): JSX.Element => (
  <section
    aria-label="BTCUSDT chart"
    aria-busy="true"
    style={{ position: "relative", width: "32rem", height: "18rem" }}
  >
    <SkeletonChart {...args} />
    <p
      style={{
        position: "absolute",
        inset: 0,
        margin: "auto",
        height: "fit-content",
        textAlign: "center",
      }}
    >
      Loading 5,000 bars…
    </p>
  </section>
);

/**
 * Theme, density and motion come from the toolbars. The per-block shimmer animates every candle (about 190 blocks
 * per price pane), bounded to 4.8 s.
 */
const meta: Meta<typeof SkeletonChart> = {
  title: "Atoms/SkeletonChart",
  component: SkeletonChart,
  render: (args) => pane(args),
};
export default meta;
type Story = StoryObj<typeof SkeletonChart>;

export const Default: Story = {
  play: async ({ canvasElement }) => {
    const region = within(canvasElement).getByRole("region", { name: "BTCUSDT chart" });
    await expect(region).toHaveAttribute("aria-busy", "true");
    await expect(canvasElement.querySelector("[data-cmp='CMP-029']")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
  },
};

export const ThreePanes: Story = {
  args: { paneCount: 3 },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelectorAll(".cv-skeleton-chart__pane")).toHaveLength(3);
  },
};

/** Reduced motion: the static two-tone from the first frame. */
export const Static: Story = { ...Default, globals: { motion: "on" } };
export const Light: Story = { ...ThreePanes, globals: { theme: "light" } };
export const HighContrast: Story = { ...ThreePanes, globals: { theme: "high-contrast" } };
