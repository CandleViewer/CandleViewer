import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import {
  ColorSwatch,
  ColorSwatchPicker,
  type ColorSwatchOption,
  type ColorSwatchPickerBaseProps,
} from "./ColorSwatch.js";

const REASON = "Owner only: your role can't change the drawing palette.";
const LOCK_REASON = "Amber is reserved for the selected drawing.";
// Story stand-ins until the user-pickable palette lands (D02 A5): Cyan and Amber are the two drawing
// tokens; Violet and Grey borrow shipped tokens. The inverse glyph's 3:1 on all four is pinned in every
// theme by test/contrast/colorswatch-glyph.test.ts. Light Amber is 2.76:1 on surface.overlay and 3.00:1
// on surface.raised, below 1.4.11 (A5): the light story shows it on surface.app (3.45:1).
const SWATCHES: readonly ColorSwatchOption[] = [
  { value: "cyan", label: "Cyan", color: "var(--color-drawing-default)" },
  { value: "amber", label: "Amber", color: "var(--color-drawing-selected)" },
  { value: "violet", label: "Violet", color: "var(--color-node-logic)" },
  { value: "grey", label: "Grey", color: "var(--color-neutral-default)" },
];
const LOCKED: readonly ColorSwatchOption[] = [
  SWATCHES[0] as ColorSwatchOption,
  { ...(SWATCHES[1] as ColorSwatchOption), disabledReason: LOCK_REASON },
  SWATCHES[2] as ColorSwatchOption,
  { ...(SWATCHES[3] as ColorSwatchOption), disabled: true },
];

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof ColorSwatchPicker> = {
  title: "Atoms/ColorSwatch",
  component: ColorSwatchPicker,
  args: {
    "aria-label": "Line colour",
    swatches: SWATCHES,
    value: "cyan",
    onChange: fn(),
  },
};
export default meta;
type Story = StoryObj<typeof ColorSwatchPicker>;

const col = { display: "grid", gap: "var(--space-inset-lg)", justifyItems: "start" } as const;
const caption = (text: string): JSX.Element => <span>{text}</span>;

/** A host that keeps the value, so the keyboard stories show the real round trip. */
type HostProps = ColorSwatchPickerBaseProps & { readonly "aria-label": string };
function Controlled(props: HostProps): JSX.Element {
  const [value, setValue] = useState(props.value);
  return (
    <ColorSwatchPicker
      {...props}
      value={value}
      onChange={(next) => {
        setValue(next);
        props.onChange?.(next);
      }}
    />
  );
}
const controlled: Story["render"] = (args) => <Controlled {...(args as HostProps)} />;

/** The Picker (catalogue Storybook line): Cyan selected, its `check` glyph shown. */
export const Picker: Story = { render: controlled };

/** No selection: the first enabled swatch holds the tab stop. */
export const NoSelection: Story = {
  args: { value: undefined },
  render: controlled,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(within(canvasElement).getByRole("radio", { name: "Cyan" })).toHaveFocus();
  },
};

export const Hover: Story = {
  render: controlled,
  play: async ({ canvasElement }) =>
    userEvent.hover(within(canvasElement).getByRole("radio", { name: "Violet" })),
};

export const HoverSelected: Story = {
  render: controlled,
  play: async ({ canvasElement }) =>
    userEvent.hover(within(canvasElement).getByRole("radio", { name: "Cyan" })),
};

export const FocusVisible: Story = {
  render: controlled,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(within(canvasElement).getByRole("radio", { name: "Cyan" })).toHaveFocus();
  },
};

export const KeyboardNavigation: Story = {
  render: controlled,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.tab();
    await userEvent.keyboard("{ArrowRight}");
    await expect(canvas.getByRole("radio", { name: "Amber" })).toHaveFocus();
    await expect(canvas.getByRole("radio", { name: "Amber" })).toBeChecked();
    await userEvent.keyboard("{End}{ArrowRight}");
    await expect(canvas.getByRole("radio", { name: "Cyan" })).toBeChecked();
    await userEvent.keyboard("{ArrowLeft}");
    await expect(canvas.getByRole("radio", { name: "Grey" })).toHaveFocus();
    await expect(args.onChange).toHaveBeenLastCalledWith("grey");
  },
};

export const Disabled: Story = { args: { disabled: true } };

