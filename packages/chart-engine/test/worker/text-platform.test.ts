// E11-S11 PR A: the browser TextPlatform over fake globals — the FontFace alias, the coverage
// raster, the sfnt cmap reader, the digest and its FNV-64 fallback (G-90), and the IndexedDB store.
import { describe, expect, it } from "vitest";
import {
  cmapLookup,
  createTextPlatform,
  RASTER_CANVAS_PX,
  type TextScope,
} from "../../src/worker/text-platform.js";

/** An sfnt with one `cmap`: format 4 maps 0–9 and A (not B); format 12 maps U+25B2–U+25BC. */
function sfnt(tag = 0x00010000): ArrayBuffer {
  const buf = new ArrayBuffer(200);
  const v = new DataView(buf);
  v.setUint32(0, tag);
  v.setUint16(4, 1);
  v.setUint32(12, 0x636d6170); // 'cmap' at 28
  v.setUint32(20, 28);
  v.setUint16(30, 2);
  v.setUint16(32, 3);
  v.setUint16(34, 1);
  v.setUint32(36, 20); // format 4 at 48
  v.setUint16(40, 3);
  v.setUint16(42, 10);
  v.setUint32(44, 64); // format 12 at 92
  const t = 48;
  v.setUint16(t, 4);
  v.setUint16(t + 6, 6); // 3 segments
  [0x39, 0x42, 0xffff].forEach((e, i) => v.setUint16(t + 14 + i * 2, e));
  [0x30, 0x41, 0xffff].forEach((s, i) => v.setUint16(t + 22 + i * 2, s));
  [1, 0, 1].forEach((d, i) => v.setUint16(t + 28 + i * 2, d));
  v.setUint16(t + 34 + 2, 4); // segment 1 reads glyphIdArray: [5, 0]
  v.setUint16(t + 40, 5);
  const g = 92;
  v.setUint16(g, 12);
  v.setUint32(g + 12, 1);
  v.setUint32(g + 16, 0x25b2);
  v.setUint32(g + 20, 0x25bc);
  return buf;
}

function fakeScope(over: Partial<TextScope> = {}, box = 6) {
  const added: unknown[] = [];
  const removed: unknown[] = [];
  const drawn: [string, number, number, string][] = [];
  const ctx = {
    font: "",
    fillStyle: "",
    textBaseline: "",
    measureText: (t: string) => ({
      width: 7,
      actualBoundingBoxLeft: 0,
      actualBoundingBoxRight: t === " " ? 0 : box,
      actualBoundingBoxAscent: t === " " ? 0 : 10,
      actualBoundingBoxDescent: t === " " ? 0 : 2,
    }),
    clearRect: () => undefined,
    fillText: (t: string, x: number, y: number) => void drawn.push([t, x, y, ctx.font]),
    getImageData: (_x: number, _y: number, w: number, h: number) => ({
      data: new Uint8ClampedArray(w * h * 4).fill(200),
    }),
  };
  const scope: TextScope = {
    FontFace: class {
      constructor(
        readonly family: string,
        readonly src: ArrayBuffer,
        readonly d: object,
      ) {}
      load = async () => this;
    } as never,
    fonts: { add: (f) => void added.push(f), delete: (f) => removed.push(f) },
    OffscreenCanvas: class {
      getContext = () => ctx;
    } as never,
    ...over,
  };
  return { scope, added, removed, drawn };
}

const font = { family: "JetBrains Mono", weight: 400, bytes: sfnt() };

