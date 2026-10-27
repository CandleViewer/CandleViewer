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

/** Where an open list starts: the chosen option when it is reachable, else the first reachable one. */
export function openIndex<T>(items: readonly T[], chosen: number, skip: Skip<T>): number {
  const item = items[chosen];
  return item !== undefined && !skip(item) ? chosen : firstIndex(items, skip);
}
