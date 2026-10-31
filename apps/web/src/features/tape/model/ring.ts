// E22-S01 (#714) PR-A: the tape's print buffer. A struct-of-arrays ring (scout §4.3): one typed
// array per field, a monotonic `seq` per print as the stable row key, eviction by an index move.
// Nothing here allocates per print beyond the decimal strings the feed already holds and one id
// map entry (the dedupe of C-68). The writer of PR-B reads it by `seq` from rAF.

/** SCR-053 (`14`:1258): the ring holds 10 000 prints by default. */
export const TAPE_RING_CAPACITY = 10_000;
/** LIM:28: the ceiling a buffer-size control may raise it to (E22-S05). */
export const TAPE_RING_MAX_CAPACITY = 50_000;

export const SIDE_BUY = 0;
export const SIDE_SELL = 1;
export type TapeSide = typeof SIDE_BUY | typeof SIDE_SELL;

/** Bits of `flags`. */
export const FLAG_BLOCK = 1;
export const FLAG_LIQUIDATION = 2;
/** The server's `is_big_trade` (`23` §14.2): read, never recomputed (BQ-210, tier 1). */
export const FLAG_BIG = 4;
/** A seam sits above this print: older rows are last-good history from before a reset (C-78). */
export const FLAG_SEAM = 8;

export interface PrintInput {
  readonly id: string | undefined;
  readonly tsMs: number;
  readonly price: string;
  readonly size: string;
  readonly side: TapeSide;
  readonly flags: number;
  readonly clusterSize: number;
}

export class TapeRing {
  readonly capacity: number;
  readonly tsMs: Float64Array;
  /** Parsed once for display maths (notional); the decimal string stays the text of record. */
  readonly price: Float64Array;
  readonly size: Float64Array;
  readonly side: Uint8Array;
  readonly flags: Uint8Array;
  readonly clusterSize: Uint16Array;
  private readonly ids: (string | undefined)[];
  private readonly priceTexts: string[];
  private readonly sizeTexts: string[];
  private readonly byId = new Map<string, number>();
  private readonly pins = new Map<number, number>();
  private pinFloor = Infinity;
  private next = 0;
  private first = 0;
  /** Prints refused because the ring was full and its oldest row was pinned (S22). */
  notKept = 0;

  constructor(capacity: number = TAPE_RING_CAPACITY) {
    if (!Number.isInteger(capacity) || capacity < 1 || capacity > TAPE_RING_MAX_CAPACITY) {
      throw new RangeError(`tape ring capacity must be 1 to ${TAPE_RING_MAX_CAPACITY}`);
    }
    this.capacity = capacity;
    this.tsMs = new Float64Array(capacity);
    this.price = new Float64Array(capacity);
    this.size = new Float64Array(capacity);
    this.side = new Uint8Array(capacity);
    this.flags = new Uint8Array(capacity);
    this.clusterSize = new Uint16Array(capacity);
    this.ids = new Array<string | undefined>(capacity).fill(undefined);
    this.priceTexts = new Array<string>(capacity).fill("");
    this.sizeTexts = new Array<string>(capacity).fill("");
  }

  /** Prints held. */
  get length(): number {
    return this.next - this.first;
  }

  /** The oldest held `seq`; equal to `nextSeq` when empty. */
  get oldestSeq(): number {
    return this.first;
  }

  /** The `seq` the next print will take; the newest held is `nextSeq - 1`. */
  get nextSeq(): number {
    return this.next;
  }

  has(seq: number): boolean {
    return seq >= this.first && seq < this.next;
  }

  /** The array index of a held `seq`; read the typed arrays with it. */
  slot(seq: number): number {
    return seq % this.capacity;
  }

  hasId(id: string): boolean {
    return this.byId.has(id);
  }

  id(seq: number): string | undefined {
    return this.has(seq) ? this.ids[this.slot(seq)] : undefined;
  }

  priceText(seq: number): string {
    return this.has(seq) ? (this.priceTexts[this.slot(seq)] ?? "") : "";
  }

  sizeText(seq: number): string {
    return this.has(seq) ? (this.sizeTexts[this.slot(seq)] ?? "") : "";
  }

  /** Appends a print and returns its `seq`, or `null` when it was not kept (full, oldest pinned). */
  push(print: PrintInput): number | null {
    if (this.next - this.first === this.capacity) {
      if (this.pinFloor <= this.first) {
        this.notKept += 1;
        return null;
      }
      this.evictOldest();
    }
    const seq = this.next;
    const i = seq % this.capacity;
    this.tsMs[i] = print.tsMs;
    this.price[i] = Number(print.price);
    this.size[i] = Number(print.size);
    this.side[i] = print.side;
    this.flags[i] = print.flags;
    this.clusterSize[i] = Math.min(0xffff, Math.max(1, print.clusterSize));
    this.ids[i] = print.id;
    this.priceTexts[i] = print.price;
    this.sizeTexts[i] = print.size;
    if (print.id !== undefined) this.byId.set(print.id, seq);
    this.next = seq + 1;
    return seq;
  }

  markSeam(seq: number): void {
    if (!this.has(seq)) return;
    const i = this.slot(seq);
    this.flags[i] = (this.flags[i] ?? 0) | FLAG_SEAM;
  }

  /**
   * Holds `seq` and every newer print against eviction (the focused print, a paused window:
   * FP-09, D02-G7). Pins nest: each `pin` needs its own `unpin`.
   */
  pin(seq: number): void {
    if (!this.has(seq)) return; // an evicted or unheld seq must never drag the floor below `first`
    this.pins.set(seq, (this.pins.get(seq) ?? 0) + 1);
    if (seq < this.pinFloor) this.pinFloor = seq;
  }

  unpin(seq: number): void {
    const held = this.pins.get(seq);
    if (held === undefined) return;
    if (held > 1) {
      this.pins.set(seq, held - 1);
      return;
    }
    this.pins.delete(seq);
    if (seq === this.pinFloor) {
      let floor = Infinity;
      for (const pinned of this.pins.keys()) if (pinned < floor) floor = pinned;
      this.pinFloor = floor;
    }
  }

  private evictOldest(): void {
    const i = this.first % this.capacity;
    const id = this.ids[i];
    if (id !== undefined && this.byId.get(id) === this.first) this.byId.delete(id);
    this.ids[i] = undefined;
    this.first += 1;
  }
}
