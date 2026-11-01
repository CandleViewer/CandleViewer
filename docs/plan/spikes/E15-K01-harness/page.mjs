// THROWAWAY SPIKE HARNESS (E15-K01 #371). The page: lays out N panes in a grid over a fixed 1600x900 plot
// area (dpr 1), then runs them in the render worker (headline) or inline on the main thread; plus the
// context-count probe and the sync fan-out bench (main thread against worker). Driven by run.mjs.
import { Pane, makeData, makeDrawings, runLoop } from "./scene.mjs";
import { mulberry32 } from "./lib.mjs";
import { fanOut, makeSubscribers, syncMessage } from "./sync.mjs";

const grid = document.getElementById("grid");
const COLS = (n) => Math.ceil(Math.sqrt(n));
/** Pane regions of the shared canvas, in GL coordinates (origin bottom-left). */
function rects(n) {
  const cols = COLS(n),
    rows = Math.ceil(n / cols),
    w = Math.floor(1600 / cols),
    h = Math.floor(900 / rows);
  return Array.from({ length: n }, (_, k) => ({
    x: (k % cols) * w,
    y: 900 - (Math.floor(k / cols) + 1) * h,
    w,
    h,
  }));
}
function layout(n) {
  const cols = COLS(n),
    rows = Math.ceil(n / cols);
  grid.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
  grid.style.gridTemplateRows = `repeat(${rows}, 1fr)`;
  return Array.from({ length: n }, () => {
    const cv = document.createElement("canvas");
    cv.width = Math.floor(1600 / cols);
    cv.height = Math.floor(900 / rows);
    grid.append(cv);
    return cv;
  });
}
const glInfo = () => {
  const gl = new OffscreenCanvas(1, 1).getContext("webgl2"); // harness record only (never a probe input)
  const d = gl?.getExtension("WEBGL_debug_renderer_info");
  const r = gl
    ? {
        renderer: gl.getParameter(d ? d.UNMASKED_RENDERER_WEBGL : gl.RENDERER),
        version: gl.getParameter(gl.VERSION),
      }
    : null;
  gl?.getExtension("WEBGL_lose_context")?.loseContext();
  return r;
};

window.__h = {
  glInfo,
  run: ({ mode, density, n, warmMs, windowMs, seed }) =>
    new Promise((resolve, reject) => {
      const canvases = layout(mode === "worker-shared" ? 1 : n);
      if (mode === "worker-shared") {
        canvases[0].width = 1600;
        canvases[0].height = 900;
        grid.style.gridTemplateColumns = grid.style.gridTemplateRows = "1fr";
      }
      if (mode !== "inline") {
        const w = new Worker("./worker.mjs", { type: "module" });
        w.onerror = (e) => reject(new Error(e.message));
        w.onmessage = ({ data }) => (w.terminate(), resolve(data));
        const off = canvases.map((c) => c.transferControlToOffscreen());
        const r = mode === "worker-shared" ? rects(n) : null;
        w.postMessage(
          { cmd: "run", canvases: off, rects: r, density, warmMs, windowMs, seed },
          off,
        );
        return;
      }
      const t0 = performance.now();
      const data = makeData();
      const dataMs = performance.now() - t0;
      const drawings = makeDrawings(data, mulberry32(seed));
      const setupMs = [];
      const panes = canvases.map((cv, k) => {
        const s = performance.now();
        const p = new Pane(cv, density, data, drawings, k);
        setupMs.push(performance.now() - s);
        return p;
      });
      const raf = (f) => requestAnimationFrame(f);
      runLoop(
        panes,
        panes.slice(-1),
        { warmMs, windowMs, raf, now: () => performance.now() },
        (r) => resolve({ ...r, dataMs, setupMs, hasRaf: true }),
      );
    }),
  // creates k webgl2 contexts on the main thread one by one and reports which were lost (BQ-05)
  contexts: async (k) => {
    const cvs = [];
    const lostAt = [];
    for (let i = 0; i < k; i += 1) {
      const cv = document.createElement("canvas");
      cv.addEventListener("webglcontextlost", () =>
        lostAt.push({ index: i, whenCreated: cvs.length }),
      );
      cv.getContext("webgl2");
      cvs.push(cv);
      await new Promise((r) => requestAnimationFrame(r));
    }
    await new Promise((r) => setTimeout(r, 500));
    return { created: k, lost: lostAt };
  },
  workerContexts: (k) =>
    new Promise((resolve) => {
      const w = new Worker("./worker.mjs", { type: "module" });
      w.onmessage = ({ data }) => (w.terminate(), resolve(data));
      w.postMessage({ cmd: "contexts", k });
    }),
  // the sync fan-out at n panes: "main" fans out on the main thread then posts one batch to the render
  // worker; "worker" posts the one message and the worker fans out. Main-thread ms per frame, rAF paced.
  sync: (n, frames, where) =>
    new Promise((resolve) => {
      const w = new Worker("./worker.mjs", { type: "module" });
      const subs = makeSubscribers(n);
      const main = [];
      let i = 0;
      const step = () => {
        const msg = syncMessage(i);
        const s = performance.now();
        if (where === "main") w.postMessage({ cmd: "sync-batch", batch: fanOut(subs, msg) });
        else w.postMessage({ cmd: "sync", msg });
        main.push(performance.now() - s);
        i += 1;
        if (i < frames) requestAnimationFrame(step);
        else {
          w.onmessage = ({ data }) => (w.terminate(), resolve({ main, worker: data.fan }));
          w.postMessage({ cmd: "sync-done" });
        }
      };
      w.onmessage = () => requestAnimationFrame(step);
      w.postMessage({ cmd: "sync-setup", n });
    }),
};
window.ready = true;
