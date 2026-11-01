// The worker half of the InputRouter (E11-S04 PR 1, 26 §3.11, README BQ-99 to BQ-103): packed
// rows become viewport changes, routed by the layout's rects. The plot pans time on a drag and
// zooms time at the cursor on a wheel (Ctrl+wheel, a trackpad pinch, too: BQ-100); the time axis
// changes `barSpacing` about the plot's right edge. E11-S05 (BQ-122, closes G-5): the price axis's
// drag and wheel zoom price about the pointer and engage the lock, its double-click restores auto,
// and a vertical plot drag pans price only while locked. Two touches pinch about their midpoint.
// Only a one-pointer plot drag coasts. Keys go through the navigator (PR 2, BQ-106 to BQ-109); a
// reduced-motion release never coasts (BQ-104). E11-S06: a key row's target sends it to an axis
// stop's keys (BQ-194). E11-S09 (#446 BQ-19): a mouse or pen down within 12 px of a pane
// boundary (plot or gutter) starts the splitter drag (`splitAt`); hover passes through the band.
// DOM-free and allocation-free per row.
import { DEFAULT_BAR_SPACING, type ChartViewport } from "../viewport/Viewport.js";
import { INPUT, INPUT_STRIDE, KEY } from "../worker/protocol.js";
import { Momentum } from "./momentum.js";
import { priceAxisKey, TARGET, timeAxisKey } from "./axis-keys.js";
import { navigate, resetView } from "./navigator.js";
import { VelocityEstimator } from "./velocity.js";
import { axisDragFactor, MOD, priceDragFactor, REGION, regionAt, wheelFactor } from "./wheel.js";

export interface GestureSink {
  /** A viewport setter ran; `changed` is its result. */
  moved(changed: boolean): void;
  /** The pointer moved to (x, y), CSS px over the canvas: the crosshair follows it (E11-S07). */
  hover(x: number, y: number): void;
  /** Registers the glide with the chart's frame scheduler. */
  animate(m: Momentum): void;
  /** An axis key changed the view (E11-S06): its `SAY` announcement code. */
  say?(code: number): void;
  /**
   * E11-S09 (BQ-19): the boundary below pane `boundary` moved `dy` CSS px. `false` ends the drag
   * (a pane collapsed or restored: the next move must not undo it).
   */
  split?(boundary: number, dy: number): boolean;
}

const Drag = { none: 0, pan: 1, spacing: 2, price: 3 } as const;
/** E11-D02 §8: the splitter's hit band reaches this far each side of a boundary. */
const BAND_HALF_PX = 12;

export class Gestures {
  readonly velocity = new VelocityEstimator();
  readonly momentum: Momentum;
  /** The app's resolved motion mode (`init` / `setMotion`): a reduce release never coasts. */
  reduce = false;
  /** Space is held (BQ-109): the pan-drag modifier E14's tools read; cleared on blur. */
  panModifier = false;
  /** The pointer's last x inside the plot (NaN until it enters): the `+/-` anchor (BQ-108). */
  pointerX = Number.NaN;
  /**
   * E11-S09 (BQ-10): the pane a price-axis key acts on: the last one the pointer was over (0
   * until then). A drag keeps the pane it started in; a wheel acts on the pane under it.
   */
  focusPane = 0;
  private dragPane = 0;
  /** The boundary a splitter drag moves (below pane `splitAt`); -1 when none is under way. */
  private splitAt = -1;
  private drag: number = Drag.none;
  private dragX = 0;
  private dragY = 0;
  /** A price-axis drag zooms about the y it started at. */
  private anchorY = 0;
  private pinched = false;
  /** Two touch slots: pointer ids (NaN when free) and their last x. */
  private readonly ids = new Float64Array([Number.NaN, Number.NaN]);
  private readonly xs = new Float64Array(2);

  constructor(
    private readonly vp: ChartViewport,
    /** The canvas size and price gutter in CSS px, for the regions (the layout engine's). */
    private readonly size: {
      readonly width: number;
      readonly height: number;
      readonly priceGutter?: number;
      /** E11-S09: the pane rows, top to bottom (the layout engine's); one pane when absent. */
      readonly panes?: readonly { readonly rect: readonly [number, number, number, number] }[];
    },
    private readonly sink: GestureSink,
  ) {
    this.momentum = new Momentum((dx) => {
      const changed = vp.pan(dx);
      sink.moved(changed);
      return changed;
    });
  }

  /** A drag, a pinch, a finger down or a glide (E11-S08, BQ-134): hover does not pick then. */
  get active(): boolean {
    const down = !Number.isNaN(this.ids[0] as number) || !Number.isNaN(this.ids[1] as number);
    const busy = this.drag !== Drag.none || this.splitAt >= 0 || this.pinched;
    return busy || down || this.momentum.active;
  }

