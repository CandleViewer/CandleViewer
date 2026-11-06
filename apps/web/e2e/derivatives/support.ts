// E24-Q02 (#772): the SCR-054 derivatives specs' harness. The REAL web client runs on the shipped bundle against the
// E08-Q05 fake gateway (`support/wsHarness.ts`) and stubbed REST reads; nothing reaches a backend or an exchange
// (C-13.5). Every value comes from a fixture in `packages/fixtures`, never invented:
// - OI history: `bybit/2026-10-05/rest/open_interest_BTCUSDT_5min_page{0,1}.json` (documented shape, exception
//   #1778 A), mapped to `22` `OpenInterestPoint` as the E24-S01 unit tests map it (#5769 at d1bf47b29);
// - live OI: `ws/recorded_tickers_BTCUSDT.jsonl` (recorded), the `openInterest` pair of each message;
// - the per-bar delta and quadrant: the E24-T06 goldens `golden/derivatives/expected_<case>.json.gz` (the engine's
//   output over the same corpus), served as `/market/metrics` series;
// - liquidations: `ws/allLiquidation_BTCUSDT_burst.jsonl` (#5273 at 9bf4ec8c2, documented shape), mapped to `23`
//   §14.9 items, the notional computed exactly from `v × p`.
// Declared transforms, each keeping relative timing (a `Timeline`, computed per test from the real time):
// 1. the recorded ticker moves by whole 15 min steps, so it begins at `nowMs`;
// 2. the REST and golden times move together by whole 15 min steps, so the golden's last bar ends where the live bar
//    begins; REST rows that would then end after `nowMs` are not served;
// 3. the liquidation burst moves so its last print lands one second before `nowMs`;
// 4. `noSampleCase` also drops the REST rows inside the stale-open golden's null bar, so that bar holds no OI sample.
// Time is Playwright's page clock, started from the real time (the socket's shared worker, which `page.clock` does
// not reach, judges the access token by the real time, as `support/contexts.ts` and `auth/session.spec.ts` note) and
// paused at `nowMs`; a spec moves it with `runFor` or `settle`, never waits on wall time.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { gunzipSync } from "node:zlib";
import { expect, test, type Locator, type Page, type Route } from "@playwright/test";
import { json, stubSession } from "../support/api";
import { startWsHarness, type WsHarness } from "../support/wsHarness";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../../../..");
const CAPTURE = join(ROOT, "packages/fixtures/bybit/2026-10-05");
const GOLDEN = join(ROOT, "packages/fixtures/golden/derivatives");
export const SYMBOL = "BTCUSDT";
const STEP_MS = 15 * 60_000;
const FIVE_MIN_MS = 5 * 60_000;

/** `expect` bounded by the 30 s test timeout; no test reads a duration from it (as `e17/support.ts`). */
export const patient = expect.configure({ timeout: 25_000 });

/** What a test automates, as the E24-Q01 plan numbers it (#5787 / #5788): the run slice maps these. */
export function covers(...ids: string[]): void {
  test.info().annotations.push({ type: "covers", description: ids.join("; ") });
}

// --- fixtures ------------------------------------------------------------------------------------------------------

const lines = (path: string): unknown[] =>
  readFileSync(path, "utf8")
    .split("\n")
    .filter((l) => l.trim() !== "")
    .map((l) => JSON.parse(l) as unknown);

interface LiveOi {
  readonly tsMs: number;
  readonly openInterest: string;
  readonly openInterestValue: string;
}

/** The recorded ticker stream folded into merged state, one entry per message that carries both OI fields. */
export function recordedLiveOi(): LiveOi[] {
  const merged: Record<string, string> = {};
  const out: LiveOi[] = [];
  for (const raw of lines(join(CAPTURE, "ws/recorded_tickers_BTCUSDT.jsonl"))) {
    const msg = raw as { ts: number; data: Record<string, string> };
    Object.assign(merged, msg.data);
    const oi = merged["openInterest"];
    const value = merged["openInterestValue"];
    if (oi !== undefined && value !== undefined)
      out.push({ tsMs: msg.ts, openInterest: oi, openInterestValue: value });
  }
  return out;
}

const LIVE = recordedLiveOi();
/** The recorded ticker's first OI message; `nowMs` keeps its phase within a 15 min bar. */
const LIVE_EPOCH_MS = LIVE[0]?.tsMs ?? 0;

interface RestRow {
  readonly openInterest: string;
  readonly timestamp: string;
}

