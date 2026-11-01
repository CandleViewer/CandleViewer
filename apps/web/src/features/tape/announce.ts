// E22-S01 (#714) PR-B: the panel's one `status` node (D02 §12, D29: visually hidden, polite,
// pre-rendered empty) and what S01 writes into it (E22-D04 §7, RULED A38).
//
// The ambient class is whale prints only, opt-in and off by default (AN-01, AN-02). The opt-in has
// no contract field yet (`accessibility.announce_whale_prints`, G-58 / BQ-211), so it is hard off
// here and no control turns it on; and "whale" is tier 2, E22-S02's 4x rule, so `isWhale` is
// injected and defaults to never (BQ-210). The throttle is A38's: one half-open 5 s window, leading
// and trailing; suppressed (dropped, never held) while a row holds focus or `verbosity` is `low`
// (AN-08). It never goes through `shouldAnnounce` (D04 §7). User-action and feed sentences (AN-03..
// AN-06) share the node and keep their own once-per rates.
import { whaleMixed, whaleOne, whaleSameSide } from "./copy";
import { formatDecimal, formatNotional } from "./format";
import { SIDE_BUY, type TapeRing } from "./model/ring";

/** A38: the whale window. */
export const WHALE_WINDOW_MS = 5_000;

/** Reads the print `seq` of `ring` and says whether it is a whale (tier 2). */
export type WhalePredicate = (ring: TapeRing, seq: number) => boolean;

/** BQ-210: until E22-S02 rules tier 2, nothing is a whale. */
export const NEVER_WHALE: WhalePredicate = () => false;

export type Verbosity = "low" | "normal" | "high";

export interface AnnouncerOptions {
  /** The opt-in (D04 §7). Hard off in the app (BQ-211); a test turns it on. */
  readonly whaleOptIn?: boolean;
  readonly isWhale?: WhalePredicate;
}

interface Pending {
  count: number;
  buys: number;
  sells: number;
  largest: number;
  largestSide: "buy" | "sell";
  largestPrice: string;
}

const emptyPending = (): Pending => ({
  count: 0,
  buys: 0,
  sells: 0,
  largest: -1,
  largestSide: "sell",
  largestPrice: "",
});

export class TapeAnnouncer {
  private node: HTMLElement | null = null;
  private readonly optIn: boolean;
  private readonly isWhale: WhalePredicate;
  private windowEnd: number | null = null;
  private pending = emptyPending();
  private focused = false;
  private verbosity: Verbosity = "normal";
  /** Every text written, in order (the panel's evidence; never read by the UI). */
  writes = 0;

  constructor(options: AnnouncerOptions = {}) {
    this.optIn = options.whaleOptIn ?? false;
    this.isWhale = options.isWhale ?? NEVER_WHALE;
  }

  attach(node: HTMLElement | null): void {
    this.node = node;
  }

  /** User-action and feed sentences: written at once, replacing the node's text. */
  say(text: string): void {
    if (this.node === null) return;
    this.node.textContent = text;
    this.writes += 1;
  }

  /** AN-08: a row holding focus suppresses whales; a window open then drops its pending sum. */
  setRowFocused(focused: boolean): void {
    if (focused && !this.focused) this.pending = emptyPending();
    this.focused = focused;
  }

  setVerbosity(verbosity: Verbosity): void {
    if (verbosity === "low" && this.verbosity !== "low") this.pending = emptyPending();
    this.verbosity = verbosity;
  }

  private get suppressed(): boolean {
    return this.focused || this.verbosity === "low";
  }

  /** The prints `fromSeq..toSeq` of this frame arrived at `nowMs`. */
  observe(ring: TapeRing, fromSeq: number, toSeq: number, nowMs: number): void {
    this.tick(nowMs);
    if (!this.optIn) return; // AN-07: with the opt-in off nothing whale-class is ever written
    for (let seq = fromSeq; seq <= toSeq; seq += 1) {
      if (!ring.has(seq) || !this.isWhale(ring, seq)) continue;
      if (this.suppressed) continue; // dropped, not held (AN-08)
      const i = ring.slot(seq);
      const side = ring.side[i] === SIDE_BUY ? "buy" : "sell";
      const notional = (ring.price[i] ?? 0) * (ring.size[i] ?? 0);
      const price = formatDecimal(ring.priceText(seq));
      if (this.windowEnd === null) {
        // AN-01: the first whale after a quiet of >= 5 s, at once; it opens a window
        this.say(whaleOne(side, formatNotional(notional), price));
        this.windowEnd = nowMs + WHALE_WINDOW_MS;
        continue;
      }
      const p = this.pending;
      p.count += 1;
      if (side === "buy") p.buys += 1;
      else p.sells += 1;
      if (notional > p.largest) {
        p.largest = notional;
        p.largestSide = side;
        p.largestPrice = price;
      }
    }
  }

  /** Closes a window that ended: its sum is said once (trailing), and the close opens the next. */
  tick(nowMs: number): void {
    if (this.windowEnd === null || nowMs < this.windowEnd) return;
    const p = this.pending;
    this.pending = emptyPending();
    if (p.count === 0) {
      this.windowEnd = null; // a window that closes with no whale ends the run
      return;
    }
    const largest = formatNotional(p.largest);
    if (p.count === 1) this.say(whaleOne(p.largestSide, largest, p.largestPrice));
    else if (p.buys === 0 || p.sells === 0) {
      this.say(whaleSameSide(p.count, p.largestSide, largest, p.largestPrice));
    } else this.say(whaleMixed(p.count, p.sells, p.buys, p.largestSide, largest, p.largestPrice));
    this.windowEnd += WHALE_WINDOW_MS;
  }
}
