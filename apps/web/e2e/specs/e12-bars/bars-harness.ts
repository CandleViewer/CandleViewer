import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, type Page } from "@playwright/test";
import type { generated } from "@candleviewer/protocol";
import { json, stubSession } from "../../support/api";
import { seriousAxe } from "../../support/axe";
import { startWsHarness, type WsHarness } from "../../support/wsHarness";
import { ChartProbe } from "./chart-probe";

// E12-Q03 (#419): the fixture-backed backend the e12-bars specs share. `/market/klines` and
// `/market/bars` are answered from the E12-Q02 conformance goldens (synthetic, public market-data
// shape, no account field), every other host is refused, and the page clock runs from the real time.

type Schemas = generated.rest.components["schemas"];
type Bar = Schemas["Bar"];
type KlineResponse = Schemas["KlineResponse"];

export const patient = expect.configure({ timeout: 15_000 });

const here = path.dirname(fileURLToPath(import.meta.url));
const GOLDENS = path.resolve(
  here,
  "../../../../../packages/fixtures/golden/bars/conformance/goldens",
);

/** The route a chart panel opens on. PROPOSED (BQ-1): the first route that mounts a chart panel. */
export const CHART_ROUTE = "/terminal";

/** Tapes in the conformance bank (`MANIFEST.toml`); `-gap` holds a recording gap. */
export type Tape = "btcusdt-2026-09-01" | "btcusdt-2026-09-02-gap";

/** One golden row: every value is a string (quoted ones JSON-encoded, e.g. `symbol`). */
type GoldenRow = Readonly<Record<string, string>>;

const iso = (us: string | undefined): string =>
  new Date(Math.floor(Number(us ?? "0") / 1_000)).toISOString();

/** The golden bars of `pair` (e.g. `time:1`, `tick:1000`) on `tape`, as `Bar`s. */
export function goldenBars(tape: Tape, pair: string): Bar[] {
  const file = path.join(GOLDENS, tape, `${pair.replace(":", "-")}.jsonl`);
  return readFileSync(file, "utf8")
    .split("\n")
    .filter((line) => line.trim() !== "")
    .map((line) => toBar(JSON.parse(line) as GoldenRow));
}

function toBar(r: GoldenRow): Bar {
  return {
    index: Number(r["index"]),
    t: iso(r["open_time"]),
    close_time: iso(r["close_time"]),
    o: r["open"] ?? "",
    h: r["high"] ?? "",
    l: r["low"] ?? "",
    c: r["close"] ?? "",
    v: r["volume"] ?? "",
    turnover: r["turnover"] ?? "",
    trades: Number(r["trade_count"]),
    confirm: r["closed"] === "true",
    gap_before: r["gap_before"] === "true",
    partial: r["partial"] === "true",
    tape_gap: false,
    delta: r["delta"] ?? "",
    min_delta: r["min_delta"] ?? "",
    max_delta: r["max_delta"] ?? "",
  };
}

export interface Served {
  readonly symbol: string;
  readonly bars: readonly Bar[];
  /** `meta.recording_started_at`; default the first bar's open time. */
  readonly recordingStartedAt?: string;
  /** Answer every market read with this status and problem `code` instead. */
  readonly fail?: { readonly status: 422 | 503; readonly code: string };
}

/** One page holding every bar: the specs assert plumbing, not paging (E12-Q02 owns values). */
export function klineResponse(served: Served): KlineResponse {
  const first = served.bars[0];
  return {
    symbol: served.symbol,
    bars: [...served.bars],
    meta: {
      next_cursor: null,
      has_more: false,
      count: served.bars.length,
      sources: ["tape"],
      recording_started_at: served.recordingStartedAt ?? first?.t ?? null,
      generated_at: new Date().toISOString(),
      stale_build: false,
    },
  };
}

export interface Backend {
  readonly harness: WsHarness;
  /** Every `/market/klines` or `/market/bars` request, in order. */
  readonly marketReads: readonly string[];
  /** Requests to any host but the preview server, which were refused. */
  readonly refused: readonly string[];
  serve(served: Served): void;
}

const MARKET = /\/api\/v1\/market\/(klines|bars)(\?|$)/u;

/**
 * Signs an owner in on stubs, starts the fixture WS gateway, refuses every off-host request and
 * answers the market reads from `served`. Call before `goto`.
 */
export async function fixtureBackend(page: Page, served: Served): Promise<Backend> {
  let current = served;
  const marketReads: string[] = [];
  const refused: string[] = [];
  await page.route(
    (url) => url.hostname !== "127.0.0.1",
    (route) => {
      refused.push(route.request().url());
      return route.abort("blockedbyclient");
    },
  );
  await stubSession(page, { role: "owner" });
  const harness = await startWsHarness(page);
  await page.route(MARKET, (route) => {
    marketReads.push(route.request().url());
    const { fail } = current;
    if (fail !== undefined) {
      return route.fulfill(json({ status: fail.status, code: fail.code }, fail.status));
    }
    return route.fulfill(json(klineResponse(current)));
  });
  return {
    harness,
    marketReads,
    refused,
    serve: (next) => void (current = next),
  };
}

/**
 * The page clock from the real time: the shared worker checks the access token against the wall
 * clock, so a fixed past epoch fails its auth. Call before `goto`.
 */
export async function realTimeClock(page: Page): Promise<void> {
  await page.clock.install();
}

/** Serious and critical axe findings, with the clock running: axe schedules with `setTimeout(0)`. */
export async function axeFindings(page: Page): Promise<string[]> {
  await page.clock.resume();
  return seriousAxe(page);
}

export interface Opened {
  readonly probe: ChartProbe;
  readonly backend: Backend;
}

/** Opens the chart route on `served` with the real-time clock; waits for the panel. */
export async function openChart(page: Page, title: string, served: Served): Promise<Opened> {
  await realTimeClock(page);
  const backend = await fixtureBackend(page, served);
  await page.goto(CHART_ROUTE);
  const probe = new ChartProbe(page, title);
  await patient(probe.panel).toBeVisible();
  return { probe, backend };
}
