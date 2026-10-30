// Textures and LUTs (E11-S02, 26 §3.4): RGBA8 2D textures indexed by a batch's `texture` number
// (0: none). `define` is the seam the SDF atlas (E11-S11) and the colour LUTs fill; `patch` is the
// `texSubImage2D` seam E21's heatmap ring streams columns through. Only what PR2 draws needs.
import { GL, type GL2Like } from "./gl-types.js";
import type { GlRegistry, Handle } from "./registry.js";

interface Texture {
  readonly handle: Handle<"texture">;
  readonly bytes: number;
  readonly width: number;
  readonly height: number;
  /** The CPU copy a restore re-uploads (BQ-49); a `patch` owner re-streams on RESTORED. */
  readonly pixels: Uint8Array | null;
}

export class GlTextures {
  bytes = 0;
  private readonly slots: (Texture | undefined)[] = [];

  constructor(
    private readonly gl: GL2Like,
    private readonly registry: GlRegistry,
  ) {}

  /** (Re)defines texture `id` (≥ 1) as width × height RGBA8, from `pixels` or uninitialised. */
  define(id: number, width: number, height: number, pixels: Uint8Array | null): void {
    const old = this.slots[id];
    if (old !== undefined) this.bytes -= old.bytes;
    const handle = old?.handle ?? this.registry.create("texture");
    const t = { handle, bytes: width * height * 4, width, height, pixels };
    this.slots[id] = t;
    this.bytes += t.bytes;
    this.upload(id, t);
  }

  /** After a context restore: every texture again, in id order (LUTs, then the atlas). */
  restore(): void {
    this.slots.forEach((t, id) => {
      if (t !== undefined) this.upload(id, t);
    });
  }

  private upload(id: number, { width, height, pixels }: Texture): void {
    this.bind(id);
    const T = GL.TEXTURE_2D;
    this.gl.texParameteri(T, GL.TEXTURE_MIN_FILTER, GL.LINEAR);
    this.gl.texParameteri(T, GL.TEXTURE_MAG_FILTER, GL.LINEAR);
    this.gl.texImage2D(T, 0, GL.RGBA8, width, height, 0, GL.RGBA, GL.UNSIGNED_BYTE, pixels);
  }

  /** Writes a sub-rectangle of texture `id` (the `texSubImage2D` seam). */
  patch(id: number, x: number, y: number, w: number, h: number, pixels: Uint8Array): void {
    if (this.slots[id] === undefined) return;
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
