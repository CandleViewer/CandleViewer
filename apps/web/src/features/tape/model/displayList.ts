// E22-S01 (#714) PR-B: the tape's display order, newest first, over the ring (C-70). It is a short
// list of segments rebuilt when the top moves, never a per-print array: a run of ring rows, the
// divider rows anchored under a print (resume, gap, the not-kept count: D02 S5, S15, S22), the
// missed prints a REST load put under a gap divider (S16), and the history tail below the oldest
// held print with its partial-history divider (S14, BQ-214). The grid writer reads one index at a
// time through a reused cursor, so nothing here allocates per frame.
import type { ExtraPrint } from "./history";
import type { TapeRing } from "./ring";

export interface Divider {
  /** A stable negative key: dividers and extra rows never share a key with a ring `seq`. */
  readonly key: number;
  text: string;
}

export interface ExtraRow {
  readonly key: number;
  readonly print: ExtraPrint;
}

interface Anchor {
  readonly seq: number;
  readonly dividers: Divider[];
  block: readonly ExtraRow[];
}

export type ItemKind = "row" | "extra" | "divider";

/** Filled by `at`: one display item. */
export interface Cursor {
  kind: ItemKind;
  /** The ring `seq` (rows), else -1. */
  seq: number;
  extra: ExtraPrint | null;
  divider: Divider | null;
  /** The writer's key: `seq` for a row, the negative key otherwise. */
  key: number;
  /** 1-based among the rows and extras, dividers excluded (`aria-rowindex` less the header). */
  rowIndex: number;
}

export const newCursor = (): Cursor => ({
  kind: "row",
  seq: -1,
  extra: null,
  divider: null,
  key: 0,
  rowIndex: 0,
});

const ROWS = 0;
const DIVIDER = 1;
const BLOCK = 2;

export class DisplayList {
  private readonly anchors = new Map<number, Anchor>();
  /** The anchors' `seq`s, newest first, kept in order as anchors come and go (no per-build sort). */
  private readonly anchorSeqs: number[] = [];
  private nextKey = -1;
  private tail: readonly ExtraRow[] = [];
  private tailDivider: Divider | null = null;
  // segments, rebuilt by `build`: kind, first display index, rows before it, and two operands
  private readonly segKind: number[] = [];
  private readonly segStart: number[] = [];
  private readonly segRowsBefore: number[] = [];
  private readonly segA: number[] = [];
  private readonly segRef: (Divider | readonly ExtraRow[] | null)[] = [];
  private total = 0;
  private rows = 0;
  private builtTop = -1;
  private builtOldest = -1;

  constructor(private readonly ring: TapeRing) {}

  /** Display items (rows, extras and dividers). */
  get length(): number {
    return this.total;
  }

  /** Rows and extras (`aria-rowcount` less the header). */
  get rowCount(): number {
    return this.rows;
  }

  /** The newest ring `seq` the last `build` showed. */
  get top(): number {
    return this.builtTop;
  }

  private key(): number {
    const k = this.nextKey;
    this.nextKey -= 1;
    return k;
  }

  private anchor(seq: number): Anchor {
    let a = this.anchors.get(seq);
    if (a === undefined) {
      a = { seq, dividers: [], block: [] };
      this.anchors.set(seq, a);
      let at = this.anchorSeqs.length;
      while (at > 0 && (this.anchorSeqs[at - 1] ?? 0) < seq) at -= 1;
      this.anchorSeqs.splice(at, 0, seq);
    }
    return a;
  }

  /** A divider row under the print `seq`. */
  addDivider(seq: number, text: string): Divider {
    const d: Divider = { key: this.key(), text };
    this.anchor(seq).dividers.push(d);
    this.builtTop = -1;
    return d;
  }

  /** Puts `prints` (newest first) under `seq`'s dividers; returns how many were placed. */
  setBlock(seq: number, prints: readonly ExtraPrint[]): number {
    this.anchor(seq).block = prints.map((print) => ({ key: this.key(), print }));
    this.builtTop = -1;
    return prints.length;
  }

  /** The history below the oldest held print (S14), newest first, and its divider once exhausted. */
  appendTail(prints: readonly ExtraPrint[]): void {
    this.tail = [...this.tail, ...prints.map((print) => ({ key: this.key(), print }))];
    this.builtTop = -1;
  }

  setTailDivider(text: string | null): void {
    this.tailDivider = text === null ? null : { key: this.key(), text };
    this.builtTop = -1;
  }

  get tailPrints(): readonly ExtraRow[] {
    return this.tail;
  }

  get hasTailDivider(): boolean {
    return this.tailDivider !== null;
  }

  /** Drops the tail when the ring evicted below it: the history would no longer touch the ring. */
  clearTail(): void {
    if (this.tail.length === 0 && this.tailDivider === null) return;
    this.tail = [];
    this.tailDivider = null;
    this.builtTop = -1;
  }

