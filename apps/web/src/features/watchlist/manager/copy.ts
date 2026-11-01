/**
 * SCR-101's words (E08-D07 §4.3, §4.4, §6.4, §6.7): verbatim where the spec quotes them, else its proposed copy; a
 * string the spec does not give is marked PROPOSED here and carried as a G-row on #4702 (owner E08-D07). Words SCR-100
 * shares (the list cap, the reasons, the no-list state, the save errors) are its `COPY`'s, never a second copy.
 */
import { LIST_CAP } from "../copy";

/** "1 symbol", "12 symbols". */
export const symbolsWord = (n: number): string => (n === 1 ? "1 symbol" : `${n} symbols`);

/** E08-D07 D14: a file is read up to 64 KB. */
export const MAX_FILE_BYTES = 64 * 1024;
/** E08-D07 §4.3: list names are 1 to 80 characters. */
export const NAME_MAX = 80;

export const MANAGER_COPY = {
  title: "Watchlists",
  lists: "Lists",
  newList: "New watchlist",
  /** §4.3 "Watchlist 2": a new list's name, then " 2", " 3" while taken (§4.4's rule for a taken name). */
  defaultName: "Watchlist",
  copyOf: (name: string): string => `${name} copy`,
  /** PROPOSED: the inline rename field's name. */
  nameField: "Watchlist name",
  /** PROPOSED (A-5335-12): the rename field's key hint, its description. */
  nameHint: "Enter saves the name; Esc cancels.",
  heading: (name: string, count: number): string => `${name} · ${symbolsWord(count)}`,
  actionsFor: (name: string): string => `Actions for ${name}`,
  rename: "Rename",
  duplicate: "Duplicate",
  exportItem: "Export",
  deleteItem: "Delete…",
  symbolsTab: "Symbols",
  columnsTab: "Columns",
  paste: "Paste symbols",
  importLabel: "Import…",
  exportList: (name: string): string => `Export ${name}`,
  /** The symbol grid's headers (§4.3; the board's one "Move" header is two columns, one per button). */
  position: "#",
  symbol: "Symbol",
  moveUpHeader: "Move up",
  moveDownHeader: "Move down",
  removeHeader: "Remove",
  moveUp: (symbol: string): string => `Move ${symbol} up`,
  moveDown: (symbol: string): string => `Move ${symbol} down`,
  remove: (symbol: string): string => `Remove ${symbol}`,
  /** PROPOSED: the symbol grid's caption. */
  caption: (name: string, count: number): string => `Symbols of ${name}, ${symbolsWord(count)}`,
  /** §4.3 Empty: an empty list's own state (its actions are the toolbar's). */
  emptyList: (name: string): string => `No symbols on ${name}`,
  /** §4.5's removal, cut: SCR-101 has no Undo. */
  removed: (symbol: string): string => `Removed ${symbol}.`,
  saving: "Saving…",
  saved: (utc: string): string => `Saved ${utc} UTC`,
  close: "Close",
  pasteLabel: "Paste symbols, one per line or separated by commas or spaces",
  preview: "Preview",
  /** PROPOSED: the import preview's heading. */
  previewOf: (file: string): string => `Preview of ${file}`,
  addN: (n: number): string => `Add ${symbolsWord(n)}`,
  /** §4.3 "Import into: a new list 'Breakouts' / Add to Majors" (proposed). */
  importInto: (name: string): string => `Import into a new list "${name}"`,
  addTo: (name: string): string => `Add to ${name}`,
  /** §4.4's preview groups; "To add" is PROPOSED. */
  toAdd: "To add",
  alreadyOn: (name: string): string => `Already on ${name}`,
  notFound: "Not found on Bybit USDT perps",
  delisted: "Delisted by the exchange",
  invalid: "Not a USDT perpetual symbol",
  overCap: (n: number): string =>
    `${symbolsWord(n)} not added: a watchlist holds at most ${LIST_CAP}.`,
  /** §4.4 rejected before parsing. */
  oversized: (size: string): string =>
    `This file is ${size}. A watchlist file can be at most 64 KB.`,
  notText: "This file isn't plain text.",
  noSymbols: "This file has no symbols.",
  /** PROPOSED (C-5335-02): a paste is read up to the file's 64 KB. */
  pasteTooLong: "Paste at most 64 KB of text.",
  /** PROPOSED (C-5335-12): a paste with no token, as a file with none says it. */
  pasteEmpty: "This text has no symbols.",
  /** PROPOSED: the one polite summary after a paste or an import (§6.5). */
  added: (n: number, name: string): string => `Added ${symbolsWord(n)} to ${name}.`,
  imported: (n: number, name: string): string => `Imported ${symbolsWord(n)} into ${name}.`,
  /** §4.3 Validation. */
  nameEmpty: "Name the watchlist.",
  nameLong: `Use ${NAME_MAX} characters or fewer.`,
  nameTaken: (name: string): string => `A watchlist named ${name} already exists.`,
  /** §4.3 Delete confirm. */
  deleteTitle: (name: string): string => `Delete ${name}?`,
  deleteBody: (count: number): string =>
    `The list and its ${symbolsWord(count)} are removed. Recordings, charts and alerts are not affected.`,
  deleteConfirm: (name: string): string => `Delete ${name}`,
  /** PROPOSED: a delete that failed, in the confirm, with Retry. */
  deleteFailed: (name: string): string => `Could not delete ${name}.`,
  /**
   * PROPOSED (C-5335-01): a copy without the symbols that no longer trade, which a create refuses (`22` 422
   * `unknown_symbol`): up to three named, then "and N more".
   */
  leftOut: (name: string, symbols: readonly string[]): string => {
    const more = symbols.length > 3 ? ` and ${symbols.length - 3} more` : "";
    return `${name} leaves out ${symbols.slice(0, 3).join(", ")}${more}: not trading on Bybit.`;
  },
  /** PROPOSED (C-5335-05): Reload or Overwrite found the list deleted in another window. */
  gone: (name: string): string => `${name} was deleted in another window.`,
  /** PROPOSED (C-5335-05): Reload or Overwrite could not read the lists again; the conflict stays. */
  reloadFailed: (name: string): string => `Could not reload ${name}.`,
  /** §4.3 Save failed's conflict. */
  overwrite: "Overwrite with my version",
} as const;
