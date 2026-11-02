import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import { PanelHeader } from "./DockPanel.js";

/** CMP-082: the handle ("Move {Kind}"), the heading, own actions (a toolbar) and close. */
const meta: Meta<typeof PanelHeader> = {
  title: "Organisms/Dock/PanelHeader",
  component: PanelHeader,
  args: { kind: "Chart", title: "Chart BTCUSDT 1 minute", onMove: () => {} },
  decorators: [(Story) => <div style={{ width: "24rem" }}>{Story()}</div>],
};
export default meta;
type Story = StoryObj<typeof PanelHeader>;

export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Move Chart" })).toBeVisible();
    await expect(canvas.getByRole("heading", { level: 2 })).toHaveTextContent(
      "Chart BTCUSDT 1 minute",
    );
  },
};
export const WithActions: Story = {
  args: {
    actions: (
      <button type="button" className="cv-control">
        Indicators
      </button>
    ),
    onClose: () => {},
  },
};
/** Inside a tab group the heading is an h3. */
export const InTabGroup: Story = { args: { level: 3 } };
export const NarrowHeader: Story = {
  decorators: [(Story) => <div style={{ width: "10rem" }}>{Story()}</div>],
};