const restRows = (): RestRow[] =>
  [0, 1].flatMap((n) => {
    const path = join(CAPTURE, `rest/open_interest_BTCUSDT_5min_page${String(n)}.json`);
    return (JSON.parse(readFileSync(path, "utf8")) as { result: { list: RestRow[] } }).result.list;
  });

/** How far past the real time `nowMs` lies at least, so `pauseAt` always moves the page clock forward. */
const MARGIN_MS = 60_000;

/** One test's times. Built before the page opens; `openDerivatives` pauses the page clock at `nowMs`. */
export interface Timeline {
  /** The first instant at least `MARGIN_MS` after the real time whose 15 min phase is the recorded ticker's. */
  readonly nowMs: number;
  /** Transform 1: whole 15 min steps that move the recorded ticker to begin at `nowMs`. */
  readonly liveShiftMs: number;
  /** Transform 2, the REST and golden transform: whole 15 min steps; the golden's last bar ends at the live bar. */
  readonly shiftMs: number;
}

/** The test's `Timeline`, from the real time, so the fixtures keep their relative timing at any time of day. */
export function timeline(realMs: number = Date.now()): Timeline {
  const liveShiftMs = Math.ceil((realMs + MARGIN_MS - LIVE_EPOCH_MS) / STEP_MS) * STEP_MS;
  const nowMs = LIVE_EPOCH_MS + liveShiftMs;
  const goldenEnd = Math.max(...goldenCase("btc_8h_15m").bars.map((b) => b.start_ms)) + STEP_MS;
  return { nowMs, liveShiftMs, shiftMs: Math.floor((nowMs - goldenEnd) / STEP_MS) * STEP_MS };
}

export interface OiPoint {
  readonly t: string;
  readonly open_interest: string;
  readonly open_interest_value: null;
  readonly interval: "5min";
  readonly source: "rest";
}

/**
 * The REST rows as `22` points, ascending and shifted, without those in any `[from, to)` drop (unshifted ms) and
 * without those whose 5 min span would end after `nowMs`.
 */
export function oiHistory(
  t: Timeline,
  drops: readonly (readonly [number, number])[] = [],
): OiPoint[] {
  return restRows()
    .map((r) => ({ ms: Number(r.timestamp), oi: r.openInterest }))
    .filter(({ ms }) => !drops.some(([from, to]) => ms >= from && ms < to))
    .filter(({ ms }) => ms + t.shiftMs + FIVE_MIN_MS <= t.nowMs)
    .sort((a, b) => a.ms - b.ms)
    .map(({ ms, oi }) => ({
      t: new Date(ms + t.shiftMs).toISOString(),
      open_interest: oi,
      open_interest_value: null,
      interval: "5min",
      source: "rest",
    }));
}

export interface GoldenBar {
  readonly start_ms: number;
  readonly open_interest_delta: string | null;
  readonly oi_price_quadrant: string | null;
}

interface GoldenCase {
  readonly id: string;
  readonly bars: { readonly minutes?: number };
  readonly drops: readonly {
    readonly stream: string;
    readonly from_ms: number;
    readonly to_ms: number;
  }[];
}

/** A T06 case: its 15 min bars as the engine computed them, and the OI drops its loader applied (unshifted). */
export function goldenCase(id: "btc_8h_15m" | "btc_8h_15m_stale_open"): {
  bars: GoldenBar[];
  drops: [number, number][];
} {
  const manifest = JSON.parse(readFileSync(join(GOLDEN, "cases.json"), "utf8")) as {
    cases: GoldenCase[];
  };
  const entry = manifest.cases.find((c) => c.id === id);
  if (entry?.bars.minutes !== 15) throw new Error(`${id}: not a 15 min golden case`);
  const bars = JSON.parse(
    gunzipSync(readFileSync(join(GOLDEN, `expected_${id}.json.gz`))).toString("utf8"),
  ) as GoldenBar[];
  const drops = entry.drops
    .filter((d) => d.stream === "oi")
    .map((d): [number, number] => [d.from_ms, d.to_ms]);
  return { bars, drops };
}

/**
 * The stale-open case with transform 4: its loader's drops plus every REST row inside its one null bar, so that bar
 * holds no OI sample and the client names it `no_sample`, not a stale `unclassified` (#5773 `buildOiBars`).
 */
export function noSampleCase(): { bars: GoldenBar[]; drops: [number, number][] } {
  const { bars, drops } = goldenCase("btc_8h_15m_stale_open");
  const empty = bars.filter((b) => b.open_interest_delta === null);
  if (empty.length !== 1) throw new Error(`expected one null bar, found ${String(empty.length)}`);
  const start = empty[0]?.start_ms ?? 0;
  return { bars, drops: [...drops, [start, start + STEP_MS]] };
}

