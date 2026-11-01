// The `drawing-line` instance ring (E14-T03 slices 2-3): line-type records (segment, ray, line,
// hline, vline, polyline) as one instance per drawn segment, plus the outlines of the filled kinds
// (a rect's four edges, a band's two parallel edges; an ellipse's ring is `drawing-fill`'s SDF).
// Chart space throughout, so a pan or zoom rewrites nothing; width is device px (style.width ×
// dpr), rebuilt on a DPR change only. DOM- and GL-free.
import { attributeOffset, PROGRAM } from "../../scene/instance-layout.js";
import type { DrawingRecord } from "./record.js";
import { attributesOf, InstanceRing } from "./ring.js";

export const LINE_ATTRIBUTES = attributesOf(PROGRAM.drawingLine);
export const LINE_STRIDE = LINE_ATTRIBUTES.stride;
const A0 = attributeOffset(PROGRAM.drawingLine, "a_anchor0");
const A1 = attributeOffset(PROGRAM.drawingLine, "a_anchor1");
const STYLE = attributeOffset(PROGRAM.drawingLine, "a_style");
const COLOR = attributeOffset(PROGRAM.drawingLine, "a_color");
const EXTEND = { segment: 0, polyline: 0, ray: 1, line: 2, hline: 2, vline: 2 } as const;
/**
 * The direction the shader takes (style.w): 0 from p0 → p1; 1 horizontal, 2 vertical, given
 * outright for hline and vline (a one-tick p1 − p0 cancels in float32 once |ky| < ~1.5e-5).
 */
const DIRECTION = { segment: 0, polyline: 0, ray: 0, line: 0, hline: 1, vline: 2 } as const;
/** Outline segments of the filled kinds: a rect's four edges, a band's two parallel edges. */
const OUTLINE: Readonly<Record<string, number>> = { rect: 4, band: 2 };

/** Instances a record draws: one per segment of a visible line-type kind or outline, else none. */
export function lineCount(r: DrawingRecord): number {
  const { kind, visible } = r.input;
  if (visible === false) return 0;
  if (Object.hasOwn(OUTLINE, kind)) return OUTLINE[kind] as number;
  if (!Object.hasOwn(EXTEND, kind)) return 0;
  return kind === "polyline" ? r.idx.length - 1 : 1;
}

/**
 * A rect's or band's corner `c` (0 A, 1 B, 2 C, 3 D = B + C − A) in chart space, into `out`:
 * a rect's corners mix its two anchors' index and tick; a band's are p0, p1, p2 and the implied
 * fourth. `drawing-fill` takes the same A, B, C, so outline and fill share every corner.
 */
export function corner(r: DrawingRecord, c: number, out: Float64Array): void {
  const { idx, tick } = r;
  const band = r.input.kind === "band";
  const ia = idx[0] as number;
  const ta = tick[0] as number;
  const ib = idx[1] as number;
  const tb = band ? (tick[1] as number) : ta;
  const ic = band ? (idx[2] as number) : ia;
  const tc = band ? (tick[2] as number) : (tick[1] as number);
  out[0] = c === 0 ? ia : c === 1 ? ib : c === 2 ? ic : ib + ic - ia;
  out[1] = c === 0 ? ta : c === 1 ? tb : c === 2 ? tc : tb + tc - ta;
}

/** Outline edges as corner pairs: a rect A→B→D→C→A, a band A→B and C→D. */
const EDGES = [0, 1, 1, 3, 3, 2, 2, 0];
const BAND_EDGES = [0, 1, 2, 3];
const P = new Float64Array(2);
const Q = new Float64Array(2);

export class LineInstances extends InstanceRing {
  constructor() {
    super(LINE_STRIDE);
  }

  /** Writes every record's instances in draw order; a pan never calls this. */
  encode(order: readonly DrawingRecord[], dpr: number): void {
    let total = 0;
    for (let i = 0; i < order.length; i += 1) total += lineCount(order[i] as DrawingRecord);
    this.begin(total);
    let at = 0;
    for (let i = 0; i < order.length; i += 1) {
      const r = order[i] as DrawingRecord;
      const n = lineCount(r);
      const kind = r.input.kind;
      if (Object.hasOwn(OUTLINE, kind)) {
        const edges = kind === "band" ? BAND_EDGES : EDGES;
        for (let s = 0; s < n; s += 1) {
          corner(r, edges[2 * s] as number, P);
          corner(r, edges[2 * s + 1] as number, Q);
          this.write(
            at++,
            r,
            P[0] as number,
            P[1] as number,
            Q[0] as number,
            Q[1] as number,
            0,
            0,
            dpr,
          );
        }
        continue;
      }
      const k = kind as keyof typeof EXTEND;
      for (let s = 0; s < n; s += 1) {
        // hline / vline: one anchor (p1 = p0), its direction given, extended both ways.
        const b = kind === "polyline" ? s + 1 : kind === "hline" || kind === "vline" ? 0 : 1;
        const ia = r.idx[s] as number;
        const ta = r.tick[s] as number;
        const ib = r.idx[b] as number;
        const tb = r.tick[b] as number;
        this.write(at++, r, ia, ta, ib, tb, EXTEND[k], DIRECTION[k], dpr);
      }
    }
    this.end(at);
  }

  private write(
    i: number,
    r: DrawingRecord,
    ia: number,
    ta: number,
    ib: number,
    tb: number,
    extend: number,
    direction: number,
    dpr: number,
  ): void {
    const o = i * LINE_STRIDE;
    this.open();
    this.anchor(o + A0, ia, ta);
    this.anchor(o + A1, ib, tb);
    const { colour, width, dash } = r.input.style;
    this.f(o + STYLE, width * dpr);
    this.f(o + STYLE + 1, dash);
    this.f(o + STYLE + 2, extend);
    this.f(o + STYLE + 3, direction);
    this.rgba(o + COLOR, colour);
    this.close(i);
  }
}
