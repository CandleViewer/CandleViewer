/**
 * The client's share of the `ticker` rebuild budget (E08-D07 D6, §4.6; `23-ws-protocol.md` §7.5, §8.5). Every `sub` of
 * the batched `ticker` that starts a subscription draws one unit of the topic's 5 per sliding 60 s, resyncs included,
 * so the client starts a change (a window move, a list switch, an add that changes the window, a re-open) only while
 * fewer than 4 draws fall in the last 60 s, keeping one unit for a resync, which is never held; changes go at least
 * 2 s apart. A `sub` the budget refuses (`resync_rate_limited`) backs off 5 s, twice as long after each further
 * refusal, up to 60 s, never in a loop. Pure: the caller passes the time.
 */

export const REBUILD_WINDOW_MS = 60_000;
/** The client starts a change only while fewer than this many draws fall in the window. */
export const CLIENT_DRAWS = 4;
export const CHANGE_SPACING_MS = 2_000;
export const BACKOFF_FIRST_MS = 5_000;
export const BACKOFF_MAX_MS = 60_000;

export interface RebuildShare {
  /** A draw (a `sub` that starts the subscription, the client's or a reconnect's restore) at `now`. */
  record(now: number): void;
  /** The draws that still count at `now`: those after `now − 60 s`. */
  drawsIn(now: number): number;
  /** The earliest time, from `now`, a change may start. */
  nextStart(now: number): number;
}

export function createRebuildShare(): RebuildShare {
  /** The draws still in the window, oldest first; never more than the window can hold. */
  let draws: number[] = [];
  const prune = (now: number): void => {
    draws = draws.filter((at) => at > now - REBUILD_WINDOW_MS);
  };
  return {
    record(now) {
      prune(now);
      draws.push(now);
    },
    drawsIn(now) {
      prune(now);
      return draws.length;
    },
    nextStart(now) {
      prune(now);
      const last = draws.at(-1);
      const spaced = last === undefined ? now : last + CHANGE_SPACING_MS;
      // With CLIENT_DRAWS in the window, the next may start once the oldest of the last CLIENT_DRAWS leaves it.
      const oldest = draws.length >= CLIENT_DRAWS ? draws[draws.length - CLIENT_DRAWS] : undefined;
      const freed = oldest === undefined ? now : oldest + REBUILD_WINDOW_MS;
      return Math.max(now, spaced, freed);
    },
  };
}

export interface Backoff {
  /** The wait before the retry that follows this refusal: 5 s, then doubling, up to 60 s. */
  next(): number;
  /** A subscription that lands starts the ladder again. */
  reset(): void;
}

export function createBackoff(): Backoff {
  let refusals = 0;
  return {
    next() {
      const wait = Math.min(BACKOFF_FIRST_MS * 2 ** refusals, BACKOFF_MAX_MS);
      refusals = Math.min(refusals + 1, 16);
      return wait;
    },
    reset() {
      refusals = 0;
    },
  };
}
