import type { Meta, StoryObj } from "@storybook/react-vite";
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
export const HighContrast: Story = {
  decorators: [
    (Story) => (
      <div data-theme="hc" data-high-contrast="true">
        <Story />
      </div>
    ),
  ],
};
export const LightTheme: Story = {
  decorators: [
    (Story) => (
      <div data-theme="light">
        <Story />
      </div>
    ),
  ],
};
