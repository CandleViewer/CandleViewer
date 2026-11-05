// E14-T04 (#359): the drawings adapter and the index changes it brought (kind tier, candidate
// budget), against the ticket's scenarios at index level. Bars are minutes; ticks 0..2 000 on
// 720 px (the hit-pick viewport); bar i opens at i minutes.
import { describe, expect, it } from "vitest";
import { hitViewport } from "../../bench/scenes/hit-pick.js";
import {
  DrawingAdapter,
  ObjectIndex,
  PICK_BUDGET,
  createPickHit,
  type DrawingPickSource,
} from "../../src/hit/index.js";
import { priceToScreen, timeToScreen } from "../../src/viewport/index.js";

const T = (i: number): number => i * 60e6;

function setup() {
  const { viewport } = hitViewport();
  const index = new ObjectIndex(viewport, 0, "main");
  const drawings = new DrawingAdapter(index);
  const hit = createPickHit();
  const ref = createPickHit();
  const add = (
    id: string,
    tool: string,
    anchors: number[],
    more: Partial<DrawingPickSource> = {},
  ) =>
    drawings.upsert({
      id,
      tool,
      anchors: anchors.flatMap((v, i) => (i % 2 === 0 ? [T(v)] : [v])),
      widthPx: 2,
      zIndex: 0,
      locked: false,
      visible: true,
      ...more,
    });
  const at = (i: number, p: number): [number, number] => [
    timeToScreen(viewport, T(i)),
    priceToScreen(viewport, 0, p),
  ];
  /** The grid's answer, equal to the brute-force scan's. */
  const pick = (x: number, y: number, pointer: "mouse" | "touch" = "mouse") => {
    index.pickLinear(x, y, pointer, ref);
    index.pick(x, y, pointer, hit);
    expect(hit).toEqual(ref);
    return hit;
  };
  return { viewport, index, drawings, add, at, pick };
}

describe("Scenario: Topmost object wins deterministically", () => {
  it("z 0, 1 and 2 overlap under the cursor: the z 2 one; at one z the nearer wins", () => {
    const { add, at, pick } = setup();
    add("z0", "rectangle", [9_890, 900, 9_910, 1_100], { zIndex: 0 });
    add("z2", "trendline", [9_890, 1_000, 9_910, 1_000], { zIndex: 2 });
    add("z1", "ellipse", [9_890, 900, 9_910, 1_100], { zIndex: 1 });
    expect(pick(...at(9_900, 1_002)).id).toBe("z2");
    const { add: add2, at: at2, pick: pick2 } = setup();
    add2("far", "horizontal_line", [9_900, 1_010]);
    add2("near", "horizontal_line", [9_900, 1_003]);
    expect(pick2(...at2(9_900, 1_000)).id).toBe("near");
  });

  it("the trading layer wins over any drawing z (D02 §5.1)", () => {
    const { index, add, at, pick } = setup();
    add("d", "trendline", [9_890, 1_000, 9_910, 1_000], { zIndex: 99 });
    index.registerPickable({
      id: "sl",
      kind: "order-line",
      paneId: "main",
      zIndex: 0,
      widthPx: 1,
      geometry: { type: "hline", p: 1_000 },
    });
    expect(pick(...at(9_900, 1_000))).toMatchObject({ id: "sl", kind: "order-line" });
  });

  it("past PICK_BUDGET drawings at the point, the order line still wins (as pickLinear)", () => {
    const { index, add, at } = setup();
    for (let i = 0; i < 2_000; i += 1) add(`z${i}`, "trendline", [9_900, 1_000, 9_900, 1_000]);
    index.registerPickable({
      id: "order",
      kind: "order-line",
      paneId: "main",
      zIndex: 0,
      widthPx: 1,
      geometry: { type: "hline", p: 1_000 },
    });
    const [hit, ref] = [createPickHit(), createPickHit()];
    index.pick(...at(9_900, 1_000), "mouse", hit);
    index.pickLinear(...at(9_900, 1_000), "mouse", ref);
    expect([hit.id, ref.id, index.counters.capped]).toEqual(["order", "order", 1]);
  });
});

