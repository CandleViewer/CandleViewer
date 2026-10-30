// A hand-written fake 2D context (E11-T05, the fake-gl precedent, README BQ-63): it logs every
// call, records each painted path's geometry and style, and has a `fillText` so a test can prove
// the 2D path never writes text (S4). No canvas dependency, no DOM.
import type { Ctx2DLike } from "../../src/canvas2d/ctx2d.js";

const finite = (...v: number[]): boolean => v.every(Number.isFinite);

export interface PaintedPath {
  readonly op: "fill" | "stroke";
  readonly style: string;
  readonly lineWidth: number;
  /** `rect x y w h`, `moveTo x y`, `lineTo x y` since the last `beginPath`. */
  readonly parts: string[];
}

export class FakeCtx2D implements Ctx2DLike {
  fillStyle: unknown = "#000000";
  strokeStyle: unknown = "#000000";
  private width = 1;
  readonly log: string[] = [];
  /** Every `fill`, `stroke` and `fillRect`, in order (`fillRect` as a one-rect fill). */
  readonly paths: PaintedPath[] = [];
  private parts: string[] = [];

  /** Like a canvas: a non-finite, zero or negative width is ignored (the last one stays). */
  get lineWidth(): number {
    return this.width;
  }
  set lineWidth(v: number) {
    if (Number.isFinite(v) && v > 0) this.width = v;
  }

  /** The styles of every fill and fillRect, in order. */
  get fills(): string[] {
    return this.paths.filter((p) => p.op === "fill").map((p) => p.style);
  }

  /** Calls by name (`fill`, `beginPath`, …), for op-count gates. */
  count(name: string): number {
    return this.log.filter((c) => c === name).length;
  }

  clearRect(): void {
    this.log.push("clearRect");
  }
  fillRect(x: number, y: number, w: number, h: number): void {
    this.log.push("fillRect");
    if (!finite(x, y, w, h)) return; // a canvas ignores non-finite arguments
    const style = String(this.fillStyle);
    this.paths.push({ op: "fill", style, lineWidth: 0, parts: [`rect ${x} ${y} ${w} ${h}`] });
  }
  beginPath(): void {
    this.log.push("beginPath");
    this.parts = [];
  }
  rect(x: number, y: number, w: number, h: number): void {
    this.log.push("rect");
    if (!finite(x, y, w, h)) return; // a canvas ignores non-finite arguments
    this.parts.push(`rect ${x} ${y} ${w} ${h}`);
  }
  moveTo(x: number, y: number): void {
    this.log.push("moveTo");
    if (!finite(x, y)) return; // a canvas ignores non-finite arguments
    this.parts.push(`moveTo ${x} ${y}`);
  }
  lineTo(x: number, y: number): void {
    this.log.push("lineTo");
    if (!finite(x, y)) return; // a canvas ignores non-finite arguments
    this.parts.push(`lineTo ${x} ${y}`);
  }
  fill(): void {
    this.log.push("fill");
    const style = String(this.fillStyle);
    this.paths.push({ op: "fill", style, lineWidth: 0, parts: this.parts });
  }
  stroke(): void {
    this.log.push("stroke");
    const style = String(this.strokeStyle);
    this.paths.push({ op: "stroke", style, lineWidth: this.lineWidth, parts: this.parts });
  }
  /** Not part of `Ctx2DLike`: present so a call would be caught (S4: no cell text in 2D). */
  fillText(): void {
    this.log.push("fillText");
  }
}
