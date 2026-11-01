import type { Meta, StoryObj } from "@storybook/react-vite";
import type { JSX } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import {
  RecorderStatusRow,
  recorderStatusColumns,
  type RecorderStatusRowData,
  type RecorderStatusRowProps,
} from "./RecorderStatusRow.js";
import { Table } from "./Table.js";

/** E16-D02 §1's sample rows (illustrative values, not a capture) on the host's clock, 2026-10-20 10:31:02 UTC. */
const NOW = Date.UTC(2026, 9, 20, 10, 31, 2);
const ETH: RecorderStatusRowProps = {
  symbol: "ETHUSDT",
  reason: "manual",
  state: "recording",
  startedAt: "2026-09-04T08:00:00Z",
  depth: 200,
  diskUsageBytes: 15.6e9,
  dailyGrowthBytes: 0.52e9,
  retentionDays: 30,
  pinned: false,
  now: NOW,
  onStop: fn(),
  onKeepRecording: fn(),
  onRecordAgain: fn(),
  onTogglePin: fn(),
  onOpenDetail: fn(),
  onWhyOpen: fn(),
};
const BTC = {
  symbol: "BTCUSDT",
  startedAt: "2026-09-01T09:00:00Z",
  diskUsageBytes: 34.8e9,
} as const;
const PINNED = { ...BTC, dailyGrowthBytes: 0.71e9, pinned: true, retentionDays: null } as const;
const SOL = {
  symbol: "SOLUSDT",
  reason: "chart_open",
  startedAt: "2026-10-20T10:14:00Z",
  depth: 50,
  diskUsageBytes: 1.3e6,
  dailyGrowthBytes: 0.11e9,
  growthEstimated: true,
  why: "SOLUSDT's chart has been open since 10:13 UTC; recording started 60 s later, at 10:14. It stops 30 min after the last SOLUSDT chart closes. Data is kept for 30 days.",
} as const;
const DOGE = {
  ...SOL,
  symbol: "DOGEUSDT",
  state: "refused",
  startedAt: null,
  symbolLimit: 20,
} as const;

/** SCR-140's grid around one table-variant row (B-5309-06): CMP-049 in grid mode, the row on its `renderRow`. */
function Grid(row: RecorderStatusRowData): JSX.Element {
  return (
    <Table
      columns={recorderStatusColumns()}
      rows={[row]}
      rowKey={(r) => r.symbol}
      caption="Recorded symbols"
      captionHidden
      renderRow={(data, grid) => <RecorderStatusRow {...data} variant="table" grid={grid} />}
    />
  );
}

/** The UI face alone, never a font size: the grid's widths are `em` of the root's 16 px, as in the app. */
const FONT = "var(--type-ui-body-font-family), system-ui, sans-serif";

const meta: Meta<typeof RecorderStatusRow> = {
  title: "Molecules/RecorderStatusRow",
  component: RecorderStatusRow,
  args: ETH,
  // D02 §1's 1440 x 900 content width: 1152 px, the nine columns' 72 em.
  decorators: [
    (Story) => (
      <div style={{ width: "72em", fontFamily: FONT }}>
        <Story />
      </div>
    ),
  ],
  // The table variant (D02H table 1); ReadOnly and Standalone draw the card.
  render: (args) => <Grid {...args} />,
};
export default meta;
type Story = StoryObj<typeof RecorderStatusRow>;
type Play = NonNullable<Story["play"]>;
const card: Story["render"] = (args) => <RecorderStatusRow {...args} />;

const shows =
  (...texts: string[]): Play =>
  async ({ canvasElement }) => {
    for (const text of texts) await expect(within(canvasElement).getByText(text)).toBeVisible();
  };
const button = (canvasElement: HTMLElement, name: string): HTMLElement =>
  within(canvasElement).getByRole("button", { name });

/** A T2 Stop (D02 §10.5): the lock leads its full label, focus shows the echo (2b) as board 20 draws it. */
const blocked =
  (name: string, reason: string): Play =>
  async ({ canvasElement, args }) => {
    const stop = button(canvasElement, `Not available ${name}`);
    await expect(stop).toHaveAttribute("aria-disabled", "true");
    await expect(stop).toHaveAccessibleDescription(reason);
    stop.focus();
    await userEvent.keyboard("{Enter}");
    await expect(stop).toHaveFocus();
    await expect(args.onStop).not.toHaveBeenCalled();
  };

