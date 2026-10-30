// The scheduler's injected clock (E11-S01, BQ-36): `src/scene` reads no global clock and calls no
// rAF. The worker or host binds the real one (PR3); tests use `test/scene/test-clock.ts`.

export type FrameCallback = (t: number) => void;

export interface FrameClock {
  /** Milliseconds on a monotonic clock, the same one the frame callback's `t` is on. */
  now(): number;
  /** Schedules `cb` for the next frame (rAF); returns a handle for `cancel`. */
  requestFrame(cb: FrameCallback): number;
  cancel(handle: number): void;
}
