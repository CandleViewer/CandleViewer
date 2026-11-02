import { useId, useMemo, useState, type JSX, type KeyboardEvent, type ReactNode } from "react";
import { Icon } from "../icons/Icon.js";
import { Checkbox } from "./Checkbox.js";
import type { MenuItem } from "./Menu.js";
import { PnLBadge, pnlReading } from "./PnLBadge.js";
import { PositionModeToggle, type PositionMode } from "./PositionModeToggle.js";
import { SplitButton, type SplitButtonProps } from "./SplitButton.js";
import {
  Table,
  type TableColumn,
  type TableRowContext,
  type TableSort,
  type TableTreeRow,
} from "./Table.js";
import { cx } from "./internal/cx.js";
import { formatDecimal } from "./internal/decimalText.js";

/** The liquidation tier (E29-D02 §5.3, D01 D5): the thresholds and their hysteresis are the host's (`liqTier.ts`). */
export type PositionsGridTier = "none" | "watch" | "near" | "critical";

/** A row's liquidation reading, the host's `LiqReading` as it stands: the cell draws it and decides nothing. */
export interface PositionsGridLiq {
  readonly tier: PositionsGridTier;
  /** `|mark − liq| / mark` in percent at one place ("1.2"); `null` without a liquidation price. */
  readonly distancePct: string | null;
  /** Isolated margin: the share of the entry buffer left, in whole percent ("27"). */
  readonly sharePct?: string | null | undefined;
  /** Cross and portfolio margin: the account's maintenance-margin rate, in whole percent ("88"). */
  readonly mmRatePct?: string | null | undefined;
}

/** Why R is "—" (#5239's `RUnavailable`): no stop on the row, no entry or mark price, or a stop at the entry. */
export type PositionsGridRUnavailable = "no_stop" | "no_price" | "zero_distance";

/**
 * One open position as the grid draws it: the fields of the apps/web positions model's `PositionRowModel` it reads
 * (#5239 `model/rowMapping.ts`), so that model's rows pass as they stand once `liq` is beside them. Money and prices
 * are the wire's decimal strings, never `number` (E29-D04 §2.1; D02 D-7).
 */
export interface PositionsGridRow {
  /** `exchange_account_id|symbol|position_idx`: unique in the grid, the row's selection key. */
  readonly key: string;
  readonly accountId: string;
  /** `null` for an account the directory does not name: the id stands in. */
  readonly accountLabel: string | null;
  readonly symbol: string;
  /** The base coin, for "0.250 BTC" (D02 §5.1). */
  readonly baseCoin: string;
  readonly side: "long" | "short";
  readonly sideWord: "Long" | "Short";
  /** Hedge mode (`position_idx` 1 or 2): " · hedge" after the side (D02 §5.1). */
  readonly hedge: boolean;
  readonly size: string;
  readonly entry: string | null;
  readonly mark: string | null;
  readonly unrealisedPnl: string | null;
  /** The frame's `realised_pnl_session`, or `null`: "—" (#911 BQ-8). */
  readonly realisedToday: { readonly value: string | null };
  /**
   * The server's R or the host's derivation (#5239's `RValue`); `null`: "—" with its reason, which only for `no_stop`
   * is D02 §5.1's "R unavailable: no stop price" (#911 BQ-8).
   */
  readonly r: {
    readonly value: string | null;
    readonly reason?: PositionsGridRUnavailable | undefined;
  };
  readonly leverage: string | null;
  readonly marginMode: { readonly value: "cross" | "isolated" | "portfolio" | null };
  readonly liqPrice: string | null;
  readonly liq: PositionsGridLiq;
}

/** One group row and its positions: the apps/web model's `GroupModel` with the header's words beside it. */
export interface PositionsGridGroup<R extends PositionsGridRow = PositionsGridRow> {
  /** The account id, the symbol or the trade group (`GroupModel.key`); `null` gathers the positions with none. */
  readonly key: string | null;
  /** The header's leading words, the host's: "Main · LIVE" (D02:238), a symbol, a trade group's name. */
  readonly label: string;
  /** An account group's position mode, as CMP-129 `display` words it (D02:238). */
  readonly positionMode?: PositionMode | undefined;
  readonly rows: readonly R[];
  readonly count: number;
  readonly unrealisedPnl: string | null;
  /** An account group's `realised_pnl_today` (D-15), else the rows' sum; `null`: "—". */
  readonly realisedToday: string | null;
  /** The signed net size, only for a group on one symbol (#911 BQ-12); else `null`. */
  readonly netSize: string | null;
  /**
   * An account's state marker when one applies (D02 §5.5 and §10.2: "checking", "Verifying", "Stale — locked"; D04H
   * C.1 `AccountGroup.state`; #911 BQ-14): the host's tag, after the header's figures. Absent, none.
   */
  readonly marker?: ReactNode;
}

/** The totals row: the apps/web model's `TotalsModel` with its rowheader's words ("LIVE total", D02:142). */
export interface PositionsGridTotals {
  readonly label: string;
  readonly count: number;
  /** Σ size × mark (D02 D-15's Exposure); `null` when a row has none. */
  readonly exposure: string | null;
  /** D-15's Net, Σ signed notional (long positive; D01 D1), in the row's tooltip and description; absent, none. */
  readonly net?: string | null | undefined;
  readonly unrealisedPnl: string | null;
  readonly realisedToday: string | null;
}

/** The data columns (D02 §5.1, the narrow dock's Status of §11.5); the ids the apps/web sort and panel state use. */
export type PositionsGridColumnId =
  | "account"
  | "symbol"
  | "side"
  | "size"
  | "entry"
  | "mark"
  | "upnl"
  | "r"
  | "rpnl_today"
  | "liq_price"
  | "liq_dist"
  | "leverage"
  | "margin"
  | "status";

