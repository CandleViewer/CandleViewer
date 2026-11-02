/**
 * E29-S02 PR2 (#912) the cancel legs (`model/gates.ts`; E29-D04 §4.1–§4.2, D02 §8.2, §10.4): each
 * disabled-with-reason leg in E09-D09 §2.1's order, a native-stop row's Cancel T2 with `sl.note`'s
 * sentence (BQ-5, G-T2.1c), the order's own kinds, busy and ended, and the C-2.6 carve-out: the kill
 * switch and a lockout never gate a cancel.
 */
import { describe, expect, it } from "vitest";
import { DECK } from "../../../../src/features/positions/copy";
import { PROPOSED } from "../../../../src/features/positions/orders/copy";
import { NO_ARM } from "../../../../src/features/positions/orders/model/amend";
import {
  bulkGate,
  cancelGate,
  commitGate,
  editGate,
  scopeGate,
  type AmendContext,
  type CancelContext,
} from "../../../../src/features/positions/orders/model/gates";
import {
  mapOrder,
  type OrderConstants,
  type OrderRowModel,
} from "../../../../src/features/positions/orders/model/orderRow";
import {
  COND,
  directory,
  ENTRY,
  ETH,
  MAIN,
  snapshotBody,
  STOP,
  SUB1,
  SUB2,
  TP,
  wsItem,
} from "./support/orders";

const CONTEXT: CancelContext = {
  viewAs: null,
  permissions: ["orders:read", "orders:write"],
  readOnlyAccounts: new Set(),
  restReachable: true,
  cancelling: new Set(),
  killSwitch: { state: "disengaged", scope: "global", exchangeAccountIds: [] },
  lockedAccounts: new Set(),
};

const NONE: OrderConstants = { createdAtMs: null, provenance: null, tradeGroupId: null };

/** A golden snapshot order as a row, its wire fields and creation constants overridden. */
function row(
  id: string,
  wire: Record<string, unknown> = {},
  constants: Partial<OrderConstants> = {},
): OrderRowModel {
  const item = { ...wsItem(snapshotBody(), id), ...wire };
  const mapped = mapOrder(item as never, "ws", directory(), { ...NONE, ...constants });
  if (mapped === null) throw new Error(`no row for ${id}`);
  return mapped;
}

const reasonOf = (r: OrderRowModel, context: Partial<CancelContext> = {}): string | null => {
  const gate = cancelGate(r, { ...CONTEXT, ...context });
  return gate.kind === "gated" ? gate.reason : null;
};

describe("a native-stop row's Cancel is T2 with sl.note as its reason (BQ-5, G-T2.1c)", () => {
  it("the Sub-2 stop (D01 D7's rule: a reduce-only stop loss on the exchange)", () => {
    const stop = row(STOP);
    expect(stop.protective.kind).toBe("native_stop");
    expect(cancelGate(stop, CONTEXT)).toEqual({
      kind: "gated",
      leg: "native_stop",
      reason: "Every position keeps a native stop — you can move it, not delete it.",
      scope: "row",
    });
    expect(reasonOf(stop)).toBe(DECK["sl.note"].string);
  });

  it("whatever else holds: an Owner, the kill switch, a cancel in flight", () => {
    const stop = row(STOP, {}, { provenance: "recorded_stop" });
    expect(stop.protective).toEqual({ kind: "native_stop", via: "provenance" });
    const gate = cancelGate(stop, {
      ...CONTEXT,
      cancelling: new Set([STOP]),
      killSwitch: { state: "engaged", scope: "global", exchangeAccountIds: [] },
    });
    expect(gate).toMatchObject({ kind: "gated", leg: "native_stop" });
  });

  it("a scope leg still comes first: a Viewer's notice, never the stop's own reason", () => {
    expect(cancelGate(row(STOP), { ...CONTEXT, permissions: ["orders:read"] })).toMatchObject({
      leg: "permission",
      scope: "panel",
    });
  });
});

