// E13-S01 (#423) S2: React reads of the indicator store, one selector each, through
// `useSyncExternalStore` (the subscription is torn down on unmount). Config only: values and
// series reach the legend through the coalesced atom path (BQ-7, S6), never through these hooks.
import { useCallback, useSyncExternalStore } from "react";
import type { Instance } from "../model/instances";
import type { HistoryState, IndicatorStore } from "./indicatorStore";

export function useChartIndicators(store: IndicatorStore, chart: string): readonly Instance[] {
  const get = useCallback(() => store.selectInstances(chart), [store, chart]);
  return useSyncExternalStore(store.subscribe, get, get);
}

export function usePaneIndicators(
  store: IndicatorStore,
  chart: string,
  pane: string,
): readonly Instance[] {
  const get = useCallback(() => store.selectPane(chart, pane), [store, chart, pane]);
  return useSyncExternalStore(store.subscribe, get, get);
}

export function useIndicatorHistory(store: IndicatorStore, chart: string): HistoryState {
  const get = useCallback(() => store.selectHistory(chart), [store, chart]);
  return useSyncExternalStore(store.subscribe, get, get);
}
