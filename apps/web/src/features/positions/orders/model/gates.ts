/**
 * The cancel and amend controls' gates (E29-S02 PR2, PR3a; E29-D04 §4.1–§4.2, E29-D02 §7, §8.2,
 * §10.3–§10.4; E09-D09 §2.1): which reason, if any, makes a row's Cancel, the bulk buttons and an
 * Edit T2, "disabled with a visible reason". Presentation only: the server enforces every leg again
 * (C-12.4), and its refusal stays the authority, the native stop's `403` above all (C-2.6).
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
 * - **The amend's legs** (PR3a; D02 §7, §10.3–§10.4, D01 D12, D04 §4.1): the same scope legs, then
 *   the order's kind (a native stop and a recorded take-profit are never amended, D-13), this
 *   client's amend (pending: `blotter.amend_in_flight`; unconfirmed: `blotter.unknown`), the order's
 *   state, and for a resting order its provenance (`model/amend.ts` `provenanceBar`: any but
 *   `placed` is `22`'s `422`, PROPOSED `blotter.not_amendable`; a reduce-only take-profit's unread
 *   one fails closed, PROPOSED `blotter.ui.amend.provenance_unread`, until the feed's next
 *   `open_only` read lists it), the instrument's steps (never guessed), and, for a risk-increasing
 *   edit only (`24` §8.10), E09-D09 §2.1 step 4's states: the kill switch, the account's reconcile
 *   lock, the arm. A price or trigger edit meets them before its editor opens; a quantity at its
 *   commit, where a cut never does (C-2.6, R5). The arm is read on every call, never kept
 *   (`ArmTokenSource`).
 */
import type { KillSwitchView } from "../../../../lib/ws/state/types";
import { killSwitchCovers, type AccountSignal, type Role } from "../../accountSignals";
import { bindDeck, bindText, DECK, type DeckKey } from "../../copy";
import { AMEND_TEXT, bindProposed } from "../copy";
import {
  armToken,
  needsArm,
  provenanceBar,
  riskClass,
  valueOf,
  type AmendField,
  type ArmTokenSource,
  type PendingMutation,
} from "./amend";
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

/** A control that is T2: its leg, its reason and where the reason renders. */
export interface Gated<L extends string> {
  readonly kind: "gated";
  readonly leg: L;
  readonly reason: string;
  readonly scope: ReasonScope;
}

export type CancelGate =
  | { readonly kind: "allowed" }
  | { readonly kind: "busy" }
  | { readonly kind: "ended" }
  | Gated<CancelLeg>;

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

const gated = <L extends string>(leg: L, reason: string, scope: ReasonScope): Gated<L> => ({
  kind: "gated",
  leg,
  reason,
  scope,
});

