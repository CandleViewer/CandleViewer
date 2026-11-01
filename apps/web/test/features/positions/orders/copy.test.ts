/**
 * E29-S02 (#912) the Working-orders words: every merged design word `orders/copy.ts` holds is found
 * at its cited line (D06 §6: no string invented); each PROPOSED key (BQ-9) is out of the deck, so
 * the deck adopting one fails here until it moves to `DECK`; and no word carries the exchange's
 * text or an "already filled" (BQ-2, BQ-3).
 */
import { describe, expect, it } from "vitest";
import { DECK } from "../../../../src/features/positions/copy";
import {
  AGE_UNITS,
  bindProposed,
  ORDER_TEXT,
  PROPOSED,
  PURPOSE_WORDS,
  STATE_WORDS,
  type CitedText,
} from "../../../../src/features/positions/orders/copy";
import { repoFile } from "../../../lib/ws/support/schemaHarness";

const docs = {
  D01: repoFile("docs/design/E29/E29-D01.md").split("\n"),
  D02: repoFile("docs/design/E29/E29-D02.md").split("\n"),
  "E30-D02": repoFile("docs/design/E30/E30-D02.md").split("\n"),
} as const;
const e30Deck = JSON.parse(repoFile("docs/design/E30/E30-D06-copy.json")) as {
  strings: Record<string, { string: string; owner: string }>;
};
const deck = JSON.parse(repoFile("docs/design/E29/E29-D06-copy.json")) as {
  strings: Record<string, { string: string }>;
};

const lineOf = ({ source }: CitedText): string => {
  const [doc, line] = source.split(":") as [keyof typeof docs, string];
  return docs[doc][Number.parseInt(line, 10) - 1] ?? "";
};

describe("merged design words, each at its cited line", () => {
  it.each(Object.entries(STATE_WORDS))("D01 D2 %s is at its line", (_, cited) => {
    expect(lineOf(cited)).toContain(`| ${cited.string}`);
  });

  it.each(Object.entries({ ...ORDER_TEXT, ...PURPOSE_WORDS }))("%s is at its line", (_, cited) => {
    expect(lineOf(cited)).toContain(cited.string);
  });

  it("Index is E30's merged trigger-by label, cited as D02 cites Mark and Last", () => {
    const entry = e30Deck.strings["ticket.order.label.trigger_by.index"];
    expect(entry?.string).toBe(ORDER_TEXT.indexPrice.string);
    expect(entry?.owner).toContain("E30-D02");
    expect(ORDER_TEXT.indexPrice.source).toBe("E30-D02:243");
  });

  it("the side's glyph and its word are apart: D02:263 draws them together", () => {
    expect(lineOf(ORDER_TEXT.buy)).toContain(
      `${ORDER_TEXT.buyGlyph.string} ${ORDER_TEXT.buy.string}`,
    );
    expect(lineOf(ORDER_TEXT.sell)).toContain(
      `${ORDER_TEXT.sellGlyph.string} ${ORDER_TEXT.sell.string}`,
    );
    expect(ORDER_TEXT.buy.string).toBe("Buy");
    expect(ORDER_TEXT.sell.string).toBe("Sell");
  });

  it("the Age units are D02:272's examples", () => {
    const line = lineOf(AGE_UNITS.seconds);
    for (const example of ["38 s", "4 m", "1 h 12 m"]) expect(line).toContain(example);
  });

  it("D01 D2 keeps draft and validated out of the blotter, and words the other fifteen", () => {
    expect(docs.D01[175]).toContain("draft / validated  | not shown in the blotter");
    expect(Object.keys(STATE_WORDS)).toHaveLength(15);
  });
});

describe("PROPOSED keys (BQ-9), routed to E29-D03's copy owner", () => {
  it.each(Object.keys(PROPOSED))("%s is not in the deck yet", (key) => {
    expect(deck.strings[key]).toBeUndefined();
    expect(Object.hasOwn(DECK, key)).toBe(false);
  });

  it("each names its owner, its status and the gap it fills", () => {
    for (const entry of Object.values(PROPOSED)) {
      expect(entry).toMatchObject({ owner: "E29-D03", status: "PROPOSED", screen: "SCR-063" });
      expect(entry.gap.length).toBeGreaterThan(10);
    }
  });

  it("a T2 reason is one sentence of at most 60 characters with a full stop (G-T2.4)", () => {
    for (const key of ["blotter.quarantined", "blotter.not_amendable"] as const) {
      const reason = PROPOSED[key].string;
      expect(reason.length).toBeLessThanOrEqual(60);
      expect(reason).toMatch(/^[^.]+\.$/);
    }
  });

  it("the cancel toast names the side by its word, never its glyph", () => {
    const toast = bindProposed("blotter.ui.cancel.toast", {
      BTCUSDT: "ETHUSDT",
      Sell: "Buy",
      "0.250": "1.00",
      "64,800.0": "2,500.00",
      Main: "Sub-2",
    });
    expect(toast).toBe("Cancel sent: ETHUSDT Buy 1.00 at 2,500.00 on Sub-2.");
    for (const entry of Object.values(PROPOSED)) expect(entry.string).not.toMatch(/[▲▼]/);
  });

  it("binds by the spans its params name, never the fixture's", () => {
    expect(
      bindProposed("blotter.ui.orders_group", { Main: "Sub-2", LIVE: "DEMO", "3": "12" }),
    ).toBe("Sub-2 · DEMO · 12 orders");
    expect(bindProposed("blotter.ui.trigger.undirected", { Mark: "Last", "63,950.0": "1.5" })).toBe(
      "Last reaches 1.5",
    );
    expect(() => bindProposed("blotter.ui.bulk.cancel_title")).toThrow(/unbound 4/);
  });
});

describe("no exchange text, no translated race (BQ-2, BQ-3)", () => {
  const words = [
    ...Object.values(STATE_WORDS),
    ...Object.values(ORDER_TEXT),
    ...Object.values(PROPOSED),
  ].map((w) => w.string);
  it("no word, and no deck line, says the order was already filled", () => {
    const all = [...words, ...Object.values(DECK).map((entry) => entry.string)];
    for (const word of all) expect(word.toLowerCase()).not.toContain("already filled");
  });

  it("no word carries a ret_msg, a retCode or a server detail", () => {
    for (const word of words) expect(word).not.toMatch(/ret_?msg|ret_?code|detail/i);
  });
});