/** D02 §5.1's default Positions columns, in order (Env out: one environment per server, #911 BQ-7). */
export const POSITIONS_GRID_COLUMNS: readonly PositionsGridColumnId[] = [
  "account",
  "symbol",
  "side",
  "size",
  "entry",
  "mark",
  "upnl",
  "r",
  "rpnl_today",
  "liq_price",
  "liq_dist",
  "leverage",
  "margin",
];

/** D02 §11.5's 360 px dock: Symbol · Side · Size · uPnL · Status, the account in its group header. */
export const POSITIONS_GRID_NARROW_COLUMNS: readonly PositionsGridColumnId[] = [
  "symbol",
  "side",
  "size",
  "upnl",
  "status",
];

export interface PositionsGridProps<R extends PositionsGridRow = PositionsGridRow> {
  /** Names the treegrid ("Positions"). */
  readonly caption: string;
  readonly captionHidden?: boolean;
  /** The groups in the host's order, each with its rows in the host's sort (sorting is within groups, D02 §5.5). */
  readonly groups: readonly PositionsGridGroup<R>[];
  /** The one totals row, pinned under the rows (D-15; one environment, #911 BQ-7). */
  readonly totals?: PositionsGridTotals | undefined;
  /** The visible data columns in order (per tab, the host's); Account and Symbol always shown, Symbol in narrow. */
  readonly columns?: readonly PositionsGridColumnId[];
  /**
   * `narrow`: the 360 px dock (D02 §11.5): its columns, `space.inset.xs` cells, and no Actions column, every row action
   * staying in the row menu (D-12).
   */
  readonly variant?: "default" | "narrow";
  readonly density?: "compact" | "comfortable";
  /** The unit of the money columns (the headers' "(USDT)", the PnL readings'). */
  readonly currency?: string;
  /** The selected rows' keys, every group's, drawn or not (D-3); with `onSelectionChange`, the select column. */
  readonly selected?: ReadonlySet<string>;
  readonly onSelectionChange?: ((next: ReadonlySet<string>) => void) | undefined;
  /** The closed groups' keys (`PositionsGridGroup.key`, `""` for `null`); without it the grid keeps its own. */
  readonly collapsed?: ReadonlySet<string> | undefined;
  readonly onCollapsedChange?: ((next: ReadonlySet<string>) => void) | undefined;
  /** CMP-049's sort: the host sorts within groups; the press cycle is the host's (F-04). */
  readonly sort?: TableSort | undefined;
  readonly onSortChange?: ((sort: TableSort) => void) | undefined;
  /**
   * A row's actions, CMP-057's props, each gate the host's (CMP-079's pair from each operation; never a role prop):
   * the Actions column (D02 §8.1), repeated as the row menu (`Shift+F10`, the Menu key, a right-click), which alone
   * carries them in the narrow dock (D-12, §11.5). Mounted by the ticket that wires them (#911 BQ-3); `undefined`, no
   * column and no row menu.
   */
  readonly rowActions?: ((row: R) => SplitButtonProps | undefined) | undefined;
  readonly loading?: boolean;
  readonly loadingText?: string;
  /** The host's CMP-026 when there are no rows (D02 §10.1 Empty, §9.2 filter-empty). */
  readonly emptyState?: ReactNode;
  /** The host's polite region for CMP-049's lines (sort and load results); none here otherwise. */
  readonly announce?: ((text: string) => void) | undefined;
}

/** CMP-049 renders a window of the rows from this many (`15` CMP-049: windowing from 50 rows). */
const WINDOW_FROM = 50;
/** Rows drawn either side of the rows in view. */
const OVERSCAN = 10;
/** Before the region reports what it shows: the first rows. */
const FIRST_WINDOW = 30;

/** Rows of the flattened tree, first and last inclusive, from 0. */
interface RowSpan {
  readonly first: number;
  readonly last: number;
}

/** The rows drawn for a view: OVERSCAN either side of it, within the list. */
const drawnFor = (view: RowSpan, total: number): RowSpan => ({
  first: Math.max(0, Math.min(view.first - OVERSCAN, total - 1)),
  last: Math.min(total, view.last + OVERSCAN + 1) - 1,
});

/**
 * Whether a reported view keeps the drawn rows: while it stays OVERSCAN / 2 rows inside each drawn edge that is not the
 * list's own end, so a mount or a short scroll draws nothing again. A view nearer an edge re-centres the window while
 * half the overscan is still drawn past it: a scroll's commit lands after that frame's paint, and no blank row shows.
 */
const keepsDrawn = (drawn: RowSpan, view: RowSpan, total: number): boolean =>
  (drawn.first === 0 || view.first >= drawn.first + OVERSCAN / 2) &&
  (drawn.last === total - 1 || view.last <= drawn.last - OVERSCAN / 2);
/** D02 §5.1's minimum widths in px, compact and comfortable, as `em` of a 16 px table (the `<col>` widths). */
const WIDTH_PX: Readonly<
  Record<PositionsGridColumnId | "select" | "actions", readonly [number, number]>
> = {
  select: [24, 32],
  account: [96, 104],
  symbol: [96, 104],
  side: [80, 88],
  size: [104, 112],
  entry: [88, 96],
  mark: [88, 96],
  upnl: [96, 104],
  r: [64, 72],
  rpnl_today: [104, 112],
  liq_price: [88, 96],
  liq_dist: [120, 128],
  leverage: [56, 64],
  margin: [80, 88],
  status: [68, 76],
  actions: [96, 104],
};
/** D02 §11.5's 360 px dock widths, compact (comfortable adds the row's 8). */
const NARROW_PX: Readonly<Partial<Record<PositionsGridColumnId | "select", number>>> = {
  select: 24,
  symbol: 72,
  side: 60,
  size: 48,
  upnl: 72,
  status: 68,
};
const PX_PER_EM = 16;

