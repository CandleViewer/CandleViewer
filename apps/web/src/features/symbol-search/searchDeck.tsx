/**
 * E08-D05 §6.2's states for a query that ranks nothing, the deck SCR-102 and SCR-041 share (§7), adopted from PR D's
 * `searchDeck` (SCR-041's builder wrote it first): the status rule, a remembered symbol gone from Bybit, and No matches
 * (CMP-026 `filtered-empty`; after a check, Check again is T2 `search.check_cooldown` for 60 s, through CMP-026's own
 * `disabledReason`: CMP-079 takes E09-D09's RBAC keys only). The check's line is the host's to place (SCR-102's detail
 * bar, SCR-041's list region). Also shared: the caption line and the focus rule (`useFocusHome`).
 */
import {
  useEffect,
  useLayoutEffect,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type JSX,
} from "react";
import { EmptyState, type EmptyStateAction, type EmptyStateActions } from "@candleviewer/ui";
import { COPY, statusText } from "./copy";
import type { InstrumentIndex } from "./instrumentIndex";
import type { Instrument, SearchResult } from "./ranking";
import {
  checkableSymbol,
  createSymbolCheck,
  type CheckSnapshot,
  type SymbolCheck,
} from "./symbolCheck";

/** A caption line: `type.ui.caption` in `color.text.secondary`, its glyphs and key caps in a row. */
export const LINE: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "var(--space-inset-sm)",
  margin: 0,
  color: "var(--color-text-secondary)",
  font: "var(--type-ui-caption-font-weight) var(--type-ui-caption-font-size) / var(--type-ui-caption-line-height) var(--type-ui-caption-font-family)",
};

/** A query that ranks nothing: the status rule, a Recent or current symbol whose lookup answered 404, or none. */
export type Unmatched =
  | { readonly kind: "status"; readonly instrument: Instrument }
  | { readonly kind: "gone"; readonly symbol: string }
  | { readonly kind: "none" };

/** The deck's case for `result` (`null` when it ranks or no list is in memory); `remembered`: Recent and the current. */
export function unmatchedOf(
  query: string,
  result: SearchResult,
  unlisted: readonly string[],
  remembered: readonly string[],
): Unmatched | null {
  if (result.kind === "status") return result;
  if (result.kind !== "none") return null;
  const symbol = checkableSymbol(query);
  const gone = symbol !== null && unlisted.includes(symbol) && remembered.includes(symbol);
  return gone ? { kind: "gone", symbol } : result;
}

export interface Deck {
  /** In the list's place; `null` while the rest and a first check run: nothing reads "no matches" before its answer. */
  readonly node: JSX.Element | null;
  /** "Checking Bybit for X…" while a check runs, else `null`. */
  readonly checking: string | null;
  /** The surface's one polite region (§9.2): the state's sentence, `""` to stay quiet. */
  readonly said: string;
  /** What `Enter` with no openable option says again (§6.2): the block's heading, or the check's line. */
  readonly heading: string | null;
  /** §12.1's `empty_state_shown` reason while a block shows. */
  readonly reason: "no_matches" | "scope_filtered" | null;
}

export interface DeckActions {
  readonly clear: () => void;
  readonly checkAgain: () => void;
  /** SCR-103's port, once registered: the status rule's View symbol info. */
  readonly info?: ((symbol: string) => void) | undefined;
}

const block = (title: string, words: string, actions: EmptyStateActions): JSX.Element => (
  <EmptyState variant="filtered-empty" title={title} description={words} actions={actions} />
);

/**
 * The deck for `unmatched`, the check's snapshot and `query` as typed. Check again keeps its block, and the focus on
 * it, while it runs (A11Y-D-01): only its line is new.
 */
