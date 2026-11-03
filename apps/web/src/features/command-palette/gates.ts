/**
 * The action rows' gates (E10-S05, #5236): which keymap command a session may not run, and E09-D09 §3's sentence
 * saying why (T2: the row stays, with the lock and its reason). PROPOSED shape: one row per command id. No registered
 * command needs one today; each later epic adds its row in the PR that registers the command, and the completeness
 * test fails when a registered `destructive`, `requiresArm` or `confirm` command has none. The server still refuses
 * whatever the row says (C-2.12, C-12.4): a gate only explains, it never authorises.
 */
import type { CommandMeta } from "../../keymap/registry";
import type { MeClaims } from "../../routes/rbac";
import { ownerOnlyReason, permissionReason, viewAsReason } from "./copy";

export interface CommandGate {
  /** The permission code the command's server call needs (`22`'s `x-permissions`). */
  readonly permission?: string;
  /** The action's own verb, where E09-D09 §3.1 gives one (the kill-switch release); else `PERMISSION_VERBS`. */
  readonly verb?: string;
  /** No non-owner role may do it under the contract (E09-D09 §3.1's chooser): `rbac.owner_only`. */
  readonly ownerOnly?: boolean;
  /** A write: read-only while viewing as another user (`rbac.view_as`). */
  readonly write?: boolean;
  /** A C-2.6 protective command (cancel, close, stop): never refused while viewing as (E10-D03 §6.1). */
  readonly protective?: boolean;
}

/** One row per command id. Empty until a command that needs one registers (see the module note). */
export const COMMAND_GATES: Readonly<Record<string, CommandGate>> = {};

/** E09-D09 §3.2's `{verb}` per permission code, verbatim; the admin domain is never rendered (step 1 hides it). */
export const PERMISSION_VERBS: Readonly<Record<string, string>> = {
  "users:read": "see users",
  "users:write": "manage users",
  "accounts:write": "change account settings",
  "keys:read": "see API keys",
  "keys:manage": "manage API keys",
  "instruments:read": "see instruments",
  "instruments:write": "change instrument settings",
  "recording:read": "see recordings",
  "recording:write": "change recording",
  "replay:read": "see replays",
  "replay:write": "control replay",
  "orders:read": "see orders",
  "orders:write": "place orders",
  "positions:read": "see positions",
  "positions:write": "change positions",
  "executions:read": "see fills",
  "killswitch:write": "use the kill switch",
  "rules:read": "see rules",
  "rules:write": "change rules",
  "rules:arm_live": "arm rules against live",
  "alerts:read": "see alerts",
  "alerts:write": "change alerts",
  "journal:read": "see the journal",
  "journal:write": "write in the journal",
  "workspaces:read": "see workspaces",
  "workspaces:write": "save workspaces",
  "settings:read": "see settings",
  "settings:write": "change settings",
  "audit:read": "see the audit log",
  "audit:export": "export the audit log",
};

/** The verb for a permission E09-D09 §3.2 does not list: never invented per code. */
export const FALLBACK_VERB = "do this";

export interface GateContext {
  readonly claims: MeClaims;
  /** `GET /auth/session/view-as`'s active context; `null` today: the shell has no view-as source (#304 gap 13). */
  readonly viewAs: { readonly user: string } | null;
}

/**
 * The row's T2 reason, or none: view-as first (the server decides `view_as_read_only` before authorisation), never
 * on a protective command; then the permission leg, `rbac.owner_only` or `rbac.permission` with its verb.
 */
export function gateReason(gate: CommandGate | undefined, ctx: GateContext): string | undefined {
  if (gate === undefined) return undefined;
  if (ctx.viewAs !== null && gate.write === true && gate.protective !== true) {
    return viewAsReason(ctx.viewAs.user);
  }
  const { permission } = gate;
  if (permission === undefined || ctx.claims.permissions.includes(permission)) return undefined;
  // A permission with no §3.2 verb must not throw inside the host's render: say it generically (the table test
  // `gates.test.ts` fails for any gate that relies on this).
  const verb = gate.verb ?? PERMISSION_VERBS[permission] ?? FALLBACK_VERB;
  return gate.ownerOnly === true ? ownerOnlyReason(verb) : permissionReason(verb);
}

/** A command the palette must not list ungated: destructive, an order entry or one that confirms. */
export const needsGate = (meta: CommandMeta, destructive: boolean): boolean =>
  destructive || meta.dangerous || meta.requiresArm || meta.confirm;

/** The ids among `registered` that need a gate row and have none (the completeness test's check). */
export function missingGates(
  registered: readonly { readonly meta: CommandMeta; readonly destructive: boolean }[],
  table: Readonly<Record<string, CommandGate>> = COMMAND_GATES,
): string[] {
  return registered
    .filter(({ meta, destructive }) => needsGate(meta, destructive) && !(meta.id in table))
    .map(({ meta }) => meta.id);
}