describe("the legs, in E09-D09 §2.1's order", () => {
  const order = row(ENTRY);
  it("view-as first, the target's name its one datum (rbac.view_as)", () => {
    const gate = cancelGate(order, {
      ...CONTEXT,
      viewAs: { user: "alex" },
      permissions: [],
      readOnlyAccounts: new Set([SUB1]),
      restReachable: false,
    });
    expect(gate).toEqual({
      kind: "gated",
      leg: "view_as",
      reason: "Read-only while viewing as alex.",
      scope: "panel",
    });
  });

  it("then the permission, the panel notice's orders:write line (rbac.permission)", () => {
    expect(
      cancelGate(order, { ...CONTEXT, permissions: ["orders:read"], restReachable: false }),
    ).toEqual({
      kind: "gated",
      leg: "permission",
      reason: "Your role can't place orders.",
      scope: "panel",
    });
  });

  it("then a read-only grant on the row's account, its header's notice", () => {
    const gate = cancelGate(order, {
      ...CONTEXT,
      readOnlyAccounts: new Set([SUB1]),
      restReachable: false,
    });
    expect(gate).toEqual({
      kind: "gated",
      leg: "account_read_only",
      reason: DECK["rbac.account_read_only"].string,
      scope: "account",
    });
    expect(cancelGate(row(ETH), { ...CONTEXT, readOnlyAccounts: new Set([SUB1]) }).kind).toBe(
      "allowed",
    );
  });

  it("then offline with REST unreachable: the deck's blotter.ui.unreachable (D02:397)", () => {
    expect(cancelGate(order, { ...CONTEXT, restReachable: false })).toEqual({
      kind: "gated",
      leg: "offline",
      reason: DECK["blotter.ui.unreachable"].string,
      scope: "panel",
    });
    expect(DECK["blotter.ui.unreachable"].string).toBe("Cannot reach server");
  });

  it("an account a cancel was refused on (403 account_scope_denied) stays T2, rbac.account (S-22)", () => {
    const denied = { ...CONTEXT, deniedAccounts: new Set([SUB1]) };
    expect(cancelGate(order, denied)).toEqual({
      kind: "gated",
      leg: "account",
      reason: "This account isn't assigned to you.",
      scope: "account",
    });
    // ahead of a read-only grant, after the permission; another account's rows stay cancellable
    expect(cancelGate(order, { ...denied, readOnlyAccounts: new Set([SUB1]) })).toMatchObject({
      leg: "account",
    });
    expect(cancelGate(order, { ...denied, permissions: [] })).toMatchObject({ leg: "permission" });
    expect(cancelGate(row(ETH), denied).kind).toBe("allowed");
  });

  it("scopeGate takes the account's legs only when one is named", () => {
    expect(scopeGate(CONTEXT)).toBeNull();
    expect(scopeGate({ ...CONTEXT, permissions: [] })?.kind).toBe("gated");
    expect(scopeGate({ ...CONTEXT, readOnlyAccounts: new Set([SUB2]) })).toBeNull();
    expect(scopeGate({ ...CONTEXT, readOnlyAccounts: new Set([SUB2]) }, SUB2)).toMatchObject({
      leg: "account_read_only",
    });
  });
});

describe("the bulk buttons' gate (D02 §8.3, D04 §4.1; design m3)", () => {
  it("the panel's legs first, whatever the accounts", () => {
    expect(bulkGate({ ...CONTEXT, permissions: [] }, [SUB1])).toMatchObject({ leg: "permission" });
    expect(bulkGate({ ...CONTEXT, restReachable: false }, [SUB1])).toMatchObject({
      leg: "offline",
    });
  });

  it("rbac.account_read_only once every account it would act on is read-only", () => {
    const readOnly = { ...CONTEXT, readOnlyAccounts: new Set([SUB1, SUB2]) };
    expect(bulkGate(readOnly, [SUB1, SUB2])).toEqual({
      kind: "gated",
      leg: "account_read_only",
      reason: "You can view this account, not trade it.",
      scope: "account",
    });
    // one tradable account among them: enabled, each read-only row left out on its own line
    expect(bulkGate(readOnly, [SUB1, MAIN])).toBeNull();
    expect(bulkGate(readOnly, [])).toBeNull();
  });
});

