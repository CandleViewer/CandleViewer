import { describe, expect, it } from "vitest";
import { INITIAL_FLAGS, reduceFlags, type FlagValues } from "../../../src/shell/flags/flags.js";
import type { SystemUpdate } from "../../../src/lib/ws/protocol/frames.js";

// The wire is untrusted: frames are built as unknown and cast, as the engine hands them on.
const frame = (v: unknown): SystemUpdate => v as SystemUpdate;
const push = (flags: unknown): SystemUpdate =>
  frame({ kind: "feature_flags", feature_flags: flags });
const health = (flags: unknown): SystemUpdate =>
  frame({ kind: "health", health: "healthy", feature_flags: flags });

describe("reduceFlags", () => {
  it("starts unread: every name is undefined", () => {
    expect(INITIAL_FLAGS.size).toBe(0);
    expect(INITIAL_FLAGS.get("maintenance.mode")).toBeUndefined();
  });

  it("a health snapshot replaces the whole set", () => {
    const held = reduceFlags(INITIAL_FLAGS, push({ old: true }));
    const next = reduceFlags(held, health({ a: true, b: false }));
    expect([...next]).toEqual([
      ["a", true],
      ["b", false],
    ]);
    expect(next.get("old")).toBeUndefined();
  });

  it("a feature_flags push updates the named flag and keeps the others", () => {
    const held = reduceFlags(INITIAL_FLAGS, health({ a: true, b: false }));
    const next = reduceFlags(held, push({ b: true }));
    expect(next.get("a")).toBe(true);
    expect(next.get("b")).toBe(true);
    expect(held.get("b")).toBe(false); // never mutated in place
  });

  it("ignores non-boolean values and keeps the boolean ones", () => {
    const next = reduceFlags(INITIAL_FLAGS, push({ a: "true", b: 1, c: null, d: {}, e: false }));
    expect([...next]).toEqual([["e", false]]);
  });

  it("keeps the set for a frame whose feature_flags is not an object", () => {
    const held = reduceFlags(INITIAL_FLAGS, push({ a: true }));
    for (const bad of [undefined, null, true, "x", 3, ["a"]]) {
      expect(reduceFlags(held, push(bad))).toBe(held);
      expect(reduceFlags(held, health(bad))).toBe(held);
    }
  });

  it("keeps the held set for a health frame with no feature_flags key (none visible to the role)", () => {
    const held = reduceFlags(INITIAL_FLAGS, health({ a: true }));
    expect(reduceFlags(held, frame({ kind: "health", health: "healthy" }))).toBe(held);
  });

  it("ignores other kinds and non-record frames", () => {
    const held: FlagValues = reduceFlags(INITIAL_FLAGS, push({ a: true }));
    expect(reduceFlags(held, frame({ kind: "notice", feature_flags: { a: false } }))).toBe(held);
    expect(reduceFlags(held, frame(null))).toBe(held);
    expect(reduceFlags(held, frame([]))).toBe(held);
  });

  it("returns the same set for a push that changes nothing", () => {
    const held = reduceFlags(INITIAL_FLAGS, push({ a: true }));
    expect(reduceFlags(held, push({ a: true }))).toBe(held);
  });

  it("keeps a __proto__ key as a plain name", () => {
    const wire: unknown = JSON.parse('{"__proto__": true}');
    const next = reduceFlags(INITIAL_FLAGS, push(wire));
    expect(next.get("__proto__")).toBe(true);
    expect(next.get("constructor")).toBeUndefined();
  });
});
