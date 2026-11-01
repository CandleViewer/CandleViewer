// The `drawing-fill` instance ring (E14-T03 slice 3): one instance per filled drawing, in chart
// space (corners A, B, C; the shader forms D), so a pan or zoom rewrites nothing and an encode
// uploads only what changed. A rect or band draws only with a fill colour; an ellipse always (its
// ring is this program's, the others' outlines are `drawing-line`'s). DOM- and GL-free.
import { attributeOffset, PROGRAM } from "../../scene/instance-layout.js";
import { corner } from "./lines.js";
import type { DrawingRecord } from "./record.js";
import { attributesOf, InstanceRing } from "./ring.js";

export const FILL_ATTRIBUTES = attributesOf(PROGRAM.drawingFill);
export const FILL_STRIDE = FILL_ATTRIBUTES.stride;
const A = attributeOffset(PROGRAM.drawingFill, "a_cornerA");
const FILL = attributeOffset(PROGRAM.drawingFill, "a_fill");
const STROKE = attributeOffset(PROGRAM.drawingFill, "a_stroke");
const STYLE = attributeOffset(PROGRAM.drawingFill, "a_style");
/** The shader's kind codes. */
export const FILL_KIND = { rect: 0, ellipse: 1, band: 2 } as const;
const C = new Float64Array(2);
/** ±2^29: the shader's int B + C − A then stays inside int32 (|sum| ≤ 3 · 2^29 < 2^31). */
export const FILL_INT_MAX = 2 ** 29;

/** 1 for a visible ellipse, or a visible rect or band with a fill colour; else 0. */
export function fillCount(r: DrawingRecord): number {
  const { kind, visible } = r.input;
  if (visible === false || !Object.hasOwn(FILL_KIND, kind)) return 0;
  return kind === "ellipse" || r.fill >= 0 ? 1 : 0;
}

export class FillInstances extends InstanceRing {
  constructor() {
    super(FILL_STRIDE);
  }

  /** Writes every filled record's instance in draw order; a pan never calls this. */
  encode(order: readonly DrawingRecord[], dpr: number, opacity = 1): void {
    let total = 0;
    for (let i = 0; i < order.length; i += 1) total += fillCount(order[i] as DrawingRecord);
    this.begin(total);
    let at = 0;
    for (let i = 0; i < order.length; i += 1) {
      const r = order[i] as DrawingRecord;
      if (fillCount(r) === 0) continue;
      const o = at * FILL_STRIDE;
      this.open();
      for (let c = 0; c < 3; c += 1) {
        corner(r, c, C);
        this.anchor(o + A + 4 * c, C[0] as number, C[1] as number, FILL_INT_MAX);
      }
      const { width, dash } = r.input.style;
      this.rgba(o + FILL, r.fill < 0 ? 0 : r.fill, opacity); // none: alpha 0 (the ring alone)
      this.rgba(o + STROKE, r.colour, opacity);
      this.f(o + STYLE, FILL_KIND[r.input.kind as keyof typeof FILL_KIND]);
      this.f(o + STYLE + 1, width * dpr);
      this.f(o + STYLE + 2, dash);
      this.f(o + STYLE + 3, 0);
      this.close(at);
      at += 1;
    }
    this.end(at);
  }
}
