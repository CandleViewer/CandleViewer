// Glyph runs and atlas metrics (E11-S11 PR B, README BQ-269 to BQ-271): a string becomes a run of
// atlas slots once, on a data or format change, and the frame path only walks runs. Runs live in
// an arena (`Uint16Array` slot ids, `Float32Array` advances) behind a bounded string → run cache
// (4,096 runs, oldest first out), so a label or a plugin string allocates on a miss only. A
// character outside the set draws `?` from the same family and is counted; `debugAsserts`
// throws instead (no silent skip, K01 item 2). `measure` is S06's `TextMeasure` (BQ-202): one
// metrics source for the gutter and the draw. DOM-free (C-2.16).
import { METRIC_STRIDE, type AtlasImage } from "./atlas-build.js";
import { ATLAS_CONFIG, type AtlasConfig } from "./config.js";
import { atlasGlyphs } from "./glyph-set.js";

/** Size classes 0 / 1 / 2 in CSS px (E11-D02 §6); density and text scale are T04's (G-51). */
export const SIZE_PX = [10, 11, 13] as const;
/** §8 `TextStyle.sizeClass` to a class (C-103: xs → 0, sm → 1, md → 2; no §8 change). */
export const SIZE_CLASS = { xs: 0, sm: 1, md: 2 } as const;
/** The label box, in ems (`fixedMeasure`'s 1.2 line box). */
export const LINE_EM = 1.2;
export const RUN_CACHE_MAX = 4096;
const ARENA_GLYPHS = RUN_CACHE_MAX * 8;
const REPLACEMENT = 0x3f; // `?`

/** S06's `TextMeasure` (src/axes/gutter.ts), structurally: no import back into the axes. */
export interface TextMeasure {
  width(text: string): number;
  readonly height: number;
}

export interface GlyphRun {
  readonly text: string;
  readonly family: number;
  /** The run's slots: arena [start, start + count), valid only in `generation`. */
  readonly start: number;
  readonly count: number;
  /** The arena generation the run was written in; a flush makes it stale (`live`). */
  readonly generation: number;
  /** Sum of advances, raster px of the family. */
  readonly width: number;
}

/** `engine.text.*` (internal; `FrameStats` is frozen, BQ-272). */
export interface TextCounters {
  replacedGlyphs: number;
  runMisses: number;
  /** Arena resets: every run dropped at once when the arena is full. */
  flushes: number;
}

export class AtlasMetrics {
  readonly ids = new Uint16Array(ARENA_GLYPHS);
  readonly advances = new Float32Array(ARENA_GLYPHS);
  readonly counters: TextCounters = { replacedGlyphs: 0, runMisses: 0, flushes: 0 };
  private used = 0;
  /** Bumped by every flush: a run of an older generation points at other strings' slots. */
  generation = 0;
  private readonly slots: Map<number, number>[];
  private readonly runs: Map<string, GlyphRun>[];
  private readonly measures: TextMeasure[];

  constructor(
    readonly image: AtlasImage,
    readonly cfg: AtlasConfig = ATLAS_CONFIG,
    private readonly debugAsserts = false,
  ) {
    this.slots = cfg.families.map(() => new Map());
    this.runs = cfg.families.map(() => new Map());
    const glyphs = atlasGlyphs(cfg);
    if (image.metrics.length !== glyphs.length * METRIC_STRIDE)
      throw new RangeError("chart-engine: atlas metrics do not match the glyph table");
    glyphs.forEach((g, i) => this.slots[g.family]?.set(g.cp, i));
    for (const [f, slots] of this.slots.entries())
      if (!slots.has(REPLACEMENT)) throw new RangeError(`chart-engine: family ${f} has no '?'`);
    this.measures = SIZE_PX.map((_, cls) => ({
      width: (text: string) => this.measure(text, cls),
      height: Math.round(SIZE_PX[cls as 0] * LINE_EM),
    }));
  }

  /** The family's raster px: a run's advances are in it. */
  rasterPx(family: number): number {
    return this.cfg.families[family]?.rasterPx ?? 1;
  }

  /** The run for `text` in `family`; built (and cached) on a miss only. */
  run(text: string, family = 0): GlyphRun {
    const cache = this.runs[family] as Map<string, GlyphRun>;
    const hit = cache.get(text);
    if (hit !== undefined) return hit;
    this.counters.runMisses += 1;
    // A string longer than the arena draws its head; the run is cached under the whole string.
    const body = text.length > ARENA_GLYPHS ? text.slice(0, ARENA_GLYPHS) : text;
    if (this.used + body.length > ARENA_GLYPHS) this.flush();
    if (cache.size >= RUN_CACHE_MAX) cache.delete(cache.keys().next().value as string);
    const slots = this.slots[family] as Map<number, number>;
    const m = this.image.metrics;
    const start = this.used;
    let width = 0;
    for (const ch of body) {
      const cp = ch.codePointAt(0) ?? REPLACEMENT;
      let slot = slots.get(cp);
      if (slot === undefined) {
        if (this.debugAsserts)
          throw new RangeError(`chart-engine: U+${cp.toString(16)} not in set`);
        this.counters.replacedGlyphs += 1;
        slot = slots.get(REPLACEMENT) as number; // checked in the constructor
      }
      const adv = m[slot * METRIC_STRIDE + 4] ?? 0;
      this.ids[this.used] = slot;
      this.advances[this.used] = adv;
      this.used += 1;
      width += adv;
    }
    const run = {
      text,
      family,
      start,
      count: this.used - start,
      generation: this.generation,
      width,
    };
    cache.set(text, run);
    return run;
  }

  /**
   * `run` if its slots are still in the arena; after a flush, the run rebuilt from its string
   * (a retained run never reads another string's slots). `debugAsserts` throws on a stale run.
   */
  live(run: GlyphRun): GlyphRun {
    if (run.generation === this.generation) return run;
    if (this.debugAsserts) throw new RangeError("chart-engine: stale glyph run after a flush");
    return this.run(run.text, run.family);
  }

  /** Width of `text` at class `cls`, CSS px. */
  measure(text: string, cls: number, family = 0): number {
    return (this.run(text, family).width * (SIZE_PX[cls as 0] ?? 11)) / this.rasterPx(family);
  }

  /** S06's `TextMeasure` for class `cls` (the same object every call). */
  measureFor(cls: number): TextMeasure {
    return this.measures[cls] ?? (this.measures[1] as TextMeasure);
  }

  private flush(): void {
    this.counters.flushes += 1;
    this.used = 0;
    this.generation += 1;
    for (const cache of this.runs) cache.clear();
  }
}
