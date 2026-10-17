// E17-T04 S2 (23 3.6, 7.2, D17; the marker rule of #3068): a chunked snapshot is applied whole or
// not at all. Chunks are structured here (`s: null` is the only marker); the binary `partial` bit is
// a second marker that must agree with it.
import { describe, expect, it } from "vitest";
import type { DataBody } from "../../../src/lib/ws/protocol/codec";
import {
  createSnapshotAssembler,
  FRAME_OVERHEAD_BYTES,
  JSON_HEAP_FACTOR,
  type Chunk,
} from "../../../src/lib/ws/core/snapshotAssembler";

const KEY = "book.BTCUSDT.50#live";
const COST = 100 * JSON_HEAP_FACTOR + FRAME_OVERHEAD_BYTES; // what a 100-character structured chunk is charged
const body = (tag: string): DataBody => ({ e: "j", p: { tag } });
/** A chunk of set `id` carrying `tag`; only the last one has a sequence number. */
const chunk = (id: string | undefined, tag: string, s: number | null = null): Chunk => ({
  id,
  s,
  partial: undefined,
  body: body(tag),
  size: 100,
  decodeMs: 1,
});
const tags = (bodies: readonly DataBody[]) => bodies.map((b) => (b.e === "j" ? b.p : b.bytes));

