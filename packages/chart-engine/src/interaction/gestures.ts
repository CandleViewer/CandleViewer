// The worker half of the InputRouter (E11-S04 PR 1, 26 §3.11, README BQ-99 to BQ-103): packed
// rows become viewport changes, routed by the layout's rects. The plot pans time on a drag and
// zooms time at the cursor on a wheel (Ctrl+wheel, a trackpad pinch, too: BQ-100); the time axis
// changes `barSpacing` about the plot's right edge; the price axis and a vertical plot drag are
// no-ops until E11-S05 (G-5). Two touches pinch about their midpoint. Only a one-pointer plot drag
// coasts. Keys go through the navigator (PR 2, BQ-106 to BQ-109); a reduced-motion release
// never coasts (BQ-104). DOM-free and allocation-free per row.
import { DEFAULT_BAR_SPACING, type ChartViewport } from "../viewport/Viewport.js";
import { INPUT, INPUT_STRIDE, KEY } from "../worker/protocol.js";
import { Momentum } from "./momentum.js";
import { navigate, resetView } from "./navigator.js";
import { VelocityEstimator } from "./velocity.js";
import { axisDragFactor, MOD, REGION, regionAt, wheelFactor } from "./wheel.js";

export interface GestureSink {
  /** A viewport setter ran; `changed` is its result. */
  moved(changed: boolean): void;
  /** The pointer is over plot x (the crosshair summary, as shipped: G-6). */
  hover(x: number): void;
  /** Registers the glide with the chart's frame scheduler. */
  animate(m: Momentum): void;
}

const Drag = { none: 0, pan: 1, spacing: 2 } as const;

export class Gestures {
  readonly velocity = new VelocityEstimator();
  readonly momentum: Momentum;
  /** The app's resolved motion mode (`init` / `setMotion`): a reduce release never coasts. */
  reduce = false;
  /** Space is held (BQ-109): the pan-drag modifier E14's tools read; cleared on blur. */
  panModifier = false;
  /** The pointer's last x inside the plot (NaN until it enters): the `+/-` anchor (BQ-108). */
  pointerX = Number.NaN;
  private drag: number = Drag.none;
  private dragX = 0;
  private pinched = false;
  /** Two touch slots: pointer ids (NaN when free) and their last x. */
  private readonly ids = new Float64Array([Number.NaN, Number.NaN]);
  private readonly xs = new Float64Array(2);

  constructor(
    private readonly vp: ChartViewport,
    /** The canvas size in CSS px, for the regions (the layout engine's own fields). */
    private readonly size: { readonly width: number; readonly height: number },
    private readonly sink: GestureSink,
  ) {
    this.momentum = new Momentum((dx) => {
      const changed = vp.pan(dx);
      sink.moved(changed);
      return changed;
    });
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
      else if (type === INPUT.key) this.key(x, ev[i + 4] as number);
    }
  }

  private region(x: number, y: number): number {
    return regionAt(x, y, this.size.width, this.size.height);
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
    this.drag = r === REGION.plot ? Drag.pan : r === REGION.time ? Drag.spacing : Drag.none;
    this.dragX = x;
  }

  private move(touch: boolean, x: number, y: number, b: number, dt: number): void {
    if (this.region(x, y) === REGION.plot) this.pointerX = x;
    if (touch) {
      const slot = this.ids[0] === b ? 0 : this.ids[1] === b ? 1 : -1;
      if (slot >= 0 && !Number.isNaN(this.ids[1 - slot] as number)) this.pinch(slot, x);
      else if (slot >= 0) this.dragTo(x, dt);
    } else if ((b & 1) === 1) this.dragTo(x, dt);
    this.sink.hover(x);
  }

  private dragTo(x: number, dt: number): void {
    const dx = x - this.dragX;
    this.dragX = x;
    const vp = this.vp;
    if (this.drag === Drag.pan) {
      this.sink.moved(vp.pan(dx)); // time only: a vertical drag is inert (G-5)
      this.velocity.sample(dx, dt);
    } else if (this.drag === Drag.spacing) {
      this.sink.moved(vp.zoomAt(vp.plotWidth, axisDragFactor(dx)));
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
    if (r === REGION.price) return; // price zoom is E11-S05's (G-5); the host prevented default
    const vp = this.vp;
    if ((mods & MOD.pan) !== 0) this.sink.moved(vp.pan(-px));
    else this.sink.moved(vp.zoomAt(r === REGION.time ? vp.plotWidth : x, wheelFactor(px)));
  }

  private dblclick(x: number, y: number): void {
    this.stop();
    const vp = this.vp;
    const r = this.region(x, y); // the price axis's reset is E11-S05's (G-5)
    if (r === REGION.plot)
      this.sink.moved(resetView(vp)); // as `Ctrl+Home` (BQ-107)
    else if (r === REGION.time) {
      this.sink.moved(vp.zoomAt(vp.plotWidth, DEFAULT_BAR_SPACING / vp.barSpacing));
    }
  }

  /**
   * A key that moves the viewport stops a glide first (BQ-103, E11-D06 D5); Space only sets the
   * pan-drag modifier, so releasing it after a Space+drag leaves that drag's coast running.
   */
  private key(code: number, mods: number): void {
    if (code === KEY.spaceDown || code === KEY.spaceUp) {
      this.panModifier = code === KEY.spaceDown;
      return;
    }
    this.stop();
    this.sink.moved(navigate(this.vp, code, mods, this.pointerX));
  }
}
