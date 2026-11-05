import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import { DockPanel, PanelHeader } from "./DockPanel.js";

const box = { height: "12rem", width: "24rem", display: "flex" } as const;
const header = <PanelHeader kind="Chart" title="Chart BTCUSDT 1 minute" onMove={() => {}} />;

/** CMP-080: one panel; theme and density come from the toolbars. */
const meta: Meta<typeof DockPanel> = {
  title: "Organisms/Dock/DockPanel",
  component: DockPanel,
  args: { title: "Chart BTCUSDT 1 minute", header },
  decorators: [(Story) => <div style={box}>{Story()}</div>],
};
export default meta;
type Story = StoryObj<typeof DockPanel>;

export const Default: Story = {
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("region", { name: "Chart BTCUSDT 1 minute" }),
    ).toBeVisible();
  },
};
/** The inset frame and the header bar; the content box is the Default story's. */
export const Focused: Story = { args: { focused: true } };
export const Loading: Story = { args: { state: "loading" } };
export const CompactView: Story = { args: { state: "compact" } };
export const Error: Story = { args: { state: "error" } };
export const Maximised: Story = { args: { state: "maximised" } };
export const Closable: Story = {
  args: {
    header: (
      <PanelHeader
        kind="Chart"
        title="Chart BTCUSDT 1 minute"
        onMove={() => {}}
        onClose={() => {}}
      />
    ),
  },
};