/** Exact decimal product of two non-negative decimal strings (`v × p`), never a float. */
export function times(a: string, b: string): string {
  const [ai = "0", af = ""] = a.split(".");
  const [bi = "0", bf = ""] = b.split(".");
  const scale = af.length + bf.length;
  const digits = (BigInt(ai + af) * BigInt(bi + bf)).toString().padStart(scale + 1, "0");
  return scale === 0 ? digits : `${digits.slice(0, -scale)}.${digits.slice(-scale)}`;
}

/** Exact sum of non-negative decimal strings, at the widest scale among them. */
export function sum(values: readonly string[]): string {
  const scale = Math.max(0, ...values.map((v) => (v.split(".")[1] ?? "").length));
  const total = values.reduce((acc, v) => {
    const [i = "0", f = ""] = v.split(".");
    return acc + BigInt(i + f.padEnd(scale, "0"));
  }, 0n);
  const digits = total.toString().padStart(scale + 1, "0");
  return scale === 0 ? digits : `${digits.slice(0, -scale)}.${digits.slice(-scale)}`;
}

export interface LiqItem {
  readonly symbol: string;
  readonly ts_ms: number;
  readonly side: "buy" | "sell";
  readonly price: string;
  readonly size: string;
  readonly notional_usd: string;
  readonly cluster_size: number;
}

type BybitLiq = { T: number; s: string; S: string; v: string; p: string };
/**
 * #5273's burst, one array of `23` §14.9 items per Bybit push. Transform 3: the last print lands one second before
 * `nowMs`. Read on use, so the OI specs never depend on it. A `Sell` print is a long liquidated.
 */
export function liquidationPushes(t: Timeline): LiqItem[][] {
  const burst = lines(join(CAPTURE, "ws/allLiquidation_BTCUSDT_burst.jsonl")).map(
    (raw) => (raw as { data: BybitLiq[] }).data,
  );
  const shift = t.nowMs - 1_000 - Math.max(...burst.flat().map((d) => d.T));
  return burst.map((push) =>
    push.map((d): LiqItem => ({
      symbol: d.s,
      ts_ms: d.T + shift,
      side: d.S === "Sell" ? "sell" : "buy",
      price: d.p,
      size: d.v,
      notional_usd: times(d.v, d.p),
      cluster_size: 1,
    })),
  );
}

/** `23` §14.9's snapshot note, as the gateway sends it on the first frame. */
const LIQ_NOTE =
  "Bybit batches at most one allLiquidation push per symbol per 500 ms; counts are lower bounds.";

// --- the stubbed backend -------------------------------------------------------------------------------------------

export interface Coverage {
  readonly first_available_ts: string | null;
  readonly covered_from: string | null;
  readonly covered_to: string | null;
  readonly no_coverage: boolean;
}

export interface Backend {
  /** The test's times: every fixture below is shifted by it, and the page clock pauses at its `nowMs`. */
  readonly timeline: Timeline;
  /** Status of `/market/open-interest` answers: 200 serves `oi`, anything else a problem body. */
  oiStatus: number;
  oi: OiPoint[];
  /** The 15 min bars `/market/metrics` serves for `open_interest_delta` and `oi_price_quadrant`. */
  bars: GoldenBar[];
  liqStatus: number;
  liqItems: LiqItem[];
  liqCoverage: Coverage;
  /** `liquidation_notional` per side: `[bar start ms, value]`, `"0"` for a bar without prints (`22` getMetrics). */
  liqBars: { long: [number, string][]; short: [number, string][] };
  readonly calls: string[];
}

const iso = (ms: number): string => new Date(ms).toISOString();
const within = (url: URL, ms: number): boolean => {
  const from = url.searchParams.get("from");
  const to = url.searchParams.get("to");
  return (from === null || ms >= Date.parse(from)) && (to === null || ms < Date.parse(to));
};
const problem = (status: number) =>
  json({ type: "about:blank", title: "Service Unavailable", status }, status, {
    "content-type": "application/problem+json",
  });

