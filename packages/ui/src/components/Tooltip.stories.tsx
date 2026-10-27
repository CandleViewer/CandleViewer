import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { Button } from "./Button.js";
import { IconButton } from "./IconButton.js";
import { Tooltip } from "./Tooltip.js";

const LONG =
  "Closes 4 positions at market — all accounts, LIVE + DEMO · hold 800 ms or press twice";
const REASON = "Only the owner can change account settings.";

const row = { display: "flex", gap: "var(--space-inset-sm)", alignItems: "center" } as const;
/** Room on every side, so the preferred side is the one drawn. */
const stage = { display: "grid", placeItems: "center", minHeight: "12rem" } as const;

/** Theme and density come from the toolbars; the light and high-contrast stories pin the theme for axe. */
const meta: Meta<typeof Tooltip> = {
  title: "Atoms/Tooltip",
  component: Tooltip,
  args: { content: "Saves the layout under a new name.", children: <Button>Save as</Button> },
  render: (args) => (
    <div style={stage}>
      <Tooltip {...args} />
    </div>
  ),
};
export default meta;
type Story = StoryObj<typeof Tooltip>;

/** The tooltip lives in a portal on `document.body`, outside the story canvas. */
const tooltip = (): HTMLElement => {
  const node = document.body.querySelector<HTMLElement>(".cv-tooltip");
  if (node === null) throw new Error("no tooltip in the document");
  return node;
};
const isShown = async (): Promise<void> =>
  waitFor(() => {
    expect(tooltip().hidden).toBe(false);
    expect(tooltip()).toHaveAttribute("data-positioned");
  });
const showByKeyboard = async (): Promise<void> => {
  await userEvent.tab();
  await isShown();
};

/** Describes · top · short · hover: hidden at first, shown after the 300 ms delay, hidden on leave. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Save as" });
    await expect(button).toHaveAccessibleDescription("Saves the layout under a new name.");
    await userEvent.hover(button);
    await expect(tooltip().hidden).toBe(true);
    await isShown();
    await expect(tooltip()).toHaveAttribute("data-side", "top");
    await userEvent.unhover(button);
    await waitFor(() => expect(tooltip().hidden).toBe(true));
  },
};

/** E39-D03 S20's sentence, wrapped at the 320 px maximum. */
export const LongContent: Story = {
  args: { content: LONG, children: <Button variant="danger">Flatten all</Button> },
  play: async () => {
    await showByKeyboard();
    const box = tooltip().getBoundingClientRect();
    const line = Number.parseFloat(getComputedStyle(tooltip()).lineHeight);
    await expect(box.width).toBeLessThanOrEqual(320);
    await expect(box.height).toBeGreaterThan(line * 1.5); // wrapped onto a second line
  },
};

/** Keyboard focus (`:focus-visible`) shows it at once, beside the trigger's CMP-039 ring (Gherkin). */
export const KeyboardTriggered: Story = {
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Save as" });
    await userEvent.tab();
    await expect(button).toHaveFocus();
    await isShown();
    await expect(button).toHaveAttribute("aria-describedby", tooltip().id);
  },
};

/** `Esc` hides it and focus stays on the trigger (APG; Gherkin). Tab away and back shows it again. */
export const EscDismiss: Story = {
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Save as" });
    await showByKeyboard();
    await userEvent.keyboard("{Escape}");
    await expect(tooltip().hidden).toBe(true);
    await expect(button).toHaveFocus();
    await userEvent.tab({ shift: true });
    await userEvent.tab();
    await isShown();
  },
};

/** Echo · name: a collapsed rail item's name over its icon; the name is the `aria-label`, read once. */
export const EchoName: Story = {
  args: {
    content: "Settings",
    mode: "echo",
    side: "right",
    children: <IconButton icon="settings" label="Settings" variant="ghost" />,
  },
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Settings" });
    await showByKeyboard();
    await expect(tooltip()).toHaveAttribute("aria-hidden", "true");
    await expect(button).not.toHaveAttribute("aria-describedby");
  },
};

/**
 * Echo · reason: the T2 2b echo over a gated CMP-002. The reason node is always rendered and is the
 * description; the tooltip only repeats it. The `lock` badge is CMP-079 RbacGate's (`form="tooltip"`).
 */
export const EchoReason: Story = {
  args: {
    content: REASON,
    mode: "echo",
    children: <IconButton icon="settings" label="Account settings" disabledReason={REASON} />,
  },
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Account settings" });
    await showByKeyboard();
    await expect(button).toHaveAttribute("aria-disabled", "true");
    await expect(button).toHaveAccessibleDescription(REASON);
    await expect(tooltip()).toHaveAttribute("aria-hidden", "true");
  },
};

const sideStory = (side: "right" | "bottom" | "left"): Story => ({
  args: { side },
  play: async () => {
    await showByKeyboard();
    await expect(tooltip()).toHaveAttribute("data-side", side);
  },
});
/** Beside an option in a vertical list. */
export const Right: Story = sideStory("right");
export const Bottom: Story = sideStory("bottom");
/** Not drawn (derivable, slice 1 C13). */
export const Left: Story = sideStory("left");

/** No room above: a top tooltip on a trigger at the viewport's top edge flips below, never clipped. */
export const EdgeFlip: Story = {
  render: (args) => (
    <div style={{ ...row, position: "fixed", insetBlockStart: 0, insetInlineStart: "50%" }}>
      <Tooltip {...args} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Save as" });
    await showByKeyboard();
    await expect(tooltip()).toHaveAttribute("data-side", "bottom");
    const tip = tooltip().getBoundingClientRect();
    await expect(tip.top).toBeGreaterThanOrEqual(button.getBoundingClientRect().bottom);
    await expect(tip.top).toBeGreaterThanOrEqual(0);
  },
};

const themed = (theme: string): Story => ({
  args: { content: LONG },
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
    await showByKeyboard();
  },
});
export const ContrastLight: Story = themed("light");
export const ContrastHighContrast: Story = themed("high-contrast");