describe("tool families", () => {
  it("a handle per anchor wins over its own body; resize knows which anchor", () => {
    const { add, at, pick } = setup();
    add("t", "trendline", [9_880, 800, 9_920, 1_200]);
    expect(pick(...at(9_920, 1_200))).toMatchObject({ id: "t", part: "handle", handle: 1 });
    expect(pick(...at(9_900, 1_000))).toMatchObject({ id: "t", part: "body", handle: -1 });
  });

  it("an extended line picks far past its anchors, inside the plot only", () => {
    const { add, at, pick } = setup();
    add("x", "extended_line", [9_900, 1_000, 9_901, 1_000]);
    expect(pick(...at(9_830, 1_000)).id).toBe("x"); // behind its first anchor
    expect(pick(...at(9_960, 1_000)).id).toBe("x");
    expect(pick(...at(9_900, 1_100)).id).toBeNull();
  });

  it("an ellipse picks inside and near its rim, not near the box corner", () => {
    const { add, at, pick } = setup();
    add("e", "ellipse", [9_880, 800, 9_920, 1_200]);
    expect(pick(...at(9_900, 1_000)).id).toBe("e");
    const [x, y] = at(9_880, 1_200); // the bounding box's corner, off the rim
    expect(pick(x - 40, y - 40).id).toBeNull(); // beyond the corner's target square
  });

  it("an ellipse's box-corner handle is grabbed in its target square, away from the rim", () => {
    const { add, at, pick } = setup();
    add("e", "ellipse", [9_800, 0, 9_990, 2_000]); // a large ellipse: its corners are far off the rim
    const [x, y] = at(9_990, 2_000);
    const hit = pick(x - 3, y + 3);
    expect([hit.id, hit.part, hit.handle]).toEqual(["e", "handle", 1]);
    const [x0, y0] = at(9_800, 0);
    expect(pick(x0 + 5, y0 - 5).handle).toBe(0);
  });

  it("a fib level set picks each level across its span, not between levels", () => {
    const { add, at, pick } = setup();
    add("f", "fib_retracement", [9_880, 0, 9_920, 2_000], { levels: [0, 0.5, 1] });
    expect(pick(...at(9_915, 1_000)).id).toBe("f"); // level 0.5
    expect(pick(...at(9_885, 1_750)).id).toBeNull(); // between 0.5 and 1, off the leg
    const { add: addX, at: atX, pick: pickX } = setup();
    addX("x", "fib_extension", [9_880, 0, 9_890, 400, 9_900, 200], { levels: [1] });
    expect(pickX(...atX(9_895, 600)).id).toBe("x"); // 200 + 400 × 1
  });

  it("a channel picks both edges, the parallel through its third anchor", () => {
    const { add, at, pick } = setup();
    add("c", "parallel_channel", [9_880, 800, 9_920, 800, 9_880, 1_200]);
    expect(pick(...at(9_900, 800)).id).toBe("c");
    expect(pick(...at(9_900, 1_200)).id).toBe("c");
    expect(pick(...at(9_900, 1_000)).id).toBeNull();
    add("two", "parallel_channel", [9_880, 1_500, 9_920, 1_500]); // mid-creation: its first edge
    expect(pick(...at(9_900, 1_500)).id).toBe("two");
  });

  it("a brush is its polyline; an unknown one-anchor tool is a point", () => {
    const { add, at, pick } = setup();
    add("b", "brush", [9_880, 800, 9_890, 1_200, 9_900, 800]);
    expect(pick(...at(9_895, 1_000)).id).toBe("b");
    add("n", "sticker", [9_910, 500]);
    expect(pick(...at(9_910, 500)).id).toBe("n");
    add("proto", "constructor", [9_870, 300]); // a prototype key is just an unknown tool
    expect(pick(...at(9_870, 300)).id).toBe("proto");
    expect(() => add("bad", "trendline", [1])).toThrow(RangeError);
  });
});

