/**
 * SCR-063's Working-orders tab (E29-S02 PR2; E29-D02 §6, §8.2–§8.3, §9–§11; S-13, S-35, S-36's
 * orders half): every working order on CMP-049's treegrid, the row's Cancel, the selection bar and
 * "Cancel all in view…" with the bulk dialog. The amend flow, the protective display and the arm
 * are PR3's; no CMP-011 toggle (BQ-12) and no chord (BQ-15).
 *
 * - **The feed** (`wsOrders.ts`) runs while the tab is mounted (CMP-042 mounts the selected tab
 *   only): its store, its `orders` subscription and its REST reads are released on unmount.
 * - **The treegrid** (D-1): the sections at level 1 ("Working · 3", "Conditional — not triggered ·
 *   2"), each account's group at level 2 ("Main · LIVE · 3 orders"), the orders at level 3, with
 *   `aria-posinset` and `aria-setsize` from the model (F-03); the select column (CMP-005, D-3), D02
 *   §6.1's columns (Env out: one environment per server, #911 BQ-7), Symbol the rowheader; past 50
 *   rows a window, the focused row kept mounted (G-01).
 * - **Cancel** (D02 §8.2; `model/gates.ts`): CMP-001 "Cancel" (N-06), the primary half of D-12's
 *   "Cancel ▾": its ▾ joins with PR3's Edit items, as a menu of none would be a menu button that
 *   opens nothing. The row menu (`Shift+F10`, `Menu`) repeats it. A row's own reason is 2b (the
 *   lock on the button, CMP-016's echo, its reason node; the menu item's second line); a scope's
 *   reason points at its one notice (2a, G-T2.5), the menu item's too, with no second line. Busy is
 *   "Cancelling…" with a static ⟳ (CMP-057's look), never T2, and holds until the row shows the
 *   cancel (a frame, a read, the row leaving), so a second press sends nothing. One click sends it,
 *   no question, and a toast without Undo names the order (D01 D7); a protective take-profit asks
 *   first (D02 §8.2), and its confirm reads the row again before it sends.
 * - **Bulk** (D02 §8.3; `model/bulk.ts`): "2 selected · Cancel selected · Clear selection" and
 *   "Cancel all in view…" (present while rows are in view, §9.2) open `BulkCancelDialog`; Confirm
 *   reads the targets again, so a native stop is never sent (C-2.6, BQ-4). Once sent, `Esc` and
 *   "Keep orders" close the view and cancel nothing; the result then comes as a toast.
 * - **Announcements** go through the panel's announcer (E17-D02 §11: no live region of its own):
 *   the selection count once per change (RT-13); a T2 press's reason through the panel's gated
 *   announcement; the toasts' sentences. Focus never drops to `body` (D05 §5.4): an ended row's
 *   Cancel hands focus to its cell; a dialog returns it to its opener, and when the opener has gone
 *   (Cancel selected clears the bar, an emptied view drops "Cancel all in view…") to the grid's
 *   roving stop, else the tab's root.
 */
import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type FocusEvent,
  type JSX,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";
import {
  Button,
  Checkbox,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Icon,
  Skeleton,
  Table,
  ToastRegion,
  type MenuItem,
  type TableColumn,
  type TableRowContext,
  type TableTreeRow,
  type ToastItem,
} from "@candleviewer/ui";
import type { Link } from "../../../lib/ws/state/types";
import { useShellSelector } from "../../../shell/useShellSelector";
import type { PanelAnnouncer } from "../announce";
import { bindKinds, bindText, D02_TEXT, DECK } from "../copy";
import { reportCancelAllInvoked, reportCancelAttempted, reportFiltered } from "../events";
import { accountWords, envWord, filterEmptyTitle, loadingLine, withdrawnLine } from "../gridModel";
import type { FilterAction } from "../model/filters";
import type { AccountInfo, Environment } from "../model/rowMapping";
import { getPanelState, updateChips, usePanelState } from "../panelState";
import type { FeedClient, PositionsSession } from "../positionsSession";
import { usePositions } from "../positionsStore";
import { Toolbar } from "../Toolbar";
import { ordersWrites, type CancelOutcome } from "./api";
import { BulkCancelDialog, type BulkState } from "./BulkCancelDialog";
import { bindProposed, CONFIRM_TEXT, ORDER_TEXT } from "./copy";
import {
  excludedLines,
  fromCancelAll,
  fromRows,
  lineText,
  planAllInView,
  planSelected,
  regate,
  retryPlan,
  runPlan,
  type AccountWords,
  type BulkPlan,
  type BulkResult,
} from "./model/bulk";
import { bulkGate, cancelGate, type CancelContext, type CancelGate } from "./model/gates";
import {
  formatAge,
  priceLabel,
  stateLabel,
  triggerLabel,
  type OrderRowModel,
} from "./model/orderRow";
import { groupLabel, sectionsOf, type AccountGroup, type OrdersSection } from "./model/sections";
import { createOrdersStore, useOrders } from "./ordersStore";
import { startOrdersFeed, type OrdersDeps, type OrdersFeed } from "./wsOrders";
import {
  accountOf,
  chipsInOrderWords,
  figure,
  openPositionFrom,
  openPositionKeys,
  orderChipLabel,
  orderName,
  rowsInView,
} from "./view";

export interface WorkingOrdersTabProps {
  readonly client: FeedClient | null;
  /** The panel's positions session: its book answers the native-stop rule (D01 D7). */
  readonly positions: PositionsSession;
  readonly announcer: PanelAnnouncer;
  /** The panel's notices over every tab (S-19, S-20, S-22), drawn in the band under the toolbar. */
  readonly notices?: ReactNode;
  /** The S-22 notice's `orders:write` line, when the panel draws it: the gated writes point at it. */
  readonly permissionNoticeId?: string | undefined;
  readonly deps?: OrdersDeps | undefined;
}

