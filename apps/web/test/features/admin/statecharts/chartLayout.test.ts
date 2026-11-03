/**
 * E42-S08 (#1137) §4.3: the drawing's layout (BQ-6 as ruled: a plain SVG drawing for now). Pure and
 * deterministic, over every committed chart made into its export: every state boxed once inside its
 * parent's group, siblings apart; on the frozen B01 (`frozenCharts.ts`) its two regions side by side
 * and its lifecycle ranked from `draft`, and a child no edge reaches in a last row; edges once per
 * pair, the root's and targetless arms left to the text list; the bounds (40 states, 120 pairs)
 * give `null`, the only `null` the loop over the committed charts accepts; and a model is laid out
 * once, however often it is drawn.
 */
import { readdirSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  createLayoutCache,
  drawnPairs,
  layoutChart,
  layoutOf,
  MAX_DRAWN_PAIRS,
  MAX_DRAWN_STATES,
  type ChartLayout,
  type LaidBox,
} from "../../../../src/features/admin/statecharts/chartLayout";
import { vetStately, type ChartModel } from "../../../../src/features/admin/statecharts/chartModel";
import { exportOf } from "./fixtures";
import { frozenChart, type FrozenChart } from "./frozenCharts";

const MACHINES = resolve(
  import.meta.dirname,
  "../../../../../../services/api/candleviewer/statechart/machines",
);
const HASH = "c".repeat(64);
const FILES = readdirSync(MACHINES)
  .filter((name) => name.endsWith(".machine.json"))
  .sort();

/** A committed chart's model, read from its export as `exportStatechart` serves it. */
function modelOf(file: string): ChartModel {
  const kind = file.split(".")[1] ?? "";
  const raw = exportOf(file, kind, HASH) as { stately: unknown };
  const model = vetStately(raw.stately, kind, HASH);
  if (model === null) throw new Error(`${file}: refused`);
  return model;
}

/** A frozen chart's model (`frozenCharts.ts`): the pins below, which no chart bump moves. */
function frozenModel(name: FrozenChart): ChartModel {
  const model = vetStately(frozenChart(name), name.split(".")[1] ?? "", HASH);
  if (model === null) throw new Error(`${name}: refused`);
  return model;
}

function laid(model: ChartModel): ChartLayout {
  const layout = layoutChart(model);
  if (layout === null) throw new Error(`${model.kind}: not laid out`);
  return layout;
}

/**
 * A committed chart's layout, or `null` where the drawing's bounds refuse it: over 40 states or 120
 * pairs the page shows the text list alone (`machine.too_large`), so a live chart that outgrows
 * them is a design decision, not a red suite. A `null` within the bounds still fails (C-1137-d01).
 */
function laidOrOver(
  model: ChartModel,
  lay: (m: ChartModel) => ChartLayout | null = layoutChart,
): ChartLayout | null {
  const layout = lay(model);
  if (layout === null) {
    const over =
      model.states.length > MAX_DRAWN_STATES || drawnPairs(model).length > MAX_DRAWN_PAIRS;
    expect(over, `${model.kind}: not laid out within the bounds`).toBe(true);
  }
  return layout;
}

const box = (layout: ChartLayout, id: string): LaidBox => {
  const found = layout.boxes.find((b) => b.id === id);
  if (found === undefined) throw new Error(`no box ${id}`);
  return found;
};
const inside = (inner: LaidBox, outer: LaidBox): boolean =>
  inner.x > outer.x &&
  inner.y > outer.y &&
  inner.x + inner.w < outer.x + outer.w &&
  inner.y + inner.h < outer.y + outer.h;
const apart = (a: LaidBox, b: LaidBox): boolean =>
  a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y;

/** A compound chart `id` of `n` leaves `s0`…, each with the transitions `on(i)` lists. */
function synthetic(id: string, n: number, on: (i: number) => readonly number[] = () => []) {
  const states = Object.fromEntries(
    Array.from({ length: n }, (_, i) => [
      `s${i}`,
      { on: Object.fromEntries(on(i).map((j) => [`GO_${j}`, `#${id}.s${j}`])) },
    ]),
  );
  const model = vetStately({ id, initial: "s0", states }, id, HASH);
  if (model === null) throw new Error("synthetic chart refused");
  return model;
}

