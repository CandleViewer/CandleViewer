import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, expectTypeOf, it } from "vitest";
import { canonicalise, compareWithServer, hash } from "../src/canonical/canonicalise.js";
import { sha256Hex } from "../src/sha256.js";

// Written and byte-checked by services/api/tests/rules/roundtrip/test_client_hash_vectors.py.
type V = { name: string; ir: string; js: boolean; canonical?: string; ir_hash?: string };
type File = { $note: string; vectors: V[] };
const FILE = join(import.meta.dirname, "..", "..", "fixtures/golden/rule-ir/hash_vectors.json");
const { $note, vectors } = JSON.parse(readFileSync(FILE, "utf8")) as File;
const vector = (name: string) => vectors.find((v) => v.name === name) as V;
const hashed = vectors.filter((v) => v.canonical !== undefined);
const sendable = hashed.filter((v) => v.js);
const refused = vectors.filter((v) => v.name.startsWith("refused/") && v.js);
// A js:false row holds what JSON.stringify never sends: skipped by name, a $note reason each.
const SKIPPED = {
  "quirk/const-one-point-zero": "C-Q2, a JSON 1.0 or 0.0 const reads as true or false",
  "quirk/const-zero-point-zero": "C-Q2, a JSON 1.0 or 0.0 const reads as true or false",
  "refused/metric-param-nan": "the client mirror is held to the js:true vectors only",
  "refused/action-param-nan": "the client mirror is held to the js:true vectors only",
};
const refusal = expect.objectContaining({ name: "RuleGraphError", code: "SCHEMA_VIOLATION" });
const BASE = JSON.parse(vector("edge/base").ir) as Record<string, unknown>;

/** edge/base with `value` at `path`, or without that key when `value` is undefined. */
function edited(path: readonly (string | number)[], value: unknown): Record<string, unknown> {
  type Node = Record<string | number, unknown>;
  const doc = structuredClone(BASE);
  const parent = path.slice(0, -1).reduce<Node>((node, step) => node[step] as Node, doc);
  const last = path.at(-1) as string | number;
  if (value === undefined) delete parent[last];
  else parent[last] = value;
  return doc;
}

/** `value` with every object's keys in a seeded order, at every depth; lists keep their order. */
function shuffled(value: unknown, seed: number): unknown {
  if (Array.isArray(value)) return value.map((item) => shuffled(item, seed));
  if (typeof value !== "object" || value === null) return value;
  const rank = (key: string) =>
    [...key].reduce((h, c) => Math.imul(h ^ (c.codePointAt(0) as number), 0x9e3779b1) >>> 0, seed);
  const entries = Object.entries(value).sort(([a], [b]) => rank(a) - rank(b));
  return Object.fromEntries(entries.map(([key, item]) => [key, shuffled(item, seed)]));
}

