// E22-S01 (#714) PR-B: the display order over the ring: rows newest first, dividers under a print,
// missed prints under a gap divider, the history tail and its partial-history divider.
import { describe, expect, it } from "vitest";
import { DisplayList, newCursor } from "../../../src/features/tape/model/displayList";
import type { ExtraPrint } from "../../../src/features/tape/model/history";
import { SIDE_BUY, TapeRing } from "../../../src/features/tape/model/ring";

const fill = (ring: TapeRing, n: number): void => {
  for (let k = 0; k < n; k += 1) {
    ring.push({
      id: `t${k}`,
      tsMs: 1_000 + k,
      price: "100.0",
      size: "1",
      side: SIDE_BUY,
      flags: 0,
      clusterSize: 1,
    });
  }
};

const extra = (id: string, tsMs: number): ExtraPrint => ({
  id,
  tsMs,
  price: "100.0",
  size: "1",
  side: SIDE_BUY,
  flags: 0,
  clusterSize: 1,
});

const describeList = (list: DisplayList): string[] => {
  const c = newCursor();
  return Array.from({ length: list.length }, (_, i) => {
    list.at(i, c);
    if (c.kind === "row") return `r${c.seq}@${c.rowIndex}`;
    if (c.kind === "extra") return `x${c.extra?.id}@${c.rowIndex}`;
    return `d:${c.divider?.text}`;
  });
};

describe("tape display list", () => {
  it("lists the ring newest first up to the given top, rows numbered without dividers", () => {
    const ring = new TapeRing(10);
    fill(ring, 4);
    const list = new DisplayList(ring);
    list.build(3);
    expect(describeList(list)).toEqual(["r3@1", "r2@2", "r1@3", "r0@4"]);
    list.build(2); // a frozen top hides the newer prints
    expect(describeList(list)).toEqual(["r2@1", "r1@2", "r0@3"]);
    expect(list.rowCount).toBe(3);
  });

  it("puts a divider under its anchor print and a block under its dividers", () => {
    const ring = new TapeRing(10);
    fill(ring, 5);
    const list = new DisplayList(ring);
    list.addDivider(2, "gap");
    list.setBlock(2, [extra("a", 50), extra("b", 40)]);
    list.build(4);
    expect(describeList(list)).toEqual([
      "r4@1",
      "r3@2",
      "r2@3",
      "d:gap",
      "xa@4",
      "xb@5",
      "r1@6",
      "r0@7",
    ]);
    expect(list.indexOfSeq(1)).toBe(6);
    expect(list.indexOfSeq(9)).toBe(-1);
    expect(list.hasExtraId("b")).toBe(true);
  });

  it("drops an anchor once the ring evicted its print, and hides one above the top", () => {
    const ring = new TapeRing(3);
    fill(ring, 3);
    const list = new DisplayList(ring);
    list.addDivider(0, "old");
    list.addDivider(2, "new");
    list.build(1);
    expect(describeList(list)).toEqual(["r1@1", "r0@2", "d:old"]);
    fill(ring, 1); // evicts seq 0
    list.build(3);
    expect(describeList(list)).toEqual(["r3@1", "r2@2", "d:new", "r1@3"]);
  });

  it("keeps the history tail below the oldest print, then its divider; clearing drops both", () => {
    const ring = new TapeRing(10);
    fill(ring, 2);
    const list = new DisplayList(ring);
    list.appendTail([extra("h1", 10)]);
    list.setTailDivider("none before");
    list.build(1);
    expect(describeList(list)).toEqual(["r1@1", "r0@2", "xh1@3", "d:none before"]);
    expect(list.hasTailDivider).toBe(true);
    const key = list.tailPrints[0]?.key ?? 0;
    expect(list.indexOfKey(key)).toBe(2);
    list.clearTail();
    list.build(1);
    expect(describeList(list)).toEqual(["r1@1", "r0@2"]);
  });

  it("re-reads a divider's changed text after invalidate", () => {
    const ring = new TapeRing(10);
    fill(ring, 2);
    const list = new DisplayList(ring);
    const d = list.addDivider(1, "before");
    list.build(1);
    d.text = "after";
    list.invalidate();
    list.build(1);
    expect(describeList(list)).toContain("d:after");
  });

  it("shows nothing for an empty ring", () => {
    const list = new DisplayList(new TapeRing(4));
    list.build(-1);
    expect(list.length).toBe(0);
    expect(list.indexOfKey(-5)).toBe(-1);
  });
});
