import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createAlertsStore, useAlerts } from "../../../src/features/alerts/alertsStore.js";
import type { Alert } from "../../../src/features/alerts/types.js";

const mk = (id: string, over: Partial<Alert> = {}): Alert =>
  ({ id, enabled: true, ...over }) as Alert;

describe("alerts store", () => {
  it("replaceAll keeps id order and drops id-less records", () => {
    const s = createAlertsStore();
    s.replaceAll([mk("b"), { enabled: true } as Alert, mk("a")]);
    expect(s.list().map((a) => a.id)).toEqual(["b", "a"]);
  });
  it("upsert and remove notify; no-ops stay silent", () => {
    const s = createAlertsStore();
    const l = vi.fn();
    s.subscribe(l);
    s.upsert(mk("a"));
    s.upsert({ enabled: true } as Alert);
    s.upsert(mk("a", { name: "x" }));
    expect(l).toHaveBeenCalledTimes(2);
    s.remove("zzz");
    expect(l).toHaveBeenCalledTimes(2);
    s.remove("a");
    expect(l).toHaveBeenCalledTimes(3);
    expect(s.list()).toEqual([]);
  });
  it("list is referentially stable between writes", () => {
    const s = createAlertsStore();
    s.upsert(mk("a"));
    expect(s.list()).toBe(s.list());
    const before = s.list();
    s.upsert(mk("b"));
    expect(s.list()).not.toBe(before);
  });
  it("recordFires advances time forward only and sums counts; unknown ids ignored", () => {
    const s = createAlertsStore();
    s.replaceAll([
      mk("a", { last_fired_at: "2026-10-31T10:00:00Z", fire_count: 1 }),
      mk("n"),
      mk("bad", { last_fired_at: "x" }),
    ]);
    const l = vi.fn();
    s.subscribe(l);
    const t = Date.parse("2026-10-31T11:00:00Z");
    s.recordFires([
      { alertId: "a", firedAtMs: t, count: 2 },
      { alertId: "a", firedAtMs: t - 1_000, count: 1 },
      { alertId: "n", firedAtMs: t, count: 0 },
      { alertId: "bad", firedAtMs: t, count: 1 },
      { alertId: "ghost", firedAtMs: t, count: 1 },
      { alertId: "a", firedAtMs: Number.NaN, count: 1 },
    ]);
    expect(l).toHaveBeenCalledTimes(1);
    const byId = s.getState().byId;
    expect(byId.get("a")).toMatchObject({
      last_fired_at: "2026-10-31T11:00:00.000Z",
      fire_count: 4,
    });
    expect(byId.get("n")).toMatchObject({ fire_count: 1 });
    expect(byId.get("bad")).toMatchObject({ last_fired_at: "2026-10-31T11:00:00.000Z" });
    s.recordFires([{ alertId: "ghost", firedAtMs: t, count: 1 }]);
    expect(l).toHaveBeenCalledTimes(1);
  });
  it("setUnackedCount notifies only on change", () => {
    const s = createAlertsStore();
    const l = vi.fn();
    s.subscribe(l);
    s.setUnackedCount(3);
    s.setUnackedCount(3);
    expect(l).toHaveBeenCalledTimes(1);
    expect(s.getState().unackedCount).toBe(3);
  });
  it("unsubscribe stops notifications", () => {
    const s = createAlertsStore();
    const l = vi.fn();
    s.subscribe(l)();
    s.upsert(mk("a"));
    expect(l).not.toHaveBeenCalled();
  });
  it("useAlerts re-renders on change and tears down on unmount", () => {
    const s = createAlertsStore();
    const { result, unmount } = renderHook(() => useAlerts(s));
    expect(result.current).toEqual([]);
    act(() => s.upsert(mk("a")));
    expect(result.current.map((a) => a.id)).toEqual(["a"]);
    unmount();
    act(() => s.upsert(mk("b")));
  });
});
