// The IndexedDB packed-rows cache (E11-S11, K01 BQ-176, BQ-264): the key names every input of
// the atlas; the record holds only the packed rows, the metrics and an FNV-1a checksum. A wrong
// shape, version or checksum is a miss that regenerates. The checksum catches corruption and
// partial writes and is bound to the key (a record copied to another key is a miss); every slot's
// rectangle is range-checked so no UV can leave the packed rows. Tampering with a recomputed
// checksum is F-03's (`atlas.ts`, CE-T14).
import type { AtlasConfig } from "./config.js";
import { fnv1a, fnv1aHex } from "./hash.js";
import { METRIC_STRIDE, type AtlasImage } from "./atlas-build.js";

export const ATLAS_DB = "cv-chart-engine";
export const ATLAS_STORE = "atlas";
export const RECORD_VERSION = 1;
/** Every store call is bounded: a hang is no cache, never a stuck chart (BQ-273). */
export const STORE_TIMEOUT_MS = 250;
/** Records kept: the current one and the one used before it, by recency of use. */
export const KEEP_KEYS = 2;
/** The recency index, most recent first; never a cache key (those contain ";"). */
export const INDEX_KEY = "cv-atlas-recent";
/** Stale records deleted per launch at most: a bloated store costs a bounded tail. */
export const MAX_PRUNE = 16;

export interface AtlasRecord {
  readonly v: number;
  readonly usedHeight: number;
  readonly rows: Uint8Array;
  readonly metrics: Float32Array;
  readonly checksum: number;
}

/** Every field of the table, each family's font digest and the glyph-set hash (K01 BQ-176). */
export function cacheKey(cfg: AtlasConfig, digests: readonly string[], setHash: string): string {
  const fams = cfg.families.map(
    (f, i) => `${f.family}|${digests[i] ?? ""}|${f.weight}|${f.rasterPx}|${f.spread}`,
  );
  const atlas = `${setHash}|${cfg.width}x${cfg.height}|p${cfg.pad}|${cfg.edt}|g${cfg.generatorVersion}`;
  return `${fams.join(";")};${atlas}`;
}

/** FNV-1a over the key, the rows and the metrics: the record is bound to its key. */
export function checksum(rows: Uint8Array, metrics: Float32Array, key: string): number {
  const seed = fnv1a(rows, parseInt(fnv1aHex(key), 16));
  return fnv1a(new Uint8Array(metrics.buffer, metrics.byteOffset, metrics.byteLength), seed);
}

export function encodeRecord(img: AtlasImage, key: string): AtlasRecord {
  const { usedHeight, rows, metrics } = img;
  return { v: RECORD_VERSION, usedHeight, rows, metrics, checksum: checksum(rows, metrics, key) };
}

/** Whether slot `i`'s rectangle lies inside the packed rows and its metrics are finite. */
export function slotInBounds(
  metrics: Float32Array,
  i: number,
  width: number,
  used: number,
  families: number,
): boolean {
  const at = i * METRIC_STRIDE;
  const [x, y, w, h, adv, bx, by, src] = metrics.subarray(at, at + METRIC_STRIDE) as unknown as [
    number,
    number,
    number,
    number,
    number,
    number,
    number,
    number,
  ];
  if (![x, y, w, h, src].every(Number.isInteger) || ![adv, bx, by].every(Number.isFinite)) {
    return false;
  }
  return (
    x >= 0 &&
    y >= 0 &&
    w >= 1 &&
    h >= 1 &&
    x + w <= width &&
    y + h <= used &&
    src >= 0 &&
    src < families
  );
}

/** The record as an atlas, or null when its shape, version, checksum or a slot is wrong. */
export function decodeRecord(
  raw: unknown,
  cfg: AtlasConfig,
  slots: number,
  key: string,
): AtlasImage | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Partial<AtlasRecord>;
  const { usedHeight: used, rows, metrics } = r;
  if (r.v !== RECORD_VERSION || !Number.isInteger(used) || (used as number) < 1) return null;
  if ((used as number) > cfg.height || !(rows instanceof Uint8Array)) return null;
  if (!(metrics instanceof Float32Array) || metrics.length !== slots * METRIC_STRIDE) return null;
  if (rows.length !== cfg.width * (used as number) || r.checksum !== checksum(rows, metrics, key)) {
    return null;
  }
  let ink = 0;
  for (let i = 0; i < slots; i += 1) {
    if (!slotInBounds(metrics, i, cfg.width, used as number, cfg.families.length)) return null;
    ink += (metrics[i * METRIC_STRIDE + 2] as number) * (metrics[i * METRIC_STRIDE + 3] as number);
  }
  const occupancyPct = (100 * ink) / (cfg.width * cfg.height);
  return {
    width: cfg.width,
    height: cfg.height,
    usedHeight: used as number,
    rows,
    metrics,
    occupancyPct,
  };
}

/** A one-shot timer; it may return its cancel. */
export type SetTimer = (cb: () => void, ms: number) => void | (() => void);

/** `p`, or a rejection after `ms` on the injected timer, which is cancelled once `p` settles. */
export function bounded<T>(p: Promise<T>, setTimer: SetTimer, ms = STORE_TIMEOUT_MS): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const cancel = setTimer(() => reject(new Error(`atlas store: no answer in ${ms} ms`)), ms);
    const settle = (): void => {
      if (typeof cancel === "function") cancel();
    };
    p.then(
      (v) => {
        settle();
        resolve(v);
      },
      (e: unknown) => {
        settle();
        reject(e instanceof Error ? e : new Error(String(e)));
      },
    );
  });
}
