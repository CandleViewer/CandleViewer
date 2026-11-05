import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  RULE_LIMITS,
  checkImportSelection,
  checkRuleShape,
  countValues,
  encodeRequestBody,
  jsonDepthExceeds,
  parseRuleJson,
  utf8ByteLength,
} from "../src/limits.js";

// SR-E36-13: each §5.1 bound at its edge (accepted) and one past it (refused, by name).
const nest = (levels: number): string => "[".repeat(levels) + "]".repeat(levels);
// Objects only: `{"a":{"a":...{}...}}`, so a scan that stops counting `{` cannot pass.
const nestObjects = (levels: number): string =>
  '{"a":'.repeat(levels - 1) + "{}" + "}".repeat(levels - 1);
const reason = (r: { ok: boolean; refusal?: { reason: string } }) =>
  r.ok ? "ok" : r.refusal?.reason;
const cmp = { node_id: "c", op: "gt", left: { metric: "m" }, right: { const: 1 } };
const all = (children: unknown[]) => ({ node_id: "g", op: "all_of", children });
const rule = (extra: Record<string, unknown>) => ({ ir_version: 1, actions: [{}], ...extra });

describe("the §5.1 numbers", () => {
  it("equal the server's and the threat model's", () => {
    expect(RULE_LIMITS).toEqual({
      importFiles: 100,
      importBytes: 20_000_000,
      bodyBytes: 2_000_000,
      irDepth: 65,
      bundleDepth: 66,
      values: 20_000,
      actions: 10,
      booleanChildren: 32,
      editableConditionNodes: 200,
      storableConditionNodes: 1_000,
      irVersion: 1,
    });
    expect(Object.isFrozen(RULE_LIMITS)).toBe(true);
  });
});

describe("checkImportSelection", () => {
  it("refuses by count first, then by the summed size, before any file is read", () => {
    expect(reason(checkImportSelection(Array<number>(100).fill(1)))).toBe("ok");
    expect(checkImportSelection(Array<number>(101).fill(0))).toEqual({
      ok: false,
      refusal: { reason: "import_files", limit: 100, measured: 101 },
    });
    expect(reason(checkImportSelection([10_000_000, 10_000_000]))).toBe("ok");
    expect(checkImportSelection([10_000_000, 10_000_001])).toEqual({
      ok: false,
      refusal: { reason: "import_bytes", limit: 20_000_000, measured: 20_000_001 },
    });
  });
});

describe("checkImportSelection sizes", () => {
  it.each([[Number.NaN], [-1], [Number.POSITIVE_INFINITY], [1.5], [2 ** 53]])(
    "refuses a size that is not a non-negative safe integer: %s",
    (size) => {
      expect(checkImportSelection([size])).toEqual({
        ok: false,
        refusal: { reason: "import_size", limit: null, measured: String(size) },
      });
      expect(reason(checkImportSelection([1, size]))).toBe("import_size");
    },
  );

  it("accepts zero and a safe integer", () => {
    expect(reason(checkImportSelection([0, 1, 19_999_999]))).toBe("ok");
  });

  it("does not let a negative size cancel a real overrun", () => {
    expect(reason(checkImportSelection([20_000_001, -1]))).toBe("import_size");
  });
});

describe("utf8ByteLength", () => {
  it.each([
    ["", 0],
    ["a", 1],
    ["é", 2],
    ["€", 3],
    ["😀", 4],
    ["\ud83d", 3], // a lone high surrogate encodes as U+FFFD
    ["\ud83dx", 4],
    ["\ude00", 3], // a lone low surrogate
  ])("measures %j as %i bytes", (text, bytes) => {
    expect(utf8ByteLength(text)).toBe(bytes);
  });

  it("equals the encoder's count on any string", () => {
    fc.assert(
      fc.property(fc.string({ unit: "binary" }), (text) => {
        expect(utf8ByteLength(text)).toBe(new TextEncoder().encode(text).length);
      }),
    );
  });
});

describe("jsonDepthExceeds", () => {
  it("counts container levels and ignores brackets inside strings and after escapes", () => {
    expect(jsonDepthExceeds(nest(3), 3)).toBe(false);
    expect(jsonDepthExceeds(nest(4), 3)).toBe(true);
    expect(jsonDepthExceeds(`["[[[[", "\\"[[[["]`, 1)).toBe(false);
    expect(jsonDepthExceeds(`[{"a":[1]},{"b":[2]}]`, 3)).toBe(false);
  });
});

