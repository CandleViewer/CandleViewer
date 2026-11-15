// E13-S01 (#423) S1: a seeded, reproducible stream for the property tests (C-13.7). `apps/web` has no
// fast-check and takes no new dependency for tests (BQ-05 rider, ruling 6652282467), so properties
// run a fixed-seed mulberry32 loop and log the seed on failure (`withSeed`).
export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** An integer in `[low, high]`. */
export const int = (next: () => number, low: number, high: number): number =>
  low + Math.floor(next() * (high - low + 1));

export const SEEDS = [1, 7, 42, 1337, 20261104];

/** Runs one seeded property; a failure logs its seed and rethrows with the seed in the message. */
export function withSeed(seed: number, body: (next: () => number) => void): void {
  try {
    body(rng(seed));
  } catch (error) {
    console.error(`property failed with seed ${seed}`);
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`[seed ${seed}] ${message}`, { cause: error });
  }
}
