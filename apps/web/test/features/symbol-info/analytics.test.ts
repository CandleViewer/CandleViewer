/** E08-D06 §12: the four events, ids and enums only, and "once per field per session". */
import { describe, expect, it, vi } from "vitest";
import {
  createSymbolInfoAnalytics,
  outcomeForFailure,
  outcomeForStatus,
} from "../../../src/features/symbol-info/analytics";

describe("symbol info analytics", () => {
  it("reports the four events with their properties", () => {
    const report = vi.fn();
    const a = createSymbolInfoAnalytics(report);
    a.viewed({
      symbol: "BTCUSDT",
      source: "search",
      section: null,
      status: "Trading",
      catalogue: "warm",
      role: "owner",
    });
    a.loadFailed("BTCUSDT", "coverage", "http_422");
    a.rulesChanged("BTCUSDT", ["tick_size"], 7, 8);
    a.malformed("BTCUSDT", "tick_size", "exponent");
    expect(report.mock.calls.map((c) => (c[0] as { name: string }).name)).toEqual([
      "symbol.info_viewed",
      "symbol.info_load_failed",
      "symbol.info_rules_changed",
      "symbol.info_value_malformed",
    ]);
    expect(report.mock.calls[2]?.[0]).toEqual({
      name: "symbol.info_rules_changed",
      symbol: "BTCUSDT",
      fields: ["tick_size"],
      revision_from: 7,
      revision_to: 8,
    });
  });

  it("reports a malformed field once per session, per symbol", () => {
    const report = vi.fn();
    const a = createSymbolInfoAnalytics(report);
    a.malformed("BTCUSDT", "tick_size", "exponent");
    a.malformed("BTCUSDT", "tick_size", "exponent");
    a.malformed("ETHUSDT", "tick_size", "exponent");
    a.malformed("BTCUSDT", "qty_step", "unparsable");
    expect(report).toHaveBeenCalledTimes(3);
  });

  it("maps failures to the outcome enum without any value", () => {
    expect(outcomeForFailure({ cause: "network" })).toBe("network");
    expect(outcomeForFailure({ cause: "malformed" })).toBe("network");
    expect(outcomeForFailure({ cause: "unavailable", instance: "urn:cv:req:x" })).toBe(
      "http_503_60s",
    );
    expect(outcomeForFailure({ cause: "http", status: 500, instance: null })).toBe("http_5xx");
    expect([403, 404, 422].map(outcomeForStatus)).toEqual(["http_403", "http_404", "http_422"]);
  });

  it("dispatches on the app's seam by default", () => {
    const seen: unknown[] = [];
    const listener = (e: Event): void => {
      seen.push((e as CustomEvent).detail);
    };
    window.addEventListener("cv:analytics", listener);
    createSymbolInfoAnalytics().loadFailed("BTCUSDT", "catalogue", "network");
    window.removeEventListener("cv:analytics", listener);
    expect(seen).toEqual([
      {
        name: "symbol.info_load_failed",
        symbol: "BTCUSDT",
        dependency: "catalogue",
        outcome: "network",
      },
    ]);
  });
});
