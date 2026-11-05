/**
 * E13-S01 (#423) S1: the words. Every deck entry `copy.ts` holds is the E13-D06 deck's, verbatim
 * (BQ-13); the validation templates reproduce d02.12.r19's sentences from the schema's own titles
 * and bounds; PROPOSED words keep G-T2.4's shape (one sentence, ≤ 60 characters, a full stop).
 */
import { describe, expect, it } from "vitest";
import {
  bind,
  DECK,
  DECK_VERSION,
  PROPOSED,
  PROPOSED_KEYS,
  rangeHelp,
  SETTINGS,
  settingsTitle,
  unavailableText,
  UNSUPPORTED_PARAM,
  validationText,
} from "../../../src/features/indicators/copy";
import {
  parseParamsSchema,
  type EditableField,
} from "../../../src/features/indicators/model/schema";
import { repoFile } from "../../lib/ws/support/schemaHarness";
import { BOLLINGER, CVD, EMA, ZIGZAG } from "./fixtures";

const deck = JSON.parse(repoFile("docs/design/E13/E13-D06-copy.json")) as {
  pack: string;
  version: string;
  base: string;
  strings: Record<string, { strings: string[]; reasons?: Record<string, string> }>;
};

const field = (raw: unknown, at = 0): EditableField => {
  const result = parseParamsSchema(raw);
  if (!result.ok) throw new Error("refused");
  return result.fields[at] as EditableField;
};

describe("the deck, verbatim", () => {
  it("names the deck version it copies", () => {
    expect(DECK_VERSION).toEqual({ pack: deck.pack, version: deck.version, base: deck.base });
  });

  it.each(Object.keys(DECK))("%s equals the deck's entry", (key) => {
    const ours = DECK[key as keyof typeof DECK] as {
      strings?: readonly string[];
      reasons?: Record<string, string>;
    };
    const theirs = deck.strings[key];
    if (ours.strings !== undefined) expect(ours.strings).toEqual(theirs?.strings);
    if (ours.reasons !== undefined) expect(ours.reasons).toEqual(theirs?.reasons);
  });

  it("marks PROPOSED only words the deck lacks, each a short sentence naming no data", () => {
    const every = Object.values(deck.strings).flatMap((e) => [
      ...e.strings,
      ...Object.values(e.reasons ?? {}),
    ]);
    for (const [key, text] of Object.entries(PROPOSED)) {
      expect(Object.keys(deck.strings)).not.toContain(key);
      expect(every).not.toContain(text);
      expect(text.length).toBeLessThanOrEqual(60);
      expect(text.endsWith(".")).toBe(true);
    }
  });

  it("marks the cap and lock reason keys PROPOSED as the deck does, with the owner (BQ-08)", () => {
    const status = deck.strings as Record<
      string,
      { key_status?: string; indicator_keys?: string[] }
    >;
    for (const [key, owner] of Object.entries(PROPOSED_KEYS)) {
      const row = Object.values(status).find((e) => e.indicator_keys?.includes(key));
      expect(row?.key_status).toBe("PROPOSED (D04 §10.2)");
      expect(owner).toBe("E09-D09 §3.1 registrar");
      expect(key.startsWith("rbac.")).toBe(false);
    }
  });

  it("writes no word for an entry with no compute path until BQ-02 (c) is ruled", () => {
    expect(Object.keys(PROPOSED)).toEqual([
      "indicator.param_whole",
      "indicator.param_choice",
      "indicator.schema_refused",
      "indicator.apply_refused",
    ]);
    expect(unavailableText("no_path")).toBeNull();
  });
});

describe("validationText reproduces d02.12.r19 from the schema (D02 D11)", () => {
  const [range, sdRange, sdStep, depth, deviation] = deck.strings["d02.12.r19"]?.strings ?? [];

  it("binds titles and bounds by name", () => {
    expect(validationText(field(EMA.params_schema), "maximum")).toBe(range);
    expect(validationText(field(BOLLINGER.params_schema, 1), "minimum")).toBe(sdRange);
    expect(validationText(field(BOLLINGER.params_schema, 1), "multipleOf")).toBe(sdStep);
    expect(validationText(field(ZIGZAG.params_schema), "minimum")).toBe(depth);
    expect(validationText(field(ZIGZAG.params_schema, 1), "maximum")).toBe(deviation);
    expect(validationText(field(BOLLINGER.params_schema, 1), "type")).toBe(sdRange);
  });

  it("uses the PROPOSED sentences where the deck has none", () => {
    expect(validationText(field(EMA.params_schema), "type")).toBe("Period must be a whole number.");
    expect(validationText(field(CVD.params_schema), "enum")).toBe(
      PROPOSED["indicator.param_choice"],
    );
  });
});

describe("the other words", () => {
  it("gives each unavailable reason its sentence (G-T2.4)", () => {
    expect(unavailableText("indicator.cap_instances")).toBe(
      "This chart has the maximum of 20 indicators.",
    );
    expect(unavailableText("indicator.cap_subpanes")).toBe(
      "This chart has the maximum of 6 sub-panes.",
    );
    expect(UNSUPPORTED_PARAM).toBe(deck.strings["d02.12.r21"]?.strings[0]);
  });

  it("bind replaces each span once and never re-reads a bound value", () => {
    expect(bind("{a} and {b}", { a: "{b}", b: "x" })).toBe("{b} and x");
    expect(bind("{missing}", {})).toBe("{missing}");
  });
});

describe("SCR-035's words (S4)", () => {
  const r = (key: string, at: number): string | undefined => deck.strings[key]?.strings[at];

  it("binds the header and the help lines to the deck's own examples", () => {
    expect(settingsTitle("EMA 21", "price", "5m")).toBe(r("d02.12.r15", 0));
    expect(rangeHelp({ kind: "integer", minimum: 1, maximum: 5000, step: 1 })).toBe(
      r("d02.12.r18", 0),
    );
    expect(rangeHelp({ kind: "number", minimum: 0.1, maximum: 10, step: 0.1 })).toBe(
      r("d02.12.r18", 1),
    );
  });

  it("takes every word from the deck or the PROPOSED list", () => {
    const every = new Set([
      ...Object.values(deck.strings).flatMap((e) => e.strings),
      ...Object.values(PROPOSED),
    ]);
    const words = Object.values(SETTINGS).flatMap((v) =>
      typeof v === "string" ? [v] : Object.values(v),
    );
    for (const word of words) expect(every).toContain(word);
  });
});
