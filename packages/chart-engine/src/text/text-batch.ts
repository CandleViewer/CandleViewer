// A retained text batch (E11-S11 PR B, README BQ-268): one scene node per (pane, kind) — cell
// text (the outline program), axis text and drawing text — whose ring of stride-12 glyph
// instances is one instanced draw. A label is written from its cached run (`AtlasMetrics.run`):
// device px, y up, the atlas UV rect flipped so the glyph's top row is up, the colour per glyph.
// Three modes: `glyphs` with an atlas; `labels` on a `degraded-2d` chart, which records each
// string, its place and its ink for the 2D backend's `fillText` (C-104); `off` on a WebGL2 chart
// without an atlas: nothing is drawn (skipped and disclosed, BQ-259). DOM- and GL-free; nothing
// is allocated per label once the ring and the label table are warm.
import { PROGRAM } from "../scene/instance-layout.js";
import { ContentNode, type NodeOptions } from "../scene/node.js";
import type { BatchSink } from "../scene/pool.js";
import { METRIC_STRIDE } from "./atlas-build.js";
import { type AtlasMetrics, SIZE_PX } from "./glyph-runs.js";

export const TEXT_STRIDE = 12;
/** The SDF atlas's texture number (`ATLAS_TEXTURE` in src/gl/textures.ts). */
const ATLAS = 1;
/** Floats per 2D label: x, y (device px, y down, the box's centre line), size px, align. */
export const LABEL_STRIDE = 4;
/** The baseline sits this many ems below a label's centre line (tabular digits' half cap). */
export const BASELINE_EM = 0.36;

/** A colour resolved once per theme: RGBA (0..1) for the GL ring, CSS for `fillText`. */
export interface TextInk {
  readonly rgba: Float32Array;
  readonly css: string;
}

export type TextMode = "off" | "glyphs" | "labels";

export class TextBatch extends ContentNode {
  data = new Float32Array(0);
  readonly head = 0;
  readonly stride = TEXT_STRIDE;
  /** Glyph instances written since `begin`. */
  count = 0;
  mode: TextMode = "off";
  metrics: AtlasMetrics | null = null;
  /** The 2D label table: `labels` strings with their inks and `LABEL_STRIDE` floats each. */
  labels = 0;
  readonly texts: string[] = [];
  readonly inks: string[] = [];
  lab = new Float32Array(LABEL_STRIDE * 64);
  /** Ring and label-table reallocations: 0 once warm (the bench's allocation count). */
  grown = 0;
  private dpr = 1;
  private deviceH = 0;

  constructor(
    id: string,
    readonly program: number = PROGRAM.sdfText,
    opts?: NodeOptions,
  ) {
    super(id, opts);
  }

  /** Starts a rewrite for a store `deviceH` device px high at `dpr`. */
  begin(dpr: number, deviceH: number): void {
    this.count = 0;
    this.labels = 0;
    this.dpr = dpr;
    this.deviceH = deviceH;
  }

  /**
   * One label at CSS (x, y), y its centre line; `align` 0 left, 0.5 centre, 1 right of x; class
   * `cls` (0 / 1 / 2). In `glyphs` mode its run's glyphs; in `labels` mode its string.
   */
  label(text: string, x: number, y: number, cls: number, align: number, ink: TextInk): void {
    const px = SIZE_PX[cls as 0] ?? 11;
    if (this.mode === "labels") {
      this.record(text, x, y, px, align, ink.css);
      return;
    }
    const metrics = this.metrics;
    if (this.mode !== "glyphs" || metrics === null) return;
    const run = metrics.run(text, 0);
    const scale = (px * this.dpr) / metrics.rasterPx(0);
    const m = metrics.image.metrics;
    const aw = metrics.image.width;
    const ah = metrics.image.height;
    let pen = x * this.dpr - align * run.width * scale;
    const baseline = (y + BASELINE_EM * px) * this.dpr;
    this.reserve(this.count + run.count);
    const f = this.data;
    const c = ink.rgba;
    for (let k = 0; k < run.count; k += 1) {
      const s = (metrics.ids[run.start + k] as number) * METRIC_STRIDE;
      const w = m[s + 2] as number;
      const h = m[s + 3] as number;
      let o = this.count * TEXT_STRIDE;
      if (w > 0 && h > 0) {
        const top = baseline + (m[s + 6] as number) * scale;
        f[o++] = pen + (m[s + 5] as number) * scale;
        f[o++] = this.deviceH - top - h * scale; // y up: the quad's bottom edge
        f[o++] = w * scale;
        f[o++] = h * scale;
        f[o++] = (m[s] as number) / aw;
        f[o++] = ((m[s + 1] as number) + h) / ah; // the bottom row at the quad's bottom
        f[o++] = w / aw;
        f[o++] = -h / ah;
        for (let i = 0; i < 4; i += 1) f[o++] = c[i] as number;
        this.count += 1;
      }
      pen += (metrics.advances[run.start + k] as number) * scale;
    }
  }

  collect(sink: BatchSink): boolean {
    const e = sink.append();
    e.nodeId = this.id;
    e.program = this.program;
    e.texture = this.mode === "glyphs" ? ATLAS : 0;
    e.first = 0;
    e.count = this.mode === "labels" ? this.labels : this.count;
    return true;
  }

  private record(text: string, x: number, y: number, px: number, align: number, css: string) {
    const n = this.labels;
    if ((n + 1) * LABEL_STRIDE > this.lab.length) {
      const next = new Float32Array(this.lab.length * 2);
      next.set(this.lab);
      this.lab = next;
      this.grown += 1;
    }
    const o = n * LABEL_STRIDE;
    this.lab[o] = x * this.dpr;
    this.lab[o + 1] = y * this.dpr;
    this.lab[o + 2] = px * this.dpr;
    this.lab[o + 3] = align;
    this.texts[n] = text;
    this.inks[n] = css;
    this.labels = n + 1;
  }

  private reserve(glyphs: number): void {
    if (glyphs * TEXT_STRIDE <= this.data.length) return;
    let size = Math.max(TEXT_STRIDE * 256, this.data.length);
    while (size < glyphs * TEXT_STRIDE) size *= 2;
    const next = new Float32Array(size);
    next.set(this.data);
    this.data = next;
    this.grown += 1;
  }
}