describe("every committed chart lays out inside its bounds", () => {
  it.each(FILES)("test_layout_%s_boxes_every_state_once_inside_its_group", (file) => {
    const model = modelOf(file);
    const layout = laidOrOver(model);
    if (layout === null) return; // over the bounds: the text list alone
    expect(layout.boxes.map((b) => b.id).sort()).toEqual(model.states.map((s) => s.id).sort());
    for (const b of layout.boxes) {
      expect(b.x, b.id).toBeGreaterThanOrEqual(0);
      expect(b.y, b.id).toBeGreaterThanOrEqual(0);
      expect(b.x + b.w, b.id).toBeLessThanOrEqual(layout.width);
      expect(b.y + b.h, b.id).toBeLessThanOrEqual(layout.height);
    }
    for (const state of model.states) {
      if (state.parent !== model.root) {
        expect(inside(box(layout, state.id), box(layout, state.parent)), state.id).toBe(true);
      }
      const siblings = model.states.filter((s) => s.parent === state.parent && s.id < state.id);
      for (const other of siblings) {
        expect(apart(box(layout, state.id), box(layout, other.id)), `${state.id}/${other.id}`).toBe(
          true,
        );
      }
    }
    // Paint order: every group before every leaf, a parent before its children.
    const firstLeaf = layout.boxes.findIndex((b) => !b.group);
    expect(layout.boxes.slice(firstLeaf).every((b) => !b.group)).toBe(true);
    expect(layout.edges).toHaveLength(drawnPairs(model).length);
  });

  it.each(FILES)("test_layout_%s_is_deterministic", (file) => {
    expect(layoutChart(modelOf(file))).toEqual(layoutChart(modelOf(file)));
  });

  it("test_layout_loop_passes_a_chart_over_the_bounds_as_its_text_list_alone", () => {
    expect(laidOrOver(synthetic("over", MAX_DRAWN_STATES + 1))).toBeNull();
  });

  it("test_layout_loop_fails_a_chart_within_the_bounds_that_is_not_laid_out", () => {
    expect(() => laidOrOver(synthetic("within", 3), () => null)).toThrow(
      /not laid out within the bounds/,
    );
  });
});

describe("the frozen B01 order: a parallel root of two regions (D35)", () => {
  const model = frozenModel("B01.order");
  const layout = laid(model);

  it("test_layout_b01_counts_23_states_and_76_pairs_within_the_bounds", () => {
    expect(model.states).toHaveLength(23);
    expect(drawnPairs(model)).toHaveLength(76);
    expect(model.states.length).toBeLessThanOrEqual(MAX_DRAWN_STATES);
    expect(drawnPairs(model).length).toBeLessThanOrEqual(MAX_DRAWN_PAIRS);
  });

  it("test_layout_b01_lays_its_regions_side_by_side_dashed", () => {
    const lifecycle = box(layout, "order.lifecycle");
    const protection = box(layout, "order.protection");
    expect([lifecycle.group, lifecycle.region, protection.group, protection.region]).toEqual([
      true,
      true,
      true,
      true,
    ]);
    expect(protection.y).toBe(lifecycle.y);
    expect(protection.x).toBeGreaterThanOrEqual(lifecycle.x + lifecycle.w);
    expect(box(layout, "order.lifecycle.draft").region).toBe(false);
  });

  it("test_layout_b01_ranks_the_lifecycle_from_draft_breadth_first", () => {
    const y = (name: string): number => box(layout, `order.lifecycle.${name}`).y;
    expect(y("draft")).toBeLessThan(y("validated"));
    expect(y("validated")).toBeLessThan(y("submitting"));
    // draft is alone in its row: rank 0 is the initial child only.
    const firstRow = model.states.filter(
      (s) => s.parent === "order.lifecycle" && y(s.name) === y("draft"),
    );
    expect(firstRow.map((s) => s.name)).toEqual(["draft"]);
  });

  it("test_layout_b01_marks_each_regions_initial_child_with_a_dot_and_arrow", () => {
    expect(layout.initials.map((mark) => mark.to)).toEqual([
      "order.lifecycle.draft",
      "order.protection.not_required",
    ]);
    for (const mark of layout.initials) {
      const target = box(layout, mark.to);
      expect(mark.cx).toBeLessThan(target.x);
      expect(mark.cy).toBe(target.y + target.h / 2);
      expect(mark.path).toMatch(new RegExp(`L${target.x} `));
    }
  });

  it("test_layout_b01_draws_a_region_to_its_own_child_from_the_regions_header", () => {
    const edge = layout.edges.find(
      (e) => e.from === "order.lifecycle" && e.to === "order.lifecycle.killed",
    );
    const lifecycle = box(layout, "order.lifecycle");
    expect(edge?.path).toMatch(
      new RegExp(`^M${lifecycle.x + lifecycle.w - 12} ${lifecycle.y + 10} L`),
    );
  });

  it("test_layout_b01_draws_self_loops_as_arcs_and_two_way_pairs_apart", () => {
    const loops = layout.edges.filter((e) => e.from === e.to);
    expect(loops.length).toBeGreaterThan(0);
    for (const loop of loops) expect(loop.path).toMatch(/^M[\d. -]+C/);
    const twoWay = layout.edges.find((e) =>
      layout.edges.some((o) => o.from === e.to && o.to === e.from && e.from !== e.to),
    );
    const back = layout.edges.find((o) => o.from === twoWay?.to && o.to === twoWay?.from);
    expect(twoWay).toBeDefined();
    // Two lines, not one line drawn twice: the way back does not start where the way there ends.
    const ends = (path: string | undefined): number[] =>
      (/^M([\d.-]+) ([\d.-]+) L([\d.-]+) ([\d.-]+)$/.exec(path ?? "") ?? []).slice(1).map(Number);
    const [, , thereX, thereY] = ends(twoWay?.path);
    const [backX, backY] = ends(back?.path);
    expect(Math.hypot((backX ?? 0) - (thereX ?? 0), (backY ?? 0) - (thereY ?? 0))).toBeGreaterThan(
      4,
    );
  });
});