describe("snapshot assembler", () => {
  it("completes a single-frame snap at once, and holds nothing", () => {
    const asm = createSnapshotAssembler();
    expect(asm.push(KEY, chunk(undefined, "only", 7))).toMatchObject({
      kind: "complete",
      seq: 7,
      bodies: [body("only")],
      size: 100,
      decodeMs: 1,
    });
    expect(asm.heldBytes).toBe(0);
  });

  it("holds a chunk set until its last chunk, then hands it over whole and in order", () => {
    const asm = createSnapshotAssembler();
    expect(asm.push(KEY, chunk("a", "1"))).toEqual({ kind: "pending" });
    expect(asm.push(KEY, chunk("a", "2"))).toEqual({ kind: "pending" });
    expect(asm.heldBytes).toBe(2 * COST);
    const done = asm.push(KEY, chunk("a", "3", 1005));
    expect(done).toMatchObject({ kind: "complete", seq: 1005, size: 300, decodeMs: 3 });
    expect(done.kind === "complete" && tags(done.bodies)).toEqual([
      { tag: "1" },
      { tag: "2" },
      { tag: "3" },
    ]);
    expect(asm.heldBytes).toBe(0);
  });

  it("D17: snap id B replaces incomplete set A", () => {
    const asm = createSnapshotAssembler();
    asm.push(KEY, chunk("a", "A1"));
    asm.push(KEY, chunk("a", "A2")); // chunks 1..2 of 4 of set A
    expect(asm.push(KEY, chunk("b", "B1"))).toEqual({ kind: "pending" });
    expect(asm.heldBytes).toBe(COST); // A is gone, B holds one chunk
    asm.push(KEY, chunk("b", "B2"));
    asm.push(KEY, chunk("b", "B3"));
    const done = asm.push(KEY, chunk("b", "B4", 2000));
    expect(done).toMatchObject({ kind: "complete", seq: 2000 });
    // Nothing from A is in what is applied.
    expect(done.kind === "complete" && tags(done.bodies)).toEqual(
      ["B1", "B2", "B3", "B4"].map((tag) => ({ tag })),
    );
  });

  it("a snap with no id replaces an incomplete set too, and completes alone (7.2)", () => {
    const asm = createSnapshotAssembler();
    asm.push(KEY, chunk("a", "A1"));
    const done = asm.push(KEY, chunk(undefined, "whole", 9));
    expect(done).toMatchObject({ kind: "complete", seq: 9, bodies: [body("whole")] });
    expect(asm.heldBytes).toBe(0); // A is gone: a later chunk of it is not a continuation
    expect(asm.push(KEY, chunk("a", "A2", 10))).toEqual({ kind: "malformed" });
  });

  it("keeps the sets of different streams apart", () => {
    const asm = createSnapshotAssembler();
    const replay = "book.BTCUSDT.50#bb000000-0000-4000-8000-000000000001";
    asm.push(KEY, chunk("a", "live1"));
    asm.push(replay, chunk("a", "replay1"));
    const done = asm.push(KEY, chunk("a", "live2", 5));
    expect(done.kind === "complete" && tags(done.bodies)).toEqual([
      { tag: "live1" },
      { tag: "live2" },
    ]);
    expect(asm.heldBytes).toBe(COST); // the replay chunk is still held
  });

  it.each([
    [
      "a chunk marked partial that carries a sequence number",
      { ...chunk("a", "x", 5), partial: true },
    ],
    [
      "a chunk with no number that the binary header does not mark partial",
      { ...chunk("a", "x"), partial: false },
    ],
    ["a chunk with no set id", chunk(undefined, "x")],
    ["the last chunk of a set that is not held", chunk("a", "x", 9)],
  ])("%s is malformed", (_what, bad) => {
    expect(createSnapshotAssembler().push(KEY, bad)).toEqual({ kind: "malformed" });
  });

  it("a malformed frame changes nothing: the held set is still there for the caller to discard", () => {
    const asm = createSnapshotAssembler();
    asm.push(KEY, chunk("a", "A1"));
    asm.push(KEY, chunk("a", "A2"));
    for (const bad of [
      chunk(undefined, "x"), // no id and `s: null`: a chunk of no set
      { ...chunk("a", "x", 5), partial: true }, // the markers disagree
      chunk("z", "Z4", 9), // the last chunk of a set that is not held
    ]) {
      expect(asm.push(KEY, bad)).toEqual({ kind: "malformed" });
      expect(asm.heldBytes).toBe(2 * COST);
    }
    asm.discard(KEY); // what the caller does: the held set goes, and its tail is refused
    expect(asm.push(KEY, chunk("a", "A3"))).toEqual({ kind: "ignored" });
    expect(asm.push(KEY, chunk("a", "A4", 500))).toEqual({ kind: "ignored" }); // never [A3, A4] as a baseline
  });

  it("charges a structured chunk for the heap it takes, a binary one for its message length", () => {
    const binary = (tag: string): Chunk => ({
      ...chunk("a", tag),
      body: { e: "b64", bytes: new ArrayBuffer(1) },
    });
    const asm = createSnapshotAssembler({ maxHeldBytes: 5 * (100 + FRAME_OVERHEAD_BYTES) });
    for (const tag of ["1", "2", "3", "4", "5"]) asm.push(KEY, binary(tag)); // 5 x (100 + 256) fits
    expect(asm.heldBytes).toBe(5 * (100 + FRAME_OVERHEAD_BYTES));
    asm.forget(KEY);
    asm.push(KEY, chunk("a", "A1"));
    asm.push(KEY, chunk("a", "A2")); // 2 x COST fits
    expect(asm.push(KEY, chunk("a", "A3"))).toEqual({ kind: "overflow" }); // 3 x COST does not
  });

  it("accepts the binary markers when they agree with s", () => {
    const asm = createSnapshotAssembler();
    expect(asm.push(KEY, { ...chunk("a", "1"), partial: true })).toMatchObject({ kind: "pending" });
    expect(asm.push(KEY, { ...chunk("a", "2", 3), partial: false })).toMatchObject({
      kind: "complete",
    });
  });

  it("discard drops the held set and refuses the rest of it, so its tail is never a snapshot", () => {
    const asm = createSnapshotAssembler();
    asm.push(KEY, chunk("a", "A1"));
    asm.discard(KEY);
    expect(asm.heldBytes).toBe(0);
    expect(asm.push(KEY, chunk("a", "A2"))).toEqual({ kind: "ignored" });
    expect(asm.push(KEY, chunk("a", "A3", 12))).toEqual({ kind: "ignored" }); // the last chunk alone is no snapshot
    expect(asm.push(KEY, chunk("b", "B1"))).toMatchObject({ kind: "pending" }); // another set lifts it
    expect(asm.push(KEY, chunk("a", "A5"))).toMatchObject({ kind: "pending" }); // and "a" is accepted again
    asm.forget(KEY);
    asm.discard(KEY, "c"); // nothing held, but the id is named
    expect(asm.push(KEY, chunk("c", "C1"))).toEqual({ kind: "ignored" });
    expect(asm.push(KEY, chunk(undefined, "whole", 13))).toMatchObject({ kind: "complete" });
    expect(asm.push(KEY, chunk("c", "C2"))).toMatchObject({ kind: "pending" }); // a single-frame snap lifted it
    asm.forget(KEY);
    asm.push(KEY, chunk("d", "D1"));
    asm.discard(KEY, "e"); // set e's first chunk failed: it replaced d, and either might still be coming
    expect(asm.heldBytes).toBe(0);
    expect(asm.push(KEY, chunk("e", "E2", 20))).toEqual({ kind: "ignored" });
    expect(asm.push(KEY, chunk("d", "D2", 21))).toEqual({ kind: "ignored" }); // so both are refused
    expect(asm.push(KEY, chunk("f", "F1"))).toMatchObject({ kind: "pending" }); // a third set lifts both
    expect(asm.push(KEY, chunk("e", "E3"))).toMatchObject({ kind: "pending" });
  });

  it("forget drops the held set without refusing anything (the subscription ended)", () => {
    const asm = createSnapshotAssembler();
    asm.push(KEY, chunk("a", "A1"));
    expect(asm.holds(KEY)).toBe(true);
    asm.forget(KEY);
    expect([asm.holds(KEY), asm.heldBytes]).toEqual([false, 0]);
    expect(asm.push(KEY, chunk("a", "A2"))).toMatchObject({ kind: "pending" });
    asm.discard(KEY, "z");
    asm.forget(KEY); // and it forgets a refusal too
    expect(asm.push(KEY, chunk("z", "Z1"))).toMatchObject({ kind: "pending" });
  });

  it("drops a set that passes the held-bytes cap and refuses its tail (bounded chunk memory)", () => {
    const asm = createSnapshotAssembler({ maxHeldBytes: 2 * COST });
    asm.push(KEY, chunk("a", "A1"));
    asm.push(KEY, chunk("a", "A2"));
    expect(asm.push(KEY, chunk("a", "A3"))).toEqual({ kind: "overflow" });
    expect(asm.heldBytes).toBe(0);
    expect(asm.push(KEY, chunk("a", "A4", 40))).toEqual({ kind: "ignored" });
    expect(asm.push(KEY, chunk("b", "B1"))).toMatchObject({ kind: "pending" });
  });

  it("charges every stream against one cap, and drops only the set that crossed it", () => {
    const asm = createSnapshotAssembler({ maxHeldBytes: 3 * COST });
    const other = "trades.BTCUSDT#live";
    asm.push(KEY, chunk("a", "A1"));
    asm.push(other, chunk("t", "T1"));
    asm.push(KEY, chunk("a", "A2"));
    expect(asm.push(other, chunk("t", "T2"))).toEqual({ kind: "overflow" });
    expect(asm.heldBytes).toBe(2 * COST); // the set of KEY is untouched
    expect(asm.push(KEY, chunk("a", "A3", 8))).toMatchObject({ kind: "complete", seq: 8 });
  });

  it("does not charge a single-frame snap against the cap: it is never held", () => {
    const asm = createSnapshotAssembler({ maxHeldBytes: COST });
    asm.push(KEY, chunk("a", "A1"));
    expect(asm.push("trades.BTCUSDT#live", chunk(undefined, "whole", 1))).toMatchObject({
      kind: "complete",
    });
  });

  it("caps what one set may hold, so a set that never completes cannot take the whole budget", () => {
    const asm = createSnapshotAssembler({ maxHeldBytes: 4 * COST, maxSetBytes: 2 * COST });
    asm.push(KEY, chunk("a", "A1"));
    asm.push(KEY, chunk("a", "A2")); // exactly at the set cap: still held
    expect(asm.push(KEY, chunk("a", "A3"))).toEqual({ kind: "overflow" }); // the set cap, not the global one
    expect(asm.heldBytes).toBe(0);
    expect(asm.push(KEY, chunk("a", "A4", 9))).toEqual({ kind: "ignored" }); // its tail is refused
    for (const key of ["trades.BTCUSDT#live", "profile.BTCUSDT.volume#live"]) {
      expect(asm.push(key, chunk("t", "T1"))).toEqual({ kind: "pending" }); // two other streams
      expect(asm.push(key, chunk("t", "T2"))).toEqual({ kind: "pending" }); // still hold a set each
    }
    expect(asm.heldBytes).toBe(4 * COST);
  });

  it("a set that is dropped for its size refuses the one it replaced too", () => {
    const asm = createSnapshotAssembler({ maxHeldBytes: 3 * COST });
    const other = "trades.BTCUSDT#live";
    asm.push(other, chunk("t", "T1"));
    asm.push(other, chunk("t", "T2"));
    asm.push(KEY, chunk("a", "A1")); // three chunks held: at the cap
    const big: Chunk = { ...chunk("b", "B1"), size: 200 };
    expect(asm.push(KEY, big)).toEqual({ kind: "overflow" }); // b replaces a, and does not fit
    expect(asm.push(KEY, chunk("a", "A2", 4))).toEqual({ kind: "ignored" }); // a goes with it
    expect(asm.push(KEY, chunk("b", "B2", 5))).toEqual({ kind: "ignored" });
  });

  it("judges a set that replaces another on its own size, not on the one it replaced", () => {
    const asm = createSnapshotAssembler({ maxHeldBytes: 4 * COST, maxSetBytes: 2 * COST });
    asm.push(KEY, chunk("a", "A1"));
    asm.push(KEY, chunk("a", "A2")); // set a is at its cap
    expect(asm.push(KEY, chunk("b", "B1"))).toEqual({ kind: "pending" });
    expect(asm.push(KEY, chunk("b", "B2", 5))).toMatchObject({ kind: "complete", seq: 5 });
  });
});

