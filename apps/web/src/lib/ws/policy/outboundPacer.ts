// E17-T04 S3 (23 8.5, C7): the outbound pacer. The gateway answers more than 30 frames/s or 300/min
// with `client_rate_limited` and then closes 4429. It counts a frame when it dispatches it, not when
// we send it, so network jitter moves frames across the edge of any window we keep: 27 frames sent
// at once and 27 more exactly 1 000 ms later can reach it as 30 or more inside one of its seconds.
// So the pacer keeps two margins: frames leave at least 40 ms apart (25 a second at most), and its
// windows are wider than the gateway's. A frame over budget waits: it is never dropped and never sent
// early. Frames queued before the next microtask checkpoint leave together, in FIFO order (an `await`
// between two `enqueue`s splits the flush), except a `ping`, which goes first and has slots kept for
// it (the heartbeat must not starve behind a backlog), and a `ctl` for a `ch` that already has one
// waiting, which merges into it (the latest value wins).
import { ctl, type ClientFrame, type CtlPayload } from "../protocol/frames";
import { platformTimers, type Timers } from "./timers";

/** Frames are at least this far apart: no burst for jitter to pile up, 25 a second at most. */
export const MIN_SPACING_MS = 40;
/** At most 27 frames in any 1 250 ms and 270 in any 65 000 ms: the gateway's 30 and 300 with slack for jitter. */
export const SHORT_WINDOW_MS = 1_250;
export const MAX_IN_SHORT_WINDOW = 27;
export const LONG_WINDOW_MS = 65_000;
export const MAX_IN_LONG_WINDOW = 270;
/** One slot per 10 s of the long window is kept for the client `ping` (9.1); every other frame shares the rest. */
export const PING_RESERVE = 7;
/** How long a frame that `send` threw on waits for the next try, at most: any `enqueue` retries it at once. */
export const RETRY_MS = 1_000;
/** 23 3.6: a `sub` or `unsub` never carries more topics than this, whatever `welcome.limits` says. */
export const MAX_TOPICS_PER_FRAME = 50;

export type NonEmpty<T> = [T, ...T[]];

/** Splits a topic list into frames of at most `welcome.limits.max_topics_per_request` (and 50). */
export function chunkTopics<T>(list: readonly T[], maxPerRequest: number): NonEmpty<T>[] {
  const size = Math.min(MAX_TOPICS_PER_FRAME, Math.max(1, Math.floor(maxPerRequest) || 1));
  const chunks: NonEmpty<T>[] = [];
  for (const [index, topic] of list.entries()) {
    const chunk = chunks[chunks.length - 1];
    if (chunk !== undefined && index % size !== 0) chunk.push(topic);
    else chunks.push([topic]);
  }
  return chunks;
}

export interface OutboundPacerOptions {
  /**
   * Writes one frame to the socket. Queued frames arrive in order, from a microtask or a timer; an
   * exempt `pong` is written synchronously from `enqueue`, so this can also run inside the caller's
   * own stack. A throw leaves the frame queued and uncounted, to be retried.
   */
  readonly send: (frame: ClientFrame) => void;
  /** Told of each throw from `send`, with the frame it was sending. */
  readonly onError?: ((error: unknown, frame: ClientFrame) => void) | undefined;
  /** The clock and timers it runs on; defaults to the platform's. */
  readonly timers?: Partial<Timers> | undefined;
}

export interface OutboundPacer {
  /**
   * Queues `frame` to leave at the next microtask checkpoint, or when the limits allow. A `ctl`
   * merges into a waiting one for its `ch` and the merged frame carries the newest `id`: the
   * superseded ids are never sent, so no reply is due for them. `false` means refused, which only
   * an empty `ctl` is (13.6: `minProperties: 1`; the generated `CtlPayload` admits `{}`, a gap for #572).
   */
  enqueue(frame: ClientFrame): boolean;
  /** `auth_ok` arrived: from here on a `pong` is sent at once and no longer counts (8.5). */
  markAuthenticated(): void;
  /** A new connection starts from nothing: drops the queue, the windows and the exemption. */
  reset(): void;
  /** Frames waiting for budget. */
  readonly size: number;
}

/** A `ctl` merges only into the last waiting frame that names its `ch`, so it never crosses a `sub`, `unsub` or `resync` of it. */
const names = (frame: ClientFrame, ch: string): boolean =>
  frame.t === "sub"
    ? frame.p.topics.some((topic) => topic.ch === ch)
    : frame.t === "unsub"
      ? frame.p.topics.includes(ch)
      : frame.t === "resync" && frame.ch === ch;

