import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { MaskedValue } from "./MaskedValue.js";

/** A stand-in value: stories never hold a real secret. */
const VALUE = "demo-secret-7f3a9c21e4b0";
const MASK = "•".repeat(8);
const writeText = fn<(text: string) => Promise<void>>();

/** Swaps `navigator.clipboard` for a mock, so no story touches the real clipboard. */
const mockClipboard = (): (() => void) => {
  writeText.mockReset();
  writeText.mockImplementation(() => Promise.resolve());
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  return () => {
    Reflect.deleteProperty(navigator, "clipboard");
  };
};

/**
 * Theme and density come from the toolbars. Every story mounts masked (S1): the revealed states are
 * reached by a press in the play function, never by a prop.
 */
const meta: Meta<typeof MaskedValue> = {
  title: "Atoms/MaskedValue",
  component: MaskedValue,
  args: { value: VALUE, label: "API secret", onToggleReveal: fn() },
  beforeEach: mockClipboard,
  render: (args) => (
    <div style={{ inlineSize: "22rem" }}>
      <MaskedValue {...args} />
    </div>
  ),
};
export default meta;
type Story = StoryObj<typeof MaskedValue>;

const toggle = (canvas: HTMLElement, verb: "Show" | "Hide", label = "API secret"): HTMLElement =>
  within(canvas).getByRole("button", { name: `${verb} ${label}` });
const stateOf = (canvas: HTMLElement): string | undefined =>
  canvas.querySelector<HTMLElement>(".cv-masked-value")?.dataset["state"];
const reveal = async (canvas: HTMLElement): Promise<void> => {
  await userEvent.click(toggle(canvas, "Show"));
  await waitFor(() => expect(stateOf(canvas)).toBe("revealed"));
};

/** Masked (the default at every mount): the 8-dot mask and "Show API secret"; the value is nowhere. */
export const Masked: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("group", { name: "API secret" })).toBeTruthy();
    await expect(canvasElement.querySelector(".cv-masked-value__mask")).toHaveTextContent(MASK);
    await expect(toggle(canvasElement, "Show")).not.toHaveAttribute("aria-pressed");
    await expect(document.body.innerHTML).not.toContain(VALUE);
  },
};

/** The toggle draws the only ring (the nested CMP-002). */
export const FocusVisible: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(toggle(canvasElement, "Show")).toHaveFocus();
  },
};

export const Hover: Story = {
  play: async ({ canvasElement }) => userEvent.hover(toggle(canvasElement, "Show")),
};

/** Revealed after a press: the value in `type.num.base`, "Hide API secret" with focus kept. */
export const Revealed: Story = {
  play: async ({ canvasElement, args }) => {
    await reveal(canvasElement);
    await expect(canvasElement.querySelector(".cv-masked-value__value")).toHaveTextContent(VALUE);
    await expect(toggle(canvasElement, "Hide")).toHaveFocus();
    await expect(args.onToggleReveal).toHaveBeenCalledWith(true);
  },
};

/** The count under the box, "Hides in 10 s"; it is never spoken per tick. */
export const AutoHideCountdown: Story = {
  play: async ({ canvasElement }) => {
    await reveal(canvasElement);
    await expect(canvasElement.querySelector(".cv-masked-value__countdown")).toHaveTextContent(
      /^Hides in (10|9) s/,
    );
    await expect(within(canvasElement).getByRole("status")).toBeEmptyDOMElement();
  },
};

/**
 * Expiring, then the re-mask: with the 3 s floor the last 2 s arrive after one second, "API secret will
 * hide in 2 seconds" is spoken once, and at 3 s the mask returns with focus kept on the toggle.
 */
export const Expiring: Story = {
  args: { autoHideMs: 3000 },
  play: async ({ canvasElement, args }) => {
    await reveal(canvasElement);
    await waitFor(() => expect(stateOf(canvasElement)).toBe("expiring"), { timeout: 2500 });
    await expect(within(canvasElement).getByRole("status")).toHaveTextContent(
      "API secret will hide in 2 seconds",
    );
    await waitFor(() => expect(stateOf(canvasElement)).toBe("masked"), { timeout: 3500 });
    await expect(toggle(canvasElement, "Show")).toHaveFocus();
    await expect(args.onToggleReveal).toHaveBeenLastCalledWith(false);
    await expect(document.body.innerHTML).not.toContain(VALUE);
  },
};

/** Copyable while masked: CMP-033 is disabled until the value is revealed (G19). */
export const Copyable: Story = {
  args: { copyable: true },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", { name: "Copy API secret" }),
    ).toBeDisabled();
    await expect(document.body.innerHTML).not.toContain(VALUE);
  },
};

/** Revealed and copied: CMP-033's `check` and "Copied"; the status never holds the value. */
export const CopiedState: Story = {
  args: { copyable: true },
  play: async ({ canvasElement }) => {
    await reveal(canvasElement);
    const copy = within(canvasElement).getByRole("button", { name: "Copy API secret" });
    await userEvent.click(copy);
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(VALUE));
    const statuses = within(canvasElement).getAllByRole("status");
    await waitFor(() => expect(statuses.some((s) => s.textContent === "Copied")).toBe(true));
  },
};

/** A long value wraps at any character inside the box; the buttons never grow or move out. */
export const LongText: Story = {
  args: {
    value: `${"demo".repeat(24)}-end`,
    label: "Exchange API secret for the main trading account",
    copyable: true,
  },
  play: async ({ canvasElement }) => {
    const label = "Exchange API secret for the main trading account";
    await userEvent.click(toggle(canvasElement, "Show", label));
    const button = toggle(canvasElement, "Hide", label);
    const host = canvasElement.querySelector(".cv-masked-value");
    const box = canvasElement.querySelector(".cv-masked-value__box");
    await expect(host?.getBoundingClientRect().right).toBeGreaterThanOrEqual(
      box?.getBoundingClientRect().right ?? Number.POSITIVE_INFINITY,
    );
    const rect = button.getBoundingClientRect();
    await expect(rect.width).toBe(rect.height);
  },
};

/** S1: revealing the second value masks the first. */
export const OneRevealedPerPage: Story = {
  render: (args) => (
    <div style={{ display: "grid", gap: "var(--space-stack-sm)", inlineSize: "22rem" }}>
      <MaskedValue {...args} label="API key" value="demo-key-0001" />
      <MaskedValue {...args} label="API secret" />
    </div>
  ),
  play: async ({ canvasElement }) => {
    await userEvent.click(toggle(canvasElement, "Show", "API key"));
    await userEvent.click(toggle(canvasElement, "Show", "API secret"));
    await waitFor(() => expect(toggle(canvasElement, "Show", "API key")).toBeTruthy());
    await expect(toggle(canvasElement, "Hide", "API secret")).toBeTruthy();
    await expect(document.body.innerHTML).not.toContain("demo-key-0001");
  },
};

/** Masked and revealed under the light and high-contrast themes; axe checks each theme. */
const themeMatrix = (theme: string): Story => ({
  globals: { theme },
  args: { copyable: true },
  render: (args) => (
    <div style={{ display: "grid", gap: "var(--space-stack-sm)", inlineSize: "22rem" }}>
      <MaskedValue {...args} label="API key" value="demo-key-0001" />
      <MaskedValue {...args} label="API secret" />
    </div>
  ),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
    await userEvent.click(toggle(canvasElement, "Show", "API secret"));
    await waitFor(() => expect(toggle(canvasElement, "Hide", "API secret")).toBeTruthy());
  },
});
export const ContrastLight: Story = themeMatrix("light");
export const ContrastHighContrast: Story = themeMatrix("high-contrast");
