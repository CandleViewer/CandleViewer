// The text platform seam (E11-S11, BQ-261): everything the atlas needs from the host, so
// `src/text` stays DOM-free (C-2.16) and runs in node under a procedural stand-in rasteriser.
// The browser implementation is `src/worker/text-platform.ts` (worker FontFace, OffscreenCanvas,
// IndexedDB, crypto.subtle). No font is ever read from the system or downloaded (BQ-259).

/** A font as the app hands it to the engine (`ChartOptions.fonts`, BQ-258). */
export interface ChartFont {
  readonly family: string;
  readonly weight: number;
  readonly bytes: ArrayBuffer;
  readonly version?: string;
}

/** One glyph's coverage box: the ink plus `pad` px each side, and its pen metrics. */
export interface GlyphRaster {
  readonly w: number;
  readonly h: number;
  /** w × h, row-major; ≥ 128 is inside. */
  readonly coverage: Uint8Array;
  readonly advance: number;
  /** The box's top-left from the pen origin on the baseline, px (y down). */
  readonly bearingX: number;
  readonly bearingY: number;
}

/** An async key/value store (IndexedDB's `atlas` store in a browser). */
export interface KvStore {
  get(key: string): Promise<unknown>;
  put(key: string, value: unknown): Promise<void>;
  keys(): Promise<string[]>;
  delete(key: string): Promise<void>;
  /** Releases the connection (idempotent): a left-open IndexedDB handle blocks a version change. */
  close(): void;
}

export interface TextPlatform {
  /** A face built from the bytes alone (never a system or fallback face); rejects on failure. */
  loadFace(font: ChartFont): Promise<unknown>;
  /** Unregisters a face `loadFace` made (the atlas is built, or its runtime is gone). */
  releaseFace(face: unknown): void;
  rasterize(face: unknown, ch: string, px: number, pad: number): GlyphRaster;
  /** Whether the font's `cmap` maps `cp` (coverage is never judged from what a canvas draws). */
  cmapHas(font: ChartFont, cp: number): boolean;
  /** `sha256:<hex>`, or `fnv64:<hex>` outside a secure context (G-90). */
  digest(bytes: ArrayBuffer): Promise<string>;
  /** The cache store, or null where none can be opened (private mode, BQ-273). */
  store(): Promise<KvStore | null>;
}
