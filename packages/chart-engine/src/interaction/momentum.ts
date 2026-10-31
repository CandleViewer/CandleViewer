// Momentum (E11-S04 PR 1, 26 §3.5, E11-D06 D1 to D5, README BQ-103): one preallocated
// integrator per chart, stepped by the frame scheduler with the elapsed ms (26 §3.2 rule 2). The
// decay is integrated exactly, `x += v·τ(1 − e^(−dt/τ))`, and the stop frame applies the
// remainder `v·τ`, so the resting position is `x₀ + v₀τ` whatever the frame rate or drops.
import type { Animation } from "../scene/frame-scheduler.js";

/**
 * PROPOSED (E11-D06 O-1): the owner's feel run may retune any of these; nothing else holds them.
 * τ and the stop speed are the ticket's; the rest are D06 D2 to D5.
 */
export const MOMENTUM = {
  /** Decay constant, ms: `v *= exp(-dt / τ)`. */
  tauMs: 120,
  /** Below this |v| (px/ms) the glide ends, applying the remainder `v·τ`. */
  stopPxPerMs: 0.02,
  /** The release velocity's averaging window, ms. */
  ewmaMs: 50,
  /** No coast when the pointer rested this long before release, ms. */
  stillMs: 100,
  /** No coast below this release speed, px/ms. */
  minPxPerMs: 0.3,
  /** |v₀| is capped at this many plot widths per τ. */
  capWidths: 1.5,
} as const;

export class Momentum implements Animation {
  /** px/ms; 0 at rest. */
  v = 0;
  active = false;
  /** In the scheduler's animation list (it is swap-removed the step after it stops). */
  registered = false;
  /** `engine.momentum.cancelled` */
  cancelled = 0;

  /** `pan` applies `dx` px and says whether the view moved (false at the clamp: no bounce). */
  constructor(private readonly pan: (dxPx: number) => boolean) {}

  /** A release at `v0` px/ms over a plot `width` px wide; true when a glide starts. */
  start(v0: number, width: number): boolean {
    if (!(Math.abs(v0) >= MOMENTUM.minPxPerMs) || !(width > 0)) return false;
    const cap = (MOMENTUM.capWidths * width) / MOMENTUM.tauMs;
    this.v = Math.min(cap, Math.max(-cap, v0));
    this.active = true;
    return true;
  }

  /** The one cancel entry point (pointer-down, wheel, key, setViewport, sync, resize, loss). */
  cancel(): void {
    if (!this.active) return;
    this.active = false;
    this.v = 0;
    this.cancelled += 1;
  }

  step(dtMs: number): boolean {
    if (!this.active) return (this.registered = false);
    if (!(dtMs > 0)) return true; // the first frame after a park carries no time
    const k = Math.exp(-dtMs / MOMENTUM.tauMs);
    let dx = this.v * MOMENTUM.tauMs * (1 - k);
    this.v *= k;
    const done = Math.abs(this.v) < MOMENTUM.stopPxPerMs;
    if (done) dx += this.v * MOMENTUM.tauMs;
    if (this.pan(dx) && !done) return true;
    this.active = false;
    this.v = 0;
    return (this.registered = false);
  }
}
