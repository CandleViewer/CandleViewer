import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, fn, mocked, userEvent, waitFor, within } from "storybook/test";
import { FormField } from "./FormField.js";
import {
  MetricPickerCombobox,
  type MetricCategory,
  type MetricPickerComboboxProps,
  type MetricPickerOption,
} from "./MetricPickerCombobox.js";
import { formatRbacReason } from "./rbacReasons.js";

const RECORD = { method: "POST", path: "/api/v1/recording/symbols", body: { symbol: "BTCUSDT" } };
const UNRECORDED = "BTCUSDT is not on the recorded-symbol list";

/** A served signal (the vocabulary's `display_name`, `unit` and `description`, verbatim). */
const metric = (
  id: string,
  label: string,
  unit: string,
  description: string,
  category: MetricCategory,
  more: Partial<MetricPickerOption> = {},
): MetricPickerOption => ({
  id,
  label,
  unit,
  description,
  category,
  estimated: false,
  available: true,
  ...more,
});

/** E36-D02 §7's board 05: sixteen options over the seven categories, Spread (bps) drawn unrecorded. */
const BOARD_05: readonly MetricPickerOption[] = [
  metric("price", "Price", "price", "Last / mark / index price", "price"),
  metric("atr", "ATR", "price", "Wilder average true range", "price"),
  metric("market_regime", "Market regime", "enum", "Regime from ADX, Hurst and ATR%", "price", {
    estimated: true,
  }),
  metric(
    "tape_speed_zscore",
    "Tape speed z-score",
    "zscore",
    "Fast-window tape speed vs baseline",
    "orderflow",
  ),
  metric(
    "in_stop_hunt_zone",
    "In stop-hunt zone",
    "bool",
    "Price within k ticks of a detected stop cluster",
    "orderflow",
    { estimated: true },
  ),
  metric(
    "cvd_divergence",
    "CVD divergence",
    "bool",
    "Pivot-based swing comparison of price vs CVD",
    "orderflow",
    { estimated: true },
  ),
  metric("spread_bps", "Spread (bps)", "bps", "Spread in basis points of mid", "book", {
    available: false,
    unavailableReason: UNRECORDED,
    recorderAction: RECORD,
  }),
  metric(
    "distance_to_liquidity_cluster",
    "Distance to liquidity cluster",
    "count",
    "Ticks to the nearest heatmap cluster at or above z",
    "book",
  ),
  metric(
    "iceberg_present_at_level",
    "Iceberg present",
    "bool",
    "Repeated resting-size refills at a level",
    "book",
    { estimated: true },
  ),
  metric("funding_rate", "Funding rate", "pct", "Current funding rate", "derivatives"),
  metric(
    "time_to_funding_ms",
    "Time to funding",
    "ms",
    "Milliseconds until the next funding",
    "derivatives",
  ),
  metric(
    "unrealised_r_multiple",
    "Unrealised R",
    "ratio",
    "Unrealised PnL in multiples of initial risk",
    "position",
  ),
  metric("position_side", "Position side", "enum", "Side of the position", "position"),
  metric("time_in_trade_ms", "Position age", "ms", "Time since the position opened", "position"),
  metric(
    "daily_loss_pct",
    "Daily loss",
    "pct",
    "Loss today as percent of start-of-day equity",
    "account",
  ),
  metric("replay_speed", "Replay speed", "ratio", "Replay speed multiplier", "replay"),
];

/**
 * The host's copy: E36-D05's keys where the deck has them (`rules.editor.row.*`, `rules.editor.name.estimated`,
 * `rules.editor.announce.metrics`). The deck keys no category heading, placeholder or no-results sentence for the
 * picker: the words below stand in for them until it does.
 */
const HEADINGS: Readonly<Record<MetricCategory, string>> = {
  price: "Price",
  orderflow: "Order flow",
  book: "Book",
  derivatives: "Derivatives",
  position: "Position",
  account: "Account",
  replay: "Replay",
};
const NO_MATCH = "No metrics match — clear the search.";
const COPY = {
  groupLabel: (category: MetricCategory, n: number) => `${HEADINGS[category]} (${String(n)})`,
  estimatedText: "(estimated)",
  estimatedName: (label: string) => `Estimated, ${label}`,
  unavailableText: (option: MetricPickerOption) =>
    `(not available — ${option.unavailableReason ?? ""} · Start recording)`,
  startRecordingText: "Start recording",
  countText: (n: number) => `${String(n)} ${n === 1 ? "metric" : "metrics"}`,
  noResultsText: NO_MATCH,
} satisfies Partial<MetricPickerComboboxProps>;
/** E09-D09 §3.1 `rbac.owner_only` with §3.2's verb: E36-D05 `rbac.owner_only.start_recording`. */
const OWNER_ONLY = formatRbacReason("rbac.owner_only", { verb: "start recording" });

type Args = { readonly onStartRecording: (option: MetricPickerOption) => void };
type HostProps = Args & { readonly initial?: string | null; readonly reason?: string };

