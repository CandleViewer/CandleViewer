import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";
import { ConfidenceDots } from "./ConfidenceDots.js";

const col = { display: "grid", gap: "var(--space-inset-sm)", justifyItems: "start" } as const;

/** Theme and density come from the toolbars; the light and high-contrast stories pin the theme for axe. */
const meta: Meta<typeof ConfidenceDots> = {
  title: "Atoms/ConfidenceDots",
  component: ConfidenceDots,
  args: { level: "low" },
};
export default meta;
type Story = StoryObj<typeof ConfidenceDots>;

/** #265 Gherkin "Estimated confidence is not colour-only": one filled dot of three plus the word. */
export const Low: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Low confidence")).toBeTruthy();
    await expect(canvasElement.querySelectorAll(".cv-confidence__dot[data-filled]")).toHaveLength(
      1,
    );
    await expect(canvasElement.querySelector(".cv-confidence__dots")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
  },
};
export const Medium: Story = { args: { level: "medium" } };
export const High: Story = { args: { level: "high" } };

/** The consumer's numeric confidence as the label; it still names the level. */
export const NumericLabel: Story = { args: { level: "medium", label: "72 %, medium confidence" } };

/** In a narrow host the label wraps and the dots stay on its first line. */
export const LongText: Story = {
  args: {
    level: "high",
    label: "High confidence: iceberg refills seen at the same price five times",
  },
  render: (args) => (
    <div style={{ width: "12rem" }}>
      <ConfidenceDots {...args} />
    </div>
  ),
};

export const AllLevels: Story = {
  render: () => (
    <div style={col}>
      <ConfidenceDots level="low" />
      <ConfidenceDots level="medium" />
      <ConfidenceDots level="high" />
    </div>
  ),
};

const themed = (theme: string): Story => ({
  ...AllLevels,
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
});
export const Light: Story = themed("light");
export const HighContrast: Story = themed("high-contrast");
