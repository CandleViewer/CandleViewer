// `scale-mode-switch` scene (E11-S05, BQ-126): 3 panes over 100 000 bars, each step switching every
// pane's scale mode (linear, log, percent, indexed, inverted) and rewriting its uniform block. A
// mode change is a projection change only: no buffer is touched. The .perf.test.ts times
// ≤ 0.05 ms of uniforms per pane per switch (BQ-80's bound); the counted test checks the blocks.
import { BarStore } from "../../src/model/BarStore.js";
import {
  ChartViewport,
  createPaneUniforms,
  type PaneTransform,
  type PaneUniforms,
  priceToScreen,
  SCALE_MODES,
  writePaneUniforms,
} from "../../src/viewport/index.js";
import { bars } from "./pan-zero-upload.js";

export const PANES = 3;

export class ScaleModeSwitchBench {
  readonly viewport: ChartViewport;
  readonly blocks = Array.from({ length: PANES }, createPaneUniforms);
  checksum = 0;
  private turn = 0;

  constructor(n = 100_000) {
    const store = new BarStore();
    store.append(bars(n));
    this.viewport = new ChartViewport(store, PANES);
    this.viewport.setSize(1920, 1080, 2);
    for (let p = 0; p < PANES; p += 1) {
      this.viewport.setPanePlot(p, p * 360, 360);
      this.viewport.setPriceInfo(p, 0, 0.5);
      (this.viewport.panes[p] as PaneTransform).logReason = null;
      this.viewport.setPriceRange(p, 100_000, 200_000);
    }
  }

  /** One switch: every pane to the next mode (and invert on alternate turns), then uniforms. */
  step(): void {
    const vp = this.viewport;
    this.turn += 1;
    const mode = SCALE_MODES[this.turn % SCALE_MODES.length] ?? "linear";
    let sum = 0;
    for (let p = 0; p < PANES; p += 1) {
      const pane = vp.panes[p] as PaneTransform;
      pane.scaleMode = mode; // the setter's effect without its command-path bookkeeping
      pane.inverted = (this.turn & 4) !== 0;
      writePaneUniforms(vp, p, this.blocks[p] as PaneUniforms);
      sum += priceToScreen(vp, p, 150_000);
    }
    this.checksum = sum;
  }
}
