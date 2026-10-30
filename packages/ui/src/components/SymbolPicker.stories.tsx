import type { Meta, StoryObj } from "@storybook/react-vite";
import type { JSX } from "react";
import { expect, fn, mocked, userEvent, waitFor, within } from "storybook/test";
import { Popover } from "./Popover.js";
import { SymbolPicker, type SymbolPickerProps } from "./SymbolPicker.js";
import { TextInput } from "./TextInput.js";

/**
 * A host, as SCR-041 composes the trigger (E08-D05 §7): a CMP-017 popover anchored on it. The host passes no
 * `expanded` and holds no state: the trigger takes the Popover's `aria-expanded` and toggle, and the popover closes
 * itself (`Esc`, a press outside, focus leaving), handing focus back to the trigger.
 */
function Host({
  open = false,
  ...props
}: SymbolPickerProps & { readonly open?: boolean }): JSX.Element {
  return (
    <Popover
      heading="Change symbol and interval"
      defaultOpen={open}
      anchor={<SymbolPicker {...props} />}
    >
      <TextInput aria-label="Search symbols" defaultValue={props.value} />
    </Popover>
  );
}

/** B02 (E08-D05 §14): Chart 1's BTCUSDT at 1 minute. Theme and density come from the toolbars. */
const meta: Meta<typeof SymbolPicker> = {
  title: "Molecules/SymbolPicker",
  component: SymbolPicker,
  args: { value: "BTCUSDT", interval: "1 minute", onOpen: fn() },
};
export default meta;
type Story = StoryObj<typeof SymbolPicker>;

const trigger = (canvasElement: HTMLElement): HTMLElement =>
  within(canvasElement).getByRole("button", { name: /^Symbol: / });

/** Rest: the value and its chevron, no chip. A click, `Enter` and `Space` each ask the host to open its dialog. */
export const Default: Story = {
  play: async ({ canvasElement, args }) => {
    const button = trigger(canvasElement);
    await expect(button).toHaveAccessibleName("Symbol: BTCUSDT, 1 minute");
    await expect(button).toHaveAttribute("aria-haspopup", "dialog");
    await expect(button).toHaveAttribute("aria-expanded", "false");
    mocked(args.onOpen).mockClear();
    await userEvent.click(button);
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    await expect(args.onOpen).toHaveBeenCalledTimes(3);
  },
};

/** The chip says "Recording", a filled dot before it, and describes the trigger. */
export const Recording: Story = {
  args: { recording: "recording" },
  play: async ({ canvasElement }) => {
    await expect(trigger(canvasElement)).toHaveAccessibleDescription("Recording");
  },
};

/** "Not recorded", a hollow dot: SCR-041's checklist row (B02, B16, B18). */
export const NotRecorded: Story = {
  args: { recording: "not-recorded" },
  play: async ({ canvasElement }) => {
    await expect(trigger(canvasElement)).toHaveAccessibleDescription("Not recorded");
  },
};

/** No chip while the state is unknown: unknown is never "not recorded" (E08-D05 §3). */
export const RecordingUnknown: Story = {
  args: { recording: "unknown" },
  play: async ({ canvasElement }) => {
    await expect(trigger(canvasElement)).not.toHaveAttribute("aria-describedby");
    await expect(within(canvasElement).queryByText(/recorded|recording/i)).toBeNull();
  },
};

/**
 * Delisted (E08-D05 §6.4, B19's entry through E11-D04's Switch symbol): the value struck, "Delisted by the exchange"
 * after ⊘ in the recording chip's place. The trigger still opens, to choose another symbol.
 */
export const Delisted: Story = {
  args: { value: "LUNAUSDT", delisted: true, recording: "not-recorded" },
  play: async ({ canvasElement, args }) => {
    const button = trigger(canvasElement);
    await expect(button).toHaveAccessibleName("Symbol: LUNAUSDT, 1 minute");
    await expect(button).toHaveAccessibleDescription("Delisted by the exchange");
    await expect(button).not.toHaveAttribute("aria-disabled");
    mocked(args.onOpen).mockClear();
    await userEvent.click(button);
    await expect(args.onOpen).toHaveBeenCalledTimes(1);
  },
};

/** Keyboard focus: one Tab stop with CMP-039's ring (in CMP-221's toolbar, its roving stop). */
export const Focus: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(trigger(canvasElement)).toHaveFocus();
  },
};

/**
 * Expanded (B02): the selected fill, `aria-expanded`, and the host's dialog below it holding focus. The host passes
 * no `expanded`: the trigger takes the Popover's state.
 */
export const Expanded: Story = {
  render: (args) => <Host {...args} open />,
  play: async ({ canvasElement }) => {
    const button = trigger(canvasElement);
    const dialog = within(document.body).getByRole("dialog", {
      name: "Change symbol and interval",
    });
    await expect(button).toHaveAttribute("aria-expanded", "true");
    await expect(button).toHaveAttribute("aria-controls", dialog.id);
    await waitFor(() => expect(within(dialog).getByRole("textbox")).toHaveFocus());
  },
};

/** A 24-character symbol (illustrative, the longest `22` allows) is drawn whole: the host's toolbar overflows it. */
export const LongSymbol: Story = {
  args: { value: "ABCDEFGHIJKLMNOPQRSTUSDT", recording: "not-recorded" },
  play: async ({ canvasElement }) => {
    const button = trigger(canvasElement);
    const value = within(button).getByText("ABCDEFGHIJKLMNOPQRSTUSDT");
    // Nothing clips it: not the value's own box, nor the trigger's, nor the root's, and it never ellipsises.
    for (const box of [value, button, button.parentElement ?? button])
      await expect(box.scrollWidth).toBeLessThanOrEqual(box.clientWidth);
    await expect(getComputedStyle(value).textOverflow).not.toBe("ellipsis");
  },
};

/** B02's frames side by side: rest, recording, not recorded, delisted and expanded. */
function Board(): JSX.Element {
  const at = { value: "BTCUSDT", interval: "1 minute", onOpen: fn() } as const;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-inset-lg)" }}>
      <SymbolPicker {...at} />
      <SymbolPicker {...at} recording="recording" />
      <SymbolPicker {...at} recording="not-recorded" />
      <SymbolPicker {...at} value="LUNAUSDT" delisted />
      <SymbolPicker {...at} expanded />
    </div>
  );
}

/** The board in a theme (dark is every other story's): axe measures each chip and fill against it. */
const themed = (theme: string): Story => ({
  globals: { theme },
  render: () => <Board />,
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
});
export const ContrastLight: Story = themed("light");
export const ContrastHighContrast: Story = themed("high-contrast");

/** Comfortable density: a 32 px trigger with `space.inset.md` padding (hand-off density table). */
export const Comfortable: Story = {
  globals: { density: "comfortable" },
  render: () => <Board />,
  play: async ({ canvasElement }) => {
    await waitFor(() =>
      expect(document.documentElement).toHaveAttribute("data-density", "comfortable"),
    );
    for (const button of within(canvasElement).getAllByRole("button"))
      await expect(button.getBoundingClientRect().height).toBe(32);
  },
};
