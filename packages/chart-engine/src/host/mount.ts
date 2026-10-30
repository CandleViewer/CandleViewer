// Host adapter (C-2.16): the only engine code that touches the DOM. It reaches the document
// through `container.ownerDocument` and never through a global, so it works inside any realm
// (iframe, Electron view) and stays inside the `no-restricted-globals` rule. src/core and
// src/layers never import this module (.dependency-cruiser.js `chart-engine-core-no-dom-host`).

import { probeCanvas, type CapabilityReport } from "../gl/capability.js";

export interface HostSurface {
  /**
   * The canvas the renderer draws into: transferred to the render worker in `RunMode.worker`,
   * drawn on directly inline (E11-T02). The stub renderer uses a 2D context, so the GL backend
   * (E11-S02) replaces this canvas rather than reusing it.
   */
  readonly canvas: HTMLCanvasElement;
  readonly mirrorRoot: HTMLElement;
  /**
   * Swaps in a fresh canvas, sized to the container as it is now, in the same place and returns
   * it: a canvas whose control went to a worker that died cannot be transferred again (E11-T02
   * crash recovery).
   */
  replaceCanvas(): HTMLCanvasElement;
  /** Removes the canvas and the mirror root from the container. Idempotent. */
  unmount(): void;
}

/**
 * Mounts a canvas sized to the container (CSS px times the device pixel ratio) and, after it,
 * the visually hidden DOM mirror root that keyboard focus lands in (05 §6.1).
 */
export function mountSurface(container: HTMLElement): HostSurface {
  const doc = container.ownerDocument;

  const makeCanvas = (): HTMLCanvasElement => {
    const dpr = doc.defaultView?.devicePixelRatio ?? 1;
    const widthCss = container.clientWidth;
    const heightCss = container.clientHeight;
    const c = doc.createElement("canvas");
    c.width = Math.max(1, Math.round(widthCss * dpr));
    c.height = Math.max(1, Math.round(heightCss * dpr));
    c.style.width = `${widthCss}px`;
    c.style.height = `${heightCss}px`;
    c.style.display = "block";
    // The canvas is presentation only: the mirror below carries the semantics (05 §6.1).
    c.setAttribute("aria-hidden", "true");
    c.setAttribute("data-cv-chart-canvas", "");
    return c;
  };
  let canvas = makeCanvas();

  const mirrorRoot = doc.createElement("div");
  mirrorRoot.setAttribute("data-cv-dom-mirror", "");
  // Visually hidden, never display:none, so focus can land in it (05 §6.1).
  mirrorRoot.style.position = "absolute";
  mirrorRoot.style.width = "1px";
  mirrorRoot.style.height = "1px";
  mirrorRoot.style.overflow = "hidden";
  mirrorRoot.style.clipPath = "inset(50%)";

  container.appendChild(canvas);
  container.appendChild(mirrorRoot);

  let mounted = true;
  return {
    get canvas(): HTMLCanvasElement {
      return canvas;
    },
    mirrorRoot,
    replaceCanvas(): HTMLCanvasElement {
      const next = makeCanvas();
      if (mounted) {
        canvas.remove();
        container.insertBefore(next, mirrorRoot);
      }
      canvas = next;
      return next;
    },
    unmount(): void {
      if (!mounted) return;
      mounted = false;
      canvas.remove();
      mirrorRoot.remove();
    },
  };
}

const probes = new WeakMap<object, CapabilityReport>();

/**
 * Lazy capability probe, once per document while it succeeds, on a throwaway canvas (E11-S02 owns detection and
 * the profile rule, README BQ-50 and BQ-57; E11-T05 owns the 2D drawing). The probe context is
 * released at once, so a multi-chart layout never spends the browser's live-context budget
 * (about 16) on probes.
 */
export function probeRenderProfile(doc: Document): CapabilityReport {
  const known = probes.get(doc);
  if (known !== undefined) return known;
  const report = probeCanvas(doc.createElement("canvas"));
  // Only a probe that got a context is kept (E11-T05, README BQ-93): a failed one holds no
  // context, so the next mount (inline "Retry WebGL2") probes again inside the ~16 budget.
  if (report.caps !== null) probes.set(doc, report);
  return report;
}