export function searchDeck(
  query: string,
  unmatched: Unmatched,
  check: CheckSnapshot,
  on: DeckActions,
): Deck {
  const clear = { label: COPY.clear, onClick: on.clear, variant: "secondary" } as const;
  if (unmatched.kind !== "none") {
    const status = unmatched.kind === "status" ? unmatched.instrument : null;
    const symbol = status?.symbol ?? (unmatched.kind === "gone" ? unmatched.symbol : "");
    const title = status === null ? COPY.gone(symbol) : COPY.notTrading(symbol);
    const words = `${status === null ? "" : statusText(status)} ${COPY.cantOpen}`.trim();
    const { info } = on;
    const view = {
      label: COPY.viewInfo,
      onClick: () => info?.(symbol),
      variant: "secondary",
    } as const;
    const actions =
      status === null || info === undefined ? ([clear] as const) : ([view, clear] as const);
    return {
      node: block(title, words, actions),
      checking: null,
      said: title,
      heading: title,
      reason: "scope_filtered",
    };
  }
  const symbol = checkableSymbol(query);
  // The check answers the query it was asked about; until it is asked about this one, the rest runs.
  const asked = check.symbol === symbol;
  const phase = asked ? check.phase : "waiting";
  const checking = phase === "checking" && symbol !== null ? COPY.checking(symbol) : null;
  // After a check of this symbol: when, and Check again; a first check has no block yet.
  const at = asked && symbol !== null ? check.checkedAt : null;
  if (phase === "waiting" || (checking !== null && at === null))
    return { node: null, checking, said: checking ?? "", heading: checking, reason: null };
  const title = COPY.noMatch(query.trim());
  const unchecked = phase === "unchecked" && symbol !== null ? [COPY.unchecked(symbol)] : [];
  const lines = [COPY.scope, COPY.hint, ...(at === null ? [] : [COPY.checked(at)]), ...unchecked];
  const again: EmptyStateAction = {
    label: COPY.checkAgain,
    onClick: on.checkAgain,
    variant: "secondary",
    ...(check.coolingDown ? { disabledReason: COPY.cooldown } : {}),
  };
  return {
    node: block(title, lines.join(" "), at === null ? [clear] : [clear, again]),
    checking,
    said: checking ?? `${title} ${COPY.scope}`,
    heading: title,
    reason: "no_matches",
  };
}

const IDLE: CheckSnapshot = {
  phase: "idle",
  symbol: null,
  instrument: null,
  checkedAt: null,
  coolingDown: false,
};
const unsubscribed = (): (() => void) => () => undefined;
const idle = (): CheckSnapshot => IDLE;

/**
 * §6.2's symbol check for one opening of a surface: made in an effect, so StrictMode's rehearsal stops only its own,
 * and asked about `query` whenever it or the list changes (a new listing may answer it); `""` cancels it.
 */
export function useSymbolCheck(
  index: InstrumentIndex,
  query: string,
): { readonly check: SymbolCheck | null; readonly checked: CheckSnapshot } {
  const live = useSyncExternalStore(index.subscribe, index.getSnapshot);
  const [check, setCheck] = useState<SymbolCheck | null>(null);
  useEffect(() => {
    const made = createSymbolCheck(index);
    setCheck(made);
    return () => made.stop();
  }, [index]);
  const checked = useSyncExternalStore(
    check?.subscribe ?? unsubscribed,
    check?.getSnapshot ?? idle,
  );
  useEffect(() => {
    check?.request(query);
  }, [check, query, live]);
  return { check, checked };
}

/**
 * §9.2: focus never falls to the page. A control that goes with its state (Retry now as the list comes, Check again
 * or Clear search as results come, the `⋯` with its option) leaves it on `body`: while `live`, it goes back to the
 * input (`home`), where the surface starts. Focus anywhere else is never moved, so a refresh moves nothing.
 */
export function useFocusHome(home: () => HTMLElement | null | undefined, live: boolean): void {
  useLayoutEffect(() => {
    const at = document.activeElement;
    if (live && (at === null || at === document.body)) home()?.focus();
  });
}