/** D02 §5.1's margin words. */
const MARGIN_WORDS = { cross: "Cross", isolated: "Isolated", portfolio: "Portfolio" } as const;
/** D02 §5.1: the side glyph before its word, never colour alone (D-6). */
const SIDE_GLYPH = { long: "▲", short: "▼" } as const;
/** D02 §5.1: a null liquidation price is "—", spoken so. */
const NO_LIQ = "no liquidation price from Bybit";
const NO_VALUE = "no value";

/**
 * What a "—" R reads (D02 §5.1, #911 BQ-8): D02's "R unavailable: no stop price", CMP-116's own default, only where
 * the row has no stop. No entry or mark price, a stop at the entry (a breakeven stop) or no reason given read a neutral
 * "R unavailable", never a false "no stop price"; fuller words are G-W3's to give.
 */
const rReading = (r: PositionsGridRow["r"]): string | undefined =>
  r.reason === "no_stop" ? undefined : "R unavailable";

/**
 * D02 §5.3's cell anatomy per tier (D01 D5): the glyph (a text glyph until CMP-019 registers `triangle`,
 * `alert-circle` and `octagon-alert`, E29-D04 §2.8.7), the word, and the D5 label the name and the echo spell.
 */
const TIER = {
  watch: { glyph: "△", word: "Watch", label: "Watch" },
  near: { glyph: "!", word: "Near", label: "Near liquidation" },
  critical: { glyph: "!!", word: "Critical", label: "Critical — near liquidation" },
} as const;

/** "—" for a null, with its spoken reason (D02 D-7). */
const dash = (reading: string): JSX.Element => (
  <>
    <span aria-hidden="true">—</span>
    <span className="cv-visually-hidden">{reading}</span>
  </>
);

/** "1 position", "3 positions" (D02:238). */
const positionsWord = (n: number): string => (n === 1 ? "1 position" : `${String(n)} positions`);

/** A wire decimal as shown, grouped and signed by U+2212; "—" for none (D02 D-7). */
const shown = (value: string | null, places?: number): string | null =>
  value === null
    ? null
    : (formatDecimal(value, places === undefined ? {} : { places })?.text ?? null);

/** A gate's reason as CMP-057 reads it: trimmed, and none when blank. */
const reasonText = (text: string | undefined): string | undefined => {
  const trimmed = text?.trim();
  return trimmed === "" ? undefined : trimmed;
};

/**
 * The D5 label with the share or the rate and the distance, which the cell's name and echo spell (D02:222): "Critical
 * — near liquidation: 14 % of the entry buffer left, 0.5 % from liquidation". The cross form names the account's
 * margin rate instead (D02 §5.3; its words PROPOSED to E29-D03's copy owner, as is the form with the distance alone).
 */
export function liqSentence(liq: PositionsGridLiq): string | undefined {
  if (liq.tier === "none") return undefined;
  const { label } = TIER[liq.tier];
  const distance = liq.distancePct === null ? undefined : `${liq.distancePct} % from liquidation`;
  const metric =
    liq.sharePct != null
      ? `${liq.sharePct} % of the entry buffer left`
      : liq.mmRatePct != null
        ? `account margin rate ${liq.mmRatePct} %`
        : undefined;
  const parts = [metric, distance].filter((part) => part !== undefined);
  return parts.length === 0 ? label : `${label}: ${parts.join(", ")}`;
}

export interface LiqTierCellProps {
  readonly liq: PositionsGridLiq;
  /** `status`: the narrow dock's Status, the glyph and the word without the distance (D02 §11.5). */
  readonly form?: "distance" | "status";
  /** The id of the node the row's description points at (E29-D05 N-02: "the tier label"). */
  readonly sentenceId?: string | undefined;
}

/**
 * CMP-114's `LiqTierCell` (E29-D04 §2.1 frames `liq-watch`, `liq-near`, `liq-critical`; D02 §5.3): glyph, tier word
 * and distance from liquidation ("! Near 1.2"), never colour alone; the glyph is `aria-hidden` and the D5 label with
 * the share and the distance is the one hidden sentence assistive technology reads. No tier: the distance alone
 * ("9.5"); no liquidation price: "—", read "no liquidation price from Bybit". A crossing's announcement is the host's
 * (D02 §5.3: polite into Near, assertive into Critical, once); a tier swap is a cut (Mo-8).
 */
export function LiqTierCell({ liq, form = "distance", sentenceId }: LiqTierCellProps): JSX.Element {
  if (liq.tier === "none") {
    return (
      <span className="cv-positions-grid__liq" data-part="LiqTierCell" data-tier="none">
        {form === "status" ? null : liq.distancePct === null ? (
          <>
            <span aria-hidden="true">—</span>
            <span className="cv-visually-hidden">{NO_LIQ}</span>
          </>
        ) : (
          liq.distancePct
        )}
      </span>
    );
  }
  const tier = TIER[liq.tier];
  return (
    <span className="cv-positions-grid__liq" data-part="LiqTierCell" data-tier={liq.tier}>
      <span aria-hidden="true">
        <span className="cv-positions-grid__tier-glyph">{tier.glyph}</span>{" "}
        <span className="cv-positions-grid__tier-word">{tier.word}</span>
        {form === "status" || liq.distancePct === null ? null : ` ${liq.distancePct}`}
      </span>
      <span id={sentenceId} className="cv-visually-hidden">
        {liqSentence(liq)}
      </span>
    </span>
  );
}

export interface UpdatesPausedChipProps {
  /** Rows held back while the pointer rests on the grid or an editor or menu is open (D01 D13 b). */
  readonly newRows: number;
  readonly closedRows: number;
  /** A held row carries NO SL: the chip takes the critical style (D02:376). */
  readonly noSl?: boolean;
  /** Applies the held inserts, exits and re-sorts. */
  readonly onApply: () => void;
  readonly density?: "compact" | "comfortable";
}