describe("snapshot assembler: structured sets at the sizes the gateway sends (3.6)", () => {
  // The gateway splits a structured snapshot only past 4 MiB of JSON, into chunks of nearly 4 MiB.
  const MiB = 1024 * 1024;
  const sized = (size: number, s: number | null = null): Chunk => ({ ...chunk("a", "x", s), size });

  it("a structured set just over 4 MiB assembles", () => {
    const asm = createSnapshotAssembler();
    expect(asm.push(KEY, sized(2.5 * MiB))).toEqual({ kind: "pending" });
    expect(asm.push(KEY, sized(2 * MiB, 7))).toMatchObject({ kind: "complete", seq: 7 });
    expect(asm.heldBytes).toBe(0);
  });

  it("holds four chunks of the frame limit, 16 MiB of text, and drops the set at a fifth", () => {
    const asm = createSnapshotAssembler();
    const full = (s: number | null = null) => sized(4 * MiB - 1024, s);
    for (let i = 0; i < 3; i += 1) expect(asm.push(KEY, full())).toEqual({ kind: "pending" });
    expect(asm.push(KEY, full(9))).toMatchObject({ kind: "complete", seq: 9 });
    for (let i = 0; i < 4; i += 1) asm.push(KEY, full());
    expect(asm.push(KEY, full(10))).toEqual({ kind: "overflow" });
    expect(asm.push(KEY, full(11))).toEqual({ kind: "ignored" });
  });

  it("pins the defaults to the byte: 64 MiB a set, 128 MiB across streams, a factor of 4 and 256 a chunk", () => {
    const edge = 16 * MiB - 64; // x 4 + 256 is exactly 64 MiB
    expect(createSnapshotAssembler().push(KEY, sized(edge))).toEqual({ kind: "pending" });
    expect(createSnapshotAssembler().push(KEY, sized(edge + 1))).toEqual({ kind: "overflow" });
    const asm = createSnapshotAssembler();
    expect(asm.push(KEY, sized(edge))).toEqual({ kind: "pending" });
    expect(asm.push("trades.BTCUSDT#live", sized(edge))).toEqual({ kind: "pending" });
    expect(asm.heldBytes).toBe(128 * MiB); // exactly the cap: it fits
    expect(asm.push("profile.BTCUSDT.volume#live", sized(1))).toEqual({ kind: "overflow" });
  });

  it("shares 128 MiB between the streams: two sets of 63 MiB fit, a third does not", () => {
    const asm = createSnapshotAssembler();
    const first = (key: string) => asm.push(key, sized(15.75 * MiB)); // 63 MiB charged at 4x
    expect(first(KEY)).toEqual({ kind: "pending" });
    expect(first("trades.BTCUSDT#live")).toEqual({ kind: "pending" });
    expect(first("profile.BTCUSDT.volume#live")).toEqual({ kind: "overflow" });
  });
});

