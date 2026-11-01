// Pane shares (E11-S09, README BQ-3, the BQ-11 default pending its ruling): the one function that
// turns the panes' weights into the shares the layout tiles and the `layout` message reports. The
// worker is their single owner. Shares sum to exactly 1 when added left to right: each pane but
// the last gets `weight / total`, and the last takes the remainder, `1 - (sum of the others)`
// (x + (1 - x) rounds to 1 for every x in [0, 1]). DOM-free; writes into the caller's array.

/** Weights below this count as this, so no share is 0 or NaN (the protocol bounds them to (0, 1]). */
const MIN_WEIGHT = 1e-9;

/**
 * Writes the normalised shares of `weights[0, n)` into `out[0, n)`: every share > 0, in order, and
 * `out[0] + ... + out[n - 1] === 1` exactly. An empty list writes nothing.
 */
export function normaliseShares(weights: ArrayLike<number>, n: number, out: number[]): void {
  let total = 0;
  for (let i = 0; i < n; i += 1) total += Math.max(MIN_WEIGHT, weights[i] ?? 0);
  let acc = 0;
  for (let i = 0; i < n - 1; i += 1) {
    const s = Math.max(MIN_WEIGHT, weights[i] ?? 0) / total;
    out[i] = s;
    acc += s;
  }
  if (n > 0) out[n - 1] = 1 - acc;
}

/** BQ-2: a new pane's weight when none is given: the mean of the others (an equal share), 1 alone. */
export function defaultWeight(weights: ArrayLike<number>, n: number): number {
  if (n === 0) return 1;
  let total = 0;
  for (let i = 0; i < n; i += 1) total += weights[i] ?? 0;
  return Math.min(1, Math.max(MIN_WEIGHT, total / n));
}
