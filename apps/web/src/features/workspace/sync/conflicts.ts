/**
 * The two conflict states E15-D06 draws (§6): computed from a group's snapshot, never stored.
 * D-7, interval mismatch: crosshair sync on and a chart member's interval differs; a status, not a
 * gate, since the crosshair still aligns by timestamp (the containing bar, BQ-06, is the engine's).
 * D-8, drawings across symbols: drawings on and a chart member's symbol differs; it gets no levels.
 * "Differs" is from the reference: the given pane's value, else the value most members share (the
 * earliest-joined on a tie). E15-S04 words both (D-7 / D-8 grammar); this module names the panes.
 */
import type { GroupSnapshot, MemberSnapshot } from "./syncBus";
import type { SyncGroupId } from "./types";

export type ConflictKind = "interval_mismatch" | "drawings_symbol_mismatch";

export interface SyncConflict {
  readonly kind: ConflictKind;
  readonly group: SyncGroupId;
  /** The value the others are compared with. */
  readonly reference: string;
  /** The chart members whose value differs, in join order. */
  readonly paneIds: readonly string[];
}

type Field = "interval" | "symbol";

function mismatch(
  snapshot: GroupSnapshot,
  kind: ConflictKind,
  field: Field,
  referencePaneId: string | undefined,
): SyncConflict | null {
  const charts = snapshot.members.filter(
    (m): m is MemberSnapshot & Record<Field, string> => m.kind === "chart" && m[field] !== null,
  );
  const counts = new Map<string, number>();
  for (const m of charts) counts.set(m[field], (counts.get(m[field]) ?? 0) + 1);
  if (counts.size < 2) return null;
  let reference = charts.find((m) => m.paneId === referencePaneId)?.[field];
  if (reference === undefined) {
    let best = 0;
    for (const [value, n] of counts) {
      if (n > best) [reference, best] = [value, n];
    }
  }
  if (reference === undefined) return null;
  const paneIds = charts.filter((m) => m[field] !== reference).map((m) => m.paneId);
  return { kind, group: snapshot.group, reference, paneIds };
}

/** The group's conflicts, D-7 then D-8; empty when there are none. */
export function conflictsOf(snapshot: GroupSnapshot, referencePaneId?: string): SyncConflict[] {
  const found: SyncConflict[] = [];
  if (snapshot.axes.crosshair) {
    const c = mismatch(snapshot, "interval_mismatch", "interval", referencePaneId);
    if (c !== null) found.push(c);
  }
  if (snapshot.axes.drawings) {
    const c = mismatch(snapshot, "drawings_symbol_mismatch", "symbol", referencePaneId);
    if (c !== null) found.push(c);
  }
  return found;
}
