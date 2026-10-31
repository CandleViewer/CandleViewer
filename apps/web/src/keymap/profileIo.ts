/**
 * The profile's JSON out and in (#305, AC7), and the changes that land a set of bindings at once: an import, a swap
 * and reset-all. Each goes through `applyRebind`, binding by binding, so a trading binding is audited whichever path
 * changes it (D10). The import is validated as one profile in `validate.ts` (D4).
 */
import { KEYMAP } from "./keymap";
import { applyRebind } from "./audit";
import type { ImportReport, SwapPlan } from "./validate";

export { importProfile } from "./validate";
export type { ImportReport } from "./validate";

/** Every command's current binding, in keymap order; an unbound command is an empty string. */
export function exportProfile(bindings: ReadonlyMap<string, string>): string {
  const out = Object.fromEntries(KEYMAP.map((c) => [c.id, bindings.get(c.id) ?? c.defaultBinding]));
  return JSON.stringify(out, null, 2);
}

export type ParsedProfile =
  | { readonly ok: true; readonly profile: Readonly<Record<string, unknown>> }
  | { readonly ok: false; readonly reason: string };

/**
 * A profile is a JSON object; its entries are checked by `importProfile`, never trusted here. Valid JSON that is not
 * an object (`[]`, a string, a number, null) is told apart from text that is not JSON (DS-305B-04).
 */
export function parseProfile(text: string): ParsedProfile {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return { ok: false, reason: "Import failed: not valid JSON" };
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return { ok: false, reason: "Import failed: not a JSON object" };
  }
  return { ok: true, profile: value as Readonly<Record<string, unknown>> };
}

function land(
  current: ReadonlyMap<string, string>,
  changes: Iterable<readonly [string, string]>,
): ReadonlyMap<string, string> {
  let next = current;
  for (const [id, binding] of changes) {
    if ((next.get(id) ?? "") !== binding) next = applyRebind(next, id, binding);
  }
  return next;
}

/** An import's profile replaces the current one, change by change. */
export function applyImport(
  current: ReadonlyMap<string, string>,
  report: ImportReport,
): ReadonlyMap<string, string> {
  return land(current, report.applied);
}

/** Both moves of a planned swap (`planSwap`), landed together (AC3). */
export function applySwap(
  current: ReadonlyMap<string, string>,
  plan: SwapPlan,
): ReadonlyMap<string, string> {
  return land(current, [
    [plan.a, plan.aTo],
    [plan.b, plan.bTo],
  ]);
}

/** Every default back (SCR-113's Reset all). */
export function resetAll(current: ReadonlyMap<string, string>): ReadonlyMap<string, string> {
  return land(
    current,
    KEYMAP.map((c) => [c.id, c.defaultBinding] as const),
  );
}
