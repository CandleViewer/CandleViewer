/**
 * Confirm-policy resolver (E47-S08 S4, US-SET-003). Pure: `(action, env, userPolicy)` gives how a
 * destructive action is confirmed. Strength order: immediate < hold < dialog. Live is never weaker than
 * Demo, and no accessibility preference is an input, so none can relax a Live confirm. Immediate mode is
 * not selectable until its audit contract exists (BQ-2): it fails closed to a dialog.
 */
export const CONFIRM_ACTIONS = [
  "flatten",
  "cancel-all",
  "close-position",
  "market-order",
  "reverse-position",
] as const;
export type ConfirmAction = (typeof CONFIRM_ACTIONS)[number];

export type ConfirmEnv = "live" | "demo";
export type ConfirmMode = "dialog" | "hold" | "immediate";

/** Bounds of CMP-044's hold duration (ms), mirrored from `packages/ui` (not exported there). */
export const HOLD_MIN_MS = 300;
export const HOLD_MAX_MS = 2000;
export const HOLD_DEFAULT_MS = 800;

/** Weakest to strongest. */
export const MODE_STRENGTH: Readonly<Record<ConfirmMode, number>> = {
  immediate: 0,
  hold: 1,
  dialog: 2,
};

/** BQ-2: flip only when the audit contract for `settings.confirm_policy_changed` exists. */
export const IMMEDIATE_SELECTABLE = false;

export interface ActionPolicy {
  readonly mode: ConfirmMode;
  readonly holdMs?: number;
}
export type UserPolicy = Readonly<Partial<Record<ConfirmAction, ActionPolicy>>>;
export interface Resolution {
  readonly mode: ConfirmMode;
  /** The hold length, ms, within 300-2,000 for `hold`; 0 otherwise. */
  readonly holdMs: number;
}

/** Defaults: Demo is lighter than Live. */
const DEMO_DEFAULT: ConfirmMode = "hold";
const LIVE_DEFAULT: ConfirmMode = "dialog";
/** The weakest mode a user may choose on Live. */
const LIVE_FLOOR: ConfirmMode = "hold";

export function clampHoldMs(ms: number | undefined): number {
  if (ms === undefined || !Number.isFinite(ms)) return HOLD_DEFAULT_MS;
  return Math.min(HOLD_MAX_MS, Math.max(HOLD_MIN_MS, Math.round(ms)));
}

const isMode = (value: unknown): value is ConfirmMode =>
  value === "dialog" || value === "hold" || value === "immediate";

/** A raw mode made enforceable: unknown values and the unselectable `immediate` fail closed to dialog. */
function enforceable(mode: unknown): ConfirmMode {
  if (!isMode(mode)) return "dialog";
  if (mode === "immediate" && !IMMEDIATE_SELECTABLE) return "dialog";
  return mode;
}

const make = (mode: ConfirmMode, holdMs: number | undefined): Resolution => ({
  mode,
  holdMs: mode === "hold" ? clampHoldMs(holdMs) : 0,
});

function demo(chosen: ActionPolicy | undefined): Resolution {
  if (chosen === undefined) return make(DEMO_DEFAULT, undefined);
  return make(enforceable(chosen.mode), chosen.holdMs);
}

export function resolveConfirm(
  action: ConfirmAction,
  env: ConfirmEnv,
  userPolicy: UserPolicy,
): Resolution {
  const chosen = Object.hasOwn(userPolicy, action) ? userPolicy[action] : undefined;
  const base = demo(chosen);
  // Anything that is not exactly "demo" is Live: fail closed.
  if (env === "demo") return base;
  const wanted = chosen === undefined ? make(LIVE_DEFAULT, undefined) : base;
  let mode = wanted.mode;
  if (MODE_STRENGTH[mode] < MODE_STRENGTH[LIVE_FLOOR]) mode = LIVE_FLOOR;
  // Live is never weaker than Demo for the same inputs.
  if (MODE_STRENGTH[mode] < MODE_STRENGTH[base.mode]) mode = base.mode;
  const holdMs = mode === "hold" ? Math.max(wanted.holdMs, base.holdMs, HOLD_MIN_MS) : 0;
  return { mode, holdMs };
}
