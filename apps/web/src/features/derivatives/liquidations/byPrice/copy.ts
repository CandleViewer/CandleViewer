// E24-S07 (#782) slice 2: the recorded liquidations by price strings. Sources: the E24-D05 deck
// (`docs/design/E24/E24-D05-copy-deck.jsonl`), D02 §6 / §15, D03 S54-56 / S54-57 and E24-K01 §6a's permitted copy;
// a string none of them carries is marked PROPOSED and goes to the E24-D05 deck owner. K01 §6a forbids
// "estimated liquidation levels", "liquidation zones" without "recorded" and any predictive claim: the
// vocabulary test reads every string here.

/** `derivatives.zones.recorded.alone` (D03 S54-57, merged): the switch when (b) ships alone. */
export const TOGGLE_LABEL = "Recorded liquidations by price · Not available to rules";
export const LAYER_NAME = "Recorded liquidations by price";
export const NOT_FOR_RULES = "Not available to rules";
/**
 * The window phrase. The merged `derivatives.zones.recorded.legend` reads "(this session)"; Bybit perpetuals have no
 * session, so BQ 5 (ruled 6624627875) sends "(today, UTC)" to #5616 as a PROPOSED change row.
 */
export const WINDOW_TODAY = "(today, UTC)";
/** K01 §6a's accessible description, verbatim (D03 S54-56: the legend row's tooltip and the layer's description). */
export const K01_SENTENCE = "Histogram of recorded liquidations by price level. Not a prediction.";

/** D03 §7: the estimated word CMP-227 carries; drawn only when the answer's flag is true (BQ 7). */
export const ESTIMATED_WORD = "(estimated)";

/** `derivatives.name.partial_chip` / `derivatives.liq.partial_chip` (merged, #780's partial chip). */
export const sinceChip = (when: string): string => `since ${when}`;
export const partialSentence = (when: string): string =>
  `No history before ${when}. Bybit publishes no liquidation history; earlier prints were not recorded.`;
/** D02 §6 `liq-before-coverage` and `liq-never-recorded` (merged, shared with #780 / #781). */
export const notRecordedBefore = (when: string): string =>
  `Not recorded before ${when} — this is not 'no liquidations'`;
export const neverRecorded = (symbol: string): string =>
  `No liquidation history for ${symbol}. Bybit publishes none, and this symbol has never been recorded.`;
/** PROPOSED: the covered part holds no print (`no_coverage` false, `items` empty). */
export const noneRecordedSince = (when: string): string =>
  `No liquidation was recorded since ${when}.`;

/** The table (D02 §11's `From (USDT) · To (USDT)` columns; the rest PROPOSED, after #781's units). */
export const tableCaption = (symbol: string, count: number): string =>
  `Recorded liquidations by price, ${symbol}, top ${String(count)} buckets, largest first`;
export const COL_FROM = "From (USDT)";
export const COL_TO = "To (USDT)";
export const COL_LONG = "Long liquidated (USDT)";
export const COL_SHORT = "Short liquidated (USDT)";
export const COL_PRINTS = "Prints";

/** PROPOSED (after #781's states): loading, failure and refusal. */
export const LOADING = "Loading recorded liquidations by price…";
export const RETRY_TITLE = "Couldn't load recorded liquidations by price";
export const RETRY = "Retry";
/** PROPOSED: an answer without its `estimated` flag, or of another shape, is refused and draws nothing (BQ 7). */
export const REFUSED = "The server's answer could not be read, so nothing is drawn.";
export const stale = (when: string): string => `Stale · last ${when}`;

const pad = (n: number): string => String(n).padStart(2, "0");
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "09:14 UTC" on `nowMs`'s UTC day, "21 Oct 09:14 UTC" on another (D02 §15, #780's `coverageTime`). */
export function coverageTime(ms: number, nowMs: number): string {
  const d = new Date(ms);
  const hm = `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`;
  if (new Date(nowMs).toISOString().slice(0, 10) === d.toISOString().slice(0, 10)) return hm;
  return `${String(d.getUTCDate())} ${MONTHS[d.getUTCMonth()] ?? ""} ${hm}`;
}

/** "62880.00" → "62,880.00": the served decimal, grouped, never rounded (D03 §2). */
export function grouped(value: string): string {
  const [int = "", frac] = value.split(".");
  const g = int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return frac === undefined ? g : `${g}.${frac}`;
}