/** A host that owns the chosen id, as every consumer does; the label is CMP-040's. */
function Host({ initial = null, reason, onStartRecording }: HostProps): JSX.Element {
  const [value, setValue] = useState<string | null>(initial);
  return (
    <FormField label="Metric">
      <MetricPickerCombobox
        {...COPY}
        options={BOARD_05}
        value={value}
        onChange={setValue}
        onStartRecording={onStartRecording}
        startRecordingReason={reason}
        placeholder="Search metrics"
      />
    </FormField>
  );
}

/** Theme and density come from the toolbars; the list portals under `body`, so plays query the page. */
const meta: Meta<Args> = {
  title: "RuleEngine/MetricPickerCombobox",
  args: { onStartRecording: fn() },
  decorators: [
    (Story) => (
      <div style={{ width: "24rem" }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<Args>;

const page = within(document.body);
const input = (canvasElement: HTMLElement): HTMLElement =>
  within(canvasElement).getByRole("combobox", { name: "Metric" });
const list = (): HTMLElement => page.getByRole("listbox", { name: "Metric" });
const opened = async (canvasElement: HTMLElement, query: string): Promise<void> => {
  await userEvent.type(input(canvasElement), query);
  await waitFor(() => expect(list()).toBeVisible(), { timeout: 3000 });
};

/** Default: a chosen metric, its `display_name` in the well; the list closed. */
export const Default: Story = {
  render: (args) => <Host {...args} initial="unrealised_r_multiple" />,
  play: async ({ canvasElement }) => {
    await expect(input(canvasElement)).toHaveValue("Unrealised R");
    await expect(input(canvasElement)).toHaveAttribute("aria-expanded", "false");
  },
};

/** SevenCategories: the open list, one group per category with its count, `replay` last. */
export const SevenCategories: Story = {
  render: (args) => <Host {...args} />,
  play: async ({ canvasElement }) => {
    input(canvasElement).focus();
    await userEvent.keyboard("{Alt>}{ArrowDown}{/Alt}");
    await waitFor(() => expect(list()).toBeVisible());
    const groups = page.getAllByRole("group").map((group) => group.getAttribute("aria-labelledby"));
    await expect(groups.map((id) => document.getElementById(id ?? "")?.textContent)).toEqual([
      "Price (3)",
      "Order flow (3)",
      "Book (3)",
      "Derivatives (2)",
      "Position (3)",
      "Account (1)",
      "Replay (1)",
    ]);
  },
};

/** EstimatedMetricTagged: "(estimated)" is a word in the option, and its name says "Estimated" first. */
export const EstimatedMetricTagged: Story = {
  render: (args) => <Host {...args} />,
  play: async ({ canvasElement }) => {
    await opened(canvasElement, "regime");
    const option = page.getByRole("option", { name: "Estimated, Market regime" });
    await expect(option).toHaveTextContent("(estimated)");
  },
};

/** UnavailableWithStartRecording: reached, explained, never chosen; `→` reaches Start recording, one call. */
export const UnavailableWithStartRecording: Story = {
  render: (args) => <Host {...args} />,
  play: async ({ canvasElement, args }) => {
    mocked(args.onStartRecording).mockClear();
    await opened(canvasElement, "spread");
    await userEvent.keyboard("{ArrowDown}");
    const option = page.getByRole("option", { name: "Spread (bps)" });
    await expect(option).toHaveAttribute("aria-disabled", "true");
    await userEvent.keyboard("{ArrowRight}{Enter}");
    const stop = page.getByRole("option", { name: "Start recording" });
    await expect(input(canvasElement)).toHaveAttribute("aria-activedescendant", stop.id);
    await expect(args.onStartRecording).toHaveBeenCalledTimes(1);
  },
};

/** StartRecordingT2: the lock leads the full label; reached and described, a press calls nothing. */
export const StartRecordingT2: Story = {
  render: (args) => <Host {...args} reason={OWNER_ONLY} />,
  play: async ({ canvasElement, args }) => {
    mocked(args.onStartRecording).mockClear();
    await opened(canvasElement, "spread");
    await userEvent.keyboard("{ArrowDown}{ArrowRight}{Enter}");
    const stop = page.getByRole("option", { name: "Start recording" });
    await expect(stop).toHaveAttribute("aria-disabled", "true");
    await expect(stop).toHaveAccessibleDescription(OWNER_ONLY);
    await expect(args.onStartRecording).not.toHaveBeenCalled();
  },
};

/** NoResults: once the query settles, the host's sentence in a status row; it is not an option. */
export const NoResults: Story = {
  render: (args) => <Host {...args} />,
  play: async ({ canvasElement }) => {
    await userEvent.type(input(canvasElement), "xyz");
    const row = (): HTMLElement =>
      page.getByText(NO_MATCH, { selector: ".cv-combobox__status span" });
    await waitFor(() => expect(row()).toBeVisible(), { timeout: 3000 });
    await expect(page.queryAllByRole("option")).toHaveLength(0);
  },
};
