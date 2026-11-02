import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";
import { PositionModeToggle } from "./PositionModeToggle.js";

const meta: Meta<typeof PositionModeToggle> = {
  title: "Trading/PositionModeToggle",
  component: PositionModeToggle,
  args: { value: "one-way" },
};
export default meta;
type Story = StoryObj<typeof PositionModeToggle>;

/** `display` is text: no role, no Tab stop, nothing to press (E29-D04 §2.5). */
const isPlainText = async (canvas: HTMLElement, word: string): Promise<void> => {
  const text = within(canvas).getByText(word);
  await expect(text).not.toHaveAttribute("role");
  await expect(text).not.toHaveAttribute("tabindex");
  await expect(within(canvas).queryByRole("radiogroup")).toBeNull();
  await expect(within(canvas).queryByRole("button")).toBeNull();
};

/** `CMP-129/display-one-way`: the account group header's mode. */
export const DisplayOneWay: Story = {
  play: async ({ canvasElement }) => isPlainText(canvasElement, "One-way"),
};

/** `CMP-129/display-hedge`. */
export const DisplayHedge: Story = {
  args: { value: "hedge" },
  play: async ({ canvasElement }) => isPlainText(canvasElement, "Hedge"),
};

/** Both words under the light and high-contrast themes; axe checks each theme. */
const themeMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: () => (
    <div style={{ display: "flex", gap: "var(--space-inset-md)" }}>
      <PositionModeToggle value="one-way" />
      <PositionModeToggle value="hedge" />
    </div>
  ),
});
export const ContrastLight: Story = themeMatrix("light");
export const ContrastHighContrast: Story = themeMatrix("high-contrast");
