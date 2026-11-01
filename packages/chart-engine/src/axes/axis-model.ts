// One chart's axes (E11-S06, README BQ-186 to BQ-204): the price and time candidates, decimation,
// the gutter, the grid instances, the retained label lists the DOM mirror shows, the stops'
// names and the announcements. `update` runs once per frame before collect and returns at once
// when nothing it reads changed (a signature of the viewport, the layout and the theme), so a
// still chart costs a compare; a TRANSFORM or LAYOUT change rebuilds the axes; before the main
// series brings its tick size there are no axes at all (no grid, no message). The kept labels of
// both axes are written into one SDF text batch, one draw call (E11-S06 PR 3 with E11-S11 PR B,
// closing G-47), measured with the atlas metrics once the atlas is ready.
import { PROGRAM } from "../scene/instance-layout.js";
import type { Rect } from "../scene/layout-engine.js";
import { TextBatch, type TextInk } from "../text/text-batch.js";
import { displayValue, priceToScreen, screenToTime } from "../viewport/transform.js";
import type { PaneTransform, ViewportState } from "../viewport/types.js";
import { TickSet } from "./decimate.js";
import { clockText, createZoned, dateText, formatNumber, ZoneClock } from "./format.js";
import { AxisGrid, GRID_NODE_ID, GRID_TOKENS, parseHex, TIER } from "./grid.js";
import { fixedMeasure, GUTTER_PAD_PX, GutterCache, type TextMeasure } from "./gutter.js";
import { PRICE_KIND, PriceTicks } from "./price-ticks.js";
import { RANK, TimeTicks } from "./time-ticks.js";

export const AXIS_TEXT_ID = "main/axis-text";
/** The axis label token (E11-D02 §6) and the class labels are set in (compact 11 px). */
export const LABEL_TOKEN = "color.text.secondary";
export const LABEL_CLASS = 1;

/** E11-D02 §6's compact density gaps G, CSS px (density and text scale are T04's: G-51). */
export const DENSITY_GAP = { time: 80, price: 40 } as const;
/** The collision gap, edge to edge: 1.5 label heights (E11-D02 §5.1). */
export const COLLISION_GAP = 1.5;
/** A label keeps 8 px clear of the tag's right and the cluster's left edge (E11-D02 §5.1). */
export const ZONE_PAD_PX = 8;

/** The layout fields the axes read (the `LayoutEngine`'s own). */
export interface AxisLayout {
  readonly width: number;
  readonly height: number;
  readonly priceGutter: number;
  readonly panes: readonly { readonly rect: Rect }[];
  readonly timeAxis: Rect;
}

/** What an axis key announces (BQ-198): the worker composes the text from fresh state. */
export const SAY = {
  none: 0,
  priceRange: 1,
  priceLocked: 2,
  priceAuto: 3,
  timeRange: 4,
  spacing: 5,
  live: 6,
  fitted: 7,
  defaultSpacing: 8,
} as const;

export const UPDATE = { grid: 1, labels: 2, gutter: 4 } as const;
const MODES = ["linear", "log", "percent", "indexed"];
const SIG = 21;
type Theme = Readonly<Record<string, string>>;

export class AxisModel {
  readonly priceSet = new TickSet();
  readonly timeSet = new TickSet();
  readonly price = new PriceTicks();
  readonly time: TimeTicks;
  readonly grid = new AxisGrid(GRID_NODE_ID, { zIndex: -1 });
  /** Both axes' labels: one retained SDF batch (`labels` on a 2D chart, `off` without atlas). */
  readonly text = new TextBatch(AXIS_TEXT_ID, PROGRAM.sdfText);
  private readonly ink: { rgba: Float32Array; css: string } = {
    rgba: new Float32Array(4),
    css: "",
  };
  readonly gutter = new GutterCache();
  /** `engine.axis.*` (BQ-204): internal, as `FrameStats` is frozen. */
  readonly counters = { ticksDrawn: [0, 0], labelsDecimated: [0, 0] };
  /** The time strip's tag (left) and cluster (right) widths, CSS px: 0 until S07 / S15. */
  readonly zones = { tag: 0, cluster: 0 };
  /** The last-price label's tick, pinned first (BQ-191); NaN until S07 / E12 feed it. */
  lastPriceTick = Number.NaN;
  /** The retained labels per axis in value order, and the stops' accessible names. */
  readonly priceLabels: string[] = [];
  readonly timeLabels: string[] = [];
  priceName = "";
  timeName = "";
  /** A pending axis-key announcement (`SAY`); taken by `takeSay`. */
  say: number = SAY.none;
  private readonly sig = new Float64Array(SIG).fill(Number.NaN);
  private readonly cur = new Float64Array(SIG);
  private readonly z = createZoned();
  private theme: Theme | null = null;
  private palette: Theme | null = null;
  private mode = "";
  private auto = true;
  private readonly widthOf = (text: string): number => this.measure.width(text);

