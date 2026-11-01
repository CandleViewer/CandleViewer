import { beforeEach, describe, expect, it } from "vitest";
import {
  COUNT_LIMIT,
  EMPTY_RECENT,
  RECENT_LIMIT,
  readRecent,
  recordRun,
} from "../../../src/features/command-palette/recent";

// E10-S05 (#5236): recency on the device, per user, ids and counts only.

/** An in-memory `Storage` slice. */
function memory(): Pick<Storage, "getItem" | "setItem"> & { readonly data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (k) => data.get(k) ?? null,
    setItem: (k, v) => void data.set(k, v),
  };
}

describe("E10-S05 recent.ts", () => {
  let store: ReturnType<typeof memory>;
  beforeEach(() => {
    store = memory();
  });

  it("keeps the last five, newest first, with a use count each", () => {
    for (const id of ["a", "b", "c", "a", "d", "e", "f"]) recordRun("u-1", id, store);
    const state = readRecent("u-1", store);
    expect(state.recent).toEqual(["f", "e", "d", "a", "c"]);
    expect(state.recent).toHaveLength(RECENT_LIMIT);
    expect(state.counts).toMatchObject({ a: 2, b: 1, f: 1 });
  });

  it("is per user, under a versioned key, and keeps nothing while no one is signed in", () => {
    recordRun("u-1", "route:R-190", store);
    expect([...store.data.keys()]).toEqual(["cv.palette-recent.v1:u-1"]);
    expect(readRecent("u-2", store)).toEqual(EMPTY_RECENT);
    recordRun(null, "route:R-180", store);
    expect(readRecent(null, store)).toEqual(EMPTY_RECENT);
    expect([...store.data.keys()]).toEqual(["cv.palette-recent.v1:u-1"]);
  });

  it("stores ids and counts only", () => {
    recordRun("u-1", "command:global.cheatsheet", store);
    expect(JSON.parse(store.data.get("cv.palette-recent.v1:u-1") ?? "null")).toEqual({
      recent: ["command:global.cheatsheet"],
      counts: { "command:global.cheatsheet": 1 },
    });
  });

  it("reads a corrupt or foreign record as empty, and drops malformed entries", () => {
    store.data.set("cv.palette-recent.v1:u-1", "{not json");
    expect(readRecent("u-1", store)).toEqual(EMPTY_RECENT);
    store.data.set("cv.palette-recent.v1:u-1", "[1,2]");
    expect(readRecent("u-1", store)).toEqual(EMPTY_RECENT);
    store.data.set(
      "cv.palette-recent.v1:u-1",
      JSON.stringify({ recent: ["a", 3, "a", "b"], counts: { a: 2, b: -1, c: "x", d: 1.5 } }),
    );
    expect(readRecent("u-1", store)).toEqual({ recent: ["a", "b"], counts: { a: 2 } });
  });

  it("bounds the counts it keeps to the most used", () => {
    for (let i = 0; i <= COUNT_LIMIT; i += 1) recordRun("u-1", `id-${String(i)}`, store);
    recordRun("u-1", "id-0", store);
    const { counts } = readRecent("u-1", store);
    expect(Object.keys(counts)).toHaveLength(COUNT_LIMIT);
    expect(counts["id-0"]).toBe(2);
  });

  it("keeps the id just run when the counts are full (a new id is never the one dropped)", () => {
    for (let i = 0; i < COUNT_LIMIT; i += 1) {
      recordRun("u-1", `id-${String(i)}`, store);
      recordRun("u-1", `id-${String(i)}`, store); // every stored id has count 2
    }
    recordRun("u-1", "brand-new", store);
    const { counts } = readRecent("u-1", store);
    expect(Object.keys(counts)).toHaveLength(COUNT_LIMIT);
    expect(counts["brand-new"]).toBe(1);
  });

  it("survives storage that throws: the run is still returned, nothing is read", () => {
    const broken = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("full");
      },
    };
    expect(recordRun("u-1", "a", broken).recent).toEqual(["a"]);
    expect(readRecent("u-1", broken)).toEqual(EMPTY_RECENT);
    expect(readRecent("u-1", null)).toEqual(EMPTY_RECENT);
  });
});
