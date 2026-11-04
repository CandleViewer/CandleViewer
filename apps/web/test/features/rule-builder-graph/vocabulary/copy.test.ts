import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  D05_COPY,
  E36_COPY,
  PROPOSED_COPY,
  TRIGGER_CLAUSES,
  VERBS,
  clauseOf,
  fill,
  text,
  verbOf,
} from "../../../../src/features/rule-builder-graph/model/vocabulary/copy.js";

const ROOT = resolve(import.meta.dirname, "../../../../../..");

interface DeckRow {
  readonly key?: string;
  readonly text?: string;
  readonly frozen?: string | null;
}

/** E36-D05's deck: one object, `strings` by key. */
const E36 = (
  JSON.parse(readFileSync(resolve(ROOT, "docs/design/E36/E36-D05-copy-deck.json"), "utf8")) as {
    strings: Record<string, DeckRow>;
  }
).strings;

/** E37-D05's deck: one JSON row per line, the first its header. */
const D05 = new Map(
  readFileSync(resolve(ROOT, "docs/design/E37/E37-D05-copy-deck.jsonl"), "utf8")
    .split("\n")
    .filter((line) => line.trim() !== "")
    .map((line) => JSON.parse(line) as DeckRow)
    .flatMap((row) => (row.key === undefined ? [] : [[row.key, row] as const])),
);

/** The rows the decks write as instances, with the values their figures stand for. */
const INSTANCES: Readonly<Record<string, Readonly<Record<string, string>>>> = {
  "rules.editor.announce.metrics": { n: "41" },
  "rules.editor.stop.kept": { price: "63,900.0" },
};

describe("the node library's copy, verbatim from the decks (E37-S02)", () => {
  it("each E36-D05 key reads as the deck does, byte for byte (an instance filled with its figures)", () => {
    for (const [key, template] of Object.entries(E36_COPY))
      expect(fill(template, INSTANCES[key]), key).toBe(E36[key]?.text);
  });

  it("Gherkin 'Estimated metrics are badged as text': the estimated word and name are E36-D05's", () => {
    expect(text("rules.editor.row.estimated")).toBe("(estimated)");
    expect(text("rules.editor.name.estimated", { "display name": "Market regime" })).toBe(
      "Estimated, Market regime",
    );
    expect(text("rules.editor.summary.estimated")).toBe(
      E36["rules.editor.summary.estimated"]?.text,
    );
  });

  it("each operator verb is E36-D05's rules.editor.verb.<op>, and only those", () => {
    const keyed = Object.keys(E36).filter((key) => key.startsWith("rules.editor.verb."));
    expect(Object.keys(VERBS).map((op) => `rules.editor.verb.${op}`)).toEqual(keyed);
    for (const [op, verb] of Object.entries(VERBS))
      expect(verb, op).toBe(E36[`rules.editor.verb.${op}`]?.text);
  });

  it("each E37-D05 row S02 renders reads as the deck does, the frozen ones under their FZ id", () => {
    for (const [key, words] of Object.entries(D05_COPY))
      expect(words, key).toBe(D05.get(key)?.text);
    const frozen = Object.keys(D05_COPY).flatMap((key) => D05.get(key)?.frozen ?? []);
    expect(frozen).toEqual(["FZ-6", "FZ-7", "FZ-8", "FZ-13"]);
  });

  it("the PROPOSED keys are in neither deck yet; the second-trigger reason fits the 80-character cap", () => {
    for (const key of Object.keys(PROPOSED_COPY))
      expect([E36[key], D05.get(key)], key).toEqual([undefined, undefined]);
    const longest = text("rules.graph.refusal.second_trigger", {
      name: "When the iceberg executed volume changes",
    });
    expect(longest).toBe(
      "This rule already has a trigger: When the iceberg executed volume changes.",
    );
    expect(longest.length).toBeLessThanOrEqual(80);
    expect(text("rules.graph.node.targets", { targets: "every account in the rule scope" })).toBe(
      "every account in the rule scope",
    );
  });

  it("each trigger clause is E36-D01 §5.6's (`docs/design/research/e36-rules-in-words.md`)", () => {
    const memo = readFileSync(resolve(ROOT, "docs/design/research/e36-rules-in-words.md"), "utf8");
    const row = memo.split("\n").find((line) => line.startsWith("| `Trigger.type`")) ?? "";
    const samples: Readonly<Record<string, Readonly<Record<string, string>>>> = {
      on_bar_close: { timeframe: "1m" },
      on_timer: { interval_ms: "60 s" },
      on_metric_change: { metric: "funding rate" },
    };
    const said = Object.entries(TRIGGER_CLAUSES).map(([id, clause]) => fill(clause, samples[id]));
    const position = said.filter((clause) => clause.startsWith("When a position "));
    expect(row).toContain(position.join(" / ").replace(/ \/ When a position /g, " / "));
    for (const clause of said.filter((c) => !position.includes(c)))
      expect(row, clause).toContain(`"${clause}"`);
  });

  it("an operator or a trigger with no copy reads by its id; an unfilled slot stays as written", () => {
    expect([verbOf("gt"), verbOf("zz_new_op"), clauseOf("on_timer"), clauseOf("zz")]).toEqual([
      "is above",
      "zz_new_op",
      "Every {interval_ms}",
      "zz",
    ]);
    expect(fill("{a} and {b}", { a: "1" })).toBe("1 and {b}");
    expect(fill("<b>{x}</b>", { x: "{y}" })).toBe("<b>{y}</b>"); // a value is text: never re-read
  });
});