  /** Stops a glide where it is: the one entry point every cancel reason calls (BQ-103). */
  stop(): void {
    this.momentum.cancel();
  }

  /** `setMotion`: a change to reduce stops a glide where it is (E11-D06 D21). */
  setMotion(reduce: boolean): void {
    this.reduce = reduce;
    if (reduce) this.stop();
  }

  apply(touch: boolean, ev: Float32Array): void {
    for (let i = 0; i < ev.length; i += INPUT_STRIDE) {
      const type = ev[i] as number;
      const x = ev[i + 1] as number;
      const y = ev[i + 2] as number;
      const b = ev[i + 3] as number;
      const dt = ev[i + 5] as number;
      if (type === INPUT.move) this.move(touch, x, y, b, dt);
      else if (type === INPUT.down) this.down(touch, x, y, b);
      else if (type === INPUT.up || type === INPUT.cancel) {
        this.up(touch, b, type === INPUT.up ? dt : Number.NaN);
      } else if (type === INPUT.wheel) this.wheel(x, y, b, ev[i + 4] as number);
      else if (type === INPUT.dblclick) this.dblclick(x, y);
      else if (type === INPUT.key) this.key(x, ev[i + 4] as number, y);
    }
  }

  /**
   * E11-S09 (BQ-10): the index of the pane whose rows hold `y` (its plot or its gutter): the last
   * pane below the stack, the first above it or when the layout has none.
   */
  paneAt(y: number): number {
    const panes = this.size.panes;
    if (panes === undefined || panes.length === 0) return 0;
    for (let i = 0; i < panes.length; i += 1) {
      const r = (panes[i] as (typeof panes)[number]).rect;
      if (y < r[1] + r[3]) return i;
    }
    return panes.length - 1;
  }

  /**
   * E11-S09 (BQ-19): the boundary whose 24 px band holds `y` (below pane i), nearest first; -1
   * outside every band or with one pane.
   */
  boundaryAt(y: number): number {
    const panes = this.size.panes;
    let best = -1;
    let gap = Number.POSITIVE_INFINITY;
    for (let i = 0; panes !== undefined && i < panes.length - 1; i += 1) {
      const r = (panes[i] as (typeof panes)[number]).rect;
      const d = y - (r[1] + r[3]); // the band is [boundary - 12, boundary + 12)
      if (d >= -BAND_HALF_PX && d < BAND_HALF_PX && Math.abs(d) < gap) {
        gap = Math.abs(d);
        best = i;
      }
    }
    return best;
  }

  private region(x: number, y: number): number {
    return regionAt(x, y, this.size.width, this.size.height, this.size.priceGutter);
  }

  private down(touch: boolean, x: number, y: number, id: number): void {
    const slot = Number.isNaN(this.ids[0] as number) ? 0 : 1;
    if (touch && !Number.isNaN(this.ids[slot] as number)) return; // a third finger is ignored
    this.stop(); // the glide stops on this frame; the drag starts from where it is
    this.velocity.reset();
    if (touch) {
      this.ids[slot] = id;
      this.xs[slot] = x;
      if (!Number.isNaN(this.ids[1 - slot] as number)) {
        this.pinched = true; // two fingers: pinch, and no coast until all are up
        return;
      }
    }
    const r = this.region(x, y);
    this.drag =
      r === REGION.plot
        ? Drag.pan
        : r === REGION.time
          ? Drag.spacing
          : r === REGION.price
            ? Drag.price
            : Drag.none;
    this.dragX = x;
    this.dragY = y;
    this.anchorY = y;
    this.dragPane = this.paneAt(y);
    // The band captures only the pointer-down that starts a drag (E11-D02 §8): a pan or a
    // price drag that starts inside it is a resize.
    // Mouse and pen only: a touch in the band pans, and two fingers pinch.
    const at = !touch && (r === REGION.plot || r === REGION.price) ? this.boundaryAt(y) : -1;
    if (at >= 0 && this.sink.split !== undefined) {
      this.drag = Drag.none; // no pan, no coast: the moves go to `splitTo` (a cached flag)
      this.splitAt = at;
    }
  }

  private move(touch: boolean, x: number, y: number, b: number, dt: number): void {
    const r = this.region(x, y);
    if (r === REGION.plot) this.pointerX = x;
    if (r === REGION.plot || r === REGION.price) this.focusPane = this.paneAt(y);
    if (touch) {
      const slot = this.ids[0] === b ? 0 : this.ids[1] === b ? 1 : -1;
      if (slot >= 0 && !Number.isNaN(this.ids[1 - slot] as number)) this.pinch(slot, x);
      else if (slot >= 0) this.dragTo(x, y, dt);
    } else if ((b & 1) === 1) {
      if (this.splitAt < 0) this.dragTo(x, y, dt);
      else this.splitTo(y); // a splitter drag: kept out of dragTo, so a pan pays nothing for it
    }
    this.sink.hover(x, y);
  }

