// E12-S10 forming / amended marks (E12-D06 §7.1 / §7.3): the ring's meta carries the bits to the
// shader; the MarkRing lists one entry per drawn bit, sorted by logical index, in step with the
// ring after any mutation sequence (a seeded property); a confirm patches exactly one ring slot
// and drops the mark in the same sync; an evicted forming slot drops its mark without an event;
// the series draws the marks at L0 only, while a marked bar is in view; `barState` reads the bits.
import { describe, expect, it, vi } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import {
  CANDLE_DIR,
  CANDLE_STRIDE,
  CandleRing,
  CandleSeries,
  candleDir,
  createBarState,
  MARK_BITS,
  MARK_HEAVY,
  MarkRing,
} from "../../src/layers/index.js";
import { BAR_FLAG, BarStore, ModelRejection, type BarBatch } from "../../src/model/index.js";
import type { MutationRange } from "../../src/model/counters.js";
import { bars } from "../model/fixtures.js";
import { ringBar, THEME } from "./fixtures.js";

const { forming: FORMING, amended: AMENDED } = BAR_FLAG;
const CASES = 1_500;

const flagged = (first: number, count: number, flags: number[]): BarBatch => ({
  ...bars(first, count),
  flags: Uint8Array.from(flags),
});

/** The marks a scan of the store finds: `index:kind` per drawn bit, ascending. */
function scan(store: BarStore): string[] {
  const { flags } = store.columns;
  const out: string[] = [];
  for (let i = 0; i < store.length; i += 1) {
    const f = flags[(store.ringHead + i) & (store.capacity - 1)] ?? 0;
    if ((f & FORMING) !== 0) out.push(`${i}:${FORMING}`);
    if ((f & AMENDED) !== 0) out.push(`${i}:${AMENDED}`);
  }
  return out;
}

const listed = (m: MarkRing, store: BarStore): string[] =>
  Array.from(
    { length: m.count },
    (_, e) => `${m.indexOf(e, store.ringHead, store.capacity - 1)}:${m.kindOf(e)}`,
  );

/**
 * Every entry's words equal the store's bar at its slot (a candle ring draws the store's values):
 * [slot, high, low, open, kind | dir | heavy], heavy for a down bar's 2-hairline wick.
 */
function wordsOk(m: MarkRing, store: BarStore): boolean {
  const { open, high, low, close } = store.columns;
  for (let e = 0; e < m.count; e += 1) {
    const w = Array.from(m.ints.subarray(e * CANDLE_STRIDE, (e + 1) * CANDLE_STRIDE));
    const p = w[0] ?? -1;
    const [o, h, l, c] = [open[p] ?? 0, high[p] ?? 0, low[p] ?? 0, close[p] ?? 0];
    const dir = candleDir(o, h, l, c);
    const want = [
      p,
      h,
      l,
      o,
      m.kindOf(e) | (dir << 4) | (dir === CANDLE_DIR.down ? MARK_HEAVY : 0),
    ];
    if (w.join() !== want.join()) return false;
  }
  return true;
}

function setup(initialCapacity = 8, maxBars?: number) {
  const store = new BarStore({ initialCapacity, ...(maxBars !== undefined && { maxBars }) });
  const patches: [string, number, number][] = [];
  const ring = new CandleRing({
    patch: (id: string, r: MutationRange) => void patches.push([id, r.from, r.to]),
  });
  ring.nodes.push("wick", "body");
  const marks = new MarkRing(ring);
  ring.follower = marks;
  marks.nodes.push("marks");
  const of = (id: string): [string, number, number][] => patches.filter((p) => p[0] === id);
  return { store, ring, marks, patches, of };
}

const events = (m: MarkRing): string[] => {
  const n = m.takeEvents();
  return Array.from({ length: n }, (_, e) => `${m.eventTimes[e]}:${m.eventBits[e]}`);
};

