import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  PointerError,
  cloneJson,
  encodePointer,
  getAt,
  hasAt,
  parsePointer,
  setAt,
} from "../src/pointer.js";

// RFC 6901 §5's example document and its pointer table.
const RFC = {
  foo: ["bar", "baz"],
  "": 0,
  "a/b": 1,
  "c%d": 2,
  "e^f": 3,
  "g|h": 4,
  "i\\j": 5,
  'k"l': 6,
  " ": 7,
  "m~n": 8,
};

const code = (fn: () => unknown): string | null => {
  try {
    fn();
    return null;
  } catch (err) {
    return err instanceof PointerError ? err.code : "other";
  }
};

describe("getAt", () => {
  it.each([
    ["", RFC],
    ["/foo", ["bar", "baz"]],
    ["/foo/0", "bar"],
    ["/", 0],
    ["/a~1b", 1],
    ["/c%d", 2],
    ["/e^f", 3],
    ["/g|h", 4],
    ["/i\\j", 5],
    ['/k"l', 6],
    ["/ ", 7],
    ["/m~0n", 8],
  ])("resolves the RFC 6901 example %j", (pointer, value) => {
    expect(getAt(RFC, pointer)).toEqual(value);
  });

  it.each([
    ["foo", "syntax"],
    ["/m~2n", "syntax"],
    ["/m~", "syntax"],
    ["/missing", "missing"],
    ["/foo/2", "missing"],
    ["/foo/01", "bad_index"],
    ["/foo/-", "bad_index"],
    ["/foo/0/x", "not_a_container"],
    ["/toString", "missing"],
    ["/__proto__", "missing"],
  ])("refuses %j with %s", (pointer, expected) => {
    expect(code(() => getAt(RFC, pointer))).toBe(expected);
  });

  it("names the pointer and the code in its message", () => {
    expect(() => getAt(RFC, "/nope")).toThrow('JSON pointer "/nope": missing');
  });
});

describe("hasAt", () => {
  it("says whether a pointer resolves, and still throws on a malformed one", () => {
    expect(hasAt(RFC, "/foo/1")).toBe(true);
    expect(hasAt(RFC, "/foo/9")).toBe(false);
    expect(hasAt(RFC, "/foo/0/x")).toBe(false);
    expect(() => hasAt(RFC, "foo")).toThrow(PointerError);
  });
});

describe("setAt", () => {
  it("replaces a member or an item where it stands, keeping member order", () => {
    const doc = cloneJson({ a: 1, b: { c: [10, 20] }, d: 4 });
    setAt(doc, "/b/c/1", { const: "1.50" });
    setAt(doc, "/a", 9);
    setAt(doc, "/b/e", true);
    expect(doc).toEqual({ a: 9, b: { c: [10, { const: "1.50" }], e: true }, d: 4 });
    expect(Object.keys(doc)).toEqual(["a", "b", "d"]);
  });

  it("writes a __proto__ member as data, never as the prototype", () => {
    const doc = JSON.parse('{"x":{}}') as { x: object };
    setAt(doc, "/x/__proto__", { polluted: true });
    expect(Object.getPrototypeOf(doc.x)).toBe(Object.prototype);
    expect(Object.hasOwn(doc.x, "__proto__")).toBe(true);
    expect(({} as Record<string, unknown>)["polluted"]).toBeUndefined();
  });

  it.each([
    ["", "syntax"],
    ["/a/b", "not_a_container"],
    ["/l/x", "bad_index"],
    ["/l/1", "missing"],
    ["/l/-", "bad_index"],
    ["/nope/x", "missing"],
    ["/s/x/y", "not_a_container"],
  ])("refuses %j with %s", (pointer, expected) => {
    expect(code(() => setAt({ a: 1, l: [0], s: "t" }, pointer, 0))).toBe(expected);
  });
});

describe("cloneJson", () => {
  it("returns an equal document that shares nothing with the original", () => {
    const doc = JSON.parse('{"a":[{"b":"1.50"}],"__proto__":{"c":1}}') as Record<string, unknown>;
    const copy = cloneJson(doc);
    expect(copy).toEqual(doc);
    expect(copy["a"]).not.toBe(doc["a"]);
    expect(Object.hasOwn(copy, "__proto__")).toBe(true);
    expect(Object.getPrototypeOf(copy)).toBe(Object.prototype);
  });
});

describe("the pointer property", () => {
  const token = fc.oneof(fc.string(), fc.constantFrom("~", "/", "~0", "~1", "~/", "/~", ""));

  it("parses what it encodes, token for token", () => {
    fc.assert(
      fc.property(fc.array(token, { maxLength: 6 }), (tokens) => {
        expect(parsePointer(encodePointer(tokens))).toEqual(tokens);
      }),
    );
  });

  it("reads back what it writes, and leaves every other value of the clone equal", () => {
    fc.assert(
      fc.property(fc.jsonValue({ maxDepth: 4 }), fc.jsonValue({ maxDepth: 2 }), (doc, value) => {
        const pointers: string[] = [];
        const walk = (node: unknown, tokens: (string | number)[]): void => {
          if (tokens.length > 0) pointers.push(encodePointer(tokens));
          if (Array.isArray(node)) node.forEach((v, i) => walk(v, [...tokens, i]));
          else if (typeof node === "object" && node !== null) {
            for (const [k, v] of Object.entries(node)) walk(v, [...tokens, k]);
          }
        };
        walk(doc, []);
        for (const pointer of pointers) {
          const copy = cloneJson(doc);
          setAt(copy, pointer, value);
          expect(getAt(copy, pointer)).toEqual(value);
          setAt(copy, pointer, cloneJson(getAt(doc, pointer)));
          expect(copy).toEqual(doc);
        }
      }),
    );
  });
});
