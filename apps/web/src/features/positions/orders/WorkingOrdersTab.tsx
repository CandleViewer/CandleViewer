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
 *   reason points at its one notice (2a, G-T2.5). Busy is "Cancelling…", never T2. One click sends
 *   it, no question, and a toast without Undo names the order (D01 D7).
 * - **Bulk** (D02 §8.3; `model/bulk.ts`): "2 selected · Cancel selected · Clear selection" and
 *   "Cancel all in view…" (present while rows are in view, §9.2) open `BulkCancelDialog`; a native
 *   stop is never sent (C-2.6, BQ-4).
 * - **Announcements** go through the panel's announcer (E17-D02 §11: no live region of its own):
 *   the selection count once per change (RT-13); a T2 press's reason through the panel's gated
 *   announcement; the toasts' sentences. Focus never drops to `body` (D05 §5.4): an ended row's
 *   Cancel hands focus to its cell, a dialog returns it to its opener.
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
} from "react";
import {
  Button,
  Checkbox,
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
import type { KillSwitchView, Link } from "../../../lib/ws/state/types";
import { useShellSelector } from "../../../shell/useShellSelector";
import { useAccountSignals } from "../accountSignals";
import type { PanelAnnouncer } from "../announce";
import { bindKinds, D02_TEXT, DECK } from "../copy";
import { reportCancelAllInvoked, reportCancelAttempted, reportFiltered } from "../events";
import {
  accountWords,
  chipsRestated,
  envWord,
  filterEmptyTitle,
  withdrawnLine,
} from "../gridModel";
import type { FilterAction } from "../model/filters";
import type { AccountInfo, Environment } from "../model/rowMapping";
import { getPanelState, updateChips, usePanelState } from "../panelState";
import type { FeedClient, PositionsSession } from "../positionsSession";
import { usePositions } from "../positionsStore";
import { Toolbar } from "../Toolbar";
import { ordersWrites, type CancelOutcome } from "./api";
import { BulkCancelDialog, type BulkState } from "./BulkCancelDialog";
import { bindProposed, ORDER_TEXT } from "./copy";
import {
  excludedLines,
  planAllInView,
  planSelected,
  retryPlan,
  runPlan,
  type AccountWords,
  type BulkPlan,
} from "./model/bulk";
import { cancelGate, scopeGate, type CancelContext, type CancelGate } from "./model/gates";
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
import { figure, openPositionOf, orderName, rowsInView } from "./view";

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
  | { readonly kind: "group"; readonly id: string; readonly group: AccountGroup }
  | { readonly kind: "order"; readonly id: string; readonly row: OrderRowModel };
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
const UNKNOWN_KILL_SWITCH: KillSwitchView = Object.freeze({ state: "unknown" });
let toastSeq = 0;

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
      out.push({ kind: "group", id: groupId, group, tree: place });
      if (!shown) return;
      group.rows.forEach((row, i) => {
        const leaf = { level: 3, posinset: i + 1, setsize: group.rows.length };
        out.push({ kind: "order", id: row.id, row, tree: leaf });
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
    row.accountLabel ?? row.accountId,
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
  /** The id of the notice a scope's reason renders in, or `undefined` for the control's own (2b). */
  readonly noticeOf: (
    gate: Extract<CancelGate, { kind: "gated" }>,
    accountId: string,
  ) => string | undefined;
  readonly readOnlyId: (accountId: string) => string | null;
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
  const notice = entry.kind === "group" ? parts.readOnlyId(entry.group.accountId) : null;
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
          <span id={notice} className="cv-positions__reason">
            <span className="cv-positions__lock">
              <Icon name="lock" />
            </span>
            {DECK["rbac.account_read_only"].string}
          </span>
        )}
      </th>
    </tr>
  );
}

