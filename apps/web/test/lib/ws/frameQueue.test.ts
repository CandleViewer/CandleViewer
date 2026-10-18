// E17-T04 S5b-2 (C-2.18, C9, 06 5.1): the bounded queue behind a consumer's `read()`, and the worker's per-consumer
// queue between the engine and the tab. A baseline voids what came before it; past its limits the queue empties
// itself and says so, and takes no delta until the next baseline.
import { describe, expect, it } from "vitest";
import type { TopicFrame } from "../../../src/lib/ws/api";
import { createFrameQueue, frameBytes, JSON_BODY_COST } from "../../../src/lib/ws/port/frameQueue";

const MIB = 1024 * 1024;
const base = { ts: 1, sp: undefined, decodeMs: 0, meta: undefined };
/** A delta: a binary body of `bytes`, or a structured one that arrived as `wire` bytes. */
const delta = (seq: number, bytes?: number, wire = 0): TopicFrame => ({
  kind: "d",
  seq,
  ...base,
  size: bytes ?? wire,
  body: bytes === undefined ? { e: "j", p: {} } : { e: "b64", bytes: new ArrayBuffer(bytes) },
});
/** A snapshot of binary chunks of these lengths, or one structured chunk when there are none. */
const snap = (seq: number, ...sizes: number[]): TopicFrame => ({
  kind: "snap",
  seq,
  ...base,
  size: sizes.reduce((sum, n) => sum + n, 0),
  bodies:
    sizes.length === 0
      ? [{ e: "j", p: {} }]
      : [
          { e: "b64", bytes: new ArrayBuffer(sizes[0] ?? 0) },
          ...sizes.slice(1).map((n) => ({ e: "b64" as const, bytes: new ArrayBuffer(n) })),
        ],
});
/** A chunked structured snapshot: `chunks` bodies that arrived as `wire` bytes in all. */
const jsonSnap = (seq: number, chunks: number, wire: number): TopicFrame => ({
  kind: "snap",
  seq,
  ...base,
  size: wire,
  bodies: [
    { e: "j", p: {} },
    ...Array.from({ length: chunks - 1 }, () => ({ e: "j" as const, p: {} })),
  ],
});
const reset: TopicFrame = { kind: "reset", reason: "gap" };
const seqs = (frames: readonly TopicFrame[]) =>
  frames.map((f) => (f.kind === "reset" ? `reset:${f.reason}` : `${f.kind}:${f.seq}`));

describe("what a frame costs", () => {
  it("is its length for a binary body, and nothing for a reset", () => {
    expect(frameBytes(delta(1, 300))).toBe(300);
    expect(frameBytes(snap(1, 100, 28))).toBe(128); // every chunk of a set
    expect(frameBytes(reset)).toBe(0);
  });

  it("is, for a structured body, 2 KiB at least and four times what it arrived as above that", () => {
    expect(JSON_BODY_COST).toBe(2048);
    expect(frameBytes(delta(1))).toBe(2048); // it arrived as nothing: the floor
    expect(frameBytes(delta(1, undefined, 100))).toBe(2048);
    expect(frameBytes(delta(1, undefined, 512))).toBe(2048); // 512 x 4 is the floor exactly
    expect(frameBytes(delta(1, undefined, 513))).toBe(2052);
    expect(frameBytes(delta(1, undefined, 1000))).toBe(4000);
    expect(frameBytes(delta(1, undefined, 4 * MIB))).toBe(16 * MIB);
  });

  it("is, for a chunked structured snapshot, what the whole set arrived as, shared out, with a floor for each chunk", () => {
    expect(frameBytes(jsonSnap(1, 3, 10_000))).toBe(40_000);
    expect(frameBytes(jsonSnap(1, 3, 100))).toBe(3 * 2048);
    expect(frameBytes(snap(1))).toBe(2048);
  });

  it("counts binary and structured bodies of one frame both", () => {
    const mixed: TopicFrame = {
      kind: "snap",
      seq: 1,
      ...base,
      size: 3000,
      bodies: [
        { e: "b64", bytes: new ArrayBuffer(50) },
        { e: "j", p: {} },
      ],
    };
    expect(frameBytes(mixed)).toBe(50 + 12_000);
  });
});