describe("the order's own kind (2b, the row's reason)", () => {
  it.each([
    ["untracked", "untracked", DECK["blotter.untracked"].string],
    ["held", "held", DECK["blotter.held"].string],
    ["quarantined", "quarantined", PROPOSED["blotter.quarantined"].string],
    ["unknown", "unknown", DECK["blotter.unknown"].string],
  ] as const)("%s", (lifecycle, leg, reason) => {
    const gate = cancelGate(row(ENTRY, { lifecycle_state: lifecycle }), CONTEXT);
    expect(gate).toEqual({ kind: "gated", leg, reason, scope: "row" });
  });

  it("a recorded take-profit: never cancelOrder while setPositionTpSl is not mounted (BQ-5)", () => {
    const tp = row(TP, {}, { provenance: "recorded_stop" });
    expect(tp.protective.kind).toBe("recorded_take_profit");
    expect(cancelGate(tp, CONTEXT)).toEqual({
      kind: "gated",
      leg: "recorded_take_profit",
      reason: "This take-profit is managed with its stop.",
      scope: "row",
    });
    // a take-profit placed as an order of its own is cancelled as any order (D02 §7's first route)
    expect(cancelGate(row(TP), CONTEXT).kind).toBe("allowed");
  });

  it("every PROPOSED reason is one sentence of at most 60 characters (G-T2.4)", () => {
    for (const reason of [PROPOSED["blotter.recorded_tp"].string]) {
      expect(reason.length).toBeLessThanOrEqual(60);
      expect(reason).toMatch(/^[^.]+\.$/);
    }
  });
});

describe("busy and ended are not T2 (E09-D09 §9.1)", () => {
  it("this client's cancel in flight, or the order's own cancel pending, is busy", () => {
    expect(cancelGate(row(ENTRY), { ...CONTEXT, cancelling: new Set([ENTRY]) })).toEqual({
      kind: "busy",
    });
    expect(cancelGate(row(ENTRY, { lifecycle_state: "cancel_pending" }), CONTEXT)).toEqual({
      kind: "busy",
    });
  });

  it("an unknown order whose cancel this client sent stays busy, never T2 (D02 §8.2)", () => {
    const sent = { ...CONTEXT, cancelling: new Set([ENTRY]) };
    expect(cancelGate(row(ENTRY, { lifecycle_state: "unknown" }), sent).kind).toBe("busy");
  });

  it.each(["filled", "cancelled", "rejected", "expired", "killed"])(
    "a %s row lingering has nothing left to cancel",
    (lifecycle) => {
      expect(cancelGate(row(ENTRY, { lifecycle_state: lifecycle }), CONTEXT)).toEqual({
        kind: "ended",
      });
    },
  );

  it.each(["submitting", "submitted", "triggered", "partially_filled", "amend_pending"])(
    "%s is cancellable (22: a step in flight is cancelled once it settles)",
    (lifecycle) => {
      expect(cancelGate(row(ENTRY, { lifecycle_state: lifecycle }), CONTEXT).kind).toBe("allowed");
    },
  );
});

describe("never a cancel leg: the kill switch and a lockout (C-2.6; D04 §4.2, D02 §10.3)", () => {
  it("an engaged kill switch covering the account, for the Owner or a Manager", () => {
    for (const scope of ["global", "accounts"] as const) {
      const killSwitch = { state: "engaged", scope, exchangeAccountIds: [SUB1] } as const;
      expect(cancelGate(row(ENTRY), { ...CONTEXT, killSwitch })).toEqual({ kind: "allowed" });
    }
    expect(cancelGate(row(ENTRY), { ...CONTEXT, killSwitch: { state: "unknown" } }).kind).toBe(
      "allowed",
    );
  });

  it("a risk lockout or a stale lock on the account", () => {
    expect(cancelGate(row(ENTRY), { ...CONTEXT, lockedAccounts: new Set([SUB1]) })).toEqual({
      kind: "allowed",
    });
    expect(scopeGate({ ...CONTEXT, lockedAccounts: new Set([SUB1]) }, SUB1)).toBeNull();
  });
});

