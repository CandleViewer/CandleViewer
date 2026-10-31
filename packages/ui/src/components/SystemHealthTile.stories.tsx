import type { Meta, StoryObj } from "@storybook/react-vite";
import type { JSX } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { KeyValueRow } from "./KeyValueRow.js";
import { SystemHealthTile } from "./SystemHealthTile.js";

/** The E42-D03 worked example's clock: 14:02:11 and 14:01:40 UTC on 2026-10-22. */
const AS_OF = Date.UTC(2026, 9, 22, 14, 2, 11);
const GOOD = Date.UTC(2026, 9, 22, 14, 1, 40);
const FONT =
  "var(--type-ui-body-font-weight) var(--type-ui-body-font-size) / var(--type-ui-body-line-height) var(--type-ui-body-font-family)";
const PROBE = { valueLabel: "probe", unit: "ms", unitSpoken: "milliseconds" } as const;
const tile = (canvas: HTMLElement, name: string): HTMLElement =>
  within(canvas).getByRole("region", { name });
const onRetry = fn();

/** About 307 px wide, a tile at 1280 (E42-D03 §6); theme and density come from the toolbars. */
const meta: Meta<typeof SystemHealthTile> = {
  title: "Molecules/SystemHealthTile",
  component: SystemHealthTile,
  args: { label: "Public WS (bybit_public_ws)", href: "#health", state: "ready", tone: "ok" },
  decorators: [
    (Story) => (
      <div style={{ maxWidth: "19rem", padding: "var(--space-inset-lg)", font: FONT }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof SystemHealthTile>;

/** E42-D05 HL-2: the word, a fresh number (its unit read in words) and its "as of". */
export const Ok: Story = { args: { stateWord: "healthy", value: 12, ...PROBE, asOf: AS_OF } };

/** E42-D03 OV-4: degraded, the triangle and "Attention:"; no reassurance on a trading fault. */
export const Warning: Story = {
  args: {
    label: "Health",
    tone: "warning",
    stateWord: "Degraded",
    detail: "bybit_private_ws reconnected 3× in the last hour",
    lastGoodAt: GOOD,
    asOf: AS_OF,
    stopsWorking: "order and position updates may lag",
  },
  play: async ({ canvasElement }) =>
    expect(tile(canvasElement, "Health")).toHaveTextContent("Attention: Degraded —"),
};

/** E42-D03 OV-5: down, the octagon. */
export const Danger: Story = {
  args: {
    label: "Audit",
    tone: "danger",
    stateWord: "Tamper check FAILED at entry 1,204,118",
    detail: "treat this as a security incident",
    asOf: AS_OF,
  },
};

/** E42-D03 OV-1: the tile's own skeleton and `aria-busy`; nothing is announced. */
export const Loading: Story = {
  args: { label: "Recorder and storage", state: "loading" },
};

/** E42-D03 OV-4: the slice answered `error`: its last good time and Retry. */
export const ErrorStory: Story = {
  name: "Error",
  args: {
    label: "Users",
    state: "error",
    detail: "timed out after 300 ms",
    lastGoodAt: GOOD,
    onRetry,
  },
  play: async ({ canvasElement }) => {
    onRetry.mockClear();
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Retry" }));
    await expect(onRetry).toHaveBeenCalledTimes(1);
  },
};

/** E42-D03 D8: a read not served or not mounted takes the down treatment, with no number. */
export const Unavailable: Story = {
  args: { label: "Profiles and limits", state: "unavailable", detail: "not built yet" },
};

/** E42-D03 OV-4: a failed re-read: the clock and "stale since". */
export const Stale: Story = {
  args: { label: "Flags", tone: "stale", staleSince: Date.UTC(2026, 9, 22, 14, 0, 2) },
};

const tradingRows = (live: boolean): JSX.Element => (
  <dl style={{ display: "grid", margin: 0 }}>
    <KeyValueRow label="Live trading" value={live ? "on" : null} missingLabel="not received" />
    <KeyValueRow label="Kill switch" value={live ? "off" : "unknown"} />
    <KeyValueRow label="Open positions" value={live ? 2 : null} missingLabel="not received" />
    <KeyValueRow label="Maintenance" value="off (flags read)" />
  </dl>
);

/** E42-D03 OV-2: Trading safety [LIVE]; the badge's word joins the region's name. */
export const WithEnvBadge: Story = {
  args: {
    label: "Trading safety",
    env: "live",
    stateWord: "ok",
    asOf: AS_OF,
    children: tradingRows(true),
  },
  play: async ({ canvasElement }) =>
    expect(tile(canvasElement, "Trading safety LIVE")).toBeVisible(),
};

/** E42-D03 OV-6 and E42-D05 HL-12: no number for a field not received. */
export const NotReceived: Story = {
  render: (args) => (
    <div style={{ display: "grid", gap: "var(--space-inset-lg)" }}>
      <SystemHealthTile
        {...args}
        label="Trading safety"
        env="live"
        state="unavailable"
        detail="trading: no provider wired"
      >
        {tradingRows(false)}
      </SystemHealthTile>
      <SystemHealthTile {...args} stateWord="healthy" value={null} {...PROBE} asOf={AS_OF} />
    </div>
  ),
  play: async ({ canvasElement }) =>
    expect(canvasElement.querySelector(".cv-health-tile__value")).toHaveTextContent(/^— not/),
};

/** E42-D05 HL-7: `not_deployed`, the ring in the neutral tone; it ranks healthy. */
export const NotDeployed: Story = {
  args: { label: "Bar writer (bars_writer)", tone: "neutral", asOf: AS_OF },
};

/** E42-D05 HL-11: a word fresh from a frame over a number with its own, older "as of". */
export const NumberStale: Story = {
  args: { stateWord: "healthy", value: 210, ...PROBE, valueAsOf: GOOD, asOf: AS_OF },
};

/** E42-D05 HL-5: down, what stops working, what is still safe, the hint and its runbook. */
export const WithHint: Story = {
  args: {
    label: "Bybit REST (bybit_rest)",
    tone: "danger",
    stateWord: "down",
    lastGoodAt: GOOD,
    stopsWorking: "no new orders; cancel/stop reserve only.",
    stillSafe: true,
    hint: "Check Exchange connectivity for rate limits or a Bybit outage; manage positions on Bybit if you must.",
    runbookHref: "#runbook",
  },
};

export const Hover: Story = {
  ...Ok,
  play: async ({ canvasElement }) => userEvent.hover(within(canvasElement).getByRole("link")),
};

/** The CMP-039 ring on the heading link, the tile's first tab stop. */
export const FocusVisible: Story = {
  ...Ok,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(within(canvasElement).getByRole("link").matches(":focus-visible")).toBe(true);
  },
};

/** E42-D05 HL-3, every line at once: it all wraps inside the tile. */
export const LongText: Story = {
  args: {
    ...WithHint.args,
    label: "Private WS (bybit_private_ws)",
    tone: "warning",
    stateWord: "Degraded",
    detail: "account a1000000… reconnected 3× in the last hour",
    value: 210,
    ...PROBE,
    stopsWorking: "order and position updates may lag; REST reconcile runs.",
    hint: "Check the account's link on Exchange connectivity; reconnects run by themselves.",
    onRetry,
  },
  play: async ({ canvasElement }) => {
    const region = tile(canvasElement, "Private WS (bybit_private_ws)");
    await expect(region.scrollWidth).toBeLessThanOrEqual(region.clientWidth);
  },
};
