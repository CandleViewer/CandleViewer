/**
 * SCR-012's row index (E10-S05, #5236): built once per opening and on a claims change while open (`14` :368's
 * precomputed index), never per keystroke. Pure: it gathers the mounted sources' rows in E10-D02 f11's fixed group
 * order (CMP-059 groups in first-appearance order, so the order is the host's) and keeps the first of any repeated id.
 * The per-keystroke filter, fuzzy score and `<mark>` ranges are CMP-059's own (`fuzzy.ts`), not forked here.
 */
import { GROUP_ORDER, type PaletteRow, type PaletteSource, type SourceContext } from "./sources";

export function buildIndex(
  sources: readonly PaletteSource[],
  ctx: SourceContext,
): readonly PaletteRow[] {
  const byGroup = new Map<string, PaletteRow[]>(GROUP_ORDER.map((g) => [g, []]));
  const seen = new Set<string>();
  for (const source of sources) {
    for (const row of source.rows(ctx)) {
      if (seen.has(row.id)) continue;
      seen.add(row.id);
      byGroup.get(row.group)?.push(row);
    }
  }
  return GROUP_ORDER.flatMap((g) => byGroup.get(g) ?? []);
}