/** Answers the three derivatives reads the stacks make, from `backend` as it is when each read arrives. */
async function routeMarket(page: Page, backend: Backend): Promise<void> {
  await page.route("**/api/v1/market/open-interest?*", (r: Route) => {
    const url = new URL(r.request().url());
    backend.calls.push("open-interest");
    if (backend.oiStatus !== 200) return r.fulfill(problem(backend.oiStatus));
    const items = backend.oi.filter((p) => within(url, Date.parse(p.t)));
    return r.fulfill(
      json({
        symbol: SYMBOL,
        items,
        meta: {
          count: items.length,
          has_more: false,
          next_cursor: null,
          coverage: {
            from: items[0]?.t ?? null,
            to: items.at(-1)?.t ?? null,
            native_interval: "5min",
            source: "rest",
            gaps: [],
          },
        },
      }),
    );
  });
  await page.route("**/api/v1/market/liquidations?*", (r: Route) => {
    const url = new URL(r.request().url());
    backend.calls.push("liquidations");
    if (backend.liqStatus !== 200) return r.fulfill(problem(backend.liqStatus));
    const items = backend.liqItems
      .filter((i) => within(url, i.ts_ms))
      .map(({ ts_ms, ...rest }) => ({ ...rest, ts: iso(ts_ms) }));
    return r.fulfill(
      json({
        items,
        meta: {
          count: items.length,
          has_more: false,
          next_cursor: null,
          coverage: backend.liqCoverage,
        },
      }),
    );
  });
  await page.route("**/api/v1/market/metrics?*", (r: Route) => {
    const url = new URL(r.request().url());
    const metric = url.searchParams.get("metric") ?? "";
    backend.calls.push(`metrics:${metric}`);
    const shift = backend.timeline.shiftMs;
    const shifted = backend.bars.map((b) => ({ ...b, start_ms: b.start_ms + shift }));
    let unit = "qty";
    let points: { t: string; v: string | null }[] = [];
    let params: Record<string, unknown> = {};
    if (metric === "open_interest_delta" || metric === "oi_price_quadrant") {
      unit = metric === "oi_price_quadrant" ? "enum" : "qty";
      points = shifted
        .filter((b) => within(url, b.start_ms))
        .map((b) => ({
          t: iso(b.start_ms),
          v: metric === "oi_price_quadrant" ? b.oi_price_quadrant : b.open_interest_delta,
        }));
    } else if (metric === "liquidation_notional") {
      const asked = JSON.parse(url.searchParams.get("params") ?? "{}") as Record<
        string,
        { side?: string }
      >;
      const side = asked[metric]?.side === "short" ? "short" : "long";
      unit = "notional";
      params = { side };
      points = backend.liqBars[side]
        .filter(([ms]) => within(url, ms))
        .map(([ms, v]) => ({ t: iso(ms), v }));
    } else {
      return r.fulfill(json({ detail: "unknown metric" }, 422));
    }
    return r.fulfill(
      json({
        symbol: SYMBOL,
        bar_type: "time",
        param: url.searchParams.get("param") ?? "15",
        series: [{ metric, estimated: false, params, unit, points }],
        meta: { count: points.length, has_more: false, next_cursor: null, generated_at: iso(0) },
      }),
    );
  });
}

export interface Opened {
  readonly backend: Backend;
  readonly harness: WsHarness;
  /** The next recorded live OI message as a `ticker.BTCUSDT` frame; returns what it sent. */
  sendLiveOi(): LiveOi;
  /** One push of liquidation prints as the next `liquidations.BTCUSDT` frame. */
  sendLiquidations(items: readonly LiqItem[]): void;
}

/** A backend whose every read answers 200 from the fixtures; the spec changes a field before or after it opens. */
export function fixtureBackend(t: Timeline = timeline()): Backend {
  const first = t.nowMs - 34 * 60_000; // D02 §6 `liq-partial`: "Liq 34 min", recording began then
  return {
    timeline: t,
    oiStatus: 200,
    oi: oiHistory(t),
    bars: goldenCase("btc_8h_15m").bars,
    liqStatus: 200,
    liqItems: [],
    liqCoverage: {
      first_available_ts: iso(first),
      covered_from: iso(first),
      covered_to: iso(t.nowMs),
      no_coverage: false,
    },
    liqBars: { long: [], short: [] },
    calls: [],
  };
}

/**
 * Signs in as `role`, starts the fake gateway, stubs the reads and opens the panel. BQ 1 (#772, as amended): no route
 * mounts SCR-054 yet, and this PR waits for the one that does; the route lives here alone, so its landing changes
 * this function only.
 */