describe("the amend's legs (PR3a; D02 §7, §10.3–§10.4, D01 D12, D04 §4.1)", () => {
  const AMEND: AmendContext = {
    ...CONTEXT,
    killSwitch: { state: "disengaged", scope: "global", exchangeAccountIds: [] },
    amends: new Map(),
    hasSteps: () => true,
    arm: NO_ARM,
    armKey: "Ctrl+Shift+T",
    role: "owner",
  };
  const ARMED: AmendContext = { ...AMEND, arm: { token: () => "arm-token-1" } };
  const ARM_LOCKED = {
    kind: "gated",
    leg: "arm",
    reason: "one-click off — Ctrl+Shift+T to arm",
    scope: "row",
  } as const;

  it("a field the order lacks has no Edit (form validity, not T2)", () => {
    expect(editGate(row(STOP), "price", AMEND)).toEqual({ kind: "absent" });
    expect(editGate(row(ETH), "trigger_price", AMEND)).toEqual({ kind: "absent" });
  });

  it("a native stop and a recorded take-profit are never amended (D-13; M19, M20)", () => {
    expect(editGate(row(STOP), "trigger_price", ARMED)).toEqual({
      kind: "gated",
      leg: "native_stop",
      reason: PROPOSED["blotter.ui.amend.native_stop"].string,
      scope: "row",
    });
    expect(commitGate(row(STOP), "qty", "0.050", ARMED)).toMatchObject({ leg: "native_stop" });
    const recorded = row(TP, {}, { provenance: "recorded_stop" });
    expect(editGate(recorded, "price", ARMED)).toMatchObject({
      leg: "recorded_take_profit",
      reason: PROPOSED["blotter.recorded_tp"].string,
    });
  });

  it("the scope legs come first, as a cancel's", () => {
    expect(editGate(row(ETH), "price", { ...ARMED, permissions: ["orders:read"] })).toMatchObject({
      leg: "permission",
      scope: "panel",
    });
    expect(editGate(row(ETH), "price", { ...ARMED, restReachable: false })).toMatchObject({
      leg: "offline",
    });
  });

  it("this client's amend: pending is in flight, unconfirmed is unknown (D02:320–321)", () => {
    const amending = (phase: "pending" | "unconfirmed"): AmendContext => ({
      ...ARMED,
      amends: new Map([[ETH, { phase }]]),
    });
    expect(editGate(row(ETH), "qty", amending("pending"))).toMatchObject({
      leg: "amend_in_flight",
      reason: DECK["blotter.amend_in_flight"].string,
    });
    expect(editGate(row(ETH), "qty", amending("unconfirmed"))).toMatchObject({
      leg: "unknown",
      reason: DECK["blotter.unknown"].string,
    });
  });

  it.each([
    ["amend_pending", "amend_in_flight"],
    ["submitting", "not_amendable"],
    ["cancel_pending", "not_amendable"],
    ["triggered", "not_amendable"],
    ["held", "held"],
    ["untracked", "untracked"],
    ["quarantined", "quarantined"],
    ["unknown", "unknown"],
  ])("an order %s takes no amend (D01 D12): %s", (lifecycle, leg) => {
    expect(editGate(row(ETH, { lifecycle_state: lifecycle }), "qty", ARMED)).toMatchObject({
      kind: "gated",
      leg,
    });
  });

  it("a final order lingering has nothing to amend", () => {
    expect(editGate(row(ETH, { lifecycle_state: "filled" }), "qty", ARMED)).toEqual({
      kind: "ended",
    });
  });

  it("no step, no editor: a step is never guessed", () => {
    expect(editGate(row(ETH), "qty", { ...ARMED, hasSteps: () => false })).toMatchObject({
      leg: "no_step",
      reason: PROPOSED["blotter.ui.amend.no_step"].string,
    });
  });

  it("a LIVE entry's price edit is T2 arm.locked until the session holds a token (M9)", () => {
    expect(editGate(row(ETH), "price", AMEND)).toEqual(ARM_LOCKED);
    expect(editGate(row(COND), "trigger_price", AMEND)).toEqual(ARM_LOCKED);
    expect(editGate(row(ETH), "price", ARMED)).toEqual({ kind: "allowed" });
  });

  it("never the arm: a quantity cut, a take-profit's price, a demo entry (M7, M8, M10)", () => {
    expect(commitGate(row(ENTRY), "qty", "0.100", AMEND)).toEqual({ kind: "allowed" });
    expect(editGate(row(TP), "price", AMEND)).toEqual({ kind: "allowed" });
    expect(editGate(row(ETH, { environment: "demo" }), "price", AMEND)).toEqual({
      kind: "allowed",
    });
  });

  it("a quantity raised meets the arm at its commit, never before", () => {
    expect(editGate(row(ENTRY), "qty", AMEND)).toEqual({ kind: "allowed" });
    expect(commitGate(row(ENTRY), "qty", "0.200", AMEND)).toEqual(ARM_LOCKED);
    expect(commitGate(row(ENTRY), "qty", "0.200", ARMED)).toEqual({ kind: "allowed" });
  });

  it("an environment this client does not know is LIVE (M12)", () => {
    const unknown = mapOrder(
      { ...wsItem(snapshotBody(), ETH), environment: undefined } as never,
      "ws",
      new Map(),
      NONE,
    );
    expect(unknown?.environment).toBeNull();
    expect(editGate(unknown as OrderRowModel, "price", AMEND)).toEqual(ARM_LOCKED);
  });

  it("the arm is read on every call, never kept from an earlier one (M13 at the gate)", () => {
    let token: string | null = "arm-token-1";
    const context: AmendContext = { ...AMEND, arm: { token: () => token } };
    expect(editGate(row(ETH), "price", context)).toEqual({ kind: "allowed" });
    token = null;
    expect(editGate(row(ETH), "price", context)).toEqual(ARM_LOCKED);
  });

  it("under the kill switch: the Owner's frozen with its time, a Manager's E39-D01 line", () => {
    const killSwitch = { state: "engaged", scope: "global", exchangeAccountIds: [] } as const;
    const frozenAtMs = Date.parse("2026-10-31T14:02:11Z");
    expect(editGate(row(ETH), "price", { ...ARMED, killSwitch, frozenAtMs })).toEqual({
      kind: "gated",
      leg: "frozen",
      reason:
        "Trading frozen by the owner at 14:02 UTC — new orders off. Cancel and close still work.",
      scope: "row",
    });
    expect(editGate(row(ETH), "price", { ...ARMED, killSwitch, role: "manager" })).toMatchObject({
      leg: "frozen",
      reason: DECK["blotter.ui.frozen_control"].string,
    });
  });

  it("the kill switch and an account's lock never gate an exit: a cut, a take-profit (C-2.6)", () => {
    const killSwitch = { state: "engaged", scope: "global", exchangeAccountIds: [] } as const;
    const stale = new Map([
      [SUB1, { oms: { state: "stale", sinceMs: 0, episode: 1, killLock: false } }],
    ] as const);
    const locked: AmendContext = { ...AMEND, killSwitch, accountStates: stale };
    expect(commitGate(row(ENTRY), "qty", "0.100", locked)).toEqual({ kind: "allowed" });
    expect(editGate(row(TP), "price", locked)).toEqual({ kind: "allowed" });
  });

  it("an account reconciling, being verified or locked gates its new exposure (D04:460)", () => {
    const states = (oms: {
      state: "reconciling" | "desync" | "stale";
      killLock: boolean;
    }): AmendContext => ({
      ...ARMED,
      accountStates: new Map([[SUB1, { oms: { ...oms, sinceMs: 0, episode: 1 } }]]),
    });
    const reasonFor = (oms: Parameters<typeof states>[0]): unknown =>
      commitGate(row(ENTRY), "qty", "0.200", states(oms));
    expect(reasonFor({ state: "reconciling", killLock: false })).toMatchObject({
      leg: "recon",
      reason: DECK["recon.reconciling"].string,
    });
    expect(reasonFor({ state: "desync", killLock: false })).toMatchObject({
      reason: DECK["recon.desync"].string,
    });
    expect(reasonFor({ state: "stale", killLock: false })).toMatchObject({
      reason: DECK["recon.stale"].string,
    });
    expect(reasonFor({ state: "stale", killLock: true })).toMatchObject({
      reason: DECK["recon.killlock"].string,
    });
  });
});
