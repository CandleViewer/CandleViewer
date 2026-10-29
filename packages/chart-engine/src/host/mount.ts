// Host adapter (C-2.16): the only engine code that touches the DOM. It reaches the document
// through `container.ownerDocument` and never through a global, so it works inside any realm
// (iframe, Electron view) and stays inside the `no-restricted-globals` rule. src/core and
// src/layers never import this module (.dependency-cruiser.js `chart-engine-core-no-dom-host`).

/** The token the stub paints the canvas with (§5 rule 1: colour comes from tokens only). */
export const BACKGROUND_TOKEN = "color.chart.background";

export interface HostSurface {
  /**
   * The stub paints it through a 2D context, so it can never take a WebGL2 context: the GL
   * backend (E11-S02) replaces this canvas rather than reusing it.
   */
  readonly canvas: HTMLCanvasElement;
  readonly mirrorRoot: HTMLElement;
  /** Paints the whole canvas with `color`; a missing token leaves it cleared. */
  fill(color: string | undefined): void;
  /** Removes the canvas and the mirror root from the container. Idempotent. */
  unmount(): void;
}

/**
 * Mounts a canvas sized to the container (CSS px times the device pixel ratio) and, after it,
 * the visually hidden DOM mirror root that keyboard focus lands in (05 §6.1).
 */
export function mountSurface(container: HTMLElement): HostSurface {
  const doc = container.ownerDocument;
  const dpr = doc.defaultView?.devicePixelRatio ?? 1;
  const widthCss = container.clientWidth;
  const heightCss = container.clientHeight;

  const canvas = doc.createElement("canvas");
  canvas.width = Math.max(1, Math.round(widthCss * dpr));
  canvas.height = Math.max(1, Math.round(heightCss * dpr));
  canvas.style.width = `${widthCss}px`;
  canvas.style.height = `${heightCss}px`;
  canvas.style.display = "block";
  // The canvas is presentation only: the mirror below carries the semantics (05 §6.1).
  canvas.setAttribute("aria-hidden", "true");
  canvas.setAttribute("data-cv-chart-canvas", "");

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
    canvas,
    mirrorRoot,
    fill(color: string | undefined): void {
      const ctx = canvas.getContext("2d");
      if (ctx === null) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (color === undefined || color === "") return;
      ctx.fillStyle = color;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    },
    unmount(): void {
      if (!mounted) return;
      mounted = false;
      canvas.remove();
      mirrorRoot.remove();
    },
  };
}

/**
 * Lazy capability probe: WebGL2 on a throwaway canvas means the `full` profile, anything else
 * `degraded-2d` (E11-T05 owns the real detection rule and the `reduced` step). The probe context
 * is released at once, so a multi-chart layout never spends the browser's live-context budget
 * (about 16) on probes.
 */
export function probeRenderProfile(container: HTMLElement): "full" | "degraded-2d" {
  const probe = container.ownerDocument.createElement("canvas");
  const gl = probe.getContext("webgl2");
  if (gl === null) return "degraded-2d";
  gl.getExtension("WEBGL_lose_context")?.loseContext();
  return "full";
}

/** Encodes the canvas as PNG. */
export function canvasToBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob === null) reject(new Error("chart-engine: the canvas could not be encoded"));
      else resolve(blob);
    }, "image/png");
  });
}