/**
 * CMP-114's `UpdatesPausedChip` (E29-D04 §2.1 frame `updates-paused-chip`; D02 §9.1, D01 D13 b): a button in the
 * toolbar, "Updates paused · 2 new · 1 closed", that applies the held changes. Values keep changing in place while it
 * shows; the held rows wait for it. An interactive chip takes the control height (D02 §12). Its critical tone (a held
 * row carries NO SL) is its fill alone, which forced colours draw as the other tone: a word or glyph for it is a design
 * gap for E29-D02's and E29-D03's owners, reachable once BQ-9's field ships. Not T2: it never refuses.
 */
export function UpdatesPausedChip({
  newRows,
  closedRows,
  noSl = false,
  onApply,
  density,
}: UpdatesPausedChipProps): JSX.Element {
  const parts = [
    "Updates paused",
    ...(newRows > 0 ? [`${String(newRows)} new`] : []),
    ...(closedRows > 0 ? [`${String(closedRows)} closed`] : []),
  ];
  return (
    <button
      type="button"
      className="cv-positions-grid__paused cv-focus-ring"
      data-part="UpdatesPausedChip"
      data-tone={noSl ? "critical" : undefined}
      data-density={density}
      onClick={onApply}
    >
      {parts.join(" · ")}
    </button>
  );
}

/** One body row of the flattened tree, or the totals row. */
type Entry<R extends PositionsGridRow> =
  | {
      readonly kind: "group";
      readonly id: string;
      readonly group: PositionsGridGroup<R>;
      readonly tree: TableTreeRow;
      readonly baseCoin: string;
    }
  | {
      readonly kind: "position";
      readonly id: string;
      readonly row: R;
      readonly tree: TableTreeRow;
    }
  | { readonly kind: "totals"; readonly id: string; readonly totals: PositionsGridTotals };

/** A group's collapse key: its `key`, `""` for the positions with none. */
const collapseKey = (group: PositionsGridGroup<PositionsGridRow>): string => group.key ?? "";

/** The rows' names: "Select BTCUSDT Long on Main" (E29-D05 N-01) and the row's own (N-02, one environment). */
const accountOf = (row: PositionsGridRow): string => row.accountLabel ?? row.accountId;
const shortName = (row: PositionsGridRow): string =>
  `${row.symbol} ${row.sideWord} on ${accountOf(row)}`;

/** The column spec: its header words, its `<col>` width and its alignment. */
interface ColumnSpec {
  readonly header: string;
  readonly hint?: string;
  readonly numeric: boolean;
}

function specOf(id: PositionsGridColumnId, currency: string, narrow: boolean): ColumnSpec {
  const unit = `(${currency})`;
  switch (id) {
    case "account":
      return { header: "Account", numeric: false };
    case "symbol":
      return { header: "Symbol", numeric: false };
    case "side":
      return { header: "Side", numeric: false };
    case "size":
      return { header: "Size", numeric: true };
    case "entry":
      return { header: `Entry ${unit}`, numeric: true };
    case "mark":
      return { header: `Mark ${unit}`, numeric: true };
    case "upnl":
      // The dock's header keeps its unit in its name (D02 §11.5).
      return narrow
        ? { header: "uPnL", hint: unit, numeric: true }
        : { header: `uPnL ${unit}`, numeric: true };
    case "r":
      return { header: "R", numeric: true };
    case "rpnl_today":
      return { header: `rPnL today ${unit}`, numeric: true };
    case "liq_price":
      return { header: `Liq price ${unit}`, numeric: true };
    case "liq_dist":
      return { header: "Liq dist. %", numeric: true };
    case "leverage":
      return { header: "Lev", numeric: true };
    case "margin":
      return { header: "Margin", numeric: false };
    case "status":
      return { header: "Status", numeric: false };
  }
}

/** The grid's column order: the always-shown ones first (D02 §5.1: Account and Symbol; the dock: Symbol). */
function visibleColumns(
  asked: readonly PositionsGridColumnId[],
  narrow: boolean,
): readonly PositionsGridColumnId[] {
  const fixed: readonly PositionsGridColumnId[] = narrow ? ["symbol"] : ["account", "symbol"];
  return [...fixed, ...asked.filter((id) => !fixed.includes(id))];
}

const widthEmOf = (
  id: PositionsGridColumnId | "select" | "actions",
  narrow: boolean,
  comfortable: boolean,
): number => {
  const dock = narrow ? NARROW_PX[id as PositionsGridColumnId | "select"] : undefined;
  const px =
    dock !== undefined ? dock + (comfortable ? 8 : 0) : (WIDTH_PX[id][comfortable ? 1 : 0] ?? 96);
  return px / PX_PER_EM;
};

/** The tree, flattened through the open groups; each entry's place from the model (E29-D05 §5.3 F-03). */
function flatten<R extends PositionsGridRow>(
  groups: readonly PositionsGridGroup<R>[],
  closed: ReadonlySet<string>,
): readonly Entry<R>[] {
  const entries: Entry<R>[] = [];
  groups.forEach((group, g) => {
    const expanded = !closed.has(collapseKey(group));
    entries.push({
      kind: "group",
      id: `group:${collapseKey(group)}`,
      group,
      tree: { level: 1, expanded, posinset: g + 1, setsize: groups.length },
      baseCoin: group.rows[0]?.baseCoin ?? "",
    });
    if (!expanded) return;
    group.rows.forEach((row, i) => {
      entries.push({
        kind: "position",
        id: row.key,
        row,
        tree: { level: 2, posinset: i + 1, setsize: group.rows.length },
      });
    });
  });
  return entries;
}

