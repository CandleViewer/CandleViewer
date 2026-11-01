// The browser `TextPlatform` (E11-S11, BQ-261): a worker-scope (or page) `FontFace` built from the
// app's bytes, OffscreenCanvas `fillText` coverage, IndexedDB and `crypto.subtle`, all reached
// structurally (this file compiles without the DOM lib). Coverage is read from the font's own
// `cmap` (sfnt: TrueType / OpenType, formats 4 and 12), never from what the canvas draws, so a
// system fallback face can never fill the atlas (K01 item 1). No network (C-2.16).
import { ATLAS_DB, ATLAS_STORE } from "../text/atlas-cache.js";
import { fnv64Hex } from "../text/hash.js";
import type { ChartFont, GlyphRaster, KvStore, TextPlatform } from "../text/platform.js";

interface Ctx2D {
  font: string;
  fillStyle: string;
  textBaseline: string;
  measureText(t: string): {
    width: number;
    actualBoundingBoxLeft: number;
    actualBoundingBoxRight: number;
    actualBoundingBoxAscent: number;
    actualBoundingBoxDescent: number;
  };
  clearRect(x: number, y: number, w: number, h: number): void;
  fillText(t: string, x: number, y: number): void;
  getImageData(x: number, y: number, w: number, h: number): { data: Uint8ClampedArray };
}
interface Req<T> {
  result: T;
  onsuccess: (() => void) | null;
  onerror: (() => void) | null;
}
interface IdbStore {
  get(k: string): Req<unknown>;
  put(v: unknown, k: string): Req<unknown>;
  getAllKeys(): Req<unknown[]>;
  delete(k: string): Req<unknown>;
}
interface Idb {
  close(): void;
  onversionchange: (() => void) | null;
  createObjectStore(name: string): unknown;
  transaction(name: string, mode: string): { objectStore(name: string): IdbStore };
}
export interface TextScope {
  FontFace?: new (family: string, src: ArrayBuffer, d: object) => { load(): Promise<unknown> };
  /** The worker's FontFaceSet (`self.fonts`); a page's is `document.fonts`. */
  fonts?: FaceSet;
  document?: { fonts?: FaceSet };
  OffscreenCanvas?: new (w: number, h: number) => { getContext(id: "2d", o: object): unknown };
  indexedDB?: {
    open(name: string, v: number): Req<Idb> & { onupgradeneeded: (() => void) | null };
  };
  crypto?: { subtle?: { digest(alg: string, data: ArrayBuffer): Promise<ArrayBuffer> } };
  isSecureContext?: boolean;
}

/** A FontFaceSet's members used here. */
interface FaceSet {
  add(face: unknown): void;
  delete(face: unknown): unknown;
}

interface Face {
  readonly weight: number;
  readonly alias: string;
  readonly face: unknown;
}

/** The scratch canvas's side: a glyph box larger than this is a raster fault, never clipped. */
export const RASTER_CANVAS_PX = 256;

const done = <T>(r: Req<T>): Promise<T> =>
  new Promise((resolve, reject) => {
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(new Error("indexedDB request failed"));
  });

/** The platform on `scope`, or null where it cannot load a face or draw one off-screen. */
export function createTextPlatform(scope: TextScope): TextPlatform | null {
  const { FontFace, OffscreenCanvas } = scope;
  const set = scope.fonts ?? scope.document?.fonts; // a face not in a set would never be drawn
  if (FontFace === undefined || OffscreenCanvas === undefined || set === undefined) return null;
  const canvas = new OffscreenCanvas(RASTER_CANVAS_PX, RASTER_CANVAS_PX);
  const ctx = canvas.getContext("2d", { willReadFrequently: true }) as Ctx2D;
  const cmaps = new WeakMap<ArrayBuffer, (cp: number) => boolean>();
  let seq = 0;
  return {
    async loadFace(font: ChartFont): Promise<Face> {
      seq += 1;
      const alias = `cv-atlas-${seq}`; // a private family name: no installed font can answer it
      const face = new FontFace(alias, font.bytes, { weight: String(font.weight) });
      await face.load();
      set.add(face);
      return { weight: font.weight, alias, face };
    },
    releaseFace(face: unknown): void {
      set.delete((face as Face).face); // the private alias leaves the page's or worker's set
    },
    rasterize(face: unknown, ch: string, px: number, pad: number): GlyphRaster {
      const f = face as Face;
      ctx.font = `${f.weight} ${px}px "${f.alias}"`; // built, never templated: no replace to miss a `%`
      ctx.textBaseline = "alphabetic";
      const m = ctx.measureText(ch);
      const x0 = Math.floor(-m.actualBoundingBoxLeft);
      const y0 = Math.floor(-m.actualBoundingBoxAscent);
      const iw = Math.max(0, Math.ceil(m.actualBoundingBoxRight) - x0);
      const ih = Math.max(0, Math.ceil(m.actualBoundingBoxDescent) - y0);
      const [w, h] = [iw + 2 * pad, ih + 2 * pad];
      if (w > RASTER_CANVAS_PX || h > RASTER_CANVAS_PX) {
        throw new Error(`glyph box ${w}x${h} exceeds the ${RASTER_CANVAS_PX} px raster canvas`);
      }
      const coverage = new Uint8Array(w * h);
      if (iw > 0 && ih > 0) {
        ctx.clearRect(0, 0, w, h);
        ctx.fillStyle = "#fff";
        ctx.fillText(ch, pad - x0, pad - y0);
        const data = ctx.getImageData(0, 0, w, h).data;
        for (let i = 0; i < w * h; i += 1) coverage[i] = data[i * 4 + 3] as number;
      }
      return { w, h, coverage, advance: m.width, bearingX: x0 - pad, bearingY: y0 - pad };
    },
    cmapHas(font: ChartFont, cp: number): boolean {
      let has = cmaps.get(font.bytes);
      if (has === undefined) cmaps.set(font.bytes, (has = cmapLookup(font.bytes)));
      return has(cp);
    },
    async digest(bytes: ArrayBuffer): Promise<string> {
      const subtle = scope.isSecureContext === false ? undefined : scope.crypto?.subtle;
      const fallback = (): string => `fnv64:${fnv64Hex(new Uint8Array(bytes))}`;
      if (subtle === undefined) return fallback();
      try {
        const d = new Uint8Array(await subtle.digest("SHA-256", bytes));
        return `sha256:${Array.from(d, (b) => b.toString(16).padStart(2, "0")).join("")}`;
      } catch {
        return fallback(); // a scope whose subtle is present but unusable (G-90)
      }
    },
    store: () => openStore(scope),
  };
}

