import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { RuleGraphError } from "../src/errors.js";
import { sha256Hex } from "../src/sha256.js";

const ASCII = Array.from({ length: 95 }, (_, i) => String.fromCharCode(32 + i));
// 1-, 2-, 3- and 4-byte UTF-8: a, e-acute, the euro sign, U+2028, U+FFFF, an emoji.
const UNICODE = [0x61, 0xe9, 0x20ac, 0x2028, 0xffff, 0x1f600].map((c) => String.fromCodePoint(c));
// The first and last code point of each UTF-8 width, and the two beside the surrogate gap.
const EDGES = [0x7f, 0x80, 0x7ff, 0x800, 0xd7ff, 0xe000, 0xffff, 0x10000, 0x10ffff];

/** `length` characters of `chars`, picked by a seeded multiplicative hash (Knuth's 0x9e3779b1). */
function seeded(length: number, chars: readonly string[], seed: number): string {
  const pick = (i: number) => chars[(Math.imul(seed + i, 0x9e3779b1) >>> 0) % chars.length] ?? "";
  return Array.from({ length }, (_, i) => pick(i)).join("");
}

const nodeSha256 = (text: string): string => createHash("sha256").update(text).digest("hex");

describe("sha256Hex", () => {
  it.each([
    ["the empty string", "", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"],
    ["abc", "abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"],
    [
      "the 448-bit message",
      "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
      "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
    ],
    [
      "the 896-bit message",
      "abcdefghbcdefghicdefghijdefghijkefghijklfghijklmghijklmn" +
        "hijklmnoijklmnopjklmnopqklmnopqrlmnopqrsmnopqrstnopqrstu",
      "cf5b16a778af8380036ce59e7b0492370b249b11e8f07a51afac45037afee9d1",
    ],
  ])("gives the NIST test-vector digest of %s", (_name, text, digest) => {
    expect(sha256Hex(text)).toBe(digest);
  });

  it("agrees with node:crypto at every ASCII length 0..130 and every UTF-8 width", () => {
    for (let length = 0; length <= 130; length++) {
      for (const text of [seeded(length, ASCII, length), seeded(length, UNICODE, 1000 + length)]) {
        expect(sha256Hex(text), JSON.stringify(text)).toBe(nodeSha256(text));
      }
    }
  });

  it.each(EDGES.map((c) => [c.toString(16).toUpperCase().padStart(4, "0"), c] as const))(
    "agrees with node:crypto on U+%s, alone and between ASCII",
    (_hex, code) => {
      for (const text of [String.fromCodePoint(code), `a${String.fromCodePoint(code)}z`]) {
        expect(sha256Hex(text)).toBe(nodeSha256(text));
      }
    },
  );

  it.each([[[0xd800]], [[0xdfff]], [[0x61, 0xdc00]], [[0xd800, 0x61]], [[0xdc00, 0xd800]]])(
    "refuses the lone surrogate in %j as a SCHEMA_VIOLATION (the server cannot encode one either)",
    (codes) => {
      const hash = () => sha256Hex(String.fromCharCode(...codes));
      expect(hash).toThrow(RuleGraphError);
      expect(hash).toThrow(expect.objectContaining({ code: "SCHEMA_VIOLATION" }));
    },
  );
});
