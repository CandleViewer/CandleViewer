import type { Meta, StoryObj } from "@storybook/react-vite";
import type { CSSProperties, JSX, ReactNode } from "react";
import { expect, fn, waitFor, within } from "storybook/test";
import type { DensityName, ThemeName } from "../theme/index.js";
import { Button } from "./Button.js";
import { Card } from "./Card.js";
import { CommandPalette, type PaletteCommand } from "./CommandPalette.js";
import { ConfirmDialog } from "./ConfirmDialog.js";
import { DatePicker } from "./DatePicker.js";
import { DateRangePicker } from "./DateRangePicker.js";
import { Dialog } from "./Dialog.js";
import { Drawer } from "./Drawer.js";
import { FormField } from "./FormField.js";
import { FormSection } from "./FormSection.js";
import { FuzzyList, type FuzzyListItem } from "./FuzzyList.js";
import { Combobox } from "./index.js";
import { InfoPanel } from "./InfoPanel.js";
import { Menu } from "./Menu.js";
import { SearchBox } from "./SearchBox.js";
import { SymbolPicker } from "./SymbolPicker.js";
import { SymbolSearchInput } from "./SymbolSearchInput.js";
import { Table, type TableColumn } from "./Table.js";
import { Tabs } from "./Tabs.js";
import { TextInput } from "./TextInput.js";
import { Toast } from "./Toast.js";
import { Text } from "./Typography.js";

/**
 * E05-T04's visual-regression matrix for the E05-S03 band, once per theme x density. Like the atoms matrix it
 * holds only what renders at rest: fixed data, a frozen clock for the date pickers, motion stopped by the in-app
 * reduced-motion override, no timer running (single Toasts, never the timed region), and every portalled menu and
 * listbox closed (CMP-213's list is drawn in place). The reflowed Table renders stacked at a 200 % text scale: its
 * threshold is in `em`, so the scaled box is the same state as a 200 % page zoom (the Table's own Reflow story
 * drives the zoom itself).
 *
 * The four modal or full-height overlays (Dialog, ConfirmDialog, Drawer, CommandPalette) each take the whole page
 * and its focus, so each has its own story per theme x density below the at-rest page, opened at mount.
 */
const meta: Meta = {
  title: "Molecules/All molecules matrix",
  parameters: { layout: "padded" },
};
export default meta;
type Story = StoryObj;

/** A frozen clock (2026-10-27 14:02 UTC): the pickers' "today" is the same on every run. */
const T0 = Date.UTC(2026, 9, 27, 14, 2, 0);
const frozen = (): number => T0;

