// E10-Q04 PR-4 (#303, AC5; BQ-Q04-09 ruled A): `palette_filter_ms` at component level. CMP-059's
// filter (fuzzyRank) over 2 000 synthetic command labels, one call per keystroke of 100 typed
// keystrokes, p95 within 16 ms (one frame, SCR-012). SCR-012 has no host until E15, which
// re-measures on the real precomputed index. The perf project: calibrated, retry 2, no coverage.
import { budget, why } from "@candleviewer/config/perf-calibration";
import { describe, expect, it } from "vitest";
import { fuzzyRank } from "../src/components/internal/fuzzy.js";

const VERBS = ["Open", "Close", "Toggle", "Show", "Hide", "Go to", "Reset", "Flatten"];
const NOUNS = ["chart", "footprint", "DOM ladder", "order ticket", "journal", "rule", "alert"];
const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT"];

/** 2 000 distinct labels, deterministic (no RNG): verb, noun, symbol and an index. */
const LABELS = Array.from({ length: 2_000 }, (_, i) => {
  const verb = VERBS[i % VERBS.length] ?? "";
  const noun = NOUNS[Math.floor(i / VERBS.length) % NOUNS.length] ?? "";
  return `${verb} ${noun}: ${SYMBOLS[i % SYMBOLS.length] ?? ""} ${i}`;
});

/** Ten typed queries of ten characters: each prefix is one keystroke, 100 in all. */
const QUERIES = [
  "open chart",
  "flatten bt",
  "toggle dom",
  "go to jour",
  "show alert",
  "reset rule",
  "hide order",
  "close foot",
  "open ethus",
  "go to link",
];
const KEYSTROKES = QUERIES.flatMap((q) => Array.from(q, (_, i) => q.slice(0, i + 1)));

/** Nearest rank (as the shell report): the value at rank ceil(p/100 x n). */
const nearestRank = (sorted: readonly number[], p: number): number =>
  sorted[Math.max(0, Math.ceil((p / 100) * sorted.length) - 1)] ?? Number.NaN;

describe("palette_filter_ms: CMP-059's filter, 2 000 labels (E10-Q04 AC5, component level)", () => {
  it("types 100 keystrokes over 2 000 labels", () => {
    expect([LABELS.length, new Set(LABELS).size, KEYSTROKES.length]).toEqual([2_000, 2_000, 100]);
    expect(fuzzyRank(LABELS, "open chart", (l) => l).length).toBeGreaterThan(0);
  });

  it("filters each keystroke within 16 ms at p95", () => {
    for (const q of QUERIES) fuzzyRank(LABELS, q, (l) => l); // warm-up, untimed
    const times = KEYSTROKES.map((query) => {
      const start = performance.now();
      fuzzyRank(LABELS, query, (l) => l);
      return performance.now() - start;
    }).sort((a, b) => a - b);
    const p50 = nearestRank(times, 50);
    const p95 = nearestRank(times, 95);
    console.info(`palette_filter_ms n=100 p50=${p50.toFixed(3)} p95=${p95.toFixed(3)}`);
    expect(p95, why(p95, 16)).toBeLessThanOrEqual(budget(16));
  });
});
