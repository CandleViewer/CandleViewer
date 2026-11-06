/**
 * E42-S02 (#1023): SCR-121's capacity line as data (E42-D03 §7, board 91's seven states; §14 `cap.*`). The model is
 * the one the Accounts tile's line already reads, exported and extended: the at-capacity sentences and the warning
 * tone (AC5), CMP-023's meter only when `used` and `cap` were both read, its value text, and the line's action
 * ([Change] a recorded tier, [Record tier] an unrecorded one, [Retry] a failed read).
 */
import { describe, expect, it } from "vitest";
import type { AdminReadState, ReadEntry } from "../../../../src/features/admin/overview/readStore";
import { accountsTile, capacityModel } from "../../../../src/features/admin/overview/tileModels";

const T0 = Date.UTC(2026, 9, 22, 14, 2, 11);
const IDLE = { phase: "idle", inFlight: false } as const;
function state(capacity: Partial<ReadEntry<unknown>>): AdminReadState {
  const ids = ["overview", "capacity", "health", "flags", "audit", "backups", "invites"] as const;
  return Object.fromEntries(
    ids.map((id) => [id, { ...IDLE, ...(id === "capacity" ? capacity : {}) }]),
  ) as unknown as AdminReadState;
}
const read = (subaccounts: unknown) => state({ phase: "ok", data: { subaccounts }, okAt: T0 });
const RECORDED = {
  status: "ok",
  tier: "regular",
  cap: 5,
  tier_source: "recorded",
  recorded_at: "2026-09-12T09:00:00Z",
};
const AT_CAPACITY = [
  "Bybit allows 5 sub-accounts on your tier — you've used 5.",
  "To add another, complete Business KYC verification with Bybit (cap 20), then record the new tier " +
    "here — or share an existing sub-account and accept that its users are not isolated from each other.",
];

describe("capacityModel (SCR-121's capacity line)", () => {
  it("loads until the capacity read answers", () => {
    expect(capacityModel(state({}))).toEqual({ state: "loading", retry: [] });
  });

  it("recorded: the line, [Change], and the meter with its value text", () => {
    expect(capacityModel(read({ ...RECORDED, used: 3 }))).toEqual({
      state: "recorded",
      line: "3 of 5 sub-accounts used · Regular tier, recorded 2026-09-12",
      action: "change",
      meter: { value: 3, max: 5, valueText: "3 of 5 sub-accounts used" },
      asOf: T0,
      retry: [],
    });
  });

  it("at capacity (AC5): the warning tone and cap.at_capacity's two sentences under the line", () => {
    expect(capacityModel(read({ ...RECORDED, used: 5 }))).toEqual({
      state: "at_capacity",
      tone: "warning",
      line: "5 of 5 sub-accounts used · Regular tier, recorded 2026-09-12",
      detail: AT_CAPACITY,
      action: "change",
      meter: { value: 5, max: 5, valueText: "5 of 5 sub-accounts used" },
      asOf: T0,
      retry: [],
    });
  });

  it("over the cap (D12): the warning tone, [Change], the meter", () => {
    expect(capacityModel(read({ ...RECORDED, used: 6 }))).toMatchObject({
      state: "over",
      tone: "warning",
      line:
        "6 sub-accounts in use · Regular tier allows 5. Bybit lets accounts keep sub-accounts made " +
        "before 14 August 2026 — or the recorded tier may be wrong.",
      action: "change",
      meter: { value: 6, max: 5, valueText: "6 of 5 sub-accounts used" },
    });
  });

  it("unrecorded: no cap and no meter, [Record tier]", () => {
    const model = capacityModel(
      read({ status: "ok", tier: null, cap: null, used: 3, tier_source: "unrecorded" }),
    );
    expect(model).toEqual({
      state: "unrecorded",
      line: "3 sub-accounts in use · Tier not recorded — record it to see your cap",
      action: "record",
      asOf: T0,
      retry: [],
    });
  });

  it("the tier unread: the count alone, no meter", () => {
    const model = capacityModel(read({ status: "error", used: 4, tier_source: "recorded" }));
    expect(model).toMatchObject({
      state: "tier_unavailable",
      line: "4 sub-accounts in use · cap unavailable right now",
    });
    expect(model.meter).toBeUndefined();
  });

  it("the count unread: the tier's cap alone, no meter", () => {
    const model = capacityModel(
      read({ status: "error", tier: "business_kyc", cap: 20, tier_source: "recorded" }),
    );
    expect(model).toMatchObject({
      state: "used_unavailable",
      line: "Business KYC tier allows 20 · sub-accounts in use: unavailable right now",
    });
    expect(model.meter).toBeUndefined();
  });

  it("neither: down; a failed read adds [Retry] on the capacity read", () => {
    expect(capacityModel(read({ status: "error" }))).toEqual({
      state: "down",
      line: "Sub-account capacity unavailable right now",
      retry: [],
    });
    expect(capacityModel(state({ phase: "failed", reason: "network" }))).toEqual({
      state: "down",
      line: "Sub-account capacity unavailable right now",
      action: "retry",
      retry: ["capacity"],
    });
  });

  it("not built: its own line, nothing to retry", () => {
    expect(capacityModel(state({ phase: "not_built" }))).toEqual({
      state: "not_built",
      line: "Sub-account capacity: Unavailable — not built yet",
      retry: [],
    });
  });

  it("the Accounts tile's line is the model's, unchanged at capacity", () => {
    const s = read({ ...RECORDED, used: 5 });
    const tile = accountsTile(
      { ...s, overview: { phase: "ok", inFlight: false, okAt: T0, data: {} } } as AdminReadState,
      "live",
    );
    expect(tile.note).toBe("5 of 5 sub-accounts used · Regular tier, recorded 2026-09-12");
    expect(tile.noteAsOf).toBe(T0);
  });
});