interface Position {
  readonly id: string;
  readonly symbol: string;
  readonly account: string;
  readonly size: number;
  readonly entry: number;
  readonly pnl: number;
}
const POSITIONS: readonly Position[] = [
  { id: "p1", symbol: "BTCUSDT", account: "Main", size: 0.25, entry: 63118, pnl: 412.5 },
  { id: "p2", symbol: "ETHUSDT", account: "Hedge", size: 3, entry: 2984.4, pnl: -120.75 },
  { id: "p3", symbol: "SOLUSDT", account: "Main", size: 40, entry: 148.32, pnl: 0 },
];
const COLUMNS: readonly TableColumn<Position>[] = [
  { id: "symbol", header: "Symbol", cell: (p) => p.symbol, sortable: true, minWidthEm: 10 },
  { id: "account", header: "Account", cell: (p) => p.account, minWidthEm: 9 },
  { id: "size", header: "Size", cell: (p) => p.size, numeric: "qty", minWidthEm: 7 },
  {
    id: "entry",
    header: "Entry price",
    cell: (p) => p.entry,
    numeric: "price",
    precision: 4,
    minWidthEm: 8,
  },
  {
    id: "pnl",
    header: "Unrealised PnL",
    cell: (p) => p.pnl,
    numeric: "pnl",
    sortable: true,
    minWidthEm: 10,
  },
];
const BY_PNL = { columnId: "pnl", direction: "descending" } as const;
const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"].map((s) => ({ value: s, label: s }));
/** E08-D05's rows (§6.1, §6.4): a Recent group with a delisted symbol, and a ranked list with its active option. */
const RECENT: readonly FuzzyListItem[] = [
  { id: "ETHUSDT", label: "ETHUSDT", hint: "ETH / USDT", tags: ["recent"] },
  {
    id: "LUNAUSDT",
    label: "LUNAUSDT",
    hint: "LUNA / USDT",
    chip: { label: "Delisted by the exchange", icon: "cancelled" },
    disabled: true,
    delisted: true,
    reason: "LUNAUSDT is not trading on Bybit.",
  },
];
const RANKED: readonly FuzzyListItem[] = ["ETHUSDT", "ETHFIUSDT"].map((s): FuzzyListItem => ({
  id: s,
  label: s,
  matchRanges: [[0, 3]],
  hint: `${s.slice(0, -4)} / USDT`,
  values: ["—", "—"],
}));
/** CMP-219's trigger, as B02 draws it (E08-D05 §14): Chart 1's BTCUSDT at 1 minute. */
const PICKED = { value: "BTCUSDT", interval: "1 minute" } as const;
const TABS = [
  { id: "positions", label: "Positions" },
  { id: "orders", label: "Orders" },
  { id: "fills", label: "Fills", disabledReason: "Fills load after the account connects." },
];

const grid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(24rem, 1fr))",
  gap: "var(--space-inset-lg)",
  alignItems: "start",
};
const col: CSSProperties = {
  display: "grid",
  gap: "var(--space-inset-sm)",
  justifyItems: "stretch",
  width: "100%",
};
const wide: CSSProperties = { gridColumn: "1 / -1" };

/** One labelled cell per molecule: the CMP id leads, so a diff names the molecule that moved. */
function Cell({
  id,
  children,
  style,
}: {
  readonly id: string;
  readonly children: ReactNode;
  readonly style?: CSSProperties;
}): JSX.Element {
  return (
    <section aria-label={id} style={{ ...col, ...style }}>
      <Text variant="caption" tone="secondary">
        {id}
      </Text>
      {children}
    </section>
  );
}

