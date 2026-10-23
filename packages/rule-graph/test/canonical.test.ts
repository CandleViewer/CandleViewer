import { readFileSync } from "node:fs";
import { join } from "node:path";
import { RULE_IR_SCHEMA } from "@candleviewer/protocol/rule-ir";
import { describe, expect, expectTypeOf, it } from "vitest";
import {
  byCodePoint,
  canonicalise,
  compareWithServer,
  hash,
} from "../src/canonical/canonicalise.js";
import { sha256Hex } from "../src/sha256.js";

// Written and byte-checked by services/api/tests/rules/roundtrip/test_client_hash_vectors.py.
type V = { name: string; ir: string; js: boolean; canonical?: string; ir_hash?: string };
type Vectors = { $note: string; vectors: V[] };
const FILE = join(import.meta.dirname, "..", "..", "fixtures/golden/rule-ir/hash_vectors.json");
const { $note, vectors } = JSON.parse(readFileSync(FILE, "utf8")) as Vectors;
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
const KIND = { name: "RuleGraphError", code: "SCHEMA_VIOLATION" };
/** A SCHEMA_VIOLATION whose message holds `where`: the refused value's path and a colon. */
const refusal = (where = "") =>
  expect.objectContaining({ ...KIND, message: expect.stringContaining(where) });
/** The path a refusal names for `path`: `$`, then `.key` or `[index]` per step. */
const at = (path: readonly (string | number)[]) =>
  `$${path.map((step) => (typeof step === "number" ? `[${step}]` : `.${step}`)).join("")}`;
