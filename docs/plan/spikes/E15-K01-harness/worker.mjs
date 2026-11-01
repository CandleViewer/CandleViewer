// THROWAWAY SPIKE HARNESS (E15-K01 #371). The render worker: owns every pane's OffscreenCanvas and context
// (the shipped run mode, 26 §6; BQ-05), and the worker leg of the sync fan-out (BQ-12).
import { Pane, makeData, makeDrawings, runLoop } from "./scene.mjs";
import { mulberry32 } from "./lib.mjs";
import { fanOut, makeSubscribers } from "./sync.mjs";

const raf = self.requestAnimationFrame
  ? (f) => self.requestAnimationFrame(f)
  : (f) => setTimeout(f, 0);
let subs = null;
const fan = [];
self.onmessage = ({ data: m }) => {
  if (m.cmd === "run") {
    const t0 = performance.now();
    const data = makeData();
    const t1 = performance.now();
    const drawings = makeDrawings(data, mulberry32(m.seed));
    const setupMs = [];
    const shared = m.rects
      ? m.canvases[0].getContext("webgl2", {
          antialias: false,
          powerPreference: "high-performance",
        })
      : null;
    const targets = m.rects ? m.rects.map((rect) => ({ gl: shared, rect })) : m.canvases;
    const panes = targets.map((cv, k) => {
      const s = performance.now();
      const p = new Pane(cv, m.density, data, drawings, k);
      setupMs.push(performance.now() - s);
      return p;
    });
    // with one shared context, one readPixels per frame waits for every pane: finish only the first
    const finishing = shared ? panes.slice(0, 1) : panes.slice(-1);
    runLoop(
      panes,
      finishing,
      { warmMs: m.warmMs, windowMs: m.windowMs, raf, now: () => performance.now() },
      (r) =>
        self.postMessage({
          ...r,
          dataMs: t1 - t0,
          setupMs,
          hasRaf: Boolean(self.requestAnimationFrame),
        }),
    );
  } else if (m.cmd === "contexts") {
    const gls = Array.from({ length: m.k }, () => new OffscreenCanvas(64, 64).getContext("webgl2"));
    setTimeout(
      () =>
        self.postMessage({
          created: m.k,
          lost: gls.map((g, i) => (g.isContextLost() ? i : -1)).filter((i) => i >= 0),
        }),
      500,
    );
  } else if (m.cmd === "sync-setup") {
    subs = makeSubscribers(m.n);
    fan.length = 0;
    self.postMessage({ ok: true });
  } else if (m.cmd === "sync") {
    const s = performance.now();
    fanOut(subs, m.msg);
    fan.push(performance.now() - s);
  } else if (m.cmd === "sync-batch") {
    const s = performance.now();
    for (const b of m.batch) subs[b.k].state = b; // apply the precomputed per-pane result
    fan.push(performance.now() - s);
  } else if (m.cmd === "sync-done") {
    self.postMessage({ fan: fan.slice() });
  }
};