function AllMolecules(): JSX.Element {
  return (
    <div style={grid}>
      <Cell id="CMP-040 FormField">
        <FormField label="Username" help="Letters, digits and underscores.">
          <TextInput defaultValue="trader_01" />
        </FormField>
        <FormField label="Quantity" required error="Enter a quantity above 0.">
          <TextInput defaultValue="" />
        </FormField>
        <FormField label="Leverage" disabledReason="Your role can't change leverage.">
          <TextInput defaultValue="5" />
        </FormField>
      </Cell>
      <Cell id="CMP-065 FormSection">
        <FormSection title="Risk limits" description="Applied to every new order on this account.">
          <FormField label="Max position size">
            <TextInput defaultValue="2.5" />
          </FormField>
        </FormSection>
        <FormSection title="Advanced" collapsible defaultOpen={false} errorCount={1}>
          <FormField label="Slippage cap">
            <TextInput defaultValue="" />
          </FormField>
        </FormSection>
      </Cell>
      <Cell id="CMP-054 SearchBox · CMP-048 Combobox">
        <SearchBox label="Search layouts" value="" onChange={fn()} onClear={fn()} />
        <SearchBox label="Search rules" value="breakout" onChange={fn()} onClear={fn()} />
        <FormField label="Symbol">
          <Combobox options={SYMBOLS} value="ETHUSDT" onChange={fn()} />
        </FormField>
      </Cell>
      <Cell id="CMP-160 SymbolSearchInput · CMP-213 FuzzyList">
        <SymbolSearchInput
          value=""
          onChange={fn()}
          onSelect={fn()}
          items={[]}
          recentSymbols={RECENT}
          target={{ label: "Changes Chart 1 · BTCUSDT 1m", armed: true }}
        />
        <FuzzyList
          id="matrix-ranked"
          aria-label="Ranked symbols"
          items={RANKED}
          activeId="ETHUSDT"
          onActivate={fn()}
        />
      </Cell>
      <Cell id="CMP-219 SymbolPicker">
        {/* B02's frames: rest, recording, not recorded, delisted and expanded. */}
        <SymbolPicker {...PICKED} onOpen={fn()} />
        <SymbolPicker {...PICKED} onOpen={fn()} recording="recording" />
        <SymbolPicker {...PICKED} onOpen={fn()} recording="not-recorded" />
        <SymbolPicker {...PICKED} onOpen={fn()} value="LUNAUSDT" delisted />
        <SymbolPicker {...PICKED} onOpen={fn()} expanded />
      </Cell>
      <Cell id="CMP-050 Card">
        <Card title="Accounts" actions={<Button variant="ghost">Manage</Button>}>
          <Text>3 accounts connected.</Text>
        </Card>
        <Card title="Notes" surface="flat" headingLevel={0}>
          <Text>A flat card with a plain-text title.</Text>
        </Card>
      </Cell>
      <Cell id="CMP-042 Tabs">
        <Tabs
          aria-label="Blotter"
          tabs={TABS}
          value="positions"
          onChange={fn()}
          renderPanel={(id) => (
            <Text>{id === "positions" ? "3 open positions." : "Nothing yet."}</Text>
          )}
        />
      </Cell>
      <Cell id="CMP-045 Toast">
        {/* Single toasts, never the timed region: nothing counts down mid-capture. */}
        <Toast title="Session extended" tone="success" onDismiss={fn()} />
        <Toast
          title="Order rejected — insufficient margin"
          description="BTCUSDT buy 0.25 at 63,120.0"
          tone="danger"
          kicker="Order"
          actions={[{ label: "View order", onClick: fn() }]}
          onDismiss={fn()}
        />
        <Toast
          title="EMA 21 removed"
          tone="info"
          undo={{ onUndo: fn(), outcome: "EMA 21 removed." }}
          undoClosed
          onDismiss={fn()}
        />
      </Cell>
      <Cell id="CMP-069 InfoPanel · CMP-041 Menu">
        <InfoPanel
          variant="inline"
          defaultOpen
          title="Iceberg detector"
          content={<Text>Flags refills at one price level within 2 s of a fill.</Text>}
          values={<Text>Confidence: medium</Text>}
          trigger={(props) => (
            <Button variant="ghost" {...props}>
              Estimated
            </Button>
          )}
        />
        <Menu
          trigger={<Button>Layer actions</Button>}
          items={[
            { id: "dup", label: "Duplicate", onSelect: fn() },
            { id: "remove", label: "Remove", danger: true, onSelect: fn() },
          ]}
        />
      </Cell>
      <Cell id="CMP-047 DatePicker · DateRangePicker">
        <FormField label="Trade date">
          <DatePicker value="2026-10-23" onChange={fn()} now={frozen} />
        </FormField>
        <FormField label="Report period">
          <DateRangePicker
            value={{ start: "2026-10-01", end: "2026-10-23" }}
            onChange={fn()}
            now={frozen}
          />
        </FormField>
        <FormField label="Replay from">
          <DatePicker value="2026-10-20" onChange={fn()} now={frozen} withTime time="09:30" />
        </FormField>
      </Cell>
      <Cell id="CMP-049 Table" style={wide}>
        <Table<Position>
          caption="Open positions"
          columns={COLUMNS}
          rows={POSITIONS}
          rowKey={(p) => p.id}
          sort={BY_PNL}
          onSortChange={fn()}
        />
      </Cell>
      <Cell id="CMP-049 Table, stacked (200 % text scale)" style={wide}>
        <div data-reflow="" style={{ fontSize: "200%", maxWidth: "40rem" }}>
          <Table<Position>
            caption="Open positions, reflowed"
            columns={COLUMNS}
            rows={POSITIONS}
            rowKey={(p) => p.id}
            density="compact"
          />
        </div>
      </Cell>
    </div>
  );
}

