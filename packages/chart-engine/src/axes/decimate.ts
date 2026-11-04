// Label decimation (E11-S06, README BQ-189 to BQ-191; E11-D02 §5): a greedy pass over one axis's
// candidates in a fixed priority order (rank, high first, then value), so the retained set never
// depends on which labels the previous frame kept. A label is dropped when its box comes within
// `gap` (1.5 label heights, edge to edge) of a placed one. Candidates run past the label area
// (the tick models add a margin): one crossing an edge still takes its place, hidden, so a label
// inside never depends on where a neighbour meets the edge and a pan blinks nothing. A rank at or
// above `shiftRank` (a P0 date) whose anchor is inside shifts in instead (one routine for every
// exclusion zone, BQ-190). The pinned last-price box is placed first (BQ-191). Struct-of-arrays
// and an in-place sort: nothing allocated per pass.

/** Candidates per axis: a plot height / label height bound (tens), with a hard cap. */
export const MAX_TICKS = 256;

/** One axis's candidates and, after `decimate`, which are kept (`kept[i]` 1). */
export class TickSet {
  n = 0;
  /** The label's centre along the axis, CSS px; it may move inside the area (a P0 shift). */
  readonly pos = new Float64Array(MAX_TICKS);
  /** The gridline's own position, which never shifts. */
  readonly at = new Float64Array(MAX_TICKS);
  /** The label's extent along the axis, CSS px. */
  readonly size = new Float64Array(MAX_TICKS);
  readonly rank = new Int32Array(MAX_TICKS);
  /** Its identity: a tick, a display value or a UTC ms. */
  readonly value = new Float64Array(MAX_TICKS);
  /** The gridline's tier: 0 minor, 1 major, 2 a dashed boundary (BQ-193). */
  readonly tier = new Uint8Array(MAX_TICKS);
  readonly kept = new Uint8Array(MAX_TICKS);
  readonly text: string[] = [];
  private readonly order = new Int32Array(MAX_TICKS);
  private readonly lo = new Float64Array(MAX_TICKS + 1);
  private readonly hi = new Float64Array(MAX_TICKS + 1);

  clear(): void {
    this.n = 0;
  }

  /** Adds a candidate; false (and nothing added) once the set is full. */
  push(
    pos: number,
    size: number,
    rank: number,
    value: number,
    tier: number,
    text: string,
  ): boolean {
    const i = this.n;
    if (i >= MAX_TICKS) return false;
    this.pos[i] = this.at[i] = pos;
    this.size[i] = size;
    this.rank[i] = rank;
    this.value[i] = value;
    this.tier[i] = tier;
    this.kept[i] = 0;
    this.text[i] = text;
    this.n = i + 1;
    return true;
  }

  /** Kept labels in value order, written into `out` (reused); returns `out`. */
  keptText(out: string[]): string[] {
    out.length = 0;
    for (let i = 0; i < this.n; i += 1) if (this.kept[i] === 1) out.push(this.text[i] ?? "");
    return out;
  }

  /**
   * Keeps candidates greedily inside [areaLo, areaHi]; returns how many anchored inside were
   * dropped. `pin` is
   * the last-price label's centre (NaN when none) with extent `pinSize`.
   */
  decimate(
    gap: number,
    areaLo: number,
    areaHi: number,
    shiftRank: number,
    pin = Number.NaN,
    pinSize = 0,
  ): number {
    const { order, lo, hi, pos, size, rank, value } = this;
    const n = this.n;
    for (let i = 0; i < n; i += 1) {
      let j = i; // insertion sort by (rank desc, value asc): n is tens
      for (; j > 0; j -= 1) {
        const o = order[j - 1] as number;
        const r = (rank[o] as number) - (rank[i] as number);
        if (r > 0 || (r === 0 && (value[o] as number) <= (value[i] as number))) break;
        order[j] = o;
      }
      order[j] = i;
    }
    let placed = 0;
    if (Number.isFinite(pin)) {
      lo[0] = pin - pinSize / 2;
      hi[0] = pin + pinSize / 2;
      placed = 1;
    }
    for (let k = 0; k < n; k += 1) {
      const i = order[k] as number;
      const half = (size[i] as number) / 2;
      let c = pos[i] as number;
      let shown = c - half >= areaLo && c + half <= areaHi;
      const shift = (rank[i] as number) >= shiftRank && c >= areaLo && c <= areaHi;
      if (!shown && shift && 2 * half <= areaHi - areaLo) {
        c = Math.min(areaHi - half, Math.max(areaLo + half, c)); // a P0 date shifts in
        shown = true;
      }
      let free = true;
      for (let p = 0; free && p < placed; p += 1) {
        free = c + half + gap <= (lo[p] as number) || c - half - gap >= (hi[p] as number);
      }
      if (!free) continue;
      lo[placed] = c - half;
      hi[placed] = c + half;
      placed += 1;
      if (!shown) continue; // placed, hidden: it blocks its neighbours as it would in view
      pos[i] = c;
      this.kept[i] = 1;
    }
    let dropped = 0; // in view and not kept: `engine.axis.labels_decimated`
    for (let i = 0; i < n; i += 1) {
      const at = this.at[i] as number;
      if (this.kept[i] === 0 && at >= areaLo && at <= areaHi) dropped += 1;
    }
    return dropped;
  }
}
