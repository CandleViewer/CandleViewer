// The chart's text host adapter (E11-S11 PR C, G-87): the app, never the engine (C-2.16), fetches
// the vendored WOFF2 design fonts, verifies them before first use and hands sfnt bytes to the engine
// through `ChartOptions.fonts`. F-03 (BQ-265): the WOFF2's SHA-256 must equal the manifest's pin
// before a byte is decoded, and the decoded `cmap` must map every glyph the engine draws. Any miss
// fails closed with a typed `ChartFontError`: the chart is created with no fonts, so the engine
// emits ENGINE_ATLAS_GENERATION_FAILED once and discloses the skipped text; no fallback face is ever
// used (BQ-259).
import { createContext } from "react";
import type { ChartOptions } from "@candleviewer/chart-engine";
import manifest from "@candleviewer/ui/fonts/manifest.json";
import uiUrl from "@candleviewer/ui/fonts/InterVariable.woff2?url";
import monoUrl from "@candleviewer/ui/fonts/JetBrainsMono[wght].woff2?url";
import { missingGlyphs } from "./cmap";
import { decodeWoff2, type BrotliDecode } from "./woff2";

export type ChartFont = NonNullable<ChartOptions["fonts"]>[number];

export type ChartFontFailure = "fetch" | "integrity" | "decode" | "coverage";

export class ChartFontError extends Error {
  override readonly name = "ChartFontError";
  constructor(
    readonly reason: ChartFontFailure,
    readonly file: string,
    message: string,
  ) {
    super(`${file}: ${message}`);
  }
}

/** What the adapter reaches outside itself; tests inject all three (no network, C-13.5). */
export interface FontHost {
  fetchBytes(url: string): Promise<ArrayBuffer>;
  /** Lower-case hex SHA-256. */
  sha256(bytes: ArrayBuffer): Promise<string>;
  /** The Brotli decoder, loaded on first use (its own chunk, C-14.3). */
  brotli(): Promise<BrotliDecode>;
}

const ASCII = Array.from({ length: 0x7f - 0x20 }, (_, i) => String.fromCharCode(0x20 + i)).join("");

/**
 * The engine's F-03 trading glyphs (`packages/chart-engine/src/text/config.ts` TRADING_GLYPHS, not
 * a public export): the mono face's `needs` must cover them (test/chart/fonts).
 */
export const TRADING_GLYPHS = "0123456789.,-+%×KMB▲▼() ?:/ADFJNOSabceglnoprtuvy";

export interface DesignFont {
  readonly file: string;
  readonly url: string;
  /** Matched by the engine's ATLAS_CONFIG families (BQ-258). */
  readonly family: string;
  readonly weight: number;
  /** E11-K01's glyph set for the family: printable ASCII plus its symbols. */
  readonly needs: string;
}

/** The two faces the atlas draws: JetBrains Mono 400 (cells, axes) and Inter 600 (watermark). */
export const DESIGN_FONTS: readonly DesignFont[] = [
  {
    file: "JetBrainsMono[wght].woff2",
    url: monoUrl,
    family: "JetBrains Mono",
    weight: 400,
    needs: `${ASCII}×▲▼`,
  },
  { file: "InterVariable.woff2", url: uiUrl, family: "Inter", weight: 600, needs: `${ASCII}·` },
];

const hex = (b: ArrayBuffer): string =>
  Array.from(new Uint8Array(b), (x) => x.toString(16).padStart(2, "0")).join("");

