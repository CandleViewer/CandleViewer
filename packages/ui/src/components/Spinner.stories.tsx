import type { Meta, StoryObj } from "@storybook/react-vite";
import type { JSX } from "react";
import { expect, waitFor } from "storybook/test";
import { Spinner } from "./Spinner.js";

/** Theme and density come from the toolbars; md follows the density's control height. */
const meta: Meta<typeof Spinner> = {
  title: "Atoms/Spinner",
  component: Spinner,
  args: { label: "Loading positions" },
};
export default meta;
type Story = StoryObj<typeof Spinner>;

const row = { display: "flex", gap: "var(--space-inset-lg)", alignItems: "center" } as const;
const pair = (): JSX.Element => (
  <div style={row}>
    <Spinner size="sm" label="Loading orders" />
    <Spinner size="md" label="Loading positions" />
  </div>
);

/**
 * Paints the rendered arc (its computed stroke) to a canvas, unrotated, and reports ink at four points on the
 * circle: 45, 135, 225 and 315 degrees from the path start (3 o'clock, clockwise). A 270-degree arc has ink at the
 * first three and its gap at the fourth; a full circle or a wrong dash fails.
 */
async function inkAround(arc: Element): Promise<boolean[]> {
  const circle = arc.querySelector("circle") ?? arc;
  const size = arc.getBoundingClientRect().width;
  const style = getComputedStyle(circle);
  const clone = arc.cloneNode(true) as SVGSVGElement;
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(size));
  clone.setAttribute("height", String(size));
  const paint = clone.querySelector("circle");
  for (const prop of ["fill", "stroke", "stroke-width", "stroke-dasharray", "vector-effect"])
    paint?.setAttribute(prop, style.getPropertyValue(prop));
  const img = new Image();
  img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(new XMLSerializer().serializeToString(clone))}`;
  await img.decode();
  const scale = 4;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size * scale;
  const ctx = canvas.getContext("2d");
  if (ctx === null) throw new Error("no 2d context");
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  const centre = canvas.width / 2;
  const radius = 0.375 * canvas.width;
  return [45, 135, 225, 315].map((deg) => {
    const rad = (deg * Math.PI) / 180;
    const x = Math.round(centre + radius * Math.cos(rad));
    const y = Math.round(centre + radius * Math.sin(rad));
    return (ctx.getImageData(x, y, 1, 1).data[3] ?? 0) > 128;
  });
}

/** Standalone: a polite status region that speaks its label. */
export const Labelled: Story = {};

/** sm (size.icon) and md (size.control.height), both standalone. */
export const Sizes: Story = {
  render: pair,
  play: async ({ canvasElement }) => {
    const arcs = canvasElement.querySelectorAll(".cv-spinner__arc");
    await expect(arcs).toHaveLength(2);
    // Both sizes draw a 270-degree arc with a quarter gap (the dash follows pathLength).
    for (const arc of arcs) await expect(await inkAround(arc)).toEqual([true, true, true, false]);
  },
};

/** Nested and decorative: no label, aria-hidden, inside a host that is itself busy and named. */
export const Decorative: Story = {
  render: () => (
    <div role="status" aria-busy="true" style={row}>
      <Spinner size="sm" />
      <span>Loading fills</span>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const spinner = canvasElement.querySelector(".cv-spinner");
    await expect(spinner).toHaveAttribute("aria-hidden", "true");
    await expect(spinner?.closest('[aria-busy="true"]')).not.toBeNull();
  },
};

/** One turn per 800 ms while motion is allowed. */
export const MotionSafe: Story = {
  globals: { motion: "off" },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-motion", "safe"));
    const style = getComputedStyle(
      canvasElement.querySelector(".cv-spinner__arc") ?? canvasElement,
    );
    await expect(style.animationName).toBe("cv-spin");
    await expect(style.animationDuration).toBe("0.8s");
  },
};

/** Reduced motion (the in-app override): no rotation, a static arc. */
export const ReducedMotion: Story = {
  globals: { motion: "on" },
  render: pair,
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-motion", "reduce"));
    for (const arc of canvasElement.querySelectorAll(".cv-spinner__arc"))
      await expect(getComputedStyle(arc).animationName).toBe("none");
  },
};

const themed = (theme: string): Story => ({
  globals: { theme },
  render: pair,
  play: async () => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
});
export const ThemeLight: Story = themed("light");
export const ThemeHighContrast: Story = themed("high-contrast");
