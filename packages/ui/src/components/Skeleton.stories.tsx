import type { JSX, ReactNode } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";
import { Skeleton } from "./Skeleton.js";

const col = { display: "grid", gap: "var(--space-inset-lg)", width: "20rem" } as const;

/** The busy-host pattern: the host region is busy and its words carry the wait; the skeleton is hidden. */
function BusyHost({
  words,
  surface,
  children,
}: {
  words: string;
  surface?: string;
  children: ReactNode;
}): JSX.Element {
  return (
    <section
      aria-label="Positions"
      aria-busy="true"
      style={{ ...col, padding: "var(--space-inset-md)", background: surface }}
    >
      <p style={{ margin: 0, color: "var(--color-text-secondary)" }}>{words}</p>
      {children}
    </section>
  );
}

/** Theme, density and motion come from the toolbars; every state below renders at each combination. */
const meta: Meta<typeof Skeleton> = {
  title: "Atoms/Skeleton",
  component: Skeleton,
  render: (args) => (
    <BusyHost words="Loading positions…">
      <Skeleton {...args} />
    </BusyHost>
  ),
};
export default meta;
type Story = StoryObj<typeof Skeleton>;

const band = (root: HTMLElement): CSSStyleDeclaration =>
  getComputedStyle(root.querySelector(".cv-skeleton__block") as HTMLElement, "::after");

export const Default: Story = {
  play: async ({ canvasElement }) => {
    const host = within(canvasElement).getByRole("region", { name: "Positions" });
    await expect(host).toHaveAttribute("aria-busy", "true");
    await expect(canvasElement.querySelector(".cv-skeleton")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    await expect(canvasElement.querySelectorAll(".cv-skeleton__block")).toHaveLength(3);
  },
};

export const Row: Story = { args: { shape: "row", count: 4 } };

export const Card: Story = { args: { shape: "card", count: 2 } };

/** A chart-sized slot in a card or tile; a chart pane uses Skeleton-Chart (CMP-029). */
export const Chart: Story = {
  args: { shape: "chart" },
  render: (args) => (
    <BusyHost words="Loading sparkline…">
      <div style={{ height: "6rem" }}>
        <Skeleton {...args} />
      </div>
    </BusyHost>
  ),
};

export const OnOverlay: Story = {
  args: { shape: "row", count: 3, surface: "overlay" },
  render: (args) => (
    <BusyHost words="Loading details…" surface="var(--color-surface-overlay)">
      <Skeleton {...args} />
    </BusyHost>
  ),
};

/** Reduced motion: the static two-tone from the first frame (#265 "Skeleton respects reduced motion"). */
export const Static: Story = {
  args: { shape: "row", count: 3 },
  globals: { motion: "on" },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-motion", "reduce"));
    await expect(band(canvasElement).animationName).toBe("none");
    await expect(band(canvasElement).display).toBe("none");
  },
};

export const LongCount: Story = { args: { count: 12 } };

/** Every shape side by side, for the theme and density toolbars. */
export const AllShapes: Story = {
  render: () => (
    <BusyHost words="Loading…">
      <Skeleton />
      <Skeleton shape="row" count={2} />
      <Skeleton shape="card" />
      <div style={{ height: "4rem" }}>
        <Skeleton shape="chart" />
      </div>
    </BusyHost>
  ),
};

const themed = (theme: string): Story => ({
  ...AllShapes,
  globals: { theme },
  play: async () => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
});
export const Light: Story = themed("light");
export const HighContrast: Story = themed("high-contrast");