export async function openDerivatives(
  page: Page,
  opts: { role?: "owner" | "manager" | "viewer"; backend?: Backend } = {},
): Promise<Opened> {
  const backend = opts.backend ?? fixtureBackend();
  await stubSession(page, { role: opts.role ?? "owner" });
  await routeMarket(page, backend);
  const harness = await startWsHarness(page);
  // started from the real time, then paused (it fakes Date, timers and animation frames): the token the page stamps
  // stays valid for the worker's real-time check, and the coalescers move only with `runFor`
  await page.clock.install();
  await page.clock.pauseAt(backend.timeline.nowMs);
  await page.goto("/terminal");
  await expect.poll(() => harness.authenticated()).toBe(1);
  let next = 0;
  return {
    backend,
    harness,
    sendLiveOi() {
      const live = LIVE[next % LIVE.length] ?? LIVE[0];
      if (live === undefined) throw new Error("no recorded OI message");
      next += 1;
      harness.sendTicker(SYMBOL, {
        open_interest: live.openInterest,
        open_interest_value: live.openInterestValue,
        ts_ms: live.tsMs + backend.timeline.liveShiftMs,
      });
      return live;
    },
    sendLiquidations(items) {
      const ch = `liquidations.${SYMBOL}`;
      const first = !harness.sent.some((f) => f["ch"] === ch);
      harness.sendData(
        ch,
        first ? { liquidations: items, note: LIQ_NOTE } : { liquidations: items },
      );
    },
  };
}

/** Moves the paused page clock `ms` on, firing due timers and frames (the 250 ms buckets, the 1 s publish). */
export async function advance(page: Page, ms: number): Promise<void> {
  await page.clock.runFor(ms);
}

/**
 * Runs the paused clock on 250 ms at a time until `holds` is true. Both feeds publish history, coverage and stream
 * changes only from their animation-frame loop, and a REST answer or a worker-relayed frame lands when it lands: a
 * single `advance` can run before it. Bounded by `patient`'s timeout.
 */
export async function settle(page: Page, holds: () => Promise<boolean>): Promise<void> {
  // a check that throws (say, a table not rendered yet) counts as "not yet", so the clock still moves
  const check = () => holds().catch(() => false);
  await patient
    .poll(async () => {
      if (await check()) return true;
      await page.clock.runFor(250);
      return check();
    })
    .toBe(true);
}

/** `settle` until `target` is visible. */
export async function shown(page: Page, target: Locator): Promise<void> {
  await settle(page, () => target.isVisible());
}

// --- locators: role and accessible name only (BQ 2), names from the stacks' `copy.ts` --------------------------------

/** #5771 at 6954e6ac7 `copy.regionName`: the OI sub-pane's region. */
export const oiPane = (page: Page): Locator =>
  page.getByRole("region", { name: `Open interest, ${SYMBOL}`, exact: true });
/** #5765 at a3380fb26 `copy.regionName`: the liquidation feed's region. */
export const feedPane = (page: Page): Locator =>
  page.getByRole("region", { name: `Liquidations, ${SYMBOL}`, exact: true });
/** #5768 at fabcc2adf `copy.regionName`: the liquidation bars' region. */
export const barsPane = (page: Page): Locator =>
  page.getByRole("region", { name: `Liquidation bars, ${SYMBOL}`, exact: true });

/**
 * E24-D04 A-08: the OI mode toggle is a `switch` named "Open interest, delta per bar", off by default. BQ 3 (#772, as
 * amended): the designed contract, not the shipped shape; the drift is a finding on #5773 / #777 for E24-D06. At
 * 17af9b002 #5773 draws its toggle only when the host passes both `mode` and `onModeChange` (BQ-1 ruling 6618708569).
 */
export const oiModeSwitch = (page: Page): Locator =>
  oiPane(page).getByRole("switch", { name: "Open interest, delta per bar", exact: true });

/** The selector `seriousAxe`'s `include` scopes one pane's scan to: the region's accessible name. */
export const paneScope = (regionName: string): string => `[aria-label="${regionName}"]`;

/** The text of every cell in `column` of `table`, by its header's accessible name. */
export async function columnTexts(table: Locator, column: string): Promise<string[]> {
  const headers = await table.getByRole("columnheader").allInnerTexts();
  const at = headers.findIndex((h) => h.trim().startsWith(column));
  if (at < 0) throw new Error(`no column ${column} in [${headers.join(" | ")}]`);
  const rows = table.getByRole("row");
  const out: string[] = [];
  for (const row of await rows.all()) {
    const cells = row.getByRole("cell");
    if ((await cells.count()) > at) out.push((await cells.nth(at).innerText()).trim());
  }
  return out;
}
