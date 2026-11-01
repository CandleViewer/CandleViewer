import { useCallback, useRef, useSyncExternalStore } from "react";
import type { ChartEvents } from "@candleviewer/chart-engine";
import { useChartApi } from "./Chart";

/**
 * The latest readout of the enclosing chart (E11-S07, BQ-11), or null before the first one. The
 * engine emits on every crosshair or price move; React hears at most one change per animation
 * frame and keeps only the last value (no per-message state, no queue). `visible: false` arrives
 * once when the crosshair hides. Unmount (or a new chart) cancels the frame and the subscription.
 */
export function useReadout(): ChartEvents["readout"] | null {
  const chart = useChartApi();
  const committed = useRef<ChartEvents["readout"] | null>(null);
  const subscribe = useCallback(
    (notify: () => void): (() => void) => {
      if (chart === null) return () => undefined;
      let latest: ChartEvents["readout"] | null = null;
      let frame: number | null = null;
      const off = chart.subscribe("readout", (r) => {
        latest = r;
        if (frame !== null) return;
        frame = requestAnimationFrame(() => {
          frame = null;
          committed.current = latest;
          notify();
        });
      });
      return () => {
        off();
        if (frame !== null) cancelAnimationFrame(frame);
        // Safe without notify: teardown means unmount or a new chart, so nobody reads the old value.
        committed.current = null;
      };
    },
    [chart],
  );
  return useSyncExternalStore(subscribe, () => committed.current);
}
