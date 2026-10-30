// The WebGL2 backend (E11-S02, 26 §3.4): `GLBackend` behind `RenderBackend`, owning the registry,
// the program cache, buffers, textures and submission. The runtime passes it to the batch builder
// as the `UploadSink` and submits each frame. A program that fails to compile stops GL drawing and
// leaves a `failure` asking for `degraded-2d` (BQ-52); the canvas swap is the host's, in PR3.
import type { RetainedBatch, UploadSink } from "../scene/batch-builder.js";
import { GlBuffers } from "./buffers.js";
import { GL, type GL2Like } from "./gl-types.js";
import {
  ENGINE_SHADER_COMPILE_FAILED,
  INFO_LOG_MAX,
  ProgramCache,
  ProgramCompileError,
} from "./program-cache.js";
import { GlRegistry } from "./registry.js";
import { submitDrawList } from "./submit.js";
import { GlTextures } from "./textures.js";
import { DrawTrace } from "./trace.js";

/** A backend failure the runtime posts as a recoverable `error`, then falls back. */
export interface GlFailure {
  readonly code: typeof ENGINE_SHADER_COMPILE_FAILED;
  readonly message: string;
  readonly recoverable: true;
  readonly fallback: "degraded-2d";
}

/** 26 §3.4's seam: what the runtime needs, so a WebGPU backend can stand in later (BQ-59). */
export interface RenderBackend extends UploadSink {
  /** Draws `list[0, count)` into a `width` × `height` backing store; the failure, else null. */
  submit(list: readonly RetainedBatch[], count: number, w: number, h: number): GlFailure | null;
  readonly trace: DrawTrace;
  readonly failure: GlFailure | null;
  readonly gpuMemoryMbEstimate: number;
  /** Bytes uploaded since the last call. */
  takeUploadedBytes(): number;
}

export class GLBackend implements RenderBackend {
  readonly registry: GlRegistry;
  readonly programs: ProgramCache;
  readonly buffers: GlBuffers;
  readonly textures: GlTextures;
  readonly trace = new DrawTrace();
  failure: GlFailure | null = null;
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

  submit(list: readonly RetainedBatch[], count: number, w: number, h: number): GlFailure | null {
    if (this.failure !== null) return this.failure;
    this.gl.viewport(0, 0, w, h);
    this.gl.clearColor(this.rgb[0] ?? 0, this.rgb[1] ?? 0, this.rgb[2] ?? 0, 1);
    this.gl.clear(GL.COLOR_BUFFER_BIT);
    try {
      submitDrawList(this.gl, list, count, this);
      return null;
    } catch (e) {
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

  /** The clear colour, from the theme's `#rgb` / `#rrggbb` background; anything else is black. */
  setBackground(css: string | undefined): void {
    if (css === this.background) return; // per frame: unchanged, no parse
    this.background = css;
    const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(css ?? "")?.[1] ?? "000";
    const n = Number.parseInt(hex.length === 3 ? hex.replace(/./g, "$&$&") : hex, 16);
    for (let i = 0; i < 3; i += 1) this.rgb[i] = ((n >> (16 - 8 * i)) & 255) / 255;
  }

  /** Deletes every GL object this backend made; losing the context itself is PR3's. */
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