describe("parseRuleJson", () => {
  it("refuses a body past 2,000,000 UTF-8 bytes before reading it, by its encoded size", () => {
    const at = `"${"a".repeat(RULE_LIMITS.bodyBytes - 2)}"`;
    expect(reason(parseRuleJson(at))).toBe("ok");
    expect(parseRuleJson(`"${"é".repeat(1_000_000)}"`)).toEqual({
      ok: false,
      refusal: { reason: "body_bytes", limit: 2_000_000, measured: 2_000_002 },
    });
  });

  it("allows 65 levels in an ir and 66 in a bundle, refusing one more before JSON.parse", () => {
    expect(reason(parseRuleJson(nest(65)))).toBe("ok");
    expect(parseRuleJson(nest(66))).toEqual({
      ok: false,
      refusal: { reason: "depth", limit: 65, measured: null },
    });
    expect(reason(parseRuleJson(nest(66), "bundle"))).toBe("ok");
    expect(reason(parseRuleJson(nest(67), "bundle"))).toBe("depth");
    // Object nesting counts the same: `{` opens a level as `[` does.
    expect(reason(parseRuleJson(nestObjects(65)))).toBe("ok");
    expect(parseRuleJson(nestObjects(66))).toEqual({
      ok: false,
      refusal: { reason: "depth", limit: 65, measured: null },
    });
    expect(reason(parseRuleJson(nestObjects(66), "bundle"))).toBe("ok");
    expect(parseRuleJson(nestObjects(67), "bundle")).toEqual({
      ok: false,
      refusal: { reason: "depth", limit: 66, measured: null },
    });
    // Unbalanced past the bound: still refused before the parser sees it.
    expect(reason(parseRuleJson("[".repeat(100_000)))).toBe("depth");
  });

  it("answers malformed JSON with a refusal, never a throw", () => {
    const out = parseRuleJson("{");
    expect(reason(out)).toBe("malformed_json");
    expect(out.ok ? null : typeof out.refusal.measured).toBe("string");
  });

  it("allows 20,000 values and refuses the 20,001st after parse", () => {
    const array = (n: number) => JSON.stringify(Array<number>(n - 1).fill(0));
    expect(parseRuleJson(array(20_000))).toEqual({ ok: true, value: Array(19_999).fill(0) });
    expect(parseRuleJson(array(20_001))).toEqual({
      ok: false,
      refusal: { reason: "values", limit: 20_000, measured: 20_001 },
    });
  });

  it("keeps a decimal served as text as text", () => {
    expect(parseRuleJson('{"const":"1.50"}')).toEqual({ ok: true, value: { const: "1.50" } });
  });
});

describe("countValues", () => {
  it("counts every object, array and scalar once, as check_bounds does", () => {
    expect(countValues(null)).toBe(1);
    expect(countValues({ a: [1, 2], b: { c: "x" } })).toBe(6);
    expect(countValues([1, 2, 3], 3)).toBe(4); // past the limit: limit + 1, early
  });

  it("refuses a wide container before stacking its children", () => {
    expect(countValues({ a: Array<number>(50).fill(0) }, 10)).toBe(11);
  });
});

describe("encodeRequestBody", () => {
  it("returns the encoded body, refusing one past the server's ceiling before sending", () => {
    expect(encodeRequestBody({ name: "r", ir: { a: "1.50" } })).toEqual({
      ok: true,
      value: '{"name":"r","ir":{"a":"1.50"}}',
    });
    const big = { note: "😀".repeat(500_000) }; // 2,000,000 bytes of note + 11 of wrapper
    expect(encodeRequestBody(big)).toEqual({
      ok: false,
      refusal: { reason: "body_bytes", limit: 2_000_000, measured: 2_000_011 },
    });
  });

  it("refuses a body with no JSON text as unencodable, never throwing", () => {
    const cyclic: Record<string, unknown> = { name: "r" };
    cyclic["ir"] = cyclic;
    for (const body of [cyclic, { n: 1n }, undefined, () => 1, Symbol("s")]) {
      expect(reason(encodeRequestBody(body))).toBe("unencodable");
    }
    expect(encodeRequestBody(undefined)).toEqual({
      ok: false,
      refusal: { reason: "unencodable", limit: null, measured: "no JSON text for undefined" },
    });
  });
});

