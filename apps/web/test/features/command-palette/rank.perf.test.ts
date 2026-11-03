import { describe, expect, it } from "vitest";
import { buildIndex } from "../../../src/features/command-palette/rank";
import {
  GROUP_ORDER,
  type PaletteRow,
  type PaletteSource,
  type SourceContext,
} from "../../../src/features/command-palette/sources";

// E10-S05 (#5236), `14` :368: SCR-012's budget is 2 000 entries at <= 16 ms. The host builds its index once per
// opening (this); the per-keystroke fuzzy score is CMP-059's own (`packages/ui` fuzzy.ts), not forked here.

const CTX: SourceContext = {
  claims: { authenticated: true, role: "owner", permissions: [] },
  bindings: new Map(),
  isValid: () => true,
  viewAs: null,
};

/** `n` synthetic rows spread over the five groups, in reverse group order, so the index has to regroup them. */
function sources(n: number): PaletteSource[] {
  return [...GROUP_ORDER].reverse().map((group, g) => {
    const rows: PaletteRow[] = [];
    for (let i = g; i < n; i += GROUP_ORDER.length)
      rows.push({
        id: `row-${String(i)}`,
        label: `Synthetic command ${String(i)} for ${group}`,
        group,
        target: { kind: "command", commandId: `row-${String(i)}` },
      });
    return { id: group, group, rows: () => rows };
  });
}

/** Median of seven runs, after one warm-up. */
function medianMs(run: () => void): number {
  run();
  const times: number[] = [];
  for (let i = 0; i < 7; i += 1) {
    const start = performance.now();
    run();
    times.push(performance.now() - start);
  }
  times.sort((a, b) => a - b);
  return times[3] ?? Infinity;
}

describe("E10-S05 rank.ts budget", () => {
  for (const n of [500, 2000])
    it(`builds the index of ${String(n)} rows within 16 ms`, () => {
      const all = sources(n);
      expect(buildIndex(all, CTX)).toHaveLength(n);
      expect(medianMs(() => buildIndex(all, CTX))).toBeLessThan(16);
    });
});
