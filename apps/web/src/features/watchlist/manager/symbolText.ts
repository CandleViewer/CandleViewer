/**
 * A list of symbols as text (E08-D07 §4.4, D14): a paste or an imported file read into tokens, the tokens grouped for
 * the preview, and a list written out for export. Pure: the instrument facts come in as predicates, the text is never
 * interpreted (no markup, no formula), and only the "to add" group can reach a request, each one a Trading symbol of
 * the catalogue (`22` `WatchlistInput.symbols`).
 */
import { LIST_CAP } from "../copy";
import { NAME_MAX, symbolsWord } from "./copy";

/** `22` `Symbol` (L14517): a USDT perpetual's form. */
export const SYMBOL_PATTERN = /^[A-Z0-9]{2,20}USDT$/;
/** §4.4: a token that is no symbol shows cut at 24 characters. */
const RAW_CUT = 24;

/**
 * A text's tokens: split on newlines, commas, semicolons, spaces and tabs (any white space); a line starting with `#`
 * dropped; each token trimmed and upper-cased; empty ones dropped and duplicates collapsed, in order.
 */
export function tokensOf(text: string): readonly string[] {
  const seen = new Set<string>();
  for (const line of text.split(/\r\n|\r|\n/)) {
    if (line.trimStart().startsWith("#")) continue;
    for (const part of line.split(/[,;\s]+/)) {
      const token = part.trim().toUpperCase();
      if (token !== "") seen.add(token);
    }
  }
  return [...seen];
}

/** What the preview shows (§4.4): what is added and what is not, and why, each as plain text. */
export interface SymbolGroups {
  /** Trading symbols not on the list, within the cap: what "Add N symbols" adds. */
  readonly add: readonly string[];
  readonly onList: readonly string[];
  /** Trading symbols past the cap (§4.4 "12 symbols not added: a watchlist holds at most 200."). */
  readonly overCap: readonly string[];
  /** The form of a symbol, but not a Trading instrument of the catalogue. */
  readonly notFound: readonly string[];
  readonly delisted: readonly string[];
  /** Not the form of a symbol: the token, cut at 24 characters. */
  readonly invalid: readonly string[];
}

export interface GroupFacts {
  /** The list's symbols now. */
  readonly onList: ReadonlySet<string>;
  /** A Trading instrument of the catalogue (E08-S09's index). */
  readonly trading: (symbol: string) => boolean;
  /** Delisted by the exchange (`Instrument.delisted`, as the index or a lookup knows it). */
  readonly delisted: (symbol: string) => boolean;
}

const cut = (token: string): string => {
  const chars = [...token];
  return chars.length > RAW_CUT ? `${chars.slice(0, RAW_CUT).join("")}…` : token;
};

export function groupSymbols(tokens: readonly string[], facts: GroupFacts): SymbolGroups {
  const room = Math.max(0, LIST_CAP - facts.onList.size);
  const groups = {
    add: [] as string[],
    onList: [] as string[],
    overCap: [] as string[],
    notFound: [] as string[],
    delisted: [] as string[],
    invalid: [] as string[],
  };
  for (const token of tokens) {
    if (!SYMBOL_PATTERN.test(token)) groups.invalid.push(cut(token));
    else if (facts.delisted(token)) groups.delisted.push(token);
    else if (!facts.trading(token)) groups.notFound.push(token);
    else if (facts.onList.has(token)) groups.onList.push(token);
    else if (groups.add.length < room) groups.add.push(token);
    else groups.overCap.push(token);
  }
  return groups;
}

/** The tokens a lookup could tell apart: the form of a symbol, neither Trading nor known delisted. */
export const unknownTokens = (tokens: readonly string[], facts: GroupFacts): readonly string[] =>
  tokens.filter((t) => SYMBOL_PATTERN.test(t) && !facts.trading(t) && !facts.delisted(t));

/**
 * A name as `22` `WatchlistInput.name` takes one: its format characters (Unicode Cf: zero-width marks, bidirectional
 * overrides) dropped, each run of control characters (Cc: a tab, a bell) one space, then trimmed. The server refuses
 * a name holding either kind (422), so none is sent; a name made of them alone is empty.
 */
export function cleanName(name: string): string {
  return name
    .replace(/\p{Cf}/gu, "")
    .replace(/\p{Cc}+/gu, " ")
    .trim();
}

/**
 * A file's name as a list's name (§4.3): without its extension, cleaned (`cleanName`), its white space runs one space,
 * at most 80 characters.
 */
export function nameOfFile(fileName: string): string {
  const dot = fileName.lastIndexOf(".");
  const stem = cleanName(dot > 0 ? fileName.slice(0, dot) : fileName).replace(/\s+/gu, " ");
  return [...stem].slice(0, NAME_MAX).join("").trim();
}

/** `base` if no name in `taken` is it (trimmed, case-insensitive), else "base 2", "base 3", … (§4.3, DJ). */
export function freeName(base: string, taken: readonly string[]): string {
  const held = new Set(taken.map((name) => name.trim().toLowerCase()));
  for (let n = 1; ; n += 1) {
    const suffix = n === 1 ? "" : ` ${n}`;
    const stem = [...base].slice(0, NAME_MAX - suffix.length).join("");
    const name = `${stem}${suffix}`;
    if (!held.has(name.trim().toLowerCase())) return name;
  }
}

/**
 * §4.4 Export: `<list name>.txt`, every character but letters, digits, space, `_` and `-` replaced by `-`; one header
 * line, then one symbol per line in list order, and nothing else (no account, key, user or position data).
 */
export function exportFile(
  name: string,
  symbols: readonly string[],
  at: Date,
): { readonly fileName: string; readonly text: string } {
  const stamp = `${at.toISOString().slice(0, 10)} ${at.toISOString().slice(11, 16)} UTC`;
  const header = `# CandleViewer watchlist "${name}", ${symbolsWord(symbols.length)}, exported ${stamp}`;
  return {
    fileName: `${name.replace(/[^\p{L}\p{N} _-]/gu, "-")}.txt`,
    text: `${[header, ...symbols].join("\n")}\n`,
  };
}
