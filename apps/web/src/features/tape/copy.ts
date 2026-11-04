// E22-S01 (#714) PR-B: every string the tape shows, by its `E22-D05-copy.json` key (D05 §8.4,
// RULED BQ-09). Nothing here is worded by the build: a fixed string is the deck's, and a template
// fills the deck's example numbers with live ones. `copy.test.ts` renders each template with the
// deck's example values and compares the result to the deck byte for byte.
import { formatCount } from "./format";

/** `d02.13.cp01` "Tape BTCUSDT". */
export const panelTitle = (symbol: string): string => `Tape ${symbol}`;

/** `d02.13.cp02` [2]: the pause button's name, its key in it. */
export const PAUSE_LABEL = "Pause tape (P)";

/** `d02.13.cp03`: the readout (CP3, BQ-209), its ladder form, and its three words. */
export const readout = (perSec: number, perFrame: number): string =>
  `${formatCount(perSec)} /s (1 s) · ${formatCount(perFrame)} /frame`;
export const readoutShort = (perSec: number): string => `${formatCount(perSec)} /s (1 s)`;
export const READOUT_NONE = "—";
export const LOADING = "Loading…";
export const READOUT_QUIET = "0 /s · quiet";

/** `d02.13.cp04`: the Paused chip, full and narrow, the scroll form and the full-buffer form (S22). */
export const pausedChip = (buffered: number): string =>
  `Paused — ${formatCount(buffered)} prints buffered`;
export const pausedChipNarrow = (buffered: number): string =>
  `Paused — ${formatCount(buffered)} buffered`;
export const pausedChipScroll = (buffered: number): string =>
  `${pausedChip(buffered)} · Jump to live`;
export const pausedChipFull = (kept: number): string =>
  `Paused — buffer full · ${formatCount(kept)} kept`;

/** `d02.13.cp05`: the feed chips. */
export const staleChip = (seconds: number): string => `Stale ${Math.floor(seconds)}s`;
export const OFFLINE_CHIP = "Offline";
export const GAPPED_CHIP = "Reconstructed after gap";

/** `d02.13.cp09`: the divider rows. */
export const dividerPaused = (n: number): string => `— ${formatCount(n)} prints while paused —`;
export const dividerGap = (from: string, to: string): string => `— gap ${from} → ${to} —`;
export const dividerDisconnected = (n: number): string =>
  `— ${formatCount(n)} prints while disconnected —`;
export const dividerNoHistory = (second: string): string =>
  `— No history before ${second}. Recording started then. —`;
export const dividerPausedNotKept = (n: number, notKept: number): string =>
  `— ${formatCount(n)} prints while paused · ${formatCount(notKept)} not kept —`;

/** `d02.13.cp10`: the status-row actions S01 owns. */
export const LOAD_MISSED = "Load missed prints";
export const JUMP_TO_LIVE = "Jump to live";

/** `d02.13.cp11`: the empty line (S12) and the loading word (S11). */
export const NO_PRINTS_YET = "No prints yet";
export const emptyLine = (lastSecond: string): string =>
  `${NO_PRINTS_YET} · last print ${lastSecond}`;
// D02 S12: the time only "when history knows one"; without it the line is its first clause.

/** `d02.13.cp15`: the row tags (D9 order `×N` · `liq` · `blk`). */
export const clusterTag = (n: number): string => `×${n}`;
export const LIQ_TAG = "liq";
export const BLOCK_TAG = "blk";

/** `d02.13.cp16`: the column headers and the Side tooltip. */
export const COLUMNS = ["Time", "Price", "Size", "Notional", "Side"] as const;
export const SIDE_TOOLTIP = "Side (taker): Buy / Sell";

/** `d02.13.cp23`: the panel's `status` sentences S01 writes (AN-03, AN-04, AN-06, S15, S16). */
export const resumed = (n: number): string => `Resumed, ${formatCount(n)} prints inserted`;
export const resumedNotKept = (n: number, notKept: number): string =>
  `Resumed, ${formatCount(n)} prints inserted, ${formatCount(notKept)} not kept`;
export const reconnectedGap = (from: string, to: string): string =>
  `Reconnected — gap ${from} to ${to}`;
export const missedLoaded = (n: number): string => `${formatCount(n)} missed prints loaded`;
export const tapeStale = (seconds: number): string => `Tape stale ${Math.floor(seconds)} seconds.`;
export const TAPE_LIVE = "Tape live.";

/** `d04.07.an01` / `d02.13.cp23` [0] / `d04.07.an02`: the whale sentences (opt-in, off, BQ-211). */
export const whaleOne = (side: "buy" | "sell", notional: string, price: string): string =>
  `Whale ${side}, ${notional} at ${price}`;
export const whaleSameSide = (
  n: number,
  side: "buy" | "sell",
  largest: string,
  price: string,
): string => `${n} whale ${side}s in 5 s, largest ${largest} at ${price}`;
export const whaleMixed = (
  n: number,
  sells: number,
  buys: number,
  largestSide: "buy" | "sell",
  largest: string,
  price: string,
): string =>
  `${n} whale prints in 5 s: ${sells} ${sells === 1 ? "sell" : "sells"}, ${buys} ${buys === 1 ? "buy" : "buys"}, largest ${largestSide} ${largest} at ${price}`;

/** `d02.13.cp24`: the T2 reasons S01 shows (S10, S21). */
export const DISCONNECTED_PAUSE_REASON = "Nothing to pause while disconnected.";
export const viewAsNotice = (user: string): string => `Read-only while viewing as ${user}.`;

/** `d02.04.s10`: the SCR-152 strip over the frozen rows. */
export const disconnectedStrip = (age: string): string => `Disconnected — last data ${age}`;

/** The names D02 §12 gives the panel's regions. */
export const NAMES = {
  toolbar: "Tape controls",
  status: "Tape status",
  log: "Tape, newest first",
  readout: "tape speed",
  lock: "Not available",
} as const;