interface RowParts<R extends PositionsGridRow> {
  readonly columns: readonly PositionsGridColumnId[];
  readonly selectable: boolean;
  readonly actions: boolean;
  readonly narrow: boolean;
  readonly density: "compact" | "comfortable";
  readonly currency: string;
  readonly selected: ReadonlySet<string>;
  readonly toggle: (key: string) => void;
  readonly selectAll: () => void;
  readonly rowActions: ((row: R) => SplitButtonProps | undefined) | undefined;
}

/**
 * The keys a row takes over CMP-049's: in a selectable grid `Space` on a cell toggles a position's selection and does
 * nothing on a group header or the totals, a handled key that never scrolls the region (a box's own Space is native);
 * `Ctrl+A` selects every position, drawn or not (D-3); and on the Actions cell's halves `←` / `→` move between them,
 * the roving model's two cells (D02 §11.1).
 */
function rowKeys(
  event: KeyboardEvent<HTMLTableRowElement>,
  parts: {
    readonly selectable: boolean;
    readonly selectAll: () => void;
    readonly toggle?: () => void;
  },
): void {
  if (event.defaultPrevented || !(event.target instanceof HTMLElement)) return;
  const target = event.target;
  if (event.ctrlKey && (event.key === "a" || event.key === "A")) {
    event.preventDefault();
    parts.selectAll();
    return;
  }
  if (event.ctrlKey || event.altKey || event.metaKey) return;
  const cell = target.closest<HTMLElement>("[data-cv-c]");
  if (event.key === " " && cell === target && parts.selectable) {
    event.preventDefault();
    parts.toggle?.();
    return;
  }
  const split = target.closest(".cv-split-button");
  if (split === null || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) return;
  const halves = [
    ...split.querySelectorAll<HTMLElement>("button.cv-button, button.cv-icon-button"),
  ];
  const next = halves[halves.indexOf(target) + (event.key === "ArrowRight" ? 1 : -1)];
  if (next === undefined) return;
  event.preventDefault();
  next.focus();
}

/** A position row (level 2): the select box, its cells in the visible order, and its actions. */
function PositionRow<R extends PositionsGridRow>({
  row,
  grid,
  parts,
}: {
  readonly row: R;
  readonly grid: TableRowContext;
  readonly parts: RowParts<R>;
}): JSX.Element {
  const sentenceId = useId();
  const sentence = liqSentence(row.liq);
  // One node carries the row's description, the tier's sentence: the first tier column's, else a hidden one of the
  // row's own, so a dropped column's value stays in it (D01 D1) and no id is ever drawn twice.
  const describer = parts.columns.find((id) => id === "liq_dist" || id === "status");
  const isSelected = parts.selected.has(row.key);
  const lead = parts.selectable ? 1 : 0;
  const size = shown(row.size) ?? row.size;
  const cell = (id: PositionsGridColumnId, i: number): JSX.Element => {
    const c = i + lead;
    // CMP-116 sets its own type; the plain numeric cells set theirs in `type.num.base` (D02 §12, D-8).
    const money = { numeric: true };
    const figure = { numeric: true, className: "cv-positions-grid__num" };
    switch (id) {
      case "account":
        return (
          <td
            key={id}
            {...grid.cellProps(c, { cut: accountOf(row), className: "cv-positions-grid__account" })}
          >
            {accountOf(row)}
          </td>
        );
      case "symbol":
        return (
          <th key={id} {...grid.cellProps(c, { header: true })}>
            {row.symbol}
            {describer !== undefined || sentence === undefined ? null : (
              <span id={sentenceId} hidden>
                {sentence}
              </span>
            )}
          </th>
        );
      case "side":
        return (
          <td key={id} {...grid.cellProps(c)}>
            <span className="cv-positions-grid__side-glyph" data-side={row.side} aria-hidden="true">
              {SIDE_GLYPH[row.side]}
            </span>{" "}
            {row.sideWord}
            {row.hedge && !parts.narrow ? " · hedge" : null}
          </td>
        );
      case "size":
        return (
          <td key={id} {...grid.cellProps(c, figure)}>
            {size}
            {/* The base coin: a suffix in `color.text.secondary`; in the dock it leaves and stays in the name. */}
            <span className={parts.narrow ? "cv-visually-hidden" : "cv-positions-grid__unit"}>
              {` ${row.baseCoin}`}
            </span>
          </td>
        );
      case "entry":
      case "mark":
      case "liq_price": {
        const value = id === "entry" ? row.entry : id === "mark" ? row.mark : row.liqPrice;
        const text = shown(value);
        return (
          <td key={id} {...grid.cellProps(c, figure)}>
            {text ?? dash(id === "liq_price" ? NO_LIQ : NO_VALUE)}
          </td>
        );
      }
      case "upnl":
        return (
          <td key={id} {...grid.cellProps(c, money)}>
            <PnLBadge value={row.unrealisedPnl} format="abs" currency={parts.currency} />
          </td>
        );
      case "r": {
        const reading = rReading(row.r);
        return (
          <td key={id} {...grid.cellProps(c, money)}>
            <PnLBadge
              value={row.r.value}
              format="r"
              places={2}
              {...(reading === undefined ? {} : { nullReading: reading })}
            />
          </td>
        );
      }
      case "rpnl_today":
        return (
          <td key={id} {...grid.cellProps(c, money)}>
            <PnLBadge value={row.realisedToday.value} format="abs" currency={parts.currency} />
          </td>
        );
      case "liq_dist":
        return (
          <td key={id} {...grid.cellProps(c, { ...figure, echo: sentence })}>
            <LiqTierCell
              liq={row.liq}
              sentenceId={describer === "liq_dist" ? sentenceId : undefined}
            />
          </td>
        );
      case "leverage": {
        const lev = shown(row.leverage);
        return (
          <td key={id} {...grid.cellProps(c, figure)}>
            {lev === null ? dash(NO_VALUE) : `${lev}×`}
          </td>
        );
      }
      case "margin":
        return (
          <td key={id} {...grid.cellProps(c)}>
            {row.marginMode.value === null ? dash(NO_VALUE) : MARGIN_WORDS[row.marginMode.value]}
          </td>
        );
      case "status":
        return (
          <td key={id} {...grid.cellProps(c, { echo: sentence })}>
            <LiqTierCell
              liq={row.liq}
              form="status"
              sentenceId={describer === "status" ? sentenceId : undefined}
            />
          </td>
        );
    }
  };
  const actionsAt = lead + parts.columns.length;
  const split = parts.actions ? parts.rowActions?.(row) : undefined;
  return (
    <tr
      {...grid.rowProps}
      className={cx(grid.rowProps.className, "cv-positions-grid__row")}
      aria-label={`${row.symbol} · ${row.sideWord} · ${size} ${row.baseCoin} · ${accountOf(row)}`}
      aria-describedby={sentence === undefined ? undefined : sentenceId}
      aria-selected={parts.selectable ? isSelected : undefined}
      data-liq={row.liq.tier}
      onKeyDown={(event) =>
        rowKeys(event, {
          selectable: parts.selectable,
          selectAll: parts.selectAll,
          toggle: () => parts.toggle(row.key),
        })
      }
    >
      {parts.selectable ? (
        <td {...grid.cellProps(0, { widget: true, className: "cv-positions-grid__select" })}>
          <Checkbox
            label={`Select ${shortName(row)}`}
            checked={isSelected}
            onChange={() => parts.toggle(row.key)}
            tabIndex={grid.tabIndexOf(0)}
            density={parts.density}
          />
        </td>
      ) : null}
      {parts.columns.map(cell)}
      {parts.actions ? (
        <td
          {...grid.cellProps(actionsAt, {
            interactive: true,
            className: "cv-positions-grid__actions",
          })}
        >
          {split === undefined ? null : <SplitButton {...split} density={parts.density} />}
        </td>
      ) : null}
    </tr>
  );
}

