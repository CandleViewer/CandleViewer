/** E08-D06 §6 and §11.3 / E08-D13 §5: the states the data layer derives, and their exact words. */
import type { generated } from "@candleviewer/protocol";
import { describe, expect, it } from "vitest";
import type { DetailOutcome } from "../../../src/features/symbol-info/instrumentDetail";
import {
  contractPhase,
  coverageGate,
  coverageState,
  liveState,
  liveTransition,
  notTradingView,
  type LiveInput,
} from "../../../src/features/symbol-info/state";

type Detail = generated.rest.components["schemas"]["InstrumentDetail"];
/** `exactOptionalPropertyTypes`: an absent field is a missing key, not `undefined`. */
const without = (d: Detail, ...keys: (keyof Detail)[]): Detail => {
  const copy = { ...d };
  for (const key of keys) delete copy[key];
  return copy;
};

const detail = (patch: Partial<Detail> = {}): Detail => ({
  symbol: "BTCUSDT",
  category: "linear",
  tick_size: "0.1",
  qty_step: "0.001",
  status: "Trading",
  ...patch,
});
const ok = (patch: Partial<Detail> = {}): DetailOutcome => ({ kind: "ok", detail: detail(patch) });

describe("contractPhase", () => {
  it("is 'Checking Bybit' before an answer and the ladder's sentence while it waits", () => {
    expect(contractPhase("BTCUSDT", null)).toEqual({
      kind: "loading",
      text: "Checking Bybit for BTCUSDT…",
      waitS: null,
    });
    expect(contractPhase("BTCUSDT", null, 4)).toMatchObject({
      text: "CandleViewer's server is loading the instrument list from Bybit — next try in 4 s.",
    });
  });

  it("words a failure by cause, with the order line and the reference only when sent", () => {
    expect(contractPhase("BTCUSDT", { kind: "failed", failure: { cause: "network" } })).toEqual({
      kind: "failed",
      heading: "Couldn't load BTCUSDT's contract rules.",
      cause: "CandleViewer can't reach its server.",
      orderLine: "CandleViewer can't check BTCUSDT orders against these rules until they load.",
      reference: null,
    });
    expect(
      contractPhase("BTCUSDT", {
        kind: "failed",
        failure: { cause: "unavailable", instance: null },
      }),
    ).toMatchObject({
      cause: "The server still has no list from Bybit after a minute.",
    });
    expect(
      contractPhase("BTCUSDT", {
        kind: "failed",
        failure: { cause: "http", status: 500, instance: "urn:cv:req:9" },
      }),
    ).toMatchObject({
      cause: "CandleViewer's server answered 500.",
      reference: "Ref urn:cv:req:9",
    });
  });

  it("words 404 and 403", () => {
    expect(contractPhase("BTCUSDT", { kind: "not_listed", retryAtMs: 60 })).toEqual({
      kind: "not_listed",
      text: "BTCUSDT isn't in Bybit's instrument list as CandleViewer last read it.",
      retryAtMs: 60,
    });
    expect(contractPhase("BTCUSDT", { kind: "forbidden" })).toEqual({
      kind: "forbidden",
      text: "Your role can't see instruments.",
    });
    expect(contractPhase("BTCUSDT", ok())).toEqual({ kind: "ready" });
  });
});

