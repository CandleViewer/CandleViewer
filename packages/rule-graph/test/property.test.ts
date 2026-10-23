// AC5 (E37-T01): documents from the server's generator (ported in support/generate.ts) go through
// toGraph then toIr. Each comes back whole, every value kept, with the same canonical text and so
// the same hash, or a RuleGraphError refuses it for a limit the mirror documents: never a lossy
// result, and never a refusal the server does not share. The generator's parameters reach 1e30 and
// the mirror refuses a number of 1e21 or more (src/canonical/decimal.ts), so a share is refused
// there, after the whole check. The seed is fresh per run, printed, and named in each failure, as
// the server's suite does (CV_ROUNDTRIP_SEED); CV_RULE_GRAPH_SEED replays a run.
import { describe, expect, it } from "vitest";
import { isTree, readLayout, toGraph } from "../src/adapter/toGraph.js";
import { toIr } from "../src/adapter/toIr.js";
import { canonicalise } from "../src/canonical/canonicalise.js";
import { isRuleGraphError } from "../src/errors.js";
import { generator } from "./support/generate.js";

const COUNT = 10_000; // US-RULE-001: at least 10 000 documents per run
const SEED = Number(process.env["CV_RULE_GRAPH_SEED"] ?? Math.floor(Math.random() * 2 ** 31));
const sorted = (_: string, v: unknown) =>
  isTree(v) ? Object.fromEntries(Object.entries(v).sort()) : v;
/** The JSON text of `ir`, keys in order, with no graph_layout: every value toIr must keep. */
const whole = (ir: object) => JSON.stringify({ ...ir, graph_layout: null }, sorted);
// The only refusals: a number the mirror holds no form for (src/canonical/decimal.ts), and the size
// bounds it shares with the server (rules/compiler/common.py:17-20). Any other is a drift.
const KNOWN = [
  /^SCHEMA_VIOLATION: the number has no canonical decimal form$/,
  /^SCHEMA_VIOLATION: (the rule IR is over 20000 values|Over 1 000 nodes|The graph expands past)/,
];

describe("toGraph then toIr on documents from the server's generator (AC5)", () => {
  it("keep each document and its hash, or refuse it for a known limit", { timeout: 60_000 }, () => {
    console.info(`[rule-graph fuzz] seed=${SEED} documents=${COUNT}`);
    expect(Number.isSafeInteger(SEED), "CV_RULE_GRAPH_SEED must be an integer").toBe(true);
    const { rule } = generator(SEED);
    const seen: Record<string, number> = {};
    for (let i = 0; i < COUNT; i++) {
      const doc = rule(i % 3 === 2); // a third from the form subset, as the server's plan
      let outcome = "kept";
      try {
        const { ir } = toIr(toGraph(doc), readLayout(doc.graph_layout));
        expect(whole(ir), `seed ${SEED}, document ${i}`).toBe(whole(doc));
        // The canonical text, whose sha256 is hash(): the same text is the same hash.
        expect(canonicalise(ir), `seed ${SEED}, document ${i}`).toBe(canonicalise(doc));
      } catch (error) {
        if (!isRuleGraphError(error)) throw error;
        outcome = `${error.code}: ${error.message.replace(/^\$\S*: /, "")}`; // no path
      }
      seen[outcome] = (seen[outcome] ?? 0) + 1;
    }
    console.info(`[rule-graph fuzz] seed=${SEED} outcomes=${JSON.stringify(seen)}`);
    const other = Object.keys(seen).filter((k) => k !== "kept" && !KNOWN.some((re) => re.test(k)));
    expect(other, `seed ${SEED}: a refusal the server does not share`).toEqual([]);
    expect(seen["kept"], `seed ${SEED}: the refusals crowd out the checks`).toBeGreaterThan(
      COUNT / 2,
    );
  });
});
