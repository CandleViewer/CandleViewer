// E24-S08 (#783) slice 2: the analytics events: ids, enums and public symbols only, never a value.
import { afterEach, describe, expect, it, vi } from "vitest";
import { createBasisAnalytics } from "../../../src/features/basis/analytics";

describe("basis analytics", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reports each event with names and enums only", () => {
    const report = vi.fn();
    const a = createBasisAnalytics(report);
    a.sourceToggled("mark");
    a.sourceFailed("BTCUSDT", "revoked");
    a.retryShown("BTCUSDT");
    a.retryClicked("BTCUSDT");
    expect(report.mock.calls.map((c) => c[0])).toEqual([
      { name: "basis.source_toggled", source: "mark" },
      { name: "basis.source_failed", symbol: "BTCUSDT", status: "revoked" },
      { name: "basis.retry_shown", symbol: "BTCUSDT" },
      { name: "basis.retry_clicked", symbol: "BTCUSDT" },
    ]);
  });

  it("dispatches on the app's cv:analytics seam by default", () => {
    const seen: unknown[] = [];
    const on = (e: Event): void => void seen.push((e as CustomEvent).detail);
    window.addEventListener("cv:analytics", on);
    createBasisAnalytics().sourceToggled("last");
    window.removeEventListener("cv:analytics", on);
    expect(seen).toEqual([{ name: "basis.source_toggled", source: "last" }]);
  });
});
