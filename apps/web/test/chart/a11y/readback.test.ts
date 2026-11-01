import { describe, expect, it } from "vitest";
import {
  accountDirectory,
  keyboardOrderReadback,
  sumDecimals,
  type AccessibleAccount,
  type KeyboardOrderIntent,
} from "../../../src/chart/a11y/readback";

const MINE: readonly AccessibleAccount[] = [
  { id: "acc-main", name: "Main", env: "live" },
  { id: "acc-hedge", name: "Hedge", env: "live" },
];
const intent = (
  legs: KeyboardOrderIntent["legs"],
  over: Partial<KeyboardOrderIntent> = {},
): KeyboardOrderIntent => ({
  side: "buy",
  kind: "limit",
  symbol: "BTCUSDT",
  env: "live",
  price: "64010",
  legs,
  ...over,
});
const MAIN = { accountId: "acc-main", qty: "0.5" } as const;
const FOREIGN = { accountId: "acc-other-desk", qty: "3" } as const;

describe("keyboard-order read-back (05 §3.3.5; Gherkin 2's sentence)", () => {
  it("says kind, side, symbol, environment, price, each account: quantity, then the total", () => {
    const r = keyboardOrderReadback(
      intent([MAIN, { accountId: "acc-hedge", qty: "0.25" }], { unit: "BTC" }),
      MINE,
    );
    expect(r).toEqual({
      ok: true,
      lines: ["Main: 0.5 BTC", "Hedge: 0.25 BTC"],
      sentence:
        "Limit buy BTCUSDT, LIVE, at 64,010. Main: 0.5 BTC; Hedge: 0.25 BTC. 2 accounts, total 0.75 BTC",
    });
  });

  it("an aggressive sell to one demo account, no unit known", () => {
    const demo: AccessibleAccount[] = [{ id: "acc-hedge", name: "Hedge", env: "demo" }];
    const r = keyboardOrderReadback(
      intent([{ accountId: "acc-hedge", qty: "1200" }], {
        side: "sell",
        kind: "aggressive",
        env: "demo",
        price: "64009.5",
      }),
      demo,
    );
    expect(r.ok && r.sentence).toBe(
      "Aggressive sell BTCUSDT, DEMO, at 64,009.5. Hedge: 1,200. 1 account, total 1,200",
    );
  });

  it("a name ending in a digit never runs into its quantity", () => {
    const r = keyboardOrderReadback(intent([{ accountId: "a2", qty: "0.1" }]), [
      { id: "a2", name: "Account 2", env: "live" },
    ]);
    expect(r.ok && r.lines).toEqual(["Account 2: 0.1"]);
  });

  it("a leg outside the caller's access refuses the whole read-back and never names that account", () => {
    const r = keyboardOrderReadback(intent([MAIN, FOREIGN]), MINE);
    expect(r).toMatchObject({ ok: false, reason: "inaccessible" });
    expect(JSON.stringify(r)).not.toMatch(/other-desk|Main|0\.5|3/);
  });

  it("access is checked across every leg first: a zero or malformed leg never masks a foreign one (M1)", () => {
    for (const first of [
      { accountId: "acc-main", qty: "0" },
      { accountId: "acc-main", qty: "-1" },
    ]) {
      expect(keyboardOrderReadback(intent([first, FOREIGN]), MINE)).toMatchObject({
        ok: false,
        reason: "inaccessible",
      });
    }
  });

  it("ids match exactly: a near-miss id fails closed", () => {
    for (const accountId of [" acc-main", "ACC-MAIN", "acc-main "])
      expect(keyboardOrderReadback(intent([{ accountId, qty: "1" }]), MINE)).toMatchObject({
        ok: false,
        reason: "inaccessible",
      });
  });

  it("an account name known only elsewhere is never used: names come from the accessible set alone", () => {
    const r = keyboardOrderReadback(intent([{ accountId: "acc-main", qty: "1" }]), [
      { id: "acc-main", name: "Main", env: "live" },
    ]);
    expect(r.ok && r.lines).toEqual(["Main: 1"]);
    const others: AccessibleAccount[][] = [[], [{ id: "acc-hedge", name: "Hedge", env: "live" }]];
    for (const accessible of others) {
      const refused = keyboardOrderReadback(
        intent([{ accountId: "acc-main", qty: "1" }]),
        accessible,
      );
      expect(refused.ok).toBe(false);
      expect(refused.sentence).not.toMatch(/acc-main|Main|Hedge/);
    }
  });

  it("an account listed twice is refused, not read as two accounts (M2, sec 3)", () => {
    const r = keyboardOrderReadback(intent([MAIN, { accountId: "acc-main", qty: "2" }]), MINE);
    expect(r).toEqual({
      ok: false,
      reason: "duplicate",
      sentence: "Order not shown: an account is listed twice",
    });
  });

  it("an account in another environment is refused generically (sec 1, C-2.11)", () => {
    const mixed: AccessibleAccount[] = [
      { id: "acc-main", name: "Main", env: "live" },
      { id: "acc-paper", name: "Paper", env: "demo" },
    ];
    const r = keyboardOrderReadback(intent([MAIN, { accountId: "acc-paper", qty: "1" }]), mixed);
    expect(r).toMatchObject({ ok: false, reason: "env" });
    expect(r.sentence).not.toMatch(/Main|Paper|acc-|LIVE|DEMO/);
    expect(keyboardOrderReadback(intent([MAIN], { env: "demo" }), MINE)).toMatchObject({
      reason: "env",
    });
  });

  it("names that read alike, a repeated id or a blank name refuse the read-back (sec 2, code m3)", () => {
    const sets: AccessibleAccount[][] = [
      [MINE[0] as AccessibleAccount, { id: "x", name: "MAIN", env: "live" }],
      [MINE[0] as AccessibleAccount, { id: "x", name: "Ma\u200bin", env: "live" }],
      [MINE[0] as AccessibleAccount, { id: "x", name: " Main\t", env: "live" }],
      [MINE[0] as AccessibleAccount, { id: "x", name: "\uff2dain", env: "live" }],
      [MINE[0] as AccessibleAccount, { id: "x", name: "\u200b\u0007", env: "live" }],
      [MINE[0] as AccessibleAccount, { id: "acc-main", name: "Other", env: "live" }],
    ];
    for (const accessible of sets) {
      const r = keyboardOrderReadback(intent([MAIN]), accessible);
      expect(r).toEqual({
        ok: false,
        reason: "ambiguous",
        sentence: "Order not shown: account names are ambiguous",
      });
      expect(accountDirectory(accessible)).toBeNull();
    }
  });

  it("a name is said cleaned: format characters dropped, control characters and space runs as one space", () => {
    const r = keyboardOrderReadback(intent([MAIN]), [
      { id: "acc-main", name: " Main\u200e\t\tDesk ", env: "live" },
    ]);
    expect(r.ok && r.lines).toEqual(["Main Desk: 0.5"]);
  });

  it("a zero, negative or malformed price is refused (sec 5)", () => {
    for (const price of ["0", "0.00", "-5", "", "1e3"])
      expect(keyboardOrderReadback(intent([MAIN], { price }), MINE)).toMatchObject({
        ok: false,
        reason: "invalid",
      });
  });

  it("a malformed quantity, symbol or unit is a refusal, never a throw, and the value is not echoed (sec 6)", () => {
    for (const qty of ["-1", "", "1e-7", ".5", "NaN"]) {
      const r = keyboardOrderReadback(intent([{ accountId: "acc-main", qty }]), MINE);
      expect(r).toEqual({
        ok: false,
        reason: "invalid",
        sentence: "Order not shown: a price or quantity is not valid",
      });
    }
    for (const over of [{ symbol: "BTC USDT; sell all" }, { unit: "btc " }])
      expect(keyboardOrderReadback(intent([MAIN], over), MINE)).toMatchObject({
        reason: "invalid",
      });
  });

  it("no legs, or a zero quantity, is refused (nothing to confirm)", () => {
    expect(keyboardOrderReadback(intent([]), MINE)).toMatchObject({ ok: false, reason: "empty" });
    expect(
      keyboardOrderReadback(intent([{ accountId: "acc-main", qty: "0.000" }]), MINE),
    ).toMatchObject({ ok: false, reason: "zero" });
  });
});

describe("sumDecimals: exact", () => {
  it("adds without float error, across scales; a non-decimal throws without echoing it", () => {
    expect(sumDecimals(["0.1", "0.2"])).toBe("0.3");
    expect(sumDecimals(["1", "0.001"])).toBe("1.001");
    expect(sumDecimals(["99999999999999999", "1"])).toBe("100000000000000000");
    expect(sumDecimals(["0.05", "0.05"])).toBe("0.10");
    expect(sumDecimals([])).toBe("0");
    expect(() => sumDecimals(["1e3"])).toThrow(/^not a non-negative decimal$/);
  });
});
