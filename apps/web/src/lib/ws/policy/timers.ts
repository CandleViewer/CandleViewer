// E17-T04 S3: the clock and timers a policy runs on. Injected so a test, or the worker, drives them
// (the engine in S4 takes the same set). The defaults look the platform up at call time, so fake
// timers installed after a policy is built still apply.
export interface Timers {
  /**
   * Monotonic milliseconds (the platform's `performance.now` is; an injected, skew-corrected clock may
   * not be). A policy that sees it step back stalls for one of its windows at most and never releases early.
   */
  readonly now: () => number;
  /** Handles are opaque: only the `clearTimeout` of the same set sees them. */
  readonly setTimeout: (callback: () => void, ms: number) => unknown;
  /** Only ever called with a handle this set's `setTimeout` returned, never with `undefined`. */
  readonly clearTimeout: (handle: unknown) => void;
  /** MUST defer: a synchronous one would re-enter a policy's `drain` from inside its own `send`. */
  readonly queueMicrotask: (callback: () => void) => void;
}

export const platformTimers: Timers = {
  now: () => performance.now(),
  setTimeout: (callback, ms) => setTimeout(callback, ms),
  // the handle always comes from the `setTimeout` above
  clearTimeout: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
  queueMicrotask: (callback) => queueMicrotask(callback),
};