describe("checkRuleShape", () => {
  it("refuses a non-object by its type", () => {
    expect(checkRuleShape([])).toEqual({
      ok: false,
      refusal: { reason: "not_an_object", limit: null, measured: "array" },
    });
    expect(checkRuleShape(null).ok ? null : "refused").toBe("refused");
  });

  it("maps ir_version 1 or none, and refuses any other by name, before anything else", () => {
    expect(reason(checkRuleShape(rule({ conditions: cmp })))).toBe("ok");
    expect(reason(checkRuleShape({ actions: [], conditions: cmp }))).toBe("ok");
    expect(checkRuleShape(rule({ ir_version: 2, actions: Array(99).fill({}) }))).toEqual({
      ok: false,
      refusal: { reason: "ir_version", limit: 1, measured: "2" },
    });
    expect(reason(checkRuleShape(rule({ ir_version: "1" })))).toBe("ir_version");
    expect(checkRuleShape(rule({ ir_version: 2n }))).toEqual({
      ok: false,
      refusal: { reason: "ir_version", limit: 1, measured: null },
    });
  });

  it("reads own members only: an inherited one neither adds nor hides a refusal", () => {
    const inherited = Object.create({
      ir_version: 2,
      actions: Array(11).fill({}),
      conditions: all(Array(33).fill(cmp)),
    }) as object;
    expect(checkRuleShape(inherited)).toEqual({
      ok: true,
      value: { conditionNodes: 0, editable: true },
    });
    const node = Object.create({ children: Array(33).fill(cmp) }) as object;
    expect(checkRuleShape(rule({ conditions: node }))).toEqual({
      ok: true,
      value: { conditionNodes: 1, editable: true },
    });
  });

  it("allows 10 actions and refuses an eleventh", () => {
    expect(reason(checkRuleShape(rule({ actions: Array(10).fill({}) })))).toBe("ok");
    expect(checkRuleShape(rule({ actions: Array(11).fill({}) }))).toEqual({
      ok: false,
      refusal: { reason: "actions", limit: 10, measured: 11 },
    });
  });

  it("allows 32 children of a boolean node and refuses a 33rd", () => {
    expect(reason(checkRuleShape(rule({ conditions: all(Array(32).fill(cmp)) })))).toBe("ok");
    expect(checkRuleShape(rule({ conditions: all(Array(33).fill(cmp)) }))).toEqual({
      ok: false,
      refusal: { reason: "boolean_children", limit: 32, measured: 33 },
    });
  });

  // `n` comparisons under `groups` all_of nodes of `per` children each, one root over them.
  const tree = (groups: number, per: number) =>
    rule({ conditions: all(Array(groups).fill(all(Array(per).fill(cmp)))) });

  it("edits 200 condition nodes and opens 201 read-only, counting operands as no node", () => {
    const at = tree(9, 21); // the root, 9 groups and 189 comparisons: 199
    const shape = (ir: unknown) => checkRuleShape(ir);
    expect(shape(at)).toEqual({ ok: true, value: { conditionNodes: 199, editable: true } });
    const wrapped = rule({
      conditions: all([
        ...Array(9).fill(all(Array(21).fill(cmp))),
        { op: "sustained_for", child: cmp },
      ]),
    });
    expect(shape(wrapped)).toEqual({ ok: true, value: { conditionNodes: 201, editable: false } });
    const two = rule({ conditions: all([...Array(9).fill(all(Array(21).fill(cmp))), cmp]) });
    expect(shape(two)).toEqual({ ok: true, value: { conditionNodes: 200, editable: true } });
  });

  it("stores 1,000 condition nodes and refuses the 1,001st, a shared node counted per use", () => {
    const shared = all(Array(31).fill(cmp)); // 32 nodes, used 31 times under the root: 992
    const at = rule({ conditions: all([...Array(31).fill(shared), all(Array(6).fill(cmp))]) });
    expect(checkRuleShape(at)).toEqual({
      ok: true,
      value: { conditionNodes: 1_000, editable: false },
    });
    const past = rule({ conditions: all([...Array(31).fill(shared), all(Array(7).fill(cmp))]) });
    expect(checkRuleShape(past)).toEqual({
      ok: false,
      refusal: { reason: "condition_nodes", limit: 1_000, measured: 1_001 },
    });
  });
});
