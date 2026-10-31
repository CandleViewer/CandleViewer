// The backing-store growth policy (E11-S10 PR 2, README BQ-149, C-44): DOM-free, so the host runs
// it and the `resize-drag` bench scene drives the same code. Each axis grows in whole 128-device-px
// steps from the current store, only when the exact size passes it, and never shrinks while
// resizes keep coming: a splitter drag reallocates once per step at most. After 10 resize-free
// frames (counted on the frame callback, never wall time), on a DPR change and before an export,
// the store is trimmed to the exact size. A 0 size (BQ-147) keeps the store as it is. The first
// size after an unsized mount (a 0 × 0 or hidden container's 1 px canvas) or after a suspension is
// not a drag: it grows to the exact size, never a step past it.

/** The growth step per axis, in device px. */
export const BACKING_STEP_PX = 128;
/** Resize-free frames before a padded store is trimmed to the exact size. */
export const SETTLE_FRAMES = 10;

/** One axis: the current store when `exact` fits in it, else grown by whole steps past `exact`. */
export const grownPx = (exact: number, current: number, step = BACKING_STEP_PX): number =>
  exact <= current ? current : current + Math.ceil((exact - current) / step) * step;

export class BackingSizer {
  /** The exact size the chart draws in (device px), 0 on an axis while suspended. */
  exactWidth: number;
  exactHeight: number;
  /** Resize-free frames counted while padded; -1 when there is nothing to trim. */
  private quiet = -1;
  /** True on an unsized mount and after a 0 size: the next size grows to exact, unpadded. */
  private fresh: boolean;

  constructor(
    /** The backing store (device px), never smaller than the exact size. */
    public width: number,
    public height: number,
    private dpr: number,
  ) {
    this.exactWidth = width;
    this.exactHeight = height;
    this.fresh = width <= 1 || height <= 1;
  }

  /** True while the store is larger than the exact size on either axis. */
  get padded(): boolean {
    const shown = this.exactWidth > 0 && this.exactHeight > 0;
    return shown && (this.width !== this.exactWidth || this.height !== this.exactHeight);
  }

  /** True while resize-free frames are being counted towards a trim. */
  get settling(): boolean {
    return this.quiet >= 0;
  }

  /** A resize to the exact device size: grow past a step, keep a larger store, trim on a DPR change. */
  resize(exactWidth: number, exactHeight: number, dpr: number): void {
    this.exactWidth = exactWidth;
    this.exactHeight = exactHeight;
    if (exactWidth > 0 && exactHeight > 0) {
      const trim = dpr !== this.dpr;
      const grow = (e: number, c: number): number => (this.fresh ? Math.max(e, c) : grownPx(e, c));
      this.width = trim ? exactWidth : grow(exactWidth, this.width);
      this.height = trim ? exactHeight : grow(exactHeight, this.height);
      this.dpr = dpr;
    }
    this.fresh = exactWidth === 0 || exactHeight === 0;
    this.quiet = this.padded ? 0 : -1;
  }

  /** One frame without a resize: true when it is the `SETTLE_FRAMES`th and the store was trimmed. */
  frame(): boolean {
    if (this.quiet < 0) return false;
    this.quiet += 1;
    return this.quiet >= SETTLE_FRAMES && this.trim();
  }

  /** Trims the store to the exact size (settle, export); true when it changed. */
  trim(): boolean {
    this.quiet = -1;
    if (!this.padded) return false;
    this.width = this.exactWidth;
    this.height = this.exactHeight;
    return true;
  }
}
