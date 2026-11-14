import { useState, type JSX } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { Button } from "./Button.js";
import { Callout } from "./Callout.js";
import { ChartLegend, type ChartLegendItem, type ChartLegendProps } from "./ChartLegend.js";
import { RbacGate } from "./RbacGate.js";
import { formatRbacReason } from "./rbacReasons.js";

type Slot = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8;
const ema = (n: number, slot: Slot, value: number): ChartLegendItem => ({
  id: `ema-${n}`,
  label: `EMA ${n}`,
  kind: "line",
  colorToken: `color.indicator.palette.${slot}`,
  marker: "line",
  value,
  visible: true,
});
const PRICE = { ...ema(0, 1, 3412.5), id: "price", label: "ETHUSDT 5m", marker: "bar" as const };
const BASE = [PRICE, ema(21, 2, 3398.12), ema(50, 3, 3371.4)];
const MANY = [
  PRICE,
  ...[8, 13, 21, 34, 55, 89, 100, 144, 200, 233, 377, 610].map((n, i) =>
    ema(n, ((i % 7) + 2) as Slot, 3400 - i * 7.5),
  ),
];
const ribbon: ChartLegendItem = {
  ...ema(0, 4, 0),
  id: "ribbon",
  label: "MA ribbon 8 13 21 34 55",
  value: null,
  children: (["line", "bold", "dash", "dash-dot", "thin"] as const).map((marker, i) => ({
    ...ema([8, 13, 21, 34, 55][i] ?? 8, 4, 3405 - i * 4),
    marker,
  })),
};
const patch = (over: Partial<ChartLegendItem>): ChartLegendItem[] => [
  PRICE,
  { ...ema(21, 2, 3398.12), ...over },
];

/** A stateful host: the eye and remove act on local items, as the host adapter will on the store. */
function Host(
  props: Partial<ChartLegendProps> & { readonly items: ChartLegendItem[] },
): JSX.Element {
  const [items, setItems] = useState(props.items);
  return (
    <ChartLegend
      paneLabel="Price"
      collapsed={false}
      onQuickEdit={() => undefined}
      {...props}
      items={items}
      onToggleVisible={(id, visible) =>
        setItems((all) => all.map((item) => (item.id === id ? { ...item, visible } : item)))
      }
      onRemove={(id) => setItems((all) => all.filter((item) => item.id !== id))}
    />
  );
}