describe("notTradingView", () => {
  it("is null while trading", () => {
    expect(notTradingView(detail())).toBeNull();
  });

  it("uses the server's status_reason verbatim, else the deck's fallback", () => {
    expect(
      notTradingView(detail({ status: "Closed", status_reason: "Delisted on 2026-10-01." })),
    ).toMatchObject({
      heading: "BTCUSDT is not trading on Bybit.",
      reason: "Delisted on 2026-10-01.",
      delisted: true,
    });
    expect(notTradingView(detail({ status: "Closed", status_reason: "  " }))?.reason).toBe(
      "Status: Closed.",
    );
    expect(notTradingView(detail({ status: "Delivering" }))).toMatchObject({
      reason: "Status: Delivering.",
      delisted: true,
    });
  });

  it("words PreLaunch apart and does not mark it delisted", () => {
    expect(notTradingView(detail({ status: "PreLaunch" }))).toMatchObject({
      heading: "BTCUSDT is not open for trading in CandleViewer — pre-launch on Bybit.",
      reason: "Not trading yet — status: Pre-launch.",
      delisted: false,
      liveReplacement: "No live trading data — BTCUSDT is not trading.",
      noFunding: "No funding — BTCUSDT is not trading.",
      coverageSentence: "Recorded coverage isn't available for symbols that aren't trading.",
    });
  });

  it("reads an unknown status as not trading, with no invented reason", () => {
    expect(notTradingView(detail({ status: "Settling" as "Closed" }))).toMatchObject({
      heading: "BTCUSDT is not trading on Bybit.",
      reason: null,
      delisted: false,
    });
    expect(notTradingView(without(detail(), "status"))).not.toBeNull();
  });
});

describe("coverage (§11.3)", () => {
  it("asks only for a Trading symbol", () => {
    expect(coverageGate(ok())).toEqual({ kind: "ask" });
    expect(coverageGate(ok({ status: "Closed" }))).toEqual({
      kind: "not_trading",
      text: "Recorded coverage isn't available for symbols that aren't trading.",
    });
    expect(coverageGate({ kind: "not_listed", retryAtMs: 0 }).kind).toBe("not_trading");
  });

  it("waits for the instrument list while there is no status yet", () => {
    for (const contract of [
      null,
      { kind: "forbidden" } as const,
      { kind: "failed", failure: { cause: "network" } } as const,
    ]) {
      expect(coverageGate(contract)).toEqual({
        kind: "waits",
        text: "Recorded coverage waits for the instrument list.",
      });
    }
  });

  it("reads a 422 by the contract band: failed for Trading, the not-trading line otherwise", () => {
    expect(coverageState(ok(), { kind: "refused_422" })).toEqual({
      kind: "failed",
      text: "Couldn't load recorded coverage.",
      retry: true,
    });
    expect(coverageState(ok({ status: "Closed" }), { kind: "refused_422" })).toMatchObject({
      kind: "not_trading",
    });
    expect(coverageState(ok(), null)).toBeNull();
    expect(coverageState(ok(), { kind: "failed", status: null })).toMatchObject({ kind: "failed" });
    expect(coverageState(ok(), { kind: "forbidden" })).toEqual({
      kind: "forbidden",
      text: "Your role can't see instruments.",
    });
    expect(coverageState(null, null)).toMatchObject({ kind: "waits" });
  });
});

const NOW = Date.parse("2026-11-01T06:35:53Z");
const live = (patch: Partial<LiveInput> = {}): LiveInput => ({
  symbol: "BTCUSDT",
  trading: true,
  subscriptionLimit: false,
  disconnected: false,
  feedDown: false,
  hasItem: true,
  lastDataMs: NOW - 1_000,
  nowMs: NOW,
  serverStale: null,
  itemStale: false,
  bootstrapOnly: false,
  ...patch,
});

