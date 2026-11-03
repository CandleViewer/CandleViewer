// Host adapter (C-2.16): the only engine code that touches the DOM. It reaches the document
// through `container.ownerDocument` and never through a global, so it works inside any realm
// (iframe, Electron view) and stays inside the `no-restricted-globals` rule. src/core and
// src/layers never import this module (.dependency-cruiser.js `chart-engine-core-no-dom-host`).

import { probeCanvas, type CapabilityReport } from "../gl/capability.js";
import { backingPx } from "../viewport/pixels.js";

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
  /**
   * E11-S13: the canvas `img` label, kept and re-applied on a replaced canvas; a no-op with the
   * mirror flag off, where the canvas stays `aria-hidden`.
   */
  setCanvasLabel(text: string): void;
  /** Removes the canvas and the mirror root from the container. Idempotent. */
  unmount(): void;
}

/**
 * Mounts a canvas sized to the container (CSS px times the device pixel ratio) and, after it,
 * the visually hidden DOM mirror root that keyboard focus lands in (05 §6.1). With `a11yMirror`
 * (E11-S13 BQ-S13-15, default off) both go inside a `role="application"` wrapper and the canvas
 * is a labelled `role="img"` (26 §12, E11-D07 §2, PROPOSED until E11-Q05); off, the tree is today's.
 */
export function mountSurface(container: HTMLElement, a11yMirror = false): HostSurface {
  const doc = container.ownerDocument;
  // An `img` is never unnamed (axe role-img-alt): a provisional name until the mirror's first roll.
  const provisionalLabel = "Chart";
  let label = provisionalLabel;

  const makeCanvas = (): HTMLCanvasElement => {
    const dpr = doc.defaultView?.devicePixelRatio ?? 1;
    // BQ-145: CSS box = backing / dpr, so CSS px map to device px by exactly dpr.
    const w = backingPx(container.clientWidth, dpr);
    const h = backingPx(container.clientHeight, dpr);
    const c = doc.createElement("canvas");
    c.width = Math.max(1, w);
    c.height = Math.max(1, h);
    c.style.width = `${w / dpr}px`;
    c.style.height = `${h / dpr}px`;
    c.style.display = "block";
    // Flag off, the canvas is hidden presentation and the mirror carries the semantics (05 §6.1).
    // Flag on, it is an `img` whose rolling label the mirror writes (D06 §8 L-1), never a tab
    // stop (E06-D03 D4: `tabindex="-1"`; the chart's one stop is the root's, PR-3).
    if (!a11yMirror) c.setAttribute("aria-hidden", "true");
    else {
      c.setAttribute("role", "img");
      c.setAttribute("aria-label", label);
      c.setAttribute("tabindex", "-1");
    }
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

  // The wrapper's static name is the symbol and interval (26 §12); the engine has neither until
  // PR-3's options, so the provisional name is generic (E47-D07's words, #1306).
  let parent: HTMLElement = container;
  if (a11yMirror) {
    parent = doc.createElement("div");
    parent.setAttribute("role", "application");
    parent.setAttribute("aria-roledescription", "trading chart"); // E06-D03 D4
    parent.setAttribute("aria-label", "Chart");
    parent.setAttribute("data-cv-chart-root", "");
    parent.style.position = "relative";
    container.appendChild(parent);
  }
  parent.appendChild(canvas);
  parent.appendChild(mirrorRoot);

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
        parent.insertBefore(next, mirrorRoot);
      }
      canvas = next;
      return next;
    },
    setCanvasLabel(text: string): void {
      if (!a11yMirror) return;
      label = text === "" ? provisionalLabel : text;
      canvas.setAttribute("aria-label", label);
    },
    unmount(): void {
      if (!mounted) return;
      mounted = false;
      canvas.remove();
      mirrorRoot.remove();
      if (parent !== container) parent.remove();
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
