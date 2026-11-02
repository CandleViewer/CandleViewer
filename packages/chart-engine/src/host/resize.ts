// Size and DPR detection on the main thread (E11-S10, README BQ-145 / BQ-146): the container's
// ResizeObserver (moved here from input-router.ts) on the device-pixel-content-box where the
// browser has it, plus a `(resolution: Xdppx)` media query re-armed after every change, which
// catches OS scaling and browser zoom (05 §4) the observer may not report; on a change it
// re-observes, so the observer sends both boxes fresh. Both feed the host's `resize`, already
// coalesced to one message per frame. The size sent is the backing store over dpr, so the
// canvas's CSS box is `backing / dpr` and CSS px map to device px by exactly dpr. A hidden or 0×0
// container sends 0, which suspends the chart (BQ-147). DOM program; the window is reached
// through the target's document, never a global.
import { backingPx } from "../viewport/pixels.js";

/** The `ChartHost` member the watcher uses. */
export interface ResizeSink {
  resize(width: number, height: number, dpr: number): void;
}

interface BoxSize {
  readonly inlineSize: number;
  readonly blockSize: number;
}
interface SizeEntry {
  readonly contentBoxSize?: readonly BoxSize[];
  readonly devicePixelContentBoxSize?: readonly BoxSize[];
}

/** Watches `target`'s size and the page's DPR into `sink`; returns the detach function. */
export function watchSize(target: HTMLElement, sink: ResizeSink): () => void {
  const view = target.ownerDocument.defaultView;
  if (view === null) return () => undefined;
  const ratio = (): number => (view.devicePixelRatio > 0 ? view.devicePixelRatio : 1);
  // Sized from the entry's own content box (CSS px), never from clientWidth, which includes padding.
  const report = (device?: BoxSize, css?: BoxSize): void => {
    const dpr = ratio();
    const w = backingPx(css?.inlineSize ?? target.clientWidth, dpr, device?.inlineSize);
    const h = backingPx(css?.blockSize ?? target.clientHeight, dpr, device?.blockSize);
    sink.resize(w / dpr, h / dpr, dpr);
  };

  const observer =
    typeof view.ResizeObserver === "function"
      ? new view.ResizeObserver((entries: readonly SizeEntry[]) => {
          const entry = entries.at(-1);
          report(entry?.devicePixelContentBoxSize?.[0], entry?.contentBoxSize?.[0]);
        })
      : null;
  // A fresh observation of a non-empty box delivers one entry with both boxes as they are now.
  const observe = (): void => {
    if (observer === null) return;
    observer.disconnect();
    try {
      observer.observe(target, { box: "device-pixel-content-box" });
    } catch {
      observer.observe(target); // no device-pixel-content-box: the content box and round(css·dpr)
    }
  };
  observe();
  // A hidden container is sent 0 at once, so a chart mounted hidden is suspended (BQ-147) rather
  // than waiting on an observer entry; in inline mode its 1×1 placeholder may still draw a frame.
  if (target.clientWidth === 0 || target.clientHeight === 0) report();

  // The query is DPR-specific, so it is re-armed for the new ratio after each change.
  let mq: MediaQueryList | null = null;
  // A zoom on a fluid container moves the CSS box but not the device box, so the observer sends
  // nothing; and the last CSS box is stale at the new ratio. Re-observing yields a fresh entry.
  const onChange = (): void => {
    if (observer === null) report();
    else observe();
    arm();
  };
  const arm = (): void => {
    if (typeof view.matchMedia !== "function") return;
    mq = view.matchMedia(`(resolution: ${ratio()}dppx)`);
    mq.addEventListener("change", onChange, { once: true });
  };
  arm();

  return () => {
    mq?.removeEventListener("change", onChange);
    mq = null;
    observer?.disconnect();
  };
}