/** The row's Cancel (N-06): its gate's rendering, busy as "Cancelling…", none left on an ended row. */
function CancelButton({
  row,
  gate,
  parts,
}: {
  readonly row: OrderRowModel;
  readonly gate: CancelGate;
  readonly parts: RowParts;
}): JSX.Element {
  const label = ORDER_TEXT.cancel.string;
  const density = { density: parts.density };
  if (gate.kind === "busy") {
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
    const notice = parts.noticeOf(gate, row.accountId);
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
  grid,
  parts,
}: {
  readonly row: OrderRowModel;
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
  const account = row.accountLabel ?? row.accountId;
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
        <CancelButton row={row} gate={gate} parts={parts} />
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
  const writes = deps?.writes ?? ordersWrites;
  const wall = deps?.wall ?? Date.now;
  const { store, retry } = useOrdersFeedSession(client, deps?.feed);
  const snap = useOrders(store, (s) => s);
  const book = usePositions(positions.store, (s) => s);
  const signals = useAccountSignals(positions.signals, (s) => s.accounts);
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
  const killSwitch = useSyncExternalStore(
    client?.subscribe ?? noSubscription,
    () => client?.getState().killSwitch ?? UNKNOWN_KILL_SWITCH,
    () => client?.getState().killSwitch ?? UNKNOWN_KILL_SWITCH,
  );
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [cancelling, setCancelling] = useState<ReadonlySet<string>>(new Set());
  const [closed, setClosed] = useState<ReadonlySet<string>>(new Set());
  const [bulk, setBulk] = useState<BulkState | null>(null);
  const [toasts, setToasts] = useState<readonly ToastItem[]>([]);
  const [now, setNow] = useState(wall);
  const [span, setSpan] = useState<Span>({ first: 0, last: FIRST_WINDOW - 1 });
  const alive = useRef(true);
  const abort = useRef(new AbortController());
  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    abort.current = controller;
    return () => {
      alive.current = false;
      controller.abort(); // a request in flight resolves into nothing once the tab has gone
    };
  }, []);

  const directory = useMemo(() => new Map(snap.accounts.map((a) => [a.id, a])), [snap.accounts]);
  const environment: Environment | null =
    shellEnv !== "unknown" ? shellEnv : (snap.accounts[0]?.environment ?? null);
  const view = useMemo(
    () => rowsInView(snap.rows, chips, openPositionOf(book)),
    [snap.rows, chips, book],
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

  const readOnly = useMemo(
    () =>
      new Set(
        grants.filter((g) => g.mode === "read").map((g) => g.exchange_account_id.toLowerCase()),
      ),
    [grants],
  );
  const context: CancelContext = {
    viewAs: null, // no client source yet (#911's reading): the server answers view_as_read_only
    permissions,
    readOnlyAccounts: readOnly,
    restReachable: !(link.kind === "offline" && REST_DOWN.has(link.cause)),
    cancelling,
    killSwitch,
    lockedAccounts: new Set(
      [...signals].filter(([, s]) => s.oms?.state === "stale").map(([id]) => id),
    ),
  };
  const gateOf = (row: OrderRowModel): CancelGate => cancelGate(row, context);
  const bulkGate = scopeGate(context);
  const readOnlyId = (accountId: string): string | null =>
    readOnly.has(accountId) ? `${ids}-read-only-${accountId}` : null;
  const noticeOf = (
    gate: Extract<CancelGate, { kind: "gated" }>,
    accountId: string,
  ): string | undefined => {
    if (gate.leg === "permission") return permissionNoticeId;
    if (gate.leg === "offline") return offlineId;
    if (gate.leg === "account_read_only") return readOnlyId(accountId) ?? undefined;
    return undefined;
  };
  const wordsOf = (accountId: string): AccountWords => ({
    label: accountWords(accountId, directory),
    environment: envWord(directory.get(accountId)?.environment ?? environment),
  });

  // RT-13: the selection count, polite, once per change
  const count = selectedRows.length;
  const said = useRef(0);
  useEffect(() => {
    if (count !== said.current && count > 0)
      announcer.say("polite", bindProposed("blotter.ui.sel.count", { "2": String(count) }), "sel");
    said.current = count;
  }, [count, announcer]);

  const toast = (item: Omit<ToastItem, "id">): void => {
    toastSeq += 1;
    const next = { ...item, id: `orders-toast-${toastSeq}` };
    setToasts((all) => [...all, next].slice(-MAX_TOASTS));
  };
  const cancel = (row: OrderRowModel): void => {
    if (gateOf(row).kind !== "allowed") return;
    setCancelling((all) => new Set(all).add(row.id));
    reportCancelAttempted();
    void writes.cancelOrder(row.id, abort.current.signal).then((outcome: CancelOutcome) => {
      if (!alive.current) return;
      setCancelling((all) => {
        const next = new Set(all);
        next.delete(row.id);
        return next;
      });
      const words = {
        BTCUSDT: row.symbol,
        Sell: row.sideLabel,
        "0.250": row.qty === null ? "—" : figure(row.qty),
        Main: row.accountLabel ?? row.accountId,
      };
      if (outcome.kind === "accepted") {
        const at = priceLabel(row, figure);
        toast({ title: bindProposed("blotter.ui.cancel.toast", { ...words, "64,800.0": at }) });
      } else if (outcome.kind === "unavailable") {
        toast({ title: bindProposed("blotter.ui.cancel.unconfirmed", words), tone: "warning" });
      } else {
        toast({
          title: bindProposed("blotter.ui.cancel.failed", words),
          tone: "warning",
          ...(outcome.kind === "native_stop" ? { description: DECK["sl.note"].string } : {}),
        });
      }
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
    void runPlan(plan, writes, abort.current.signal).then((result) => {
      if (alive.current) setBulk({ phase: "result", result, sending: false });
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
    setBulk({ phase: "sending", plan: bulk.plan });
    if (bulk.plan.scope === "selected") setSelected(new Set());
    send(bulk.plan, false);
  };
  const onRetry = (): void => {
    if (bulk?.phase !== "result" || bulk.sending) return;
    const plan = retryPlan(bulk.result, view, chips, gateOf);
    if (plan === null) return;
    setBulk({ ...bulk, sending: true });
    send(plan, true);
  };
  const onCloseBulk = (): void => {
    if (bulk?.phase === "sending") return; // the request runs to its result
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
    readOnlyId,
    cancel,
  };

  const bulkButton = (label: string, onClick: () => void): JSX.Element => {
    const notice = bulkGate?.kind === "gated" ? noticeOf(bulkGate, "") : undefined;
    return bulkGate?.kind === "gated" ? (
      <Button
        disabledReason={bulkGate.reason}
        {...(notice === undefined ? {} : { disabledReasonId: notice })}
        density={density}
      >
        {label}
      </Button>
    ) : (
      <Button density={density} onClick={onClick}>
        {label}
      </Button>
    );
  };
  const end = (
    <>
      {count === 0 ? null : (
        <span className="cv-orders__selection" data-part="SelectionBar">
          <span>{bindProposed("blotter.ui.sel.count", { "2": String(count) })}</span>
          {bulkButton(DECK["blotter.ui.sel.cancel"].string, () =>
            openBulk(planSelected(selectedRows, gateOf)),
          )}
          <Button variant="ghost" density={density} onClick={() => setSelected(new Set())}>
            {bindProposed("blotter.ui.sel.clear")}
          </Button>
        </span>
      )}
      {view.length === 0
        ? null
        : bulkButton(DECK["blotter.ui.bulk.cancel_all"].string, () =>
            openBulk(planAllInView(view, chips, gateOf)),
          )}
    </>
  );

  const windowed = entries.length > WINDOW_FROM;
  const drawn = windowed ? drawnFor(span, entries.length) : { first: 0, last: entries.length - 1 };
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
  const menuOf = (row: OrderRowModel): readonly MenuItem[] => {
    const gate = gateOf(row);
    return [
      {
        id: "cancel",
        label: gate.kind === "busy" ? ORDER_TEXT.cancelling.string : ORDER_TEXT.cancel.string,
        onSelect: () => cancel(row),
        ...(gate.kind === "gated" ? { disabledReason: gate.reason } : {}),
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
    body = (
      <div className="cv-positions__loading" data-part="Loading" aria-busy="true">
        <Skeleton shape="row" count={3} />
      </div>
    );
  } else {
    const empty =
      snap.rows.length > 0 ? (
        <EmptyState
          variant="filtered-empty"
          title={filterEmptyTitle(chips.length)}
          description={chipsRestated(chips, directory)}
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
          rowActions={(e) => (e.kind === "order" ? menuOf(e.row) : [])}
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
              <OrderRow row={e.row} grid={grid} parts={parts} />
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
        accounts={snap.accounts}
        chips={chips}
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
          <p className="cv-positions__reason">{ORDER_TEXT.cannotReachServer.string}</p>
        </div>
      )}
      {body}
      {snap.status === "revoked" ? null : withdrawn}
      <BulkCancelDialog
        state={bulk}
        live={live}
        chipsLine={chipsRestated(chips, directory)}
        wordsOf={wordsOf}
        environment={envWord(environment)}
        onConfirm={onConfirm}
        onRetry={onRetry}
        onClose={onCloseBulk}
        fallbackFocusRef={opener}
      />
      <ToastRegion
        toasts={toasts}
        onDismiss={(id) => setToasts((all) => all.filter((t) => t.id !== id))}
        announce={(politeness, text) => announcer.say(politeness, text)}
      />
    </div>
  );
}