describe("snapshot assembler: the chunk count of one set", () => {
  // Small chunks: 4 096 of them cost about 1 MiB, far under both byte caps, so only the count stops them.
  const tiny = (id: string, s: number | null = null): Chunk => ({ ...chunk(id, "t", s), size: 1 });
  const fill = (asm: ReturnType<typeof createSnapshotAssembler>, id: string, count: number) => {
    for (let i = 0; i < count; i += 1) asm.push(KEY, tiny(id));
  };

  it("holds a set of exactly 4 096 chunks and hands it over", () => {
    const asm = createSnapshotAssembler();
    fill(asm, "a", 4096 - 1);
    const done = asm.push(KEY, tiny("a", 7));
    expect(done).toMatchObject({ kind: "complete", seq: 7 });
    expect(done.kind === "complete" && done.bodies.length).toBe(4096);
  });

  it("drops a set that would pass it, and refuses its tail", () => {
    const asm = createSnapshotAssembler();
    fill(asm, "a", 4096);
    expect(asm.heldBytes).toBe(4096 * (JSON_HEAP_FACTOR + FRAME_OVERHEAD_BYTES));
    expect(asm.push(KEY, tiny("a", 8))).toEqual({ kind: "overflow" }); // the last chunk would be the 4 097th
    expect(asm.heldBytes).toBe(0);
    expect(asm.push(KEY, tiny("a", 9))).toEqual({ kind: "ignored" });
  });

  it("counts a replacing set from its own first chunk", () => {
    const asm = createSnapshotAssembler();
    fill(asm, "a", 4096);
    expect(asm.push(KEY, tiny("b"))).toEqual({ kind: "pending" });
    expect(asm.heldBytes).toBe(JSON_HEAP_FACTOR + FRAME_OVERHEAD_BYTES);
  });
});