async function openStore(scope: TextScope): Promise<KvStore | null> {
  const factory = scope.indexedDB;
  if (factory === undefined) return null;
  const open = factory.open(ATLAS_DB, 1);
  open.onupgradeneeded = () => void open.result.createObjectStore(ATLAS_STORE);
  const db = await done(open);
  db.onversionchange = () => db.close(); // another context upgrades the database: let it
  const tx = (mode: string): IdbStore => db.transaction(ATLAS_STORE, mode).objectStore(ATLAS_STORE);
  return {
    get: (k) => done(tx("readonly").get(k)),
    put: async (k, v) => void (await done(tx("readwrite").put(v, k))),
    keys: async () => (await done(tx("readonly").getAllKeys())).map(String),
    delete: async (k) => void (await done(tx("readwrite").delete(k))),
    close: () => db.close(),
  };
}

/**
 * Whether an sfnt font's Unicode `cmap` (format 4 or 12) maps `cp`, per lookup: work is bounded
 * by the table, never by the ranges it claims. Anything else (WOFF2 included, which needs
 * Brotli) maps nothing: a coverage failure, never a guess.
 */
export function cmapLookup(bytes: ArrayBuffer): (cp: number) => boolean {
  const v = new DataView(bytes);
  const u16 = (o: number): number => v.getUint16(o);
  const u32 = (o: number): number => v.getUint32(o);
  const tables: number[] = [];
  try {
    const tag = u32(0);
    if (tag !== 0x00010000 && tag !== 0x4f54544f && tag !== 0x74727565) return () => false;
    let cmap = -1;
    for (let i = 0; i < u16(4); i += 1)
      if (u32(12 + i * 16) === 0x636d6170) cmap = u32(20 + i * 16);
    for (let i = 0; cmap >= 0 && i < u16(cmap + 2); i += 1) {
      const rec = cmap + 4 + i * 8;
      const [pid, eid] = [u16(rec), u16(rec + 2)];
      if (pid === 0 || (pid === 3 && (eid === 1 || eid === 10))) tables.push(cmap + u32(rec + 4));
    }
  } catch {
    return () => false; // a truncated directory maps nothing
  }
  return (cp) =>
    tables.some((t) => {
      try {
        return u16(t) === 4 ? format4(v, t, cp) : u16(t) === 12 && format12(v, t, cp);
      } catch {
        return false;
      }
    });
}

function format4(v: DataView, t: number, cp: number): boolean {
  const n = v.getUint16(t + 6) / 2;
  const [ends, starts, deltas, offs] = [t + 14, t + 16 + n * 2, t + 16 + n * 4, t + 16 + n * 6];
  for (let s = 0; s < n; s += 1) {
    const [a, b] = [v.getUint16(starts + s * 2), v.getUint16(ends + s * 2)];
    if (cp < a || cp > b || cp === 0xffff) continue;
    const delta = v.getUint16(deltas + s * 2);
    const ro = v.getUint16(offs + s * 2);
    const g = ro === 0 ? cp : v.getUint16(offs + s * 2 + ro + (cp - a) * 2);
    return g !== 0 && ((g + delta) & 0xffff) !== 0;
  }
  return false;
}

function format12(v: DataView, t: number, cp: number): boolean {
  for (let g = 0; g < v.getUint32(t + 12); g += 1) {
    if (cp >= v.getUint32(t + 16 + g * 12) && cp <= v.getUint32(t + 20 + g * 12)) return true;
  }
  return false;
}
