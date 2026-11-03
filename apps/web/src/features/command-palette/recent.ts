/**
 * SCR-012's recency on this device (E10-S05, #5236; PROPOSED, `14` :364's `PATCH /me/preferences` has no palette leaf
 * in `22`'s `Settings`): the last five rows run, newest first, and a use count per row, per signed-in user. Modelled
 * on the keymap profile (`keymap/profile.ts`): stored under `cv.palette-recent.v1:<user id>`, kept by no one while no
 * one is signed in, and read afresh when another user signs in. It holds row ids and counts only: never the query.
 */

const STORE_KEY = "cv.palette-recent.v1";
const keyOf = (user: string): string => `${STORE_KEY}:${user}`;

/** Recent shows the last five (E10-D02 f10). */
export const RECENT_LIMIT = 5;
/** The use counts kept: the most used, so the stored record stays small. */
export const COUNT_LIMIT = 100;

export interface RecentState {
  /** Row ids, newest first, at most `RECENT_LIMIT`. */
  readonly recent: readonly string[];
  /** Runs per row id. */
  readonly counts: Readonly<Record<string, number>>;
}

export const EMPTY_RECENT: RecentState = { recent: [], counts: {} };

type Store = Pick<Storage, "getItem" | "setItem">;
const deviceStore = (): Store | null =>
  typeof window === "undefined" ? null : window.localStorage;

/** A stored record, checked: anything that is not an id list and a count map reads as empty. */
function parse(raw: string | null): RecentState {
  if (raw === null) return EMPTY_RECENT;
  const v: unknown = JSON.parse(raw);
  if (typeof v !== "object" || v === null || Array.isArray(v)) return EMPTY_RECENT;
  const { recent, counts } = v as { recent?: unknown; counts?: unknown };
  const ids = Array.isArray(recent) ? recent.filter((x): x is string => typeof x === "string") : [];
  const kept: Record<string, number> = {};
  if (typeof counts === "object" && counts !== null && !Array.isArray(counts)) {
    for (const [id, n] of Object.entries(counts)) {
      if (typeof n === "number" && Number.isInteger(n) && n > 0) kept[id] = n;
    }
  }
  return { recent: [...new Set(ids)].slice(0, RECENT_LIMIT), counts: kept };
}

/** The user's record; empty for no user, or when storage is unavailable or corrupt. */
export function readRecent(user: string | null, store: Store | null = deviceStore()): RecentState {
  if (user === null || store === null) return EMPTY_RECENT;
  try {
    return parse(store.getItem(keyOf(user)));
  } catch {
    return EMPTY_RECENT;
  }
}

/** Records one run of `id` for `user` (nothing while no one is signed in) and returns the new record. */
export function recordRun(
  user: string | null,
  id: string,
  store: Store | null = deviceStore(),
): RecentState {
  const prev = readRecent(user, store);
  const recent = [id, ...prev.recent.filter((x) => x !== id)].slice(0, RECENT_LIMIT);
  const counts = Object.fromEntries(
    Object.entries({ ...prev.counts, [id]: (prev.counts[id] ?? 0) + 1 })
      .sort(([, a], [, b]) => b - a)
      .slice(0, COUNT_LIMIT),
  );
  const next: RecentState = { recent, counts };
  if (user === null || store === null) return next;
  try {
    store.setItem(keyOf(user), JSON.stringify(next));
  } catch {
    /* storage full or unavailable: the run still happened; recency is a convenience */
  }
  return next;
}
