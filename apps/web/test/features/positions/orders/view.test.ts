/**
 * E29-S02 PR2 (#912) the Working-orders tab's view helpers (`orders/view.ts`): the open-position keys
 * the tab selects from the positions store (a mark tick leaves them equal, code m5), the chip words
 * of this tab (the Side chip in the order's side, the orchestrator's ruling), and an order's account.
 */
import { describe, expect, it } from "vitest";
import type { FilterChip } from "../../../../src/features/positions/model/filters";
import {
  accountOf,
  chipsInOrderWords,
  openPositionFrom,
  openPositionKeys,
  orderChipLabel,
} from "../../../../src/features/positions/orders/view";
import { directory, MAIN, SUB1, SUB2 } from "./support/orders";

type Book = Parameters<typeof openPositionKeys>[0];
const position = (accountId: string, symbol: string, positionIdx: number, mark: string) =>
  ({ accountId, symbol, positionIdx, markPrice: mark }) as unknown as Book["rows"][number];

describe("the open positions the tab reads (code m5)", () => {
  const book = (mark: string, source: Book["source"] = "ws"): Book => ({
    source,
    rows: [position(SUB2, "BTCUSDT", 1, mark), position(MAIN, "BTCUSDT", 0, mark)],
  });

  it("a mark tick leaves the keys equal, so the store's selector re-renders nothing", () => {
    const before = openPositionKeys(book("64012"));
    expect(openPositionKeys(book("64100"))).toBe(before);
    expect(before).toBe(`${MAIN}|BTCUSDT|0\n${SUB2}|BTCUSDT|1`);
  });

  it("answers a position open or not once the book is read, nothing before", () => {
    expect(openPositionKeys(book("1", "none"))).toBeNull();
    expect(openPositionFrom(null)).toBeUndefined();
    const open = openPositionFrom(openPositionKeys(book("1")));
    expect(open?.(SUB2, "BTCUSDT", 1)).toBe(true);
    expect(open?.(SUB2, "BTCUSDT", 0)).toBe(false);
    expect(openPositionFrom("")?.(MAIN, "BTCUSDT", 0)).toBe(false); // a book read and empty
  });
});

describe("the chips in this tab's words (the orchestrator's Side ruling)", () => {
  const accounts = directory();
  it.each([
    ["long", "Side: Buy"],
    ["short", "Side: Sell"],
  ] as const)("a Side chip of %s reads %s", (value, words) => {
    expect(orderChipLabel({ kind: "side", value }, accounts)).toBe(words);
  });

  it("the other chips read as the panel's; restated with them", () => {
    const chips: readonly FilterChip[] = [
      { kind: "account", value: SUB1 },
      { kind: "side", value: "short" },
    ];
    expect(orderChipLabel(chips[0] as FilterChip, accounts)).toBe("Account: Sub-1");
    expect(chipsInOrderWords(chips, accounts)).toBe("Account: Sub-1 · Side: Sell");
  });
});

describe("an order's account (design n4)", () => {
  it("its label, else an ellipsis and its id's last four, never the whole id", () => {
    expect(accountOf({ accountLabel: "Main", accountId: MAIN })).toBe("Main");
    expect(accountOf({ accountLabel: null, accountId: MAIN })).toBe("…0001");
  });
});