/** JSON drops `undefined` and turns a non-finite number into `null`: neither is a value, so a payload of them is an empty `ctl`. */
const definedOnly = (p: CtlPayload): CtlPayload =>
  // cast: the entries came from a CtlPayload; nothing may be left of them, and `enqueue` refuses that
  Object.fromEntries(
    Object.entries(p).filter(
      ([, value]) => value !== undefined && !(typeof value === "number" && !Number.isFinite(value)),
    ),
  ) as CtlPayload;

export function createOutboundPacer(options: OutboundPacerOptions): OutboundPacer {
  const timers = { ...platformTimers, ...options.timers };
  const queue: ClientFrame[] = [];
  const sentAt: number[] = []; // counted frames of the last long window, oldest first
  let authenticated = false;
  let flushQueued = false;
  let timer: unknown;
  let epoch = 0; // bumped by `reset()`, so a `send` or `onError` that resets is not undone by its caller

  /** Milliseconds until one more frame fits every limit; 0 means now. */
  function waitMs(at: number, ping: boolean): number {
    sentAt.forEach((stamp, i) => {
      if (stamp > at) sentAt[i] = at; // a clock that stepped back left it in the future: count it as now
    });
    const live = sentAt.findIndex((stamp) => at - stamp < LONG_WINDOW_MS);
    sentAt.splice(0, live === -1 ? sentAt.length : live);
    // A window is full while its k-th newest stamp is still inside it (a stamp leaves when a full window old).
    const nth = (k: number) => sentAt[sentAt.length - k] ?? -Infinity;
    return Math.max(
      0,
      nth(1) + MIN_SPACING_MS - at,
      nth(MAX_IN_SHORT_WINDOW) + SHORT_WINDOW_MS - at,
      nth(MAX_IN_LONG_WINDOW - (ping ? 0 : PING_RESERVE)) + LONG_WINDOW_MS - at,
    );
  }

  function arm(ms: number): void {
    timer = timers.setTimeout(drain, ms);
  }

  /** Never clears a handle that was not set: a strict worker `clearTimeout` throws on one. */
  function disarm(): void {
    if (timer !== undefined) timers.clearTimeout(timer);
    timer = undefined;
  }

  /** Writes `frame`; `false` if `send` threw, which goes to `onError`. */
  function emit(frame: ClientFrame): boolean {
    try {
      options.send(frame);
      return true;
    } catch (error) {
      try {
        options.onError?.(error, frame);
      } catch {
        // a faulty handler must not wedge the queue: the retry timer is armed by the caller
      }
      return false;
    }
  }

  /** Runs from a microtask or a timer, never from `send`, so it is never re-entered. */
  function drain(): void {
    disarm();
    for (let frame = queue[0]; frame !== undefined; frame = queue[0]) {
      const at = timers.now();
      const wait = waitMs(at, frame.t === "ping");
      if (wait > 0) return arm(Math.ceil(wait));
      queue.shift(); // out of the queue while `send` runs, so a `send` that enqueues sees a whole one
      const connection = epoch;
      const sent = emit(frame);
      if (connection !== epoch) return; // `send` or `onError` reset the pacer: this frame is the old connection's
      if (!sent) {
        queue.unshift(frame); // not sent, so not counted: it goes first on the next try
        return arm(RETRY_MS);
      }
      sentAt.push(at);
    }
  }

  /** The waiting `ctl` for `ch` that a new one may merge into, or -1. */
  function mergeTarget(ch: string): number {
    for (let i = queue.length - 1; i >= 0; i -= 1) {
      const waiting = queue[i];
      if (waiting?.t === "ctl" && waiting.ch === ch) return i;
      if (waiting !== undefined && names(waiting, ch)) return -1;
    }
    return -1;
  }

  function enqueue(frame: ClientFrame): boolean {
    if (authenticated && frame.t === "pong") {
      emit(frame); // exempt, so it neither waits behind the queue nor spends budget (C6)
      return true;
    }
    if (frame.t === "ctl") {
      const p = definedOnly(frame.p);
      if (Object.keys(p).length === 0) return false;
      const at = mergeTarget(frame.ch);
      const prior = queue[at];
      queue[at === -1 ? queue.length : at] = ctl(frame.id, frame.ch, {
        ...(prior?.t === "ctl" ? prior.p : {}),
        ...p,
      });
    } else if (frame.t === "ping") {
      queue.unshift(frame);
    } else {
      queue.push(frame);
    }
    if (!flushQueued) {
      flushQueued = true;
      timers.queueMicrotask(() => {
        flushQueued = false;
        drain();
      });
    }
    return true;
  }

  return {
    enqueue,
    markAuthenticated: () => {
      authenticated = true;
    },
    reset: () => {
      epoch += 1;
      queue.length = 0;
      sentAt.length = 0;
      authenticated = false;
      disarm();
    },
    get size() {
      return queue.length;
    },
  };
}
