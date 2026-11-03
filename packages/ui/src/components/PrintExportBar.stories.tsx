import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { PrintExportBar } from "./PrintExportBar.js";

/** SCR-078's title bar offers CSV alone (E29-D04 §2.8.9); the catalogue's second format is PDF. */
const meta: Meta<typeof PrintExportBar> = {
  title: "Molecules/PrintExportBar",
  component: PrintExportBar,
  args: { formats: ["csv"], onExport: fn() },
};
export default meta;
type Story = StoryObj<typeof PrintExportBar>;

const exportCsv = (canvas: HTMLElement): HTMLElement =>
  within(canvas).getByRole("button", { name: "Export CSV" });

/** Idle: one CMP-001 secondary button named "Export CSV" (E29-D03:297). */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    await expect(exportCsv(canvasElement)).not.toHaveAttribute("aria-busy");
  },
};

/** Both catalogue formats, one distinct labelled button each; "Export PDF" is PROPOSED. */
export const BothFormats: Story = {
  args: { formats: ["csv", "pdf"] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getAllByRole("button")).toHaveLength(2);
    await expect(within(canvasElement).getByRole("button", { name: "Export PDF" })).toBeVisible();
  },
};

export const Hover: Story = {
  play: async ({ canvasElement }) => userEvent.hover(exportCsv(canvasElement)),
};

export const FocusVisible: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(exportCsv(canvasElement)).toHaveFocus();
  },
};

/** Keyboard reachable: Tab, then `Enter` and `Space` each start the export. */
export const Keyboard: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.tab();
    await expect(exportCsv(canvasElement)).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    await expect(args.onExport).toHaveBeenCalledTimes(2);
    await expect(args.onExport).toHaveBeenLastCalledWith("csv");
  },
};

/**
 * Running (E29-D03:200): CMP-038's busy form, `aria-busy` with the label kept and the arc leading it; a press does
 * nothing, and the bar says nothing (the host's footer carries the progress words).
 */
export const Exporting: Story = {
  args: { loading: true },
  play: async ({ canvasElement, args }) => {
    const button = exportCsv(canvasElement);
    await expect(button).toHaveAttribute("aria-busy", "true");
    const label = button.querySelector(".cv-button__label");
    const arc = button.querySelector(".cv-spinner");
    await expect(label).toBeVisible();
    await expect(arc).toBeVisible();
    await expect(getComputedStyle(label ?? button).opacity).toBe("1");
    // The arc leads the label, clear of it.
    await expect(arc?.getBoundingClientRect().right).toBeLessThanOrEqual(
      label?.getBoundingClientRect().left ?? Number.NEGATIVE_INFINITY,
    );
    button.focus();
    await userEvent.keyboard("{Enter}");
    await expect(args.onExport).not.toHaveBeenCalled();
    await expect(canvasElement.querySelector("[aria-live], [role='status']")).toBeNull();
  },
};

/** Reduced motion: the arc stands still and the label still says what runs. */
export const ExportingReducedMotion: Story = {
  args: { loading: true },
  globals: { motion: "on" },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-motion", "reduce"));
    const arc = canvasElement.querySelector(".cv-spinner__arc");
    await expect(arc).toBeVisible();
    await expect(arc === null ? "" : getComputedStyle(arc).animationName).toBe("none");
    const running = arc?.getAnimations() ?? [];
    await expect(running.every((a) => a.playState !== "running")).toBe(true);
    await expect(exportCsv(canvasElement)).toHaveAttribute("aria-busy", "true");
  },
};

/**
 * A narrow title bar, a column narrower than one label: each button keeps its whole label, never "Export C…", and the
 * second format wraps under the first (E29-D03 §3.2, §8.2).
 */
export const Narrow: Story = {
  args: { formats: ["csv", "pdf"] },
  render: (args) => (
    <div style={{ display: "grid", gridTemplateColumns: "4rem" }}>
      <PrintExportBar {...args} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const buttons = within(canvasElement).getAllByRole("button");
    for (const button of buttons) {
      const label = button.querySelector(".cv-button__label") ?? button;
      await expect(getComputedStyle(label).textOverflow).toBe("clip");
      await expect(getComputedStyle(button).flexShrink).toBe("0");
      // Nothing overflows the button: it holds its whole label.
      await expect(button.scrollWidth).toBeLessThanOrEqual(button.clientWidth);
    }
    const [csv, pdf] = buttons.map((button) => button.getBoundingClientRect());
    await expect(pdf?.top).toBeGreaterThanOrEqual(csv?.bottom ?? Number.POSITIVE_INFINITY);
  },
};

/** Idle and running, both formats, under the light and high-contrast themes; axe checks each theme. */
const themeMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: () => (
    <div style={{ display: "grid", gap: "var(--space-stack-sm)", justifyItems: "start" }}>
      <PrintExportBar formats={["csv", "pdf"]} onExport={fn()} />
      <PrintExportBar formats={["csv", "pdf"]} onExport={fn()} loading />
    </div>
  ),
});
export const ContrastLight: Story = themeMatrix("light");
export const ContrastHighContrast: Story = themeMatrix("high-contrast");
