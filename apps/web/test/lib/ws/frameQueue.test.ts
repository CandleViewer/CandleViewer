// E17-T04 S5b (C-2.18, C9, 06 5.1): the bounded queue behind a consumer's `read()`, and the worker's per-consumer
// queue between the engine and the tab. A baseline voids what came before it; past its limits the queue empties
// itself and says so.
import { describe, expect, it } from "vitest";
import type { TopicFrame } from "../../../src/lib/ws/api";
import { createFrameQueue, frameBytes, JSON_BODY_COST } from "../../../src/lib/ws/port/frameQueue";

const base = { ts: 1, sp: undefined, decodeMs: 0, meta: undefined };
const delta = (seq: number, size?: number): TopicFrame => ({
  kind: "d",
  seq,
  ...base,
  body: size === undefined ? { e: "j", p: {} } : { e: "b64", bytes: new ArrayBuffer(size) },
});
const snap = (seq: number, ...sizes: number[]): TopicFrame => ({
  kind: "snap",
  seq,
  ...base,
  bodies:
    sizes.length === 0
      ? [{ e: "j", p: {} }]
      : [
          { e: "b64", bytes: new ArrayBuffer(sizes[0] ?? 0) },
          ...sizes.slice(1).map((n) => ({ e: "b64" as const, bytes: new ArrayBuffer(n) })),
        ],
});
const reset: TopicFrame = { kind: "reset", reason: "gap" };
const seqs = (frames: readonly TopicFrame[]) =>
  frames.map((f) => (f.kind === "reset" ? `reset:${f.reason}` : `${f.kind}:${f.seq}`));

describe("what a frame costs", () => {
  it("is its length for a binary body, a flat share for a structured one, and nothing for a reset", () => {
    expect(frameBytes(delta(1, 300))).toBe(300);
    expect(frameBytes(delta(1))).toBe(JSON_BODY_COST);
    expect(frameBytes(snap(1, 100, 28))).toBe(128); // every chunk of a set
    expect(frameBytes(snap(1))).toBe(JSON_BODY_COST);
    expect(frameBytes(reset)).toBe(0);
  });
});

describe("a bounded frame queue", () => {
  it("hands over what was queued, in order, and is empty after", () => {
    const queue = createFrameQueue();
    for (const seq of [2, 3, 4]) expect(queue.push(delta(seq))).toBe("ok");
    expect([queue.size, queue.bytes]).toEqual([3, 3 * JSON_BODY_COST]);
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
    expect(queue.push(delta(5))).toBe("ok"); // and it takes frames again
    expect(seqs(queue.drain())).toEqual(["d:5"]);
  });

  it("empties itself and says so when it holds more bytes than its limit", () => {
    const queue = createFrameQueue({ maxFrames: 100, maxBytes: 100 });
    expect(queue.push(delta(1, 60))).toBe("ok");
    expect(queue.push(delta(2, 40))).toBe("ok"); // exactly the limit
    expect(queue.push(delta(3, 1))).toBe("overflow");
    expect(queue.size).toBe(0);
  });

  it("never refuses a baseline that is alone for its size, but not the delta behind it", () => {
    const queue = createFrameQueue({ maxFrames: 100, maxBytes: 100 });
    expect(queue.push(snap(1, 5_000))).toBe("ok"); // a snapshot bigger than the queue's bytes is still the state
    expect(queue.bytes).toBe(5_000);
    expect(queue.push(delta(2, 1))).toBe("overflow");
    expect(queue.size).toBe(0);
  });

  it("clear drops everything", () => {
    const queue = createFrameQueue();
    queue.push(delta(1, 10));
    queue.clear();
    expect([queue.size, queue.bytes, queue.drain()]).toEqual([0, 0, []]);
  });
});