type Entry =
  | { readonly kind: "section"; readonly id: string; readonly section: OrdersSection }
  | {
      readonly kind: "group";
      readonly id: string;
      readonly group: AccountGroup;
      readonly sectionId: string;
    }
  | {
      readonly kind: "order";
      readonly id: string;
      readonly row: OrderRowModel;
      readonly sectionId: string;
    };
type Placed = Entry & { readonly tree: TableTreeRow };

type ColumnId =
  | "account"
  | "symbol"
  | "side"
  | "type"
  | "qty"
  | "filled"
  | "avg_fill"
  | "price"
  | "trigger"
  | "tif"
  | "flags"
  | "age"
  | "parent"
  | "state";

/** D02 §6.1's columns in order, their header words and minimum widths in px, compact / comfortable. */
const COLUMNS: readonly {
  readonly id: ColumnId;
  readonly header: string;
  readonly px: readonly [number, number];
  readonly numeric?: true;
}[] = [
  { id: "account", header: ORDER_TEXT.colAccount.string, px: [96, 104] },
  { id: "symbol", header: ORDER_TEXT.colSymbol.string, px: [96, 104] },
  { id: "side", header: ORDER_TEXT.colSide.string, px: [72, 80] },
  { id: "type", header: ORDER_TEXT.colType.string, px: [128, 136] },
  { id: "qty", header: ORDER_TEXT.colQty.string, px: [96, 104], numeric: true },
  { id: "filled", header: ORDER_TEXT.colFilled.string, px: [80, 88], numeric: true },
  { id: "avg_fill", header: ORDER_TEXT.colAvgFill.string, px: [88, 96], numeric: true },
  { id: "price", header: ORDER_TEXT.colPrice.string, px: [88, 96], numeric: true },
  { id: "trigger", header: ORDER_TEXT.colTrigger.string, px: [168, 176] },
  { id: "tif", header: ORDER_TEXT.colTif.string, px: [64, 72] },
  { id: "flags", header: ORDER_TEXT.colFlags.string, px: [104, 112] },
  { id: "age", header: ORDER_TEXT.colAge.string, px: [64, 72], numeric: true },
  { id: "parent", header: ORDER_TEXT.colParent.string, px: [104, 112] },
  { id: "state", header: ORDER_TEXT.colState.string, px: [296, 304] },
];
/** The select column, the data columns, the actions column. */
const ALL_COLUMNS = COLUMNS.length + 2;
const ACTIONS_AT = COLUMNS.length + 1;
const PX_PER_EM = 16;

/** CMP-049 windows a long list from this many rows (`15` CMP-049), OVERSCAN either side of the view. */
const WINDOW_FROM = 50;
const OVERSCAN = 10;
const FIRST_WINDOW = 30;
/** The toasts a tab holds at most (C-2.18): the newest stay. */
const MAX_TOASTS = 3;
/** The Age column repaints at most once a second (D02:272), never announced. */
const AGE_TICK_MS = 1_000;
/** A shell cause takes REST down with the socket (D02:397; `connectionRegion.ts`). */
const REST_DOWN: ReadonlySet<string> = new Set([
  "offline",
  "tailnet_unreachable",
  "backend_unreachable",
]);
const NO_GRANTS: readonly { readonly exchange_account_id: string; readonly mode: string }[] = [];
const NONE: readonly string[] = [];
const noSubscription = (): (() => void) => () => undefined;
const UP: Link = Object.freeze({ kind: "up" });
/** The grid's one Tab stop (CMP-049's roving cell or its control): focus's place when an opener has gone. */
const ROVING_STOP = '[role="treegrid"] [tabindex="0"]';
let toastSeq = 0;
let sendSeq = 0;

/** A cancel in flight from this client: the row's lifecycle at the press, and whether the server took it. */
interface Pending {
  readonly from: string | null;
  readonly taken: boolean;
}

interface Span {
  readonly first: number;
  readonly last: number;
}
const drawnFor = (view: Span, total: number): Span => ({
  first: Math.max(0, Math.min(view.first - OVERSCAN, total - 1)),
  last: Math.min(total, view.last + OVERSCAN + 1) - 1,
});
const keepsDrawn = (drawn: Span, view: Span, total: number): boolean =>
  (drawn.first === 0 || view.first >= drawn.first + OVERSCAN / 2) &&
  (drawn.last === total - 1 || view.last <= drawn.last - OVERSCAN / 2);
/**
 * G-T2.5 under the window: the drawn rows' account header stays drawn while it holds the notice
 * their Cancels point at, so no `aria-describedby` names a node that is not there (the window then
 * starts at that header).
 */
function withNoticeHeader(
  drawn: Span,
  entries: readonly Placed[],
  noticed: (e: Placed) => boolean,
): Span {
  for (let i = drawn.first; i >= 0; i -= 1) {
    const entry = entries[i];
    if (entry === undefined || entry.kind === "section") return drawn;
    if (entry.kind === "group") return noticed(entry) ? { ...drawn, first: i } : drawn;
  }
  return drawn;
}

/** The tree, flattened through the open rows; each entry's place from the model (F-03). */
function flatten(sections: readonly OrdersSection[], closed: ReadonlySet<string>): Placed[] {
  const out: Placed[] = [];
  sections.forEach((section, s) => {
    const sectionId = `section:${section.id}`;
    const open = !closed.has(sectionId);
    const tree = { level: 1, expanded: open, posinset: s + 1, setsize: sections.length };
    out.push({ kind: "section", id: sectionId, section, tree });
    if (!open) return;
    section.groups.forEach((group, g) => {
      const groupId = `group:${section.id}:${group.accountId}`;
      const shown = !closed.has(groupId);
      const place = { level: 2, expanded: shown, posinset: g + 1, setsize: section.groups.length };
      out.push({ kind: "group", id: groupId, group, sectionId: section.id, tree: place });
      if (!shown) return;
      group.rows.forEach((row, i) => {
        const leaf = { level: 3, posinset: i + 1, setsize: group.rows.length };
        out.push({ kind: "order", id: row.id, row, sectionId: section.id, tree: leaf });
      });
    });
  });
  return out;
}

