// E17-T04 S2 (23 3.6, 7.2, D17; Q1 interim rule, #3068): a chunked snapshot is applied whole or not
// at all. Chunks are structured here (`s: null` is the only marker); the binary `partial` bit is a
// second marker that must agree with it.
import { describe, expect, it } from "vitest";
import type { DataBody } from "../../../src/lib/ws/protocol/codec";
import {
  createSnapshotAssembler,
  FRAME_OVERHEAD_BYTES,
  type Chunk,
} from "../../../src/lib/ws/core/snapshotAssembler";

const KEY = "book.BTCUSDT.50#live";
const COST = 100 + FRAME_OVERHEAD_BYTES;
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
      replaced: false,
      bodies: [body("only")],
    });
    expect(asm.heldBytes).toBe(0);
  });

  it("holds a chunk set until its last chunk, then hands it over whole and in order", () => {
    const asm = createSnapshotAssembler();
    expect(asm.push(KEY, chunk("a", "1"))).toEqual({ kind: "pending", replaced: false });
    expect(asm.push(KEY, chunk("a", "2"))).toEqual({ kind: "pending", replaced: false });
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
    expect(asm.push(KEY, chunk("b", "B1"))).toEqual({ kind: "pending", replaced: true });
    expect(asm.heldBytes).toBe(COST); // A is gone, B holds one chunk
    asm.push(KEY, chunk("b", "B2"));
    asm.push(KEY, chunk("b", "B3"));
    const done = asm.push(KEY, chunk("b", "B4", 2000));
    expect(done).toMatchObject({ kind: "complete", seq: 2000, replaced: false });
    // Nothing from A is in what is applied.
    expect(done.kind === "complete" && tags(done.bodies)).toEqual(
      ["B1", "B2", "B3", "B4"].map((tag) => ({ tag })),
    );
  });

  it("a snap with no id replaces an incomplete set too, and completes alone (7.2)", () => {
    const asm = createSnapshotAssembler();
    asm.push(KEY, chunk("a", "A1"));
    const done = asm.push(KEY, chunk(undefined, "whole", 9));
    expect(done).toMatchObject({
      kind: "complete",
      seq: 9,
      replaced: true,
      bodies: [body("whole")],
    });
    expect(asm.heldBytes).toBe(0);
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
  ])("%s is malformed", (_what, bad) => {
    expect(createSnapshotAssembler().push(KEY, bad)).toEqual({ kind: "malformed" });
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
    asm.forget(KEY);
    asm.discard(KEY, "c"); // nothing held, but the id is named
    expect(asm.push(KEY, chunk("c", "C1"))).toEqual({ kind: "ignored" });
    expect(asm.push(KEY, chunk(undefined, "whole", 13))).toMatchObject({ kind: "complete" });
    expect(asm.push(KEY, chunk("c", "C2"))).toMatchObject({ kind: "pending" }); // a single-frame snap lifted it
    asm.forget(KEY);
    asm.push(KEY, chunk("d", "D1"));
    asm.discard(KEY, "e"); // set e's first chunk failed: it replaced d, and it is e that is refused
    expect(asm.heldBytes).toBe(0);
    expect(asm.push(KEY, chunk("e", "E2", 20))).toEqual({ kind: "ignored" });
  });

  it("forget drops the held set without refusing anything (the subscription ended)", () => {
    const asm = createSnapshotAssembler();
    asm.push(KEY, chunk("a", "A1"));
    asm.forget(KEY);
    expect(asm.heldBytes).toBe(0);
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
});