/** A refused start (an `idle` entry): no switch and no action, Keep forever and Retention a dash. */
const refused =
  (words: string): Play =>
  async (context) => {
    await shows(words)(context);
    await expect(within(context.canvasElement).queryByRole("switch")).toBeNull();
    await expect(within(context.canvasElement).getAllByText("—")).toHaveLength(5);
  };

/** CMP-177 · State=recording: a manual symbol; Stop asks for its confirmation (D02 §6.2). */
export const Recording: Story = {
  play: async (context) => {
    await shows("Recording", "15.6 GB · 0.52/d", "30 d")(context);
    await userEvent.click(button(context.canvasElement, "Stop recording ETHUSDT"));
    await expect(context.args.onStop).toHaveBeenCalledTimes(1);
  },
};

/** State=stopped: the data kept per retention, "gone by" the stop plus 30 days; Record again. */
export const Stopped: Story = {
  args: {
    symbol: "ADAUSDT",
    state: "stopped",
    stoppedAt: "2026-10-18T12:00:00Z",
    diskUsageBytes: 11e9,
  },
  play: async (context) => {
    await shows("Stopped 18 Oct · gone by 17 Nov", "11.0 GB")(context);
    await userEvent.click(button(context.canvasElement, "Record ADAUSDT again"));
    await expect(context.args.onRecordAgain).toHaveBeenCalledTimes(1);
  },
};

/** Pinned=true: keep forever, Retention "Forever". */
export const Pinned: Story = {
  args: PINNED,
  play: async (context) => {
    await shows("Forever", "34.8 GB · 0.71/d")(context);
    const keep = within(context.canvasElement).getByRole("switch", {
      name: "Keep BTCUSDT data forever",
    });
    await expect(keep).toHaveAttribute("aria-checked", "true");
  },
};

/** Disk=near (level 1): the Size adds the share of the budget in words. */
export const NearDiskBudget: Story = {
  args: { ...PINNED, diskLevel: 1, budgetShare: 0.17 },
  play: shows("34.8 GB · 0.71/d · 17 % of budget"),
};

/** Reason=chart_open: Stop T2 `recorder.stop_blocked.chart_auto`. */
export const AutoChartOpen: Story = {
  args: { ...SOL, stopBlockedReason: "chart_open", onStop: fn() },
  play: blocked("Stop recording SOLUSDT", "Recording stops 30 min after the last chart closes."),
};

/** Reason=position_open: "Recording · position", Stop T2 `recorder.stop_blocked.position_auto` (INV-B11-a). */
export const AutoPositionOpen: Story = {
  args: {
    ...SOL,
    symbol: "XRPUSDT",
    reason: "position_open",
    stopBlockedReason: "position_open",
    onStop: fn(),
    depth: 200,
    diskUsageBytes: 6.9e6,
    growthEstimated: false,
  },
  play: blocked("Stop recording XRPUSDT", "Recording continues while a position is open."),
};

/** A manual symbol with an open position: "Recording · position open", never Gated. */
export const ManualWithPosition: Story = {
  args: { stopBlockedReason: "position_open", onStop: fn() },
  play: async (context) => {
    await shows("Recording · position open")(context);
    await blocked(
      "Stop recording ETHUSDT",
      "Stop is unavailable while a position is open.",
    )(context);
  },
};

/** D02 §3 `paused` (board 04): retention accelerated, so the Retention cell reads both figures. */
export const AcceleratedRetention: Story = {
  args: { diskLevel: 2, budgetShare: 0.08, retentionAcceleratedDays: 15 },
  play: shows("30 d → 15 d (accelerated)", "15.6 GB · 0.52/d · 8 % of budget"),
};

/** State=lingering: "stops in 24 min" (whole minutes, rounded up); Keep recording. */
export const Lingering: Story = {
  args: { ...SOL, state: "lingering", lingerUntil: new Date(NOW + 23.5 * 60e3).toISOString() },
  play: async (context) => {
    await shows("Recording · stops in 24 min")(context);
    await userEvent.click(button(context.canvasElement, "Keep recording SOLUSDT"));
    await expect(context.args.onKeepRecording).toHaveBeenCalledTimes(1);
  },
};

/** State=starting: the spinner, Since and Size a dash; Stop stays enabled. */
export const Starting: Story = {
  args: { state: "starting", startedAt: null },
  play: shows("Starting · initial book snapshot"),
};

/** State=degraded: a stream unhealthy, the gap count secondary. */
export const Degraded: Story = {
  args: { state: "degraded", gapCount: 2 },
  play: shows("Degraded · stream unhealthy · 2 gaps in 24 h"),
};

