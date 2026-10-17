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
   * (`"deferred"`). A request that finds one waiting replaces it: the latest `send` runs, once.
   * The budget is per `ch`: a `resync` frame names no replay session, so the gateway cannot tell
   * the streams of one `ch` apart either.
   */
  request(ch: string, send: () => void): "sent" | "deferred";
  /** The topic recovered by itself (a `snap` arrived): drops the waiting request, keeps the budget. */
  cancel(ch: string): void;
  /** The subscription is gone, and with it the gateway's window for it. */
  forget(ch: string): void;
  /** A new connection or a stopped engine: nothing is owed and nothing waits. */
  reset(): void;
  /** Topics with a request waiting. */
  readonly waiting: number;
}

export function createResyncGuard(options: ResyncGuardOptions = {}): ResyncGuard {
  const now = options.now ?? (() => performance.now());
  const setTimer = options.setTimer ?? ((fn, ms) => setTimeout(fn, ms));
  const clearTimer =
    options.clearTimer ?? ((handle) => clearTimeout(handle as ReturnType<typeof setTimeout>));
  const horizon = RESYNC_WINDOW_MS + RESYNC_MARGIN_MS;
  const stamps = new Map<string, number[]>(); // admitted resyncs per topic, oldest first
  const queued = new Map<string, { send: () => void; timer: unknown }>();

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

  function defer(ch: string, send: () => void, wait: number): void {
    queued.set(ch, { send, timer: setTimer(() => fire(ch), wait) });
  }

  function fire(ch: string): void {
    const entry = queued.get(ch);
    if (entry === undefined) return;
    queued.delete(ch);
    const wait = admitOrWait(ch, now());
    // A timer can fire a little early against this clock; the request waits again, never sends early.
    if (wait > 0) defer(ch, entry.send, wait);
    else entry.send();
  }

  function cancel(ch: string): void {
    const entry = queued.get(ch);
    if (entry === undefined) return;
    clearTimer(entry.timer);
    queued.delete(ch);
  }

  return {
    request(ch, send) {
      const entry = queued.get(ch);
      if (entry !== undefined) {
        entry.send = send;
        return "deferred";
      }
      const wait = admitOrWait(ch, now());
      if (wait > 0) {
        defer(ch, send, wait);
        return "deferred";
      }
      send();
      return "sent";
    },
    cancel,
    forget(ch) {
      cancel(ch);
      stamps.delete(ch);
    },
    reset() {
      for (const entry of queued.values()) clearTimer(entry.timer);
      queued.clear();
      stamps.clear();
    },
    get waiting() {
      return queued.size;
    },
  };
}
