// Test doubles for the worker boundary (E11-T02): a dedicated worker that runs the REAL worker
// entry (`startWorker`) on an asynchronous bus with transfer semantics, and a host env on fake
// timers. `move` is a real transfer (structuredClone with a transfer list), so a sender's buffer
// is detached exactly as `postMessage` detaches it.
import { startWorker } from "../../src/worker/render-worker.js";
import type { HostEnv, WorkerLike } from "../../src/worker/host.js";
import type { FromWorker } from "../../src/worker/protocol.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";

const move = (b: ArrayBuffer): ArrayBuffer => structuredClone(b, { transfer: [b] });

/** Top-level fields of `msg` re-pointed at moved buffers (the transfer list's semantics). */
function transfer(msg: unknown, list: readonly unknown[]): unknown {
  if (typeof msg !== "object" || msg === null || list.length === 0) return msg;
  const out: Record<string, unknown> = { ...(msg as Record<string, unknown>) };
  for (const [k, v] of Object.entries(out)) {
    if (v instanceof ArrayBuffer && list.includes(v)) out[k] = move(v);
    else if (v instanceof Float32Array && list.includes(v.buffer))
      out[k] = new Float32Array(move(v.buffer as ArrayBuffer));
  }
  return out;
}

export class FakeWorker implements WorkerLike {
  static created: FakeWorker[] = [];
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  onmessageerror: ((ev: unknown) => void) | null = null;
  terminated = false;
  /** Every message the worker side received, after transfer. */
  readonly inbox: unknown[] = [];
  private readonly scope: {
    onmessage: ((ev: { data: unknown }) => void) | null;
    postMessage(msg: FromWorker): void;
    OffscreenCanvas: new () => { getContext(id: string): unknown };
  };

  constructor(webgl2 = true) {
    FakeWorker.created.push(this);
    this.scope = {
      onmessage: null,
      postMessage: (msg) => {
        setTimeout(() => {
          if (!this.terminated) this.onmessage?.({ data: msg });
        }, 0);
      },
      OffscreenCanvas: class {
        getContext(): unknown {
          return webgl2 ? new FakeGl({ params: ROOMY }) : null;
        }
      },
    };
    startWorker(this.scope);
  }

  postMessage(msg: unknown, list: Transferable[]): void {
    const moved = transfer(msg, list);
    setTimeout(() => {
      if (this.terminated) return;
      this.inbox.push(moved);
      this.scope.onmessage?.({ data: moved });
    }, 0);
  }

  terminate(): void {
    this.terminated = true;
  }

  /** The worker dies externally: the host sees an `error` event. */
  kill(): void {
    this.terminated = true;
    this.onerror?.({ type: "error" });
  }
}

let ids = 0;

/** A host env on vitest fake timers; `createWorker` can be swapped to inject failures. */
export function fakeEnv(over: Partial<HostEnv> = {}): HostEnv {
  return {
    createWorker: () => new FakeWorker(),
    requestFrame: (cb) => {
      setTimeout(cb, 16);
    },
    setTimer: (cb, ms) => {
      setTimeout(cb, ms);
    },
    // Fake timers fake Date, so this clock advances with vi.advanceTimersByTime.
    now: () => Date.now(),
    probe: () => FULL,
    correlationId: () => {
      ids += 1;
      return `cv-test-${ids}`;
    },
    ...over,
  };
}