  /** No easing (E11-D06 D17): the boundary follows the pointer; the layout reflows once a frame. */
  private splitTo(y: number): void {
    const dy = y - this.dragY;
    this.dragY = y;
    if (dy !== 0 && this.sink.split?.(this.splitAt, dy) === false) this.splitAt = -1;
  }

  private dragTo(x: number, y: number, dt: number): void {
    const dx = x - this.dragX;
    const dy = y - this.dragY;
    this.dragX = x;
    this.dragY = y;
    const vp = this.vp;
    if (this.drag === Drag.pan) {
      this.sink.moved(vp.pan(dx));
      this.sink.moved(vp.panPrice(this.dragPane, dy)); // inert while autoscale is on (D01 D2)
      this.velocity.sample(dx, dt);
    } else if (this.drag === Drag.spacing) {
      this.sink.moved(vp.zoomAt(vp.plotWidth, axisDragFactor(dx)));
    } else if (this.drag === Drag.price && dy !== 0) {
      this.sink.moved(vp.zoomPrice(this.dragPane, this.anchorY, priceDragFactor(dy))); // locks
    }
  }

  /** Slot `slot` moved to `x`: pan by the midpoint's move, zoom by the spread about it. */
  private pinch(slot: number, x: number): void {
    const o = 1 - slot;
    const ox = this.xs[o] as number;
    const before = this.xs[slot] as number;
    this.xs[slot] = x;
    const d0 = Math.abs(before - ox);
    const d1 = Math.abs(x - ox);
    const mid = (x + ox) / 2;
    const vp = this.vp;
    this.sink.moved(vp.pan(mid - (before + ox) / 2));
    if (d0 >= 1 && d1 >= 1) this.sink.moved(vp.zoomAt(mid, d1 / d0));
  }

  /** `dt` is NaN for a cancel (pointercancel, lost capture): it ends the drag with no coast. */
  private up(touch: boolean, id: number, dt: number): void {
    if (touch) {
      const slot = this.ids[0] === id ? 0 : this.ids[1] === id ? 1 : -1;
      if (slot < 0) return;
      this.ids[slot] = Number.NaN;
      const left = this.ids[1 - slot] as number;
      if (!Number.isNaN(left)) {
        this.dragX = this.xs[1 - slot] as number; // the finger left keeps panning from here
        return;
      }
    }
    const coast = this.drag === Drag.pan && !this.pinched && !this.reduce && !Number.isNaN(dt);
    this.drag = Drag.none;
    this.splitAt = -1;
    this.pinched = false;
    if (!coast) return;
    const m = this.momentum;
    if (m.start(this.velocity.release(dt), this.vp.plotWidth) && !m.registered) {
      m.registered = true;
      this.sink.animate(m);
    }
  }

  private wheel(x: number, y: number, px: number, mods: number): void {
    this.stop();
    const r = this.region(x, y);
    const vp = this.vp;
    if ((mods & MOD.pan) !== 0) this.sink.moved(vp.pan(-px));
    else if (r === REGION.price)
      this.sink.moved(vp.zoomPrice(this.paneAt(y), y, wheelFactor(px))); // locks
    else this.sink.moved(vp.zoomAt(r === REGION.time ? vp.plotWidth : x, wheelFactor(px)));
  }

  private dblclick(x: number, y: number): void {
    this.stop();
    const vp = this.vp;
    const r = this.region(x, y);
    if (r === REGION.plot)
      this.sink.moved(resetView(vp)); // as `Ctrl+Home` (BQ-107), autoscale included (BQ-119)
    else if (r === REGION.time) {
      this.sink.moved(vp.zoomAt(vp.plotWidth, DEFAULT_BAR_SPACING / vp.barSpacing));
    } else this.sink.moved(vp.setScale(this.paneAt(y), { auto: true })); // the gutter: auto
  }

  /**
   * A key that moves the viewport stops a glide first (BQ-103, E11-D06 D5); Space only sets the
   * pan-drag modifier, so releasing it after a Space+drag leaves that drag's coast running.
   */
  private key(code: number, mods: number, target: number): void {
    if (code === KEY.spaceDown || code === KEY.spaceUp) {
      this.panModifier = code === KEY.spaceDown;
      return;
    }
    this.stop();
    if (target === TARGET.plot) {
      this.sink.moved(navigate(this.vp, code, mods, this.pointerX));
      return;
    }
    // E11-S06 (BQ-194): an axis stop's key, and what it announces.
    const say =
      target === TARGET.price
        ? priceAxisKey(this.vp, this.focusPane, code, mods)
        : timeAxisKey(this.vp, code, mods);
    this.sink.moved(say !== 0);
    if (say !== 0) this.sink.say?.(say);
  }
}
