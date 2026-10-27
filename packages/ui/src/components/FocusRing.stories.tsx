import type { Meta, StoryObj } from "@storybook/react-vite";
import type { JSX } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { useFocusRing, type FocusRingOptions } from "./FocusRing.js";

/** CMP-039 is a utility: `useFocusRing({ inset? })` returns `{ className }`, shown on a plain sample. Press Tab. */
function Sample({ inset = false, children }: FocusRingOptions & { children: string }): JSX.Element {
  const ring = useFocusRing({ inset });
  return (
    <button
      type="button"
      className={ring.className}
      style={{
        minHeight: "var(--size-control-height)",
        padding: "0 var(--space-inset-md)",
        border: 0,
        borderRadius: "var(--radius-control)",
        background: "var(--color-surface-raised)",
        color: "var(--color-text-primary)",
        font: "inherit",
        width: inset ? "100%" : undefined,
        textAlign: "start",
      }}
    >
      {children}
    </button>
  );
}

/** The inset ring's home: a full-width item inside a scrolling list, which would clip an outside ring. */
const list = {
  display: "grid",
  width: "16rem",
  maxHeight: "6rem",
  overflow: "auto",
  background: "var(--color-surface-overlay)",
  borderRadius: "var(--radius-control)",
} as const;

const meta: Meta<typeof Sample> = {
  title: "Atoms/FocusRing",
  component: Sample,
  args: { children: "Sample control" },
};
export default meta;
type Story = StoryObj<typeof Sample>;

const ringOf = (el: Element): CSSStyleDeclaration => getComputedStyle(el);

/** Outside the element, 2px clear of it, on keyboard focus. */
export const Normal: Story = {
  play: async ({ canvasElement }) => {
    const sample = within(canvasElement).getByRole("button", { name: "Sample control" });
    await userEvent.tab();
    await expect(sample.matches(":focus-visible")).toBe(true);
    const ring = ringOf(sample);
    await expect(ring.outlineStyle).toBe("solid");
    // The 2px offset constant equals the border.focus width: the ring sits one ring-width clear.
    await expect(ring.outlineOffset).toBe(ring.outlineWidth);
  },
};

/** Inside the item's bounds (H8), so the scrolling list never clips it. */
export const Inset: Story = {
  render: () => (
    <div style={list}>
      {["Reveal on chart", "Copy price", "Add alert"].map((label) => (
        <Sample key={label} inset>
          {label}
        </Sample>
      ))}
    </div>
  ),
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    const ring = ringOf(within(canvasElement).getByRole("button", { name: "Reveal on chart" }));
    await expect(ring.outlineStyle).toBe("solid");
    await expect(ring.outlineOffset).toBe(`-${ring.outlineWidth}`);
  },
};

const themed = (theme: string): Story => ({
  globals: { theme },
  render: (args) => (
    <div style={list}>
      <Sample {...args} />
      <Sample inset>Inset item</Sample>
    </div>
  ),
  play: async () => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
    await userEvent.tab();
  },
});
export const ThemeLight: Story = themed("light");
export const ThemeHighContrast: Story = themed("high-contrast");
