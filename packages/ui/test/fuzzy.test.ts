import { describe, expect, it } from "vitest";
import { fold, fuzzyMatch, fuzzyRank } from "../src/components/internal/fuzzy.js";

const marked = (label: string, query: string): string[] =>
  (fuzzyMatch(label, query)?.ranges ?? []).map(([a, b]) => label.slice(a, b));
const order = (labels: string[], query: string): string[] =>
  fuzzyRank(labels, query, (l) => l).map((r) => r.item);

describe("fuzzyMatch (CMP-059's scorer)", () => {
  it("matches a subsequence and returns null when a character is missing or out of order", () => {
    expect(fuzzyMatch("Flatten all positions", "flp")).not.toBeNull();
    expect(fuzzyMatch("Flatten all positions", "flx")).toBeNull();
    expect(fuzzyMatch("Flatten", "nf")).toBeNull();
    expect(fuzzyMatch("ab", "abc")).toBeNull();
  });

  it("an empty or blank query matches everything with no ranges", () => {
    expect(fuzzyMatch("Anything", "")).toEqual({ score: 0, ranges: [] });
    expect(fuzzyMatch("Anything", "   ")).toEqual({ score: 0, ranges: [] });
  });

  it("is case-insensitive and ignores spaces in the query", () => {
    expect(marked("Open Settings", "OPEN set")).toEqual(["Open", "Set"]);
    expect(fuzzyMatch("open settings", "OS")).not.toBeNull();
  });

  it("prefers word starts and contiguous runs when choosing the alignment", () => {
    // "pos" could match p-o-s scattered in "Flatten all positions"; the contiguous word start wins.
    expect(marked("Flatten all positions", "pos")).toEqual(["pos"]);
    // Word starts ("Go To Chart") beat inner letters for an acronym.
    expect(marked("Go to chart", "gtc")).toEqual(["G", "t", "c"]);
    expect(marked("goToChart", "gtc")).toEqual(["g", "T", "C"]);
  });

  it("folds case and accents per code point, and keeps ranges in UTF-16 offsets", () => {
    expect(fold("É")).toBe("e");
    expect(marked("Réglages", "regl")).toEqual(["Régl"]);
    expect(marked("🚀 Launch", "la")).toEqual(["La"]);
    expect(marked("Ünïcode", "UNI")).toEqual(["Ünï"]);
    expect(fuzzyMatch("日本語メニュー", "メニュ")?.ranges).toEqual([[3, 6]]);
  });
});

describe("fuzzyRank", () => {
  it("ranks a leading run, then word starts, then a run inside a word", () => {
    expect(order(["Reset layout", "Close panel", "Select type", "Settings"], "set")).toEqual([
      "Settings",
      "Select type",
      "Reset layout",
    ]);
  });

  it("keeps the input order between equal scores (stable)", () => {
    expect(order(["Beta tool", "Alpha tool", "Gamma tool"], "tool")).toEqual([
      "Beta tool",
      "Alpha tool",
      "Gamma tool",
    ]);
  });

  it("drops non-matches and returns the input index", () => {
    const ranked = fuzzyRank(["x", "chart", "y"], "ch", (l) => l);
    expect(ranked.map((r) => [r.item, r.index])).toEqual([["chart", 1]]);
    expect(fuzzyRank(["x"], "zz", (l) => l)).toEqual([]);
  });
});
