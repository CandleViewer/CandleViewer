// @vitest-environment node
// E11-S11 PR C: the text host adapter's F-03 verify-before-first-use and its WOFF2 decoder, on the
// vendored JetBrains Mono / Inter files read from disk (no network, C-13.5).
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { decompress } from "brotli/decompress";
import { describe, expect, it, vi } from "vitest";
import { missingGlyphs } from "../../../src/chart/fonts/cmap";
import {
  browserFontHost,
  ChartFontError,
  createChartFontStore,
  DESIGN_FONTS,
  loadDesignFont,
  loadDesignFonts,
  reportChartFontFailure,
  TRADING_GLYPHS,
  type DesignFont,
  type FontHost,
} from "../../../src/chart/fonts/designFonts";
import { decodeWoff2, Woff2Error } from "../../../src/chart/fonts/woff2";

const FONTS = resolve(import.meta.dirname, "../../../../../packages/ui/src/fonts");
const bytesOf = (file: string): ArrayBuffer => {
  const b = readFileSync(resolve(FONTS, file));
  // A Node Buffer's backing store is typed ArrayBufferLike; readFileSync never hands out a
  // SharedArrayBuffer, so the slice is a plain ArrayBuffer.
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer;
};
const sha = (b: ArrayBuffer | Uint8Array): string =>
  createHash("sha256").update(new Uint8Array(b)).digest("hex");
const MONO = DESIGN_FONTS[0] as DesignFont;
const MONO_WOFF2 = bytesOf(MONO.file);

function host(over: Partial<FontHost> = {}): FontHost & { brotli: ReturnType<typeof vi.fn> } {
  return {
    fetchBytes: async (url) => bytesOf(DESIGN_FONTS.find((f) => f.url === url)?.file ?? url),
    sha256: async (b) => sha(b),
    ...over,
    brotli: vi.fn(async () => decompress),
  };
}

const reasonOf = (p: Promise<unknown>): Promise<string> =>
  p.then(
    () => "resolved",
    (e: unknown) => (e instanceof ChartFontError ? e.reason : `untyped ${String(e)}`),
  );

describe("F-03 verify-before-first-use (BQ-265)", () => {
  it("test_loadDesignFonts_goodFiles_handsVerifiedSfntBytesToTheChart", async () => {
    const fonts = await loadDesignFonts(host());
    expect(fonts.map((f) => [f.family, f.weight, f.version])).toEqual([
      ["JetBrains Mono", 400, "v2.304"],
      ["Inter", 600, "v4.1"],
    ]);
    for (const f of fonts) {
      expect(new DataView(f.bytes).getUint32(0)).toBe(0x00010000); // TrueType sfnt, not WOFF2
      expect(f.bytes.byteLength).toBeLessThanOrEqual(8 * 1024 * 1024); // the engine's face bound
    }
  });

  it("test_loadDesignFont_shaMismatch_refusedBeforeDecode", async () => {
    const tampered = MONO_WOFF2.slice(0);
    const view = new Uint8Array(tampered);
    view[view.length - 1] = (view[view.length - 1] ?? 0) ^ 0xff;
    const h = host({ fetchBytes: async () => tampered });
    expect(await reasonOf(loadDesignFont(MONO, h))).toBe("integrity");
    expect(h.brotli).not.toHaveBeenCalled();
  });

  it("test_loadDesignFont_unhashable_refusedBeforeDecode", async () => {
    const h = host({ sha256: () => Promise.reject(new Error("no subtle")) });
    expect(await reasonOf(loadDesignFont(MONO, h))).toBe("integrity");
    expect(h.brotli).not.toHaveBeenCalled();
  });

  it("test_loadDesignFont_unpinnedFile_refused", async () => {
    const h = host();
    expect(await reasonOf(loadDesignFont({ ...MONO, file: "Other.woff2" }, h))).toBe("integrity");
    expect(h.brotli).not.toHaveBeenCalled();
  });

  it("test_loadDesignFont_cmapMissingANeededGlyph_failsClosed", async () => {
    const font = { ...MONO, needs: `${MONO.needs}中` };
    await expect(loadDesignFont(font, host())).rejects.toThrow(/cmap lacks 1 needed glyph/);
  });

  it("test_loadDesignFont_fetchFailure_isTyped", async () => {
    const h = host({ fetchBytes: () => Promise.reject(new TypeError("offline")) });
    expect(await reasonOf(loadDesignFont(MONO, h))).toBe("fetch");
  });

  it("test_loadDesignFont_pinnedButUndecodable_isTyped", async () => {
    const junk = new Uint8Array(64).buffer;
    const h = host({ fetchBytes: async () => junk, sha256: async () => sha(MONO_WOFF2) });
    expect(await reasonOf(loadDesignFont(MONO, h))).toBe("decode");
  });

  it("test_loadDesignFont_decoderChunkFailsToLoad_isAFetchFailure", async () => {
    const h: FontHost = { ...host(), brotli: () => Promise.reject(new Error("chunk 404")) };
    expect(await reasonOf(loadDesignFont(MONO, h))).toBe("fetch");
  });

  it("test_tradingGlyphs_matchTheEngineSource", () => {
    // The engine's set is not a public export: read its source so a change there fails here.
    const config = readFileSync(
      resolve(import.meta.dirname, "../../../../../packages/chart-engine/src/text/config.ts"),
      "utf8",
    );
    expect(/export const TRADING_GLYPHS = "([^"]*)";/.exec(config)?.[1]).toBe(TRADING_GLYPHS);
  });

  it("test_monoNeeds_coverTheEngineTradingGlyphs", () => {
    expect([...TRADING_GLYPHS].filter((ch) => !MONO.needs.includes(ch))).toEqual([]);
  });
});

