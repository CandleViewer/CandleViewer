/**
 * The client's feature-flag mirror (#971 #973 #561): the latest resolved boolean per flag name,
 * folded from the WS `system` topic (`23` §15.9). Flags are registered server-side
 * (`admin/flags/catalogue.py`, `21` §10.7); the client never defines one and reads no build-time
 * flag. Pure: `reduceFlags(flags, update)` depends on its arguments only.
 *
 * §15.9: a `feature_flags` frame carries only the changed keys, merged into the set held; a
 * `health` frame (the topic snapshot, sent on subscribe; `auth_ok` carries only `kill_switch`, §4.3)
 * carries the full set the role may see, so its `feature_flags` replaces the set. The wire is
 * untrusted: only a boolean value counts; a frame whose `feature_flags` is not an object changes
 * nothing. The server omits the key when no flag is visible to the role, so a `health` frame
 * without it keeps the set held; a flag later hidden from a role keeps its last value until the
 * shell stops (`clearFlags`).
 *
 * A name with no value reads `undefined`: unread, or not visible to the role. Callers treat
 * `undefined` as OFF.
 */
import type { SystemUpdate } from "../../lib/ws/protocol/frames";

/** Flag name -> resolved value. A `Map`, so a name such as `__proto__` is only ever a key. */
export type FlagValues = ReadonlyMap<string, boolean>;

export const INITIAL_FLAGS: FlagValues = new Map<string, boolean>();

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** The boolean entries of a wire `feature_flags` object; `undefined` when it is not an object. */
function booleanEntries(flags: unknown): [string, boolean][] | undefined {
  if (!isRecord(flags)) return undefined;
  const out: [string, boolean][] = [];
  for (const [name, value] of Object.entries(flags)) {
    if (typeof value === "boolean") out.push([name, value]);
  }
  return out;
}

/** Folds one `system` frame into the flags: `health` replaces the set, `feature_flags` merges. */
export function reduceFlags(flags: FlagValues, update: SystemUpdate): FlagValues {
  if (!isRecord(update)) return flags; // not a payload at all
  if (update.kind !== "health" && update.kind !== "feature_flags") return flags;
  const entries = booleanEntries(update.feature_flags);
  if (entries === undefined) return flags;
  if (update.kind === "health") return new Map(entries);
  if (entries.every(([name, value]) => flags.get(name) === value)) return flags; // no change
  const next = new Map(flags);
  for (const [name, value] of entries) next.set(name, value);
  return next;
}
