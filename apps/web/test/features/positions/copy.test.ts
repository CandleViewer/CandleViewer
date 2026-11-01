/**
 * E29-S01 (#911) the words: every deck entry `copy.ts` holds is the E29-D06 deck's, byte for byte
 * (D06 §6, BQ-17: no string invented); the binder replaces the named spans only; the D02 strings the
 * deck does not key are found at their cited lines, and the Viewer's verbs at E09-D09 §3.2.
 */
import { describe, expect, it } from "vitest";
import {
  bindDeck,
  bindKinds,
  D02_TEXT,
  DECK,
  DECK_VERSION,
  PROPOSED_TEXT,
  RBAC_VERBS,
} from "../../../src/features/positions/copy";
import { repoFile } from "../../lib/ws/support/schemaHarness";

const deck = JSON.parse(repoFile("docs/design/E29/E29-D06-copy.json")) as {
  pack: string;
  version: string;
  base: string;
  strings: Record<string, unknown>;
};

describe("the deck, verbatim", () => {
  it("names the deck version it copies", () => {
    expect(DECK_VERSION).toEqual({ pack: deck.pack, version: deck.version, base: deck.base });
  });

  it.each(Object.keys(DECK))("%s equals the deck's entry", (key) => {
    expect(DECK[key as keyof typeof DECK]).toEqual(deck.strings[key]);
  });
});

describe("bindDeck", () => {
  it("replaces the account and environment spans, never the fixture's", () => {
    expect(bindDeck("blotter.ui.snapshot_failed", { "Sub-1": "Alice — demo", LIVE: "DEMO" })).toBe(
      "Could not load Alice — demo · DEMO",
    );
    expect(bindDeck("panel.no_longer_shown", { "{account}": "Sub-2" })).toBe(
      "No longer shown — access to Sub-2 was withdrawn.",
    );
    expect(bindDeck("rbac.permission", { "{verb}": RBAC_VERBS["orders:write"] })).toBe(
      "Your role can't place orders.",
    );
  });

  it("leaves a fixed span as written, and a bound value is never re-read", () => {
    expect(bindDeck("acct.stale.line", { "Sub-2": "LIVE desk", LIVE: "LIVE" })).toBe(
      "LIVE desk · LIVE is stale — CandleViewer could not reconcile it with Bybit for 2 minutes. New orders are locked until the owner resolves it; closing, cancelling and tightening stops still work.",
    );
  });

  it("refuses an unbound span, and binds a string without spans as written", () => {
    expect(() => bindDeck("blotter.ui.loading", { "Sub-1": "Main" })).toThrow(/unbound LIVE/);
    expect(bindDeck("blotter.ui.empty")).toBe("No open positions");
  });
});

describe("bindKinds", () => {
  it("binds each span by its kind, whatever fixture word the deck wrote", () => {
    expect(bindKinds("acct.stale.line.nocause", { label: "Desk A", environment: "DEMO" })).toBe(
      "Desk A · DEMO is stale — new orders are locked until the owner resolves it; closing, cancelling and tightening stops still work.",
    );
    expect(bindKinds("acct.announce.reconciling", { label: "Main" })).toBe(
      "Reconciling Main with Bybit. Closing, cancelling and tightening stops still work.",
    );
    expect(bindKinds("blotter.ui.filter_empty", { count: "3" })).toBe("No rows match 3 filters");
    expect(bindKinds("acct.marker.stale", { time: "09:01:02" })).toBe(
      "Stale — locked since 09:01:02 UTC",
    );
    expect(bindKinds("blotter.ui.empty", {})).toBe("No open positions");
  });

  it("refuses a span left unbound, and binds no placeholder kind", () => {
    expect(() => bindKinds("blotter.ui.loading", { label: "Main" })).toThrow(/unbound LIVE/);
    expect(() => bindKinds("panel.no_longer_shown", { label: "Main" })).toThrow(/unbound/);
  });
});

describe("PROPOSED words (BQ-15, G-W3)", () => {
  it("none is a deck string or a D02 string: each waits for E29-D03's copy owner", () => {
    const deck = Object.values(DECK).map((e) => e.string);
    const d02 = repoFile("docs/design/E29/E29-D02.md");
    for (const text of Object.values(PROPOSED_TEXT)) {
      expect(deck).not.toContain(text);
      expect(d02).not.toContain(text);
    }
  });
});

describe("strings the deck does not key", () => {
  const lines = repoFile("docs/design/E29/E29-D02.md").split("\n");

  it.each(Object.entries(D02_TEXT))("%s is at its D02 line", (_, { string, source }) => {
    const line = Number.parseInt(source.replace("D02:", ""), 10);
    expect(lines[line - 1]).toContain(string);
  });

  it("the Viewer's verbs are E09-D09 §3.2's", () => {
    const e09 = repoFile("docs/design/E09/E09-D09.md");
    expect(e09).toContain('`orders:write` → "place orders"');
    expect(e09).toContain('`positions:write` → "change positions"');
    expect(Object.keys(RBAC_VERBS)).toEqual(["positions:write", "orders:write"]);
  });
});
