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

// No timing assertion here: this file runs under the coverage `unit` project, where wall-clock bounds (absolute
// or as a ratio) flaked under parallel load. It pins the 2 000-row shape the budget is about; the 16 ms budget
// (`14` :368) belongs to a non-coverage bench lane, carried as a row on #5236.
describe("E10-S05 rank.ts budget shape", () => {
  it("indexes every one of 2 000 rows once, grouped in the fixed group order", () => {
    const index = buildIndex(sources(2000), CTX);
    expect(index).toHaveLength(2000);
    expect(new Set(index.map((row) => row.id)).size).toBe(2000);
    const groups = index.map((row) => GROUP_ORDER.indexOf(row.group));
    expect(groups).toEqual([...groups].sort((a, b) => a - b));
  });
});
