/**
 * The chart's drawing as boxes and lines (E42-S08 §4.3; BQ-6 as ruled: a feature-local drawing for
 * now, no dependency and no chart engine, C-2.16). Pure and deterministic: no React, no DOM, the
 * same model always gives the same layout. It lays out the served chart's structure only
 * (`chartModel`); it never evaluates a guard or predicts a state, and what is current is the
 * caller's to mark (C-2.19 to C-2.22). The text list stays the normative equivalent: event names
 * are never drawn, and a chart over the drawing's bounds has no layout.
 *
 * - A leaf is a box `clamp(8 + 7 × label length, 72, 220)` × 44 px: room for its label and, when
 *   current, the word "current" under it.
 * - A compound state is a group around its children, laid out in rows by breadth-first rank from
 *   its `initial` child over the edges between its own children (each edge read at the child that
 *   holds its end); children never reached go in a last row, and a row is in document order.
 * - A parallel state lays its regions side by side (D35).
 * - Groups have 12 px padding and a 20 px header for their label.
 * - Edges are straight lines from border to border, a self-loop a small arc; a pair is drawn once,
 *   and a pair drawn both ways is drawn as two parallel lines. The root's own transitions ("any
 *   state") and arms with no target are the text list's alone.
 * - An initial child has a 6 px dot with an arrow to it.
 */
import type { ChartModel, ChartState, StateKind } from "./chartModel";

/** The most states and unique source → target pairs drawn (B1 has 23 and 76). */
export const MAX_DRAWN_STATES = 40;
export const MAX_DRAWN_PAIRS = 120;

const LEAF_H = 44;
const LEAF_MIN_W = 72;
const LEAF_MAX_W = 220;
const CHAR_W = 7;
const PAD = 12;
const HEADER = 20;
const GAP_X = 32;
const GAP_Y = 32;
/** Room left of a compound's rows for its initial marker. */
const INITIAL_INSET = 20;
/** A group's header reserves room for its label and the word "current" after it. */
const CURRENT_WORD = " current".length;
/** Two lines of a pair drawn both ways sit this far apart. */
const PAIR_OFFSET = 3;

export interface LaidBox {
  readonly id: string;
  readonly label: string;
  readonly kind: StateKind;
  /** A state with children: drawn as a group around them, its label in its header. */
  readonly group: boolean;
  /** A region of a parallel state (all regions are active together): its group is dashed. */
  readonly region: boolean;
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
}

export interface LaidEdge {
  readonly from: string;
  readonly to: string;
  /** An SVG path: a line from border to border, or a self-loop's arc. */
  readonly path: string;
}

export interface LaidInitial {
  /** The initial child the marker points at. */
  readonly to: string;
  /** The dot's centre. */
  readonly cx: number;
  readonly cy: number;
  /** The arrow from the dot to the child's border. */
  readonly path: string;
}

export interface ChartLayout {
  readonly width: number;
  readonly height: number;
  /** Every state once, in paint order: groups first (outer before inner), then leaves. */
  readonly boxes: readonly LaidBox[];
  readonly edges: readonly LaidEdge[];
  readonly initials: readonly LaidInitial[];
}

interface Placed {
  readonly w: number;
  readonly h: number;
  /** Each child's offset in this node, by id. */
  readonly offsets: ReadonlyMap<string, { readonly x: number; readonly y: number }>;
}

/** A size never asked for: every state is measured before it is placed. */
const NOWHERE: Placed = { w: 0, h: 0, offsets: new Map() };

const clamp = (value: number, min: number, max: number): number =>
  Math.min(Math.max(value, min), max);
/** One decimal: deterministic and short path data. */
const r1 = (value: number): number => Math.round(value * 10) / 10;
const leafWidth = (label: string): number =>
  clamp(8 + CHAR_W * label.length, LEAF_MIN_W, LEAF_MAX_W);
const headerWidth = (label: string): number => 2 * PAD + CHAR_W * (label.length + CURRENT_WORD);

/** The pairs a drawing would show: each source → target once, the root's and targetless left out. */
export function drawnPairs(model: ChartModel): readonly (readonly [string, string])[] {
  const seen = new Set<string>();
  const pairs: (readonly [string, string])[] = [];
  for (const edge of model.edges) {
    if (edge.to === null || edge.from === model.root) continue;
    const key = `${edge.from}|${edge.to}`;
    if (seen.has(key)) continue;
    seen.add(key);
    pairs.push([edge.from, edge.to]);
  }
  return pairs;
}