/**
 * CMP-114's `GroupHeaderRow` (E29-D04 §2.1 frame `group-header`; D02 §5.5, D-15): a level-1 row whose one cell, its
 * rowheader and its tree cell, reads "▾ Main · LIVE · One-way · 1 position · uPnL +8.00 · rPnL today +37.40", then the
 * host's state marker when one applies (`marker`); → and ← (or a click) open and close it (CMP-049's treegrid), the ▸ /
 * ▾ and `aria-expanded` carrying the state (Mo-10). The net size shows only for a group on one symbol (#911 BQ-12). The
 * Actions cell stays empty: Flatten account… mounts with the ticket that wires it (BQ-3).
 */
function GroupHeaderRow<R extends PositionsGridRow>({
  entry,
  grid,
  parts,
}: {
  readonly entry: Extract<Entry<R>, { kind: "group" }>;
  readonly grid: TableRowContext;
  readonly parts: RowParts<R>;
}): JSX.Element {
  const { group } = entry;
  const span = parts.columns.length + (parts.selectable ? 1 : 0);
  const net = shown(group.netSize);
  return (
    <tr
      {...grid.rowProps}
      className={cx(grid.rowProps.className, "cv-positions-grid__group")}
      data-part="GroupHeaderRow"
      onKeyDown={(event) =>
        rowKeys(event, { selectable: parts.selectable, selectAll: parts.selectAll })
      }
    >
      <th
        {...grid.cellProps(0, { header: true, span, className: "cv-positions-grid__group-cell" })}
      >
        <span className="cv-positions-grid__disclosure">
          <Icon name={entry.tree.expanded === true ? "chevron-down" : "chevron-right"} />
        </span>
        <span className="cv-positions-grid__group-label">{group.label}</span>
        {group.positionMode === undefined ? null : (
          <>
            {" · "}
            <PositionModeToggle value={group.positionMode} />
          </>
        )}
        {` · ${positionsWord(group.count)}`}
        {net === null ? null : ` · net ${net} ${entry.baseCoin}`}
        {" · uPnL "}
        <PnLBadge value={group.unrealisedPnl} format="abs" currency={parts.currency} />
        {" · rPnL today "}
        <PnLBadge value={group.realisedToday} format="abs" currency={parts.currency} />
        {group.marker == null ? null : (
          <>
            {" · "}
            {group.marker}
          </>
        )}
      </th>
      {parts.actions ? <td {...grid.cellProps(span)} /> : null}
    </tr>
  );
}

/**
 * CMP-114's `TotalsRow` (E29-D04 §2.1 frame `totals-row`; D02 §5.2, D-15): CMP-049's trailing rowgroup, pinned, led by
 * its rowheader "LIVE total" with the count and the exposure in the label's span ("LIVE total · 5 open · Exposure
 * 34,322.66 USDT"), its uPnL and rPnL today under their columns; never a size summed across symbols. What has no place
 * on the row is in its tooltip (the label's echo) and its description: Net (D-15, D01 D1), a total whose column is not
 * shown, and in the 360 px dock the exposure, the label keeping its count alone there, so no numeral is ever cut (D02
 * §11.5, D-8).
 */
