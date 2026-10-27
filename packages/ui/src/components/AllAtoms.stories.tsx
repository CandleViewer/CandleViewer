import type { Meta, StoryObj } from "@storybook/react-vite";
import type { CSSProperties, JSX, ReactNode } from "react";
import { expect, fn, waitFor } from "storybook/test";
import type { DensityName, ThemeName } from "../theme/index.js";
import { Avatar } from "./Avatar.js";
import { AvatarGroup } from "./AvatarGroup.js";
import { Badge } from "./Badge.js";
import { Button } from "./Button.js";
import { Callout } from "./Callout.js";
import { ColorSwatch, ColorSwatchPicker, type ColorSwatchOption } from "./ColorSwatch.js";
import { ConfidenceDots } from "./ConfidenceDots.js";
import { CopyButton } from "./CopyButton.js";
import { Countdown } from "./Countdown.js";
import { Divider, DividerLabel } from "./Divider.js";
import { EmptyState } from "./EmptyState.js";
import { ErrorState, InlineError } from "./ErrorState.js";
import { useFocusRing } from "./FocusRing.js";
import { InlineSpinnerText } from "./InlineSpinnerText.js";
import { Kbd } from "./Kbd.js";
import { KeyValueRow } from "./KeyValueRow.js";
import { Link } from "./Link.js";
import { Popover } from "./Popover.js";
import { ProgressBar } from "./ProgressBar.js";
import { Skeleton } from "./Skeleton.js";
import { SkeletonChart } from "./SkeletonChart.js";
import { Sparkline } from "./Sparkline.js";
import { Spinner } from "./Spinner.js";
import { SwatchLegendItem } from "./SwatchLegendItem.js";
import { Tag } from "./Tag.js";
import { Tooltip } from "./Tooltip.js";
import { Heading, MonoText, NumericText, Text } from "./Typography.js";

/**
 * E05-T04's visual-regression matrix for the E05-S02 band: every atom built so far in its main states on one
 * page, once per theme x density. Interactive states (hover, open, copied, revealed) stay in each atom's own
 * stories; this page holds only what renders at rest, on a frozen clock and fixed data, so a capture is stable.
 */
const meta: Meta = {
  title: "Atoms/All atoms matrix",
  parameters: { layout: "padded" },
};
export default meta;
type Story = StoryObj;

/** A frozen clock: the countdowns render the same digits on every run. */
const T0 = Date.UTC(2026, 9, 27, 14, 2, 0);
const frozen = (): number => T0;
const SERIES = [3, 4, 3.5, 5, 4.6, 6, 5.8, 7.2, 6.9, 8.1];
const ACCOUNTS = ["Alpha Desk", "Bravo Sub", "Carry Fund", "Delta Main", "Echo Hedge"].map(
  (label) => ({ label }),
);
const SWATCHES: readonly ColorSwatchOption[] = [
  { value: "cyan", label: "Cyan", color: "var(--color-drawing-default)" },
  { value: "violet", label: "Violet", color: "var(--color-node-logic)" },
  {
    value: "grey",
    label: "Grey",
    color: "var(--color-neutral-default)",
    disabledReason: "Grey is reserved for inactive drawings.",
  },
];

const grid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(22rem, 1fr))",
  gap: "var(--space-inset-lg)",
  alignItems: "start",
};
const row: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: "var(--space-inset-sm)",
  alignItems: "center",
};
const col: CSSProperties = { display: "grid", gap: "var(--space-inset-sm)", justifyItems: "start" };
const list: CSSProperties = { listStyle: "none", margin: 0, padding: 0, display: "grid" };

/** One labelled cell per atom: the CMP id leads, so a diff names the atom that moved. */
function Cell({
  id,
  children,
}: {
  readonly id: string;
  readonly children: ReactNode;
}): JSX.Element {
  return (
    <section aria-label={id} style={col}>
      <Text variant="caption" tone="secondary">
        {id}
      </Text>
      {children}
    </section>
  );
}