/** "—" for a null, with its spoken reason (D02 D-7). */
const dash = (): JSX.Element => (
  <>
    <span aria-hidden="true">—</span>
    <span className="cv-visually-hidden">no value</span>
  </>
);

/** CMP-115's name order: the state word, the symbol and side, the type with its purpose, price, size, account. */
function rowName(row: OrderRowModel): string {
  const qty = row.qty === null ? "—" : `${figure(row.qty)} ${row.baseCoin}`.trimEnd();
  return [
    stateLabel(row, figure),
    row.symbol,
    row.sideLabel,
    row.typeLabel,
    priceLabel(row, figure),
    qty,
    accountOf(row),
  ].join(" · ");
}

/** What every row renderer shares. */
interface RowParts {
  readonly density: "compact" | "comfortable";
  readonly now: number;
  readonly selected: ReadonlySet<string>;
  readonly toggle: (id: string) => void;
  readonly selectAll: () => void;
  readonly gateOf: (row: OrderRowModel) => CancelGate;
  /**
   * The id of the notice a scope's reason renders in (the panel's, the tab's offline line, the
   * account header of the row's own section), or `undefined` for the control's own (2b).
   */
  readonly noticeOf: (
    gate: Extract<CancelGate, { kind: "gated" }>,
    accountId: string,
    sectionId: string,
  ) => string | undefined;
  /** The account header's notice in a section (its id and reason), or `null` when it has none. */
  readonly accountNotice: (
    sectionId: string,
    accountId: string,
  ) => { readonly id: string; readonly reason: string } | null;
  readonly cancel: (row: OrderRowModel) => void;
}

/** `Space` on a cell toggles its order's selection; `Ctrl+A` selects every order in view (D02 §11.1, D-3). */
function rowKeys(event: KeyboardEvent<HTMLTableRowElement>, parts: RowParts, id?: string): void {
  if (event.defaultPrevented || !(event.target instanceof HTMLElement)) return;
  if (event.ctrlKey && (event.key === "a" || event.key === "A")) {
    event.preventDefault();
    parts.selectAll();
    return;
  }
  const cell = event.target.closest<HTMLElement>("[data-cv-c]");
  if (event.key !== " " || cell !== event.target || id === undefined) return;
  if (event.ctrlKey || event.altKey || event.metaKey) return;
  event.preventDefault();
  parts.toggle(id);
}

/** A section or an account group: one header cell across the row, its disclosure glyph first. */
function HeaderRow({
  entry,
  grid,
  parts,
}: {
  readonly entry: Placed & { readonly kind: "section" | "group" };
  readonly grid: TableRowContext;
  readonly parts: RowParts;
}): JSX.Element {
  const notice =
    entry.kind === "group" ? parts.accountNotice(entry.sectionId, entry.group.accountId) : null;
  return (
    <tr
      {...grid.rowProps}
      className={`${grid.rowProps.className} cv-orders__${entry.kind}`}
      data-part={entry.kind === "section" ? "SectionRow" : "GroupRow"}
      onKeyDown={(event) => rowKeys(event, parts)}
    >
      <th {...grid.cellProps(0, { header: true, span: ALL_COLUMNS })}>
        <span className="cv-orders__disclosure">
          <Icon name={entry.tree.expanded === true ? "chevron-down" : "chevron-right"} />
        </span>
        {entry.kind === "section" ? entry.section.label : groupLabel(entry.group)}
        {notice === null ? null : (
          <span id={notice.id} className="cv-positions__reason">
            <span className="cv-positions__lock">
              <Icon name="lock" />
            </span>
            {notice.reason}
          </span>
        )}
      </th>
    </tr>
  );
}

/** The row's Cancel (N-06): its gate's rendering, busy as "Cancelling…", none left on an ended row. */
function CancelButton({
  row,
  sectionId,
  gate,
  parts,
}: {
  readonly row: OrderRowModel;
  readonly sectionId: string;
  readonly gate: CancelGate;
  readonly parts: RowParts;
}): JSX.Element {
  const label = ORDER_TEXT.cancel.string;
  const density = { density: parts.density };
  if (gate.kind === "busy") {
    // "Cancelling…" led by D02:345's static ⟳: `positions.css` keeps CMP-057's look (no spinner)
    return (
      <Button loading iconLeft="refresh" {...density}>
        {ORDER_TEXT.cancelling.string}
      </Button>
    );
  }
  if (gate.kind === "ended") {
    // form validity, outside the T2 grammar (E09-D09 §9.1): nothing is left to cancel
    return (
      <Button disabled {...density}>
        {label}
      </Button>
    );
  }
  if (gate.kind === "gated") {
    const notice = parts.noticeOf(gate, row.accountId, sectionId);
    return (
      <Button
        disabledReason={gate.reason}
        {...(notice === undefined ? {} : { disabledReasonId: notice })}
        {...density}
      >
        {label}
      </Button>
    );
  }
  return (
    <Button {...density} onClick={() => parts.cancel(row)}>
      {label}
    </Button>
  );
}