describe("canonicalise and hash", () => {
  it.each(sendable)("give $name the server's canonical bytes and ir_hash", (v) => {
    expect(canonicalise(JSON.parse(v.ir))).toBe(v.canonical);
    expect(hash(JSON.parse(v.ir))).toBe(v.ir_hash);
  });

  it.each(refused)("refuse $name as a SCHEMA_VIOLATION, as the server does", (v) => {
    expect(() => canonicalise(JSON.parse(v.ir))).toThrow(refusal);
  });

  it("skip only the js:false rows, each by name with a reason the file's $note gives", () => {
    expect(vectors.filter((v) => !v.js).map((v) => v.name)).toEqual(Object.keys(SKIPPED));
    for (const reason of Object.values(SKIPPED)) expect($note).toContain(reason);
  });

  it("give the same bytes with every object's keys reordered, at every depth", () => {
    for (const v of sendable) {
      for (const seed of [1, 2, 3]) {
        expect(canonicalise(shuffled(JSON.parse(v.ir), seed)), v.name).toBe(v.canonical);
      }
    }
  });

  it("strip the presentation and metadata fields at the top level only, as the server does", () => {
    const bare = edited(["editor"], undefined);
    delete bare["graph_layout"];
    const dressed = { ...BASE, editor: "graph", graph_layout: null, created_at: 1, updated_at: 2 };
    expect([canonicalise(bare), canonicalise(dressed)]).toEqual(Array(2).fill(canonicalise(BASE)));
    const params = { channel: "ui", graph_layout: { x: 1 }, editor: "graph" };
    expect(canonicalise(edited(["actions", 0, "params"], params))).toContain(
      '"params":{"channel":"ui","editor":"graph","graph_layout":{"x":"1"}}',
    );
  });

  it("fill the defaults, the limits and metric params factories included", () => {
    const left = '"left":{"account_id":null,"metric":"price","params":{},"symbol":null,';
    expect(canonicalise(edited(["conditions", "left"], { metric: "price" }))).toContain(left);
    expect(canonicalise(edited(["limits"], undefined))).toBe(vector("edge/base").canonical);
  });

  // edge/base: 34 values as rules/compiler/common.py:23-45 counts them; 4 deep at its action params.
  it("accept 20 000 values and 64 levels, and refuse one more of either", () => {
    const at = (key: string, value: unknown) => () =>
      canonicalise(edited(["actions", 0, "params", key], value));
    const deep = (n: number): unknown => (n === 0 ? 0 : [deep(n - 1)]);
    expect(at("pad", Array(19_965).fill(0))).not.toThrow(); // 34 + the list + 19 965 zeros
    expect(at("pad", Array(19_966).fill(0))).toThrow(refusal);
    expect(at("deep", deep(60))).not.toThrow(); // the 0 sits at depth 4 + 60
    expect(at("deep", deep(61))).toThrow(refusal);
  });

  it.each([
    ["a number of 1e21 or more", ["conditions", "right", "const"], 1e21],
    ["NaN", ["conditions", "right", "const"], Number.NaN],
    ["a fraction in an integer field", ["version"], 1.5],
    ["text in an integer field", ["version"], "7"],
    ["true in an integer field", ["version"], true],
    ["decimal text with an exponent", ["conditions", "tolerance"], "1e5"],
    ["decimal text in a spelling no vector pins", ["conditions", "tolerance"], ".5"],
    ["decimal text past 28 digits", ["conditions", "tolerance"], "1234567890.1234567890123456789"],
    ["decimal text past the exponent range", ["conditions", "tolerance"], `1${"0".repeat(1e6)}`],
    ["a UUID without its hyphens", ["rule_id"], "00000000000040008000000000000001"],
    ["a lone surrogate in a params key", ["actions", 0, "params", "\ud800"], 1],
    ["a lone surrogate deep in a params value", ["actions", 0, "params", "x"], [{ y: "a\udc00" }]],
    ["an operand of no kind", ["conditions", "right"], { params: {} }],
    ["a condition op that is not text", ["conditions", "op"], 5],
    ["a missing required field", ["trigger"], undefined],
    ["a list where an object belongs", ["scope"], []],
    ["an object where text belongs", ["name"], {}],
    ["a function, which JSON.stringify drops", ["actions", 0, "params", "x"], () => 0],
    ["an object that is not plain data", ["actions", 0, "params", "x"], new Date(0)],
  ] as const)("refuse %s as a SCHEMA_VIOLATION", (_case, path, value) => {
    expect(() => canonicalise(edited(path, value))).toThrow(refusal);
  });

  it("refuse a non-object document", () => expect(() => canonicalise([])).toThrow(refusal));

  it("match sha256Hex of every canonical form in the file to its ir_hash, js:false rows too", () => {
    for (const v of hashed) expect(sha256Hex(v.canonical as string), v.name).toBe(v.ir_hash);
  });
});

describe("compareWithServer", () => {
  it("says match for the same digest and mismatch for anything else, never a third outcome", () => {
    const digest = vector("edge/base").ir_hash as string;
    expect(compareWithServer(hash(BASE), digest)).toBe("match");
    expect(compareWithServer(digest, vector("edge/sent-version").ir_hash)).toBe("mismatch");
    expect(compareWithServer(digest, undefined)).toBe("mismatch");
    expect(compareWithServer(undefined, undefined)).toBe("mismatch");
    expect(compareWithServer("x", "x")).toBe("mismatch");
    expect(compareWithServer(Symbol("x"), digest)).toBe("mismatch");
    expectTypeOf(compareWithServer).returns.toEqualTypeOf<"match" | "mismatch">(); // tsc holds it
  });
});