/** The globals every capture needs: this cell of the matrix, with motion reduced. */
const applied = async (theme: ThemeName, density: DensityName): Promise<void> => {
  const root = document.documentElement;
  await waitFor(() => expect(root).toHaveAttribute("data-theme", theme));
  await waitFor(() => expect(root).toHaveAttribute("data-density", density));
  await waitFor(() => expect(root).toHaveAttribute("data-motion", "reduce"));
};

const matrix = (theme: ThemeName, density: DensityName): Story => ({
  // `motion: "on"` turns the reduced-motion override on (`data-motion="reduce"`), so nothing animates.
  globals: { theme, density, motion: "on" },
  render: () => <AllMolecules />,
  play: async ({ canvasElement }) => {
    await applied(theme, density);
    // The reflowed table is stacked, with no sideways overflow; the plain one stays a table.
    const reflow = canvasElement.querySelector<HTMLElement>("[data-reflow] [data-cmp='CMP-049']");
    await waitFor(() => expect(reflow).toHaveAttribute("data-layout", "stacked"));
    const region = reflow?.querySelector<HTMLElement>(".cv-table__region");
    await expect(region?.scrollWidth).toBeLessThanOrEqual(region?.clientWidth ?? 0);
    await expect(
      within(canvasElement).getByRole("table", { name: "Open positions" }).closest("[data-cmp]"),
    ).not.toHaveAttribute("data-layout");
    // Every portalled listbox and menu is closed at rest; CMP-213's list is drawn in place.
    await expect(document.querySelector('[role="listbox"]:not(.cv-fuzzylist__list)')).toBeNull();
    await expect(document.querySelector('[role="menu"]:not([hidden])')).toBeNull();
  },
});

export const DarkCompact: Story = matrix("dark", "compact");
export const DarkComfortable: Story = matrix("dark", "comfortable");
export const LightCompact: Story = matrix("light", "compact");
export const LightComfortable: Story = matrix("light", "comfortable");
export const HighContrastCompact: Story = matrix("high-contrast", "compact");
export const HighContrastComfortable: Story = matrix("high-contrast", "comfortable");

const cmd = (id: string, label: string, group: string, extra: Partial<PaletteCommand> = {}) => ({
  id,
  label,
  group,
  onRun: fn(),
  ...extra,
});
const PALETTE: readonly PaletteCommand[] = [
  cmd("chart", "Go to chart", "Navigate", { shortcut: ["Ctrl", "1"] }),
  cmd("btc", "BTCUSDT", "Symbol"),
  cmd("flatten", "Flatten all positions", "Action", { destructive: true }),
  cmd("leverage", "Set leverage", "Action", {
    disabledReason: "Your role can't change positions.",
  }),
  cmd("theme", "Switch theme", "Setting", { shortcut: ["Ctrl", "Shift", "H"] }),
];

type Overlay = "Dialog" | "ConfirmDialog" | "Drawer" | "CommandPalette";

/** One overlay, open at mount. Every handler is a spy: nothing closes it, so the capture holds still. */
function OpenOverlay({ kind }: { readonly kind: Overlay }): JSX.Element {
  switch (kind) {
    case "Dialog":
      return (
        <Dialog
          open
          onOpenChange={fn()}
          title="Save layout as"
          description="The layout keeps every panel and its symbol."
          footer={
            <>
              <Button>Cancel</Button>
              <Button variant="primary">Save</Button>
            </>
          }
        >
          <FormField label="Layout name">
            <TextInput defaultValue="Scalping, 3 panels" />
          </FormField>
        </Dialog>
      );
    case "ConfirmDialog":
      // Hold with a token: the typed field and the progress ring at 0 %, no hold running.
      return (
        <ConfirmDialog
          open
          title="Flatten everything?"
          restatement={<p>Closes 4 positions at market on every account.</p>}
          confirmLabel="Flatten 4 positions — all accounts"
          variant="hold"
          typedConfirmValue="FLATTEN"
          now={frozen}
          onConfirm={fn()}
          onCancel={fn()}
        />
      );
    case "Drawer":
      return (
        <Drawer open onOpenChange={fn()} title="Alert details">
          <Text>BTCUSDT crossed 65,000.0 at 14:02 UTC.</Text>
        </Drawer>
      );
    case "CommandPalette":
      return (
        <CommandPalette
          open
          onOpenChange={fn()}
          commands={PALETTE}
          sections={[{ label: "Recent", commands: PALETTE.slice(0, 3) }]}
          placeholder="Type a command or symbol"
          onRequestConfirm={fn()}
        />
      );
  }
}