/** The legs every write of the tab takes on `accountId`'s rows (the panel's alone without one). */
export function scopeGate(context: CancelContext, accountId?: string): Gated<CancelLeg> | null {
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

export type AmendLeg =
  | CancelLeg
  | "amend_in_flight"
  | "not_amendable"
  | "provenance_unread"
  | "no_step"
  | "frozen"
  | "recon"
  | "arm";

export type AmendGate =
  | { readonly kind: "allowed" }
  /** The order has no such field: no Edit item (form validity, outside the T2 grammar). */
  | { readonly kind: "absent" }
  /** A final row lingering: nothing to amend (plain `disabled`). */
  | { readonly kind: "ended" }
  | Gated<AmendLeg>;

export interface AmendContext extends CancelContext {
  /** This client's amends by order id (`amendStore`): pending is in flight, unconfirmed unknown. */
  readonly amends: ReadonlyMap<string, Pick<PendingMutation, "phase">>;
  /** Whether the symbol's tick and lot steps are known (`instruments.ts`); a step is never guessed. */
  readonly hasSteps: (symbol: string) => boolean;
  /** The arm's token, read on every gate and again at the commit, never kept (M13). */
  readonly arm: ArmTokenSource;
  /** The arm command's binding (`bindingFor("ticket.arm")`, or the user's), never a literal (F-08). */
  readonly armKey: string;
  readonly role: Role;
  /** The kill switch's engage time (`accountSignals`), for `frozen`'s `{hh:mm}`. */
  readonly frozenAtMs?: number | null | undefined;
  /** Each account's reconcile state (`accountSignals`). */
  readonly accountStates?: ReadonlyMap<string, AccountSignal> | undefined;
}

const ALLOWED: AmendGate = Object.freeze({ kind: "allowed" });

/** D04:460's key for an account's reconcile state; a stale lock the kill switch left is its own. */
function reconKey(oms: NonNullable<AccountSignal["oms"]>): DeckKey {
  if (oms.state === "reconciling") return "recon.reconciling";
  if (oms.state === "desync") return "recon.desync";
  return oms.killLock ? "recon.killlock" : "recon.stale";
}

/** `frozen`'s "14:02" (UTC); "—" while the engage time is not known, as `utcTime` writes it. */
const hhmm = (ms: number | null): string =>
  ms === null || !Number.isFinite(ms) ? "—" : new Date(ms).toISOString().slice(11, 16);

/** A resting order's provenance (D-13): not `placed` is `22`'s `422`; unread may fail closed. */
function provenanceGate(row: OrderRowModel): AmendGate | null {
  const bar = provenanceBar(row);
  if (bar === null) return null;
  return bar === "unread"
    ? gated("provenance_unread", bindProposed("blotter.ui.amend.provenance_unread"), "row")
    : gated("not_amendable", bindProposed("blotter.not_amendable"), "row");
}

/** The order's own legs (D01 D12: not editable while Amending, Cancelling, Unknown, … or final). */
function kindGate(row: OrderRowModel, context: AmendContext): AmendGate | null {
  if (row.protective.kind === "native_stop")
    return gated("native_stop", bindProposed("blotter.ui.amend.native_stop"), "row");
  if (row.protective.kind === "recorded_take_profit")
    return gated("recorded_take_profit", bindProposed("blotter.recorded_tp"), "row");
  const mine = context.amends.get(row.id)?.phase;
  if (mine === "pending")
    return gated("amend_in_flight", DECK["blotter.amend_in_flight"].string, "row");
  if (mine === "unconfirmed") return gated("unknown", DECK["blotter.unknown"].string, "row");
  switch (row.state.lifecycle) {
    case "submitted":
    case "partially_filled":
      return provenanceGate(row);
    case "amend_pending":
      return gated("amend_in_flight", DECK["blotter.amend_in_flight"].string, "row");
    case "untracked":
      return gated("untracked", DECK["blotter.untracked"].string, "row");
    case "held":
      return gated("held", DECK["blotter.held"].string, "row");
    case "quarantined":
      return gated("quarantined", bindProposed("blotter.quarantined"), "row");
    case "unknown":
      return gated("unknown", DECK["blotter.unknown"].string, "row");
    default:
      // Sending, Cancelling, Triggered, or a state not reported: the server takes an amend only
      // while the order rests (`22` `amendOrder`'s `422 order_not_amendable`)
      return row.state.terminal
        ? { kind: "ended" }
        : gated("not_amendable", bindProposed("blotter.not_amendable"), "row");
  }
}

/** A risk-increasing edit's states (D04 §4.1, D02 §10.3), step 4's order: freeze, lock, the arm. */
function exposureGate(
  row: OrderRowModel,
  field: AmendField,
  requested: string | null,
  context: AmendContext,
): AmendGate | null {
  if (context.killSwitch !== undefined && killSwitchCovers(context.killSwitch, row.accountId)) {
    return context.role === "owner"
      ? gated("frozen", bindDeck("frozen", { "{hh:mm}": hhmm(context.frozenAtMs ?? null) }), "row")
      : gated("frozen", DECK["blotter.ui.frozen_control"].string, "row");
  }
  const oms = context.accountStates?.get(row.accountId)?.oms ?? null;
  if (oms !== null) return gated("recon", DECK[reconKey(oms)].string, "row");
  if (needsArm(row, field, requested) && armToken(context.arm, row.accountId) === null) {
    const reason = bindText(AMEND_TEXT.armLocked, "AMEND_TEXT.armLocked", {
      "{arm_key}": context.armKey,
    });
    return gated("arm", reason, "row");
  }
  return null;
}

/** An Edit before its editor opens: a price or trigger meets the new-exposure legs here (D02 §7). */
export function editGate(row: OrderRowModel, field: AmendField, context: AmendContext): AmendGate {
  if (valueOf(row, field) === null) return { kind: "absent" };
  const gate = scopeGate(context, row.accountId) ?? kindGate(row, context);
  if (gate !== null) return gate;
  if (!context.hasSteps(row.symbol))
    return gated("no_step", bindProposed("blotter.ui.amend.no_step"), "row");
  if (field === "qty" || riskClass(row, field, null) === "none") return ALLOWED;
  return exposureGate(row, field, null, context) ?? ALLOWED;
}

/** The commit (`Enter`): every leg again with the arm read again; a quantity raised meets them now. */
export function commitGate(
  row: OrderRowModel,
  field: AmendField,
  requested: string,
  context: AmendContext,
): AmendGate {
  const edit = editGate(row, field, context);
  if (edit.kind !== "allowed" || field !== "qty") return edit;
  if (riskClass(row, field, requested) === "none") return ALLOWED;
  return exposureGate(row, field, requested, context) ?? ALLOWED;
}
