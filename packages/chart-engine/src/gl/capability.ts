// The capability probe and the profile decision (E11-S02, README BQ-50, BQ-57): this module owns
// detection; E11-T05 owns the 2D drawing `degraded-2d` hands over to. `selectProfile` is pure.
import { acquireContext, releaseContext, type CanvasLike } from "./context.js";
import { GL, type GL2Like } from "./gl-types.js";

export type RenderProfile = "full" | "reduced" | "degraded-2d";

/** BQ-50: the `full` floors (key, GL enum, floor, plain name); any one missed is `reduced`. */
export const FULL_LIMITS = [
  ["maxTextureSize", GL.MAX_TEXTURE_SIZE, 4096, "largest texture"],
  ["maxVertexAttribs", GL.MAX_VERTEX_ATTRIBS, 16, "vertex attribute count"],
  ["maxTextureImageUnits", GL.MAX_TEXTURE_IMAGE_UNITS, 8, "texture unit count"],
] as const;
type Limit = (typeof FULL_LIMITS)[number][0];
/** Recorded for diagnostics, not required (BQ-50). */
export const RECORDED_EXTENSIONS: readonly string[] = [
  "EXT_color_buffer_float",
  "OES_texture_float_linear",
];

export interface GlCaps extends Readonly<Record<Limit, number>> {
  /** The recorded extensions present. */
  readonly extensions: readonly string[];
  /** The unmasked GPU string, only via `WEBGL_debug_renderer_info`; for SCR-046 alone. */
  readonly renderer: string | null;
}

/** The `ready` message's capability report: the profile and, in plain words, why. */
export interface CapabilityReport {
  readonly profile: RenderProfile;
  /** One plain-language line per reduced capability; empty for `full`. */
  readonly reasons: readonly string[];
  /** Null when there is no usable WebGL2 context. */
  readonly caps: GlCaps | null;
}

export const NO_WEBGL2_REASON = "WebGL2 is not available, so the chart is drawn in 2D.";
export const FAILED_CONTEXT_REASON = "The graphics context failed, so the chart is drawn in 2D.";

/**
 * What a profile cannot draw (E11-T05, README BQ-89): the five E11-D04 §23 G-3 values, all of them
 * under `degraded-2d` (layers not built yet included), none under `full` or `reduced`.
 */
export const REDUCED_CAPABILITIES = [
  "footprint-text",
  "heatmap",
  "bubbles",
  "profile-shading",
  "gpu-effects",
] as const;
export type ReducedCapability = (typeof REDUCED_CAPABILITIES)[number];

/** Why a chart draws in 2D, as a code the app words (BQ-89): never prose. */
export const DEGRADE_REASONS = [
  "no-webgl2",
  "context-failed",
  "compile-failed",
  "restore-failed",
  "forced",
] as const;
export type DegradeReason = (typeof DEGRADE_REASONS)[number];

const NONE: readonly ReducedCapability[] = [];

/** BQ-89's mapping beside `selectProfile`: the capabilities `profile` reduces. */
export function reducedCapabilities(profile: RenderProfile): readonly ReducedCapability[] {
  return profile === "degraded-2d" ? REDUCED_CAPABILITIES : NONE;
}

/** The probe's reason code for a `degraded-2d` report (the failed-context line, else no WebGL2). */
export function degradeReason(report: CapabilityReport): DegradeReason {
  return report.reasons.includes(FAILED_CONTEXT_REASON) ? "context-failed" : "no-webgl2";
}

/** BQ-50's decision over probed capabilities (null: no WebGL2). */
export function selectProfile(caps: GlCaps | null, why = NO_WEBGL2_REASON): CapabilityReport {
  if (caps === null) return { profile: "degraded-2d", reasons: [why], caps: null };
  const reasons = FULL_LIMITS.filter(([key, , floor]) => !(caps[key] >= floor)).map(
    ([key, , floor, name]) =>
      Number.isFinite(caps[key])
        ? `Reduced detail: the GPU's ${name} is ${caps[key]}, under ${floor}.`
        : `Reduced detail: the GPU did not report its ${name}.`,
  );
  return { profile: reasons.length === 0 ? "full" : "reduced", reasons, caps };
}

/** Reads the limits and extensions off a live context; a throwing or lost one is `degraded-2d`. */
export function probeCapabilities(gl: GL2Like | null): CapabilityReport {
  if (gl === null) return selectProfile(null);
  try {
    if (gl.isContextLost()) return selectProfile(null, FAILED_CONTEXT_REASON);
    const debug = Boolean(gl.getExtension("WEBGL_debug_renderer_info"));
    const renderer = debug ? gl.getParameter(GL.UNMASKED_RENDERER_WEBGL) : null;
    const limits = {} as Record<Limit, number>;
    for (const [key, pname] of FULL_LIMITS) {
      const v = gl.getParameter(pname);
      limits[key] = typeof v === "number" ? v : Number.NaN; // unreported, not "0"
    }
    return selectProfile({
      ...limits,
      extensions: RECORDED_EXTENSIONS.filter((name) => Boolean(gl.getExtension(name))),
      renderer: typeof renderer === "string" ? renderer : null,
    });
  } catch {
    return selectProfile(null, FAILED_CONTEXT_REASON);
  }
}

/** Probes a throwaway canvas and releases its context at once (worker scope or document). */
export function probeCanvas(canvas: CanvasLike): CapabilityReport {
  const acquired = acquireContext(canvas);
  const report = probeCapabilities(acquired?.gl ?? null);
  if (acquired !== null) releaseContext(acquired.gl);
  return report;
}
