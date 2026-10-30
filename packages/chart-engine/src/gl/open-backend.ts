// Backend selection (E11-T05, README BQ-85): the one place that turns the probe's report into a
// `RenderBackend`, so the runtime holds only the seam and never names a backend or a profile.
// WebGL2 when the probe allows it and this canvas yields a context; otherwise the Canvas 2D
// backend, with the reason as a code (BQ-89). A forced profile (the host's handoff, BQ-53, or the
// test hook over `init.profile`, BQ-94) goes straight to 2D and is not re-announced.
import { asCtx2D } from "../canvas2d/ctx2d.js";
import { Canvas2DBackend } from "../canvas2d/backend.js";
import type { RenderBackend } from "./backend.js";
import { GLBackend } from "./backend.js";
import {
  type CapabilityReport,
  type DegradeReason,
  degradeReason,
  NO_WEBGL2_REASON,
  type ReducedCapability,
  reducedCapabilities,
} from "./capability.js";
import { acquireContext } from "./context.js";

/** The canvas members selection touches (OffscreenCanvas and HTMLCanvasElement both fit). */
export interface SurfaceLike {
  getContext(id: "2d" | "webgl2", attributes?: object): unknown;
}

export interface OpenedBackend {
  readonly backend: RenderBackend;
  /** Why the chart draws in 2D when it was not forced to: the runtime says so once. */
  readonly degraded: {
    readonly reason: DegradeReason;
    readonly message: string;
    readonly reducedCapabilities: readonly ReducedCapability[];
  } | null;
}

export function openBackend(
  canvas: SurfaceLike,
  report: CapabilityReport,
  forced: boolean,
  now: () => number,
): OpenedBackend {
  const allowed = !forced && report.profile !== "degraded-2d";
  const acquired = allowed ? acquireContext(canvas) : null;
  if (acquired !== null) {
    const backend = new GLBackend(acquired.gl, report.caps?.renderer ?? null, now);
    return { backend, degraded: null };
  }
  const backend = new Canvas2DBackend(asCtx2D(canvas.getContext("2d")));
  if (forced) return { backend, degraded: null };
  // The probe's own words when it said no; a canvas that refused WebGL2 after a good probe is
  // simply "no WebGL2" (BQ-50).
  const message = allowed ? NO_WEBGL2_REASON : report.reasons.join(" ");
  const reason = allowed ? "no-webgl2" : degradeReason(report);
  return {
    backend,
    degraded: { reason, message, reducedCapabilities: reducedCapabilities("degraded-2d") },
  };
}
