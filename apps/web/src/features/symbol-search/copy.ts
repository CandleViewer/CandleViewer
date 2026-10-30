/**
 * SCR-102's words: E08-D05 §6.2's copy deck verbatim, §3 row 3's status fallbacks (E11-D04) and §9.1's spoken target
 * line. A string the deck lacks is marked PROPOSED here and carried as a G-row on #4703.
 */
import type { Instrument } from "./ranking";
import type { SymbolTarget as Target } from "./searchSession";

export const SEARCH_TITLE = "Symbol search";

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

/** The footer's key hints, the input's description (§6.1's anatomy; PROPOSED: the form with no target pane). */
export const keyHints = (
  pane: string | null,
): readonly (readonly [readonly string[], string])[] => [
  [["Enter"], pane === null ? "open in a new chart" : `open in ${pane}`],
  ...(pane === null ? [] : [[["Shift", "Enter"], "new chart"] as const]),
  [["Esc"], "close"],
];