/** State=gated: the write gate closed, never plain "Recording" (C-2.14). */
export const Gated: Story = { args: { state: "gated" }, play: shows("Gated · data dropped") };

/** State=refused, Refusal=symbol_cap: the {limit} from `policy.max_symbols`. */
export const RefusedSymbolCap: Story = {
  args: { ...DOGE, refusal: "symbol_cap" },
  play: refused("Not recording: 20-symbol limit reached"),
};

/** State=refused, Refusal=disk_pressure: a level-2 refusal. */
export const RefusedDiskPressure: Story = {
  args: { ...DOGE, refusal: "disk_pressure" },
  play: refused("Not recording: disk nearly full"),
};

/** State=silent: no write for 60 s or more. */
export const Silent: Story = {
  args: { state: "silent", lastEventAt: "2026-10-20T10:29:40Z" },
  play: shows("No writes since 10:29:40"),
};

/** State=error: the error text lives in the row detail; Stop waits for the retry (B11). */
export const Errored: Story = {
  name: "Error",
  args: { state: "error" },
  play: shows("Error · retrying"),
};

/** State=stopping: flushing, no action. */
export const Stopping: Story = {
  args: { state: "stopping" },
  play: async (context) => {
    await shows("Stopping · flushing to disk")(context);
    await expect(
      within(context.canvasElement).queryByRole("button", { name: /recording/ }),
    ).toBeNull();
  },
};

/** WriteReason=owner_only (standalone, SCR-103): every write T2 through CMP-079, one notice for all. */
export const ReadOnly: Story = {
  args: { ...SOL, writeReason: "rbac.owner_only" },
  render: card,
  play: async ({ canvasElement, args }) => {
    const notice = "Read-only — only the owner can change recording.";
    await expect(within(canvasElement).getByText(notice)).toBeVisible();
    const stop = button(canvasElement, "Not available Stop recording SOLUSDT");
    const keep = within(canvasElement).getByRole("switch", { name: /Keep SOLUSDT data forever/ });
    await expect(stop).toHaveAccessibleDescription(notice);
    await expect(keep).toHaveAccessibleDescription(notice);
    await userEvent.click(keep);
    await expect(args.onTogglePin).not.toHaveBeenCalled();
  },
};

/** Variant=standalone (SCR-103): a group of Tab stops, Why? → Keep forever → the action. */
export const Standalone: Story = {
  args: PINNED,
  render: card,
  play: async ({ canvasElement }) => {
    const group = within(canvasElement).getByRole("group", { name: "BTCUSDT recording" });
    await expect(group).toHaveAccessibleDescription(
      "BTCUSDT, manual, recording since 1 Sep 2026, 34.8 GB, keep forever on",
    );
    await userEvent.tab();
    await userEvent.tab();
    await expect(within(group).getByRole("switch")).toHaveFocus();
  },
};

/** Stale=true: no `recorder` frame for 2 s; the words kept on the sunken row with a "stale" tag. */
export const Stale: Story = { args: { stale: true }, play: shows("Recording", "stale") };

/** The light and high-contrast themes (D-5309-13): rows, a T2 Stop, the share, the read-only card; axe checks each. */
const themed = (theme: "light" | "high-contrast"): Story => ({
  globals: { theme },
  render: (args) => (
    <>
      <Grid {...args} diskLevel={1} budgetShare={0.08} stale />
      <Grid {...args} {...SOL} stopBlockedReason="chart_open" />
      <RecorderStatusRow {...ETH} {...SOL} writeReason="rbac.owner_only" />
    </>
  ),
  // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
  play: async () =>
    waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme)),
});
export const ContrastLight: Story = themed("light");
export const ContrastHighContrast: Story = themed("high-contrast");

/** The action under the pointer: the ghost fill (CMP-001). */
export const Hover: Story = {
  play: async ({ canvasElement }) =>
    userEvent.hover(button(canvasElement, "Stop recording ETHUSDT")),
};

/**
 * Keyboard focus on the action, reached as the grid's keys reach it (B-5309-06): Tab onto the grid's one stop, End to
 * the row's Action cell, Enter into its control (CMP-049's interactive cell); the CMP-039 ring on Stop.
 */
export const FocusVisible: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await userEvent.keyboard("{End}{Enter}");
    await expect(button(canvasElement, "Stop recording ETHUSDT")).toHaveFocus();
  },
};
