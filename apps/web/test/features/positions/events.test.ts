/**
 * E29-S01 (#911) analytics on the `cv:analytics` seam: `blotter.opened`, `blotter.grouped{by}` and
 * `blotter.filtered`, with kinds and counts only, never an account, a symbol or a figure.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  reportFiltered,
  reportGrouped,
  reportOpened,
} from "../../../src/features/positions/events";
import { THEME_ANALYTICS_EVENT } from "../../../src/shell/bootstrap/themeStore";
import { SUB1 } from "./support/fakes";

const seen = vi.fn();
const listen = (event: Event): void => seen((event as CustomEvent).detail);

beforeEach(() => window.addEventListener(THEME_ANALYTICS_EVENT, listen));
afterEach(() => {
  window.removeEventListener(THEME_ANALYTICS_EVENT, listen);
  seen.mockReset();
});

describe("blotter analytics", () => {
  it("opened and grouped", () => {
    reportOpened("positions");
    reportGrouped("trade_group");
    expect(seen.mock.calls).toEqual([
      [{ name: "blotter.opened", tab: "positions" }],
      [{ name: "blotter.grouped", by: "trade_group" }],
    ]);
  });

  it("filtered: how many chips, of which kinds, never their values", () => {
    reportFiltered([
      { kind: "symbol", value: "BTCUSDT" },
      { kind: "account", value: SUB1 },
      { kind: "account", value: "a1000000-0000-4000-8000-000000000003" },
    ]);
    expect(seen).toHaveBeenCalledWith({
      name: "blotter.filtered",
      chips: 3,
      kinds: ["account", "symbol"],
    });
    expect(JSON.stringify(seen.mock.calls)).not.toMatch(/BTCUSDT|a1000000/);
  });
});
