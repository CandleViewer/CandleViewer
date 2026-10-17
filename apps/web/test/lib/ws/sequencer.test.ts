// E17-T04 S2 (23 7.1, C2): a `d` applies only as the next number of a live stream. Anything else
// voids the stream, and nothing applies again until a complete `snap`.
import { describe, expect, it } from "vitest";
import { createSequencer, topicKey } from "../../../src/lib/ws/core/sequencer";

const BOOK = topicKey("book.BTCUSDT.50");
const APPLY = { kind: "apply" };
const DROP = { kind: "drop" };
const RS = "bb000000-0000-4000-8000-000000000001";

/** mulberry32: a small seeded PRNG, so a failing case names its seed and replays exactly. */
function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4_294_967_296;
  };
}

describe("sequencer", () => {
  it("A gap is never patched", () => {
    const seq = createSequencer();
    seq.baseline(BOOK, 1000);
    expect(seq.accept(BOOK, 1001)).toEqual(APPLY);
    expect(seq.accept(BOOK, 1002)).toEqual(APPLY);
    // 1003 is lost: 1004 is a gap, it is not applied and it does not become the baseline.
    expect(seq.accept(BOOK, 1004)).toEqual({ kind: "gap", check: "gap", lastSeq: 1002 });
    expect(seq.state(BOOK)).toBe("resyncing");
    // Nothing applies until the fresh snap: not the late 1003 that would "fill" the hole, nor 1005...
    for (const s of [1003, 1004, 1005, 1006]) expect(seq.accept(BOOK, s)).toEqual(DROP);
    expect(seq.lastSeq(BOOK)).toBe(1002);
    seq.baseline(BOOK, 1010);
    expect(seq.state(BOOK)).toBe("live");
    expect(seq.accept(BOOK, 1011)).toEqual(APPLY);
  });

  it("treats a duplicate and an out-of-order frame as gaps too (C-2.5)", () => {
    const seq = createSequencer();
    seq.baseline(BOOK, 10);
    expect(seq.accept(BOOK, 11)).toEqual(APPLY);
    expect(seq.accept(BOOK, 11)).toEqual({ kind: "gap", check: "duplicate", lastSeq: 11 });
    seq.baseline(BOOK, 20);
    expect(seq.accept(BOOK, 15)).toEqual({ kind: "gap", check: "out-of-order", lastSeq: 20 });
  });

  it("drops a d that has no baseline, and a fresh snap resets one even with a lower number", () => {
    const seq = createSequencer();
    expect(seq.state(BOOK)).toBe("pending");
    expect(seq.accept(BOOK, 1)).toEqual(DROP);
    expect(seq.lastSeq(BOOK)).toBeNull();
    seq.baseline(BOOK, 500);
    seq.baseline(BOOK, 3); // a replay seek or a generation swap moves the number anywhere (7.4)
    expect(seq.accept(BOOK, 4)).toEqual(APPLY);
  });

  it("discard voids a live stream but keeps the last number for the resync that follows", () => {
    const seq = createSequencer();
    seq.baseline(BOOK, 7);
    seq.discard(BOOK);
    expect([seq.state(BOOK), seq.lastSeq(BOOK)]).toEqual(["resyncing", 7]);
    expect(seq.accept(BOOK, 8)).toEqual(DROP);
    const fresh = createSequencer();
    fresh.discard(BOOK); // a stream that never had a baseline is awaiting one too
    expect([fresh.state(BOOK), fresh.lastSeq(BOOK)]).toEqual(["resyncing", null]);
    seq.forget(BOOK);
    expect([seq.state(BOOK), seq.lastSeq(BOOK)]).toEqual(["pending", null]);
  });

  it("keeps live and replay data of one ch independent (23 11)", () => {
    const seq = createSequencer();
    const replay = topicKey("book.BTCUSDT.50", RS);
    expect(replay).not.toBe(BOOK);
    seq.baseline(BOOK, 100);
    seq.baseline(replay, 5);
    expect(seq.accept(replay, 7)).toMatchObject({ kind: "gap", lastSeq: 5 }); // replay gaps...
    expect(seq.accept(BOOK, 101)).toEqual(APPLY); // ...and live is untouched
    expect(seq.accept(replay, 6)).toEqual(DROP);
    expect(seq.state(BOOK)).toBe("live");
  });

  it("a 1 000-frame stream with one d dropped never applies across the gap (exact oracle)", () => {
    for (let seed = 1; seed <= 100; seed += 1) {
      const rand = mulberry32(seed);
      const base = Math.floor(rand() * 1e9);
      const lost = base + 1 + Math.floor(rand() * 1000); // any of base+1 .. base+1000, either end included
      const sent = Array.from({ length: 1000 }, (_, i) => base + 1 + i).filter((s) => s !== lost);
      const seq = createSequencer();
      seq.baseline(BOOK, base);
      const verdicts = sent.map((s) => seq.accept(BOOK, s));
      // Oracle: what precedes the hole applies, the first frame after it is the one gap, the rest drop.
      const expected = sent.map((s) => (s < lost ? "apply" : s === lost + 1 ? "gap" : "drop"));
      expect(
        verdicts.map((v) => v.kind),
        `seed ${seed}`,
      ).toEqual(expected);
      const gap = verdicts.find((v) => v.kind === "gap");
      expect(
        gap === undefined || (gap.kind === "gap" && gap.lastSeq === lost - 1),
        `seed ${seed}`,
      ).toBe(true);
      // Recovery is the fresh snap and nothing else.
      expect(seq.accept(BOOK, lost)).toEqual(gap === undefined ? APPLY : DROP);
      seq.baseline(BOOK, base + 2000);
      expect(seq.accept(BOOK, base + 2001)).toEqual(APPLY);
    }
  });
});
