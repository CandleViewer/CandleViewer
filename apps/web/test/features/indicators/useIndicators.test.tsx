/**
 * E13-S01 (#423) S2: the React reads of the indicator store re-render on their slice only and
 * unsubscribe on unmount (30-frontend-react: every subscription has a teardown test).
 */
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createFakeEngine } from "../../../src/features/indicators/engine/stub/fakeEngine";
import {
  normaliseDescriptor,
  type CatalogueEntry,
} from "../../../src/features/indicators/model/catalogue";
import { createIndicatorStore } from "../../../src/features/indicators/store/indicatorStore";
import {
  useChartIndicators,
  useIndicatorHistory,
  usePaneIndicators,
} from "../../../src/features/indicators/store/useIndicators";
import { EMA } from "./fixtures";

const ema = normaliseDescriptor(EMA) as CatalogueEntry;
const input = { entry: ema, params: {}, target: "overlay", source: "library" } as const;

describe("indicator store hooks", () => {
  it("test_hooks_follow_store_changes", () => {
    const store = createIndicatorStore({ report: () => undefined });
    store.bind("c", createFakeEngine());
    const { result } = renderHook(() => ({
      all: useChartIndicators(store, "c"),
      price: usePaneIndicators(store, "c", "price"),
      history: useIndicatorHistory(store, "c"),
    }));
    expect(result.current.all).toEqual([]);
    act(() => {
      store.add("c", input);
    });
    expect(result.current.all).toHaveLength(1);
    expect(result.current.price).toHaveLength(1);
    expect(result.current.history).toEqual({ canUndo: true, canRedo: false });
  });

  it("test_unmount_unsubscribes", () => {
    const store = createIndicatorStore({ report: () => undefined });
    const off = vi.fn();
    const subscribe = vi.spyOn(store, "subscribe").mockImplementation(() => off);
    const { unmount } = renderHook(() => useChartIndicators(store, "c"));
    expect(subscribe).toHaveBeenCalled();
    unmount();
    expect(off).toHaveBeenCalled();
  });
});
