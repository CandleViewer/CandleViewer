/**
 * SCR-102's "Add to watchlist…" (E08-D05 §6.3; E08-D07 D36 and board 08, "Adding from search"; `14` SCR-102), built
 * on SCR-101's REST client. A CMP-041 submenu of the user's lists with their counts, the list SCR-100 last showed
 * first: "Majors, 12 symbols". A list that holds the symbol shows its outcome in its label, "Majors, 12 symbols · has
 * ETHUSDT", never T2 (§6.6), and choosing it adds nothing: SCR-102's region says "ETHUSDT is already on Majors."; a
 * full list without it is T2 with D10's words; with no list, one item, "New watchlist with ETHUSDT", creates one, named
 * as §4.3 names a new list. Choosing a list adds the symbol at its end with one `replace` against the version read
 * (`If-Match`, `22` `updateWatchlist`); the menus close, focus goes back to SCR-102's input, and one polite line says
 * the outcome in its region: "Added ETHUSDT to Majors.", a conflict's (another window changed the list: the next
 * opening reads it again), a refusal's or a failure's words. Without `workspaces:write` the item itself is T2
 * (E08-D05 §6.3's Viewer row; the interim verb, as SCR-100's). A delisted row has no item (its host leaves it out).
 * The lists are read each time the menu opens; each list stored goes to SCR-100 (`appWatchlistSync`).
 */
import { useEffect, useState } from "react";
import { watchlistCountName, type MenuItem } from "@candleviewer/ui";
import { reportWatchlist } from "./analytics";
import { COPY, LIST_CAP } from "./copy";
import type { Watchlist } from "./listEdits";
import { MANAGER_COPY } from "./manager/copy";
import { freeName } from "./manager/symbolText";
import { ROUTE_PANE, localPaneSettings } from "./ports";
import { appWatchlistSync } from "./sync";
import { createWatchlistApi, type ManagerApi } from "./watchlistApi";

/** The user's lists as the chooser read them. */
export type ChooserLists =
  | { readonly kind: "loading" }
  | { readonly kind: "failed" }
  | { readonly kind: "ready"; readonly lists: readonly Watchlist[] };

/** What a chosen item does. */
export interface ChooserActions {
  /** Adds `symbol` at the end of `list`. */
  readonly add: (list: Watchlist) => void;
  /** Says the list already holds it; adds nothing. */
  readonly already: (list: Watchlist) => void;
  /** Creates a list holding `symbol` (no list yet). */
  readonly create: () => void;
}

const nothing = (): void => undefined;

/**
 * SCR-102's item for `symbol`: T2 without `workspaces:write`, else the submenu of `lists` (the one `firstId` names
 * first), as they are read.
 */
export function watchlistChooserItem(
  symbol: string,
  lists: ChooserLists,
  writable: boolean,
  firstId: string | undefined,
  act: ChooserActions,
): MenuItem {
  const item = { id: "watchlist", label: COPY.addToWatchlist } as const;
  if (!writable) return { ...item, disabledReason: COPY.writeReason, items: [] };
  if (lists.kind === "loading")
    return {
      ...item,
      items: [{ id: "loading", label: COPY.listsLoading, busy: true, onSelect: nothing }],
    };
  if (lists.kind === "failed")
    return {
      ...item,
      items: [{ id: "failed", label: COPY.loadFailed, disabled: true, onSelect: nothing }],
    };
  if (lists.lists.length === 0)
    return { ...item, items: [{ id: "new", label: COPY.newWith(symbol), onSelect: act.create }] };
  const ordered = [
    ...lists.lists.filter((l) => l.id === firstId),
    ...lists.lists.filter((l) => l.id !== firstId),
  ];
  return {
    ...item,
    items: ordered.map((list): MenuItem => {
      const name = watchlistCountName(list.name, list.symbols.length);
      // On the list: its outcome, never T2 (§6.6); choosing it says so and adds nothing.
      if (list.symbols.includes(symbol))
        return {
          id: list.id,
          label: COPY.hasSymbol(name, symbol),
          onSelect: () => act.already(list),
        };
      return list.symbols.length >= LIST_CAP
        ? { id: list.id, label: name, disabledReason: COPY.capFull, onSelect: nothing }
        : { id: list.id, label: name, onSelect: () => act.add(list) };
    }),
  };
}

