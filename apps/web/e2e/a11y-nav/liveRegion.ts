/**
 * The polite-region coalescing budget of 05-accessibility-standard.md s6.2: at most one update per 2 s per
 * field, always the latest value. `fields` is how many ambient fields write (best bid/ask, mark, P&L: 1 to 5);
 * the +1 is the write that opens the window.
 */
export const AMBIENT_CADENCE_MS = 2_000;

export function politeBudget(elapsedMs: number, fields = 1): number {
  return fields * (Math.ceil(elapsedMs / AMBIENT_CADENCE_MS) + 1);
}
