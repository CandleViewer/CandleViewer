/**
 * E29-S02 PR2 (#912) the cancel legs (`model/gates.ts`; E29-D04 §4.1–§4.2, D02 §8.2, §10.4): each
 * disabled-with-reason leg in E09-D09 §2.1's order, a native-stop row's Cancel T2 with `sl.note`'s
 * sentence (BQ-5, G-T2.1c), the order's own kinds, busy and ended, and the C-2.6 carve-out: the kill
 * switch and a lockout never gate a cancel.
 */
import { describe, expect, it } from "vitest";
import { DECK } from "../../../../src/features/positions/copy";
import { PROPOSED } from "../../../../src/features/positions/orders/copy";
import {
  bulkGate,
  cancelGate,
  scopeGate,
  type CancelContext,
} from "../../../../src/features/positions/orders/model/gates";
import {
  mapOrder,
  type OrderConstants,
  type OrderRowModel,
} from "../../../../src/features/positions/orders/model/orderRow";
import {
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