/** Theme, density and motion come from the toolbars; the pane is a 600 px plot (E11-D02 D12's overflow frame). */
const meta: Meta<typeof Host> = {
  title: "ChartEngine/ChartLegend",
  component: Host,
  args: { items: BASE },
  decorators: [
    (Story) => (
      <div style={{ position: "relative", height: "37.5rem", width: "26rem" }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof Host>;

export const Default: Story = {};
export const ManyIndicators: Story = { args: { items: MANY.slice(0, 7) } };
export const AllHidden: Story = { args: { items: BASE.map((i) => ({ ...i, visible: false })) } };
export const OneHidden: Story = { args: { items: patch({ visible: false }) } };
/** 13 rows in a 600 px compact pane: 7 shown, "+6 more". */
export const PlusNMore: Story = { args: { items: MANY } };
export const PopoverOpen: Story = {
  args: { items: MANY },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: /more series/ }));
    await waitFor(() => expect(within(document.body).getByRole("dialog")).toBeVisible());
  },
};
export const Collapsed: Story = { args: { items: patch({ visible: false }), collapsed: true } };
export const PaneLabelRowFocused: Story = {
  play: async ({ canvasElement }) => {
    within(canvasElement).getByRole("button", { name: "Collapse Price" }).focus();
    await waitFor(() => expect(canvasElement.querySelector("[aria-current]")).not.toBeNull());
  },
};
export const Comfortable: Story = { globals: { density: "comfortable" } };
export const Compact: Story = { globals: { density: "compact" } };
/** Dense rows are 24, as compact (`15` CMP-199 Variants); the toolbar has no third density. */
export const Dense: Story = { args: { items: MANY.slice(0, 9) }, globals: { density: "compact" } };
export const Errored: Story = {
  args: {
    items: patch({
      error: "Compute failed: History for this indicator can't be computed right now.",
    }),
  },
};
export const WarmingUp: Story = {
  args: { items: [PRICE, { ...ema(200, 5, 0), value: null, warmup: { needed: 34 } }] },
};
export const BeforeHistory: Story = {
  args: {
    items: [
      PRICE,
      {
        ...ema(1, 6, 1520.4),
        id: "cvd",
        label: "CVD",
        kind: "histogram",
        marker: "bar",
        beforeHistory: { startsAt: "2026-09-01 00:00 UTC" },
      },
    ],
  },
};
export const MultiOutput: Story = {
  args: {
    items: [
      PRICE,
      {
        ...ema(12, 7, 12.4),
        id: "macd",
        label: "MACD 12 26 9",
        kind: "oscillator",
        outputs: [
          { name: "MACD line", value: 12.4, marker: "line" },
          { name: "Signal line", value: 9.8, marker: "dash" },
          { name: "Histogram", value: 2.6, marker: "bar" },
        ],
      },
    ],
  },
};
export const Ribbon: Story = { args: { items: [PRICE, ribbon] } };
export const RibbonExpanded: Story = {
  args: { items: [PRICE, ribbon] },
  play: async ({ canvasElement }) => {
    const chevron = within(canvasElement).getByRole("button", {
      name: "Expand MA ribbon 8 13 21 34 55",
    });
    chevron.focus();
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() =>
      expect(
        within(canvasElement).getByRole("button", { name: "EMA 55 visible" }),
      ).toBeVisible(),
    );
  },
};
export const UsedByRules: Story = { args: { items: patch({ usedByRules: true }) } };
export const Provisional: Story = {
  args: {
    items: [
      PRICE,
      { ...ema(5, 8, 3390), id: "zz", label: "Zig Zag 5", marker: "glyph", provisional: true },
    ],
  },
};
export const Stale: Story = {
  args: { items: patch({ stale: { ageS: 7, lastGoodTs: "13:42:05" } }) },
};
export const Rebuilding: Story = { args: { items: patch({ rebuilding: true }) } };
export const Editing: Story = { args: { items: patch({ editing: { param: "Period" } }) } };

function AddHost(): JSX.Element {
  const [items, setItems] = useState(BASE);
  return (
    <>
      <Button onClick={() => setItems((all) => [...all, ema(100, 6, 3350.2)])}>Add EMA 100</Button>
      <ChartLegend
        paneLabel="Price"
        collapsed={false}
        items={items}
        onToggleVisible={() => undefined}
      />
    </>
  );
}
/** M7: the new row fades in at motion.duration.fast at its final position. */
export const RowAdd: Story = {
  render: () => <AddHost />,
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Add EMA 100" }));
    await waitFor(() =>
      expect(
        within(canvasElement).getByRole("button", { name: "EMA 100 visible" }),
      ).toBeVisible(),
    );
  },
};
/** The same add under reduced motion: instant (E13-D04 M7). */
export const RowAddReducedMotion: Story = { ...RowAdd, globals: { motion: "off" } };

/** The quick-edit's `Enter` is T2 under the frame's one notice: view-as (`rbac.view_as`) and a Viewer (`rbac.permission`). */
export const QuickEditViewAs: Story = {
  render: () => (
    <div style={{ display: "grid", gap: "var(--space-stack-md)" }}>
      <Callout
        id="legend-view-as"
        title={formatRbacReason("rbac.view_as", { user: "Dana" })}
        live="off"
      />
      <RbacGate
        form="notice"
        noticeId="legend-view-as"
        allowed={false}
        reason="rbac.view_as"
        fills={{ user: "Dana" }}
      >
        <Host items={patch({ editing: { param: "Period" } })} paneLabel="Price (viewing as)" />
      </RbacGate>
      <Callout
        id="legend-viewer"
        title={formatRbacReason("rbac.permission", { verb: "save workspaces" })}
        live="off"
      />
      <RbacGate
        form="notice"
        noticeId="legend-viewer"
        allowed={false}
        reason="rbac.permission"
        fills={{ verb: "save workspaces" }}
      >
        <Host items={patch({ editing: { param: "Period" } })} paneLabel="Price (Viewer)" />
      </RbacGate>
    </div>
  ),
};
