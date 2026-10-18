// E17-T04 S2 (23 7.5): the gateway answers a sixth `resync` for one topic inside a minute with
// `resync_rate_limited` and revokes the subscription, so the client never sends it early: a request
// over budget waits for the window to reopen. The count is the gateway's (a stamp leaves once a full
// window old), widened by a margin, because the gateway stamps on receipt and transit jitter can put
// two sends a little closer together than their receipts.
export const RESYNC_LIMIT = 5;
export const RESYNC_WINDOW_MS = 60_000;
export const RESYNC_MARGIN_MS = 1_000;

export interface ResyncGuardOptions {
  /** Monotonic milliseconds. Defaults to `performance.now`. */
  readonly now?: (() => number) | undefined;
  /** Defaults to `setTimeout`; injected so a test owns the clock. */
  readonly setTimer?: ((fn: () => void, ms: number) => unknown) | undefined;
  readonly clearTimer?: ((handle: unknown) => void) | undefined;
}

export interface ResyncGuard {
  /**
   * Runs `send` now when `ch` is within budget (`"sent"`), else when the window reopens
   * (`"deferred"`). The budget is per `ch`: a `resync` frame names no replay session, so the gateway
   * cannot tell the streams of one `ch` apart either. The wait is per stream (`stream` is the key of
   * one: a live and a replay stream of one `ch` each have a request): a request that finds its own
   * stream waiting replaces it (the latest `send` runs, once, in the place the first held), and the
   * streams that wait for one `ch` are served oldest first as the window reopens.
   */
  request(ch: string, stream: string, send: () => void): "sent" | "deferred";
  /** The stream recovered by itself (a `snap` arrived) or is gone: drops its waiting request alone, keeps the budget. */
  cancel(ch: string, stream: string): void;
  /** The subscription is gone, and with it the gateway's window for it: drops every request waiting for `ch`. */
  forget(ch: string): void;
  /** A new connection or a stopped engine: nothing is owed and nothing waits. */
  reset(): void;
  /** Streams with a request waiting. */
  readonly waiting: number;
}

/** The streams of one `ch` that wait for its budget, oldest first, and the one timer that wakes them. */
interface Queue {
  readonly entries: { readonly stream: string; send: () => void }[];
  timer: unknown;
}

export function createResyncGuard(options: ResyncGuardOptions = {}): ResyncGuard {
  const now = options.now ?? (() => performance.now());
  const setTimer = options.setTimer ?? ((fn, ms) => setTimeout(fn, ms));
  const clearTimer =
    options.clearTimer ?? ((handle) => clearTimeout(handle as ReturnType<typeof setTimeout>));
  const horizon = RESYNC_WINDOW_MS + RESYNC_MARGIN_MS;
  const stamps = new Map<string, number[]>(); // admitted resyncs per topic, oldest first
  const queues = new Map<string, Queue>();

  /**
   * 0 when `ch` may resync now, and the resync is then counted; otherwise the milliseconds until
   * it may. The count is taken before `send` runs, so a `send` that throws cannot be retried in a loop.
   */
  function admitOrWait(ch: string, at: number): number {
    const live = (stamps.get(ch) ?? []).filter((stamp) => at - stamp < horizon);
    if (live.length >= RESYNC_LIMIT) {
      stamps.set(ch, live);
      return Math.min(...live) + horizon - at;
    }
    stamps.set(ch, [...live, at]);
    return 0;
  }

  function drop(ch: string, queue: Queue): void {
    clearTimer(queue.timer);
    queues.delete(ch);
  }

  /** Serves the streams waiting for `ch`, oldest first, as many as the budget admits. */
  function fire(ch: string): void {
    const queue = queues.get(ch);
    if (queue === undefined) return;
    let wait = 0;
    try {
      while (queue.entries.length > 0) {
        wait = admitOrWait(ch, now());
        // A timer can fire a little early against this clock; the queue then waits again, never sends early.
        if (wait > 0) break;
        queue.entries.shift()?.send();
      }
    } finally {
      // `wait` is 0 here only when a `send` threw: the request that threw is gone, the rest go on at once.
      if (queue.entries.length === 0) drop(ch, queue);
      else queue.timer = setTimer(() => fire(ch), wait);
    }
  }

  return {
    request(ch, stream, send) {
      const queue = queues.get(ch);
      if (queue !== undefined) {
        // Budget is spent, or earlier requests are owed first: this one waits its turn, behind them.
        const entry = queue.entries.find((e) => e.stream === stream);
        if (entry !== undefined) entry.send = send;
        else queue.entries.push({ stream, send });
        return "deferred";
      }
      const wait = admitOrWait(ch, now());
      if (wait > 0) {
        queues.set(ch, { entries: [{ stream, send }], timer: setTimer(() => fire(ch), wait) });
        return "deferred";
      }
      send();
      return "sent";
    },
    cancel(ch, stream) {
      const queue = queues.get(ch);
      const at = queue?.entries.findIndex((e) => e.stream === stream) ?? -1;
      if (queue === undefined || at === -1) return;
      queue.entries.splice(at, 1);
      if (queue.entries.length === 0) drop(ch, queue);
    },
    forget(ch) {
      const queue = queues.get(ch);
      if (queue !== undefined) drop(ch, queue);
      stamps.delete(ch);
    },
    reset() {
      for (const queue of queues.values()) clearTimer(queue.timer);
      queues.clear();
      stamps.clear();
    },
    get waiting() {
      let waiting = 0;
      for (const queue of queues.values()) waiting += queue.entries.length;
      return waiting;
    },
  };
}
