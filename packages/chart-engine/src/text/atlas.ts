// The atlas service (E11-S11 PR A): one CPU atlas per runtime (BQ-277), built from the app's
// font bytes. Plain code, not a statechart (an engine lifecycle, not a catalogue one):
//   idle → keying → (cache hit: verifying | miss: generating) → ready | failed
// A hit is held until F-03 re-derives the trading glyphs and finds them byte-identical (BQ-265);
// a bad record or a mismatch emits ENGINE_ATLAS_CACHE_INVALID once and regenerates. Generation
// is one task per family, mono first, each after a timer yield (BQ-276). Without fonts, or on a
// load, coverage, pack or raster failure, ENGINE_ATLAS_GENERATION_FAILED is emitted once with
// `details.atlasReason`; no fallback face is ever used (BQ-259). A store that throws, hangs past
// 250 ms or rejects a write, or a key that cannot be digested, is no cache, silently (BQ-273).
// The faces are released once the atlas is built or failed; `dispose` stops a build in flight.
import {
  AtlasBuildError,
  glyphSdf,
  matchesSlot,
  packAtlas,
  sources,
  type AtlasImage,
  type AtlasReason,
  type GlyphSdf,
} from "./atlas-build.js";
import {
  bounded,
  cacheKey,
  decodeRecord,
  encodeRecord,
  INDEX_KEY,
  KEEP_KEYS,
  MAX_PRUNE,
  type SetTimer,
} from "./atlas-cache.js";
import { ENGINE_ATLAS_CACHE_INVALID, ENGINE_ATLAS_GENERATION_FAILED } from "./codes.js";
import { ATLAS_CONFIG, TRADING_GLYPHS, type AtlasConfig } from "./config.js";
import { atlasGlyphs, glyphSetHash, type GlyphEntry } from "./glyph-set.js";
import type { ChartFont, KvStore, TextPlatform } from "./platform.js";

export { ENGINE_ATLAS_CACHE_INVALID, ENGINE_ATLAS_GENERATION_FAILED };

export type AtlasPhase = "idle" | "keying" | "verifying" | "generating" | "ready" | "failed";

/** `ChartEvents.error.details` on ENGINE_ATLAS_GENERATION_FAILED only (BQ-272). */
export interface AtlasDetails {
  readonly atlasReason: AtlasReason;
}

/** `engine.atlas.*` (internal; `FrameStats` is frozen, BQ-272). */
export interface AtlasCounters {
  cacheHit: boolean;
  /** Generation only (raster, EDT, pack), summed over the family tasks. */
  generateMs: number;
  occupancyPct: number;
  /** Glyphs rasterised, F-03's re-derivations included. */
  rasterized: number;
}

export interface AtlasDeps {
  readonly platform: TextPlatform | null;
  now(): number;
  readonly setTimer: SetTimer;
  /** The atlas is ready: upload it into every chart's context. */
  ready(img: AtlasImage): void;
  emit(code: string, message: string, recoverable: boolean, details?: AtlasDetails): void;
  readonly config?: AtlasConfig;
}

/** Thrown inside a build that `dispose` stopped: nothing is published or emitted. */
class Disposed extends Error {}

/** Why the atlas failed, kept so a chart that opens later is told too (BQ-259). */
export interface AtlasFailure {
  readonly message: string;
  readonly details: AtlasDetails;
}

export class AtlasService {
  phase: AtlasPhase = "idle";
  image: AtlasImage | null = null;
  failure: AtlasFailure | null = null;
  readonly counters: AtlasCounters = {
    cacheHit: false,
    generateMs: 0,
    occupancyPct: 0,
    rasterized: 0,
  };
  private readonly cfg: AtlasConfig;
  private readonly glyphs: GlyphEntry[];
  private invalidSent = false;
  private disposed = false;
  private loaded: unknown[] = [];
  private store: KvStore | null = null;
  private lateClose = false;
  private readonly closed = new WeakSet<KvStore>();

  constructor(private readonly deps: AtlasDeps) {
    this.cfg = deps.config ?? ATLAS_CONFIG;
    this.glyphs = atlasGlyphs(this.cfg);
  }