describe("liveState", () => {
  it("is live under 5 s, with nothing to announce", () => {
    expect(liveState(live())).toEqual({ kind: "live", announce: null });
  });

  it("is stale T1 at 5 s with the marker, the last update and a polite sentence", () => {
    expect(liveState(live({ lastDataMs: NOW - 7_000 }))).toEqual({
      kind: "stale_t1",
      marker: "Stale 7s",
      lastUpdate: "Last update 06:35:46 UTC",
      announce: "Live values stale.",
    });
    expect(liveState(live({ lastDataMs: NOW - 4_999 })).kind).toBe("live");
    expect(liveState(live({ lastDataMs: NOW - 5_000 })).kind).toBe("stale_t1");
    expect(liveState(live({ itemStale: true })).kind).toBe("stale_t1");
  });

  it("is stale T2 at 15 s, its assertive sentence the shell's, not repeated here", () => {
    expect(liveState(live({ lastDataMs: NOW - 15_000 }))).toMatchObject({
      kind: "stale_t2",
      marker: "Stale 15 s — new orders blocked on BTCUSDT",
      announce: null,
    });
    expect(
      liveState(
        live({
          lastDataMs: NOW - 2_000,
          serverStale: { sinceMs: Date.parse("2026-11-01T14:02:11Z") },
        }),
      ),
    ).toMatchObject({
      kind: "stale_t2",
      marker: "Stale (server) — since 14:02:11",
    });
  });

  it("keeps a bootstrap-only band at T1 for ever: never T2, never live again", () => {
    expect(liveState(live({ bootstrapOnly: true, lastDataMs: NOW - 120_000 })).kind).toBe(
      "stale_t1",
    );
    expect(
      liveState(
        live({ bootstrapOnly: true, lastDataMs: NOW - 6_000, serverStale: { sinceMs: null } }),
      ).kind,
    ).toBe("stale_t1");
  });

  it("labels the exchange feed down", () => {
    expect(liveState(live({ feedDown: true }))).toMatchObject({
      kind: "feed_down",
      marker: "Stale — exchange feed down",
    });
  });

  it("ranks not trading over live unavailable over disconnected over stale", () => {
    const stale = { lastDataMs: NOW - 30_000, feedDown: true };
    expect(
      liveState(live({ ...stale, disconnected: true, subscriptionLimit: true, trading: false }))
        .kind,
    ).toBe("not_trading");
    expect(liveState(live({ ...stale, disconnected: true, subscriptionLimit: true })).kind).toBe(
      "live_unavailable",
    );
    expect(liveState(live({ ...stale, disconnected: true }))).toEqual({
      kind: "disconnected",
      text: "Disconnected — last data 06:35",
    });
    expect(liveState(live(stale)).kind).toBe("feed_down");
  });

  it("words live unavailable (the 40-symbol limit)", () => {
    expect(liveState(live({ subscriptionLimit: true }))).toEqual({
      kind: "live_unavailable",
      lines: [
        "Live values unavailable — CandleViewer has reached its live-data limit.",
        "Close a chart or a watchlist symbol, then try again.",
      ],
    });
  });

  it("awaits the first tick, saying so only after 5 s", () => {
    expect(liveState(live({ hasItem: false, lastDataMs: null }))).toEqual({
      kind: "awaiting",
      text: null,
    });
    expect(liveState(live({ hasItem: false, lastDataMs: NOW - 6_000 }))).toEqual({
      kind: "awaiting",
      text: "No live values yet",
    });
  });

  it("words not trading and a disconnect with no data", () => {
    expect(liveState(live({ trading: false }))).toEqual({
      kind: "not_trading",
      text: "No live trading data — BTCUSDT is not trading.",
    });
    expect(liveState(live({ disconnected: true, lastDataMs: null }))).toMatchObject({
      text: "Disconnected — last data —",
    });
  });
});

describe("liveTransition", () => {
  it("announces stale on entry, current on exit, and nothing between stale kinds", () => {
    const t1 = liveState(live({ lastDataMs: NOW - 7_000 }));
    const t2 = liveState(live({ lastDataMs: NOW - 20_000 }));
    const current = liveState(live());
    expect(liveTransition("live", t1)).toBe("Live values stale.");
    expect(liveTransition("stale_t1", t1)).toBeNull();
    expect(liveTransition("stale_t1", t2)).toBeNull();
    expect(liveTransition("live", t2)).toBeNull();
    expect(liveTransition("stale_t1", current)).toBe("Live values current.");
    expect(liveTransition("stale_t2", current)).toBe("Live values current.");
    expect(liveTransition(null, current)).toBeNull();
  });
});