const deep = (n: number) => Array.from({ length: n }).reduce<unknown>((v) => [v], 0);
const BASE = JSON.parse(vector("edge/base").ir) as Record<string, unknown>;
const params = (value: unknown) => canonicalise(edited(["actions", 0, "params"], value));
const tolerance = (text: string) => canonicalise(edited(["conditions", "tolerance"], text));

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
    expect(() => canonicalise(JSON.parse(v.ir))).toThrow(refusal());
  });

  it("skip only the js:false rows, each by name with a reason the file's $note gives", () => {
    const skipped = vectors.filter((v) => !v.js).map((v) => v.name);
    expect(skipped.sort()).toEqual(Object.keys(SKIPPED).sort());
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
    expect(params({ channel: "ui", graph_layout: { x: 1 }, editor: "graph" })).toContain(
      '"params":{"channel":"ui","editor":"graph","graph_layout":{"x":"1"}}',
    );
  });

  it("fill the defaults, the limits and metric params factories included", () => {
    const left = '"left":{"account_id":null,"metric":"price","params":{},"symbol":null,';
    expect(canonicalise(edited(["conditions", "left"], { metric: "price" }))).toContain(left);
    expect(canonicalise(edited(["limits"], undefined))).toBe(vector("edge/base").canonical);
  });

  it("keep ids under params as sent, and number the real nodes as if params held none", () => {
    const x = { l: [{ node_id: "c1" }], m: { node_id: "a1", ref: "c1" }, node_id: "z", ref: "a1" };
    const out = params({ x });
    expect(out).toContain(`"params":{"x":${JSON.stringify(x)}}`); // its keys are in order
    expect(out).toContain('"node_id":"n2","op":"gt"'); // the condition, after the action a1
  });

  it("sort keys by code point across the surrogate gap and astral planes, prefixes first", () => {
    const edges = [0xd7ff, 0xe000, 0xe001, 0xffff, 0x10000, 0x10fffe, 0x10ffff];
    const keys = ["", "a", "ab", "abc", ...edges.map((c) => String.fromCodePoint(c))];
    const out = params(Object.fromEntries([...keys].reverse().map((key) => [key, 1])));
    const { actions } = JSON.parse(out) as { actions: [{ params: object }] };
    expect(Object.keys(actions[0].params)).toEqual(keys);
  });

  it("compare ids as a number below, above or at zero, never NaN: a prefix first both ways round", () => {
    const signs = [byCodePoint("c1", "c10"), byCodePoint("c10", "c1"), byCodePoint("c1", "c1")];
    expect(signs.map(Math.sign)).toEqual([-1, 1, 0]); // an engine sort never shows a NaN or a 1 for 0
  });

  it("read plain decimal text as Python's Decimal does, zeros and 28 digits included", () => {
    const cases = { "00.5": "0.5", "007": "7", "0007.50": "7.5", "-0": "0", "-0.00": "0" };
    for (const [text, out] of Object.entries(cases))
      expect(tolerance(text)).toContain(`"tolerance":"${out}"`);
    const wide = [`1${"0".repeat(63)}`, `-0.${"0".repeat(60)}1`]; // plain_decimal.py's widest, 64
    for (const text of ["9".repeat(28), `0.${"9".repeat(28)}`, ...wide]) {
      expect(tolerance(text)).toContain(`"tolerance":"${text}"`);
    }
  });

  it("refuse every UUID spelling but the hyphenated one, though pydantic reads some", () => {
    const u = "00000000-0000-4000-8000-0000000000ab";
    for (const text of [u.replaceAll("-", ""), `{${u}}`, `urn:uuid:${u}`, `${u} `]) {
      expect(() => canonicalise(edited(["rule_id"], text)), text).toThrow(refusal("$.rule_id: "));
    }
  });

  it("keep __proto__ and constructor as plain keys, and read a null-prototype map", () => {
    const sent = JSON.parse('{"__proto__":{"p":true},"constructor":2,"y":1}') as object;
    expect(params(sent)).toContain('"params":{"__proto__":{"p":true},"constructor":"2","y":"1"}');
    expect(params(Object.assign(Object.create(null), { a: 1 }))).toContain('"params":{"a":"1"}');
  });

  // edge/base: 34 values as rules/compiler/common.py:23-45 counts them; 4 deep at its action params.
  it("accept 20 000 values and 64 levels, and refuse one more of either", () => {
    const put = (key: string, value: unknown) => () =>
      canonicalise(edited(["actions", 0, "params", key], value));
    expect(put("pad", Array(19_965).fill(0))).not.toThrow(); // 34 + the list + 19 965 zeros
    expect(put("pad", Array(19_966).fill(0))).toThrow(refusal("$: the rule IR is over"));
    expect(put("deep", deep(60))).not.toThrow(); // the 0 sits at depth 4 + 60
    expect(put("deep", deep(61))).toThrow(refusal("$: the rule IR is over"));
  });

  it("check the bounds first: a 100 000-level or circular map is refused, not a crash", () => {
    const loop: Record<string, unknown> = {};
    loop["self"] = loop;
    for (const x of [deep(100_000), loop]) {
      expect(() => params({ x })).toThrow(refusal("$: the rule IR is over"));
    }
  });

  it("refuse a dropped value, a hole or a lone surrogate at any depth, at its path", () => {
    expect(() => canonicalise({ ...BASE, name: undefined })).toThrow(refusal("$.name: "));
    expect(() => canonicalise({ ...BASE, description: undefined })).toThrow(
      refusal("$.description: "),
    );
    expect(() => params({ x: { y: undefined } })).toThrow(refusal("$.actions[0].params.x.y: "));
    expect(() => params({ x: Array(2) })).toThrow(refusal("$.actions[0].params.x[0]: "));
    expect(() => params({ x: { y: "a\udc00" } })).toThrow(refusal("$.actions[0].params.x.y: "));
    expect(() => params({ "\ud800": 1 })).toThrow(refusal("$.actions[0].params: "));
  });

  it.each([
    ["a number of 1e21 or more", ["conditions", "right", "const"], 1e21],
    ["NaN", ["conditions", "right", "const"], Number.NaN],
    ["a fraction in an integer field", ["version"], 1.5],
    ["text in an integer field", ["version"], "7"],
    ["true in an integer field", ["version"], true],
    ["decimal text with an exponent", ["conditions", "tolerance"], "1e5"],
    ["decimal text in a spelling no vector pins", ["conditions", "tolerance"], ".5"],
    ["decimal text with a plus sign", ["conditions", "tolerance"], "+1.5"],
    ["decimal text that ends in a point", ["conditions", "tolerance"], "5."],
    ["decimal text past 28 digits", ["conditions", "tolerance"], "1234567890.1234567890123456789"],
    ["decimal text a million digits wide", ["conditions", "tolerance"], `1${"0".repeat(1e6)}`],
    ["a fraction a million digits wide", ["conditions", "tolerance"], `0.${"0".repeat(1e6)}1`],
    ["a 65-character form, its sign counted", ["conditions", "tolerance"], `-1${"0".repeat(63)}`],
    ["an operand of no kind", ["conditions", "right"], { params: {} }],
    ["an op that is not text", ["conditions"], { node_id: "c", op: 5, left: { const: 1 } }],
    ["a missing required field", ["trigger"], undefined],
    ["an unknown key", ["limits", "zzz"], 1],
    ["a missing action params", ["actions", 0, "params"], undefined],
    ["a list where an object belongs", ["scope"], []],
    ["an object where text belongs", ["name"], {}],
    ["a function, which JSON.stringify drops", ["actions", 0, "params", "x"], () => 0],
    ["an object that is not plain data", ["actions", 0, "params", "x"], new Date(0)],
  ] as const)("refuse %s as a SCHEMA_VIOLATION at its path", (_case, path, value) => {
    expect(() => canonicalise(edited(path, value))).toThrow(refusal(`${at(path)}: `));
  });

  it("refuse a non-object document", () => expect(() => canonicalise([])).toThrow(refusal("$: ")));

  // emit numbers ids outside params and const and never rewrites `ref` (canonical.py:102 does), so
  // it matches the server only while no field is named ref and free-form maps are opaque or stripped.
  it("rely on no field named ref and on free-form maps only as params or graph_layout", () => {
    const free: string[] = [];
    const visit = (node: object, path: string): void => {
      for (const [key, child] of Object.entries(node)) {
        if (key === "properties") expect(Object.keys(child), path).not.toContain("ref");
        if (key === "additionalProperties" && child !== false) free.push(path);
        if (typeof child === "object" && child !== null) visit(child, `${path}/${key}`);
      }
    };
    visit(RULE_IR_SCHEMA, "#");
    const maps = ["#/$defs/Action/properties/params", "#/$defs/MetricRef/properties/params"];
    expect(free.sort()).toEqual([...maps, "#/properties/graph_layout/anyOf/0"]);
  });

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
    for (const odd of [digest.slice(1), `${digest}0`, digest.toUpperCase()]) {
      expect(compareWithServer(odd, odd), odd).toBe("mismatch"); // 63 or 65 digits, or upper case
    }
    expect(compareWithServer(new String(digest), digest)).toBe("mismatch"); // a boxed String
    expectTypeOf(compareWithServer).returns.toEqualTypeOf<"match" | "mismatch">(); // tsc holds it
  });
});