  /** Builds the atlas once; later calls (more charts) do nothing. Never rejects. */
  start(fonts: readonly ChartFont[]): Promise<void> {
    if (this.phase !== "idle") return Promise.resolve();
    this.phase = "keying";
    return this.run(fonts)
      .catch((e: unknown) => this.fail(e))
      .finally(() => this.release());
  }

  /** The runtime is gone: a build in flight stops at its next step; the faces are released. */
  dispose(): void {
    this.disposed = true;
    this.release();
  }

  private async run(fonts: readonly ChartFont[]): Promise<void> {
    const p = this.deps.platform;
    if (p === null) throw new AtlasBuildError("font-load", "no font platform in this runtime");
    const chosen = this.cfg.families.map((f) =>
      fonts.find((x) => x.family === f.family && x.weight === f.weight),
    );
    const missing = this.cfg.families.filter((_, i) => chosen[i] === undefined);
    if (missing.length > 0) {
      const names = missing.map((f) => `${f.family} ${f.weight}`).join(", ");
      throw new AtlasBuildError("no-font", `no font bytes for ${names}`);
    }
    const fs = chosen as ChartFont[];
    // The digest only names the cache entry: a failure is no cache, never a failed atlas.
    const digests = await Promise.all(fs.map((f) => p.digest(f.bytes))).catch(() => null);
    this.alive();
    const key = digests && cacheKey(this.cfg, digests, glyphSetHash(this.cfg));
    const store = key === null ? null : await this.open(p);
    const raw = store === null || key === null ? null : await this.quiet(store.get(key));
    this.alive();
    let faces: unknown[] | null = null;
    if (store !== null && key !== null && raw !== null && raw !== undefined) {
      const hit = decodeRecord(raw, this.cfg, this.glyphs.length, key);
      if (hit !== null) {
        this.phase = "verifying";
        faces = await this.faces(p, fs);
        await this.yieldTask(); // off the first-frame path: text stays held until verified
        this.alive(); // a dispose in this tick must not re-derive against released faces
        if (this.verify(p, fs, faces, hit)) {
          this.counters.cacheHit = true;
          this.publish(hit);
          await this.quiet(this.remember(store, key));
          return;
        }
      }
      this.invalid(hit === null ? "failed its shape, version or checksum check" : "failed F-03");
      await this.quiet(store.delete(key));
    }
    this.phase = "generating";
    faces ??= await this.faces(p, fs);
    const src = sources(p, fs, this.glyphs);
    const slots: GlyphSdf[] = [];
    for (let fam = 0; fam < this.cfg.families.length; fam += 1) {
      await this.yieldTask(); // one family per task, mono first (BQ-276)
      this.alive();
      const t0 = this.deps.now();
      this.glyphs.forEach((g, i) => {
        if (g.family === fam) slots[i] = this.raster(p, faces as unknown[], g, src[i] as number);
      });
      this.counters.generateMs += this.deps.now() - t0;
    }
    const t0 = this.deps.now();
    const img = packAtlas(this.cfg, slots);
    this.counters.generateMs += this.deps.now() - t0;
    this.publish(img);
    if (store !== null && key !== null) await this.quiet(this.write(store, key, img));
  }

  /** F-03: the trading glyphs, re-derived from the font, equal the cached ones byte for byte. */
  private verify(p: TextPlatform, fs: ChartFont[], faces: unknown[], img: AtlasImage): boolean {
    for (const ch of TRADING_GLYPHS) {
      const i = this.glyphs.findIndex((g) => g.family === 0 && g.ch === ch);
      const g = this.glyphs[i] as GlyphEntry;
      const src = sources(p, fs, [g])[0] as number;
      if (!matchesSlot(img, i, this.raster(p, faces, g, src))) return false;
    }
    return true;
  }

  private raster(p: TextPlatform, faces: unknown[], g: GlyphEntry, src: number): GlyphSdf {
    this.counters.rasterized += 1;
    try {
      return glyphSdf(p, this.cfg, faces, g, src);
    } catch (e) {
      if (e instanceof AtlasBuildError) throw e;
      throw new AtlasBuildError("raster", `rasteriser failed on U+${g.cp.toString(16)}`);
    }
  }

