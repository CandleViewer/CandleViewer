// E17-T04 S5b-2 (C-2.18, C9, 06 5.1): the bounded queue of frames a consumer has not taken yet. The worker
// keeps one per consumer between the engine and the tab (a burst leaves as one message), and the tab keeps
// one behind `read()`. A baseline voids everything before it, so a queue never holds state a `snap` or a
// `reset` already replaced; and it never grows without bound: past its limits it empties itself and says
// so, and until the next baseline it takes no delta (23 7.1: a delta extends a baseline, and the one this
// queue held is gone), so its owner voids the stream and asks for a fresh snapshot.
import type { TopicFrame } from "../api";
import { JSON_HEAP_FACTOR } from "../core/snapshotAssembler";

export interface QueueLimits {
  /** Frames held at most. */
  readonly maxFrames: number;
  /** Bytes held at most, counted with `frameBytes`. */
  readonly maxBytes: number;
}

/** Far above what one animation frame brings (E17-T04's scenario is 500 frames), far below what a stalled consumer could pile up. */
export const DEFAULT_QUEUE_LIMITS: QueueLimits = { maxFrames: 4096, maxBytes: 64 * 1024 * 1024 };

/**
 * The least a structured body is charged: held as parsed values it is never as small as its few bytes.
 * Above that it is charged its encoded size times `JSON_HEAP_FACTOR`, what the assembler charges the same
 * value, so a 4 MiB structured delta is not mistaken for 2 KiB (C-2.18: a queue is bounded in bytes).
 */
export const JSON_BODY_COST = 2048;

/**
 * What a frame holds: a binary body its length; the structured bodies of a frame, which share its encoded
 * `size` (a chunked set: all its chunks), the larger of that times `JSON_HEAP_FACTOR` and a floor each.
 */
export function frameBytes(frame: TopicFrame): number {
  if (frame.kind === "reset") return 0;
  let binary = 0;
  let structured = 0;
  for (const body of frame.kind === "snap" ? frame.bodies : [frame.body]) {
    if (body.e === "b64") binary += body.bytes.byteLength;
    else structured += 1;
  }
  if (structured === 0) return binary;
  return binary + Math.max(structured * JSON_BODY_COST, frame.size * JSON_HEAP_FACTOR);
}

/** `voided`: a delta that came while the queue has no baseline (after an `overflow`, before a `snap` or a `reset`): dropped. */
export type PushResult = "ok" | "overflow" | "voided";

export interface FrameQueue {
  /**
   * Appends `frame`. A `snap` or a `reset` replaces what was queued before it (their state is void:
   * 7.1), so a queue that is read once in a while holds one baseline and the deltas since. `overflow`
   * means the limits were passed: the queue is empty now, and what it held is gone, the frame included;
   * every delta after it is `voided` until a `snap` or a `reset` comes, which are taken again.
   * A baseline that is alone in the queue is never refused for its size.
   */
  push(frame: TopicFrame): PushResult;
  /** Everything queued, in order; the queue is empty after. */
  drain(): TopicFrame[];
  /** Drops what is queued. It says nothing of the stream: a queue that had overflowed still waits for a baseline. */
  clear(): void;
  readonly size: number;
  readonly bytes: number;
}

export function createFrameQueue(limits: QueueLimits = DEFAULT_QUEUE_LIMITS): FrameQueue {
  let frames: TopicFrame[] = [];
  let bytes = 0;
  let lost = false; // an overflow emptied the queue: no delta extends anything until a baseline comes
  const clear = (): void => {
    frames = [];
    bytes = 0;
  };
  return {
    push(frame) {
      if (frame.kind === "d") {
        if (lost) return "voided";
      } else {
        clear();
        lost = false;
      }
      frames.push(frame);
      bytes += frameBytes(frame);
      if (frames.length > limits.maxFrames || (frames.length > 1 && bytes > limits.maxBytes)) {
        clear();
        lost = true;
        return "overflow";
      }
      return "ok";
    },
    drain() {
      const out = frames;
      clear();
      return out;
    },
    clear,
    get size() {
      return frames.length;
    },
    get bytes() {
      return bytes;
    },
  };
}
