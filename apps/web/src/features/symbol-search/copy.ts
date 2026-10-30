/**
 * The words of SCR-102 and SCR-041's shared deck: E08-D05 §6.2's copy deck verbatim, §6.1's column header and §6.3's
 * menu items, §3 row 3's status fallbacks (E11-D04) and §9.1's spoken target line. A string the deck lacks is marked
 * PROPOSED here and carried as a G-row on #4703.
 */
import type { RefreshAnswer } from "./instrumentIndex";
import type { Instrument } from "./ranking";
import type { SymbolTarget as Target } from "./searchSession";

export const SEARCH_TITLE = "Symbol search";

/** "13:02", the UTC time of `at` (ms). */
const utc = (at: number): string => new Date(at).toISOString().slice(11, 16);

export const COPY = {
  firstRun: ["Type a symbol or base asset, for example BTC.", "Your recent symbols appear here."],
  loading: "Loading the instrument list…",
  loadingRetry: (s: number): string =>
    `CandleViewer's server is loading the instrument list from Bybit — next try in ${String(s)} s.`,
  failed: "Couldn't load the instrument list.",
  network: "CandleViewer can't reach its server.",
  unavailable: "The server still has no list from Bybit after a minute.",
  answered: (status: number): string => `CandleViewer's server answered ${String(status)}.`,
  nextTry: (s: number): string => `Next try in ${String(s)} s.`,
  retryNow: "Retry now",
  notTrading: (symbol: string): string => `${symbol} is not trading on Bybit.`,
  delisted: "Delisted by the exchange",
  newChart: "Opens a new chart",
  // No matches, the status rule and the check (adopted from PR D's `searchDeck`, SCR-041's builder's).
  noMatch: (query: string): string => `No USDT perpetual matches '${query}'.`,
  scope: "v1 supports Bybit USDT linear perpetuals only.",
  hint: "Search by base asset, for example BTC.",
  checked: (at: number): string => `Checked with the server at ${utc(at)} UTC.`,
  unchecked: (symbol: string): string => `Couldn't check Bybit for ${symbol} just now.`,
  checking: (symbol: string): string => `Checking Bybit for ${symbol}…`,
  checkAgain: "Check again",
  /** PROPOSED state key `search.check_cooldown` (§6.2; its vocabulary owner is E08-D05's deck). */
  cooldown: "Checked a moment ago.",
  clear: "Clear search",
  cantOpen: "It can't be opened as a new chart.",
  gone: (symbol: string): string => `${symbol} is no longer listed on Bybit.`,
  // The footer (stale, refreshing, disconnected) and the armed target's detail-bar line (D-10).
  stale: (hours: number): string =>
    `Instrument list updated ${String(hours)} h ago — the scheduled refresh is overdue.`,
  retry: "Retry",
  refreshing: "Updating the instrument list…",
  // Refresh from Bybit (`POST /instruments/refresh`, the Owner's): its answers, by status and `code` only (§12.2).
  refresh: "Refresh from Bybit",
  /** E09-D09 §3.2's verb for `rbac.owner_only` (A-D05-10, PROPOSED there). */
  refreshVerb: "refresh the instrument list",
  refreshRequested: "Refresh requested — updating the instrument list…",
  rateLimited: (s: number): string => `Too many requests — try again in ${String(s)} s.`,
  exchangeLimited: (s: number): string =>
    `Bybit is limiting requests — try again in ${String(s)} s.`,
  /**
   * PROPOSED (owner: E08-D05 §6.2's deck; a 403 is E09-D09's T4): any other answer or none, the 404 of the route
   * E08-S01 has yet to ship among them, so a press never reads as success.
   */
  refreshRefused: "Couldn't request a refresh just now.",
  disconnected: (at: number): string =>
    `Disconnected — results come from the list loaded at ${utc(at)} UTC.`,
  armed: (pane: string): string => `Switching locks chart trading on ${pane}.`,
  // §6.3's menu, named for its option (§9.1).
  actions: (symbol: string): string => `Actions for ${symbol}`,
  openIn: (pane: string): string => `Open in ${pane}`,
  openNew: "Open in new chart",
  viewInfo: "View symbol info",
  forget: "Remove from recent",
} as const;

/** §6.1's column header; no Recording column while no row has a recording chip (E16-S02). */
export const COLUMNS = {
  label: "Symbol",
  hint: "Base / quote",
  values: ["24 h", "24 h turnover"],
} as const;

const FALLBACK: Readonly<Record<string, string>> = {
  Closed: "Status: Closed.",
  Delivering: "Status: Delivering.",
  PreLaunch: "Not trading yet — status: Pre-launch.",
};

/** `status_reason`, else E11-D04's fallback for the status. */
export const statusText = (instrument: Instrument): string =>
  instrument.status_reason?.trim() || (FALLBACK[instrument.status ?? ""] ?? "");

/** The chip (CMP-160's target) and §9.1's spoken target line, the dialog's description. */
export function targetWords(target: Target | null): {
  readonly chip: string;
  readonly said: string;
} {
  // PROPOSED: the spoken line with no pane (§9.1 gives the pane's only).
  if (target === null) return { chip: COPY.newChart, said: `${COPY.newChart}.` };
  const { pane, symbol } = target;
  return {
    chip: `Changes ${pane} · ${symbol} ${target.interval}`,
    said: `Changes ${pane}, ${symbol} ${target.intervalWords}.`,
  };
}

/** §6.2's commit sentence, said through the shell's polite region as the dialog closes. */
export function commitSentence(
  symbol: string,
  target: Target | null,
  disconnected: boolean,
): string {
  const armed = target?.armed === true ? " Chart trading locked." : "";
  const said =
    target === null
      ? `Opened ${symbol} in a new chart.`
      : `${target.pane} now shows ${symbol}, ${target.intervalWords}.${armed}`;
  return disconnected ? `${said} Live data resumes when the connection returns.` : said;
}

/** §6.2 Refresh answered: the footer's words, and the surface's region's, for `answer`. */
export const refreshAnswered = (answer: RefreshAnswer): string =>
  answer.kind === "requested"
    ? COPY.refreshRequested
    : answer.kind === "rate_limited"
      ? COPY.rateLimited(answer.waitS)
      : answer.kind === "exchange_rate_limited"
        ? COPY.exchangeLimited(answer.waitS)
        : COPY.refreshRefused;

/** The footer's key hints, the input's description (§6.1's anatomy; PROPOSED: the form with no target pane). */
export const keyHints = (
  pane: string | null,
): readonly (readonly [readonly string[], string])[] => [
  [["Enter"], pane === null ? "open in a new chart" : `open in ${pane}`],
  ...(pane === null ? [] : [[["Shift", "Enter"], "new chart"] as const]),
  [["Shift", "F10"], "actions"],
  [["Esc"], "close"],
];
