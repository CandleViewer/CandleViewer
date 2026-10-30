// A deterministic `FrameClock` (E11-S01, 26 §14): time moves only when a test says so, and a frame
// runs only on `tick`. It counts requests, so a test can see parking and double-scheduling.
import type { FrameCallback, FrameClock } from "../../src/scene/frame-clock.js";

export class TestClock implements FrameClock {
  t = 1000; // not 0, so a duration measured from the clock's epoch shows
  requests = 0;
  doubleRequests = 0; // a request while one is pending: the scheduler must never do this
  private pending: FrameCallback | null = null;

  now(): number {
    return this.t;
  }

  requestFrame(cb: FrameCallback): number {
    if (this.pending !== null) this.doubleRequests += 1;
    this.pending = cb;
    return (this.requests += 1); // the handle
  }

  cancel(handle: number): void {
    if (handle === this.requests) this.pending = null;
  }

  /** Moves time on without a frame: the frame work's own cost, or a dropped frame. */
  advance(ms: number): void {
    this.t += ms;
  }

  /** Moves time on by `ms`, then runs the pending frame; `false` when none was requested. */
  tick(ms = 16): boolean {
    this.t += ms;
    const cb = this.pending;
    this.pending = null;
    cb?.(this.t);
    return cb !== null;
  }
}
