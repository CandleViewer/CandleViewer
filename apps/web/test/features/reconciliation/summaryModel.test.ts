/**
 * E29-S07 (#1028) the while-you-were-offline summary (E29-D03 §4.6; the deck's `summary.*`): built
 * from the server's digest and the window's fills, never a guessed rule-action clause.
 */
import { describe, expect, it } from "vitest";
import {
  buildSummary,
  formatWindow,
  isReconnectPass,
  textOf,
  type SummaryAccount,
} from "../../../src/features/reconciliation/summaryModel";
import { digest } from "./support/digests";

const A = "a1000000-0000-4000-8000-00000000000a";
const B = "a1000000-0000-4000-8000-00000000000b";
const SUB1: SummaryAccount = { id: A, label: "Sub-1", env: "LIVE" };
const SUB2: SummaryAccount = { id: B, label: "Sub-2", env: "LIVE" };
const FROM = Date.UTC(2026, 10, 3, 14, 1, 30);
const TO = Date.UTC(2026, 10, 3, 14, 2, 11);
const WINDOW = { fromMs: FROM, toMs: TO };

describe("buildSummary (D03 §4.6)", () => {
  it("Reconnect with a correction: the fill is listed and linked to its row; line 2 points to the account", () => {
    const s = buildSummary({
      window: WINDOW,
      accounts: [SUB1],
      digests: new Map([[A, digest({ corrected: ["link-1"], counts: { corrected: 1 } })]]),
      fills: [{ accountId: A, orderId: "o-1", filled: true }],
    });
    expect(textOf(s.body)).toBe("While you were offline: 1 order filled.");
    expect(s.body?.find((x) => x.href !== undefined)).toEqual({
      text: "1 order filled",
      href: "/positions/order/o-1",
    });
    expect(textOf(s.line2)).toBe(
      "Offline 14:01:30–14:02:11 UTC · Sub-1: 1 change — review them in Positions.",
    );
    expect(s.line2?.at(-2)).toEqual({ text: "review them in Positions", href: `/positions/${A}` });
    expect(s.announce).toBe("Reconnected. 1 order filled while offline.");
  });

  it("The reassurance must be true: a repaired stop is named first, its account before the others", () => {
    const s = buildSummary({
      window: WINDOW,
      accounts: [SUB2, SUB1],
      digests: new Map([
        [B, digest({ exchange_account_id: B, corrected: ["x"] })],
        [A, digest({ sl_repaired: ["BTCUSDT"], corrected: ["y", "z"] })],
      ]),
      fills: [],
    });
    expect(textOf(s.line2)).toBe(
      "Offline 14:01:30–14:02:11 UTC · Sub-1: 3 changes, including 1 stop attached automatically — " +
        "review them in Positions · Sub-2: 1 change — review them in Positions.",
    );
  });

  it("no rule-action clause is ever shown, and nothing to report reads Reconnected alone", () => {
    const s = buildSummary({
      window: WINDOW,
      accounts: [SUB1],
      digests: new Map([[A, digest()]]),
      fills: [],
    });
    expect(s.body).toBeNull();
    expect(textOf(s.line2)).toBe("Offline 14:01:30–14:02:11 UTC.");
    expect(s.announce).toBe("Reconnected.");
    expect(JSON.stringify(s)).not.toMatch(/rule/);
  });

  it("with no digest of this reconnect, line 2 is summary.interim", () => {
    const periodic = digest({ trigger: "periodic", corrected: ["x"] });
    const s = buildSummary({
      window: WINDOW,
      accounts: [SUB1],
      digests: new Map([[A, periodic]]),
      fills: null,
    });
    expect(textOf(s.line2)).toBe(
      "Offline 14:01:30–14:02:11 UTC. Rule actions are not listed here yet — check your stops.",
    );
  });

  it("several orders, filled and partly filled, link to the Positions screen", () => {
    const s = buildSummary({
      window: WINDOW,
      accounts: [],
      digests: new Map(),
      fills: [
        { accountId: A, orderId: "o-1", filled: true },
        { accountId: A, orderId: "o-2", filled: true },
        { accountId: A, orderId: "o-3", filled: false },
      ],
    });
    expect(textOf(s.body)).toBe("While you were offline: 2 orders filled, 1 order partly filled.");
    expect(s.body?.filter((x) => x.href !== undefined).map((x) => x.href)).toEqual([
      "/positions",
      "/positions/order/o-3",
    ]);
    expect(s.announce).toBe(
      "Reconnected. 2 orders filled and 1 order partly filled while offline.",
    );
  });

  it("counts are the server's full lengths when the lists are cut", () => {
    const cut = digest({ corrected: ["a"], counts: { corrected: 300 } });
    const s = buildSummary({
      window: WINDOW,
      accounts: [SUB1],
      digests: new Map([[A, cut]]),
      fills: null,
    });
    expect(textOf(s.line2)).toContain("Sub-1: 300 changes");
  });

  it("a pass that read the exchange before the drop, or with no time, is not this reconnect's", () => {
    expect(isReconnectPass(digest({ confirmed_at: "2026-11-03T14:00:00Z" }), WINDOW)).toBe(false);
    expect(isReconnectPass(digest({ confirmed_at: "not a time" }), WINDOW)).toBe(false);
    expect(isReconnectPass(digest(), WINDOW)).toBe(true);
    expect(formatWindow(WINDOW)).toBe("14:01:30–14:02:11");
  });
});