function TotalsRow<R extends PositionsGridRow>({
  totals,
  grid,
  parts,
}: {
  readonly totals: PositionsGridTotals;
  readonly grid: TableRowContext;
  readonly parts: RowParts<R>;
}): JSX.Element {
  const descriptionId = useId();
  const lead = parts.selectable ? 1 : 0;
  const unit = parts.currency;
  /** A plain figure as the label shows it ("34,322.66 USDT", "— USDT") and as it is said ("no value" for a dash). */
  const plain = (value: string | null): { readonly shown: string; readonly said: string } => {
    const text = shown(value);
    return text === null
      ? { shown: `— ${unit}`, said: NO_VALUE }
      : { shown: `${text} ${unit}`, said: `${text} ${unit}` };
  };
  /** A P&L as CMP-116 shows it ("+34.40 USDT") and says it ("profit 34.40 USDT"). */
  const pnl = (value: string | null): { readonly shown: string; readonly said: string } => {
    const signed = value === null ? null : formatDecimal(value, { plus: true });
    return {
      shown: `${signed?.text ?? "—"} ${unit}`,
      said: pnlReading({ value, format: "abs", currency: unit }),
    };
  };
  const aside = [
    ...(parts.narrow ? [{ label: "Exposure", ...plain(totals.exposure) }] : []),
    ...(totals.net === undefined ? [] : [{ label: "Net", ...plain(totals.net) }]),
    ...(parts.columns.includes("upnl") ? [] : [{ label: "uPnL", ...pnl(totals.unrealisedPnl) }]),
    ...(parts.columns.includes("rpnl_today")
      ? []
      : [{ label: "rPnL today", ...pnl(totals.realisedToday) }]),
  ];
  const count = `· ${String(totals.count)} open`;
  // The label spans the columns before the first money column it carries.
  const sums = parts.columns
    .map((id, i) => ({ id, c: i + lead }))
    .filter(({ id }) => id === "upnl" || id === "rpnl_today");
  const labelSpan = sums[0]?.c ?? lead + parts.columns.length;
  const cells: JSX.Element[] = [];
  let at = labelSpan;
  for (const { id, c } of sums) {
    if (c > at)
      cells.push(<td key={`gap-${String(c)}`} {...grid.cellProps(at, { span: c - at })} />);
    cells.push(
      <td key={id} {...grid.cellProps(c, { numeric: true })}>
        <PnLBadge
          value={id === "upnl" ? totals.unrealisedPnl : totals.realisedToday}
          format="abs"
          currency={unit}
        />
      </td>,
    );
    at = c + 1;
  }
  const end = lead + parts.columns.length + (parts.actions ? 1 : 0);
  if (end > at) cells.push(<td key="rest" {...grid.cellProps(at, { span: end - at })} />);
  return (
    <tr
      {...grid.rowProps}
      className={cx(grid.rowProps.className, "cv-positions-grid__totals")}
      data-part="TotalsRow"
      aria-describedby={aside.length === 0 ? undefined : descriptionId}
      onKeyDown={(event) =>
        rowKeys(event, { selectable: parts.selectable, selectAll: parts.selectAll })
      }
    >
      <th
        {...grid.cellProps(0, {
          header: true,
          span: labelSpan,
          echo: aside.map((part) => `${part.label} ${part.shown}`).join(" · "),
        })}
      >
        {/* The space is the cell's own text: at the span's edge, a name that trims each element's words drops it. */}
        {`${totals.label} `}
        <span className="cv-positions-grid__totals-span">
          {parts.narrow ? count : `${count} · Exposure ${plain(totals.exposure).shown}`}
        </span>
        {aside.length === 0 ? null : (
          // Hidden, so the label's name stays its own words; the row's description reads it whole.
          <span id={descriptionId} hidden>
            {aside.map((part) => `${part.label} ${part.said}`).join(" · ")}
          </span>
        )}
      </th>
      {cells}
    </tr>
  );
}

/**
 * CMP-114 PositionsGrid (E29-D04 §2.1, D04H §C.1; E29-D02 §5; E29-D05 §5–§7): SCR-063's Positions tab as a CMP-049
 * `treegrid`, presentational: the host's groups, rows and totals in, selection, open groups and sort out. Account
 * groups (or symbols, or trade groups) at level 1 open on their positions at level 2, `aria-posinset` and
 * `aria-setsize` from the model; a select column (CMP-005, kept at every width, D-3), Account and Symbol pinned
 * (Symbol the rowheader), the liquidation tier as glyph, word and distance (`LiqTierCell`), every signed money cell a
 * CMP-116, and the totals in CMP-049's pinned trailing rowgroup (`TotalsRow`). Rows past 50 are windowed, the focused
 * row kept mounted outside the window (G-01). A row's name is "BTCUSDT · Long · 0.250 BTC · Main" (N-02), its
 * description its tier's sentence. Row updates are never announced here: the host's regions speak (D02 §11.4). The
 * Actions column (CMP-057 per row, its T2 gates the host's, a scope's reason pointing at the host's one notice) shows
 * only with `rowActions`, which the row menu repeats; the dock keeps the row menu alone (D-12). No motion of its own:
 * every state swap is a cut (Mo-8, Mo-10).
 */
