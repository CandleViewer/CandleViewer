// Scenario 5, the CPU stand-in (E14-T03 PR 2, #358 BQ-1 / BQ-4; the BQ-78 / #395 precedent): until
// E11-T08's SwiftShader runner lands (#391), each primitive × theme × DPR renders through the
// Canvas 2D path on a recording context and the GL instance rings, twice from scratch, and the two
// runs must match exactly (the golden suite's determinism, here at zero tolerance); the colours
// come from the theme's tokens alone (no CSS from a style, SR-E14-04). The pixel goldens (≤ 0.1 %
// diff, both profiles, default-token contrast against both themes) are the `it.todo` rows below,
// listed on #391 at merge.
import { describe, expect, it } from "vitest";
import {
  DRAWING_KINDS,
  type DrawingInput,
  type DrawingKind,
} from "../../../src/layers/drawings/model.js";
import { minuteMap } from "../../interaction/fixtures.js";
import { harness } from "./harness.js";

const T = (i: number): number => minuteMap().indexToTime(i);
/** Stand-in token values per theme (the real ones arrive through `setTheme`, BQ-4). */
const THEMES = {
  dark: { "color.drawing.default": "#5b8def", "color.drawing.fill": "#5b8def33" },
  light: { "color.drawing.default": "#1f4fbf", "color.drawing.fill": "#1f4fbf33" },
} as const;
const DPRS = [1, 2] as const;
const POINTS: Record<DrawingKind, number[]> = {
  segment: [T(10), 1_010, T(30), 1_040],
  ray: [T(10), 1_010, T(30), 1_040],
  line: [T(10), 1_010, T(30), 1_040],
  hline: [T(10), 1_020],
  vline: [T(20), 1_020],
  rect: [T(10), 1_010, T(30), 1_040],
  ellipse: [T(10), 1_010, T(30), 1_040],
  band: [T(10), 1_010, T(30), 1_020, T(10), 1_030],
  polyline: [T(10), 1_010, T(20), 1_040, T(30), 1_015, T(40), 1_035],
  text: [T(20), 1_025],
};
const drawing = (kind: DrawingKind): DrawingInput => ({
  id: kind,
  kind,
  points: POINTS[kind],
  style: { colour: "color.drawing.default", fill: "color.drawing.fill", width: 2, dash: 1 },
  label: `${kind} 1.25`,
});

/** One render from scratch: the 2D calls and the three GL rings' words. */
function render(kind: DrawingKind, theme: keyof typeof THEMES, dpr: number): string {
  const h = harness(dpr, false, [drawing(kind)]);
  h.node.theme = THEMES[theme];
  h.graph.markTheme();
  h.frame();
  const { node, ctx2d } = h;
  const rings = [node.lines, node.fills, node.labels].map((r) => [
    ...r.data.slice(0, r.count * r.stride),
  ]);
  return JSON.stringify([ctx2d.paths, ctx2d.dashes, ctx2d.ellipses, ctx2d.texts, rings]);
}

describe("Scenario: Golden images are deterministic (CPU stand-in until #391)", () => {
  for (const kind of DRAWING_KINDS) {
    for (const theme of ["light", "dark"] as const) {
      it.each(DPRS)(`${kind} × ${theme} × dpr %s: two runs match; colours are the tokens'`, (d) => {
        const first = render(kind, theme, d);
        expect(render(kind, theme, d)).toBe(first);
        const hex = THEMES[theme]["color.drawing.default"].slice(1);
        const rgb = [0, 2, 4].map((i) => Number.parseInt(hex.slice(i, i + 2), 16)).join(", ");
        expect(first).toContain(`rgba(${rgb}, 1)`); // the stroke, or the label's fill
      });
    }
  }
});

describe("drawings goldens on SwiftShader (E11-T08, #391)", () => {
  for (const kind of DRAWING_KINDS) {
    for (const theme of ["light", "dark"] as const) {
      for (const dpr of DPRS) {
        it.todo(
          `${kind} × ${theme} × dpr ${dpr}: WebGL2 and degraded-2d each within 0.1 % of the committed golden, twice`,
        );
      }
    }
  }
  it.todo("default stroke / fill / label tokens reach the contrast floor against both themes");
});
