import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect, useState, type CSSProperties, type JSX } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { PREVIEW_TILE_COPY, PreviewTile } from "./PreviewTile.js";

/** CMP-228 (J2, J21). Theme and density come from the toolbars: every story renders at each 3 x 2 cell. */
const meta: Meta<typeof PreviewTile> = {
  title: "Molecules/PreviewTile",
  component: PreviewTile,
  args: {
    label: "Preview: BTCUSDT 1 minute, logarithmic scale, 1 decimal, 12 pixels per bar, UTC",
  },
  decorators: [
    (Story) => (
      <div style={{ maxWidth: "calc(var(--size-control-height) * 12)" }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof PreviewTile>;

const grid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(6, 1fr)",
  gap: "var(--space-inset-xs)",
  inlineSize: "100%",
  blockSize: "calc(var(--size-control-height) * 3)",
};

/** A stand-in for the host's second engine view: token cells, never the real renderer. */
function HostImage({ ramp }: { ramp: readonly string[] }): JSX.Element {
  return (
    <span style={grid}>
      {Array.from({ length: 18 }, (_, i) => (
        <span key={i} style={{ background: `var(${ramp[i % ramp.length] ?? ""})` }} />
      ))}
    </span>
  );
}
const FOOTPRINT = ["--color-buy-subtle", "--color-sell-subtle", "--color-surface-raised"];
const HEATMAP = ["--color-surface-raised", "--color-buy-default", "--color-sell-default"];

const img = (canvas: HTMLElement): HTMLElement => within(canvas).getByRole("img");

/** The default kind, live: the host's bars through the pending settings. */
export const Default: Story = {
  args: { children: <HostImage ramp={FOOTPRINT} /> },
  play: async ({ canvasElement }) => {
    await expect(img(canvasElement)).toHaveAccessibleName(/^Preview: BTCUSDT 1 minute/);
    await expect(img(canvasElement)).not.toHaveAttribute("tabindex");
  },
};

export const Footprint: Story = {
  args: {
    kind: "footprint",
    label: "Preview: footprint, bid by ask, 1 tick rows",
    children: <HostImage ramp={FOOTPRINT} />,
  },
};

export const Heatmap: Story = {
  args: {
    kind: "heatmap",
    label: "Preview: heatmap, logarithmic intensity",
    children: <HostImage ramp={HEATMAP} />,
  },
};

/** The built-in theme sample (CMP-031 swatches beside their words) in the toolbar's theme. */
export const ThemeDark: Story = {
  globals: { theme: "dark" },
  args: { kind: "theme", label: "Preview: dark theme, compact density" },
};
export const ThemeLight: Story = {
  globals: { theme: "light" },
  args: { kind: "theme", label: "Preview: light theme, compact density" },
};

export const Sample: Story = {
  args: { source: "sample", children: <HostImage ramp={FOOTPRINT} /> },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText(PREVIEW_TILE_COPY.sample)).toBeVisible();
  },
};

export const Empty: Story = {
  args: { status: "empty" },
  play: async ({ canvasElement }) => {
    await expect(img(canvasElement)).toHaveAccessibleName(PREVIEW_TILE_COPY.unavailable);
  },
};

export const ErrorState: Story = {
  name: "Error",
  args: { status: "error", children: <HostImage ramp={FOOTPRINT} /> },
  play: async ({ canvasElement }) => {
    await expect(img(canvasElement)).toHaveAccessibleName(PREVIEW_TILE_COPY.unavailable);
    await expect(img(canvasElement)).toHaveTextContent(PREVIEW_TILE_COPY.error);
  },
};

export const Ladder: Story = {
  args: { kind: "ladder", label: "Total quantity 2.500 BTC", value: "2.500 BTC" },
};

export const LadderCollapsed: Story = {
  args: {
    kind: "ladder",
    label: "Ladder totals",
    value: ["2.500 BTC", "64,180.2", "160,450 USDT", "1.2% of cap", "6 of 120 requests"],
  },
};

export const LadderProvisional: Story = {
  args: {
    kind: "ladder",
    label: "Worst case 1,365.85 (provisional)",
    value: "worst case 1,365.85 (provisional)",
  },
};

export const LadderRefused: Story = {
  args: {
    kind: "ladder",
    label: "Worst case 719.11 beside the cap 600.00",
    value: "719.11 beside 600.00",
  },
};

/** Reads two token values at runtime, so the story carries no raw colour (the hex-literal lint). */
function LowContrastTile(): JSX.Element {
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  useEffect(() => {
    const css = getComputedStyle(document.documentElement);
    const read = (name: string): string => css.getPropertyValue(name).trim();
    setOverrides({
      "color.text.primary": read("--color-border-strong"),
      "color.surface.sunken": read("--color-border-default"),
    });
  }, []);
  // A host image, not the theme sample: the frame carries no text, so the a11y gate stays clean.
  return (
    <PreviewTile label="Preview: custom theme" tokenOverrides={overrides}>
      <HostImage ramp={HEATMAP} />
    </PreviewTile>
  );
}

/** BQ-18: overridden body text below 4.5:1 on the overridden surface shows the warning, glyph and words. */
export const LowContrastWarning: Story = {
  render: () => <LowContrastTile />,
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText(/^Low contrast:/)).toBeVisible());
  },
};

export const LongText: Story = {
  args: {
    label:
      "Preview: BTCUSDT 1 minute, logarithmic scale, 1 decimal, inverted, 12 pixels per bar, UTC, session breaks",
    source: "sample",
    caption:
      "Changes: logarithmic scale, inverted axis, 12 pixels per bar, UTC timestamps, session breaks shown, 1 decimal",
    children: <HostImage ramp={FOOTPRINT} />,
  },
};

/** Not interactive: Tab passes the tile (no hover, focus or disabled state; spec "Not drawn"). */
export const NotFocusable: Story = {
  render: (args) => (
    <>
      <button type="button">Before</button>
      <PreviewTile {...args} kind="theme" />
      <button type="button">After</button>
    </>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Before" }));
    await userEvent.tab();
    await expect(canvas.getByRole("button", { name: "After" })).toHaveFocus();
  },
};

export const ReducedMotion: Story = {
  globals: { motion: "on" },
  args: { kind: "theme" },
  play: async () => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-motion", "reduce"));
  },
};

/** Every J21 state side by side. */
export const AllStates: Story = {
  render: (args) => (
    <div style={{ display: "grid", gap: "var(--space-inset-lg)" }}>
      <PreviewTile {...args}>
        <HostImage ramp={FOOTPRINT} />
      </PreviewTile>
      <PreviewTile {...args} source="sample">
        <HostImage ramp={FOOTPRINT} />
      </PreviewTile>
      <PreviewTile {...args} status="empty" />
      <PreviewTile {...args} status="error" />
      <PreviewTile {...args} kind="theme" />
      <PreviewTile {...args} kind="ladder" value="2.500 BTC" caption="Total quantity" />
      <PreviewTile {...args} kind="ladder" value={["2.500 BTC", "64,180.2", "160,450 USDT"]} />
    </div>
  ),
};
