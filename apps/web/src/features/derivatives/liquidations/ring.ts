// E24-S05 (#780) slice 1: the feed's bounded print buffer. A fixed-size ring (the ticket's "fixed-size ring
// buffer of recent prints"): the oldest print is evicted by an index move, never by a copy, so memory stays
// bounded at any print rate (the threat model's D: client-side cascade amplification). Every print takes a
// monotonic `seq`, the stable row key.
import type { LiquidationPrint } from "./prints";

/**
 * BQ 7 (ruled 6612481277, #780): the retained print count; `14` names only the 40 rows in view. The bound is
 * 1,000 small frozen objects (four short decimal strings each), whatever the print rate.
 */
export const LIQ_RING_CAPACITY = 1_000;

export interface HeldPrint extends LiquidationPrint {
  readonly seq: number;
}

export class LiquidationRing {
  readonly capacity: number;
  private readonly slots: (HeldPrint | undefined)[];
  private next = 0;
  private first = 0;

  constructor(capacity: number = LIQ_RING_CAPACITY) {
    if (!Number.isInteger(capacity) || capacity < 1) {
      throw new RangeError("liquidation ring capacity must be a positive integer");
    }
    this.capacity = capacity;
    this.slots = new Array<HeldPrint | undefined>(capacity).fill(undefined);
  }

  get length(): number {
    return this.next - this.first;
  }

  /** The `seq` the next print takes; the newest held is `nextSeq - 1`. */
  get nextSeq(): number {
    return this.next;
  }

  /** The newest held print's time, or `null` when empty. */
  get newestTsMs(): number | null {
    return this.length === 0 ? null : (this.slots[(this.next - 1) % this.capacity]?.tsMs ?? null);
  }

  push(print: LiquidationPrint): HeldPrint {
    if (this.length === this.capacity) {
      this.slots[this.first % this.capacity] = undefined;
      this.first += 1;
    }
    const held: HeldPrint = { ...print, seq: this.next };
    this.slots[this.next % this.capacity] = held;
    this.next += 1;
    return held;
  }

  /** Up to `count` prints, newest first. */
  newest(count: number): HeldPrint[] {
    const out: HeldPrint[] = [];
    for (let seq = this.next - 1; seq >= this.first && out.length < count; seq -= 1) {
      const held = this.slots[seq % this.capacity];
      if (held !== undefined) out.push(held);
    }
    return out;
  }

  /** Every held print, oldest first. */
  all(): HeldPrint[] {
    return this.newest(this.length).reverse();
  }

  clear(): void {
    this.slots.fill(undefined);
    this.first = this.next;
  }
}
