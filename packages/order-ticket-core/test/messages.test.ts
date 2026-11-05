import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  BY_CODE_KEYS,
  DECK_STRINGS,
  PENDING,
  formatMessage,
  message,
  messageFor,
  summaryMessages,
  validate,
  type RuleId,
  type DeckKey,
  type Message,
} from "../src/index.js";
import { MATRIX } from "./matrix.js";
import { PENDING_ROW, RULE_KEYS } from "./ruleKeys.js";

/** Every deck key the table lists (its `PENDING` outcomes aside). */
const DECK_OUTCOMES: readonly string[] = Object.values(RULE_KEYS)
  .flat()
  .filter((k) => k !== PENDING_ROW);

interface DeckString {
  readonly string: string;
  readonly params?: readonly { readonly name: string }[];
}
interface Deck {
  readonly pack: string;
  readonly strings: Readonly<Record<string, DeckString>>;
  readonly by_code: Readonly<Record<string, Readonly<Record<string, string>>>>;
}

const DECK: Deck = JSON.parse(
  readFileSync(resolve(import.meta.dirname, "../../../docs/design/E30/E30-D06-copy.json"), "utf8"),
) as Deck;

const KEYS = Object.keys(DECK_STRINGS) as DeckKey[];

describe("messages: pinned to the E30-D06 deck (BQ 11)", () => {
  it("deck_isTheE30D06Pack", () => {
    expect(DECK.pack).toBe("E30-D06");
  });

  it.each(KEYS)("deckString_%s_existsVerbatimWithTheSameParams", (key) => {
    const entry = DECK.strings[key];
    expect(entry, `${key} is missing from the deck`).toBeDefined();
    expect(entry?.string, `${key} was reworded in the deck`).toBe(DECK_STRINGS[key].template);
    const pinned: { template: string; params?: readonly string[] } = DECK_STRINGS[key];
    expect((entry?.params ?? []).map((p) => p.name)).toEqual([...(pinned.params ?? [])]);
  });

  it("byCodeKeys_areStillTheKeysTheirDeckRowsName", () => {
    for (const [key, code] of Object.entries(BY_CODE_KEYS)) {
      expect(DECK.by_code[code]?.["order"], `${code}`).toBe(key);
    }
  });

  it("ruleKeys_everyKeyIsPinned_andEveryPinnedValidationKeyIsUsed", () => {
    const used = new Set<string>();
    for (const key of DECK_OUTCOMES) {
      expect(KEYS).toContain(key);
      used.add(key);
    }
    const summary = ["ticket.order.v.summary.heading", "ticket.order.v.submit.reason"];
    expect(KEYS.filter((k) => !used.has(k) && !summary.includes(k))).toEqual([]);
  });

  it("ruleKeys_aKeyOutsideV_isReachedOnlyThroughAByCodeRow", () => {
    for (const key of DECK_OUTCOMES) {
      if (!key.startsWith("ticket.order.v.")) expect(Object.keys(BY_CODE_KEYS)).toContain(key);
    }
  });

  it("formatMessage_fillsTheDeckTemplate", () => {
    expect(formatMessage(message("ticket.order.v.qty.lot", { min: "0.001", step: "0.001" }))).toBe(
      "Minimum 0.001, step 0.001.",
    );
    expect(formatMessage(message("ticket.order.v.sl.required"))).toBe(
      "Every position-opening order requires a stop-loss.",
    );
  });

  it("message_refusesParamsTheTemplateDoesNotTake", () => {
    expect(() => message("ticket.order.v.price.tick")).toThrow(RangeError);
    expect(() => message("ticket.order.v.price.tick", { tick: "1", extra: "2" })).toThrow(
      RangeError,
    );
    expect(() => message("ticket.order.v.qty.lot", { min: "1", stepp: "1" })).toThrow(RangeError);
  });

  it("formatMessage_refusesAMissingParam", () => {
    const broken: Message = { key: "ticket.order.v.price.tick", params: {} };
    expect(() => formatMessage(broken)).toThrow(RangeError);
  });

  it("summaryMessages_countTheProblems", () => {
    const { heading, reason } = summaryMessages(3);
    expect(formatMessage(heading)).toBe("Can't submit — 3 problems");
    expect(formatMessage(reason)).toBe("Fix 3 problems to submit");
  });

  it("messageFor_everyMatrixFailure_rendersExactlyTheOutcomesItsTableRowLists", () => {
    const seen = new Map<RuleId, Set<string>>();
    for (const row of MATRIX) {
      if (row.expect === "pass") continue;
      const hit = validate(row.draft, row.ctx).failures.find((f) => f.rule === row.rule);
      expect(hit, row.name).toBeDefined();
      if (hit === undefined) continue;
      const msg = messageFor(hit);
      if (msg.key !== null) expect(formatMessage(msg)).not.toMatch(/\{\w+\}/);
      const outcomes = seen.get(row.rule) ?? new Set<string>();
      seen.set(row.rule, outcomes.add(msg.key ?? PENDING_ROW));
    }
    for (const [rule, row] of Object.entries(RULE_KEYS) as [RuleId, readonly string[]][]) {
      expect([...(seen.get(rule) ?? [])].sort(), rule).toEqual([...row].sort());
    }
  });

  it("messageFor_fillsTheSentenceFromTheFailuresParams", () => {
    const at = (rule: RuleId, params: Record<string, string>) =>
      messageFor({ field: "qty", rule, code: null, params });
    const step = at("qty_step", { qty: "0.0125", step: "0.001", min: "0.001" });
    expect(step.key === null ? null : formatMessage(step)).toBe(
      "0.0125 is not a multiple of the 0.001 step.",
    );
    expect(at("invalid_stop_distance", { kind: "level", side: "short" }).key).toBe(
      "ticket.order.v.sl.side.short",
    );
    expect(at("take_profit_side", { side: "long" }).key).toBe("ticket.order.v.tp.side.long");
    expect(at("take_profit_side", { side: "short" }).key).toBe("ticket.order.v.tp.side.short");
    expect(at("reduce_only_no_position", { read: "unread" })).toBe(PENDING);
    expect(at("invalid_stop_distance", { kind: "non_positive", side: "long" })).toBe(PENDING);
    expect(at("take_profit_side", { kind: "non_positive", side: "short" })).toBe(PENDING);
    expect(at("tick_size", {})).toBe(PENDING);
  });

  it("pending_isFrozenAndCarriesNoKey", () => {
    expect(PENDING.key).toBeNull();
    expect(Object.isFrozen(PENDING)).toBe(true);
  });
});
