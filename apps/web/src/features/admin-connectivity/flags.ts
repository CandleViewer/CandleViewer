// E08-S12 (#5207) BQ-5: one build-time switch per slice, `apps/web` having no client flag service (same
// pattern as `features/tape/flag.ts`). Every flag is off ("unset") by default, and a slice that is off reads
// S-19 "Not connected yet" (E08-D09 §5.2). Each flag dies with PR 2 of this ticket, which turns the slices on.

/** The slices of SCR-147 and the contract G-row each one waits on (E08-D09 §21.2). */
export const SLICES = {
  /** Per-account rate budgets: the served `rate_budget[]` (D09-G1, G2). */
  rateBudget: "VITE_FLAG_CONNECTIVITY_RATE_BUDGET",
  /** The connection state of the market-data socket (D09-G4). */
  connection: "VITE_FLAG_CONNECTIVITY_CONNECTION",
  /** The clock offset and its guard (D13-G-6). */
  clock: "VITE_FLAG_CONNECTIVITY_CLOCK",
  /** The reserve for stops and cancels (D09-G14). */
  reserve: "VITE_FLAG_CONNECTIVITY_RESERVE",
  /** The subscription inspector (D09-G3, G4). */
  inspector: "VITE_FLAG_CONNECTIVITY_INSPECTOR",
  /** Force reconnect and Change budget (D09-G7, G8). */
  actions: "VITE_FLAG_CONNECTIVITY_ACTIONS",
} as const;

export type SliceName = keyof typeof SLICES;

/** A build's `import.meta.env`, or any record of it. */
export type FlagEnv = Readonly<Record<string, string | boolean | undefined>>;

/** `true` only for the build variable "1"; anything else, or unset, is off. */
export function sliceOn(env: FlagEnv, slice: SliceName): boolean {
  return env[SLICES[slice]] === "1";
}

/** Every slice's switch for the running build. */
export function sliceFlags(env: FlagEnv = import.meta.env): Readonly<Record<SliceName, boolean>> {
  return {
    rateBudget: sliceOn(env, "rateBudget"),
    connection: sliceOn(env, "connection"),
    clock: sliceOn(env, "clock"),
    reserve: sliceOn(env, "reserve"),
    inspector: sliceOn(env, "inspector"),
    actions: sliceOn(env, "actions"),
  };
}
