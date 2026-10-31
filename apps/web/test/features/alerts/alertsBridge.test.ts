import { describe, expect, it, vi } from "vitest";
import { createAlertsStore } from "../../../src/features/alerts/alertsStore.js";
import { startAlertsBridge } from "../../../src/features/alerts/alertsBridge.js";
import type { Alert, AlertsFrame } from "../../../src/features/alerts/types.js";

const delivery = (alert_id: string, fired_at_ms: number): AlertsFrame["deliveries"][number] => ({
  id: fired_at_ms,
  alert_id,
  channel: "in_app",
  status: "sent",
  message: "m",
  fired_at_ms,
});

function rig() {
  const store = createAlertsStore();
  store.replaceAll([{ id: "a", enabled: true } as Alert, { id: "b", enabled: true } as Alert]);
  let push: (f: AlertsFrame) => void = () => {};
  const unsubscribe = vi.fn();
  const source = {
    subscribe: (cb: (f: AlertsFrame) => void) => {
      push = cb;
      return unsubscribe;
    },
  };
  const frames: Array<() => void> = [];
  const raf = vi.fn((cb: (t: number) => void) => frames.push(() => cb(0)));
  const caf = vi.fn();
  const stop = startAlertsBridge(source, store, { raf, caf });
  return { store, push: (f: AlertsFrame) => push(f), unsubscribe, frames, raf, caf, stop };
}

describe("alerts bridge", () => {
  it("coalesces many frames into one store write per animation frame", () => {
    const r = rig();
    const listener = vi.fn();
    r.store.subscribe(listener);
    r.push({ deliveries: [delivery("a", 1000), delivery("a", 3000)] });
    r.push({ deliveries: [delivery("a", 2000), delivery("b", 500)], unacked_count: 7 });
    expect(listener).not.toHaveBeenCalled();
    expect(r.raf).toHaveBeenCalledTimes(1);
    r.frames[0]?.();
    const byId = r.store.getState().byId;
    expect(byId.get("a")).toMatchObject({
      fire_count: 3,
      last_fired_at: new Date(3000).toISOString(),
    });
    expect(byId.get("b")).toMatchObject({ fire_count: 1 });
    expect(r.store.getState().unackedCount).toBe(7);
  });
  it("a count-only frame still lands on a frame", () => {
    const r = rig();
    r.push({ deliveries: [], unacked_count: 2 });
    r.frames[0]?.();
    expect(r.store.getState().unackedCount).toBe(2);
    expect(r.store.list().every((a) => (a.fire_count ?? 0) === 0)).toBe(true);
  });
  it("a frame without a count leaves unackedCount alone", () => {
    const r = rig();
    r.push({ deliveries: [delivery("a", 1)] });
    r.frames[0]?.();
    expect(r.store.getState().unackedCount).toBeNull();
  });
  it("later arrivals start a fresh fact after a frame", () => {
    const r = rig();
    r.push({ deliveries: [delivery("a", 1)] });
    r.frames[0]?.();
    r.push({ deliveries: [delivery("a", 2)] });
    r.frames[1]?.();
    expect(r.store.getState().byId.get("a")?.fire_count).toBe(2);
  });
  it("teardown unsubscribes, cancels the pending frame and ignores later frames", () => {
    const r = rig();
    r.push({ deliveries: [delivery("a", 1)] });
    r.stop();
    expect(r.unsubscribe).toHaveBeenCalledTimes(1);
    expect(r.caf).toHaveBeenCalledTimes(1);
    r.push({ deliveries: [delivery("a", 2)] });
    expect(r.raf).toHaveBeenCalledTimes(1);
    expect(r.store.getState().byId.get("a")?.fire_count).toBeUndefined();
  });
});
