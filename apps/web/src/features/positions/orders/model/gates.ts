/**
 * The cancel controls' gates (E29-S02 PR2; E29-D04 §4.1–§4.2, E29-D02 §8.2, §10.4; E09-D09 §2.1):
 * which reason, if any, makes a row's Cancel and the bulk buttons T2, "disabled with a visible
 * reason". Presentation only: the server enforces every leg again (C-12.4), and its refusal stays
 * the authority, the native stop's `403` above all (C-2.6). The arm legs and the amend's are PR3's.
 *
 * - **Legs, in E09-D09 §2.1's order:** view-as (`rbac.view_as`), the permission (`rbac.permission`,
 *   `orders:write`), an account the server refused as outside the session's grants (`rbac.account`,
 *   kept once a cancel met `403 account_scope_denied`, S-22), a read-only grant
 *   (`rbac.account_read_only`), then offline with REST unreachable (the deck's
 *   `blotter.ui.unreachable`, D02:397). The first two and the last are the panel's notice, the two
 *   account legs the account header's: one notice, many pointers (G-T2.5). The bulk buttons take
 *   the panel's legs, and the read-only one once every account they would act on is read-only.
 * - **The order's own kind** (a row's reason, rendered per control, 2b): a native-stop row,
 *   `sl.note`'s sentence (BQ-5, G-T2.1c); a recorded take-profit, PROPOSED `blotter.recorded_tp`
 *   (its Cancel is `setPositionTpSl`'s, which is not mounted: never `cancelOrder`); Untracked, Held,
 *   Quarantined and Unknown, their `blotter.*` sentences (`22` refuses each such cancel with `409`).
 * - **Never a cancel leg** (E29-D04 §4.2, D02 §10.2–§10.3; `24` §8.10's C-2.6 carve-out): the kill
 *   switch, the Owner's or a Manager's, a risk lockout, and an account reconciling, in desync or
 *   stale-locked. The context carries them so that this is stated, and tested, here.
 * - **Busy, not T2:** this client's cancel in flight, or the order's own cancel pending ("Cancelling…",
 *   `aria-busy`, no reason). A final row lingering is **ended**: it has nothing left to cancel.
 */
import type { KillSwitchView } from "../../../../lib/ws/state/types";
import { bindDeck, DECK } from "../../copy";
import { bindProposed } from "../copy";
import type { OrderRowModel } from "./orderRow";

export type CancelLeg =
  | "view_as"
  | "permission"
  | "account"
  | "account_read_only"
  | "offline"
  | "native_stop"
  | "recorded_take_profit"
  | "untracked"
  | "held"
  | "quarantined"
  | "unknown";

/** Where a reason renders: the panel's notice, the account header's, or the control's own (2b). */
export type ReasonScope = "panel" | "account" | "row";

export type CancelGate =
  | { readonly kind: "allowed" }
  | { readonly kind: "busy" }
  | { readonly kind: "ended" }
  | {
      readonly kind: "gated";
      readonly leg: CancelLeg;
      readonly reason: string;
      readonly scope: ReasonScope;
    };

export interface CancelContext {
  /** The view-as target's name while a context is live; `null` otherwise (no client source yet). */
  readonly viewAs: { readonly user: string } | null;
  /** The session's permissions (`GET /me`). */
  readonly permissions: readonly string[];
  /** Accounts the session holds a read-only grant on. */
  readonly readOnlyAccounts: ReadonlySet<string>;
  /** Accounts a cancel was refused on with `403 account_scope_denied`: T2 from then on (S-22). */
  readonly deniedAccounts?: ReadonlySet<string> | undefined;
  /** False while the link is offline for a shell cause: REST is unreachable too (D02:397). */
  readonly restReachable: boolean;
  /** Orders with this client's cancel in flight. */
  readonly cancelling: ReadonlySet<string>;
  /** Never a cancel leg (C-2.6): never read, so the carve-out is stated, and tested, here. */
  readonly killSwitch?: KillSwitchView | undefined;
  /** Accounts under a risk lockout or a stale lock: never a cancel leg either (C-2.6), never read. */
  readonly lockedAccounts?: ReadonlySet<string> | undefined;
}

/** E09-D09 §3.2's verb for `orders:write` (D02:433). */
const ORDERS_VERB = "place orders";

const gated = (leg: CancelLeg, reason: string, scope: ReasonScope): CancelGate => ({
  kind: "gated",
  leg,
  reason,
  scope,
});

/** The legs every write of the tab takes on `accountId`'s rows (the panel's alone without one). */
export function scopeGate(context: CancelContext, accountId?: string): CancelGate | null {
  if (context.viewAs !== null)
    return gated("view_as", bindDeck("rbac.view_as", { "{user}": context.viewAs.user }), "panel");
  if (!context.permissions.includes("orders:write"))
    return gated("permission", bindDeck("rbac.permission", { "{verb}": ORDERS_VERB }), "panel");
  if (accountId !== undefined && context.deniedAccounts?.has(accountId) === true)
    return gated("account", DECK["rbac.account"].string, "account");
  if (accountId !== undefined && context.readOnlyAccounts.has(accountId))
    return gated("account_read_only", DECK["rbac.account_read_only"].string, "account");
  if (!context.restReachable)
    return gated("offline", DECK["blotter.ui.unreachable"].string, "panel");
  return null;
}

/**
 * Cancel selected's and "Cancel all in view…"'s gate over the accounts of the rows they would act on
 * (D02 §8.3: they take their rows' gates): the panel's legs, then `rbac.account_read_only` once
 * every one of those accounts is read-only (D04 §4.1), the reason drawn beside the buttons (2a).
 * Fewer read-only accounts leave the buttons enabled: each such row is left out on its own line.
 */
export function bulkGate(context: CancelContext, accountIds: readonly string[]): CancelGate | null {
  const scope = scopeGate(context);
  if (scope !== null) return scope;
  if (accountIds.length > 0 && accountIds.every((id) => context.readOnlyAccounts.has(id)))
    return gated("account_read_only", DECK["rbac.account_read_only"].string, "account");
  return null;
}

/** A row's Cancel: the scope legs, then the order's own kind, then busy, ended or allowed. */
export function cancelGate(row: OrderRowModel, context: CancelContext): CancelGate {
  const scope = scopeGate(context, row.accountId);
  if (scope !== null) return scope;
  if (row.protective.kind === "native_stop")
    return gated("native_stop", DECK["sl.note"].string, "row");
  if (row.protective.kind === "recorded_take_profit")
    return gated("recorded_take_profit", bindProposed("blotter.recorded_tp"), "row");
  if (context.cancelling.has(row.id)) return { kind: "busy" };
  switch (row.state.lifecycle) {
    case "untracked":
      return gated("untracked", DECK["blotter.untracked"].string, "row");
    case "held":
      return gated("held", DECK["blotter.held"].string, "row");
    case "quarantined":
      return gated("quarantined", bindProposed("blotter.quarantined"), "row");
    case "unknown":
      return gated("unknown", DECK["blotter.unknown"].string, "row");
    case "cancel_pending":
      return { kind: "busy" };
    default:
      return row.state.terminal ? { kind: "ended" } : { kind: "allowed" };
  }
}