describe("the ring's meta carries the state bits to the shader (E12-S10)", () => {
  it("forming is bit 1 and amended bit 3, under the direction in bits 4..5", () => {
    const { store, ring } = setup();
    ring.sync(store, store.replace(flagged(0, 3, [0, AMENDED, FORMING | AMENDED])));
    const meta = (i: number): number => ringBar(ring, i)[4] ?? -1;
    expect([meta(0) & MARK_BITS, meta(1) & MARK_BITS, meta(2) & MARK_BITS]).toEqual([
      0,
      AMENDED,
      FORMING | AMENDED,
    ]);
    expect([meta(0) >> 4, meta(1) >> 4, meta(2) >> 4]).toEqual([0, 0, 0]); // up: the bits move no dir
  });
});

describe("MarkRing", () => {
  it("lists one entry per drawn bit: [slot, high, low, open, kind | dir << 4]", () => {
    const { store, ring, marks, of } = setup();
    ring.sync(store, store.replace(flagged(0, 4, [0, AMENDED, 0, FORMING | AMENDED])));
    expect(listed(marks, store)).toEqual([`1:${AMENDED}`, `3:${FORMING}`, `3:${AMENDED}`]);
    expect(wordsOk(marks, store)).toBe(true);
    expect(of("marks")).toEqual([["marks", 0, 3]]);
    expect([marks.length, marks.capacity, marks.slots]).toEqual([3, 4, 4]);
    ring.sync(store, store.replace(flagged(0, 2, [0, 0])));
    // Empty: the batch spans nothing (no draw-list entry per frame); the buffer stays.
    expect([marks.length, marks.capacity, marks.slots]).toEqual([0, 0, 4]);
  });

  it("a close-only tick leaves the entry as it was: no marks upload, no event", () => {
    const { store, ring, marks, of } = setup();
    ring.sync(store, store.replace(flagged(0, 3, [0, 0, FORMING])));
    events(marks);
    const live = flagged(2, 1, [FORMING]);
    (live.close as Int32Array)[0] = 3; // inside [low 0, high 5], still up from open 2
    const r = store.append(live, true);
    expect([r.from, r.to]).toEqual([2, 3]);
    ring.sync(store, r);
    expect(of("marks")).toHaveLength(1); // only the first build's
    expect(of("body").at(-1)).toEqual(["body", 2, 3]); // the ring: exactly one slot
    expect(events(marks)).toEqual([]);
    (live.high as Int32Array)[0] = 9; // a new high moves the ring: the entry is patched
    ring.sync(store, store.append(live, true));
    expect(of("marks").at(-1)).toEqual(["marks", 0, 1]);
    expect(wordsOk(marks, store)).toBe(true);
  });

  it("a sync that touches a mark makes no typed-array view (no subarray)", () => {
    const { store, ring, marks } = setup();
    ring.sync(store, store.replace(flagged(0, 3, [0, 0, FORMING])));
    events(marks);
    const live = flagged(2, 1, [FORMING]);
    (live.high as Int32Array)[0] = 9;
    const spies = [Int32Array, Float64Array, Uint8Array].map((T) =>
      vi.spyOn(T.prototype, "subarray"),
    );
    try {
      const r = store.append(live, true);
      ring.sync(store, r);
      expect(marks.count).toBe(1);
      expect(spies.map((spy) => spy.mock.calls.length)).toEqual([0, 0, 0]);
    } finally {
      for (const spy of spies) spy.mockRestore();
    }
  });

  it("confirm: a merge-patch clearing the bit patches one ring slot and drops the mark", () => {
    const { store, ring, marks, of } = setup();
    ring.sync(store, store.replace(flagged(0, 3, [0, 0, FORMING])));
    expect(events(marks)).toEqual([`${bars(2, 1).time[0]}:${FORMING}`]);
    const [rewrites, written, before] = [ring.rewrites, ring.written, of("body").length];
    ring.sync(store, store.append(flagged(2, 1, [0]), true));
    expect(of("body").slice(before)).toEqual([["body", 2, 3]]); // exactly one slot
    expect([ring.rewrites, ring.written - written]).toEqual([rewrites, 1]);
    expect(marks.count).toBe(0); // the ring's mark is gone in the same sync
    expect(events(marks)).toEqual([`${bars(2, 1).time[0]}:0`]);
    // The next bar opens forming: a new time, no duplicate of the confirmed one.
    ring.sync(store, store.append(flagged(3, 1, [FORMING]), true));
    expect([store.length, listed(marks, store)]).toEqual([4, [`3:${FORMING}`]]);
    expect(store.indexToTime(2)).not.toBe(store.indexToTime(3));
    expect(events(marks)).toEqual([`${bars(3, 1).time[0]}:${FORMING}`]);
  });

  it("an evicted forming slot drops its mark, and posts no event", () => {
    const { store, ring, marks } = setup(4, 4);
    ring.sync(store, store.replace(flagged(0, 4, [FORMING, 0, 0, 0])));
    events(marks);
    const r = store.append(flagged(4, 1, [0]));
    expect(r.indexShift).toBe(1); // bar 0 evicted; its slot holds the new bar
    ring.sync(store, r);
    expect(marks.count).toBe(0);
    expect(events(marks)).toEqual([]);
  });

  it("a replace that keeps a bar's bits posts nothing; one that drops the bar posts nothing", () => {
    const { store, ring, marks } = setup();
    ring.sync(store, store.replace(flagged(0, 3, [0, AMENDED, FORMING])));
    events(marks);
    ring.sync(store, store.replace(flagged(0, 3, [0, AMENDED, FORMING])));
    expect(events(marks)).toEqual([]);
    ring.sync(store, store.replace(flagged(10, 2, [0, 0])));
    expect([marks.count, events(marks)]).toEqual([0, []]);
  });

  it("a full buffer re-marking one of its bars keeps its array (no reallocation)", () => {
    const { store, ring, marks, of } = setup(16);
    ring.sync(store, store.replace(flagged(0, 4, [AMENDED, AMENDED, AMENDED, FORMING])));
    const data = marks.data;
    expect([marks.count, marks.slots]).toEqual([4, 4]);
    const live = flagged(3, 1, [FORMING]);
    (live.high as Int32Array)[0] = 9; // the forming bar's new high: its entry changes
    ring.sync(store, store.append(live, true));
    expect([marks.count, marks.slots, marks.data === data]).toEqual([4, 4, true]);
    expect(of("marks").at(-1)).toEqual(["marks", 3, 4]); // only that entry is patched
  });

  it("grows past its 4 entries into a new array; the event queue grows the same way", () => {
    const { store, ring, marks } = setup(64);
    const data = marks.data;
    ring.sync(store, store.replace(flagged(0, 12, new Array<number>(12).fill(AMENDED))));
    expect([marks.count, marks.capacity, marks.data !== data]).toEqual([12, 16, true]);
    expect(events(marks)).toHaveLength(12);
  });

  it("anyIn: only a mark inside [first, last] counts", () => {
    const { store, ring, marks } = setup(16);
    ring.sync(store, store.replace(flagged(0, 10, [0, 0, 0, AMENDED, 0, 0, 0, 0, 0, FORMING])));
    const any = (a: number, b: number): boolean => marks.anyIn(a, b, store.ringHead, 15);
    expect([any(0, 2), any(0, 3), any(4, 8), any(9, 20), any(-5, -1)]).toEqual([
      false,
      true,
      false,
      true,
      false,
    ]);
  });

  it("refuses a slot outside the flags column (a corrupt store), naming it", () => {
    const { store, marks } = setup(4);
    const lying = { ...store, length: 4, capacity: 64, ringHead: 40, columns: store.columns };
    const r = { op: "append", from: 0, to: 4, indexShift: 0 } as MutationRange;
    expect(() => marks.sync(lying as unknown as BarStore, r, false)).toThrow(/mark slot/);
  });

  it("without a sink it lists and queues, and patches nothing", () => {
    const store = new BarStore({ initialCapacity: 8 });
    const ring = new CandleRing();
    const marks = new MarkRing(ring);
    ring.follower = marks;
    ring.sync(store, store.replace(flagged(0, 2, [0, FORMING])));
    expect([marks.count, marks.patched, marks.takeEvents()]).toEqual([1, 0, 1]);
  });
});

