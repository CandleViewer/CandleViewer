/**
 * E29-S02 PR3a (#912) the amend's steps (`instruments.ts`): `GET /instruments/{symbol}`'s tick, lot
 * and minimum through symbol search's `lookupSymbol`, kept per symbol in a bounded cache; a step is
 * never guessed, a failed lookup is asked again only after `RETRY_MS`, and nothing lands after
 * `stop`. Instruments carry the policy corpus's figures (`packages/fixtures/golden/policy/`); no
 * golden of the route exists.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { generated } from "@candleviewer/protocol";
import {
  createStepsCache,
  MAX_SYMBOLS,
  RETRY_MS,
  stepsOf,
} from "../../../../src/features/positions/orders/instruments";
import type { Lookup } from "../../../../src/features/symbol-search/instrumentIndex";
import { repoFile } from "../../../lib/ws/support/schemaHarness";

const apiFetch = vi.hoisted(() => vi.fn<(path: string, init?: RequestInit) => Promise<Response>>());
vi.mock("../../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

type Instrument = generated.rest.components["schemas"]["Instrument"];

/** A `22` `Instrument` with the policy corpus's steps for `symbol`. */
function instrument(symbol: string): Instrument {
  const corpus = JSON.parse(repoFile("packages/fixtures/golden/policy/corpus.json")) as {
    cases: {
      instrument: { symbol: string; tick_size: string; qty_step: string; min_order_qty: string };
    }[];
  };
  const found = corpus.cases.find((c) => c.instrument.symbol === symbol)?.instrument;
  if (found === undefined) throw new Error(`no corpus instrument ${symbol}`);
  return {
    symbol,
    category: "linear",
    status: "Trading",
    tick_size: found.tick_size,
    qty_step: found.qty_step,
    min_order_qty: found.min_order_qty,
  };
}
const listed = (symbol: string): Lookup => ({
  kind: "listed",
  symbol,
  instrument: instrument(symbol),
});

/** A lookup whose answers the test hands out, one deferred promise per call. */
function deferredLookup() {
  const calls: { symbol: string; answer: (lookup: Lookup) => void; fail: () => void }[] = [];
  const lookup = vi.fn(
    (symbol: string) =>
      new Promise<Lookup>((resolve, reject) => {
        calls.push({ symbol, answer: resolve, fail: () => reject(new Error("no answer")) });
      }),
  );
  return { lookup, calls };
}
const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

afterEach(() => {
  apiFetch.mockReset();
});

describe("stepsOf: the tick, the lot and the minimum, never guessed", () => {
  it("reads a listed instrument's, and a non-Trading one's", () => {
    expect(stepsOf(listed("BTCUSDT"))).toEqual({
      tickSize: "0.1",
      qtyStep: "0.001",
      minOrderQty: "0.001",
    });
    const status: Lookup = { kind: "status", symbol: "ETHUSDT", instrument: instrument("ETHUSDT") };
    expect(stepsOf(status)?.tickSize).toBe("0.01");
  });

  it("none for a 404, an unchecked lookup, or a step that is no positive decimal", () => {
    expect(stepsOf({ kind: "not_listed", symbol: "BTCUSDT" })).toBeNull();
    expect(stepsOf({ kind: "unchecked", symbol: "BTCUSDT" })).toBeNull();
    const zero = { ...instrument("BTCUSDT"), tick_size: "0" };
    expect(stepsOf({ kind: "listed", symbol: "BTCUSDT", instrument: zero })).toBeNull();
    const junk = { ...instrument("BTCUSDT"), qty_step: "1e-3" };
    expect(stepsOf({ kind: "listed", symbol: "BTCUSDT", instrument: junk })).toBeNull();
    const noMinimum: Instrument = { ...instrument("BTCUSDT") };
    delete noMinimum.min_order_qty;
    expect(stepsOf({ kind: "listed", symbol: "BTCUSDT", instrument: noMinimum })?.minOrderQty).toBe(
      null,
    );
  });
});

describe("the cache", () => {
  it("asks once per symbol, never while a lookup is in flight, and tells its readers", async () => {
    const { lookup, calls } = deferredLookup();
    const cache = createStepsCache({ lookup });
    const heard = vi.fn();
    cache.subscribe(heard);
    expect(cache.get("BTCUSDT")).toBeNull();
    cache.load("BTCUSDT");
    cache.load("BTCUSDT");
    expect(lookup).toHaveBeenCalledTimes(1);
    calls[0]?.answer(listed("BTCUSDT"));
    await flush();
    expect(cache.get("BTCUSDT")?.qtyStep).toBe("0.001");
    expect(cache.getVersion()).toBe(1);
    expect(heard).toHaveBeenCalledTimes(1);
    cache.load("BTCUSDT");
    expect(lookup).toHaveBeenCalledTimes(1);
  });

  it("a failed lookup leaves no step and is asked again only after RETRY_MS", async () => {
    let now = 0;
    const { lookup, calls } = deferredLookup();
    const cache = createStepsCache({ lookup, now: () => now });
    const heard = vi.fn();
    cache.subscribe(heard);
    cache.load("ETHUSDT");
    calls[0]?.answer({ kind: "unchecked", symbol: "ETHUSDT" });
    await flush();
    expect(cache.get("ETHUSDT")).toBeNull();
    expect(heard).not.toHaveBeenCalled();
    now = RETRY_MS - 1;
    cache.load("ETHUSDT");
    expect(lookup).toHaveBeenCalledTimes(1);
    now = RETRY_MS;
    cache.load("ETHUSDT");
    expect(lookup).toHaveBeenCalledTimes(2);
    calls[1]?.fail();
    await flush();
    expect(cache.get("ETHUSDT")).toBeNull();
  });

  it("is bounded: past its size the oldest symbol is forgotten (C-2.18)", async () => {
    const { lookup, calls } = deferredLookup();
    const cache = createStepsCache({ lookup, max: 2 });
    for (const symbol of ["BTCUSDT", "ETHUSDT", "AWKWARDUSDT"]) {
      cache.load(symbol);
      calls.at(-1)?.answer(listed(symbol));
      await flush();
    }
    expect(cache.get("BTCUSDT")).toBeNull();
    expect(cache.get("ETHUSDT")).not.toBeNull();
    expect(cache.get("AWKWARDUSDT")?.qtyStep).toBe("0.003");
    expect(MAX_SYMBOLS).toBe(64);
  });

  it("nothing lands after stop, and nothing more is asked", async () => {
    const { lookup, calls } = deferredLookup();
    const cache = createStepsCache({ lookup });
    cache.load("BTCUSDT");
    cache.stop();
    calls[0]?.answer(listed("BTCUSDT"));
    await flush();
    expect(cache.get("BTCUSDT")).toBeNull();
    cache.load("ETHUSDT");
    expect(lookup).toHaveBeenCalledTimes(1);
  });

  it("by default asks symbol search's lookupSymbol, GET /instruments/{symbol}", async () => {
    apiFetch.mockResolvedValueOnce(
      new Response(JSON.stringify(instrument("ETHUSDT")), { status: 200 }),
    );
    const cache = createStepsCache();
    cache.load("ETHUSDT");
    await vi.waitFor(() => expect(cache.get("ETHUSDT")).not.toBeNull());
    expect(apiFetch.mock.calls[0]?.[0]).toBe("/api/v1/instruments/ETHUSDT");
    expect(cache.get("ETHUSDT")).toEqual({
      tickSize: "0.01",
      qtyStep: "0.01",
      minOrderQty: "0.01",
    });
    cache.stop();
  });
});
