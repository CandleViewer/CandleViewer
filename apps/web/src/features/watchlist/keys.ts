/**
 * The Watchlist focus context (E08-D07 §6.2; E08-D12 KB-17, KB-18, KB-20, G-04). SCR-100's panel carries
 * `data-keymap-context="Watchlist"`, whose rows in `keymap.json` are the panel's own keys: `Del` removes the focused
 * row, `Alt+↑/↓` move it, `Ctrl+F` focuses the filter, each remappable in SCR-113 as any view's key is. The focused
 * row runs its key itself, by the binding the profile holds now (`rowKeyOf`, CMP-161's `keyOf`), with its T2 echo and
 * its held-key rules, and a body row is one with `aria-rowindex` from 2 (the header row is 1). The filter key is the
 * command's own: it focuses the filter of the panel that has focus, from anywhere in it (its tab strip included), and
 * is valid only where the panel draws one; with the panel loading, failed or holding no list the key is not taken and
 * the browser's find opens (C-5335-d01). The context's handlers take the key, so the window keymap neither runs
 * another view's command on it (the rules editor's "Reorder down" on `Alt+↓`) nor reports one; a key pressed off a row
 * is said to need one ("Move row up is not available here (Watchlist view): …"). `Enter` and `Ctrl+C` stay CMP-161's
 * own and the arrows CMP-049's: a `Ctrl+C` row would report every copy outside the panel.
 *
 * SCR-101 is a modal whose keys are its own (KB-21, KB-22: `F2`, `Del`, `Alt+↑/↓` in its lists, grid and columns): its
 * root stops every key typed in it but `Esc` and a Global chord (`stopManagerKeys`), as SCR-102's does (E08-D05 §8).
 */
import { useEffect, type KeyboardEvent } from "react";
import { registerCommand } from "../../keymap/KeymapHost";
import { bindingFor, eventBinding, type KeyEventLike } from "../../keymap/keymap";
import { getBindings } from "../../keymap/profile";
import { globalChord } from "../symbol-search/keys";

/** The `data-keymap-context` of SCR-100's root (`keymap.json`'s context). */
export const WATCHLIST_CONTEXT = "Watchlist";

/** CMP-161's row keys, by their commands. */
const ROW_COMMANDS = {
  remove: "watchlist.remove",
  up: "watchlist.move_up",
  down: "watchlist.move_down",
} as const;
export type RowKey = keyof typeof ROW_COMMANDS;
const FILTER_COMMAND = "watchlist.filter";

/** Whether `event` is `command`'s binding as the profile holds it now; an unbound command takes no key. */
function boundTo(event: KeyEventLike, command: string): boolean {
  const binding = getBindings().get(command) ?? bindingFor(command);
  return binding !== "" && eventBinding(event) === binding;
}

/** Which of CMP-161's row keys a press is, by the profile's bindings (its `keyOf`). */
export function rowKeyOf(event: KeyEventLike): RowKey | null {
  for (const key of ["remove", "up", "down"] as const)
    if (boundTo(event, ROW_COMMANDS[key])) return key;
  return null;
}

/**
 * Focus on a symbol's row of a watchlist's grid: where the row keys run. The header row is `aria-rowindex` 1 and the
 * empty list's state row is 2, with no row header (CMP-161's symbol is a `th scope="row"`, as the DS Table draws it).
 */
const onRow = (): boolean => {
  const row = document.activeElement?.closest(
    `[data-keymap-context="${WATCHLIST_CONTEXT}"] tr[aria-rowindex]`,
  );
  if (row === null || row === undefined) return false;
  return (
    Number(row.getAttribute("aria-rowindex")) >= 2 && row.querySelector('th[scope="row"]') !== null
  );
};

/** The filter of the Watchlist panel that has focus: the search box its list view draws, none until it has a list. */
const panelFilter = (): HTMLInputElement | null =>
  document.activeElement
    ?.closest(`[data-keymap-context="${WATCHLIST_CONTEXT}"]`)
    ?.querySelector<HTMLInputElement>('input[type="search"]') ?? null;

/** The row ran the key: the context only takes it. */
const taken = (): void => undefined;

const focusFilter = (): void => panelFilter()?.focus();

let panels = 0;
let release: (() => void) | null = null;

/** Registers the context's handlers while a watchlist panel is mounted (the registry takes one per command). */
export function useWatchlistKeys(): void {
  useEffect(() => {
    panels += 1;
    if (panels === 1) {
      const offs = [
        ...Object.values(ROW_COMMANDS).map((id) => registerCommand(id, taken, onRow)),
        registerCommand(FILTER_COMMAND, focusFilter, () => panelFilter() !== null),
      ];
      release = () => offs.forEach((off) => off());
    }
    return () => {
      panels -= 1;
      if (panels > 0) return;
      release?.();
      release = null;
    };
  }, []);
}

/**
 * SCR-101's key stop (E08-D05 §8, as SCR-102's): a key typed in the manager stops at its root, so the window keymap
 * neither runs nor reports it; `Esc` goes on (the layer stack closes the topmost layer on it) and so does a Global
 * chord.
 */
export function stopManagerKeys(event: KeyboardEvent): void {
  if (event.key === "Escape" || globalChord(event)) return;
  event.stopPropagation();
}
