import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { InlineSpinnerText, SLOW_AFTER_MS } from "./InlineSpinnerText.js";

/**
 * Brings the 5 s slow path forward for one story, so its play function and axe see the slow state without a
 * real five-second wait. Only the slow-path delay is shortened; every other timer keeps its own.
 */
const fastSlowPath = (): (() => void) => {
  const real = window.setTimeout;
  const shortened = (handler: TimerHandler, ms?: number, ...rest: unknown[]): number =>
    real(handler, ms === SLOW_AFTER_MS ? 0 : ms, ...rest);
  window.setTimeout = shortened as typeof window.setTimeout;
  return () => {
    window.setTimeout = real;
  };
};

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof InlineSpinnerText> = {
  title: "Atoms/InlineSpinnerText",
  component: InlineSpinnerText,
  args: { label: "Loading positions" },
};
export default meta;
type Story = StoryObj<typeof InlineSpinnerText>;

const col = { display: "grid", gap: "var(--space-inset-sm)", justifyItems: "start" } as const;

/** Waiting: one polite status, mounted empty, the label inserted after mount; the spinner hidden. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const status = within(canvasElement).getByRole("status");
    await waitFor(() => expect(status).toHaveTextContent("Loading positions"));
    await expect(status.querySelector(".cv-spinner")).toHaveAttribute("aria-hidden", "true");
  },
};

/** SCR-150's slow boot at 5 s: the slow text replaces the label; no Cancel. */
export const SlowPath: Story = {
  beforeEach: fastSlowPath,
  args: { label: "Loading", slowLabel: "Still loading… the server is slow to answer" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("status")).toHaveTextContent("Still loading…"));
    await expect(canvas.queryByRole("button")).toBeNull();
  },
};

/** A load at 5 s: "Still loading positions…" with a ghost Cancel after the text, outside the status. */
export const SlowPathWithCancel: Story = {
  beforeEach: fastSlowPath,
  args: {
    kind: "load",
    label: "Loading positions",
    slowLabel: "Still loading positions…",
    onCancel: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const cancel = await canvas.findByRole("button", { name: "Cancel" });
    await expect(canvas.getByRole("status")).not.toHaveTextContent("Cancel");
    await userEvent.tab();
    await expect(cancel).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await expect(args.onCancel).toHaveBeenCalledTimes(1);
  },
};

/** A submit never offers Cancel, even on its slow path (C-2.10). */
export const SubmitNeverCancels: Story = {
  beforeEach: fastSlowPath,
  render: () => (
    <InlineSpinnerText kind="submit" label="Saving rule" slowLabel="Still saving the rule…" />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("status")).toHaveTextContent("Still saving"));
    await expect(canvas.queryByRole("button")).toBeNull();
  },
};

/** The text wraps after the spinner. */
export const LongText: Story = {
  render: () => (
    <div style={{ ...col, width: "12rem" }}>
      <InlineSpinnerText label="Loading 5,000 bars of BTCUSDT-PERPETUAL history from the recorder" />
    </div>
  ),
};

/** Every phase under the light and high-contrast themes; axe checks each theme. */
const themeMatrix = (theme: string): Story => ({
  globals: { theme },
  beforeEach: fastSlowPath,
  play: async ({ canvasElement }) => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
    await within(canvasElement).findByRole("button", { name: "Cancel export" });
  },
  render: () => (
    <div style={col}>
      <InlineSpinnerText label="Loading positions" />
      <InlineSpinnerText
        kind="export"
        label="Exporting"
        onCancel={fn()}
        cancelLabel="Cancel export"
      />
    </div>
  ),
});
export const ContrastLight: Story = themeMatrix("light");
export const ContrastHighContrast: Story = themeMatrix("high-contrast");
