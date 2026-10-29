/**
 * Detects "connected but unreachable" (tailnet down) within 5 s by tracking
 * actual request failures, not `navigator.onLine` alone (SCR-159 performance
 * note). `navigator.onLine` is used only as a fast-path optimistic signal;
 * the authoritative signal is a run of consecutive failed requests within
 * the reachability window.
 */

export type ReachabilityCause = "offline" | "tailnet_unreachable" | "backend_unreachable";

export interface ReachabilityState {
  readonly reachable: boolean;
  readonly cause: ReachabilityCause | null;
}

/** The shell store's copy (SCR-159, #306): the verdict and, while unreachable, the next probe. */
export interface Reachability extends ReachabilityState {
  /** Epoch ms of the next probe while unreachable ("Retrying in ~N s"); `null` while reachable. */
  readonly retryAtMs: number | null;
  /** A probe is running while unreachable (the page's busy state); always `false` while reachable. */
  readonly probing: boolean;
}

export const REACHABLE: Reachability = Object.freeze({
  reachable: true,
  cause: null,
  retryAtMs: null,
  probing: false,
});

/** Upper bound on how long the UI may show a transient state before this
 * tracker must have committed to an explicit reachable/unreachable verdict
 * (SCR-159 performance note). Exported for the contract test asserting the
 * detection budget. */
export const REACHABILITY_WINDOW_MS = 5_000;

export class ReachabilityTracker {
  private state: ReachabilityState = { reachable: true, cause: null };
  private readonly listeners = new Set<(state: ReachabilityState) => void>();

  get current(): ReachabilityState {
    return this.state;
  }

  subscribe(listener: (state: ReachabilityState) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** Call on every bootstrap/WS request outcome. A single failure is enough
   * to flag the unreachable state — actual request failure, not only
   * `navigator.onLine`, is the authoritative signal. */
  recordSuccess(): void {
    this.setState({ reachable: true, cause: null });
  }

  recordFailure(): void {
    this.setState({ reachable: false, cause: this.classifyCause() });
  }

  private classifyCause(): ReachabilityCause {
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      return "offline";
    }
    return "tailnet_unreachable";
  }

  private setState(next: ReachabilityState): void {
    if (next.reachable === this.state.reachable && next.cause === this.state.cause) return;
    this.state = next;
    for (const listener of this.listeners) listener(next);
  }
}
