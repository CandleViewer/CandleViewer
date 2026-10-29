/**
 * The in-house fuzzy scorer for CMP-059 (and CMP-213 later): pure, no dependency. A query matches a label when
 * its characters (whitespace dropped) appear in order, case- and accent-insensitively, compared one code point at
 * a time. Among the alignments the best-scoring one wins: a word start and a run of contiguous characters score
 * more, a gap costs a little. Ranking keeps the input order between equal scores (stable).
 */

/** A matched span of the label, in UTF-16 offsets: `[start, end)`, so `label.slice(start, end)` is the text. */
export type MatchRange = readonly [start: number, end: number];

export interface FuzzyMatch {
  readonly score: number;
  readonly ranges: readonly MatchRange[];
}

export interface Ranked<T> {
  readonly item: T;
  readonly match: FuzzyMatch;
  /** The item's position in the input: the tie order. */
  readonly index: number;
}

/** Every matched character. */
const BASE = 1;
/** A match at the label's start, after a separator, or at a lower-to-upper case change. */
const WORD_START = 8;
/** A match on the label's very first character, on top of the word start. */
const LEADING = 2;
/** A match right after the previous matched character: a run scores as a word start does. */
const CONTIGUOUS = 8;
/** A jump over one or more label characters between two matches. */
const GAP = 2;

const COMBINING = /\p{M}/gu;
const SEPARATOR = /[\s\p{P}\p{S}]/u;
const SPACE = /\s/u;
const UPPER = /\p{Lu}/u;
const LOWER = /\p{Ll}/u;

/** One code point, folded: compatibility-decomposed, combining marks dropped, lower-cased ("É" → "e"). */
export const fold = (char: string): string =>
  char.normalize("NFKD").replace(COMBINING, "").toLowerCase();

interface Char {
  readonly folded: string;
  readonly at: number;
  readonly end: number;
  readonly wordStart: boolean;
}

function chars(label: string): Char[] {
  const out: Char[] = [];
  let at = 0;
  let prev: string | undefined;
  for (const char of label) {
    const wordStart =
      prev === undefined ||
      (SEPARATOR.test(prev) && !SEPARATOR.test(char)) ||
      (LOWER.test(prev) && UPPER.test(char));
    out.push({ folded: fold(char), at, end: at + char.length, wordStart });
    at += char.length;
    prev = char;
  }
  return out;
}

/** The best alignment of `query` in `label`, or `null` when its characters do not all appear in order. */
export function fuzzyMatch(label: string, query: string): FuzzyMatch | null {
  const needle = [...query]
    .filter((c) => !SPACE.test(c))
    .map(fold)
    .filter((c) => c !== "");
  if (needle.length === 0) return { score: 0, ranges: [] };
  const hay = chars(label);
  const n = hay.length;
  const m = needle.length;
  if (m > n) return null;
  // score[j][i]: the best total with query char j matched at label char i (-Infinity: impossible).
  // from[j][i]: the label position of query char j - 1 in that alignment.
  const score: Float64Array[] = [];
  const from: Int32Array[] = [];
  for (let j = 0; j < m; j += 1) {
    const row = new Float64Array(n).fill(-Infinity);
    const back = new Int32Array(n).fill(-1);
    const prev = score[j - 1];
    // The best of the previous row strictly before i - 1 (a gap), carried left to right.
    let best = -Infinity;
    let bestAt = -1;
    for (let i = j; i < n; i += 1) {
      if (prev !== undefined && i >= 2) {
        const candidate = prev[i - 2] ?? -Infinity;
        if (candidate > best) {
          best = candidate;
          bestAt = i - 2;
        }
      }
      const c = hay[i] as Char;
      if (c.folded !== needle[j]) continue;
      const own = BASE + (c.wordStart ? WORD_START : 0) + (i === 0 ? LEADING : 0);
      if (prev === undefined) {
        row[i] = own;
        continue;
      }
      const adjacent = (prev[i - 1] ?? -Infinity) + CONTIGUOUS;
      const jumped = best - GAP;
      if (adjacent === -Infinity && jumped === -Infinity) continue;
      if (adjacent >= jumped) {
        row[i] = own + adjacent;
        back[i] = i - 1;
      } else {
        row[i] = own + jumped;
        back[i] = bestAt;
      }
    }
    score.push(row);
    from.push(back);
  }
  const last = score[m - 1] as Float64Array;
  let end = -1;
  for (let i = 0; i < n; i += 1) if (end === -1 || (last[i] ?? 0) > (last[end] ?? 0)) end = i;
  if (end === -1 || last[end] === -Infinity) return null;
  // Walk back through the alignment, merging neighbours into ranges.
  const positions: number[] = [];
  for (let j = m - 1, i = end; j >= 0; j -= 1) {
    positions.push(i);
    i = (from[j] as Int32Array)[i] ?? -1;
  }
  positions.reverse();
  const ranges: [number, number][] = [];
  for (const i of positions) {
    const c = hay[i] as Char;
    const tail = ranges[ranges.length - 1];
    if (tail !== undefined && tail[1] === c.at) tail[1] = c.end;
    else ranges.push([c.at, c.end]);
  }
  return { score: last[end] ?? 0, ranges };
}

/** The items that match, best first; equal scores keep the input order. */
export function fuzzyRank<T>(
  items: readonly T[],
  query: string,
  label: (item: T) => string,
): Ranked<T>[] {
  const out: Ranked<T>[] = [];
  items.forEach((item, index) => {
    const match = fuzzyMatch(label(item), query);
    if (match !== null) out.push({ item, match, index });
  });
  return out.sort((a, b) => b.match.score - a.match.score || a.index - b.index);
}