export function PositionsGrid<R extends PositionsGridRow = PositionsGridRow>({
  caption,
  captionHidden = false,
  groups,
  totals,
  columns: askedColumns,
  variant = "default",
  density = "compact",
  currency = "USDT",
  selected,
  onSelectionChange,
  collapsed,
  onCollapsedChange,
  sort,
  onSortChange,
  rowActions,
  loading = false,
  loadingText,
  emptyState,
  announce,
}: PositionsGridProps<R>): JSX.Element {
  const narrow = variant === "narrow";
  const comfortable = density === "comfortable";
  const columns = visibleColumns(
    askedColumns ?? (narrow ? POSITIONS_GRID_NARROW_COLUMNS : POSITIONS_GRID_COLUMNS),
    narrow,
  );
  const selectable = onSelectionChange !== undefined;
  const actions = rowActions !== undefined && !narrow;
  const [ownClosed, setOwnClosed] = useState<ReadonlySet<string>>(new Set());
  const closed = collapsed ?? ownClosed;
  const entries = useMemo(() => flatten(groups, closed), [groups, closed]);
  const indexOf = useMemo(() => new Map(entries.map((entry, i) => [entry.id, i])), [entries]);
  // The window (CMP-049's host side): the rows in view and OVERSCAN either side, from WINDOW_FROM rows, kept while
  // the reported view stays clear of its edges (`keepsDrawn`).
  const [view, setView] = useState<RowSpan>({ first: 0, last: FIRST_WINDOW - 1 });
  const windowed = entries.length > WINDOW_FROM;
  const drawn = windowed ? drawnFor(view, entries.length) : { first: 0, last: entries.length - 1 };
  const selection = selected ?? new Set<string>();
  const allKeys = (): string[] => groups.flatMap((group) => group.rows.map((row) => row.key));
  const parts: RowParts<R> = {
    columns,
    selectable,
    actions,
    narrow,
    density,
    currency,
    selected: selection,
    toggle: (key) => {
      const next = new Set(selection);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      onSelectionChange?.(next);
    },
    selectAll: () => onSelectionChange?.(new Set(allKeys())),
    rowActions,
  };
  const setClosed = (next: ReadonlySet<string>): void => {
    if (collapsed === undefined) setOwnClosed(next);
    onCollapsedChange?.(next);
  };
  const tableColumns: TableColumn<Entry<R>>[] = [
    ...(selectable
      ? [
          {
            id: "select",
            header: "Select",
            cell: (entry: Entry<R>) => entry.id,
            widthEm: widthEmOf("select", narrow, comfortable),
          },
        ]
      : []),
    ...columns.map((id): TableColumn<Entry<R>> => {
      const spec = specOf(id, currency, narrow);
      return {
        id,
        header: spec.header,
        ...(spec.hint === undefined ? {} : { headerHint: spec.hint }),
        cell: (entry: Entry<R>) => entry.id,
        ...(spec.numeric ? { align: "end" as const } : {}),
        sortable: id !== "status",
        widthEm: widthEmOf(id, narrow, comfortable),
      };
    }),
    ...(actions
      ? [
          {
            id: "actions",
            header: "Actions",
            cell: (entry: Entry<R>) => entry.id,
            widthEm: widthEmOf("actions", narrow, comfortable),
          },
        ]
      : []),
  ];
  const pinned = (selectable ? 1 : 0) + (narrow ? 1 : 2);
  // The row menu repeats CMP-057 (E29-D05 §6.3): its primary first, then the ▾'s items. As on the button, the gate
  // wins over busy, and a busy primary is a busy item: its busy label, `aria-busy`, never activated (D02 §8.1).
  const menuOf = (row: R): readonly MenuItem[] => {
    const split = rowActions?.(row);
    if (split === undefined) return [];
    const gate =
      reasonText(split.disabledReason) ??
      (split.allowed === false ? reasonText(split.reason) : undefined);
    const busy = split.busy === true && gate === undefined;
    return [
      {
        id: "primary",
        label: busy ? (split.primary.busyLabel ?? split.primary.label) : split.primary.label,
        onSelect: split.primary.onClick,
        ...(gate === undefined ? {} : { disabledReason: gate }),
        ...(busy ? { busy: true } : {}),
      },
      ...split.items,
    ];
  };
  return (
    <div
      className="cv-positions-grid"
      data-cmp="CMP-114"
      data-variant={variant}
      data-density={density}
      data-select={selectable ? "" : undefined}
      data-actions={actions ? "" : undefined}
    >
      <Table<Entry<R>>
        treegrid
        caption={caption}
        captionHidden={captionHidden}
        columns={tableColumns}
        rows={entries.slice(drawn.first, drawn.last + 1)}
        rowKey={(entry) => entry.id}
        treeRow={(entry) =>
          entry.kind === "totals" ? { level: 1, posinset: 1, setsize: 1 } : entry.tree
        }
        onExpandedChange={(entry, expanded) => {
          if (entry.kind !== "group") return;
          const next = new Set(closed);
          if (expanded) next.delete(collapseKey(entry.group));
          else next.add(collapseKey(entry.group));
          setClosed(next);
        }}
        multiselectable={selectable}
        density={density}
        loading={loading}
        {...(loadingText === undefined ? {} : { loadingText })}
        emptyState={emptyState}
        sort={sort}
        {...(onSortChange === undefined ? {} : { onSortChange })}
        announce={announce}
        stickyFirstColumn={pinned}
        stickyLastColumn={actions}
        totalRows={totals === undefined ? undefined : [{ kind: "totals", id: "totals", totals }]}
        rowLabel={(entry) =>
          entry.kind === "position"
            ? shortName(entry.row)
            : entry.kind === "group"
              ? entry.group.label
              : entry.totals.label
        }
        {...(rowActions === undefined
          ? {}
          : {
              // Every position's row menu, the dock's too; a group header or the totals offers none (yet).
              rowActions: (entry: Entry<R>) => (entry.kind === "position" ? menuOf(entry.row) : []),
            })}
        {...(windowed
          ? {
              rowWindow: { offset: drawn.first, total: entries.length },
              onRowsInView: (first: number, last: number) =>
                setView((was) =>
                  keepsDrawn(drawnFor(was, entries.length), { first, last }, entries.length)
                    ? was
                    : { first, last },
                ),
              rowByKey: (key: string) => {
                const index = indexOf.get(key);
                const row = index === undefined ? undefined : entries[index];
                return index === undefined || row === undefined ? undefined : { row, index };
              },
            }
          : {})}
        renderRow={(entry, grid) =>
          entry.kind === "group" ? (
            <GroupHeaderRow entry={entry} grid={grid} parts={parts} />
          ) : entry.kind === "position" ? (
            <PositionRow row={entry.row} grid={grid} parts={parts} />
          ) : (
            <TotalsRow totals={entry.totals} grid={grid} parts={parts} />
          )
        }
      />
    </div>
  );
}
