/**
 * E08-S08 (#4702): SCR-100's instrument facts (E08-D07 §4.1, D20) from E08-S09's index: a list symbol the Trading
 * listing lacks is looked up once while the page shows (no network: `apiFetch` is faked), and delisted is read from
 * the instrument.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import type { IndexSnapshot } from "../../../src/features/symbol-search/instrumentIndex";
import { toEntry, type Instrument } from "../../../src/features/symbol-search/ranking";
import {
  isDelisted,
  useInstrumentFacts,
  useListLookups,
  useWatchlistIndex,
  type InstrumentSource,
} from "../../../src/features/watchlist/instruments";

const inst = (symbol: string, status: Instrument["status"] = "Trading"): Instrument => ({
  symbol,
  category: "linear",
  status,
  tick_size: "0.01",
  qty_step: "0.001",
});
const SNAPSHOT: IndexSnapshot = {
  phase: "ready",
  entries: [toEntry(inst("BTCUSDT"))],
  known: [],
  unlisted: [],
  loadedAt: 0,
  cacheAgeS: 0,
  staleSince: null,
  refreshing: false,
  retryAt: null,
  failure: null,
};

afterEach(() => apiFetch.mockReset());

describe("isDelisted", () => {
  it("reads the flag, else a status neither Trading nor PreLaunch", () => {
    expect(isDelisted(undefined)).toBe(false);
    expect(isDelisted(inst("BTCUSDT"))).toBe(false);
    expect(isDelisted(inst("NEWUSDT", "PreLaunch"))).toBe(false);
    expect(isDelisted(inst("LUNAUSDT", "Closed"))).toBe(true);
    expect(isDelisted({ ...inst("OLDUSDT"), delisted: true })).toBe(true);
  });
});

describe("useListLookups", () => {
  it("looks up a symbol the listing lacks, once, and its answer joins the index", async () => {
    apiFetch.mockImplementation(
      async () => new Response(JSON.stringify(inst("LUNAUSDT", "Closed")), { status: 200 }),
    );
    const learn = vi.fn();
    const source: InstrumentSource = {
      subscribe: () => () => undefined,
      getSnapshot: () => SNAPSHOT,
      learn,
      reread: () => undefined,
    };
    const { rerender } = renderHook(() => {
      const facts = useInstrumentFacts(source);
      useListLookups(source, facts, ["BTCUSDT", "LUNAUSDT"]);
      return facts;
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    rerender();
    expect(apiFetch).toHaveBeenCalledOnce();
    expect(apiFetch.mock.calls[0]?.[0]).toBe("/api/v1/instruments/LUNAUSDT");
    expect(learn).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "status", symbol: "LUNAUSDT" }),
    );
  });
});

describe("useWatchlistIndex", () => {
  it("runs an index of its own while the shell's does not run, and stops it on unmount", async () => {
    apiFetch.mockImplementation(() => new Promise<Response>(() => undefined));
    const { result, unmount } = renderHook(() => useWatchlistIndex());
    expect(result.current.getSnapshot().phase).toBe("loading");
    expect(apiFetch).toHaveBeenCalledOnce();
    unmount();
  });
});
