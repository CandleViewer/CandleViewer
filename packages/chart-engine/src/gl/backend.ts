// The WebGL2 backend (E11-S02, 26 §3.4): `GLBackend` behind `RenderBackend`, owning the registry,
// the program cache, buffers, textures and submission. The runtime passes it to the batch builder
// as the `UploadSink` and submits each frame. A program that fails to compile stops GL drawing and
// leaves a `failure` asking for `degraded-2d` (BQ-52); the host swaps the canvas (BQ-53). A loss
// drops every GL object and `restore()` rebuilds them from CPU state (BQ-49). E11-T05's
// `Canvas2DBackend` (src/canvas2d) is the seam's second implementation (README BQ-85).
import type { RetainedBatch, UploadSink } from "../scene/batch-builder.js";
import { GlBuffers, type VertexSource } from "./buffers.js";
import { GL, type GL2Like } from "./gl-types.js";
import {
  ContextLostError,
  ENGINE_SHADER_COMPILE_FAILED,
  INFO_LOG_MAX,
  ProgramCache,
  ProgramCompileError,
} from "./program-cache.js";
import { GlRegistry } from "./registry.js";
import { type PaneUniformSource, submitDrawList } from "./submit.js";
import { GlTextures } from "./textures.js";
import { DrawTrace } from "./trace.js";

/** A backend failure the runtime posts as a recoverable `error`, then falls back (BQ-85). */
export interface BackendFailure {
  readonly code: typeof ENGINE_SHADER_COMPILE_FAILED;
  readonly message: string;
  readonly recoverable: true;
  readonly fallback: "degraded-2d";
}

/** A backend whose context can be lost (WebGL2): the runtime's loss wiring needs only this (BQ-85). */
export interface LossCapable {
  /** On `webglcontextlost`: every GPU object is gone; the CPU mirrors stay. */
  invalidate(): void;
  /** On `webglcontextrestored`: rebuild from CPU state; false when the context was lost again. */
  restore(): boolean;
  isContextLost(): boolean;
}

/** 26 §3.4's seam: what the runtime needs, so a WebGPU backend can stand in later (BQ-59). */
export interface RenderBackend extends UploadSink {
  /** Draws `list[0, count)` into a `width` × `height` backing store; the failure, else null. */
  submit(
    list: readonly RetainedBatch[],
    count: number,
    w: number,
    h: number,
  ): BackendFailure | null;
  readonly trace: DrawTrace;
  readonly failure: BackendFailure | null;
  /** True when this backend draws the whole chart in 2D: `degraded-2d` whatever the probe said. */
  readonly drawsIn2d: boolean;
  /** The loss hooks, or null for a backend whose context cannot be lost (Canvas 2D). */
  readonly loss: LossCapable | null;
  readonly gpuMemoryMbEstimate: number;
  /** Bytes uploaded since the last call. */
  takeUploadedBytes(): number;
  /** Where each batch's pane uniform block comes from (E11-S03, closes BQ-59's setters). */
  setPaneUniforms(source: PaneUniformSource | null): void;
  /** Gives a drawing node its instance ring (the store-to-node mapping is the runtime's). */
  attach(nodeId: string, source: VertexSource): void;
  /** The clear colour, from the theme's background token. */
  setBackground(css: string | undefined): void;
  /** Frees what the backend made (chart release). */
  dispose(): void;
}

export class GLBackend implements RenderBackend, LossCapable {
  readonly registry: GlRegistry;
  readonly programs: ProgramCache;
  readonly buffers: GlBuffers;
  readonly textures: GlTextures;
  readonly trace = new DrawTrace();
  failure: BackendFailure | null = null;
  readonly drawsIn2d = false;
  readonly loss: LossCapable = this;
  paneUniforms: PaneUniformSource | null = null;
  private readonly rgb = [0, 0, 0];
  private background: string | undefined = "#000";

  /** `renderer` is the probe's unmasked string, null when `WEBGL_debug_renderer_info` is absent. */
  constructor(
    readonly gl: GL2Like,
    private readonly renderer: string | null,
    now: () => number = () => 0,
  ) {
    this.registry = new GlRegistry(gl);
    this.programs = new ProgramCache(gl, this.registry, now);
    this.buffers = new GlBuffers(gl, this.registry);
    this.textures = new GlTextures(gl, this.registry);
  }

  uploadSubRange(batch: RetainedBatch, from: number, to: number): void {
    if (this.failure === null) this.buffers.uploadSubRange(batch, from, to);
  }

  attach(nodeId: string, source: VertexSource): void {
    this.buffers.attach(nodeId, source);
  }

  submit(
    list: readonly RetainedBatch[],
    count: number,
    w: number,
    h: number,
  ): BackendFailure | null {
    if (this.failure !== null) return this.failure;
    this.gl.viewport(0, 0, w, h);
    this.gl.clearColor(this.rgb[0] ?? 0, this.rgb[1] ?? 0, this.rgb[2] ?? 0, 1);
    this.gl.clear(GL.COLOR_BUFFER_BIT);
    try {
      submitDrawList(this.gl, list, count, this);
      return null;
    } catch (e) {
      if (e instanceof ContextLostError) return null; // `webglcontextlost` follows (BQ-49)
      if (!(e instanceof ProgramCompileError)) throw e;
      this.trace.begin(); // a partial frame is not counted; later frames skip submission
      const on = this.renderer ?? "renderer masked";
      this.failure = {
        code: ENGINE_SHADER_COMPILE_FAILED,
        message: `program "${e.program}" failed to compile on ${on}: ${e.log.slice(0, INFO_LOG_MAX)}`,
        recoverable: true,
        fallback: "degraded-2d",
      };
      return this.failure;
    }
  }

  setPaneUniforms(source: PaneUniformSource | null): void {
    this.paneUniforms = source;
  }

  /** The clear colour, from the theme's `#rgb` / `#rrggbb` background; anything else is black. */
  setBackground(css: string | undefined): void {
    if (css === this.background) return; // per frame: unchanged, no parse
    this.background = css;
    const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(css ?? "")?.[1] ?? "000";
    const n = Number.parseInt(hex.length === 3 ? hex.replace(/./g, "$&$&") : hex, 16);
    for (let i = 0; i < 3; i += 1) this.rgb[i] = ((n >> (16 - 8 * i)) & 255) / 255;
  }

  /** On `webglcontextlost`: every GL object is gone; the CPU mirrors stay. */
  invalidate(): void {
    this.registry.invalidateAll();
    this.buffers.invalidate();
  }

  /**
   * On `webglcontextrestored`: programs, then textures (LUTs, atlas), then every node's buffer,
   * from CPU state. False when the context was lost again. A program that now fails to compile
   * stays unlinked, so the next frame reports it the usual way (BQ-52).
   */
  restore(): boolean {
    const ids = this.programs.forget();
    if (this.registry.recreateAll() > 0) return false;
    for (const id of ids) {
      try {
        this.programs.use(id);
      } catch (e) {
        if (e instanceof ContextLostError) return false;
        if (!(e instanceof ProgramCompileError)) throw e;
      }
    }
    this.textures.restore();
    this.buffers.restore();
    return !this.gl.isContextLost();
  }

  isContextLost(): boolean {
    return this.gl.isContextLost();
  }

  /** Deletes every GL object this backend made (chart release; a lost context deletes none). */
  dispose(): void {
    this.registry.releaseAll();
  }

  get gpuMemoryMbEstimate(): number {
    return (this.buffers.bytes + this.textures.bytes) / 2 ** 20;
  }

  takeUploadedBytes(): number {
    return this.buffers.takeUploaded();
  }
}