describe("decodeWoff2", () => {
  const decode = (b: Uint8Array): Uint8Array => decodeWoff2(b, (x, n) => decompress(x, n));

  it("test_decodeWoff2_vendoredMono_isAStableValidSfnt", () => {
    const sfnt = decode(new Uint8Array(MONO_WOFF2));
    const v = new DataView(sfnt.buffer, sfnt.byteOffset, sfnt.byteLength);
    let sum = 0;
    for (let i = 0; i < sfnt.length; i += 4) sum = (sum + v.getUint32(i)) >>> 0;
    expect(sum).toBe(0xb1b0afba); // head.checkSumAdjustment closes the whole-font checksum
    const tags = Array.from({ length: v.getUint16(4) }, (_, i) =>
      String.fromCharCode(...sfnt.subarray(12 + i * 16, 16 + i * 16)),
    );
    expect(tags).toEqual([...tags].sort());
    // Every glyph matched fontTools 4.60.1's decompression (coordinates, flags, components,
    // instructions; the PR's evidence); the digest pins that output against a regression.
    expect(sha(sfnt)).toBe("4201f73228a61f113bee6ad66c1b39f9f205509003dbb4e42cab3d5718024a79");
    expect(missingGlyphs(sfnt, MONO.needs)).toEqual([]);
  });

  it("test_decodeWoff2_notWoff2_throws", () => {
    expect(() => decode(new Uint8Array(64))).toThrow(Woff2Error);
  });

  it("test_decodeWoff2_truncated_throws", () => {
    const b = new Uint8Array(MONO_WOFF2.slice(0, 200));
    new DataView(b.buffer).setUint32(8, 200); // a consistent length field over a cut file
    expect(() => decode(b)).toThrow(Woff2Error);
  });

  it("test_decodeWoff2_collection_throws", () => {
    const b = new Uint8Array(MONO_WOFF2.slice(0));
    new DataView(b.buffer).setUint32(4, 0x74746366);
    expect(() => decode(b)).toThrow(/collections/);
  });

  it("test_decodeWoff2_wrongLengthField_throws", () => {
    const b = new Uint8Array(MONO_WOFF2.slice(0));
    new DataView(b.buffer).setUint32(8, 1);
    expect(() => decode(b)).toThrow(/length field/);
  });

  it.each([1, 2])("test_decodeWoff2_reservedGlyfTransformVersion%i_throws", (version) => {
    const b = new Uint8Array(MONO_WOFF2.slice(0));
    const v = new DataView(b.buffer);
    let p = 48;
    const base128 = (): void => {
      while (((b[p++] ?? 0) & 0x80) !== 0);
    };
    for (let i = 0; i < v.getUint16(12); i += 1) {
      const flags = b[p] ?? 0;
      if ((flags & 63) === 10) b[p] = (version << 6) | 10; // glyf, WOFF2 §4.3 index 10
      p += (flags & 63) === 63 ? 5 : 1;
      base128();
      const [tag, ver] = [flags & 63, flags >> 6];
      if (tag === 10 || tag === 11 ? ver !== 3 : ver !== 0) base128(); // transformLength
    }
    expect(() => decode(b)).toThrow(/reserved glyf transform version/);
  });

  it("test_decodeWoff2_shortBrotliOutput_throws", () => {
    const b = new Uint8Array(MONO_WOFF2);
    expect(() => decodeWoff2(b, () => new Uint8Array(4))).toThrow(/wrong size/);
  });
});