/** A swatch with a reason: arrow-reachable, never selected, true colour kept; a plain-disabled one is skipped. */
export const SwatchLocked: Story = {
  args: { swatches: LOCKED },
  render: controlled,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.tab();
    await userEvent.keyboard("{ArrowRight}");
    const locked = canvas.getByRole("radio", { name: "Amber" });
    await expect(locked).toHaveFocus();
    await expect(locked).toHaveAttribute("aria-checked", "false");
    await expect(locked).toHaveAccessibleDescription(LOCK_REASON);
    await expect(canvas.getByRole("radio", { name: "Cyan" })).toBeChecked();
    await userEvent.keyboard("{ArrowRight}{ArrowRight}");
    await expect(canvas.getByRole("radio", { name: "Cyan" })).toHaveFocus();
  },
};

/** A locked picker: the selected swatch stays the tab stop and every swatch carries the reason and a lock. */
export const PickerLocked: Story = {
  args: { disabledReason: REASON },
  play: async ({ canvasElement, args }) => {
    const swatches = within(canvasElement).getAllByRole("radio");
    await userEvent.tab();
    await expect(swatches[0]).toHaveFocus();
    await expect(swatches[0]).toHaveAccessibleDescription(REASON);
    await userEvent.keyboard("{ArrowRight}{End} ");
    await userEvent.click(swatches[2] as HTMLElement);
    await expect(args.onChange).not.toHaveBeenCalled();
    await expect(swatches[0]).toHaveAttribute("aria-checked", "true");
  },
};

/** Gated and selected: the check and the corner lock together (the combination worth seeing). */
export const LockedSelected: Story = {
  args: { swatches: LOCKED, value: "amber" },
};

/** Static (no onSelect): a named `img`, not focusable. */
export const StaticSwatch: Story = {
  render: () => <ColorSwatch color="var(--color-drawing-default)" label="Cyan" />,
  play: async ({ canvasElement }) => {
    const swatch = within(canvasElement).getByRole("img", { name: "Cyan" });
    await expect(swatch).not.toHaveAttribute("tabindex");
  },
};

/** Static beside text that names the colour: hidden from assistive technology. */
export const StaticDecorative: Story = {
  render: () => (
    <span style={{ display: "inline-flex", gap: "var(--space-inset-sm)", alignItems: "center" }}>
      <ColorSwatch color="var(--color-drawing-selected)" label="Amber" decorative />
      Amber
    </span>
  ),
};

/** Every drawn state side by side (spec matrix): picker, plain disabled, swatch lock, picker lock, static. */
export const AllStates: Story = {
  render: (args) => (
    <div style={col}>
      {caption("Picker")}
      <Controlled {...(args as HostProps)} />
      {caption("Disabled")}
      <ColorSwatchPicker {...(args as HostProps)} disabled />
      {caption("Swatch with a reason, selected and not")}
      <ColorSwatchPicker {...(args as HostProps)} swatches={LOCKED} value="amber" />
      {caption("Picker with a reason")}
      <ColorSwatchPicker {...(args as HostProps)} disabledReason={REASON} />
      {caption("Static")}
      <ColorSwatch color="var(--color-drawing-default)" label="Cyan" />
    </div>
  ),
};

/**
 * The light and high-contrast themes: axe checks each, and the swatches keep their glyph contrast.
 * `surface` is the background the pickers sit on: light Amber needs surface.app to reach 3:1 (A5).
 */
const themed = (theme: string, surface?: string): Story => ({
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: (args) => (
    <div
      style={{
        ...col,
        ...(surface === undefined ? {} : { background: surface, padding: "var(--space-inset-lg)" }),
      }}
    >
      <ColorSwatchPicker {...(args as HostProps)} />
      <ColorSwatchPicker {...(args as HostProps)} swatches={LOCKED} value="amber" />
      <ColorSwatchPicker {...(args as HostProps)} disabledReason={REASON} />
    </div>
  ),
});
export const ThemeLight: Story = themed("light", "var(--color-surface-app)");
export const ThemeHighContrast: Story = themed("high-contrast");

/** A narrow container: the picker wraps onto new rows at the same gap; the swatches never shrink. */
export const Wrapping: Story = {
  decorators: [
    (Story) => (
      <div style={{ width: "4rem" }}>
        <Story />
      </div>
    ),
  ],
  play: async ({ canvasElement }) => {
    const [first, , third] = within(canvasElement).getAllByRole("radio");
    await expect(third?.offsetTop).toBeGreaterThan(first?.offsetTop ?? 0);
    await expect(first?.offsetWidth).toBe(first?.offsetHeight);
  },
};
