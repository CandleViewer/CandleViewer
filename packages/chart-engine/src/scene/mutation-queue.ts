// The data-mutation queue (E11-S01, 26 §3.2 rule 3): opaque thunks in a ring, applied in order
// under a per-frame clamp; what does not fit waits for the next frame and is never dropped.
import type { FrameClock } from "./frame-clock.js";

export type Mutation = () => void;

export class MutationQueue {
  private items: (Mutation | undefined)[];
  private head = 0;
  length = 0; // queued, not yet applied; only this class writes it
  grown = 0; // ring doublings: an allocation, so the zero-allocation tests read it

  constructor(capacity = 256) {
    this.items = new Array<Mutation | undefined>(Math.max(1, capacity)).fill(undefined);
  }

  push(mutation: Mutation): void {
    if (this.length === this.items.length) this.grow();
    this.items[(this.head + this.length) % this.items.length] = mutation;
    this.length += 1;
  }

  /**
   * Applies mutations in order while less than `clampMs` has passed since the call (BQ-37): one is
   * always applied, and the clock is read before each, so an opaque thunk is never cut short.
   * Returns how many wait for the next frame.
   */
  drain(clock: FrameClock, clampMs: number): number {
    const start = clock.now();
    for (let n = 0; this.length > 0 && (n === 0 || clock.now() - start < clampMs); n += 1) {
      const mutation = this.items[this.head] as Mutation; // length > 0
      this.items[this.head] = undefined;
      this.head = (this.head + 1) % this.items.length;
      this.length -= 1;
      mutation();
    }
    return this.length;
  }

  private grow(): void {
    const next = new Array<Mutation | undefined>(this.items.length * 2).fill(undefined);
    for (let i = 0; i < this.length; i += 1) {
      next[i] = this.items[(this.head + i) % this.items.length];
    }
    this.items = next;
    this.head = 0;
    this.grown += 1;
  }
}
