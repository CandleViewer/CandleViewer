import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor } from "storybook/test";
import { PnLBadge } from "./PnLBadge.js";

/** E29-D04 board 03's figures, in USDT (the fixture accounts' unit). */
const meta: Meta<typeof PnLBadge> = {
  title: "Trading/PnLBadge",
  component: PnLBadge,
  args: { value: "8", places: 2, format: "currency", currency: "USDT" },
};
export default meta;
type Story = StoryObj<typeof PnLBadge>;

const row = { display: "flex", gap: "var(--space-inset-md)", alignItems: "center" } as const;
const col = { display: "grid", gap: "var(--space-inset-sm)", justifyItems: "start" } as const;

/** The one sentence assistive technology reads, and no `aria-label` anywhere (E29-D04 §2.3). */
const reads = async (canvas: HTMLElement, sentence: string): Promise<void> => {
  const badge = canvas.querySelector<HTMLElement>('[data-cmp="CMP-116"]');
  await expect(badge?.querySelector(".cv-visually-hidden")).toHaveTextContent(sentence);
  await expect(canvas.querySelector("[aria-label]")).toBeNull();
};

/** `CMP-116/bar-profit`: "+8.00 USDT", the bar in `color.buy.default`, read "profit 8.00 USDT". */
export const Profit: Story = {
  play: async ({ canvasElement }) => reads(canvasElement, "profit 8.00 USDT"),
};

/** `CMP-116/bar-loss`: "−121.50 USDT" (U+2212), the bar in `color.sell.default`. */
export const Loss: Story = {
  args: { value: "-121.5" },
  play: async ({ canvasElement }) => reads(canvasElement, "loss 121.50 USDT"),
};

/** `CMP-116/bar-flat`: zero is unsigned, the bar in `color.neutral.default`. */
export const Flat: Story = {
  args: { value: "0" },
  play: async ({ canvasElement }) => reads(canvasElement, "0.00 USDT"),
};

/** A grid cell: the header carries the unit ("uPnL (USDT)"), the reading still names it (E29-D02:184). */
export const InCell: Story = {
  args: { value: "8", format: "abs", currency: "USDT" },
  play: async ({ canvasElement }) => reads(canvasElement, "profit 8.00 USDT"),
};

/** The R column: "+0.32", signed by side by the server or the host (E29-D02:185). */
export const RMultiple: Story = {
  args: { value: "0.32", format: "r", places: 2 },
  play: async ({ canvasElement }) => reads(canvasElement, "profit 0.32 R"),
};

/** `CMP-116/r-null`: no stop on the row, "—" read as "R unavailable: no stop price"; no bar. */
export const RNull: Story = {
  args: { value: null, format: "r" },
  play: async ({ canvasElement }) => {
    await reads(canvasElement, "R unavailable: no stop price");
    await expect(canvasElement.querySelector(".cv-pnl-badge__bar")).toBeNull();
  },
};

export const Percent: Story = {
  args: { value: "-1.255", format: "pct", places: 2 },
  play: async ({ canvasElement }) => reads(canvasElement, "loss 1.26%"),
};

/** The three digit steps, `type.num.sm`, `type.num.base` and `type.num.md`. */
export const Sizes: Story = {
  render: () => (
    <div style={row}>
      <PnLBadge value="8" places={2} format="currency" currency="USDT" size="sm" />
      <PnLBadge value="8" places={2} format="currency" currency="USDT" size="md" />
      <PnLBadge value="8" places={2} format="currency" currency="USDT" size="lg" />
    </div>
  ),
};

/** Numerals never truncate (E29-D02 D-8): the badge widens, grouped, exact beyond a double's digits. */
export const LongText: Story = {
  args: { value: "-123456789012.345", places: 2 },
  play: async ({ canvasElement }) => reads(canvasElement, "loss 123,456,789,012.35 USDT"),
};

const strip = (
  <div style={col}>
    <PnLBadge value="8" places={2} format="abs" currency="USDT" />
    <PnLBadge value="-121.5" places={2} format="abs" currency="USDT" />
    <PnLBadge value="0" places={2} format="abs" currency="USDT" />
  </div>
);

/** `CMP-116/strip-greyscale`: under the a11y addon's achromatopsia filter the bars lose their hue, the sign stays. */
export const Greyscale: Story = {
  globals: { vision: "achromatopsia" },
  render: () => strip,
};

/** `CMP-116/strip-deuteranopia`: the bars as a deuteranope sees them; the sign carries the direction. */
export const Deuteranopia: Story = {
  globals: { vision: "deuteranopia" },
  render: () => strip,
};

/** Every state under the light and high-contrast themes; axe checks each theme. */
const themeMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: () => (
    <div style={row}>
      <PnLBadge value="8" places={2} format="currency" currency="USDT" />
      <PnLBadge value="-121.5" places={2} format="currency" currency="USDT" />
      <PnLBadge value="0" places={2} format="currency" currency="USDT" />
      <PnLBadge value="0.32" places={2} format="r" />
      <PnLBadge value={null} format="r" />
    </div>
  ),
});
export const ContrastLight: Story = themeMatrix("light");
export const ContrastHighContrast: Story = themeMatrix("high-contrast");