describe("Scenario: Hidden objects are not pickable / locked are", () => {
  it("visible=false leaves the index; re-showing registers it again", () => {
    const { drawings, add, at, pick } = setup();
    const rec = add("h", "trendline", [9_890, 1_000, 9_910, 1_000], { visible: false });
    expect(pick(...at(9_900, 1_000)).id).toBeNull();
    drawings.setVisible(rec, true);
    expect(pick(...at(9_900, 1_000)).id).toBe("h");
    drawings.setVisible(rec, false);
    expect(pick(...at(9_900, 1_000)).id).toBeNull();
    expect(drawings.get("h")).toBe(rec);
  });

  it("a locked drawing stays pickable for inspection", () => {
    const { add, at, pick } = setup();
    add("l", "rectangle", [9_890, 900, 9_910, 1_100], { locked: true });
    expect(pick(...at(9_900, 1_000)).id).toBe("l");
  });

  it("replacing a drawing re-buckets it; removing frees its id", () => {
    const { index, drawings, add, at, pick } = setup();
    add("r", "trendline", [9_890, 1_000, 9_910, 1_000]);
    add("r", "trendline", [9_890, 500, 9_910, 500]);
    expect(pick(...at(9_900, 1_000)).id).toBeNull();
    expect(pick(...at(9_900, 500)).id).toBe("r");
    expect(drawings.remove("r")).toBe(true);
    expect(index.size).toBe(0);
    expect(drawings.size).toBe(0);
  });
});

describe("Scenario: Touch tolerance differs from pointer", () => {
  it("13 px off a handle: touch (16) reaches it, mouse (10) does not", () => {
    const { add, at, pick } = setup();
    add("t", "horizontal_line", [9_900, 1_000], { widthPx: 0 });
    const [x, y] = at(9_900, 1_000);
    expect(pick(x, y + 13, "touch")).toMatchObject({ id: "t", part: "handle", handle: 0 });
    expect(pick(x, y + 13, "mouse").id).toBeNull();
  });

  it("a mouse reaches a handle anywhere in its 24 px target square (GK-05), not past it", () => {
    const { index, add, at, pick } = setup();
    add("t", "horizontal_line", [9_900, 1_000], { widthPx: 0 });
    const [x, y] = at(9_900, 1_000);
    expect(pick(x + 11, y + 11.5, "mouse")).toMatchObject({ id: "t", part: "handle", handle: 0 });
    expect(pick(x, y + 12.5, "mouse").id).toBeNull();
    index.handleHalfPx = 20; // ThemeMetrics.handleTargetPx 40
    expect(pick(x, y + 19, "mouse")).toMatchObject({ part: "handle", handle: 0 });
  });
});

describe("Security: picking is bounded work (BQ-04)", () => {
  it("10 000 zero-length segments in one bucket: at most PICK_BUDGET tests, counted capped", () => {
    const { index, at } = setup();
    for (let i = 0; i < 10_000; i += 1) {
      index.registerPickable({
        id: `z${i}`,
        kind: "drawing",
        paneId: "main",
        zIndex: 0,
        widthPx: 1,
        geometry: { type: "segment", t0: T(9_900), p0: 1_000, t1: T(9_900), p1: 1_000 },
      });
    }
    const [hit, again] = [createPickHit(), createPickHit()];
    expect(index.pick(...at(9_900, 1_000), "mouse", hit)).toBe(true);
    expect(index.counters.lastCandidates).toBe(PICK_BUDGET);
    expect(index.counters.capped).toBe(1);
    index.pick(...at(9_900, 1_000), "mouse", again); // a fixed visit order: the same answer
    expect([again.id, index.counters.capped]).toEqual([hit.id, 2]);
    index.pick(...at(9_000, 1_000), "mouse", hit); // elsewhere: uncapped
    expect(index.counters.capped).toBe(2);
  });

  it("the budget counts work: a 1 024-anchor brush costs 1 024, so one fills it", () => {
    const { index, add, at } = setup();
    const zigzag = Array.from({ length: 1_024 }, (_, i) => [9_900 + (i % 2), 1_000]).flat();
    for (let i = 0; i < 10; i += 1) add(`b${i}`, "brush", zigzag);
    index.pick(...at(9_900, 1_000), "mouse", createPickHit());
    expect([index.counters.lastCandidates, index.counters.capped]).toEqual([1, 1]);
  });
});
