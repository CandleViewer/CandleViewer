/**
 * The Positions panel's view state (E29-S01 #911, BQ-16): the tab, the group-by, the filter chips,
 * the columns per tab and the density, per user on this device, under one versioned key, in the
 * `layoutStore` shape (a `useSyncExternalStore` pub/sub): no pane host or workspace client exists
 * yet, so the shape is one E15 can lift into the layout document as it stands. Storage may be
 * missing or throw: reads fall back to the defaults and writes are dropped.
 *
 * Deep links (`12-sitemap.md` §7, R-130): `?groupBy=account|symbol` and `?account=<uuid>` set the
 * view; a deep-linked value is not persisted (it is "persisted per-user if changed interactively").
 * `manager` is read as no value: Group by Manager is not offered (BQ-10). `trade_group` has no
 * deep-link form (D04-G2). The server re-validates an account's scope whatever the link says.
 */
import { useSyncExternalStore } from "react";
import { normaliseChip, reduceFilters, type FilterAction, type FilterChip } from "./model/filters";
import { GROUP_BYS, type GroupBy } from "./model/grouping";
import { isUuid } from "./model/rowMapping";

export type PanelTab = "positions" | "working_orders" | "fills" | "trade_groups" | "algos";
export type Density = "compact" | "comfortable";

export interface PanelState {
  readonly tab: PanelTab;
  readonly groupBy: GroupBy;
  readonly chips: readonly FilterChip[];
  /** The visible column ids per tab, in order; a tab not named shows its defaults. */
  readonly columns: Readonly<Partial<Record<PanelTab, readonly string[]>>>;
  readonly density: Density;
}

/** D02 D-17: the five tabs, fixed. */
export const PANEL_TABS: readonly PanelTab[] = [
  "positions",
  "working_orders",
  "fills",
  "trade_groups",
  "algos",
];
export const PANEL_STORAGE_KEY = "cv.positions.panel.v1";
const VERSION = 1;
const MAX_COLUMNS = 32;
const COLUMN_ID = /^[a-z][a-z0-9_]{0,31}$/;

export const DEFAULT_PANEL_STATE: PanelState = Object.freeze({
  tab: "positions",
  groupBy: "account",
  chips: [],
  columns: {},
  density: "compact",
});

const keyOf = (user: string): string => `${PANEL_STORAGE_KEY}:${user}`;

function columnsOf(raw: unknown): PanelState["columns"] {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return {};
  const out: Partial<Record<PanelTab, readonly string[]>> = {};
  for (const tab of PANEL_TABS) {
    const list: unknown = (raw as Record<string, unknown>)[tab];
    if (!Array.isArray(list)) continue;
    const ids = list.filter((id): id is string => typeof id === "string" && COLUMN_ID.test(id));
    out[tab] = [...new Set(ids)].slice(0, MAX_COLUMNS);
  }
  return out;
}

/** A stored value read back, each field checked on its own: a bad one falls back alone. */
export function parsePanelState(raw: unknown): PanelState {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return DEFAULT_PANEL_STATE;
  const v = raw as Record<string, unknown>;
  if (v["v"] !== VERSION) return DEFAULT_PANEL_STATE; // another version's shape: never guessed at
  const chips = Array.isArray(v["chips"])
    ? reduceFilters([], { type: "replace", chips: v["chips"] as FilterChip[] })
    : [];
  return {
    tab: PANEL_TABS.find((t) => t === v["tab"]) ?? DEFAULT_PANEL_STATE.tab,
    groupBy: GROUP_BYS.find((g) => g === v["groupBy"]) ?? DEFAULT_PANEL_STATE.groupBy,
    chips,
    columns: columnsOf(v["columns"]),
    density: v["density"] === "comfortable" ? "comfortable" : "compact",
  };
}

function read(user: string | null): PanelState {
  if (user === null) return DEFAULT_PANEL_STATE;
  try {
    const raw = globalThis.localStorage?.getItem(keyOf(user)) ?? null;
    return raw === null ? DEFAULT_PANEL_STATE : parsePanelState(JSON.parse(raw));
  } catch {
    return DEFAULT_PANEL_STATE;
  }
}

function write(user: string | null, state: PanelState): void {
  if (user === null) return; // no one signed in: the view holds for this page only
  try {
    globalThis.localStorage?.setItem(keyOf(user), JSON.stringify({ v: VERSION, ...state }));
  } catch {
    // no storage: the choice lasts for this page only
  }
}

let user: string | null = null;
let state: PanelState = DEFAULT_PANEL_STATE;
const listeners = new Set<() => void>();

function set(next: PanelState, persist: boolean): void {
  if (persist) write(user, next);
  if (next === state) return;
  state = next;
  for (const listener of [...listeners]) listener();
}

export const getPanelState = (): PanelState => state;

export function subscribePanelState(listener: () => void): () => void {
  listeners.add(listener);
  return () => void listeners.delete(listener);
}

/** Whose view this is: loads that user's stored state (or the defaults for none). */
export function setPanelUser(next: string | null): void {
  user = next;
  set(read(next), false);
}

/** An interactive change: applied and stored for the user. */
export function updatePanelState(patch: Partial<PanelState>): void {
  set({ ...state, ...patch }, true);
}

export function updateChips(action: FilterAction): void {
  const chips = reduceFilters(state.chips, action);
  if (chips !== state.chips) updatePanelState({ chips });
}

export interface DeepLink {
  readonly groupBy?: "account" | "symbol";
  readonly account?: string;
}

/** R-130's deep link from a location search string; an unknown or malformed value is no value. */
export function readDeepLink(search: string): DeepLink {
  const params = new URLSearchParams(search);
  const groupBy = params.get("groupBy");
  const account = params.get("account");
  return {
    ...((groupBy === "account" || groupBy === "symbol") && { groupBy }),
    ...(isUuid(account) && { account: account.toLowerCase() }),
  };
}

/** The view a deep link opens: its group-by, and its account as the one Account chip. Not stored. */
export function applyDeepLink(link: DeepLink): void {
  const chip =
    link.account === undefined ? null : normaliseChip({ kind: "account", value: link.account });
  const chips =
    chip === null ? state.chips : [...state.chips.filter((c) => c.kind !== "account"), chip];
  set({ ...state, ...(link.groupBy !== undefined && { groupBy: link.groupBy }), chips }, false);
}

/** The deep link of the view (account and symbol group-bys; the first Account chip). */
export function deepLinkSearch(view: PanelState): string {
  const params = new URLSearchParams();
  if (view.groupBy === "account" || view.groupBy === "symbol") params.set("groupBy", view.groupBy);
  const account = view.chips.find((c) => c.kind === "account");
  if (account !== undefined) params.set("account", account.value);
  const text = params.toString();
  return text === "" ? "" : `?${text}`;
}

/** Back to a fresh page's state (tests, sign-out). */
export function resetPanelState(): void {
  user = null;
  set(DEFAULT_PANEL_STATE, false);
}

/** One field of the panel state; a component re-renders only when that field changes. */
export function usePanelState<K extends keyof PanelState>(key: K): PanelState[K] {
  const field = (): PanelState[K] => state[key];
  return useSyncExternalStore(subscribePanelState, field, field);
}