  private async faces(p: TextPlatform, fs: ChartFont[]): Promise<unknown[]> {
    const loads = fs.map((f) =>
      p.loadFace(f).then((face) => {
        this.loaded.push(face); // released even when another face fails or `dispose` ran
        return face;
      }),
    );
    const faces = await Promise.all(loads).catch(() => {
      throw new AtlasBuildError("font-load", "a font's bytes did not load as a face");
    });
    this.alive();
    return faces;
  }

  private release(): void {
    const p = this.deps.platform;
    for (const face of this.loaded.splice(0)) p?.releaseFace(face);
    this.lateClose = true; // a store still opening arrives to a runtime that is done with it
    this.closeStore();
  }

  /** Opens the store; one that answers after the bound is closed on arrival, never leaked. */
  private async open(p: TextPlatform): Promise<KvStore | null> {
    const opening = Promise.resolve().then(() => p.store());
    opening.then(
      (s) => {
        if (s === null) return;
        if (this.lateClose) this.closeOnce(s);
        else this.store = s;
      },
      () => undefined,
    );
    try {
      const store = await this.bound(opening);
      return this.lateClose ? null : store; // disposed while opening: the store is already closed
    } catch {
      this.lateClose = true; // answered after the bound (or failed): no connection stays open
      this.closeStore();
      return null;
    }
  }

  private closeStore(): void {
    const s = this.store;
    this.store = null;
    if (s !== null) this.closeOnce(s);
  }

  /** Closes a store at most once; a close that throws leaves nothing to release. */
  private closeOnce(s: KvStore): void {
    if (this.closed.has(s)) return;
    this.closed.add(s);
    try {
      s.close();
    } catch {
      // nothing left to release
    }
  }

  private async write(store: KvStore, key: string, img: AtlasImage): Promise<void> {
    await this.bound(store.put(key, encodeRecord(img, key)));
    await this.remember(store, key);
  }

  /** Puts `key` first in the recency index and deletes the records it no longer keeps. */
  private async remember(store: KvStore, key: string): Promise<void> {
    const prev = await this.bound(store.get(INDEX_KEY));
    const known = Array.isArray(prev) ? prev.filter((k): k is string => typeof k === "string") : [];
    const keep = [key, ...known.filter((k) => k !== key)].slice(0, KEEP_KEYS);
    await this.bound(store.put(INDEX_KEY, keep));
    const stale = (await this.bound(store.keys())).filter(
      (k) => k !== INDEX_KEY && !keep.includes(k),
    );
    for (const k of stale.slice(0, MAX_PRUNE)) await this.bound(store.delete(k));
  }

  private alive(): void {
    if (this.disposed) throw new Disposed();
  }

  private publish(img: AtlasImage): void {
    this.alive();
    this.image = img;
    this.phase = "ready";
    this.counters.occupancyPct = img.occupancyPct;
    this.deps.ready(img);
  }

  private invalid(why: string): void {
    if (this.invalidSent) return; // once per runtime launch (BQ-264)
    this.invalidSent = true;
    const msg = `Cached text atlas ${why}: discarded and regenerated`;
    this.deps.emit(ENGINE_ATLAS_CACHE_INVALID, msg, true);
  }

  private fail(e: unknown): void {
    if (this.disposed || e instanceof Disposed) return; // nobody is left to tell
    this.phase = "failed";
    const reason = e instanceof AtlasBuildError ? e.reason : "raster";
    const why = e instanceof Error ? e.message : "unknown failure";
    const message = `Text atlas not generated (${reason}): ${why}; chart text is not drawn`;
    this.failure = { message, details: { atlasReason: reason } };
    this.deps.emit(ENGINE_ATLAS_GENERATION_FAILED, message, false, { atlasReason: reason });
  }

  private bound<T>(p: Promise<T>): Promise<T> {
    return bounded(p, (cb, ms) => this.deps.setTimer(cb, ms));
  }

  /** A store call that fails or hangs is null: no cache, no code (BQ-273). */
  private quiet<T>(p: Promise<T>): Promise<T | null> {
    return this.bound(p).catch(() => {
      this.closeStore(); // a store that hangs or fails is dropped, its connection with it
      return null;
    });
  }

  private yieldTask(): Promise<void> {
    return new Promise((resolve) => this.deps.setTimer(resolve, 0));
  }
}