describe("CandleSeries: the marks batch and the bar state", () => {
  const series = (flags: number[]) => {
    const { store, ring } = setup(16);
    const c = new CandleSeries(ring);
    expect(c.setTheme(THEME)).toBeNull();
    ring.sync(store, store.replace(flagged(0, flags.length, flags)));
    return { c, store };
  };
  const drawn = (c: CandleSeries): number => c.blocks[3]?.instances ?? -1;

  it("draws the marks at L0 only (s >= 3 CSS px), while a marked bar is in view", () => {
    const { c } = series([0, AMENDED, FORMING]);
    expect(c.blocks.map((b) => b.label)).toContain("series.candle.marks");
    c.frame(3, 1, 0, 2);
    expect(drawn(c)).toBe(2);
    c.frame(2.99, 1, 0, 2); // L1: the words alone carry the state
    expect(drawn(c)).toBe(0);
    c.frame(12, 2, 0, 0); // only bar 0 in view: no mark there
    expect(drawn(c)).toBe(0);
    c.frame(12, 2, 1, 1);
    expect(drawn(c)).toBe(2); // the batch covers every entry; the shader places each
  });

  it("draws nothing when no bar is forming or amended", () => {
    const { c } = series([0, 0, 0]);
    c.frame(12, 1, 0, 2);
    expect(drawn(c)).toBe(0);
  });

  it("collect: a context that is not one of its hosts gets every part", () => {
    const { c } = series([0, FORMING, 0]);
    const parts: number[] = [];
    const ctx = { instances: (_: unknown, __: string, part: number) => void parts.push(part) };
    c.collect(ctx as unknown as Parameters<CandleSeries["collect"]>[0]);
    expect(parts).toEqual([0, 1, 4, 7]);
  });

  it("dirtyHosts: the bar parts always; the seam and the marks only after their list changed", () => {
    const { store, ring } = setup(16);
    const c = new CandleSeries(ring);
    ring.sync(store, store.replace(flagged(0, 3, [0, 0, 0])));
    expect(c.dirtyHosts()).toBe(0b1111); // the first call sees every list
    ring.sync(store, store.append(flagged(2, 1, [0]), true));
    expect(c.dirtyHosts()).toBe(0b0011);
    ring.sync(store, store.append(flagged(2, 1, [FORMING]), true));
    expect(c.dirtyHosts()).toBe(0b1011);
    ring.sync(store, store.append(flagged(3, 1, [1]), true)); // a gap_before bar
    expect(c.dirtyHosts()).toBe(0b0111); // the seam only: bar 2 is still forming
  });

  it("barState reads the bits per bar; stale only on the forming bar of a stale series", () => {
    const { c } = series([0, AMENDED, FORMING]);
    const out = createBarState();
    const at = (i: number): string => {
      const ok = c.barState(i, out);
      return `${ok} ${out.forming} ${out.amended} ${out.stale}`;
    };
    expect([at(0), at(1), at(2), at(3), at(-1)]).toEqual([
      "true false false false",
      "true false true false",
      "true true false false",
      "false false false false",
      "false false false false",
    ]);
    c.stale = true;
    expect([at(1), at(2)]).toEqual(["true false true false", "true true false true"]);
  });
});

