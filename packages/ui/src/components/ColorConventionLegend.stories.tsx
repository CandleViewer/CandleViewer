import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor } from "storybook/test";
import { ColorConventionLegend } from "./ColorConventionLegend.js";

const meta: Meta<typeof ColorConventionLegend> = {
  title: "Trading/ColorConventionLegend",
  component: ColorConventionLegend,
  args: { view: "Footprint" },
  decorators: [
    (Story, ctx) => (
      <div
        data-theme={String(ctx.globals["theme"] ?? "dark")}
        data-palette={ctx.args.palette ?? "default"}
        data-convention={ctx.args.convention ?? "standard"}
      >
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof ColorConventionLegend>;

export const Default: Story = {};
export const Inverted: Story = { args: { convention: "inverted" } };
export const CvdSafe: Story = { args: { palette: "cvd-safe" } };
export const CvdSafeInverted: Story = { args: { palette: "cvd-safe", convention: "inverted" } };
/** Pinned themes set the global, so the page canvas switches too and axe measures the real pair. */
const themed = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
});
export const HighContrast: Story = themed("high-contrast");
export const LightTheme: Story = themed("light");
