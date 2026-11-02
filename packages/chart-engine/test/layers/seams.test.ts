// E12-S06 gap seams (BQ-8, E12-D06 §8): the SeamRing lists every `gap_before` bar, sorted by
// logical index, after any mutation sequence; it patches its node only when the list changed; and
// `anyIn` agrees with a scan. Seeded mulberry32 loops (README BQ-30); a failure prints its seed.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { CANDLE_STRIDE, CandleRing, FLAG_GAP_BEFORE, SeamRing } from "../../src/layers/index.js";
import { BarStore, ModelRejection, type BarBatch } from "../../src/model/index.js";
import type { MutationRange } from "../../src/model/counters.js";
import { bars } from "../model/fixtures.js";

const CASES = 1_500;

const gappy = (rng: () => number, first: number, count: number, p = 0.3): BarBatch => ({
  ...bars(first, count),
  flags: Uint8Array.from({ length: count }, () =>
    rng() < p ? FLAG_GAP_BEFORE | (rng() < 0.5 ? 2 : 0) : rng() < 0.2 ? 4 : 0,
  ),
});

/** The seams a scan of the store finds: logical indices of `gap_before` bars, ascending. */
function scan(store: BarStore): number[] {
  const { flags } = store.columns;
  const out: number[] = [];
  for (let i = 0; i < store.length; i += 1) {
    const p = (store.ringHead + i) & (store.capacity - 1);
    if (((flags[p] ?? 0) & FLAG_GAP_BEFORE) !== 0) out.push(i);
  }
  return out;
}

const listed = (s: SeamRing, store: BarStore): number[] =>
  Array.from({ length: s.count }, (_, e) => s.indexOf(e, store.ringHead, store.capacity - 1));

function setup() {
  const patches: [string, number, number][] = [];
  const ring = new CandleRing({
    patch: (id: string, r: MutationRange) => void patches.push([id, r.from, r.to]),
  });
  const seams = new SeamRing(ring);
  ring.seams = seams;
  seams.nodes.push("seam");
  return { ring, seams, patches };
}

describe("SeamRing", () => {
  it("lists the gap_before bars and patches [0, max(old, new)) on a change only", () => {
    const store = new BarStore({ initialCapacity: 8 });
    const { ring, seams, patches } = setup();
    const b = bars(0, 5);
    ring.sync(store, store.replace({ ...b, flags: Uint8Array.of(0, 1, 0, 3, 0) }));
    expect(listed(seams, store)).toEqual([1, 3]);
    expect(seams.ints[CANDLE_STRIDE]).toBe((store.ringHead + 3) & 7); // a physical slot
    expect(patches.filter((p) => p[0] === "seam")).toEqual([["seam", 0, 2]]);
    ring.sync(store, store.append({ ...bars(5, 1), flags: Uint8Array.of(0) }));
    expect(patches.filter((p) => p[0] === "seam")).toHaveLength(1); // unchanged: no patch
    ring.sync(store, store.patch(1, { ...bars(1, 1), flags: Uint8Array.of(0) }));
    expect(listed(seams, store)).toEqual([3]);
    expect(patches.filter((p) => p[0] === "seam").at(-1)).toEqual(["seam", 0, 2]);
  });

  it("grows past 16 entries into a new array (a full upload next)", () => {
    const store = new BarStore({ initialCapacity: 64 });
    const { ring, seams } = setup();
    const data = seams.data;
    ring.sync(store, store.replace({ ...bars(0, 40), flags: new Uint8Array(40).fill(1) }));
    expect([seams.count, seams.capacity, seams.data !== data]).toEqual([40, 64, true]);
    expect(seams.length).toBe(40);
  });

  it("anyIn: only a seam inside [first, last] counts", () => {
    const store = new BarStore({ initialCapacity: 16 });
    const { ring, seams } = setup();
    ring.sync(
      store,
      store.replace({ ...bars(0, 10), flags: Uint8Array.of(0, 0, 0, 1, 0, 0, 0, 0, 1, 0) }),
    );
    const any = (a: number, b: number): boolean => seams.anyIn(a, b, store.ringHead, 15);
    expect([any(0, 2), any(0, 3), any(4, 7), any(4, 8), any(9, 20), any(-5, -1)]).toEqual([
      false,
      true,
      false,
      true,
      false,
      false,
    ]);
  });

  it("refuses a slot outside the flags column (a corrupt store), naming it", () => {
    const store = new BarStore({ initialCapacity: 4 });
    const { seams } = setup();
    const lying = { ...store, length: 4, capacity: 64, ringHead: 40, columns: store.columns };
    const r = { op: "append", from: 0, to: 4, indexShift: 0 } as MutationRange;
    expect(() => seams.sync(lying as unknown as BarStore, r, false)).toThrow(/seam slot/);
  });
});

