/**
 * E29-S04 (#979) the fills' words: every `DECK` entry is the E29-D06 deck's, byte for byte, and the
 * deck's every `fills.*` key is held (D06 §6: no string invented); every lifted string is found at
 * its cited line of D03, D02 or D01 (BQ-5, BQ-13); the PROPOSED words are no deck string; the
 * binders replace the named spans only.
 */
import { describe, expect, it } from "vitest";
import {
  bindEntry,
  bindFills,
  D02_TEXT,
  D03_TEXT,
  DECK,
  DECK_VERSION,
  emptyOrderText,
  PROPOSED_TEXT,
  STATE_WORDS,
  type CitedText,
} from "../../../../src/features/positions/fills/copy";
import { repoFile } from "../../../lib/ws/support/schemaHarness";

const deck = JSON.parse(repoFile("docs/design/E29/E29-D06-copy.json")) as {
  pack: string;
  version: string;
  base: string;
  strings: Record<string, { string: string }>;
};
const lines = (doc: string): string[] => repoFile(`docs/design/E29/E29-${doc}.md`).split("\n");
const docs: Record<string, string[]> = { D01: lines("D01"), D02: lines("D02"), D03: lines("D03") };

describe("the deck, verbatim and whole", () => {
  it("names the deck version it copies", () => {
    expect(DECK_VERSION).toEqual({ pack: deck.pack, version: deck.version, base: deck.base });
  });

  it.each(Object.keys(DECK))("%s equals the deck's entry", (key) => {
    expect(DECK[key as keyof typeof DECK]).toEqual(deck.strings[key]);
  });

  it("holds every fills.* key the deck has (41)", () => {
    const keys = Object.keys(deck.strings).filter((k) => k.startsWith("fills."));
    expect(Object.keys(DECK)).toEqual(keys);
    expect(keys).toHaveLength(41);
  });
});

describe("strings the deck does not key, each at its cited line", () => {
  const cited: [string, CitedText][] = [
    ...Object.entries(D03_TEXT),
    ...Object.entries(D02_TEXT),
    ...Object.entries(STATE_WORDS),
  ];

  it.each(cited)("%s is at its line", (_, { string, source }) => {
    const [doc = "", line = "0"] = source.split(":");
    expect(docs[doc]?.[Number.parseInt(line, 10) - 1]).toContain(string);
  });

  it("a lifted string's bound spans are in it", () => {
    for (const [, text] of cited)
      for (const span of Object.keys(text.params ?? {})) expect(text.string).toContain(span);
  });

  it("the PROPOSED words are no deck or design string (G-W3)", () => {
    const all = Object.values(deck.strings).map((s) => s.string);
    for (const { string } of Object.values(PROPOSED_TEXT)) {
      expect(all).not.toContain(string);
      expect(docs["D03"]?.some((l) => l.includes(string))).toBe(false);
    }
  });
});

describe("the binders", () => {
  it("replace every named span with the caller's text, never the fixture's", () => {
    expect(
      bindFills("fills.title.order", {
        "…a3f2": "…9f00",
        BTCUSDT: "ETHUSDT",
        "▲ Buy": "▼ Sell",
        Main: "Desk",
        LIVE: "DEMO",
      }),
    ).toBe("Fills — order …9f00 · ETHUSDT ▼ Sell · Desk · DEMO");
    expect(
      bindFills("fills.sum.filled", { "0.250": "0.1", "0.250 BTC": "0.2 BTC", "3": "1" }),
    ).toBe("Filled 0.1 of 0.2 BTC · 1 fills");
  });

  it("a bound value is never read again as a span; an unbound span refuses", () => {
    expect(bindFills("fills.revoked", { "Sub-1": "Sub-1 · LIVE" })).toBe(
      "No longer shown — access to Sub-1 · LIVE was withdrawn.",
    );
    expect(() => bindFills("fills.footer")).toThrow(/unbound 3/);
    expect(bindFills("fills.chrome")).toBe("Time");
    expect(bindEntry({ string: "a b", params: { b: "fixed" } })).toBe("a b");
  });

  it("fills.empty.order takes the order's state word (BQ-5)", () => {
    expect(emptyOrderText("submitted")).toBe(DECK["fills.empty.order"].string);
    expect(emptyOrderText("cancelled")).toBe("No fills for this order yet — it is Cancelled.");
  });
});