  constructor(
    timeZone = "UTC",
    public measure: TextMeasure = fixedMeasure(),
  ) {
    this.time = new TimeTicks(new ZoneClock(timeZone));
  }

  get timeZone(): string {
    return this.time.clock.timeZone;
  }

  /**
   * Rebuilds the axes when an input changed: `UPDATE` bits, 0 when nothing did. With `gutter`
   * set the caller lays out again with `gutter.width` and calls once more.
   */
  update(vp: ViewportState, layout: AxisLayout, theme: Theme): number {
    const rect = layout.panes[0]?.rect;
    const p = vp.panes[0];
    // No series, no scale: the axes wait for the main series' tick size (its `bars` params).
    if (rect === undefined || p === undefined || !(p.tickSize > 0)) return 0;
    if (!this.changed(vp, layout, p, rect, theme)) return 0;
    const m = this.measure;
    const ps = this.priceSet;
    this.price.update(vp, 0, rect[1], rect[3], DENSITY_GAP.price, m.height, ps);
    if (ps.n > 0) {
      const g = this.gutter.widthFor(this.price.kind, this.price.decimals, this.price.magnitude, m);
      if (g !== layout.priceGutter) return UPDATE.gutter;
    }
    const gap = COLLISION_GAP * m.height;
    const pin = this.lastPriceTick;
    const pinY = Number.isFinite(pin) ? priceToScreen(vp, 0, pin) : Number.NaN;
    const c = this.counters;
    c.labelsDecimated[1] = ps.decimate(gap, rect[1], rect[1] + rect[3], Infinity, pinY, m.height);
    const ts = this.timeSet;
    this.time.update(vp, rect[2], DENSITY_GAP.time, this.widthOf, ts);
    // BQ-190: one routine for both exclusion zones; a P0 date shifts in at a zone's edge only.
    // The strip's own ends are no zone (a P0 there is a hidden blocker like any label), so with
    // both zones 0 wide until S07 / S15 draw the tag and the cluster, nothing shifts.
    const { tag, cluster } = this.zones;
    const lo = tag > 0 ? tag + ZONE_PAD_PX : 0;
    const hi = cluster > 0 ? rect[2] - cluster - ZONE_PAD_PX : rect[2];
    const shift = tag > 0 || cluster > 0 ? RANK.day : Infinity;
    c.labelsDecimated[0] = ts.decimate(gap, lo, hi, shift);
    this.writeGrid(vp, layout, rect, theme);
    this.writeText(vp, layout, rect);
    const a = this.relabel(ps, this.priceLabels);
    const b = this.relabel(ts, this.timeLabels);
    c.ticksDrawn[0] = this.timeLabels.length;
    c.ticksDrawn[1] = this.priceLabels.length;
    const restate = a || b || p.scaleMode !== this.mode || p.autoScale !== this.auto;
    this.mode = p.scaleMode;
    this.auto = p.autoScale;
    return restate && this.names(p.scaleMode, p.autoScale)
      ? UPDATE.grid | UPDATE.labels
      : UPDATE.grid;
  }

  /** Measures with `m` from now on (the atlas metrics, BQ-271): the gutter re-measures. */
  setMeasure(m: TextMeasure): void {
    this.measure = m;
    this.invalidate();
  }

  /** Forces the next `update` to rebuild (a restored context re-uploads the grid ring). */
  invalidate(): void {
    this.theme = null; // a signature mismatch whatever the view
  }

  /** The pending announcement's text, once (BQ-198); null when none. */
  takeSay(vp: ViewportState): string | null {
    const say = this.say;
    this.say = SAY.none;
    switch (say) {
      case SAY.priceRange:
        return `${this.fmtPrice(vp, this.price.lo)} to ${this.fmtPrice(vp, this.price.hi)}`;
      case SAY.priceLocked:
        return "Price scale locked";
      case SAY.priceAuto:
        return "Price scale: auto";
      case SAY.timeRange: {
        const from = this.fmtTime(screenToTime(vp, 0));
        return `${from} to ${this.fmtTime(screenToTime(vp, vp.plotWidth))}`;
      }
      case SAY.spacing:
        return `${Math.round(vp.barSpacing)} pixels per bar`;
      case SAY.live:
        return "Following live";
      case SAY.fitted:
        return `Fitted ${formatNumber(vp.map.length, 0)} bars`;
      case SAY.defaultSpacing:
        return "Default spacing";
      default:
        return null;
    }
  }

