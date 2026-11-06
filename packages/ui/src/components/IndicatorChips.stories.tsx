import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";
import { IndicatorChips } from "./IndicatorChips.js";

/** Density comes from the toolbar (compact: a 20 px pill in a 24 px hit box; comfortable: a 24 px pill). */
const meta: Meta<typeof IndicatorChips> = {
  title: "Molecules/IndicatorChips",
  component: IndicatorChips,
  args: { count: 4, onOpen: fn() },
};
export default meta;
type Story = StoryObj<typeof IndicatorChips>;

export const None: Story = { args: { count: 0 } };
export const Several: Story = {};
export const WithHidden: Story = { args: { suffix: { kind: "hidden", n: 1 } } };
export const WithError: Story = { args: { suffix: { kind: "error", n: 1 } } };
export const WithComputing: Story = { args: { suffix: { kind: "computing", n: 1 } } };
export const WithStale: Story = { args: { suffix: { kind: "stale", n: 2 } } };
export const AtCap: Story = { args: { count: 20 } };
/** SCR-036 is open: the chip is `aria-expanded` and `aria-controls` the drawer, with the pressed fill. */
export const PressedDrawerOpen: Story = {
  args: { open: true, drawerId: "scr-036-drawer" },
  play: async ({ canvasElement }) => {
    const chip = within(canvasElement).getByRole("button", { name: /^Indicators: 4 / });
    await expect(chip).toHaveAttribute("aria-expanded", "true");
    await expect(chip).toHaveAttribute("aria-controls", "scr-036-drawer");
    await expect(chip).not.toHaveAttribute("aria-pressed");
  },
};
/** Keyboard focus shows the ring; `Enter` opens SCR-036. */
export const Focused: Story = {
  args: { suffix: { kind: "hidden", n: 1 } },
  play: async ({ args, canvasElement }) => {
    await userEvent.tab();
    const chip = within(canvasElement).getByRole("button", {
      name: "Indicators: 4 on this chart, 1 hidden — open the object manager",
    });
    await expect(chip).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await expect(args.onOpen).toHaveBeenCalledTimes(1);
  },
};