export const browserFontHost: FontHost = {
  async fetchBytes(url) {
    const res = await fetch(url, { credentials: "same-origin" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.arrayBuffer();
  },
  sha256: async (bytes) => hex(await crypto.subtle.digest("SHA-256", bytes)),
  brotli: async () => (await import("brotli/decompress")).decompress,
};

/** Fetches, verifies and decodes one face; every failure is a `ChartFontError`. */
export async function loadDesignFont(font: DesignFont, host: FontHost): Promise<ChartFont> {
  const pin = manifest.files.find((f) => f.file === font.file);
  const fail = (reason: ChartFontFailure, message: string): ChartFontError =>
    new ChartFontError(reason, font.file, message);
  if (pin === undefined) throw fail("integrity", "has no manifest pin");
  const raw = await host.fetchBytes(font.url).catch(() => {
    throw fail("fetch", "could not be fetched");
  });
  const digest = await host.sha256(raw).catch(() => {
    throw fail("integrity", "could not be hashed");
  });
  if (digest !== pin.sha256) throw fail("integrity", "SHA-256 does not match the manifest");
  // The decoder is its own lazy chunk: failing to load it is a fetch failure, not a bad font.
  const brotli = await host.brotli().catch(() => {
    throw fail("fetch", "could not load the WOFF2 decoder");
  });
  let sfnt: Uint8Array<ArrayBuffer>;
  try {
    sfnt = decodeWoff2(new Uint8Array(raw), brotli);
  } catch {
    throw fail("decode", "is not a decodable WOFF2 font");
  }
  const missing = missingGlyphs(sfnt, font.needs);
  if (missing.length > 0) throw fail("coverage", `cmap lacks ${missing.length} needed glyph(s)`);
  return { family: font.family, weight: font.weight, bytes: sfnt.buffer, version: pin.release };
}

/**
 * All design faces, or the first face's typed failure. All or nothing, by choice: one verified set
 * or none, so a failed Inter (the watermark face) also drops JetBrains Mono and the chart draws no
 * text rather than a part-verified mix (fail closed, BQ-259). The engine discloses the skipped text.
 */
export function loadDesignFonts(
  host: FontHost = browserFontHost,
  fonts: readonly DesignFont[] = DESIGN_FONTS,
): Promise<readonly ChartFont[]> {
  return Promise.all(fonts.map((f) => loadDesignFont(f, host)));
}

export type ChartFontsState =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly fonts: readonly ChartFont[] }
  | { readonly status: "failed"; readonly error: ChartFontError };

/**
 * A load-once source for `<Chart>`: it starts on the first chart's mount, never at import. A
 * failure is final for the page's lifetime (no retry: a refused font is not fetched again until a
 * reload), and it is reported once through `report` with its typed reason and file.
 */
export interface ChartFontStore {
  snapshot(): ChartFontsState;
  subscribe(listener: () => void): () => void;
  start(): void;
}

const LOADING: ChartFontsState = { status: "loading" };

/**
 * The default failure report: one structured console line per page load, naming the typed reason
 * and the file (never bytes), so a SHA-256 mismatch (F-03 tamper, CE-T13/CE-T14) is told apart from
 * a fetch failure, an undecodable file or a cmap gap; the engine's ENGINE_ATLAS_GENERATION_FAILED
 * (`no-font`) cannot say which.
 */
export function reportChartFontFailure(error: ChartFontError): void {
  console.error("[chart-fonts] design fonts refused; chart text is not drawn", {
    reason: error.reason,
    file: error.file,
  });
}

export function createChartFontStore(
  load: () => Promise<readonly ChartFont[]>,
  report: (error: ChartFontError) => void = reportChartFontFailure,
): ChartFontStore {
  let state = LOADING;
  let started = false;
  const listeners = new Set<() => void>();
  const settle = (next: ChartFontsState): void => {
    state = next;
    for (const l of [...listeners]) l();
  };
  return {
    snapshot: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    start() {
      if (started) return;
      started = true;
      load().then(
        (fonts) => settle({ status: "ready", fonts }),
        (e: unknown) => {
          const error =
            e instanceof ChartFontError ? e : new ChartFontError("decode", "", String(e));
          report(error);
          settle({ status: "failed", error });
        },
      );
    },
  };
}

/** The page's one store over the vendored fonts (the app root provides it to every chart). */
export const designFontStore: ChartFontStore = createChartFontStore(() => loadDesignFonts());

/**
 * The design-font source (E11-S11 PR C, G-87). With one, a `<Chart>` is created once the fonts
 * settle: with their verified bytes, or with none after a typed failure (fail closed, BQ-259). With
 * none (the default), it is created at mount and only an explicit `options.fonts` reaches the engine.
 */
export const ChartFontsContext = createContext<ChartFontStore | null>(null);