/** An order (level 3): the select box, D02 §6.1's cells, the Cancel. */
function OrderRow({
  row,
  sectionId,
  grid,
  parts,
}: {
  readonly row: OrderRowModel;
  readonly sectionId: string;
  readonly grid: TableRowContext;
  readonly parts: RowParts;
}): JSX.Element {
  const actions = useRef<HTMLTableCellElement>(null);
  const gate = parts.gateOf(row);
  const isSelected = parts.selected.has(row.id);
  // An ended row's Cancel is disabled: focus inside it goes to its cell, never to `body` (D05 §5.4)
  useLayoutEffect(() => {
    const cell = actions.current;
    const active = document.activeElement;
    if (gate.kind === "ended" && cell !== null && active !== cell && cell.contains(active))
      cell.focus();
  }, [gate.kind]);
  const text = (c: number, value: ReactNode, numeric = false): JSX.Element => (
    <td key={c} {...grid.cellProps(c, numeric ? { numeric: true } : {})}>
      {value}
    </td>
  );
  const account = accountOf(row);
  const cells: Record<ColumnId, (c: number) => JSX.Element> = {
    account: (c) => (
      <td key={c} {...grid.cellProps(c, { cut: account })}>
        {account}
      </td>
    ),
    symbol: (c) => (
      <th key={c} {...grid.cellProps(c, { header: true })}>
        {row.symbol}
      </th>
    ),
    side: (c) =>
      text(
        c,
        <>
          {row.sideGlyph === null ? null : (
            <span className="cv-orders__side" data-side={row.side} aria-hidden="true">
              {`${row.sideGlyph} `}
            </span>
          )}
          {row.sideLabel}
        </>,
      ),
    type: (c) => text(c, row.typeLabel),
    qty: (c) =>
      text(c, row.qty === null ? dash() : `${figure(row.qty)} ${row.baseCoin}`.trimEnd(), true),
    filled: (c) => text(c, row.filledQty === null ? dash() : figure(row.filledQty), true),
    avg_fill: (c) => text(c, row.avgFillPrice === null ? dash() : figure(row.avgFillPrice), true),
    price: (c) => text(c, priceLabel(row, figure), true),
    trigger: (c) => text(c, triggerLabel(row, figure)),
    tif: (c) => text(c, row.tifLabel),
    flags: (c) => text(c, row.flagsLabel),
    age: (c) => text(c, formatAge(row.createdAtMs, parts.now), true),
    parent: (c) => text(c, row.parentLabel),
    state: (c) =>
      text(
        c,
        <span className="cv-orders__state" data-family={row.state.family}>
          {stateLabel(row, figure)}
        </span>,
      ),
  };
  return (
    <tr
      {...grid.rowProps}
      className={`${grid.rowProps.className} cv-orders__row`}
      aria-label={rowName(row)}
      aria-selected={isSelected}
      data-key={row.id}
      data-family={row.state.family}
      onKeyDown={(event) => rowKeys(event, parts, row.id)}
    >
      <td {...grid.cellProps(0, { widget: true, className: "cv-orders__select" })}>
        <Checkbox
          label={`Select ${orderName(row)}`}
          checked={isSelected}
          onChange={() => parts.toggle(row.id)}
          tabIndex={grid.tabIndexOf(0)}
          density={parts.density}
        />
      </td>
      {COLUMNS.map((column, i) => cells[column.id](i + 1))}
      <td ref={actions} {...grid.cellProps(ACTIONS_AT, { interactive: true })}>
        <CancelButton row={row} sectionId={sectionId} gate={gate} parts={parts} />
      </td>
    </tr>
  );
}

/** The orders feed for as long as the tab is mounted (its store, subscription and reads). */
function useOrdersFeedSession(
  client: FeedClient | null,
  feed: OrdersDeps["feed"],
): { readonly store: ReturnType<typeof createOrdersStore>; readonly retry: () => void } {
  const [store] = useState(createOrdersStore);
  const running = useRef<OrdersFeed | null>(null);
  useEffect(() => {
    if (client === null) return undefined;
    const started = startOrdersFeed({ ...feed, client, store });
    running.current = started;
    return () => {
      started.stop();
      if (running.current === started) running.current = null;
    };
  }, [client, store, feed]);
  return { store, retry: () => running.current?.retry() };
}

