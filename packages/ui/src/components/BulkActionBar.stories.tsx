import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { BulkActionBar, type BulkAction } from "./BulkActionBar.js";

const action = (label: string): BulkAction => ({ id: label, label, onClick: fn() });
/** SCR-080's actions (E36-D03 §2): "3 selected · Disarm · Export · Clear". */
const RULES: readonly BulkAction[] = [action("Disarm"), action("Export")];
/** SCR-036's actions (E13-D02 §6.3 D22): Hide · Show · Lock · Unlock · Delete, then Clear. */
const OBJECTS: readonly BulkAction[] = ["Hide", "Show", "Lock", "Unlock", "Delete"].map(action);

const meta: Meta<typeof BulkActionBar> = {
  title: "Molecules/BulkActionBar",
  component: BulkActionBar,
  args: { count: 3, actions: RULES, onClear: fn() },
};
export default meta;
type Story = StoryObj<typeof BulkActionBar>;

const bar = (canvas: HTMLElement): HTMLElement =>
  within(canvas).getByRole("toolbar", { name: "3 selected" });

/** No selection: the bar is not rendered at all. */
export const Hidden: Story = {
  args: { count: 0 },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("toolbar")).toBeNull();
  },
};

/** A selection: the toolbar is named by its count; one Tab stop, arrows rove, its appearance takes no focus. */
export const ThreeSelected: Story = {
  play: async ({ canvasElement, args }) => {
    const toolbar = bar(canvasElement);
    await expect(toolbar).not.toContainElement(document.activeElement as HTMLElement | null);
    await userEvent.tab();
    const disarm = within(toolbar).getByRole("button", { name: "Disarm" });
    await expect(disarm).toHaveFocus();
    await userEvent.keyboard("{End}");
    await expect(within(toolbar).getByRole("button", { name: "Clear" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await expect(args.onClear).toHaveBeenCalledTimes(1);
  },
};

/** Reduced motion: the panel-in recipe resolves to none, so the bar is there at frame 0. */
export const ReducedMotion: Story = {
  globals: { motion: "on" },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-motion", "reduce"));
    await expect(getComputedStyle(bar(canvasElement)).animationName).toBe("none");
  },
};

/** SCR-080 (E36-D03 §2): Disarm · Export · Clear. */
export const RulesList: Story = {
  play: async ({ canvasElement }) => {
    const names = within(bar(canvasElement))
      .getAllByRole("button")
      .map((b) => b.textContent);
    await expect(names).toEqual(["Disarm", "Export", "Clear"]);
  },
};

/** SCR-036 (E13-D02 §6.3): Hide · Show · Lock · Unlock · Delete · Clear. */
export const IndicatorManager: Story = {
  args: { actions: OBJECTS },
  play: async ({ canvasElement }) => {
    await expect(within(bar(canvasElement)).getAllByRole("button")).toHaveLength(6);
  },
};
