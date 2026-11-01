// The Canvas 2D surface the `degraded-2d` backend uses, hand-written (E11-T05, README BQ-84): only
// the members it calls, so src/canvas2d compiles under tsconfig.core.json with no DOM lib, as
// src/gl does with `GL2Like`. A real `CanvasRenderingContext2D` (or its offscreen twin) fits it.
export interface Ctx2DLike {
  fillStyle: unknown;
  strokeStyle: unknown;
  lineWidth: number;
  clearRect(x: number, y: number, w: number, h: number): void;
  fillRect(x: number, y: number, w: number, h: number): void;
  beginPath(): void;
  rect(x: number, y: number, w: number, h: number): void;
  moveTo(x: number, y: number): void;
  lineTo(x: number, y: number): void;
  fill(): void;
  stroke(): void;
  /** Label text in `degraded-2d` (E11-S11 PR B, C-104); a context without them draws no text. */
  font?: string;
  textAlign?: string;
  textBaseline?: string;
  fillText?(text: string, x: number, y: number): void;
  /** The padded store's clip (E11-S10, BQ-149); every real context has them. */
  save?(): void;
  restore?(): void;
  clip?(): void;
}

const METHODS = [
  "clearRect",
  "fillRect",
  "beginPath",
  "rect",
  "moveTo",
  "lineTo",
  "fill",
  "stroke",
];

/** `getContext("2d")`'s answer as a `Ctx2DLike`, or null (no 2D context, or not a 2D one). */
export function asCtx2D(v: unknown): Ctx2DLike | null {
  if (typeof v !== "object" || v === null) return null;
  const o = v as Record<string, unknown>;
  return METHODS.every((m) => typeof o[m] === "function") ? (v as Ctx2DLike) : null;
}
