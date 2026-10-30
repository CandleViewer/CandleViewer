// The render-worker entry (E11-T02, 26 §6): a dedicated module worker shared by every chart on the
// page, bundled same-origin (no `blob:` URL), so the Electron CSP keeps `worker-src 'self'`.
// It only wires the runtime to the worker scope; the runtime is the same module `RunMode.inline`
// runs on the main thread. No DOM, no network (C-2.16).
import { probeCanvas, selectProfile } from "../gl/capability.js";
import { createRenderRuntime } from "./runtime.js";
import type { CapabilityReport, FromWorker } from "./protocol.js";

/** The dedicated-worker scope members used here (typed structurally: no WebWorker lib). */
interface WorkerScope {
  onmessage: ((ev: { data: unknown }) => void) | null;
  postMessage(msg: FromWorker): void;
  requestAnimationFrame?: (cb: () => void) => number;
  OffscreenCanvas?: new (w: number, h: number) => { getContext(id: string): unknown };
}

/**
 * The capability probe on a throwaway OffscreenCanvas (E11-S02 owns detection and the profile
 * rule, README BQ-50 and BQ-57; E11-T05 owns the 2D drawing `degraded-2d` hands over to).
 */
export function probeWorker(scope: WorkerScope): CapabilityReport {
  try {
    const Ctor = scope.OffscreenCanvas;
    return Ctor === undefined ? selectProfile(null) : probeCanvas(new Ctor(1, 1));
  } catch {
    return selectProfile(null);
  }
}

/** Starts the runtime on `scope`; the module runs it on its own global when loaded as a worker. */
export function startWorker(scope: WorkerScope): void {
  const runtime = createRenderRuntime({
    runMode: "worker",
    post: (msg) => scope.postMessage(msg),
    requestFrame: (cb) => {
      if (typeof scope.requestAnimationFrame === "function") scope.requestAnimationFrame(cb);
      else setTimeout(cb, 16);
    },
    now: () => performance.now(),
    probe: () => probeWorker(scope),
  });
  scope.onmessage = (ev) => runtime.handle(ev.data);
}

const scope = globalThis as unknown as WorkerScope & { importScripts?: unknown };
// A dedicated worker has `importScripts`; a page or a test importing this module does not.
if (typeof scope.importScripts === "function") startWorker(scope);
