// WebGL2 context acquisition (E11-S02) on a canvas reached structurally: an OffscreenCanvas in the
// worker, the HTMLCanvasElement inline (README BQ-48). No DOM type here (C-2.16).
import type { ContextAttributes, GL2Like } from "./gl-types.js";

/**
 * E10's tuned attributes (ticket Technical notes). `desynchronized` and `powerPreference` are
 * hints a browser may ignore, so the attributes actually granted are recorded (README BQ-62).
 */
export const CONTEXT_ATTRIBUTES: ContextAttributes = {
  alpha: false,
  antialias: false,
  depth: false,
  stencil: false,
  powerPreference: "high-performance",
  preserveDrawingBuffer: false,
  desynchronized: true,
};

/** The canvas member acquisition needs; OffscreenCanvas and HTMLCanvasElement both fit. */
export interface CanvasLike {
  getContext(id: "webgl2", attributes?: ContextAttributes): unknown;
}

export interface AcquiredContext {
  readonly gl: GL2Like;
  /** What `getContextAttributes()` reports, not what was asked for (BQ-62). */
  readonly attributes: ContextAttributes;
}

const isGL2 = (v: unknown): v is GL2Like =>
  typeof v === "object" &&
  v !== null &&
  ["getParameter", "getExtension", "getContextAttributes", "isContextLost"].every(
    (m) => typeof (v as Record<string, unknown>)[m] === "function",
  );

/** A WebGL2 context with the E10 attributes, or null (no WebGL2 or a failed context). */
export function acquireContext(canvas: CanvasLike): AcquiredContext | null {
  try {
    const gl = canvas.getContext("webgl2", CONTEXT_ATTRIBUTES);
    return isGL2(gl) ? { gl, attributes: gl.getContextAttributes() ?? {} } : null;
  } catch {
    return null;
  }
}

/** Frees a probe's context at once, so probes never spend the browser's live-context budget. */
export function releaseContext(gl: GL2Like): void {
  const ext = gl.getExtension("WEBGL_lose_context") as { loseContext?: () => void } | null;
  ext?.loseContext?.();
}