  /** Whether the print `seq` already has an extra row with this id (dedupe across loads). */
  hasExtraId(id: string): boolean {
    for (const a of this.anchors.values())
      for (const r of a.block) if (r.print.id === id) return true;
    for (const r of this.tail) if (r.print.id === id) return true;
    return false;
  }

  /** Rebuilds the segments for a list whose newest shown print is `top`. */
  build(top: number): void {
    const oldest = this.ring.oldestSeq;
    if (top === this.builtTop && oldest === this.builtOldest) return;
    this.builtTop = top;
    this.builtOldest = oldest;
    // the oldest anchors sit at the end of the newest-first list
    while ((this.anchorSeqs.at(-1) ?? oldest) < oldest) {
      this.anchors.delete(this.anchorSeqs.pop() ?? oldest);
    }
    this.segKind.length = 0;
    this.segStart.length = 0;
    this.segRowsBefore.length = 0;
    this.segA.length = 0;
    this.segRef.length = 0;
    this.total = 0;
    this.rows = 0;
    let hi = top;
    if (top >= oldest) {
      for (let k = 0; k < this.anchorSeqs.length; k += 1) {
        const seq = this.anchorSeqs[k] ?? 0;
        if (seq > top) continue;
        this.pushSeg(ROWS, hi, null, hi - seq + 1); // hi down to seq
        const a = this.anchors.get(seq) as Anchor;
        for (let d = 0; d < a.dividers.length; d += 1) {
          this.pushSeg(DIVIDER, 0, a.dividers[d] as Divider, 1);
        }
        if (a.block.length > 0) this.pushSeg(BLOCK, 0, a.block, a.block.length);
        hi = seq - 1;
      }
      if (hi >= oldest) this.pushSeg(ROWS, hi, null, hi - oldest + 1);
    }
    if (this.tail.length > 0) this.pushSeg(BLOCK, 0, this.tail, this.tail.length);
    if (this.tailDivider !== null) this.pushSeg(DIVIDER, 0, this.tailDivider, 1);
  }

  /** Appends one segment while `build` runs: `total` and `rows` accumulate as it goes. */
  private pushSeg(
    kind: number,
    a: number,
    ref: Divider | readonly ExtraRow[] | null,
    n: number,
  ): void {
    this.segKind.push(kind);
    this.segStart.push(this.total);
    this.segRowsBefore.push(this.rows);
    this.segA.push(a);
    this.segRef.push(ref);
    this.total += n;
    if (kind !== DIVIDER) this.rows += n;
  }

  /** Forces the next `build` to run (a divider's text changed). */
  invalidate(): void {
    this.builtTop = -1;
  }

  private segmentOf(index: number): number {
    let lo = 0;
    let hi = this.segStart.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if ((this.segStart[mid] ?? 0) <= index) lo = mid;
      else hi = mid - 1;
    }
    return lo;
  }

  /** Fills `out` with the item at display `index` (0 = the newest). */
  at(index: number, out: Cursor): void {
    const s = this.segmentOf(index);
    const offset = index - (this.segStart[s] ?? 0);
    const kind = this.segKind[s];
    const rowsBefore = this.segRowsBefore[s] ?? 0;
    if (kind === ROWS) {
      const seq = (this.segA[s] ?? 0) - offset;
      out.kind = "row";
      out.seq = seq;
      out.extra = null;
      out.divider = null;
      out.key = seq;
      out.rowIndex = rowsBefore + offset + 1;
    } else if (kind === BLOCK) {
      const row = (this.segRef[s] as readonly ExtraRow[])[offset] as ExtraRow;
      out.kind = "extra";
      out.seq = -1;
      out.extra = row.print;
      out.divider = null;
      out.key = row.key;
      out.rowIndex = rowsBefore + offset + 1;
    } else {
      const d = this.segRef[s] as Divider;
      out.kind = "divider";
      out.seq = -1;
      out.extra = null;
      out.divider = d;
      out.key = d.key;
      out.rowIndex = 0;
    }
  }

  /** The display index of the ring print `seq`, or -1 when it is not shown. */
  indexOfSeq(seq: number): number {
    for (let s = 0; s < this.segKind.length; s += 1) {
      if (this.segKind[s] !== ROWS) continue;
      const hi = this.segA[s] ?? 0;
      const start = this.segStart[s] ?? 0;
      const next = this.segStart[s + 1] ?? this.total;
      const lo = hi - (next - start) + 1;
      if (seq <= hi && seq >= lo) return start + (hi - seq);
    }
    return -1;
  }

  /** The display index of the item with `key` (any kind), or -1. */
  indexOfKey(key: number, cursor: Cursor = newCursor()): number {
    if (key >= 0) return this.indexOfSeq(key);
    for (let i = 0; i < this.total; i += 1) {
      this.at(i, cursor);
      if (cursor.key === key) return i;
    }
    return -1;
  }
}
