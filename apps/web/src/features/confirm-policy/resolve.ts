import type { Environment } from "../../shell/bootstrap/store";

/**
 * Confirm-policy resolver (E47-S08 S4, US-SET-003). Pure: `(action, env, userPolicy, serverFloor)` gives
 * how a destructive action is confirmed. UX-ONLY (C-2.12): the resolution never decides whether a request
 * is sent; the server's arm token, step-up and risk checks apply regardless of what it says.
 *
 * Strength order: immediate < hold < dialog. Live is never weaker than Demo, and no accessibility
 * preference is an input, so none can relax a Live confirm. `immediate` is not selectable until its audit
 * contract exists (BQ-2): it resolves to `dialog` unconditionally, here and in the store.
 *
 * `env` comes from `shell/bootstrap/store` (`environment`, never guessed). Only "demo" gets Demo rules;
 * "live", "testnet" and "unknown" all get Live rules (fail closed).
 */
export const CONFIRM_ACTIONS = ["flatten", "cancel-all", "reverse", "freeze"] as const;
export type ConfirmAction = (typeof CONFIRM_ACTIONS)[number];

export type ConfirmEnv = Environment | "unknown";
export type ConfirmMode = "dialog" | "hold" | "immediate";

/** CMP-044's hold bounds (ms), mirrored from `packages/ui` (not exported there); a test pins them. */
export const HOLD_MIN_MS = 300;
export const HOLD_MAX_MS = 2000;
export const HOLD_DEFAULT_MS = 800;

/** Weakest to strongest. */
export const MODE_STRENGTH: Readonly<Record<ConfirmMode, number>> = {
  immediate: 0,
  hold: 1,
  dialog: 2,
};

export interface ActionPolicy {
  readonly mode: ConfirmMode;
  readonly holdMs?: number;
}
export type UserPolicy = Readonly<Partial<Record<ConfirmAction, ActionPolicy>>>;

/** Server-held settings that raise a floor (Settings.trading, `22`). */
export interface ServerFloor {
  /** `confirm_flatten = true` (E30-D03 §7 key-binding table, `confirm_flatten` row: true <=> flatten `dialog`). */
  readonly confirmFlatten?: boolean;
}

export interface Resolution {
  readonly mode: ConfirmMode;
  /** The hold length, ms, within 300-2,000 for `hold`; 0 otherwise. */
  readonly holdMs: number;
  /** A typed confirm word is required as well. */
  readonly typed: boolean;
}

interface Rule {
  /** The weakest mode the user may reach in this env, before `immediate` is mapped to dialog. */
  readonly floor: ConfirmMode;
  /** Dialog only: a user `hold` / `immediate` is T2 and ignored. */
  readonly dialogOnly: boolean;
  readonly typed: boolean;
  /** Minimum hold length when the result is a hold. */
  readonly holdMinMs: number;
}

const FREE: Rule = { floor: "immediate", dialogOnly: false, typed: false, holdMinMs: HOLD_MIN_MS };
const DIALOG_ONLY: Rule = { floor: "dialog", dialogOnly: true, typed: false, holdMinMs: 0 };

/**
 * The per-(action, env) floors, from the ruled specs (anchors are sections, not line numbers):
 * - flatten Demo: free (dialog default, hold selectable): E30-D03 §7 "Destructive-action rows"; US-SET-003
 *   scenario "Policy choice".
 * - flatten Live: hold >= 800 ms plus a typed confirm: 14 SCR-010 Interactions and Validation. It keeps
 *   hold + typed until C14 (E39-D03 §14, row C14) is ruled. With no user choice it resolves to dialog +
 *   typed: stricter than the spec, allowed by US-SET-003 scenario "Live stricter than demo".
 * - cancel-all Demo: free: E30-D03 §7 "Destructive-action rows" (dialog default / hold 300-2,000 ms).
 * - cancel-all Live: derived, no explicit spec row: never below hold (E30-D02 §1.3 SC-3 lock;
 *   US-SET-003 scenario "Live stricter than demo"; E39-D03 §5 "The three confirmModes"); no typed word:
 *   no spec asks for one.
 * - reverse, both: dialog only (F19; E30-D03 §7 "Destructive-action rows" and its Confirmation row;
 *   US-ORD-011 scenario "Confirm policy").
 * - freeze, both: dialog only, SCR-072 `alertdialog`, no typed word, no hold (14 SCR-072; E30-D03 §7
 *   "Destructive-action rows").
 */
const RULES: Readonly<Record<ConfirmAction, Readonly<Record<"demo" | "live", Rule>>>> = {
  flatten: {
    demo: FREE,
    live: { floor: "hold", dialogOnly: false, typed: true, holdMinMs: HOLD_DEFAULT_MS },
  },
  "cancel-all": { demo: FREE, live: { ...FREE, floor: "hold" } },
  reverse: { demo: DIALOG_ONLY, live: DIALOG_ONLY },
  freeze: { demo: DIALOG_ONLY, live: DIALOG_ONLY },
};

export function clampHoldMs(ms: number | undefined): number {
  if (ms === undefined || !Number.isFinite(ms)) return HOLD_DEFAULT_MS;
  return Math.min(HOLD_MAX_MS, Math.max(HOLD_MIN_MS, Math.round(ms)));
}

/** A raw mode made enforceable: unknown values and `immediate` (BQ-2) fail closed to dialog. */
function sanitise(mode: unknown): "dialog" | "hold" {
  return mode === "hold" ? "hold" : "dialog";
}

function resolveFor(
  rule: Rule,
  chosen: ActionPolicy | undefined,
  serverDialog: boolean,
): Resolution {
  // M2: the default is a dialog; a user choice is sanitised, then lifted to the floor.
  let mode: "dialog" | "hold" =
    rule.dialogOnly || chosen === undefined ? "dialog" : sanitise(chosen.mode);
  if (MODE_STRENGTH[mode] < MODE_STRENGTH[rule.floor]) mode = sanitise(rule.floor);
  if (serverDialog) mode = "dialog";
  const holdMs = mode === "hold" ? Math.max(rule.holdMinMs, clampHoldMs(chosen?.holdMs)) : 0;
  return { mode, holdMs, typed: rule.typed };
}

export function resolveConfirm(
  action: ConfirmAction,
  env: ConfirmEnv,
  userPolicy: UserPolicy,
  serverFloor: ServerFloor = {},
): Resolution {
  const chosen = Object.hasOwn(userPolicy, action) ? userPolicy[action] : undefined;
  const serverDialog = action === "flatten" && serverFloor.confirmFlatten === true;
  const demo = resolveFor(RULES[action].demo, chosen, serverDialog);
  if (env === "demo") return demo;
  const live = resolveFor(RULES[action].live, chosen, serverDialog);
  // Live is never weaker than Demo for the same inputs.
  if (MODE_STRENGTH[live.mode] < MODE_STRENGTH[demo.mode])
    return { mode: demo.mode, holdMs: demo.holdMs, typed: live.typed || demo.typed };
  if (live.mode === "hold" && demo.mode === "hold")
    return { ...live, holdMs: Math.max(live.holdMs, demo.holdMs) };
  return live;
}
