// `viewport-transform` scene (E11-S03, BQ-80): 3 panes over 100 000 bars, each step a pan frame
// through the shared transform: the per-pane uniform blocks plus the projections a frame's hit-test
// and axis make. 06 §4.3's data-window stage holds it; the .perf.test.ts times ≤ 0.05 ms per pane.
import { BarStore } from "../../src/model/BarStore.js";
import {
  ChartViewport,
  createPaneUniforms,
  type PaneUniforms,
  priceToScreen,
  screenToIndex,
  screenToPrice,
  screenToTime,
  writePaneUniforms,
} from "../../src/viewport/index.js";
import { bars } from "./pan-zero-upload.js";

export const PANES = 3;

export class ViewportTransformBench {
  readonly viewport: ChartViewport;
  /** One block per pane, allocated once: a frame rewrites them in place. */
  readonly blocks = Array.from({ length: PANES }, createPaneUniforms);
  checksum = 0;

  constructor(n = 100_000) {
    const store = new BarStore();
    store.append(bars(n));
    this.viewport = new ChartViewport(store, PANES);
    this.viewport.setSize(1920, 1080, 2);
    for (let p = 0; p < PANES; p += 1) {
      this.viewport.setPanePlot(p, p * 360, 360);
      this.viewport.setPriceRange(p, 900, 1100);
    }
    this.viewport.pan(-(n / 2) * this.viewport.barSpacing);
  }

  /** One pan frame: move, then per pane the uniform block and a cursor's projections. */
  step(dxPx = -3, cursorX = 960): void {
    const vp = this.viewport;
    vp.pan(dxPx);
    let sum = screenToIndex(vp, cursorX) + screenToTime(vp, cursorX) * 1e-12;
    for (let p = 0; p < PANES; p += 1) {
      writePaneUniforms(vp, p, this.blocks[p] as PaneUniforms);
      sum += priceToScreen(vp, p, 1000) + screenToPrice(vp, p, p * 360 + 180);
    }
    this.checksum = sum;
  }
}
