// E13-S01 (#423) S4: the settings dialog's injected clock (D06 §6: "Updating…" only past 100 ms).
// Tests drive a fake one; nothing in the dialog reads wall time (40-testing quality rules).
import type { Params } from "../model/types";

export interface SettingsClock {
  /** Runs `fn` once after `ms`; the returned function cancels it. */
  after(ms: number, fn: () => void): () => void;
}

export const systemClock: SettingsClock = {
  after(ms, fn) {
    const handle = globalThis.setTimeout(fn, ms);
    return () => globalThis.clearTimeout(handle);
  },
};

/** The caption word waits this long (D06 §6 budget; D02 D13). */
export const SLOW_MS = 100;

/**
 * The display-only preview of a `client_worker` instance (D06 §6 row 1): the visible window
 * recomputed with draft params, no metric published, no key changed. PROPOSED to #425 with the
 * port (G-a): no engine member previews on `main`, so only tests and stories implement it today.
 */
export interface IndicatorPreviewPort {
  /** Recomputes the preview; settles when the new curve has landed. */
  preview(params: Params): Promise<void>;
  /** Drops the preview: the chart shows the committed instance again. */
  clear(): void;
}
