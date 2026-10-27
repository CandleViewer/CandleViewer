import type { Meta, StoryObj } from "@storybook/react-vite";
import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import { expect, waitFor, within } from "storybook/test";
import { Sparkline } from "./Sparkline.js";
import { Text } from "./Typography.js";

/** Deterministic samples: a gentle ramp with a fixed wobble, so every run draws the same line. */
const series = (n: number, from: number, to: number): number[] =>
  Array.from(
    { length: n },
    (_, i) => from + ((to - from) * i) / (n - 1) + (i % 3 === 1 ? (to - from) * 0.08 : 0),
  );
const UP = [...series(19, 100, 103.2), 103.2];
const DOWN = [...series(19, 100, 96.8), 96.8];
const FLAT = [...series(19, 100, 100.04), 100];

const row = { display: "flex", alignItems: "center", gap: "var(--space-inset-sm)" } as const;
const col = { display: "grid", gap: "var(--space-inset-sm)", justifyItems: "start" } as const;

/** Theme and density come from the toolbars; the light and high-contrast stories pin the theme for axe. */
const meta: Meta<typeof Sparkline> = {
  title: "Atoms/Sparkline",
  component: Sparkline,
  args: { data: UP },
};
export default meta;
type Story = StoryObj<typeof Sparkline>;

export const Uptrend: Story = {
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("img", { name: "up 3.2% over 20 bars" }),
    ).toBeTruthy();
  },
};
export const UptrendColorBySign: Story = { args: { colorBySign: true } };

export const Downtrend: Story = {
  args: { data: DOWN },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("img", { name: "down 3.2% over 20 bars" }),
    ).toBeTruthy();
  },
};
export const DowntrendColorBySign: Story = { args: { data: DOWN, colorBySign: true } };

/** E22: a 0.04 % wobble draws near-flat inside the ±0.5 % floor, not as full-height noise. */
export const Flat: Story = {
  args: { data: FLAT },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("img", { name: "unchanged over 20 bars" }),
    ).toBeTruthy();
  },
};
export const FlatColorBySign: Story = { args: { data: FLAT, colorBySign: true } };

/** Below two points there is no trend; nothing breaks. */
export const Empty: Story = { args: { data: [] } };
export const SinglePoint: Story = { args: { data: [100] } };

/** The host sets the box; the 1.5 px stroke never scales. */
export const Sized: Story = { args: { width: 256, height: 64, colorBySign: true } };

/** In a watchlist-style row: the row's text names the symbol, the sparkline its trend. */
export const InRow: Story = {
  render: () => (
    <div style={row}>
      <Text>BTCUSDT</Text>
      <Sparkline data={UP} colorBySign />
    </div>
  ),
};

const All: Story = {
  render: () => (
    <div style={col}>
      {[UP, DOWN, FLAT].map((data, i) => (
        <div key={i} style={row}>
          <Sparkline data={data} />
          <Sparkline data={data} colorBySign />
        </div>
      ))}
    </div>
  ),
};

const themed = (theme: string): Story => ({
  ...All,
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
});
export const Light: Story = themed("light");
export const HighContrast: Story = themed("high-contrast");

const BUDGET_MS = 16.6;
const POINTS = Array.from({ length: 200 }, (_, i) => 100 + Math.sin(i / 7) * 2 + i / 50);

/**
 * The 200-point timing check: the median of 30 warmed re-renders of a 200-point sparkline (summary, floor,
 * points and the DOM commit) stays within one frame. Tagged `perf`: a wall-clock budget is no pass/fail
 * check on a shared runner, so the storybook project skips it (#269) unless `CV_STORYBOOK_PERF=1`.
 */
export const Perf200Points: Story = {
  tags: ["perf"],
  args: { data: POINTS, width: 256, height: 64 },
  play: async ({ canvasElement }) => {
    const host = canvasElement.appendChild(document.createElement("div"));
    const root = createRoot(host);
    const samples: number[] = [];
    for (let i = 0; i < 35; i += 1) {
      const data = POINTS.map((v) => v + i / 100);
      const start = performance.now();
      flushSync(() => root.render(<Sparkline data={data} width={256} height={64} />));
      samples.push(performance.now() - start);
    }
    root.unmount();
    host.remove();
    const median = samples.slice(5).sort((a, b) => a - b)[15] ?? Infinity;
    await expect(median).toBeLessThan(BUDGET_MS);
  },
};
