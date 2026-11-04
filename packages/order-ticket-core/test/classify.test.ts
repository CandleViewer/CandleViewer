import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  classify,
  closesSide,
  dec,
  knownQty,
  lte,
  reducibleSize,
  toPlain,
  type EntryReason,
  type OrderDraft,
  type OrderSide,
  type PositionRead,
  type TicketTarget,
} from "../src/index.js";
import { TARGET, draft, exitDraft, held, qty } from "./drafts.js";

const SEED = 984;
const LONG = held("long", "1.000");
const pct = (p: string) =>
  exitDraft("0", { sizing: { mode: "pct_position", pct: p, round_to_lot: true } });
/** The long read, moved to another symbol or account. */
const moved = (over: object): PositionRead =>
  LONG.status === "known" && LONG.position !== null
    ? { status: "known", position: { ...LONG.position, ...over } }
    : LONG;
const GROUP: TicketTarget = { kind: "group", accountIds: [TARGET.accountId] };

/** Draft, read (and target) → the entry reason, or `null` for "not an entry". */
// prettier-ignore
const CASES: readonly (readonly [string, OrderDraft, PositionRead, EntryReason | null, TicketTarget?])[] = [
  ["not reduce-only, whatever the intent", draft({ intent: "flatten" }), held("short", "5"), "not_reduce_only"],
  ["reduce-only inside a known long", exitDraft("0.4"), LONG, null],
  ["reduce-only closing the whole long", exitDraft("1.000"), LONG, null],
  ["reduce-only above the long", exitDraft("1.001"), LONG, "exceeds_position"],
  ["an unread position (fail closed)", exitDraft("0.1"), { status: "unknown" }, "position_unknown"],
  ["no position", exitDraft("0.1"), { status: "known", position: null }, "no_position"],
  ["a same-side position", exitDraft("0.1"), held("short", "1"), "no_position"],
  ["a flat position", exitDraft("0.1"), held("flat", "0"), "no_position"],
  ["a zero-size long", exitDraft("0.1"), held("long", "0"), "no_position"],
  ["a malformed size", exitDraft("0.1"), held("long", "junk"), "no_position"],
  ["fixed_notional (qty unknown before sizing)", exitDraft("0.1", { sizing: { mode: "fixed_notional", notional_usd: "10", round_to_lot: true } }), LONG, "qty_unknown"],
  ["a qty of 0", exitDraft("0"), LONG, "qty_unknown"],
  ["a negative qty", exitDraft("-1"), LONG, "qty_unknown"],
  ["pct_position 0", pct("0"), LONG, "qty_unknown"],
  ["pct_position 100", pct("100"), held("long", "0.003"), null],
  ["pct_position 100.01", pct("100.01"), held("long", "0.003"), "exceeds_position"],
  ["(M1) a read on another symbol", exitDraft("0.5"), moved({ symbol: "ETHUSDT" }), "position_unknown"],
  ["(M1) a read on another account", exitDraft("0.5"), moved({ exchange_account_id: "other" }), "position_unknown"],
  ["(M1) a draft for another account", exitDraft("0.5", { exchangeAccountId: "other" }), LONG, "position_unknown"],
  ["(M1) a group target", exitDraft("0.5"), LONG, "position_unknown", GROUP],
  ["(L2) a side of hold", { ...exitDraft("0.5"), side: "hold" } as unknown as OrderDraft, LONG, "side_invalid"],
];

describe("classify (22:6576-6579, SR-E29-01)", () => {
  for (const [name, d, read, reason, target = TARGET] of CASES) {
    it(`classify: ${name}`, () => {
      const expected = reason === null ? { entry: false } : { entry: true, reason };
      expect(classify(d, read, target)).toMatchObject(expected);
    });
  }

  it("classify_aReducingOrder_carriesItsQtyAndThePositionSize", () => {
    const result = classify(exitDraft("0.4"), LONG, TARGET);
    expect(result.entry ? null : [toPlain(result.qty), toPlain(result.positionSize)]).toEqual([
      "0.4",
      "1.000",
    ]);
  });

  it("knownQty_pctPosition_isTheFlooredShareOfThePosition", () => {
    expect(toPlain(knownQty(pct("50"), dec("0.003")) ?? dec("-1"))).toBe("0.0015000");
    expect(knownQty(pct("0.000001"), dec("0.001"))).toBeNull();
  });

  it("closesSide_andReducibleSize_pairABuyWithAShort", () => {
    expect([closesSide("buy"), closesSide("sell")]).toEqual(["short", "long"]);
    expect(reducibleSize(draft(), { status: "unknown" }, TARGET)).toBe("unknown");
    expect(reducibleSize(draft(), LONG, TARGET)).toBeNull();
    const size = reducibleSize(draft(), held("short", "2"), TARGET);
    expect(size !== null && size !== "unknown" ? toPlain(size) : size).toBe("2");
  });

  it("classify_isNotAnEntry_onlyForAReduceOnlyQtyWithinAKnownOppositePosition", () => {
    const sides = fc.constantFrom<OrderSide>("buy", "sell");
    const posSides = fc.constantFrom("long" as const, "short" as const, "flat" as const);
    const amount = fc
      .integer({ min: -2, max: 5000 })
      .map((n) => toPlain({ units: BigInt(n), scale: 3 }));
    const args = [sides, posSides, amount, amount, fc.boolean(), fc.boolean()] as const;
    fc.assert(
      fc.property(...args, (side, posSide, size, q, ro, known) => {
        const read = known ? held(posSide, size) : ({ status: "unknown" } as const);
        const result = classify(draft({ side, reduceOnly: ro, ...qty(q) }), read, TARGET);
        const positive = dec(size).units > 0n && dec(q).units > 0n;
        const reduces =
          ro && known && posSide === closesSide(side) && positive && lte(dec(q), dec(size));
        expect(result.entry).toBe(!reduces);
      }),
      { seed: SEED, numRuns: 500 },
    );
  });
});
