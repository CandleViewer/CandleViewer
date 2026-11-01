/**
 * SCR-012's row index (E10-S05, #5236): built once per opening and on a claims change while open (`14` :368's
 * precomputed index), never per keystroke. Pure: it gathers the mounted sources' rows in E10-D02 f11's fixed group
 * order (CMP-059 groups in first-appearance order, so the order is the host's) and keeps the first of any repeated id.
 * The per-keystroke filter, fuzzy score and `<mark>` ranges are CMP-059's own (`fuzzy.ts`), not forked here. The
 * empty query's sections are built here too, from the same index.
 */
import { GROUPS } from "./copy";
import type { RecentState } from "./recent";
import {
  ADMIN_READ,
  GROUP_ORDER,
  isAdminPath,
  type PaletteRow,
  type PaletteSource,
  type SourceContext,
} from "./sources";

export function buildIndex(
  sources: readonly PaletteSource[],
  ctx: SourceContext,
): readonly PaletteRow[] {
  const byGroup = new Map<string, PaletteRow[]>(GROUP_ORDER.map((g) => [g, []]));
  const seen = new Set<string>();
  // Structural anti-enumeration (`14` §0.5 rule 5): whatever source supplied it, an `/admin/*` row never enters the
  // index without `admin:read`, so no count, highlight, event or Recent entry can name it.
  const admin = ctx.claims.permissions.includes(ADMIN_READ);
  for (const source of sources) {
    for (const row of source.rows(ctx)) {
      if (!admin && row.target.kind === "route" && isAdminPath(row.target.path)) continue;
      if (seen.has(row.id)) continue;
      seen.add(row.id);
      byGroup.get(row.group)?.push(row);
    }
  }
  return GROUP_ORDER.flatMap((g) => byGroup.get(g) ?? []);
}

/** Suggested shows at most this many rows. PROPOSED (E10-D02 f10 draws a short list and names no number). */
export const SUGGESTED_LIMIT = 5;

export interface EmptyQuerySections {
  readonly recent: readonly PaletteRow[];
  readonly suggested: readonly PaletteRow[];
}

/**
 * The empty query's two sections (E10-D02 f10): Recent, the last five run, newest first, each resolved against this
 * opening's index (an id that no longer resolves, a route the session lost or a command unregistered, is dropped
 * silently); and Suggested, role-aware (only the session's own rows, none gated), most used first, ties in keymap
 * order: the Action rows, minus those already in Recent (PROPOSED: Navigate rows reach Suggested only by Recent).
 */
export function emptyQuerySections(
  index: readonly PaletteRow[],
  state: RecentState,
): EmptyQuerySections {
  const byId = new Map(index.map((row) => [row.id, row]));
  const recent = state.recent.flatMap((id) => byId.get(id) ?? []);
  const shown = new Set(recent.map((row) => row.id));
  const uses = (row: PaletteRow): number => state.counts[row.id] ?? 0;
  const suggested = index
    .filter((row) => row.group === GROUPS.action && row.disabledReason === undefined)
    .filter((row) => !shown.has(row.id))
    .sort((a, b) => uses(b) - uses(a)) // stable: ties keep the index's keymap order
    .slice(0, SUGGESTED_LIMIT);
  return { recent, suggested };
}
