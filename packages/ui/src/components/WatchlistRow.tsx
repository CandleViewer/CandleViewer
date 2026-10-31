import { useId, type JSX, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";
import { Icon } from "../icons/Icon.js";
import { FreshnessMarker, freshnessClassName } from "./FreshnessMarker.js";
import type { TableColumn, TableHeaderStatus, TableRowContext } from "./Table.js";
import { cx } from "./internal/cx.js";
import {
  NO_VALUE,
  formatCountdown,
  formatFundingPct,
  formatSigFigs,
  formatSignedPct,
  formatSpreadBps,
  formatUtcTime,
  formatWatchlistPrice,
} from "./internal/watchlistFormat.js";

/** The default columns (E08-D07 D8, §4.1), in their order: Symbol is locked first; the Status slot always follows. */
export const WATCHLIST_DEFAULT_COLUMNS = [
  "symbol",
  "last",
  "chg_24h_pct",
  "turnover_24h",
  "funding_rate",
  "next_funding",
  "oi_chg_24h_pct",
  "spread_bps",
  "rec",
] as const;

/** The optional columns, off by default (E08-D07 §4.1): every one of them in the ticker group. */
export const WATCHLIST_OPTIONAL_COLUMNS = [
  "volume_24h",
  "open_interest_value",
  "mark_price",
  "index_price",
  "bid1_price",
  "ask1_price",
  "high_24h",
  "low_24h",
] as const;

export type WatchlistDefaultColumnId = (typeof WATCHLIST_DEFAULT_COLUMNS)[number];
export type WatchlistOptionalColumnId = (typeof WATCHLIST_OPTIONAL_COLUMNS)[number];
/** A column's stored id (D8): a list's columns are these strings; an unknown one is skipped on read. */
export type WatchlistColumnId = WatchlistDefaultColumnId | WatchlistOptionalColumnId;

type SlotId = WatchlistColumnId | "status";

interface ColumnSpec {
  readonly header: string;
  /** E08-D07 §4.1's width (DJ) in `em` of the table's 16 px: the `<col>` width and the reflow minimum. */
  readonly widthEm: number;
  readonly numeric: boolean;
  /** The ticker group: "—" before a first value, merged on a delisted row, T2 under a live sort past the budget. */
  readonly live: boolean;
}

/**
 * The column registry (E08-D07 §4.1). "High 24h" and "Low 24h" are PROPOSED (E08-D07 names only their ids). The
 * widths are §4.1's but for Symbol and Turnover, measured in the pinned faces (Inter 4.0 at `type.ui.label`, with
 * CMP-049's 8 px cell padding): a delisted LUNAUSDT and its lock need 102 px and "Turnover USDT" 104, so both take
 * 6.5 em, and the reference holds its 784 px (49 em) as 24h %, Funding %, OI Δ and Spread give 0.25 em each. Every
 * default header and value needs 799 px whole, so at 784 "Funding %", "OI Δ 24h %" and "Spread bps" are cut, the
 * echo showing them whole. The interim (orchestrator, 2026-10-31) is CMP-049's: an end-aligned header uses its start
 * padding as room. They need 61.3, 64.7 and 65.5 px against the 60 px that leaves, so they stay cut and keep the
 * ellipsis and the echo; the lasting answer, shorter headers or a wider reference, is a C-row for E08-D07's owner.
 */
const SPEC: Readonly<Record<SlotId, ColumnSpec>> = {
  symbol: { header: "Symbol", widthEm: 6.5, numeric: false, live: false },
  last: { header: "Last", widthEm: 5, numeric: true, live: true },
  chg_24h_pct: { header: "24h %", widthEm: 4.25, numeric: true, live: true },
  turnover_24h: { header: "Turnover USDT", widthEm: 6.5, numeric: true, live: true },
  funding_rate: { header: "Funding %", widthEm: 4.25, numeric: true, live: true },
  next_funding: { header: "Funding in", widthEm: 5, numeric: true, live: true },
  oi_chg_24h_pct: { header: "OI Δ 24h %", widthEm: 4.25, numeric: true, live: true },
  spread_bps: { header: "Spread bps", widthEm: 4.25, numeric: true, live: true },
  rec: { header: "Rec", widthEm: 3, numeric: false, live: false },
  volume_24h: { header: "Volume 24h", widthEm: 5, numeric: true, live: true },
  open_interest_value: { header: "OI USDT", widthEm: 5, numeric: true, live: true },
  mark_price: { header: "Mark", widthEm: 5, numeric: true, live: true },
  index_price: { header: "Index", widthEm: 5, numeric: true, live: true },
  bid1_price: { header: "Bid", widthEm: 5, numeric: true, live: true },
  ask1_price: { header: "Ask", widthEm: 5, numeric: true, live: true },
  high_24h: { header: "High 24h", widthEm: 5, numeric: true, live: true },
  low_24h: { header: "Low 24h", widthEm: 5, numeric: true, live: true },
  status: { header: "Status", widthEm: 6, numeric: false, live: false },
};

/** The row's slots: the known columns in their order, each once, then the fixed Status slot. */
const slotsOf = (columns: readonly string[]): readonly SlotId[] => {
  const seen = new Set<string>();
  const known = columns.filter((id): id is WatchlistColumnId => {
    if (id === "status" || seen.has(id) || !Object.hasOwn(SPEC, id)) return false;
    seen.add(id);
    return true;
  });
  return [...known, "status"];
};

/** The words of the delisted state (E08-D04 §3, `delisted`; `14` L2037): the merged cell and its T2 reason. */
const DELISTED = "Delisted by the exchange";

/** A row's state (E08-D07 D7, D20): `initialising` and `not-live` show no value, so they claim no freshness. */
export type WatchlistRowState = "live" | "initialising" | "not-live" | "delisted";

/** The ticker group's freshness (E08-D07 D1): every live column goes stale together. */
export interface WatchlistTickerFreshness {
  readonly state: "live" | "stale";
  /** The age of the symbol's last value: the chip's "Stale 7s". */
  readonly ageMs?: number;
  /** Past T2 (15 s): the strong chip. */
  readonly escalated?: boolean;
  /** `meta.stale` or a per-item `stale`: "Stale (server)", the T1 style until T2 (E17-D01 L149). */
  readonly server?: boolean;
  /** The chip's echo (hover and focus): "Last update 10:31:02 UTC", or the exchange-feed-down sentence (D28). */
  readonly detail?: string;
}

/** OI Δ's REST baseline (E08-D07 D21): stale on its own, its column's cells only. */
export interface WatchlistOiFreshness {
  readonly state: "live" | "stale";
  /** The footer line that says why: the stale cells' description. */
  readonly noteId?: string;
}

/** The row's sources (E08-D07 §4.1): Rec's changes are events, so it has none of its own. */
export interface WatchlistFreshness {
  readonly ticker?: WatchlistTickerFreshness;
  readonly oiBaseline?: WatchlistOiFreshness;
}

/**
 * The Rec cell (E08-D07 §4.2 REC states; E16-S02 fills it): absent, nothing; `restricted`, the lock named "Recording
 * status restricted"; a chip, its compact form drawn and its full text read.
 */
export type WatchlistRec =
  | { readonly kind: "restricted" }
  | {
      readonly kind: "chip";
      readonly compact: string;
      readonly full: string;
      /** "REC ⚠" and "— ⚠": the compact form's ⚠ in `color.status.warning.strong`. */
      readonly warning?: boolean;
    };

/**
 * One symbol's values (E08-D07 §4.1): percentages are percentage points (the wire fraction × 100), prices at
 * `priceScale`. An absent value is "—".
 */
export interface WatchlistRowData {
  readonly symbol: string;
  readonly priceScale: number;
  readonly lastPrice?: number;
  readonly pctChange24h?: number;
  /** USDT. */
  readonly turnover24h?: number;
  readonly fundingRate?: number;
  readonly nextFundingTimeMs?: number;
  /** `null`: no point 24 h back, "—" named "no 24 h baseline" (D21). */
  readonly openInterestChangePct24h?: number | null;
  readonly spreadBps?: number;
  /** Base coin. */
  readonly volume24h?: number;
  /** USDT. */
  readonly openInterestValue?: number;
  readonly markPrice?: number;
  readonly indexPrice?: number;
  readonly bid1Price?: number;
  readonly ask1Price?: number;
  readonly high24h?: number;
  readonly low24h?: number;
  readonly rec?: WatchlistRec;
}

/** How `watchlistColumns` builds CMP-049's columns. */
export interface WatchlistColumnsOptions<T> {
  /** The table's row → its values; the row itself by default. */
  readonly item?: (row: T) => WatchlistRowData;
  /** A sort button on every column but Status (the host sorts, E08-D07 D5). */
  readonly sortable?: boolean;
  /** Live sort past the live budget (D5, §6.7): T2 on every live column's header, with this reason. */
  readonly liveSortReason?: string;
  /** OI Δ's own sort gate (from C-11 until C-8, §6.7): T2 on its header alone. */
  readonly oiSortReason?: string;
  /** The OI baseline is stale (D21): "⚠" on OI Δ's header, its name adding "stale". */
  readonly oiStale?: boolean;
}

const STALE_HEADER: TableHeaderStatus = { icon: "warning", label: "stale", tone: "stale" };
/** A cell's content and the words its echo shows. */
interface CellView {
  readonly content: ReactNode;
  readonly echo?: string;
}

/** "—" read as `word` (E08-D07 §4.2: "no value yet", "no 24 h baseline"): never as a dash. */
const dash = (word: string): JSX.Element => (
  <>
    <span className="cv-wl__dash" aria-hidden="true">
      {NO_VALUE}
    </span>
    <span className="cv-visually-hidden">{word}</span>
  </>
);

const plain = (text: string): JSX.Element =>
  text === NO_VALUE ? dash("no value") : <span className="cv-wl__value">{text}</span>;

/** D9's signed percentages: the sign is the text channel; ▲/▼ go with it, hidden and coloured by the sign. */
const signedView = (points: number | undefined): ReactNode => {
  if (points === undefined) return dash("no value");
  const shown = formatSignedPct(points);
  return (
    <>
      {shown.glyph === "" ? null : (
        <>
          <span className="cv-wl__glyph" data-sign={shown.sign} aria-hidden="true">
            {shown.glyph}
          </span>{" "}
        </>
      )}
      <span className="cv-wl__value">{shown.text}</span>
    </>
  );
};

/** Three significant figures drawn, the whole number read (D9: "1.20B", named "1,200,000,000 USDT"). */
const sizedView = (value: number | undefined, unit: string): ReactNode => {
  if (value === undefined) return dash("no value");
  const { text, full } = formatSigFigs(value);
  return (
    <>
      <span className="cv-wl__value" aria-hidden="true">
        {text}
      </span>
      <span className="cv-visually-hidden">{unit === "" ? full : `${full} ${unit}`}</span>
    </>
  );
};

/** D22: whole seconds on the shared clock; the name and the echo add the target in UTC; at zero, "Settling…". */
const countdownView = (target: number | undefined, now: number | undefined): CellView => {
  if (target === undefined || now === undefined) return { content: dash("no value") };
  const left = formatCountdown(target - now);
  if (left === undefined) return { content: <span className="cv-wl__value">Settling…</span> };
  const at = `at ${formatUtcTime(target)}`;
  return {
    content: (
      <>
        <span className="cv-wl__value">{left}</span>
        <span className="cv-visually-hidden"> {at}</span>
      </>
    ),
    echo: at,
  };
};

/** The Rec slot (E16-S02's data): nothing, the restricted lock, or the compact chip read as its full text. */
const recView = (rec: WatchlistRec | undefined): ReactNode => {
  if (rec === undefined) return null;
  if (rec.kind === "restricted")
    return (
      <span className="cv-wl__rec-lock">
        <Icon name="lock" decorative={false} label="Recording status restricted" />
      </span>
    );
  return (
    <span className="cv-wl__rec-chip">
      <span aria-hidden="true">
        {rec.compact}
        {rec.warning === true ? (
          <span className="cv-wl__rec-warning">
            <Icon name="warning" />
          </span>
        ) : null}
      </span>
      <span className="cv-visually-hidden">{rec.full}</span>
    </span>
  );
};

const price = (value: number | undefined, row: WatchlistRowData): CellView => ({
  content: plain(formatWatchlistPrice(value, row.priceScale)),
});

/** A slot's content, D9's formats. */
function viewOf(slot: SlotId, row: WatchlistRowData, now: number | undefined): CellView {
  switch (slot) {
    case "symbol":
      return { content: row.symbol };
    case "last":
      return price(row.lastPrice, row);
    case "chg_24h_pct":
      return { content: signedView(row.pctChange24h) };
    case "turnover_24h":
      return { content: sizedView(row.turnover24h, "USDT") };
    case "funding_rate":
      return {
        content:
          row.fundingRate === undefined
            ? dash("no value")
            : plain(formatFundingPct(row.fundingRate)),
      };
    case "next_funding":
      return countdownView(row.nextFundingTimeMs, now);
    case "oi_chg_24h_pct":
      return {
        content:
          row.openInterestChangePct24h === null
            ? dash("no 24 h baseline")
            : signedView(row.openInterestChangePct24h),
      };
    case "spread_bps":
      return {
        content:
          row.spreadBps === undefined ? dash("no value") : plain(formatSpreadBps(row.spreadBps)),
      };
    case "volume_24h":
      return { content: sizedView(row.volume24h, "") };
    case "open_interest_value":
      return { content: sizedView(row.openInterestValue, "USDT") };
    case "mark_price":
      return price(row.markPrice, row);
    case "index_price":
      return price(row.indexPrice, row);
    case "bid1_price":
      return price(row.bid1Price, row);
    case "ask1_price":
      return price(row.ask1Price, row);
    case "high_24h":
      return price(row.high24h, row);
    case "low_24h":
      return price(row.low24h, row);
    case "rec":
      return { content: recView(row.rec) };
    case "status":
      return { content: null };
  }
}

/**
 * CMP-161's columns as CMP-049's (E08-D07 §4.1): the known ids in their order, each once, then the fixed Status
 * slot; numbers end-aligned; D07's widths (DJ) as `<col>` widths and the reflow minimums. A column's `cell` draws
 * the same values as the row (the table's own rows, and the row menu's name from Symbol).
 */
export function watchlistColumns(
  columns: readonly string[],
  options?: WatchlistColumnsOptions<WatchlistRowData>,
): TableColumn<WatchlistRowData>[];
export function watchlistColumns<T>(
  columns: readonly string[],
  options: WatchlistColumnsOptions<T> & { readonly item: (row: T) => WatchlistRowData },
): TableColumn<T>[];
export function watchlistColumns<T>(
  columns: readonly string[],
  options: WatchlistColumnsOptions<T> = {},
): TableColumn<T>[] {
  // Without `item` the first overload holds: the rows are the values themselves.
  const item = options.item ?? ((row: T): WatchlistRowData => row as unknown as WatchlistRowData);
  return slotsOf(columns).map((slot): TableColumn<T> => {
    const spec = SPEC[slot];
    const sortable = options.sortable === true && slot !== "status";
    const reason = !sortable
      ? undefined
      : spec.live
        ? (options.liveSortReason ?? (slot === "oi_chg_24h_pct" ? options.oiSortReason : undefined))
        : undefined;
    return {
      id: slot,
      header: spec.header,
      widthEm: spec.widthEm,
      minWidthEm: spec.widthEm,
      ...(spec.numeric ? { align: "end" as const } : {}),
      ...(sortable ? { sortable: true } : {}),
      ...(reason === undefined ? {} : { sortDisabledReason: reason }),
      ...(slot === "oi_chg_24h_pct" && options.oiStale === true
        ? { headerStatus: STALE_HEADER }
        : {}),
      cell: (row: T) => viewOf(slot, item(row), undefined).content,
    };
  });
}

/** CMP-161's props: one interactive-grid row over the column registry (E08-D07 §5). */
export interface WatchlistRowProps {
  /** CMP-049's row contract: `renderRow`'s second argument. */
  readonly grid: TableRowContext;
  readonly row: WatchlistRowData;
  /** The list's columns, as given to `watchlistColumns`: the same slots, the Status slot last. */
  readonly columns: readonly string[];
  readonly freshness?: WatchlistFreshness;
  /** Default `live`. */
  readonly rowState?: WatchlistRowState;
  /** The shared 1 Hz clock's server time (D22): every countdown renders on its tick, never a timer per row. */
  readonly nowMs?: number;
  /** The activated symbol (D11): `aria-current`, the selected fill and the 2 px bar. */
  readonly active?: boolean;
  /** The row header's description, such as the active row's "Shows in group A" (proposed, E08-D07 §4.2). */
  readonly description?: string;
  /** A not-live row's why, in its chip's echo (E08-D07 §4.2 "Not live"). */
  readonly notLiveDetail?: string;
  /** Ids every value cell adds to its description: the panel status while disconnected (E08-D07 D4). */
  readonly describedBy?: string;
  /** A click or `Enter` (D11); a delisted row refuses it with its reason (D20). */
  readonly onActivate?: () => void;
  /** `Alt+↑`/`Alt+↓` (§6.4). */
  readonly onMove?: (direction: "up" | "down") => void;
  /** A direction's T2 reason (sorted, filtered, an end, read-only: §6.7): the key re-shows it and moves nothing. */
  readonly moveReason?: { readonly up?: string; readonly down?: string };
  /** `Del`: a held key removes one (§6.2). */
  readonly onRemove?: () => void;
  /** Read-only (§4.2): `Del` re-shows it and removes nothing. */
  readonly removeReason?: string;
  /**
   * `Ctrl+C` with no text selected in the grid: the host copies `symbol` and says so. A non-empty selection that
   * reaches into the grid is left to the browser, which copies it; a stale one elsewhere in the document does not
   * stop the key.
   */
  readonly onCopy?: (symbol: string) => void;
}

/**
 * Whether text is selected that reaches into the grid `row` sits in (the browser's copy is then the user's): a
 * selection elsewhere in the document is stale for this key, and a collapsed or empty one holds no text.
 */
const selectedInGrid = (row: HTMLElement): boolean => {
  const selection = row.ownerDocument.getSelection();
  const table = row.closest("table");
  if (selection === null || table === null || selection.isCollapsed) return false;
  const ranges = Array.from({ length: selection.rangeCount }, (_, i) => selection.getRangeAt(i));
  return ranges.some((range) => range.intersectsNode(table)) && selection.toString() !== "";
};

/**
 * CMP-161 WatchlistRow: one row of SCR-100's grid over CMP-049's row contract (`renderRow`), the symbol its row
 * header. D9's formats in tabular mono; Last, Funding % and Spread never coloured; 24h % and OI Δ with the sign and a
 * hidden ▲/▼. States (E08-D07 §4.2, never stacked): live; stale (the row's tint and demoted text by `data-freshness`,
 * values kept, one CMP-239 chip whose words describe every cell); a stale OI baseline (its cells alone, CMP-239's
 * class swap); initialising and not live ("—" and a word, no freshness claimed); delisted (struck, the live cells
 * merged into "Delisted by the exchange", activation T2). Disconnected is the host's: one `data-cv-feed` on an
 * ancestor demotes every row. Keys: `Enter` activates, `Del` removes, `Alt+↑/↓` move, `Ctrl+C` copies (unless text
 * in the grid is selected); a T2 key changes nothing and re-shows its reason in the table's echo, said once per
 * press (a held key's repeats say nothing). A delisted row's symbol leads with the lock, named "Not available"
 * (E09-D09 §2.2).
 */
export function WatchlistRow({
  grid,
  row,
  columns,
  freshness,
  rowState = "live",
  nowMs,
  active = false,
  description,
  notLiveDetail,
  describedBy,
  onActivate,
  onMove,
  moveReason,
  onRemove,
  removeReason,
  onCopy,
}: WatchlistRowProps): JSX.Element {
  const id = useId();
  const slots = slotsOf(columns);
  const ticker = freshness?.ticker;
  const oi = freshness?.oiBaseline;
  const delisted = rowState === "delisted";
  // One state per row (E08-D01 §2): stale only marks a row that shows values; a stale row covers its OI cells.
  const stale = rowState === "live" && ticker?.state === "stale";
  const waiting = rowState === "initialising" && ticker?.state === "stale";
  const oiStale = rowState === "live" && !stale && oi?.state === "stale";
  const chipId = `${id}-age`;
  const mergedId = `${id}-delisted`;
  const aboutId = `${id}-about`;
  // The row's words reach every value cell as its description: the age chip's, then the host's.
  const shared = cx(stale ? chipId : undefined, describedBy) || undefined;

  const onKeyDown = (event: KeyboardEvent<HTMLTableRowElement>): void => {
    if (event.defaultPrevented) return;
    const bare = !event.altKey && !event.ctrlKey && !event.metaKey && !event.shiftKey;
    if (event.key === "Enter" && bare) {
      if (!delisted && onActivate === undefined) return;
      event.preventDefault();
      // A refusal is re-shown once per press: a held key's repeats say nothing (E09-D09 §9.3, as Del's).
      if (delisted) {
        if (!event.repeat) grid.refuse(DELISTED);
      } else onActivate?.();
    } else if (event.key === "Delete" && bare) {
      if (onRemove === undefined && removeReason === undefined) return;
      event.preventDefault();
      // A held key removes one: its repeats change nothing (E08-D07 §6.2).
      if (event.repeat) return;
      if (removeReason !== undefined) grid.refuse(removeReason);
      else onRemove?.();
    } else if (
      event.altKey &&
      !event.ctrlKey &&
      !event.metaKey &&
      !event.shiftKey &&
      (event.key === "ArrowUp" || event.key === "ArrowDown")
    ) {
      const direction = event.key === "ArrowUp" ? "up" : "down";
      const reason = moveReason?.[direction];
      if (onMove === undefined && reason === undefined) return;
      event.preventDefault();
      // A held key keeps moving the row, but a refusal is said once per press.
      if (reason !== undefined) {
        if (!event.repeat) grid.refuse(reason);
      } else onMove?.(direction);
    } else if (
      (event.ctrlKey || event.metaKey) &&
      !event.altKey &&
      !event.shiftKey &&
      event.key.toLowerCase() === "c"
    ) {
      if (onCopy === undefined) return;
      // Text the user selected in this grid is theirs to copy: the browser's copy runs, the symbol's does not.
      if (selectedInGrid(event.currentTarget)) return;
      event.preventDefault();
      onCopy(row.symbol);
    }
  };

  const onClick = (event: MouseEvent<HTMLTableRowElement>): void => {
    if (event.defaultPrevented) return;
    if (delisted) grid.refuse(DELISTED);
    else onActivate?.();
  };

  const cells: JSX.Element[] = [];
  let firstRun = true;
  for (let i = 0; i < slots.length; i += 1) {
    const slot = slots[i] ?? "status";
    const spec = SPEC[slot];
    if (slot === "symbol") {
      cells.push(
        <th
          key={slot}
          {...grid.cellProps(i, {
            header: true,
            // E08-D07 §4.1: a symbol the cell cuts shows whole in the echo.
            cut: row.symbol,
            describedBy:
              cx(shared, delisted && mergedId, description !== undefined && aboutId) || undefined,
            className: "cv-wl__cell cv-wl__symbol",
          })}
          aria-disabled={delisted ? true : undefined}
          data-column={slot}
        >
          {grid.label(i)}
          {delisted ? (
            <span className="cv-wl__lock">
              <Icon name="lock" decorative={false} label="Not available" />
            </span>
          ) : null}
          <span className="cv-wl__symbol-text">{row.symbol}</span>
          {description === undefined ? null : (
            <span id={aboutId} className="cv-visually-hidden" aria-hidden="true">
              {description}
            </span>
          )}
        </th>,
      );
    } else if (delisted && spec.live) {
      // D20: each run of live columns is one merged cell; Rec, between runs, stays its own.
      let end = i;
      while (end + 1 < slots.length && SPEC[slots[end + 1] ?? "status"].live) end += 1;
      cells.push(
        <td
          key={slot}
          {...grid.cellProps(i, { span: end - i + 1, className: "cv-wl__cell cv-wl__delisted" })}
          id={firstRun ? mergedId : undefined}
          data-column={slot}
        >
          <span className="cv-wl__delisted-glyph">
            <Icon name="cancelled" />
          </span>{" "}
          <span>{DELISTED}</span>
        </td>,
      );
      firstRun = false;
      i = end;
    } else if (slot === "status") {
      const chip =
        stale && ticker !== undefined ? (
          <FreshnessMarker
            id={chipId}
            presentation="compact"
            state="stale"
            {...(ticker.ageMs === undefined ? {} : { lastUpdatedAgeMs: ticker.ageMs })}
            {...(ticker.escalated === true ? { escalated: true } : {})}
            {...(ticker.server === true ? { label: "Stale (server)" } : {})}
          />
        ) : waiting ? (
          <span className="cv-wl__tag">No data yet</span>
        ) : rowState === "not-live" ? (
          <span className="cv-wl__tag">Not live</span>
        ) : null;
      const echo = stale ? ticker?.detail : rowState === "not-live" ? notLiveDetail : undefined;
      const words = echo?.trim() || undefined;
      cells.push(
        <td
          key={slot}
          {...grid.cellProps(i, { echo: words, className: "cv-wl__cell cv-wl__status" })}
          data-column={slot}
        >
          {grid.label(i)}
          {chip}
          {/* The echo is aria-hidden: the cell carries its words for AT itself, as Funding in's target does. */}
          {words === undefined ? null : <span className="cv-visually-hidden"> {words}</span>}
        </td>,
      );
    } else {
      const view: CellView =
        !spec.live || rowState === "live"
          ? viewOf(slot, row, nowMs)
          : { content: dash(rowState === "initialising" ? "no value yet" : "not live") };
      const marked = slot === "oi_chg_24h_pct" && oiStale;
      cells.push(
        <td
          key={slot}
          {...grid.cellProps(i, {
            numeric: spec.numeric,
            echo: view.echo,
            describedBy: cx(shared, marked && oi?.noteId) || undefined,
            className: cx(
              "cv-wl__cell",
              spec.numeric && "cv-wl__num",
              marked && freshnessClassName("stale"),
            ),
          })}
          data-column={slot}
        >
          {grid.label(i)}
          {view.content}
        </td>,
      );
    }
  }

  return (
    <tr
      {...grid.rowProps}
      className={cx(grid.rowProps.className, "cv-wl-row")}
      data-cmp="CMP-161"
      data-row-state={rowState}
      data-freshness={stale ? "stale" : undefined}
      aria-current={active ? "true" : undefined}
      onKeyDown={onKeyDown}
      onClick={onClick}
    >
      {cells}
    </tr>
  );
}
