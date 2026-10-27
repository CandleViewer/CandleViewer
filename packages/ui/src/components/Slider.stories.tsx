import { useState } from "react";
import type { JSX } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { Slider, type SliderProps } from "./Slider.js";

const REASON = "Owner only: your role can't raise leverage.";
const col = { display: "grid", gap: "var(--space-inset-lg)", width: "16rem" } as const;

/** A controlled host: the slider renders server truth, so the stories own the value like a form would. */
function Host(props: SliderProps): JSX.Element {
  const [value, setValue] = useState(props.value);
  return (
    <Slider
      {...props}
      value={value}
      onChange={(next) => {
        setValue(next);
        props.onChange(next);
      }}
    />
  );
}

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof Slider> = {
  title: "Atoms/Slider",
  component: Slider,
  args: { value: 40, min: 0, max: 100, step: 5, onChange: fn(), "aria-label": "Leverage" },
  render: (args) => (
    <div style={col}>
      <Host {...args} />
    </div>
  ),
};
export default meta;
type Story = StoryObj<typeof Slider>;

const thumb = (canvasElement: HTMLElement): HTMLElement =>
  within(canvasElement).getByRole("slider", { name: "Leverage" });

export const Default: Story = {};

export const WithMarks: Story = {
  args: { marks: [0, 25, 50, 75, 100], suffix: "x" },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelectorAll(".cv-slider__mark")).toHaveLength(5);
  },
};

/** Marks that would overlap collapse to min and max (a heuristic; the count is what is pinned). */
export const CrowdedMarks: Story = {
  args: { marks: [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100] },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelectorAll(".cv-slider__mark")).toHaveLength(2);
  },
};

export const Disabled: Story = { args: { disabled: true, marks: [0, 50, 100] } };

export const DisabledWithReason: Story = {
  args: { disabledReason: REASON, marks: [0, 50, 100] },
  play: async ({ canvasElement, args }) => {
    await userEvent.tab();
    await expect(thumb(canvasElement)).toHaveFocus();
    await expect(thumb(canvasElement)).toHaveAccessibleDescription(REASON);
    await userEvent.keyboard("{ArrowRight}{PageUp}{End}");
    await expect(thumb(canvasElement)).toHaveAttribute("aria-valuenow", "40");
    await expect(args.onChange).not.toHaveBeenCalled();
  },
};

/** The states side by side, for the theme and density toolbars. */
export const AllStates: Story = {
  render: (args) => (
    <div style={col}>
      <Host {...args} aria-label="Default" />
      <Host {...args} aria-label="With marks" marks={[0, 50, 100]} />
      <Host {...args} aria-label="Disabled" disabled marks={[0, 50, 100]} />
      <Host {...args} aria-label="With a reason" disabledReason={REASON} marks={[0, 50, 100]} />
    </div>
  ),
};

export const LongSuffix: Story = {
  args: { suffix: "percent of the account equity", value: 12.5, step: 0.5, max: 25 },
  play: async ({ canvasElement }) => {
    await expect(thumb(canvasElement)).toHaveAttribute(
      "aria-valuetext",
      "12.5 percent of the account equity",
    );
  },
};

/** Gated: the thumb is text.primary on the surface and the lock is text.secondary; axe runs per theme. */
const gatedMatrix = (theme: string): Story => ({
  globals: { theme },
  args: { disabledReason: REASON, marks: [0, 50, 100] },
  play: async () => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
});
export const GatedContrastLight: Story = gatedMatrix("light");
export const GatedContrastHighContrast: Story = gatedMatrix("high-contrast");

export const FocusVisible: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(thumb(canvasElement)).toHaveFocus();
  },
};

export const Hover: Story = {
  play: async ({ canvasElement }) =>
    userEvent.hover(canvasElement.querySelector<HTMLElement>(".cv-slider__rail") as HTMLElement),
};

export const KeyboardSteps: Story = {
  args: { marks: [0, 100] },
  play: async ({ canvasElement, args }) => {
    await userEvent.tab();
    await userEvent.keyboard("{ArrowRight}");
    await expect(thumb(canvasElement)).toHaveAttribute("aria-valuenow", "45");
    await userEvent.keyboard("{PageDown}");
    await expect(thumb(canvasElement)).toHaveAttribute("aria-valuenow", "0");
    await userEvent.keyboard("{End}");
    await expect(thumb(canvasElement)).toHaveAttribute("aria-valuenow", "100");
    await expect(args.onChange).toHaveBeenLastCalledWith(100);
  },
};

/** Pointer-down on the rail jumps the thumb: the single-pointer alternative to dragging (WCAG 2.5.7). */
export const RailJump: Story = {
  play: async ({ canvasElement }) => {
    const rail = canvasElement.querySelector<HTMLElement>(".cv-slider__rail") as HTMLElement;
    const box = rail.getBoundingClientRect();
    await userEvent.pointer({
      keys: "[MouseLeft]",
      target: rail,
      coords: { clientX: box.left + box.width * 0.8, clientY: box.top + box.height / 2 },
    });
    await expect(thumb(canvasElement)).toHaveAttribute("aria-valuenow", "80");
    await expect(thumb(canvasElement)).toHaveFocus();
  },
};
