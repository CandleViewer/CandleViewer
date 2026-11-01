// Textures and LUTs (E11-S02, 26 §3.4): 2D textures indexed by a batch's `texture` number
// (0: none). `define` is the seam the SDF atlas (E11-S11) and the colour LUTs fill; `patch` is the
// `texSubImage2D` seam E21's heatmap ring streams columns through. E11-S11 (BQ-266) adds the R8
// format (1 B/px, `UNPACK_ALIGNMENT` 1) and `patchRows`, whose rows are the CPU copy a restore
// re-uploads; while the context is lost nothing is uploaded, and the restore uploads once.
import { GL, type GL2Like } from "./gl-types.js";
import type { GlRegistry, Handle } from "./registry.js";

export type TextureFormat = "rgba8" | "r8";
/** The SDF atlas's texture number in every chart (one R8 texture, BQ-277). */
export const ATLAS_TEXTURE = 1;
/** The colour LUTs' texture number (E11-T04: one 256 × N RGBA8 texture, a row per ramp). */
export const LUT_TEXTURE = 2;

interface Texture {
  readonly handle: Handle<"texture">;
  readonly bytes: number;
  readonly width: number;
  readonly height: number;
  readonly format: TextureFormat;
  /** Clamp both axes (the atlas and the LUTs): an edge texel never samples the opposite edge. */
  readonly clamp: boolean;
  /** The CPU copy a restore re-uploads (BQ-49); a `patch` owner re-streams on RESTORED. */
  readonly pixels: Uint8Array | null;
  /** Rows written from the top by `patchRows`, re-uploaded after `pixels` on a restore. */
  rows: Uint8Array | null;
}

export class GlTextures {
  bytes = 0;
  private readonly slots: (Texture | undefined)[] = [];

  constructor(
    private readonly gl: GL2Like,
    private readonly registry: GlRegistry,
  ) {}

  /** (Re)defines texture `id` (≥ 1) as width × height, from `pixels` or zeroed. */
  define(
    id: number,
    width: number,
    height: number,
    pixels: Uint8Array | null,
    format: TextureFormat = "rgba8",
    clamp: boolean = format === "r8",
  ): void {
    const old = this.slots[id];
    if (old !== undefined) this.bytes -= old.bytes;
    const handle = old?.handle ?? this.registry.create("texture");
    const bytes = width * height * (format === "r8" ? 1 : 4);
    const t = { handle, bytes, width, height, format, clamp, pixels, rows: null };
    this.slots[id] = t;
    this.bytes += t.bytes;
    if (!this.gl.isContextLost()) this.upload(id, t);
  }

  /** Writes `rows` (whole texture rows from row `y`) and keeps them for a restore. */
  patchRows(id: number, y: number, rows: Uint8Array): void {
    const t = this.slots[id];
    if (t === undefined || t.format !== "r8" || y !== 0) return; // the atlas's packed rows only
    t.rows = rows;
    if (!this.gl.isContextLost()) this.writeRows(id, t);
  }

  /** After a context restore: every texture again, in id order (the atlas, the LUTs, then the rest). */
  restore(): void {
    this.slots.forEach((t, id) => {
      if (t !== undefined) this.upload(id, t);
    });
  }

  private upload(id: number, t: Texture): void {
    const { width, height, pixels, format } = t;
    this.bind(id);
    const T = GL.TEXTURE_2D;
    this.gl.texParameteri(T, GL.TEXTURE_MIN_FILTER, GL.LINEAR);
    this.gl.texParameteri(T, GL.TEXTURE_MAG_FILTER, GL.LINEAR);
    if (t.clamp) {
      // The atlas and the LUTs never wrap: a UV at an edge clamps instead of sampling the
      // opposite edge (t = −1 must not read the +1 end of the delta row).
      this.gl.texParameteri(T, GL.TEXTURE_WRAP_S, GL.CLAMP_TO_EDGE);
      this.gl.texParameteri(T, GL.TEXTURE_WRAP_T, GL.CLAMP_TO_EDGE);
    }
    if (format === "r8") {
      this.gl.pixelStorei(GL.UNPACK_ALIGNMENT, 1); // R8 rows are not 4-byte aligned
      this.gl.texImage2D(T, 0, GL.R8, width, height, 0, GL.RED, GL.UNSIGNED_BYTE, pixels);
      if (t.rows !== null) this.writeRows(id, t);
      return;
    }
    this.gl.texImage2D(T, 0, GL.RGBA8, width, height, 0, GL.RGBA, GL.UNSIGNED_BYTE, pixels);
  }

  private writeRows(id: number, t: Texture): void {
    const rows = t.rows as Uint8Array;
    const h = Math.min(t.height, Math.floor(rows.length / t.width));
    this.bind(id);
    this.gl.pixelStorei(GL.UNPACK_ALIGNMENT, 1);
    this.gl.texSubImage2D(GL.TEXTURE_2D, 0, 0, 0, t.width, h, GL.RED, GL.UNSIGNED_BYTE, rows);
  }

  /** Writes a sub-rectangle of texture `id` (the `texSubImage2D` seam). */
  patch(id: number, x: number, y: number, w: number, h: number, pixels: Uint8Array): void {
    if (this.slots[id] === undefined || this.gl.isContextLost()) return;
    this.bind(id);
    this.gl.texSubImage2D(GL.TEXTURE_2D, 0, x, y, w, h, GL.RGBA, GL.UNSIGNED_BYTE, pixels);
  }

  /** Binds texture `id` on unit 0; 0 or an undefined id binds none. */
  bind(id: number): void {
    const t = this.slots[id];
    this.gl.activeTexture(GL.TEXTURE0);
    this.gl.bindTexture(GL.TEXTURE_2D, t === undefined ? null : this.registry.get(t.handle));
  }
}