  /** BQ-193: minor and major lines at the kept labels, every boundary dashed, both axis rules. */
  private writeGrid(vp: ViewportState, l: AxisLayout, r: Rect, theme: Theme): void {
    const g = this.grid;
    if (theme !== this.palette) {
      this.palette = theme;
      for (let i = 0; i < GRID_TOKENS.length; i += 1)
        parseHex(theme[GRID_TOKENS[i] ?? ""], g.colors, 4 * i);
      parseHex(theme[LABEL_TOKEN], this.ink.rgba, 0);
      this.ink.css = theme[LABEL_TOKEN] ?? "#808080";
    }
    g.begin(vp.dpr, Math.round(l.height * vp.dpr));
    const ps = this.priceSet;
    for (let i = 0; i < ps.n; i += 1) {
      if (ps.kept[i] === 1) g.hLine(ps.at[i] as number, 0, r[2], ps.tier[i] as number);
    }
    const ts = this.timeSet;
    for (let i = 0; i < ts.n; i += 1) {
      const tier = ts.tier[i] as number;
      const x = ts.at[i] as number;
      if (ts.kept[i] === 1 || (tier === TIER.boundary && x >= 0 && x <= r[2])) {
        g.vLine(x, r[1], r[1] + r[3], tier, tier === TIER.boundary);
      }
    }
    g.vLine(r[2], 0, l.height, TIER.rule);
    g.hLine(l.timeAxis[1], 0, r[2], TIER.rule);
  }

  /** The kept labels into the text batch: price left in the gutter, time centred in the strip. */
  private writeText(vp: ViewportState, l: AxisLayout, r: Rect): void {
    const t = this.text;
    t.begin(vp.dpr, Math.round(l.height * vp.dpr));
    if (t.mode === "off") return;
    const ink: TextInk = this.ink;
    const ps = this.priceSet;
    const x = r[2] + GUTTER_PAD_PX / 2;
    for (let i = 0; i < ps.n; i += 1) {
      if (ps.kept[i] === 1) t.label(ps.text[i] ?? "", x, ps.pos[i] as number, LABEL_CLASS, 0, ink);
    }
    const ts = this.timeSet;
    const y = l.timeAxis[1] + l.timeAxis[3] / 2;
    for (let i = 0; i < ts.n; i += 1) {
      if (ts.kept[i] === 1)
        t.label(ts.text[i] ?? "", ts.pos[i] as number, y, LABEL_CLASS, 0.5, ink);
    }
  }

  /** Copies `set`'s kept labels into `out`; true when they differ from what it held. */
  private relabel(set: TickSet, out: string[]): boolean {
    let k = 0;
    let differ = false;
    for (let i = 0; i < set.n; i += 1) {
      if (set.kept[i] !== 1) continue;
      const text = set.text[i] ?? "";
      if (out[k] !== text) {
        differ = true;
        out[k] = text;
      }
      k += 1;
    }
    differ ||= out.length !== k;
    out.length = k;
    return differ;
  }

  /** The stops' accessible names (E11-D02 §7.1, §7.2); true when either changed. */
  private names(mode: string, auto: boolean): boolean {
    const span = (l: readonly string[]): string =>
      l.length === 0 ? "" : `, ${l[0] ?? ""} to ${l[l.length - 1] ?? ""}`;
    const price = `Price axis${span(this.priceLabels)}, ${mode}, ${auto ? "auto" : "locked"}`;
    const time = `${this.timeZone} time axis${span(this.timeLabels)}`;
    const changed = price !== this.priceName || time !== this.timeName;
    this.priceName = price;
    this.timeName = time;
    return changed;
  }

  private fmtPrice(vp: ViewportState, tick: number): string {
    const p = vp.panes[0];
    const v = p === undefined ? Number.NaN : displayValue(p, tick);
    const s = formatNumber(v, this.price.decimals);
    return this.price.kind === PRICE_KIND.percent ? `${s}%` : s;
  }

  private fmtTime(us: number): string {
    const z = this.time.clock.fields(us / 1000, this.z);
    return `${dateText(z)} ${clockText(z.ms, false)}`;
  }

  /** True when any input of the axes moved since the last rebuild (no allocation). */
  private changed(
    vp: ViewportState,
    l: AxisLayout,
    p: Readonly<PaneTransform>,
    r: Rect,
    theme: Theme,
  ): boolean {
    const c = this.cur;
    c[0] = vp.leftIndex;
    c[1] = vp.barSpacing;
    c[2] = vp.plotWidth;
    c[3] = vp.height;
    c[4] = vp.dpr;
    c[5] = vp.map.length;
    c[6] = p.priceLow;
    c[7] = p.priceHigh;
    c[8] = p.plotTop;
    c[9] = p.plotHeight;
    c[10] = p.tickSize;
    c[11] = p.priceOrigin;
    c[12] = p.anchorTick;
    c[13] = MODES.indexOf(p.scaleMode);
    c[14] = (p.inverted ? 1 : 0) + (p.autoScale ? 2 : 0);
    c[15] = l.width;
    c[16] = l.height;
    c[17] = l.priceGutter;
    c[18] = r[1];
    c[19] = r[3];
    c[20] = this.lastPriceTick;
    let same = theme === this.theme;
    for (let i = 0; same && i < SIG; i += 1) {
      const a = c[i] as number;
      const b = this.sig[i] as number;
      same = a === b || (Number.isNaN(a) && Number.isNaN(b));
    }
    this.sig.set(c);
    this.theme = theme;
    return !same;
  }
}
