/**
 * The GL-churn guard (E15-T02): counts WebGL context creations, `transferControlToOffscreen` calls,
 * `webglcontextlost` events and panel mounts / unmounts across an operation sequence, so "a layout
 * change never remounts the WebGL context" (SCR-020) regresses loudly in the unit suite. In a dev
 * build the active guard's counters are on `window.__cvGlChurn`, so Storybook and the console see
 * a regression too.
 */

export interface GlChurnCounters {
  contextsCreated: number;
  offscreenTransfers: number;
  contextsLost: number;
  panelMounts: number;
  panelUnmounts: number;
}

export interface GlChurnGuard {
  readonly counters: Readonly<GlChurnCounters>;
  /** Zeroes the counters: call it after the initial mount, before the sequence under test. */
  reset(): void;
  uninstall(): void;
}

let active: GlChurnCounters | null = null;

/** Called by every docked panel host as it mounts and unmounts. */
export function notePanelMount(delta: 1 | -1): void {
  if (active === null) return;
  if (delta === 1) active.panelMounts += 1;
  else active.panelUnmounts += 1;
}

const zero = (): GlChurnCounters => ({
  contextsCreated: 0,
  offscreenTransfers: 0,
  contextsLost: 0,
  panelMounts: 0,
  panelUnmounts: 0,
});

/** Wraps the canvas entry points of `win` until `uninstall`. One guard at a time. */
export function installGlChurnGuard(win: Window & typeof globalThis = window): GlChurnGuard {
  const counters = zero();
  const proto = win.HTMLCanvasElement.prototype;
  const getContext = proto.getContext;
  const transfer = proto.transferControlToOffscreen as (() => OffscreenCanvas) | undefined;
  // One wrapper for every overload: the arguments go through unchanged.
  const wrappedGetContext = function (this: HTMLCanvasElement, ...args: unknown[]): unknown {
    if (typeof args[0] === "string" && args[0].startsWith("webgl")) counters.contextsCreated += 1;
    return (getContext as (...a: unknown[]) => unknown).apply(this, args);
  };
  proto.getContext = wrappedGetContext as typeof proto.getContext;
  proto.transferControlToOffscreen = function (this: HTMLCanvasElement): OffscreenCanvas {
    counters.offscreenTransfers += 1;
    if (transfer === undefined) throw new win.DOMException("not supported", "NotSupportedError");
    return transfer.call(this);
  };
  const onLost = (): void => {
    counters.contextsLost += 1;
  };
  win.document.addEventListener("webglcontextlost", onLost, true);
  active = counters;
  if (import.meta.env?.DEV === true) Reflect.set(win, "__cvGlChurn", counters);
  return {
    counters,
    reset: () => void Object.assign(counters, zero()),
    uninstall: () => {
      proto.getContext = getContext;
      if (transfer === undefined) Reflect.deleteProperty(proto, "transferControlToOffscreen");
      else proto.transferControlToOffscreen = transfer;
      win.document.removeEventListener("webglcontextlost", onLost, true);
      if (active === counters) active = null;
      Reflect.deleteProperty(win, "__cvGlChurn");
    },
  };
}