describe("what the drawing leaves to the text list", () => {
  it("test_layout_never_draws_the_roots_own_or_a_targetless_arm", () => {
    const model = frozenModel("B18.kill_switch");
    expect(model.edges.some((e) => e.from === model.root)).toBe(true);
    expect(model.edges.some((e) => e.to === null)).toBe(true);
    const layout = laid(model);
    expect(layout.edges.some((e) => e.from === model.root)).toBe(false);
    expect(layout.edges.every((e) => e.to !== "")).toBe(true);
    expect(layout.edges).toHaveLength(
      new Set(
        model.edges
          .filter((e) => e.to !== null && e.from !== model.root)
          .map((e) => `${e.from}|${e.to}`),
      ).size,
    );
  });

  it("test_layout_sizes_a_leaf_by_its_label_between_72_and_220_px", () => {
    const model = vetStately(
      { id: "w", initial: "a", states: { a: {}, partially_filled: {}, ["x".repeat(40)]: {} } },
      "w",
      HASH,
    );
    if (model === null) throw new Error("refused");
    const layout = laid(model);
    expect(box(layout, "w.a").w).toBe(72);
    expect(box(layout, "w.partially_filled").w).toBe(8 + 7 * 16);
    expect(box(layout, `w.${"x".repeat(40)}`).w).toBe(220);
    expect(layout.boxes.every((b) => b.h === 44)).toBe(true);
  });
});

describe("rows: ranked from the initial child, the unreached last", () => {
  it("test_layout_puts_a_child_no_edge_reaches_in_a_last_row", () => {
    // `c` leads back to `a`, but no edge reaches `c`: it sits below every ranked row, never in row 0.
    const model = vetStately(
      {
        id: "isle",
        initial: "a",
        states: { a: { on: { GO: "#isle.b" } }, b: {}, c: { on: { BACK: "#isle.a" } } },
      },
      "isle",
      HASH,
    );
    if (model === null) throw new Error("refused");
    const layout = laid(model);
    const y = (name: string): number => box(layout, `isle.${name}`).y;
    expect(y("a")).toBeLessThan(y("b"));
    expect(y("c")).toBeGreaterThan(y("b"));
  });
});

describe("the drawing's bounds: 40 states and 120 unique pairs", () => {
  it("test_layout_40_states_draw_and_41_give_null", () => {
    expect(layoutChart(synthetic("forty", 40))).not.toBeNull();
    expect(layoutChart(synthetic("fortyone", 41))).toBeNull();
  });

  it("test_layout_120_pairs_draw_and_121_give_null", () => {
    // Eleven states each to every other (110), and self-loops on ten (120) or all eleven (121).
    const all = (loops: number) => (i: number) =>
      Array.from({ length: 11 }, (_, j) => j).filter((j) => j !== i || i < loops);
    const at = synthetic("bound", 11, all(10));
    const over = synthetic("over", 11, all(11));
    expect(drawnPairs(at)).toHaveLength(120);
    expect(drawnPairs(over)).toHaveLength(121);
    expect(layoutChart(at)).not.toBeNull();
    expect(layoutChart(over)).toBeNull();
  });
});

describe("one layout per model: once per kind@hash per visit (§3.3, §10)", () => {
  it("test_layout_cache_lays_out_a_model_once_however_often_drawn", () => {
    let calls = 0;
    const cache = createLayoutCache((model) => {
      calls += 1;
      return layoutChart(model);
    });
    const model = frozenModel("B04.oco");
    const first = cache(model);
    expect(cache(model)).toBe(first);
    expect(cache(model)).toBe(first);
    expect(calls).toBe(1);
    cache(frozenModel("B04.oco")); // another visit's model: laid out again
    expect(calls).toBe(2);
  });

  it("test_layout_cache_keeps_a_null_answer_without_asking_again", () => {
    let calls = 0;
    const cache = createLayoutCache((model) => {
      calls += 1;
      return layoutChart(model);
    });
    const big = synthetic("big", 41);
    expect(cache(big)).toBeNull();
    expect(cache(big)).toBeNull();
    expect(calls).toBe(1);
  });

  it("test_layout_of_is_the_shared_cache", () => {
    const model = frozenModel("B18.kill_switch");
    expect(layoutOf(model)).toBe(layoutOf(model));
  });
});