/** Bars [first, first + count) with seeded flags: forming / amended / gap / partial bits. */
const random = (rng: () => number, first: number, count: number, p: number): BarBatch =>
  flagged(
    first,
    count,
    Array.from(
      { length: count },
      () => (rng() < p ? FORMING : 0) | (rng() < p ? AMENDED : 0) | (rng() < 0.2 ? 1 : 0),
    ),
  );

describe("property: the marks stay in step with the ring after any mutation sequence", () => {
  it(`holds for ${CASES} seeded cases`, { timeout: 60_000 }, () => {
    const failures: string[] = [];
    const seen = { evictions: 0, prepends: 0, patches: 0, replaces: 0, changes: 0 };
    for (let c = 0; c < CASES && failures.length === 0; c += 1) {
      const seed = 20261101 + c;
      const rng = mulberry32(seed);
      const int = (n: number): number => Math.floor(rng() * n);
      const maxBars = 4 + int(28);
      const { store, ring, marks, of } = setup(1 + int(8), maxBars);
      let [lo, hi] = [0, 0];
      ring.sync(store, store.replace(random(rng, 0, 0, 0)));
      for (let s = 0; s < 14 && failures.length === 0; s += 1) {
        const op = int(5);
        const k = int(op === 4 ? maxBars + 1 : 6);
        const p = rng() * 0.4;
        let r;
        try {
          if (op === 0) r = store.append(random(rng, hi, k, p));
          else if (op === 1) {
            const merge = store.length > 0;
            r = store.append(random(rng, merge ? hi - 1 : hi, k, p), true);
            if (merge && k > 0) hi -= 1;
          } else if (op === 2) {
            const n = store.length;
            const at = n === 0 ? 0 : int(n);
            r = store.patch(at, random(rng, lo + at, Math.min(k, n - at), p));
            seen.patches += 1;
          } else if (op === 3) {
            r = store.prepend(random(rng, lo - k, k, p));
            seen.prepends += 1;
          } else {
            r = store.replace(random(rng, (lo = int(100)), k, p));
            seen.replaces += 1;
          }
        } catch (e) {
          if (!(e instanceof ModelRejection)) throw e;
          continue;
        }
        if (op === 0 || op === 1) hi += k;
        if (op === 3) lo -= k;
        if (op === 4) hi = lo + k;
        lo = Math.max(lo, hi - store.length);
        seen.evictions += r.op === "append" ? r.indexShift : 0;
        const changes = marks.changes;
        const patched = of("marks").length;
        ring.sync(store, r);
        marks.takeEvents();
        const [want, got] = [scan(store), listed(marks, store)];
        if (got.join() !== want.join()) {
          failures.push(`seed=${seed} step ${s}: marks ${got.join()} vs scan ${want.join()}`);
        } else if (!wordsOk(marks, store)) {
          failures.push(`seed=${seed} step ${s}: an entry's words differ from its bar`);
        }
        const fresh = of("marks").slice(patched);
        if (marks.changes === changes && fresh.length > 0) {
          failures.push(`seed=${seed} step ${s}: patched an unchanged list`);
        }
        for (const [, from, to] of fresh) {
          if (!(from >= 0 && to <= marks.count && from < to)) {
            failures.push(`seed=${seed} step ${s}: patch [${from}, ${to}) of ${marks.count}`);
          }
        }
        if (marks.changes !== changes) seen.changes += 1;
      }
    }
    expect(failures).toEqual([]);
    expect(Object.values(seen).every((v) => v > 0)).toBe(true); // every path was exercised
  });

  it("an event names exactly the bars whose bits changed and that the store still holds", () => {
    const failures: string[] = [];
    for (let c = 0; c < 400 && failures.length === 0; c += 1) {
      const seed = 20261201 + c;
      const rng = mulberry32(seed);
      const { store, ring, marks } = setup(8, 12);
      let hi = 0;
      let bits = new Map<number, number>();
      for (let s = 0; s < 20 && failures.length === 0; s += 1) {
        const merge = store.length > 0 && rng() < 0.6;
        const k = 1 + Math.floor(rng() * 3);
        const r = store.append(random(rng, merge ? hi - 1 : hi, k, 0.4), true);
        hi += merge ? k - 1 : k;
        ring.sync(store, r);
        const now = new Map<number, number>();
        const { time, flags } = store.columns;
        for (let i = 0; i < store.length; i += 1) {
          const q = (store.ringHead + i) & (store.capacity - 1);
          const f = (flags[q] ?? 0) & MARK_BITS;
          if (f !== 0) now.set(time[q] ?? 0, f);
        }
        const want: string[] = [];
        for (const t of new Set([...bits.keys(), ...now.keys()])) {
          const held = store.indexToTime(store.timeToIndex(t)) === t;
          if ((bits.get(t) ?? 0) !== (now.get(t) ?? 0) && held)
            want.push(`${t}:${now.get(t) ?? 0}`);
        }
        const got = events(marks);
        if (got.sort().join() !== want.sort().join()) {
          failures.push(`seed=${seed} step ${s}: events ${got.join()} vs ${want.join()}`);
        }
        bits = now;
      }
    }
    expect(failures).toEqual([]);
  });
});

