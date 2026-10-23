// AC5 (E37-T01): documents from the server's generator (ported in support/generate.ts) go through
// toGraph then toIr. Each comes back whole, every value kept, with the same canonical text and so
// the same hash, or a RuleGraphError refuses it: never a lossy result. The generator's parameters
// reach 1e30 and the mirror refuses a number of 1e21 or more (src/canonical/decimal.ts), so a share
// is refused there, after the whole check. The seed is fresh per run and printed, as the server's
// suite does (CV_ROUNDTRIP_SEED); CV_RULE_GRAPH_SEED replays a run.
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

describe("toGraph then toIr on documents from the server's generator (AC5)", () => {
  it("keep each document and its hash, or refuse it by name", { timeout: 60_000 }, () => {
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
    expect(seen["kept"]).toBeGreaterThan(COUNT / 2); // the refusals never crowd out the checks
  });
});
