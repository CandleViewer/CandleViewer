// E22-S01 (#714) BQ-213: the click-to-locate seam (D4-08); no chart-engine edit.
import { describe, expect, it, vi } from "vitest";
import { locate, subscribeLocate } from "../../../src/lib/state/chartLocate";

describe("chart locate seam", () => {
  it("hands a print's time and price to every subscriber until it unsubscribes", () => {
    const a = vi.fn();
    const b = vi.fn();
    const offA = subscribeLocate(a);
    const offB = subscribeLocate(b);
    const request = { symbol: "BTCUSDT", tsMs: 1_700_000_000_123, price: 65000.5 };
    locate(request);
    expect(a).toHaveBeenCalledWith(request);
    expect(b).toHaveBeenCalledWith(request);
    offA();
    locate(request);
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(2);
    offB();
  });

  it("ignores a request without a finite time or price, and is a no-op with no subscriber", () => {
    const listener = vi.fn();
    const off = subscribeLocate(listener);
    locate({ symbol: "BTCUSDT", tsMs: Number.NaN, price: 1 });
    locate({ symbol: "BTCUSDT", tsMs: 1, price: Number.POSITIVE_INFINITY });
    expect(listener).not.toHaveBeenCalled();
    off();
    expect(() => locate({ symbol: "BTCUSDT", tsMs: 1, price: 1 })).not.toThrow();
  });
});
