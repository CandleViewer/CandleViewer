import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import { FundingCountdown } from "./FundingCountdown.js";
import { Text } from "./Typography.js";

/** The settlement D06 §7 draws: 08:00 UTC, and a frozen clock 5,053,771 ms before it (the recorded frame). */
const HOUR_AHEAD = Date.UTC(2026, 9, 27, 8, 0, 0);
const T0 = HOUR_AHEAD - 5_053_771;
const frozen = (): number => T0;
const at = (ms: number): number => T0 + ms;

/** Static text with no hover or press of its own; focus never lands here. Theme and density come from the toolbars. */
const meta: Meta<typeof FundingCountdown> = {
  title: "Atoms/FundingCountdown",
  component: FundingCountdown,
  args: { symbol: "BTCUSDT", nextFundingTimeMs: HOUR_AHEAD, now: frozen },
  render: (args) => (
    <Text variant="body" as="p">
      Next funding <FundingCountdown {...args} />
    </Text>
  ),
};
export default meta;
type Story = StoryObj<typeof FundingCountdown>;

const root = (canvas: HTMLElement): HTMLElement => {
  const node = canvas.querySelector<HTMLElement>("[data-cmp='CMP-126']");
  if (node === null) throw new Error("no CMP-126");
  return node;
};

/** At least an hour out: fixed-width digits and the UTC time; the twin reads the words, nothing speaks per tick. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    await expect(root(canvasElement)).toHaveAttribute("data-state", "ahead");
    await expect(canvasElement.querySelector(".cv-funding__digits")).toHaveTextContent(
      "next in 01:24:13 · 08:00 UTC",
    );
    await expect(
      within(canvasElement).getByText("Next funding in 1 hour 24 minutes, at 08:00 UTC"),
    ).toBeTruthy();
    await expect(within(canvasElement).getByRole("status")).toBeEmptyDOMElement();
  },
};

/** Under an hour: the same form, 00:59:59. */
export const UnderOneHour: Story = {
  args: { nextFundingTimeMs: at(59 * 60_000 + 59_000) },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector(".cv-funding__digits")).toHaveTextContent(
      "next in 00:59:59",
    );
  },
};

/** Under 5 minutes: "settles in" after a warning glyph; the words carry it, not the colour. */
export const Settling: Story = {
  args: { nextFundingTimeMs: at(4 * 60_000 + 12_000) },
  play: async ({ canvasElement }) => {
    await expect(root(canvasElement)).toHaveAttribute("data-state", "settling");
    await expect(canvasElement.querySelector(".cv-funding__digits")).toHaveTextContent(
      "settles in 00:04:12",
    );
    await expect(canvasElement.querySelector(".cv-funding__warn svg")).toBeTruthy();
  },
};

/** Under one minute. */
export const UnderOneMinute: Story = {
  args: { nextFundingTimeMs: at(42_000) },
};

/** The settlement passed and no fresh ticker: it says so, once, politely, and waits. */
export const Elapsed: Story = {
  args: { nextFundingTimeMs: at(-1_000) },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getAllByText("Settlement time passed — waiting for an update").length,
    ).toBeGreaterThan(0);
  },
};

/** `next_funding_time_ms` absent: no countdown, no seconds. */
export const Unknown: Story = {
  args: { nextFundingTimeMs: undefined },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Next funding time not available")).toBeTruthy();
  },
};

/** The symbol is not trading: the sentence alone. A long symbol wraps rather than clipping. */
export const NotTrading: Story = {
  args: { notTrading: true },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByText("No funding — BTCUSDT is not trading."),
    ).toBeTruthy();
  },
};

export const LongText: Story = {
  args: { notTrading: true, symbol: "1000000BABYDOGEUSDT-PERPETUAL-CONTRACT-EXAMPLE" },
  decorators: [
    (Story) => (
      <div style={{ maxWidth: "12rem" }}>
        <Story />
      </div>
    ),
  ],
};

/** The clock alarm is on: the absolute time and the skew line replace the count. */
export const ClockAlarm: Story = {
  args: { clockAlarm: true, clockSkewMs: 612 },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByText("at 08:00:00 UTC (in about 1 h 24 min)"),
    ).toBeTruthy();
    await expect(
      within(canvasElement).getAllByText("Clock skew 612 ms — the countdown may be off").length,
    ).toBeGreaterThan(0);
  },
};

/** The offset is unknown: the absolute time alone. */
export const ClockAlarmUnknownOffset: Story = {
  args: { clockAlarm: true },
};

/** The rate's sign is a character as well as a colour: "+0.0100%". */
export const Positive: Story = { args: { rate: "0.0100%" } };
export const Negative: Story = { args: { rate: "−0.0050%" } };
export const Zero: Story = { args: { rate: "0.0000%" } };