function RingSample(): JSX.Element {
  const ring = useFocusRing();
  return (
    <button type="button" className={ring.className}>
      Focus ring sample
    </button>
  );
}

function AllAtoms(): JSX.Element {
  return (
    <div style={grid}>
      <Cell id="CMP-011 Tag">
        <div style={row}>
          <Tag label="Breakout" />
          <Tag variant="info" label="Info" />
          <Tag variant="warning" label="Stale" />
          <Tag variant="danger" label="Rejected" />
          <Tag label="Scalp" removable onRemove={fn()} />
        </div>
      </Cell>
      <Cell id="CMP-012 Badge">
        <div style={row}>
          <Badge value={3} label="unread alerts" tone="danger" />
          <Badge value={120} label="queued items" tone="neutral" />
          <span style={row}>
            <Badge variant="dot" tone="success" />
            Connected
          </span>
        </div>
      </Cell>
      <Cell id="CMP-013 Avatar · CMP-025 AvatarGroup">
        <div style={row}>
          <Avatar label="Alpha Desk" standalone />
          <Avatar label="Bravo Sub" size="sm" standalone />
          <AvatarGroup items={ACCOUNTS} max={3} />
        </div>
      </Cell>
      <Cell id="CMP-014 Spinner · CMP-038 InlineSpinnerText">
        <div style={col}>
          <Spinner label="Loading positions" />
          <InlineSpinnerText kind="load" label="Loading 5,000 bars" onCancel={fn()} />
          <InlineSpinnerText kind="submit" label="Saving rule" />
        </div>
      </Cell>
      <Cell id="CMP-015 Skeleton · CMP-029 SkeletonChart">
        <div style={{ ...col, justifyItems: "stretch", width: "100%" }} aria-busy="true">
          <Skeleton shape="text" count={2} />
          <Skeleton shape="row" />
          <SkeletonChart />
        </div>
      </Cell>
      <Cell id="CMP-016 Tooltip · CMP-017 Popover">
        <div style={row}>
          <Tooltip content="Saves the layout under a new name.">
            <Button>Save as</Button>
          </Tooltip>
          <Popover heading="Line style" anchor={<Button>Line style</Button>}>
            <Text>Width 2</Text>
          </Popover>
        </div>
      </Cell>
      <Cell id="CMP-018 Divider · CMP-030 DividerLabel">
        <div style={{ ...col, justifyItems: "stretch", width: "100%" }}>
          <Divider />
          <Divider inset />
          <DividerLabel label="Earlier today" />
          <div style={row}>
            <Text>Left</Text>
            <Divider orientation="vertical" />
            <Text>Right</Text>
          </div>
        </div>
      </Cell>
      <Cell id="CMP-020 Typography">
        <div style={col}>
          <Heading level={3} variant="heading-sm">
            Positions
          </Heading>
          <Text>Body text in the primary tone.</Text>
          <Text variant="caption" tone="secondary">
            Caption in the secondary tone
          </Text>
          <NumericText value={61234.5} format="price" />
          <MonoText>ord-7f3a-0021</MonoText>
        </div>
      </Cell>
      <Cell id="CMP-021 Link · CMP-022 Kbd">
        <div style={col}>
          <Link href="#settings">Shortcut settings</Link>
          <Link href="https://bybit-exchange.github.io/docs/v5/rate-limit" external>
            Bybit API documentation
          </Link>
          <Link href="#settings" disabled>
            Shortcut settings
          </Link>
          <div style={row}>
            <Kbd keys={["Ctrl", "Shift", "S"]} />
            <Kbd keys={["Shift", "wheel"]} />
          </div>
        </div>
      </Cell>
      <Cell id="CMP-023 ProgressBar">
        <div style={{ ...col, justifyItems: "stretch", width: "100%" }}>
          <ProgressBar label="Backfill" value={33} />
          <ProgressBar label="Uploaded" tone="success" value={100} />
          <ProgressBar label="Margin used" kind="meter" tone="warning" value={72} />
          <ProgressBar label="Rate budget" kind="meter" tone="danger" value={95} />
        </div>
      </Cell>
      <Cell id="CMP-024 Sparkline · CMP-032 ConfidenceDots">
        <div style={row}>
          <Sparkline data={SERIES} />
          <Sparkline data={SERIES} colorBySign />
          <ConfidenceDots level="low" />
          <ConfidenceDots level="medium" />
          <ConfidenceDots level="high" />
        </div>
      </Cell>
      <Cell id="CMP-026 EmptyState">
        <EmptyState
          headingLevel={3}
          title="No rules yet"
          description="Start from a template."
          cta={{ label: "Browse templates", onClick: fn() }}
          link={{ label: "Read the guide", href: "#guide" }}
        />
      </Cell>
      <Cell id="CMP-027 ErrorState · InlineError">
        <div style={col}>
          <ErrorState
            form="panel"
            title="Couldn't load positions"
            message="The server did not answer in time."
            retry={{ label: "Retry", onClick: fn() }}
            live="off"
          />
          <InlineError message="Enter a quantity." live="off" />
          <InlineError severity="warning" message="Above the usual size." live="off" />
        </div>
      </Cell>
      <Cell id="CMP-028 Callout">
        <div style={{ ...col, justifyItems: "stretch", width: "100%" }}>
          <Callout tone="info" title="Replay mode" live="off">
            Orders are simulated.
          </Callout>
          <Callout tone="success" title="Saved" live="off" />
          <Callout tone="warning" title="Feed delayed" live="off" />
          <Callout tone="danger" title="Order rejected" live="off" />
        </div>
      </Cell>
      <Cell id="CMP-031 ColorSwatch">
        <div style={col}>
          <div style={row}>
            <ColorSwatch color="var(--color-drawing-default)" label="Cyan" />
            <ColorSwatch color="var(--color-drawing-selected)" label="Amber" />
          </div>
          <ColorSwatchPicker aria-label="Line colour" swatches={SWATCHES} value="cyan" />
        </div>
      </Cell>
      <Cell id="CMP-033 CopyButton · CMP-035 Countdown">
        <div style={row}>
          <CopyButton value="ord-7f3a-0021" label="Copy order ID" />
          <CopyButton value="ord-7f3a-0021" label="Copy order ID" disabled />
          <Text variant="caption" tone="secondary">
            Cancels in <Countdown expiresAt={T0 + 20_000} now={frozen} />
          </Text>
          <Text variant="caption" tone="secondary">
            Expires in <Countdown expiresAt={T0 + 9_000} now={frozen} />
          </Text>
        </div>
      </Cell>
      <Cell id="CMP-036 KeyValueRow · CMP-037 SwatchLegendItem">
        <div style={{ ...col, justifyItems: "stretch", width: "100%" }}>
          <dl style={list}>
            <KeyValueRow
              label="Liquidation"
              value={<NumericText value={61234.5} format="price" />}
            />
            <KeyValueRow label="Size" value={<NumericText value={1} format="qty" />} emphasis />
            <KeyValueRow label="Funding" value={null} />
            <KeyValueRow label="Account" value="Main desk" layout="stacked" />
          </dl>
          <ul style={list}>
            <SwatchLegendItem color="var(--color-heatmap-zero)" label="Zero intensity" />
          </ul>
        </div>
      </Cell>
      <Cell id="CMP-039 FocusRing">
        <RingSample />
      </Cell>
    </div>
  );
}

const matrix = (theme: ThemeName, density: DensityName): Story => ({
  globals: { theme, density },
  render: () => <AllAtoms />,
  play: async () => {
    // The theme runtime applies the globals in an effect: prove the capture and axe see this cell of the matrix.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-density", density));
  },
});

export const DarkCompact: Story = matrix("dark", "compact");
export const DarkComfortable: Story = matrix("dark", "comfortable");
export const LightCompact: Story = matrix("light", "compact");
export const LightComfortable: Story = matrix("light", "comfortable");
export const HighContrastCompact: Story = matrix("high-contrast", "compact");
export const HighContrastComfortable: Story = matrix("high-contrast", "comfortable");