describe("property: the seams equal a scan of the store after any mutation sequence", () => {
  it(`holds for ${CASES} seeded cases`, { timeout: 60_000 }, () => {
    const failures: string[] = [];
    const seen = { evictions: 0, prepends: 0, patches: 0, changes: 0, unchanged: 0 };
    for (let c = 0; c < CASES && failures.length === 0; c += 1) {
      const seed = 20261102 + c;
      const rng = mulberry32(seed);
      const int = (n: number): number => Math.floor(rng() * n);
      const maxBars = 4 + int(28);
      const store = new BarStore({ maxBars, initialCapacity: 1 + int(8) });
      const { ring, seams, patches } = setup();
      let [lo, hi] = [0, 0];
      ring.sync(store, store.replace(gappy(rng, 0, 0)));
      for (let s = 0; s < 14 && failures.length === 0; s += 1) {
        const op = int(5);
        const k = int(op === 4 ? maxBars + 1 : 6);
        const p = rng() * 0.5;
        let r;
        try {
          if (op === 0) r = store.append(gappy(rng, hi, k, p));
          else if (op === 1) {
            const merge = store.length > 0;
            r = store.append(gappy(rng, merge ? hi - 1 : hi, k, p), true);
            if (merge && k > 0) hi -= 1;
          } else if (op === 2) {
            const n = store.length;
            const at = n === 0 ? 0 : int(n);
            r = store.patch(at, gappy(rng, lo + at, Math.min(k, n - at), p));
            seen.patches += 1;
          } else if (op === 3) {
            r = store.prepend(gappy(rng, lo - k, k, p));
            seen.prepends += 1;
          } else r = store.replace(gappy(rng, (lo = int(100)), k, p));
        } catch (e) {
          if (!(e instanceof ModelRejection)) throw e;
          continue;
        }
        if (op === 0 || op === 1) hi += k;
        if (op === 3) lo -= k;
        if (op === 4) hi = lo + k;
        lo = Math.max(lo, hi - store.length);
        seen.evictions += r.op === "append" ? r.indexShift : 0;
        const before = listed(seams, store).join();
        const changes = seams.changes;
        const patched = patches.length;
        ring.sync(store, r);
        const want = scan(store);
        const got = listed(seams, store);
        if (got.join() !== want.join()) {
          failures.push(`seed=${seed} step ${s}: seams ${got.join()} vs scan ${want.join()}`);
        }
        const seamPatches = patches.slice(patched).filter((x) => x[0] === "seam").length;
        if (seams.changes !== changes) seen.changes += 1;
        else seen.unchanged += 1;
        if (seamPatches !== seams.changes - changes) {
          failures.push(`seed=${seed} step ${s}: ${seamPatches} patches for a change count`);
        }
        if (seams.changes === changes && got.join() !== before && r.indexShift === 0) {
          failures.push(`seed=${seed} step ${s}: the list changed without a patch`);
        }
        const a = int(store.length + 4) - 2;
        const b = a + int(8);
        const brute = want.some((i) => i >= a && i <= b);
        if (seams.anyIn(a, b, store.ringHead, store.capacity - 1) !== brute) {
          failures.push(`seed=${seed} step ${s}: anyIn(${a}, ${b}) disagrees`);
        }
      }
    }
    expect(failures).toEqual([]);
    for (const [k, v] of Object.entries(seen)) expect(v, k).toBeGreaterThan(0);
  });
});