describe("createTextPlatform (BQ-261)", () => {
  it("is null without FontFace, an OffscreenCanvas or a font set to register into", () => {
    const { scope } = fakeScope();
    const without = (k: keyof TextScope, more: TextScope = {}): TextScope => {
      const s: TextScope = { ...scope, ...more };
      delete s[k];
      return s;
    };
    expect(createTextPlatform(without("FontFace"))).toBeNull();
    expect(createTextPlatform(without("OffscreenCanvas"))).toBeNull();
    expect(createTextPlatform(without("fonts"))).toBeNull();
    expect(createTextPlatform(without("fonts", { document: scope }))).not.toBeNull();
  });

  it("loads a face under a private alias and rasterises the ink box plus the pad", async () => {
    const { scope, added, drawn } = fakeScope();
    const p = createTextPlatform(scope);
    const face = await p?.loadFace(font);
    expect(added).toEqual([
      expect.objectContaining({ family: "cv-atlas-1", d: { weight: "400" } }),
    ]);
    const r = p?.rasterize(face, "8", 12, 2);
    expect(r).toMatchObject({ w: 10, h: 16, advance: 7, bearingX: -2, bearingY: -12 });
    expect(r?.coverage.every((c) => c === 200)).toBe(true);
    expect(drawn).toEqual([["8", 2, 12, '400 12px "cv-atlas-1"']]);
    const space = p?.rasterize(face, " ", 12, 2);
    expect([space?.w, space?.h, space?.coverage.some((c) => c > 0), drawn.length]).toEqual([
      4,
      4,
      false,
      1,
    ]);
  });

  it("builds the font string from weight, alias and size: no `%` survives, whatever the size", async () => {
    const { scope, drawn } = fakeScope();
    const p = createTextPlatform(scope);
    const face = await p?.loadFace({ ...font, weight: 700 });
    for (const px of [9, 12.5, 100]) p?.rasterize(face, "8", px, 1);
    expect(drawn.map((d) => d[3])).toEqual([
      '700 9px "cv-atlas-1"',
      '700 12.5px "cv-atlas-1"',
      '700 100px "cv-atlas-1"',
    ]);
    expect(drawn.some((d) => d[3].includes("%"))).toBe(false);
  });

  it("releaseFace takes the face back out of the font set", async () => {
    const { scope, added, removed } = fakeScope();
    const p = createTextPlatform(scope);
    const face = await p?.loadFace(font);
    p?.releaseFace(face);
    expect(removed).toEqual(added);
  });

  it("a glyph box larger than the raster canvas is a raster fault, never a clipped glyph", async () => {
    const p = createTextPlatform(fakeScope({}, RASTER_CANVAS_PX).scope);
    const face = await p?.loadFace(font);
    expect(() => p?.rasterize(face, "8", 12, 2)).toThrow(/exceeds/);
  });

  it("reads coverage from the cmap (formats 4 and 12), never from the canvas", () => {
    const p = createTextPlatform(fakeScope().scope);
    const has = (cp: number) => p?.cmapHas(font, cp);
    expect([0x30, 0x39, 0x41, 0x25b2, 0x25bc].map(has)).toEqual([true, true, true, true, true]);
    expect([0x2f, 0x42, 0x43, 0x25bd, 0xffff].map(has)).toEqual([
      false,
      false,
      false,
      false,
      false,
    ]);
    expect(cmapLookup(sfnt(0x774f4632))(0x30)).toBe(false); // WOFF2: maps nothing (Brotli)
    expect(cmapLookup(new ArrayBuffer(8))(0x30)).toBe(false); // truncated
  });

  it("digests with SHA-256, or FNV-64 outside a secure context (G-90)", async () => {
    const subtle = { digest: async () => Uint8Array.of(0, 255).buffer };
    const secure = createTextPlatform(fakeScope({ crypto: { subtle } }).scope);
    const insecure = createTextPlatform(
      fakeScope({ crypto: { subtle }, isSecureContext: false }).scope,
    );
    await expect(secure?.digest(Uint8Array.of(0x61).buffer)).resolves.toBe("sha256:00ff");
    await expect(insecure?.digest(Uint8Array.of(0x61).buffer)).resolves.toBe(
      "fnv64:af63dc4c8601ec8c",
    );
    const broken = { digest: () => Promise.reject(new Error("NotSupportedError")) };
    const unusable = createTextPlatform(fakeScope({ crypto: { subtle: broken } }).scope);
    await expect(unusable?.digest(Uint8Array.of(0x61).buffer)).resolves.toBe(
      "fnv64:af63dc4c8601ec8c",
    );
  });

  it("stores records in IndexedDB's atlas store; no IndexedDB is no store", async () => {
    const data = new Map<string, unknown>();
    const stores: string[] = [];
    const req = <T>(fn: () => T) => {
      const r = {
        result: undefined as T,
        onsuccess: null as (() => void) | null,
        onerror: null as (() => void) | null,
      };
      queueMicrotask(() => {
        try {
          r.result = fn();
          r.onsuccess?.();
        } catch {
          r.onerror?.();
        }
      });
      return r;
    };
    const os = {
      get: (k: string) => req(() => data.get(k)),
      put: (v: unknown, k: string) => req(() => data.set(k, v)),
      getAllKeys: () => req(() => [...data.keys()]),
      delete: (k: string) => req(() => data.delete(k)),
    };
    const db = {
      createObjectStore: (n: string) => stores.push(n),
      closed: 0,
      close() {
        this.closed += 1;
      },
      onversionchange: null as (() => void) | null,
      transaction: () => ({ objectStore: () => os }),
    };
    const indexedDB = {
      open: () => {
        const r = Object.assign(
          req(() => db),
          { onupgradeneeded: null as (() => void) | null },
        );
        queueMicrotask(() => r.onupgradeneeded?.());
        return r;
      },
    };
    const kv = await createTextPlatform(
      fakeScope({ indexedDB: indexedDB as never }).scope,
    )?.store();
    await kv?.put("k", 1);
    expect([await kv?.get("k"), await kv?.keys(), stores]).toEqual([1, ["k"], ["atlas"]]);
    await kv?.delete("k");
    expect(await kv?.keys()).toEqual([]);
    os.get = () =>
      req(() => {
        throw new Error("x");
      });
    await expect(kv?.get("k")).rejects.toThrow("indexedDB request failed");
    await expect(createTextPlatform(fakeScope().scope)?.store()).resolves.toBeNull();
    // The connection is released on close() and when another context upgrades the database.
    kv?.close();
    expect(db.closed).toBe(1);
    db.onversionchange?.();
    expect(db.closed).toBe(2);
  });
});