describe("the marks follow the drawn bar under E12-S07's hollow and Heikin-Ashi", () => {
  const live = (flags: number[], cols: Partial<BarBatch> = {}) => {
    const { store, ring } = setup(16);
    const c = new CandleSeries(ring);
    ring.sync(store, store.replace({ ...flagged(0, flags.length, flags), ...cols }));
    c.marks.takeEvents(); // the load's own events
    return { c, store, ring, marks: c.marks };
  };
  /** Entry `e`'s words against the ring's at its slot: [high, low, open, dir]. */
  const drawn = (ring: CandleRing, m: MarkRing, e: number): number[][] => {
    const w = m.ints.subarray(e * CANDLE_STRIDE, (e + 1) * CANDLE_STRIDE);
    const v = (w[0] ?? 0) * CANDLE_STRIDE;
    return [
      [w[1] ?? 0, w[2] ?? 0, w[3] ?? 0, ((w[4] ?? 0) >> 4) & 3],
      [
        ring.ints[v + 1] ?? 0,
        ring.ints[v + 2] ?? 0,
        ring.ints[v] ?? 0,
        ((ring.ints[v + 4] ?? 0) >> 4) & 3,
      ],
    ];
  };

  it("Heikin-Ashi: the ring and the square place on the HA candle, not the store's bar", () => {
    const { c, store, ring, marks } = live([0, AMENDED, 0, FORMING]);
    const before = Array.from(marks.ints.subarray(0, 2 * CANDLE_STRIDE));
    c.setKind("candles", true, store);
    expect(marks.count).toBe(2);
    for (let e = 0; e < 2; e += 1) {
      const [mine, ring2] = drawn(ring, marks, e);
      expect(mine).toEqual(ring2);
    }
    expect(Array.from(marks.ints.subarray(0, 2 * CANDLE_STRIDE))).not.toEqual(before);
    expect(marks.takeEvents()).toBe(0); // a view switch changes no bar's state
    c.setKind("candles", false, store);
    expect(Array.from(marks.ints.subarray(0, 2 * CANDLE_STRIDE))).toEqual(before);
  });

  it("Heikin-Ashi: patching an earlier bar moves the forming bar's HA candle and its ring", () => {
    const { c, store, ring, marks } = live([0, 0, 0, FORMING]);
    c.setKind("candles", true, store);
    const was = drawn(ring, marks, 0)[0];
    const fix = { ...flagged(0, 1, [0]), open: Int32Array.of(-40), low: Int32Array.of(-40) };
    ring.sync(store, store.patch(0, fix));
    const [mine, ring2] = drawn(ring, marks, 0);
    expect(mine).toEqual(ring2);
    expect(mine).not.toEqual(was);
  });

  it("hollow: `heavy` is the colour-down wick (close < previous close), not the body's dir", () => {
    // Bar 2 is up (close >= open) but closes below bar 1: hollow, down colour, 2-hairline wick.
    const { c, store, marks } = live([0, 0, FORMING], {
      open: Int32Array.of(10, 10, 5),
      high: Int32Array.of(20, 30, 12),
      low: Int32Array.of(5, 5, 2),
      close: Int32Array.of(15, 25, 8),
    });
    const word = (): number => marks.ints[4] ?? 0;
    expect(word() & MARK_HEAVY).toBe(0); // candles: an up bar's 1-hairline wick
    c.setKind("hollow", false, store);
    expect(word() & MARK_HEAVY).toBe(MARK_HEAVY);
    expect(marks.takeEvents()).toBe(0);
    c.setKind("candles", false, store);
    expect(word() & MARK_HEAVY).toBe(0);
  });
});
