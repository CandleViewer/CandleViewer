import { describe, expect, it } from "vitest";
import {
  keyboardOrderReadback,
  sumDecimals,
  type AccessibleAccount,
  type KeyboardOrderIntent,
} from "../../../src/chart/a11y/readback";

const MINE: readonly AccessibleAccount[] = [
  { id: "acc-main", name: "Main" },
  { id: "acc-hedge", name: "Hedge" },
];
const intent = (
  legs: KeyboardOrderIntent["legs"],
  over: Partial<KeyboardOrderIntent> = {},
): KeyboardOrderIntent => ({
  side: "buy",
  kind: "limit",
  symbol: "BTCUSDT",
  price: "64010",
  legs,
  ...over,
});

describe("keyboard-order read-back (05 §3.3.5; Gherkin 2's sentence)", () => {
  it("says side, kind, symbol, price and every account with its resolved quantity, then the total", () => {
    const r = keyboardOrderReadback(
      intent([
        { accountId: "acc-main", qty: "0.5" },
        { accountId: "acc-hedge", qty: "0.25" },
      ]),
      MINE,
    );
    expect(r).toEqual({
      ok: true,
      lines: ["Main 0.5", "Hedge 0.25"],
      sentence: "Buy limit BTCUSDT at 64,010: Main 0.5; Hedge 0.25. 2 accounts, total 0.75",
    });
  });

  it("an aggressive sell to one account", () => {
    const r = keyboardOrderReadback(
      intent([{ accountId: "acc-hedge", qty: "1200" }], {
        side: "sell",
        kind: "aggressive",
        price: "64009.5",
      }),
      MINE,
    );
    expect(r.ok && r.sentence).toBe(
      "Sell aggressive BTCUSDT at 64,009.5: Hedge 1,200. 1 account, total 1,200",
    );
  });

  it("a leg outside the caller's access refuses the whole read-back and never names that account", () => {
    const r = keyboardOrderReadback(
      intent([
        { accountId: "acc-main", qty: "0.5" },
        { accountId: "acc-other-desk", qty: "3" },
      ]),
      MINE,
    );
    expect(r.ok).toBe(false);
    expect(r).toMatchObject({ reason: "inaccessible" });
    expect(JSON.stringify(r)).not.toMatch(/other-desk|Main|0\.5|3/);
  });

  it("an account name known only elsewhere is never used: names come from the accessible set alone", () => {
    const r = keyboardOrderReadback(intent([{ accountId: "acc-main", qty: "1" }]), [
      { id: "acc-main", name: "Main" },
    ]);
    expect(r.ok && r.lines).toEqual(["Main 1"]);
    for (const accessible of [[], [{ id: "acc-hedge", name: "Hedge" }]]) {
      const refused = keyboardOrderReadback(
        intent([{ accountId: "acc-main", qty: "1" }]),
        accessible,
      );
      expect(refused.ok).toBe(false);
      expect(refused.sentence).not.toMatch(/acc-main|Main|Hedge/);
    }
  });

  it("no legs, or a zero quantity, is refused (nothing to confirm)", () => {
    expect(keyboardOrderReadback(intent([]), MINE)).toMatchObject({ ok: false, reason: "empty" });
    expect(
      keyboardOrderReadback(intent([{ accountId: "acc-main", qty: "0.000" }]), MINE),
    ).toMatchObject({
      ok: false,
      reason: "zero",
    });
  });

  it("a malformed quantity throws rather than reading a wrong number", () => {
    expect(() =>
      keyboardOrderReadback(intent([{ accountId: "acc-main", qty: "-1" }]), MINE),
    ).toThrow(RangeError);
  });
});

describe("sumDecimals: exact", () => {
  it("adds without float error, across scales", () => {
    expect(sumDecimals(["0.1", "0.2"])).toBe("0.3");
    expect(sumDecimals(["1", "0.001"])).toBe("1.001");
    expect(sumDecimals(["99999999999999999", "1"])).toBe("100000000000000000");
    expect(sumDecimals(["0.05", "0.05"])).toBe("0.10");
    expect(sumDecimals([])).toBe("0");
    expect(() => sumDecimals(["1e3"])).toThrow(RangeError);
  });
});
