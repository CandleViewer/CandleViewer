import { describe, expect, it } from "vitest";
import {
  runBulkAction,
  summarise,
  type BulkRunner,
} from "../../../src/features/alerts/bulkActions.js";

describe("runBulkAction", () => {
  it("returns per-id outcomes in input order and an ok/failed summary", async () => {
    const runner: BulkRunner = async (_a, id) => {
      if (id === "b") throw new Error("404 not found");
      if (id === "d") throw "boom";
    };
    const r = await runBulkAction("delete", ["a", "b", "c", "d"], runner);
    expect(r.outcomes).toEqual([
      { id: "a", ok: true },
      { id: "b", ok: false, error: "404 not found" },
      { id: "c", ok: true },
      { id: "d", ok: false, error: "request failed" },
    ]);
    expect(r.summary).toEqual({ total: 4, ok: 2, failed: 2 });
    expect(r.failedIds).toEqual(["b", "d"]);
    expect(r.action).toBe("delete");
  });
  it("runs duplicate ids once", async () => {
    const seen: string[] = [];
    const r = await runBulkAction("enable", ["a", "a", "b"], async (_a, id) => {
      seen.push(id);
    });
    expect(seen).toEqual(["a", "b"]);
    expect(r.summary.total).toBe(2);
  });
  it("handles an empty selection", async () => {
    const r = await runBulkAction("disable", [], async () => {});
    expect(r.summary).toEqual({ total: 0, ok: 0, failed: 0 });
  });
  it("bounds concurrency", async () => {
    let live = 0;
    let peak = 0;
    const release: Array<() => void> = [];
    const runner: BulkRunner = () =>
      new Promise<void>((resolve) => {
        live += 1;
        peak = Math.max(peak, live);
        release.push(() => {
          live -= 1;
          resolve();
        });
      });
    const p = runBulkAction("snooze", ["1", "2", "3", "4", "5"], runner, 2);
    for (let i = 0; i < 20 && release.length < 5; i += 1) {
      await Promise.resolve();
      release.splice(0).forEach((fn) => fn());
    }
    const r = await p;
    expect(peak).toBe(2);
    expect(r.summary.ok).toBe(5);
  });
  it("clamps a zero concurrency to one lane", async () => {
    const r = await runBulkAction("unsnooze", ["a"], async () => {}, 0);
    expect(r.summary.ok).toBe(1);
  });
  it("summarise counts", () => {
    expect(summarise([{ id: "a", ok: true }])).toEqual({ total: 1, ok: 1, failed: 0 });
  });
});