export interface ChooserOptions {
  /** The session's `workspaces:write` (the server enforces it, C-2.12). */
  readonly writable: boolean;
  /** One polite line in SCR-102's region. */
  readonly say: (text: string) => void;
  /** After a choice: focus back to SCR-102's input. */
  readonly done: () => void;
  /** The REST client; the app's by default. */
  readonly api?: ManagerApi;
}

/**
 * SCR-102's chooser while its action menu is `open`: the lists read once per opening, and the item for a symbol.
 */
export function useWatchlistChooser(
  open: boolean,
  options: ChooserOptions,
): (symbol: string) => MenuItem {
  const { writable, say, done } = options;
  const [api] = useState(() => options.api ?? createWatchlistApi());
  const [lists, setLists] = useState<ChooserLists>({ kind: "loading" });
  useEffect(() => {
    if (!open || !writable) return undefined;
    const controller = new AbortController();
    setLists({ kind: "loading" });
    api.list(controller.signal).then(
      (read) => {
        if (!controller.signal.aborted) setLists({ kind: "ready", lists: read });
      },
      () => {
        if (!controller.signal.aborted) setLists({ kind: "failed" });
      },
    );
    return () => controller.abort();
  }, [open, writable, api]);

  /** A stored list goes to SCR-100 and replaces the one read, so a second choice reads its new count. */
  const stored = (list: Watchlist): void => {
    appWatchlistSync.publish({ kind: "stored", list });
    setLists((now) =>
      now.kind === "ready"
        ? {
            kind: "ready",
            lists: now.lists.some((l) => l.id === list.id)
              ? now.lists.map((l) => (l.id === list.id ? list : l))
              : [...now.lists, list],
          }
        : now,
    );
  };

  return (symbol) =>
    watchlistChooserItem(symbol, lists, writable, localPaneSettings.read(ROUTE_PANE).watchlist_id, {
      already: (list) => {
        done();
        say(COPY.alreadyOn(symbol, list.name));
      },
      add: (list) => {
        done();
        void api
          .replace(list, {
            name: list.name,
            symbols: [...list.symbols, symbol],
            columns: list.columns,
          })
          .catch(() => ({ kind: "failed" }) as const)
          .then((outcome) => {
            if (outcome.kind === "saved") {
              stored(outcome.list);
              reportWatchlist({ name: "watchlist.symbol_added", watchlist_id: list.id, symbol });
              say(COPY.added(symbol, list.name));
            } else
              say(
                outcome.kind === "conflict"
                  ? COPY.conflict(list.name)
                  : outcome.kind === "refused"
                    ? COPY.notSent
                    : COPY.addFailed(symbol, list.name),
              );
          });
      },
      create: () => {
        done();
        const names = lists.kind === "ready" ? lists.lists.map((l) => l.name) : [];
        const name = freeName(MANAGER_COPY.defaultName, names);
        void api
          .create({ name, symbols: [symbol] })
          .catch(() => ({ kind: "failed" }) as const)
          .then((outcome) => {
            if (outcome.kind === "saved") {
              stored(outcome.list);
              reportWatchlist({ name: "watchlist.created", watchlist_id: outcome.list.id });
              say(COPY.added(symbol, outcome.list.name));
            } else
              say(
                outcome.kind === "name_taken"
                  ? MANAGER_COPY.nameTaken(name)
                  : outcome.kind === "refused"
                    ? COPY.notSent
                    : COPY.addFailed(symbol, name),
              );
          });
      },
    });
}
