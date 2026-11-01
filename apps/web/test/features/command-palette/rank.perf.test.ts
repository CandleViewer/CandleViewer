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

// Structural, not wall-clock (this file runs under the coverage `unit` project, where an absolute 16 ms is flaky):
// eight times the rows must cost about eight times the time, from the fastest of several runs. A quadratic build
// would cost about sixty-four times; the bound is loose enough for coverage instrumentation and a noisy runner.
// The absolute 2 000-row budget (`14` :368) is for the bench lane, not for this project.
function fastestMs(run: () => void): number {
  run();
  let best = Infinity;
  for (let i = 0; i < 9; i += 1) {
    const start = performance.now();
    run();
    best = Math.min(best, performance.now() - start);
  }
  return best;
}

describe("E10-S05 rank.ts budget", () => {
  it("builds every row, and the cost grows about linearly with the row count", () => {
    const small = sources(250);
    const large = sources(2000);
    expect(buildIndex(small, CTX)).toHaveLength(250);
    expect(buildIndex(large, CTX)).toHaveLength(2000);
    const ratio =
      fastestMs(() => buildIndex(large, CTX)) /
      Math.max(
        fastestMs(() => buildIndex(small, CTX)),
        0.01,
      );
    expect(ratio).toBeLessThan(24);
  });
});