/** A compound's children as rows: ranked breadth first from its initial child, the unreached last. */
function rowsOf(
  kids: readonly ChartState[],
  pairs: readonly (readonly [string, string])[],
): ChartState[][] {
  const holder = (id: string): string | undefined =>
    kids.find((kid) => id === kid.id || id.startsWith(`${kid.id}.`))?.id;
  const next = new Map<string, string[]>(kids.map((kid) => [kid.id, []]));
  for (const [from, to] of pairs) {
    const a = holder(from);
    const b = holder(to);
    if (a === undefined || b === undefined || a === b) continue;
    const list = next.get(a);
    if (list !== undefined && !list.includes(b)) list.push(b);
  }
  const start = kids.find((kid) => kid.initial) ?? kids[0];
  const rank = new Map<string, number>();
  if (start !== undefined) {
    rank.set(start.id, 0);
    const queue = [start.id];
    // The array iterator reads the length on each step, so ids pushed meanwhile are visited too.
    for (const id of queue) {
      const at = rank.get(id) ?? 0;
      for (const to of next.get(id) ?? []) {
        if (rank.has(to)) continue;
        rank.set(to, at + 1);
        queue.push(to);
      }
    }
  }
  const last = Math.max(-1, ...rank.values()) + 1;
  const rows: ChartState[][] = [];
  for (const kid of kids) {
    const at = rank.get(kid.id) ?? last;
    (rows[at] ??= []).push(kid);
  }
  return rows.filter((row) => row.length > 0);
}

/** A point on `box`'s border on the way from its centre towards (`px`, `py`). */
function borderPoint(box: LaidBox, px: number, py: number): readonly [number, number] {
  const cx = box.x + box.w / 2;
  const cy = box.y + box.h / 2;
  const dx = px - cx;
  const dy = py - cy;
  if (dx === 0 && dy === 0) return [cx, cy];
  const t = Math.min(
    dx === 0 ? Infinity : box.w / 2 / Math.abs(dx),
    dy === 0 ? Infinity : box.h / 2 / Math.abs(dy),
  );
  return [cx + dx * t, cy + dy * t];
}

/** A group's anchor for an edge to or from its own descendant: the right end of its header. */
const anchorOf = (box: LaidBox): readonly [number, number] => [
  box.x + box.w - PAD,
  box.y + HEADER / 2,
];

const line = (x1: number, y1: number, x2: number, y2: number): string =>
  `M${r1(x1)} ${r1(y1)} L${r1(x2)} ${r1(y2)}`;

/** A self-loop: from the box's top edge round to its right edge, outside the box. */
function loop(box: LaidBox): string {
  const sx = box.x + box.w - 18;
  const ey = box.y + 18;
  const ex = box.x + box.w;
  return `M${r1(sx)} ${r1(box.y)} C${r1(sx)} ${r1(box.y - 20)} ${r1(ex + 20)} ${r1(ey)} ${r1(ex)} ${r1(ey)}`;
}

function edgePath(from: LaidBox, to: LaidBox, offset: number): string {
  if (from.id === to.id) return loop(from);
  let start: readonly [number, number];
  let end: readonly [number, number];
  if (to.id.startsWith(`${from.id}.`)) {
    start = anchorOf(from);
    end = borderPoint(to, start[0], start[1]);
  } else if (from.id.startsWith(`${to.id}.`)) {
    end = anchorOf(to);
    start = borderPoint(from, end[0], end[1]);
  } else {
    start = borderPoint(from, to.x + to.w / 2, to.y + to.h / 2);
    end = borderPoint(to, from.x + from.w / 2, from.y + from.h / 2);
  }
  if (offset === 0) return line(start[0], start[1], end[0], end[1]);
  // A pair drawn both ways: each line shifts to its own left, so the two never overlap.
  const dx = end[0] - start[0];
  const dy = end[1] - start[1];
  const length = Math.hypot(dx, dy) || 1;
  const nx = (-dy / length) * offset;
  const ny = (dx / length) * offset;
  return line(start[0] + nx, start[1] + ny, end[0] + nx, end[1] + ny);
}

/**
 * The layout of `model`, or `null` when it has more than `MAX_DRAWN_STATES` states or
 * `MAX_DRAWN_PAIRS` unique pairs: the text list alone then shows it.
 */