const ROLE: Record<Overlay, string> = {
  Dialog: "dialog",
  ConfirmDialog: "alertdialog",
  Drawer: "dialog",
  CommandPalette: "dialog",
};

const overlay = (kind: Overlay, theme: ThemeName, density: DensityName): Story => ({
  globals: { theme, density, motion: "on" },
  render: () => <OpenOverlay kind={kind} />,
  play: async () => {
    await applied(theme, density);
    await waitFor(() => expect(within(document.body).getByRole(ROLE[kind])).toBeVisible());
  },
});

export const DialogDarkCompact: Story = overlay("Dialog", "dark", "compact");
export const DialogDarkComfortable: Story = overlay("Dialog", "dark", "comfortable");
export const DialogLightCompact: Story = overlay("Dialog", "light", "compact");
export const DialogLightComfortable: Story = overlay("Dialog", "light", "comfortable");
export const DialogHighContrastCompact: Story = overlay("Dialog", "high-contrast", "compact");
export const DialogHighContrastComfortable: Story = overlay(
  "Dialog",
  "high-contrast",
  "comfortable",
);
export const ConfirmDialogDarkCompact: Story = overlay("ConfirmDialog", "dark", "compact");
export const ConfirmDialogDarkComfortable: Story = overlay("ConfirmDialog", "dark", "comfortable");
export const ConfirmDialogLightCompact: Story = overlay("ConfirmDialog", "light", "compact");
export const ConfirmDialogLightComfortable: Story = overlay(
  "ConfirmDialog",
  "light",
  "comfortable",
);
export const ConfirmDialogHighContrastCompact: Story = overlay(
  "ConfirmDialog",
  "high-contrast",
  "compact",
);
export const ConfirmDialogHighContrastComfortable: Story = overlay(
  "ConfirmDialog",
  "high-contrast",
  "comfortable",
);
export const DrawerDarkCompact: Story = overlay("Drawer", "dark", "compact");
export const DrawerDarkComfortable: Story = overlay("Drawer", "dark", "comfortable");
export const DrawerLightCompact: Story = overlay("Drawer", "light", "compact");
export const DrawerLightComfortable: Story = overlay("Drawer", "light", "comfortable");
export const DrawerHighContrastCompact: Story = overlay("Drawer", "high-contrast", "compact");
export const DrawerHighContrastComfortable: Story = overlay(
  "Drawer",
  "high-contrast",
  "comfortable",
);
export const CommandPaletteDarkCompact: Story = overlay("CommandPalette", "dark", "compact");
export const CommandPaletteDarkComfortable: Story = overlay(
  "CommandPalette",
  "dark",
  "comfortable",
);
export const CommandPaletteLightCompact: Story = overlay("CommandPalette", "light", "compact");
export const CommandPaletteLightComfortable: Story = overlay(
  "CommandPalette",
  "light",
  "comfortable",
);
export const CommandPaletteHighContrastCompact: Story = overlay(
  "CommandPalette",
  "high-contrast",
  "compact",
);
export const CommandPaletteHighContrastComfortable: Story = overlay(
  "CommandPalette",
  "high-contrast",
  "comfortable",
);
