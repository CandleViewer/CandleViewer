/**
 * Index arithmetic for a single-select list (CMP-009; the seam for slice 11's type-ahead and option looks).
 * Every function takes `skip`, the rule for an option the arrows pass over, so a later option look changes
 * one predicate and not the key handler. An index of -1 means "no active option".
 */
export type Skip<T> = (item: T) => boolean;

/** The first index at or after `from` (stepping `dir`) that is not skipped, or -1 when none remains. No wrap. */
function scan<T>(items: readonly T[], from: number, dir: 1 | -1, skip: Skip<T>): number {
  for (let i = from; i >= 0 && i < items.length; i += dir) {
    if (!skip(items[i] as T)) return i;
  }
  return -1;
}

export const firstIndex = <T>(items: readonly T[], skip: Skip<T>): number =>
  scan(items, 0, 1, skip);

export const lastIndex = <T>(items: readonly T[], skip: Skip<T>): number =>
  scan(items, items.length - 1, -1, skip);

/** One step from `from`: the next reachable option, or `from` itself at either end (no wrap). */
export function stepIndex<T>(
  items: readonly T[],
  from: number,
  dir: 1 | -1,
  skip: Skip<T>,
): number {
  const found = scan(items, from + dir, dir, skip);
  return found === -1 ? from : found;
}

/** Up to `count` reachable steps from `from`; it stops at the end and never wraps. */
export function pageIndex<T>(
  items: readonly T[],
  from: number,
  dir: 1 | -1,
  count: number,
  skip: Skip<T>,
): number {
  let at = from;
  for (let i = 0; i < count; i += 1) {
    const next = stepIndex(items, at, dir, skip);
    if (next === at) break;
    at = next;
  }
  return at;
}

/** Where an open list starts: the chosen option when it is reachable, else the first reachable one. */
export function openIndex<T>(items: readonly T[], chosen: number, skip: Skip<T>): number {
  const item = items[chosen];
  return item !== undefined && !skip(item) ? chosen : firstIndex(items, skip);
}

/** Type-ahead (APG): a typed string lives this long (ms) after its last key. */
export const TYPE_AHEAD_MS = 500;

export interface Typed {
  readonly text: string;
  readonly at: number;
}

/** The string after one more key: it restarts when the last key is older than the window. `now` is injected. */
export const extendTyped = (prev: Typed, char: string, now: number): Typed => ({
  text: now - prev.at > TYPE_AHEAD_MS ? char : prev.text + char,
  at: now,
});

/**
 * The next option whose label starts with `text` (case-insensitive), wrapping. A string of one repeated letter
 * cycles: it starts after `from`. Any other string starts at `from` itself, so "su" stays on "Sub-account 1".
 * Skipped options never match. Returns -1 for no match.
 */
export function matchIndex<T>(
  items: readonly T[],
  from: number,
  text: string,
  label: (item: T) => string,
  skip: Skip<T>,
): number {
  const needle = text.toLowerCase();
  const cycle = [...needle].every((c) => c === needle[0]);
  const begin = cycle ? from + 1 : Math.max(from, 0);
  for (let step = 0; step < items.length; step += 1) {
    const i = (begin + step) % items.length;
    const item = items[i] as T;
    // A repeated letter matches on that one letter, so "aa" keeps cycling through the "a" labels.
    if (
      !skip(item) &&
      label(item)
        .toLowerCase()
        .startsWith(cycle ? needle.slice(0, 1) : needle)
    ) {
      return i;
    }
  }
  return -1;
}