describe("a bounded frame queue", () => {
  it("hands over what was queued, in order, and is empty after", () => {
    const queue = createFrameQueue();
    for (const seq of [2, 3, 4]) expect(queue.push(delta(seq))).toBe("ok");
    expect([queue.size, queue.bytes]).toEqual([3, 3 * 2048]);
    expect(seqs(queue.drain())).toEqual(["d:2", "d:3", "d:4"]);
    expect([queue.size, queue.bytes, queue.drain()]).toEqual([0, 0, []]);
  });

  it("a snapshot voids what came before it: the queue holds one baseline and the deltas since", () => {
    const queue = createFrameQueue();
    queue.push(delta(2, 10));
    queue.push(delta(3, 10));
    queue.push(snap(9, 5));
    queue.push(delta(10, 1));
    expect(seqs(queue.drain())).toEqual(["snap:9", "d:10"]);
    queue.push(snap(11, 7));
    expect(queue.bytes).toBe(7); // the bytes of what was dropped are not still counted
  });

  it("a reset voids what came before it too, and is itself kept: the consumer must clear its state", () => {
    const queue = createFrameQueue();
    queue.push(delta(2));
    queue.push(reset);
    queue.push(delta(3));
    expect(seqs(queue.drain())).toEqual(["reset:gap", "d:3"]);
  });

  it("empties itself and says so when it holds more frames than its limit", () => {
    const queue = createFrameQueue({ maxFrames: 3, maxBytes: 1e9 });
    expect([1, 2, 3].map((n) => queue.push(delta(n)))).toEqual(["ok", "ok", "ok"]);
    expect(queue.push(delta(4))).toBe("overflow");
    expect([queue.size, queue.bytes]).toEqual([0, 0]); // the frame that broke it is gone too
  });

  it("empties itself and says so when it holds more bytes than its limit", () => {
    const queue = createFrameQueue({ maxFrames: 100, maxBytes: 100 });
    expect(queue.push(delta(1, 60))).toBe("ok");
    expect(queue.push(delta(2, 40))).toBe("ok"); // exactly the limit
    expect(queue.push(delta(3, 1))).toBe("overflow");
    expect(queue.size).toBe(0);
  });

  it("a 4 MiB structured delta is charged what it holds: the bytes trip before the frames", () => {
    const queue = createFrameQueue(); // 4 096 frames, 64 MiB
    const big = (seq: number) => delta(seq, undefined, 4 * MIB);
    expect([1, 2, 3, 4].map((n) => queue.push(big(n)))).toEqual(["ok", "ok", "ok", "ok"]);
    expect(queue.bytes).toBe(64 * MIB); // four of 16 MiB: exactly the limit
    expect(queue.push(big(5))).toBe("overflow"); // 5 frames of 4 096: it was the bytes
    expect(queue.size).toBe(0);
  });

  it("never refuses a baseline that is alone for its size, but not the delta behind it", () => {
    const queue = createFrameQueue({ maxFrames: 100, maxBytes: 100 });
    expect(queue.push(snap(1, 5_000))).toBe("ok"); // a snapshot bigger than the queue's bytes is still the state
    expect(queue.bytes).toBe(5_000);
    expect(queue.push(delta(2, 1))).toBe("overflow");
    expect(queue.size).toBe(0);
    expect(queue.push(jsonSnap(3, 2, 8 * MIB))).toBe("ok"); // nor a structured one, which is charged 32 MiB
    expect(queue.bytes).toBe(32 * MIB);
  });

  it("after an overflow it takes no delta, which extends nothing, until a snapshot comes", () => {
    const queue = createFrameQueue({ maxFrames: 2, maxBytes: 1e9 });
    expect([1, 2, 3].map((n) => queue.push(delta(n)))).toEqual(["ok", "ok", "overflow"]);
    expect(queue.push(delta(4))).toBe("voided");
    expect(queue.push(delta(5))).toBe("voided");
    expect([queue.size, queue.bytes]).toEqual([0, 0]); // dropped, not held
    expect(queue.push(snap(6, 1))).toBe("ok");
    expect(queue.push(delta(7))).toBe("ok"); // it has a baseline again
    expect(seqs(queue.drain())).toEqual(["snap:6", "d:7"]);
  });

  it("a reset ends the wait for a baseline too: its owner says the state is void, and a snapshot follows", () => {
    const queue = createFrameQueue({ maxFrames: 1, maxBytes: 1e9 });
    queue.push(delta(1));
    expect(queue.push(delta(2))).toBe("overflow");
    expect(queue.push(delta(3))).toBe("voided");
    expect(queue.push(reset)).toBe("ok");
    expect(queue.push(delta(4))).toBe("overflow"); // it takes a frame again (this one is past the limit of one)
    expect(queue.push(delta(5))).toBe("voided");
  });

  it("an overflow caused by a baseline's own company still voids the deltas after it", () => {
    const queue = createFrameQueue({ maxFrames: 100, maxBytes: 100 });
    queue.push(snap(1, 90));
    expect(queue.push(delta(2, 20))).toBe("overflow");
    expect(queue.push(delta(3, 1))).toBe("voided");
  });

  it("clear drops everything, and says nothing of the stream", () => {
    const queue = createFrameQueue();
    queue.push(delta(1, 10));
    queue.clear();
    expect([queue.size, queue.bytes, queue.drain()]).toEqual([0, 0, []]);
    expect(queue.push(delta(2))).toBe("ok"); // it had not overflowed

    const lost = createFrameQueue({ maxFrames: 1, maxBytes: 1e9 });
    lost.push(delta(1));
    lost.push(delta(2)); // overflow
    lost.clear();
    expect(lost.push(delta(3))).toBe("voided"); // still without a baseline
  });
});
