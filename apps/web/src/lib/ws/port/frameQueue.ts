// E17-T04 S5b (C-2.18, C9, 06 5.1): the bounded queue of frames a consumer has not taken yet. The worker
// keeps one per consumer between the engine and the tab (a burst leaves as one message), and the tab keeps
// one behind `read()`. A baseline voids everything before it, so a queue never holds state a `snap` or a
// `reset` already replaced; and it never grows without bound: past its limits it empties itself and says
// so, and its owner voids the stream and asks for a fresh snapshot.
import type { TopicFrame } from "../api";

export interface QueueLimits {
  /** Frames held at most. */
  readonly maxFrames: number;
  /** Bytes held at most, counted with `frameBytes`. */
  readonly maxBytes: number;
}

/** Far above what one animation frame brings (500 frames is the scenario of 23 8.5), far below what a stalled consumer could pile up. */
export const DEFAULT_QUEUE_LIMITS: QueueLimits = { maxFrames: 4096, maxBytes: 64 * 1024 * 1024 };

/**
 * What a frame with a structured body is charged: its size is not known here (the codec bounds a whole
 * message at 4 MiB), so each pays a flat share. A binary body pays its length.
 */
export const JSON_BODY_COST = 2048;

export function frameBytes(frame: TopicFrame): number {
  if (frame.kind === "reset") return 0;
  let bytes = 0;
  for (const body of frame.kind === "snap" ? frame.bodies : [frame.body]) {
    bytes += body.e === "b64" ? body.bytes.byteLength : JSON_BODY_COST;
  }
  return bytes;
}

export interface FrameQueue {
  /**
   * Appends `frame`. A `snap` or a `reset` replaces what was queued before it (their state is void:
   * 7.1), so a queue that is read once in a while holds one baseline and the deltas since. `overflow`
   * means the limits were passed: the queue is empty now, and what it held is gone, the frame included.
   * A baseline that is alone in the queue is never refused for its size.
   */
  push(frame: TopicFrame): "ok" | "overflow";
  /** Everything queued, in order; the queue is empty after. */
  drain(): TopicFrame[];
  clear(): void;
  readonly size: number;
  readonly bytes: number;
}

export function createFrameQueue(limits: QueueLimits = DEFAULT_QUEUE_LIMITS): FrameQueue {
  let frames: TopicFrame[] = [];
  let bytes = 0;
  const clear = (): void => {
    frames = [];
    bytes = 0;
  };
  return {
    push(frame) {
      if (frame.kind !== "d") clear();
      frames.push(frame);
      bytes += frameBytes(frame);
      if (frames.length > limits.maxFrames || (frames.length > 1 && bytes > limits.maxBytes)) {
        clear();
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