/** A one-table sfnt whose only cmap subtable (3, 10) is format 12 with one group. */
function format12Sfnt(start: number, end: number, glyph: number): Uint8Array {
  const b = new Uint8Array(68);
  const v = new DataView(b.buffer);
  v.setUint16(4, 1); // numTables
  v.setUint32(12, 0x636d6170); // 'cmap'
  v.setUint32(20, 28); // table offset
  v.setUint32(24, 40);
  v.setUint16(30, 1); // cmap: version 0, one encoding record
  v.setUint16(32, 3);
  v.setUint16(34, 10); // Windows, full Unicode
  v.setUint32(36, 12); // subtable offset from the cmap
  v.setUint16(40, 12); // format 12
  v.setUint32(44, 28); // length
  v.setUint32(52, 1); // numGroups
  v.setUint32(56, start);
  v.setUint32(60, end);
  v.setUint32(64, glyph);
  return b;
}

describe("missingGlyphs", () => {
  it("test_missingGlyphs_notAnSfnt_coversNothing", () => {
    expect(missingGlyphs(new Uint8Array(8), "ab")).toEqual(["a", "b"]);
  });

  it("test_missingGlyphs_format12_mapsANonBmpCodePointInItsGroup", () => {
    expect(missingGlyphs(format12Sfnt(0x1f600, 0x1f601, 5), "\u{1F601}a")).toEqual(["a"]);
  });

  it("test_missingGlyphs_format12_groupToGlyphZero_isMissing", () => {
    expect(missingGlyphs(format12Sfnt(0x1f600, 0x1f600, 0), "\u{1F600}")).toEqual(["\u{1F600}"]);
  });

  it("test_missingGlyphs_format12_outsideEveryGroup_isMissing", () => {
    expect(missingGlyphs(format12Sfnt(0x41, 0x42, 7), "ABC")).toEqual(["C"]);
  });
});

describe("createChartFontStore", () => {
  it("test_store_loadsOnceAndSettlesReady", async () => {
    const load = vi.fn(async () => []);
    const store = createChartFontStore(load);
    const seen = vi.fn();
    const off = store.subscribe(seen);
    expect(store.snapshot().status).toBe("loading");
    store.start();
    store.start();
    await vi.waitFor(() => expect(store.snapshot().status).toBe("ready"));
    expect(load).toHaveBeenCalledTimes(1);
    expect(seen).toHaveBeenCalledTimes(1);
    off();
  });

  it("test_store_untypedFailure_settlesATypedError", async () => {
    const store = createChartFontStore(
      () => Promise.reject(new Error("boom")),
      () => undefined,
    );
    store.start();
    await vi.waitFor(() => expect(store.snapshot().status).toBe("failed"));
    const s = store.snapshot();
    expect(s.status === "failed" && s.error).toBeInstanceOf(ChartFontError);
  });

  it("test_store_failure_reportsTheTypedReasonAndFileOnce", async () => {
    const report = vi.fn();
    const error = new ChartFontError("integrity", MONO.file, "SHA-256 does not match the manifest");
    const store = createChartFontStore(() => Promise.reject(error), report);
    store.start();
    await vi.waitFor(() => expect(store.snapshot().status).toBe("failed"));
    expect(report).toHaveBeenCalledTimes(1);
    expect(report).toHaveBeenCalledWith(error);
  });

  it("test_store_success_reportsNothing", async () => {
    const report = vi.fn();
    const store = createChartFontStore(async () => [], report);
    store.start();
    await vi.waitFor(() => expect(store.snapshot().status).toBe("ready"));
    expect(report).not.toHaveBeenCalled();
  });

  it("test_reportChartFontFailure_logsReasonAndFileOnly", () => {
    const log = vi.spyOn(console, "error").mockImplementation(() => undefined);
    try {
      reportChartFontFailure(new ChartFontError("integrity", MONO.file, "SHA-256 mismatch"));
      expect(log).toHaveBeenCalledTimes(1);
      expect(log.mock.calls[0]?.[1]).toEqual({ reason: "integrity", file: MONO.file });
    } finally {
      log.mockRestore();
    }
  });
});

describe("browserFontHost", () => {
  it("test_browserFontHost_fetchesSameOriginBytesAndRefusesAnHttpError", async () => {
    const fetch = vi.fn(async (url: string) =>
      url === "/ok" ? new Response(new Uint8Array([1, 2])) : new Response(null, { status: 404 }),
    );
    vi.stubGlobal("fetch", fetch);
    try {
      expect(new Uint8Array(await browserFontHost.fetchBytes("/ok"))).toEqual(
        new Uint8Array([1, 2]),
      );
      await expect(browserFontHost.fetchBytes("/missing")).rejects.toThrow("HTTP 404");
      expect(fetch).toHaveBeenCalledWith("/ok", { credentials: "same-origin" });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("test_browserFontHost_hashesHexAndLoadsTheDecoderLazily", async () => {
    expect(await browserFontHost.sha256(MONO_WOFF2)).toBe(sha(MONO_WOFF2));
    expect(await browserFontHost.brotli()).toBe(decompress);
  });
});