export function layoutChart(model: ChartModel): ChartLayout | null {
  const pairs = drawnPairs(model);
  if (model.states.length > MAX_DRAWN_STATES || pairs.length > MAX_DRAWN_PAIRS) return null;
  const children = new Map<string, ChartState[]>();
  for (const state of model.states) {
    children.set(state.parent, [...(children.get(state.parent) ?? []), state]);
  }
  const placed = new Map<string, Placed>();

  /** Sizes `id` (its children first) and records where each child sits in it. */
  const measure = (id: string, kind: StateKind, label: string, root: boolean): Placed => {
    const kids = children.get(id) ?? [];
    if (kids.length === 0) {
      const leaf: Placed = { w: leafWidth(label), h: LEAF_H, offsets: new Map() };
      placed.set(id, leaf);
      return leaf;
    }
    const sizes = new Map(kids.map((kid) => [kid.id, measure(kid.id, kid.kind, kid.label, false)]));
    const sizeOf = (kid: ChartState): Placed => sizes.get(kid.id) ?? NOWHERE;
    const top = root ? PAD : HEADER + PAD;
    const minW = root ? 0 : headerWidth(label);
    const offsets = new Map<string, { x: number; y: number }>();
    let w: number;
    let h: number;
    if (kind === "parallel") {
      let x = PAD;
      let tallest = 0;
      for (const kid of kids) {
        const size = sizeOf(kid);
        offsets.set(kid.id, { x, y: top });
        x += size.w + GAP_X;
        tallest = Math.max(tallest, size.h);
      }
      w = Math.max(x - GAP_X + PAD, minW);
      h = top + tallest + PAD;
    } else {
      const rows = rowsOf(kids, pairs);
      const widthOf = (row: readonly ChartState[]): number =>
        row.reduce((sum, kid) => sum + sizeOf(kid).w, 0) + GAP_X * (row.length - 1);
      const inner = Math.max(...rows.map(widthOf));
      w = Math.max(PAD + INITIAL_INSET + inner + PAD, minW);
      let y = top;
      for (const row of rows) {
        let x = PAD + INITIAL_INSET + Math.floor((inner - widthOf(row)) / 2);
        let tallest = 0;
        for (const kid of row) {
          const size = sizeOf(kid);
          offsets.set(kid.id, { x, y });
          x += size.w + GAP_X;
          tallest = Math.max(tallest, size.h);
        }
        y += tallest + GAP_Y;
      }
      h = y - GAP_Y + PAD;
    }
    const node = { w, h, offsets };
    placed.set(id, node);
    return node;
  };
  const whole = measure(model.root, model.rootKind, model.root, true);

  // Absolute boxes, in document order: a parent always comes before its children.
  const kindOf = new Map<string, StateKind>([[model.root, model.rootKind]]);
  const origin = new Map<string, { x: number; y: number }>([[model.root, { x: 0, y: 0 }]]);
  const laid = new Map<string, LaidBox>();
  for (const state of model.states) {
    kindOf.set(state.id, state.kind);
    const parentAt = origin.get(state.parent) ?? { x: 0, y: 0 };
    const offset = placed.get(state.parent)?.offsets.get(state.id) ?? { x: 0, y: 0 };
    const at = { x: parentAt.x + offset.x, y: parentAt.y + offset.y };
    origin.set(state.id, at);
    const size = placed.get(state.id) ?? NOWHERE;
    laid.set(state.id, {
      id: state.id,
      label: state.label,
      kind: state.kind,
      group: (children.get(state.id)?.length ?? 0) > 0,
      region: kindOf.get(state.parent) === "parallel",
      x: at.x,
      y: at.y,
      w: size.w,
      h: size.h,
    });
  }
  const all = [...laid.values()];
  const boxes = [...all.filter((box) => box.group), ...all.filter((box) => !box.group)];

  const drawn = new Set(pairs.map(([from, to]) => `${from}|${to}`));
  const edges: LaidEdge[] = [];
  for (const [from, to] of pairs) {
    const a = laid.get(from);
    const b = laid.get(to);
    if (a === undefined || b === undefined) continue; // every pair's states are the model's
    const both = from !== to && drawn.has(`${to}|${from}`);
    edges.push({ from, to, path: edgePath(a, b, both ? PAIR_OFFSET : 0) });
  }

  const initials: LaidInitial[] = [];
  for (const state of model.states) {
    const box = laid.get(state.id);
    if (!state.initial || box === undefined) continue;
    const cy = box.y + box.h / 2;
    initials.push({
      to: state.id,
      cx: r1(box.x - 14),
      cy: r1(cy),
      path: line(box.x - 11, cy, box.x, cy),
    });
  }
  return { width: whole.w, height: whole.h, boxes, edges, initials };
}

/** A per-model cache: each model is laid out once, however often it is drawn. */
export interface LayoutCache {
  (model: ChartModel): ChartLayout | null;
}

/**
 * A cache over `compute` keyed by the model object. The store keeps one model per `kind@hash` for
 * the visit (§3.3), so a chart is laid out once per `kind@hash` per visit, and a model the store
 * dropped takes its layout with it.
 */
export function createLayoutCache(
  compute: (model: ChartModel) => ChartLayout | null = layoutChart,
): LayoutCache {
  const cache = new WeakMap<ChartModel, ChartLayout | null>();
  return (model) => {
    if (cache.has(model)) return cache.get(model) ?? null;
    const layout = compute(model);
    cache.set(model, layout);
    return layout;
  };
}

/** The inspector's one layout cache. */
export const layoutOf: LayoutCache = createLayoutCache();