export function WorkingOrdersTab({
  client,
  positions,
  announcer,
  notices,
  permissionNoticeId,
  deps,
}: WorkingOrdersTabProps): JSX.Element {
  const ids = useId();
  const root = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const addFilterId = `${ids}-add-filter`;
  const offlineId = `${ids}-offline`;
  const bulkReasonId = `${ids}-bulk-reason`;
  const writes = deps?.writes ?? ordersWrites;
  const wall = deps?.wall ?? Date.now;
  const { store, retry } = useOrdersFeedSession(client, deps?.feed);
  const snap = useOrders(store, (s) => s);
  // the open positions alone (code m5): a mark tick leaves the string equal, so nothing re-renders
  const openKeys = usePositions(positions.store, openPositionKeys);
  const chips = usePanelState("chips");
  const groupBy = usePanelState("groupBy");
  const density = usePanelState("density");
  const permissions = useShellSelector((s) => s.me?.permissions ?? NONE);
  const grants = useShellSelector((s) => s.me?.accounts ?? NO_GRANTS);
  const shellEnv = useShellSelector((s) => s.environment);
  const link = useSyncExternalStore(
    client?.subscribe ?? noSubscription,
    () => client?.getState().link ?? UP,
    () => client?.getState().link ?? UP,
  );
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [cancelling, setCancelling] = useState<ReadonlyMap<string, Pending>>(new Map());
  const [denied, setDenied] = useState<ReadonlySet<string>>(new Set());
  const [closed, setClosed] = useState<ReadonlySet<string>>(new Set());
  const [bulk, setBulk] = useState<BulkState | null>(null);
  const [takeProfit, setTakeProfit] = useState<OrderRowModel | null>(null);
  const [toasts, setToasts] = useState<readonly ToastItem[]>([]);
  const [now, setNow] = useState(wall);
  const [span, setSpan] = useState<Span>({ first: 0, last: FIRST_WINDOW - 1 });
  const alive = useRef(true);
  const abort = useRef<AbortController | null>(null);
  /** The bulk send the dialog waits on, and where a closed dialog's late result goes. */
  const showing = useRef<{ readonly seq: number; readonly closed: "toast" | "drop" | null } | null>(
    null,
  );
  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    abort.current = controller;
    return () => {
      alive.current = false;
      // A request in flight resolves into nothing once the tab has gone; a per-row bulk still
      // running stops there too: each target left is answered at once, unsent, as not known.
      controller.abort();
    };
  }, []);

  const directory = useMemo(() => new Map(snap.accounts.map((a) => [a.id, a])), [snap.accounts]);
  const environment: Environment | null =
    shellEnv !== "unknown" ? shellEnv : (snap.accounts[0]?.environment ?? null);
  const openPosition = useMemo(() => openPositionFrom(openKeys), [openKeys]);
  const view = useMemo(
    () => rowsInView(snap.rows, chips, openPosition),
    [snap.rows, chips, openPosition],
  );
  const sections = useMemo(() => sectionsOf(view), [view]);
  const entries = useMemo(() => flatten(sections, closed), [sections, closed]);
  const indexOf = useMemo(() => new Map(entries.map((e, i) => [e.id, i])), [entries]);
  const selectedRows = view.filter((r) => selected.has(r.id));

  // the Age column: once a second while rows show (D02:272)
  useEffect(() => {
    if (view.length === 0) return undefined;
    const tick = setInterval(() => setNow(wall()), AGE_TICK_MS);
    return () => clearInterval(tick);
  }, [view.length, wall]);

  // A cancel the server took stays busy until its row shows it: a frame or a read moves its state
  // off the one it was pressed in, or the row leaves (design m5). The store's row is what the gate
  // reads, so the 202's own state never ends it: a second press meanwhile sends nothing.
  useEffect(() => {
    const lifecycleOf = new Map(snap.rows.map((r) => [r.id, r.state.lifecycle]));
    const done = [...cancelling].filter(
      ([id, p]) => p.taken && (!lifecycleOf.has(id) || lifecycleOf.get(id) !== p.from),
    );
    if (done.length === 0) return;
    setCancelling((all) => {
      const next = new Map(all);
      for (const [id] of done) next.delete(id);
      return next;
    });
  }, [snap.rows, cancelling]);

  const readOnly = useMemo(
    () =>
      new Set(
        grants.filter((g) => g.mode === "read").map((g) => g.exchange_account_id.toLowerCase()),
      ),
    [grants],
  );
  const cancellingIds = useMemo(() => new Set(cancelling.keys()), [cancelling]);
  const context: CancelContext = {
    viewAs: null, // no client source yet (#911's reading): the server answers view_as_read_only
    permissions,
    readOnlyAccounts: readOnly,
    deniedAccounts: denied,
    restReachable: !(link.kind === "offline" && REST_DOWN.has(link.cause)),
    cancelling: cancellingIds,
  };
  const gateOf = (row: OrderRowModel): CancelGate => cancelGate(row, context);
  const accountsOf = (rows: readonly OrderRowModel[]): readonly string[] => [
    ...new Set(rows.map((r) => r.accountId)),
  ];
  const accountNotice = (
    sectionId: string,
    accountId: string,
  ): { readonly id: string; readonly reason: string } | null => {
    const reason = denied.has(accountId)
      ? DECK["rbac.account"].string
      : readOnly.has(accountId)
        ? DECK["rbac.account_read_only"].string
        : null;
    // one node per section's header (design m1): an account heads a group in each section
    return reason === null ? null : { id: `${ids}-account-${sectionId}-${accountId}`, reason };
  };
  const noticeOf = (
    gate: Extract<CancelGate, { kind: "gated" }>,
    accountId: string,
    sectionId: string,
  ): string | undefined => {
    if (gate.leg === "permission") return permissionNoticeId;
    if (gate.leg === "offline") return offlineId;
    if (gate.leg === "account" || gate.leg === "account_read_only")
      return accountNotice(sectionId, accountId)?.id;
    return undefined;
  };
  const wordsOf = (accountId: string): AccountWords => ({
    label: accountWords(accountId, directory),
    environment: envWord(directory.get(accountId)?.environment ?? environment),
  });
  /** Where focus goes when a control's own opener has gone: the grid's roving stop, else the root. */
  const focusHome = (): HTMLElement | null =>
    root.current?.querySelector<HTMLElement>(ROVING_STOP) ?? root.current;
  // D05 §5.4: the opener while it is there, else the grid's stop, else the root, read as a dialog
  // closes, so it outlives an opener that left with the selection bar or an emptied view (M2)
  const [fallbackFocus] = useState<RefObject<HTMLElement | null>>(() => ({
    get current(): HTMLElement | null {
      const pressed = opener.current;
      if (pressed?.isConnected === true) return pressed;
      return root.current?.querySelector<HTMLElement>(ROVING_STOP) ?? root.current;
    },
  }));

  // RT-13: the selection count, polite, once per change; 0 too, so emptying it is heard (design n5)
  const count = selectedRows.length;
  const said = useRef(0);
  useEffect(() => {
    if (count !== said.current)
      announcer.say("polite", bindProposed("blotter.ui.sel.count", { "2": String(count) }), "sel");
    said.current = count;
  }, [count, announcer]);

  const toast = (item: Omit<ToastItem, "id">): void => {
    toastSeq += 1;
    const next = { ...item, id: `orders-toast-${toastSeq}` };
    setToasts((all) => [...all, next].slice(-MAX_TOASTS));
  };
  const release = (id: string): void =>
    setCancelling((all) => {
      const next = new Map(all);
      next.delete(id);
      return next;
    });
  /** One row's cancel, the row read again as it is now (code m7): nothing is sent for one no longer allowed. */
  const sendCancel = (pressed: OrderRowModel): void => {
    const row = view.find((r) => r.id === pressed.id);
    if (row === undefined || gateOf(row).kind !== "allowed") return;
    setCancelling((all) => new Map(all).set(row.id, { from: row.state.lifecycle, taken: false }));
    reportCancelAttempted();
    void writes
      .cancelOrder(row.id, abort.current?.signal)
      .catch((): CancelOutcome => ({ kind: "unavailable" })) // a throw is no answer (code m9)
      .then((outcome: CancelOutcome) => {
        if (!alive.current) return;
        if (outcome.kind === "accepted")
          setCancelling((all) =>
            all.has(row.id)
              ? new Map(all).set(row.id, { from: row.state.lifecycle, taken: true })
              : all,
          );
        else release(row.id);
        const words = {
          BTCUSDT: row.symbol,
          Sell: row.sideLabel,
          "0.250": row.qty === null ? "—" : figure(row.qty),
          Main: accountOf(row),
        };
        if (outcome.kind === "accepted") {
          const priced = !row.isMarket && row.price !== null;
          toast({
            title: priced
              ? bindProposed("blotter.ui.cancel.toast", {
                  ...words,
                  "64,800.0": figure(row.price ?? ""),
                })
              : bindProposed("blotter.ui.cancel.toast.no_price", words),
          });
        } else if (outcome.kind === "unavailable") {
          toast({ title: bindProposed("blotter.ui.cancel.unconfirmed", words), tone: "warning" });
        } else {
          if (outcome.kind === "account_scope") setDenied((all) => new Set(all).add(row.accountId));
          const why =
            outcome.kind === "native_stop"
              ? DECK["sl.note"].string
              : outcome.kind === "account_scope"
                ? DECK["rbac.account"].string
                : outcome.kind === "view_as"
                  ? bindProposed("blotter.ui.cancel.view_as")
                  : undefined;
          toast({
            title: bindProposed("blotter.ui.cancel.failed", words),
            tone: "warning",
            ...(why === undefined ? {} : { description: why }),
          });
        }
      });
  };
  /** A row's Cancel (D02 §8.2): at once, but a protective take-profit asks first (D01 D7). */
  const cancel = (row: OrderRowModel): void => {
    if (gateOf(row).kind !== "allowed") return;
    if (row.intent === "take_profit" && row.reduceOnly) {
      const active = document.activeElement;
      opener.current = active instanceof HTMLElement && active !== document.body ? active : null;
      setTakeProfit(row);
      return;
    }
    sendCancel(row);
  };
  const takeProfitAt = takeProfit?.price ?? takeProfit?.trigger?.price ?? null;
  const takeProfitTitle =
    takeProfit === null
      ? ""
      : bindText(CONFIRM_TEXT.takeProfit, "takeProfit", {
          "64,800.0": takeProfitAt === null ? ORDER_TEXT.none.string : figure(takeProfitAt),
          Main: accountOf(takeProfit),
          BTCUSDT: takeProfit.symbol,
        });

  /** A closed dialog's result, as a toast (design m12): one line per account, nothing dropped. */
  const resultToast = (result: BulkResult): void => {
    const lines = [
      ...result.lines.map((line) => lineText(line, wordsOf(line.accountId))),
      ...excludedLines(result.plan.excluded),
    ];
    const failed = result.lines.some((line) => line.kind !== "done");
    toast({
      title: bindProposed("blotter.ui.result.title"),
      description: lines.join(". "),
      ...(failed ? { tone: "warning" as const } : {}),
    });
  };
  const send = (plan: BulkPlan, isRetry: boolean): void => {
    reportCancelAllInvoked({
      scope: plan.scope,
      route: plan.route.kind,
      orders: plan.targets.length,
      accounts: new Set(plan.targets.map((r) => r.accountId)).size,
      retry: isRetry,
    });
    sendSeq += 1;
    const seq = sendSeq;
    showing.current = { seq, closed: null };
    void runPlan(plan, writes, abort.current?.signal)
      .catch(() =>
        // a throw is no answer (code m9): every target not known, never re-sent
        plan.route.kind === "cancel_all"
          ? fromCancelAll(plan, { kind: "unavailable" })
          : fromRows(plan, new Map()),
      )
      .then((result) => {
        const waiting = showing.current;
        if (!alive.current || waiting?.seq !== seq) return;
        showing.current = null;
        if (waiting.closed === "toast") resultToast(result);
        else if (waiting.closed === null) setBulk({ phase: "result", result, sending: false });
        // a retry whose dialog was closed is dropped, never re-opened (code m8)
      });
  };
  const openBulk = (plan: BulkPlan): void => {
    if (plan.targets.length === 0) {
      // nothing to send: say why where the press was, no dialog (an empty confirm is form validity)
      const [title = "", ...more] = excludedLines(plan.excluded);
      toast({ title, ...(more.length === 0 ? {} : { description: more.join(" ") }) });
      return;
    }
    const active = document.activeElement;
    opener.current =
      active instanceof HTMLElement && active !== document.body ? active : root.current;
    setBulk({ phase: "confirm", plan });
  };
  const onConfirm = (): void => {
    if (bulk?.phase !== "confirm") return;
    // C-2.6, BQ-4: the targets as they are now; a stop whose position opened is never sent (M1)
    const plan = regate(bulk.plan, view, chips, gateOf);
    setBulk({ phase: "sending", plan });
    if (plan.scope === "selected") setSelected(new Set());
    send(plan, false);
  };
  const onRetry = (): void => {
    if (bulk?.phase !== "result" || bulk.sending) return;
    const plan = retryPlan(bulk.result, view, chips, gateOf);
    if (plan === null) return;
    setBulk({ ...bulk, sending: true });
    send(plan, true);
  };
  const onCloseBulk = (): void => {
    // once sent, Esc and "Keep orders" close the view and cancel nothing (CMP-043 H22, design m12):
    // the first send's result comes as a toast; a retry's is dropped (code m8)
    const waiting = showing.current;
    if (waiting !== null && bulk !== null && (bulk.phase === "sending" || bulk.phase === "result"))
      showing.current = { ...waiting, closed: bulk.phase === "sending" ? "toast" : "drop" };
    setBulk(null);
  };

  const onChips = (action: FilterAction): void => {
    const before = getPanelState().chips;
    updateChips(action);
    const after = getPanelState().chips;
    if (after !== before) reportFiltered(after);
  };
  const onGridFocus = (event: FocusEvent<HTMLDivElement>): void => {
    const target = event.target instanceof Element ? event.target : null;
    store.setFocused(target?.closest("tr[data-key]")?.getAttribute("data-key") ?? null);
  };
  const onGridBlur = (event: FocusEvent<HTMLDivElement>): void => {
    const next = event.relatedTarget;
    if (!(next instanceof Node) || !event.currentTarget.contains(next)) store.setFocused(null);
  };

  const parts: RowParts = {
    density,
    now,
    selected,
    toggle: (id) =>
      setSelected((all) => {
        const next = new Set(all);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      }),
    selectAll: () => setSelected(new Set(view.map((r) => r.id))),
    gateOf,
    noticeOf,
    accountNotice,
    cancel,
  };

  const selectedGate = bulkGate(context, accountsOf(selectedRows));
  const allGate = bulkGate(context, accountsOf(view));
  // the read-only reason beside the bulk buttons that take it (D04 §4.1, 2a): one node, two pointers
  const bulkReason = [count === 0 ? null : selectedGate, view.length === 0 ? null : allGate].find(
    (g) => g?.kind === "gated" && g.leg === "account_read_only",
  );
  const bulkButton = (label: string, gate: CancelGate | null, onClick: () => void): JSX.Element => {
    if (gate?.kind !== "gated")
      return (
        <Button density={density} onClick={onClick}>
          {label}
        </Button>
      );
    const notice = gate.leg === "account_read_only" ? bulkReasonId : noticeOf(gate, "", "");
    return (
      <Button
        disabledReason={gate.reason}
        {...(notice === undefined ? {} : { disabledReasonId: notice })}
        density={density}
      >
        {label}
      </Button>
    );
  };
  const clearSelection = (): void => {
    // the bar leaves with its own button: focus goes to the grid's stop first, never `body` (D05 §5.4)
    focusHome()?.focus();
    setSelected(new Set());
  };
  const separator = (
    <span className="cv-orders__dot" aria-hidden="true">
      ·
    </span>
  );
  const end = (
    <>
      {count === 0 ? null : (
        <span className="cv-orders__selection" data-part="SelectionBar">
          <span>{bindProposed("blotter.ui.sel.count", { "2": String(count) })}</span>
          {separator}
          {bulkButton(DECK["blotter.ui.sel.cancel"].string, selectedGate, () =>
            openBulk(planSelected(selectedRows, gateOf)),
          )}
          {separator}
          <Button variant="ghost" density={density} onClick={clearSelection}>
            {bindProposed("blotter.ui.sel.clear")}
          </Button>
        </span>
      )}
      {view.length === 0
        ? null
        : bulkButton(DECK["blotter.ui.bulk.cancel_all"].string, allGate, () =>
            openBulk(planAllInView(view, chips, gateOf)),
          )}
      {bulkReason?.kind === "gated" ? (
        <span id={bulkReasonId} className="cv-positions__reason" data-part="BulkReason">
          {bulkReason.reason}
        </span>
      ) : null}
    </>
  );

  const windowed = entries.length > WINDOW_FROM;
  const drawn = windowed
    ? withNoticeHeader(
        drawnFor(span, entries.length),
        entries,
        (e) => e.kind === "group" && accountNotice(e.sectionId, e.group.accountId) !== null,
      )
    : { first: 0, last: entries.length - 1 };
  const columns: TableColumn<Placed>[] = [
    { id: "select", header: bindProposed("blotter.ui.col.select"), cell: (e) => e.id },
    ...COLUMNS.map((c): TableColumn<Placed> => ({
      id: c.id,
      header: c.header,
      cell: (e) => e.id,
      widthEm: c.px[density === "comfortable" ? 1 : 0] / PX_PER_EM,
      ...(c.numeric === true ? { align: "end" as const } : {}),
    })),
    { id: "actions", header: bindProposed("blotter.ui.col.actions"), cell: (e) => e.id },
  ];
  const menuOf = (row: OrderRowModel, sectionId: string): readonly MenuItem[] => {
    const gate = gateOf(row);
    // a scope's reason points at its one notice with no second line (G-T2.5, D02 §10.4)
    const notice = gate.kind === "gated" ? noticeOf(gate, row.accountId, sectionId) : undefined;
    return [
      {
        id: "cancel",
        label: gate.kind === "busy" ? ORDER_TEXT.cancelling.string : ORDER_TEXT.cancel.string,
        onSelect: () => cancel(row),
        ...(gate.kind === "gated" ? { disabledReason: gate.reason } : {}),
        ...(notice === undefined ? {} : { disabledReasonId: notice }),
        ...(gate.kind === "busy" ? { busy: true } : {}),
        ...(gate.kind === "ended" ? { disabled: true } : {}),
      },
    ];
  };

  const withdrawn =
    snap.withdrawn.length === 0 ? null : (
      <div className="cv-positions__withdrawn" data-part="Withdrawn">
        {snap.withdrawn.map((w) => (
          <p key={w.accountId}>{withdrawnLine(w, directory)}</p>
        ))}
      </div>
    );
  const onRetryFeed = (): void => {
    retry();
    root.current?.focus(); // Retry leaves with its state: the tab keeps focus, never `body`
  };
  const failedLine = (accounts: readonly AccountInfo[]): readonly string[] =>
    (accounts.length > 0 ? accounts : [null]).map((a) =>
      bindKinds("blotter.ui.snapshot_failed", {
        label: a?.label ?? D02_TEXT.tabWorkingOrders.string,
        environment: envWord(a?.environment ?? environment),
      }),
    );

  let body: ReactNode;
  if (snap.status === "no_accounts") {
    body = <EmptyState title={DECK["blotter.ui.no_accounts"].string} headingLevel={2} />;
  } else if (snap.status === "snapshot_failed" || snap.status === "revoked") {
    body = (
      <div className="cv-positions__failed" data-part="SnapshotFailed">
        {snap.status === "revoked"
          ? withdrawn
          : failedLine(snap.accounts).map((line) => (
              <ErrorState key={line} form="banner" severity="warning" live="off" message={line} />
            ))}
        <Button onClick={onRetryFeed}>{D02_TEXT.retry.string}</Button>
      </div>
    );
  } else if (snap.status === "loading" && snap.rows.length === 0) {
    // S-01 as the Positions tab draws it (#911, design m15): one busy group per account
    body = (
      <div className="cv-positions__loading" data-part="Loading">
        {snap.accounts.length === 0 ? (
          <div aria-busy="true">
            <Skeleton shape="row" count={3} />
          </div>
        ) : (
          snap.accounts.map((a) => (
            <div
              key={a.id}
              role="group"
              aria-busy="true"
              aria-labelledby={`${ids}-loading-${a.id}`}
            >
              <p id={`${ids}-loading-${a.id}`}>{loadingLine(a)}</p>
              <Skeleton shape="row" count={3} />
            </div>
          ))
        )}
      </div>
    );
  } else {
    const empty =
      snap.rows.length > 0 ? (
        <EmptyState
          variant="filtered-empty"
          title={filterEmptyTitle(chips.length)}
          description={chipsInOrderWords(chips, directory)}
          actions={[
            {
              label: D02_TEXT.clearFilters.string,
              onClick: () => {
                onChips({ type: "clear" });
                document.getElementById(addFilterId)?.focus();
              },
            },
          ]}
          headingLevel={2}
        />
      ) : (
        <EmptyState
          title={bindProposed("blotter.ui.orders_empty")}
          description={bindProposed("blotter.ui.orders_empty_cause")}
          headingLevel={2}
        />
      );
    body = (
      <div
        className="cv-positions__grid cv-orders"
        data-select=""
        data-actions=""
        onFocus={onGridFocus}
        onBlur={onGridBlur}
      >
        <Table<Placed>
          treegrid
          multiselectable
          caption={D02_TEXT.tabWorkingOrders.string}
          captionHidden
          columns={columns}
          rows={entries.slice(drawn.first, drawn.last + 1)}
          rowKey={(e) => e.id}
          treeRow={(e) => e.tree}
          onExpandedChange={(e, expanded) => {
            if (e.kind === "order") return;
            setClosed((all) => {
              const next = new Set(all);
              if (expanded) next.delete(e.id);
              else next.add(e.id);
              return next;
            });
          }}
          density={density}
          emptyState={empty}
          announce={(text) => announcer.say("polite", text)}
          stickyFirstColumn={3}
          stickyLastColumn
          rowLabel={(e) =>
            e.kind === "order"
              ? orderName(e.row)
              : e.kind === "group"
                ? groupLabel(e.group)
                : e.section.label
          }
          rowActions={(e) => (e.kind === "order" ? menuOf(e.row, e.sectionId) : [])}
          {...(windowed
            ? {
                rowWindow: { offset: drawn.first, total: entries.length },
                onRowsInView: (first: number, last: number) =>
                  setSpan((was) =>
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
          renderRow={(e, grid) =>
            e.kind === "order" ? (
              <OrderRow row={e.row} sectionId={e.sectionId} grid={grid} parts={parts} />
            ) : (
              <HeaderRow entry={e} grid={grid} parts={parts} />
            )
          }
        />
      </div>
    );
  }

  const live = environment === "live";
  return (
    <div
      className="cv-positions__tab"
      data-part="WorkingOrdersTab"
      ref={root}
      tabIndex={-1}
      role="group"
      aria-label={D02_TEXT.tabWorkingOrders.string}
    >
      <Toolbar
        variant="orders"
        accounts={snap.accounts}
        chips={chips}
        chipWords={(chip) => orderChipLabel(chip, directory)}
        groupBy={groupBy}
        columns={[]}
        onGroupBy={() => undefined}
        onChips={onChips}
        onColumns={() => undefined}
        onExport={() => undefined}
        density={density}
        addFilterId={addFilterId}
        end={end}
      />
      {notices}
      {context.restReachable ? null : (
        <div id={offlineId} className="cv-positions__notice" data-part="OfflineNotice">
          <span className="cv-positions__lock">
            <Icon name="lock" />
          </span>
          <p className="cv-positions__reason">{DECK["blotter.ui.unreachable"].string}</p>
        </div>
      )}
      {body}
      {snap.status === "revoked" ? null : withdrawn}
      <BulkCancelDialog
        state={bulk}
        live={live}
        chipsLine={chipsInOrderWords(chips, directory)}
        wordsOf={wordsOf}
        environment={envWord(environment)}
        onConfirm={onConfirm}
        onRetry={onRetry}
        onClose={onCloseBulk}
        fallbackFocusRef={fallbackFocus}
      />
      <ConfirmDialog
        open={takeProfit !== null}
        title={takeProfitTitle}
        confirmLabel={bindProposed("blotter.ui.tp_confirm.confirm")}
        cancelLabel={bindProposed("blotter.ui.tp_confirm.keep")}
        confirmVariant="danger"
        onConfirm={() => {
          const row = takeProfit;
          setTakeProfit(null);
          if (row !== null) sendCancel(row); // read again there: one that changed sends nothing
        }}
        onCancel={() => setTakeProfit(null)}
        fallbackFocusRef={fallbackFocus}
      />
      <ToastRegion
        toasts={toasts}
        label={bindProposed("blotter.ui.toasts")}
        durationMs={null}
        onDismiss={(id) => setToasts((all) => all.filter((t) => t.id !== id))}
        announce={(politeness, text) => announcer.say(politeness, text)}
      />
    </div>
  );
}
