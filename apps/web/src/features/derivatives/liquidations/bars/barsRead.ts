// E24-S06 (#781) slice 1: the bars read, `GET /api/v1/market/metrics` with `metric=liquidation_notional` (BQ-3: the
// 24 §7.2 name, never the `liquidation_intensity` alias), one request per side because `params` is one object per
// metric code: `{"liquidation_notional":{"side":"long"}}`. `bar_type=time` and `param` the chart's interval code, so
// the grid is the price chart's own (the ticket). Contract: `22` `getMetrics` as #5341 declares it (head 021c79460,
// not on `main`; `MetricCode` and `Settings.deriv` are not in the generated types yet, so the shapes below are the
// declared ones, checked at the boundary). A point is `{t, v}`: `v` an exact decimal string, or `null`; a bar with no
// prints reads "0". Anything else is counted as malformed and read as unknown, never as 0.
// TODO(#723): `min_notional_usd` is not a `liquidation_notional` param yet (G-row on E24-T04, BQ-1). It is sent only
// when the caller says the server applies it (`BARS_FILTER_SERVER_SIDE`, false until then).
import { apiFetch } from "../../../../lib/http/csrfFetch";
import { DEADLINE_MS } from "../historyRead";
import { asNotional, isZero, type SidePoints } from "./model";
import type { LiqHistoryClock } from "../history";

export const METRIC = "liquidation_notional";
export const UNIT = "notional";
/** BQ-1: false until #723 adds `min_notional_usd` to `liquidation_notional`; the legend reads it too. */
export const BARS_FILTER_SERVER_SIDE: boolean = false;

export type BarSide = "long" | "short";

export interface BarsRequest {
  readonly symbol: string;
  /** `22`'s `bar_type=time` `param`: "1" … "720", "D", "W". */
  readonly param: string;
  readonly fromMs: number;
  readonly toMs: number;
  readonly minNotionalUsd: string;
  /** Send `minNotionalUsd` to the server (`BARS_FILTER_SERVER_SIDE`); otherwise the bars read unfiltered. */
  readonly serverThreshold: boolean;
  readonly signal: AbortSignal;
  readonly clock?: LiqHistoryClock | undefined;
}

export type BarsRead =
  | {
      readonly kind: "ok";
      readonly long: SidePoints;
      readonly short: SidePoints;
      readonly malformed: number;
    }
  | {
      readonly kind: "failed";
      /** `null`: no answer (network, deadline, unreadable body). */
      readonly status: number | null;
      readonly code: string | null;
      /** The problem's `detail` (e.g. #5341's 422 "not computed by this server yet: …"), or `null`. */
      readonly detail: string | null;
    };

const SYSTEM: LiqHistoryClock = {
  setTimeout: (run, ms) => setTimeout(run, ms),
  // `id` is what this clock's `setTimeout` returned; the cast only restores that type.
  clearTimeout: (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
};

const get = (v: unknown, key: string): unknown =>
  typeof v === "object" && v !== null ? Reflect.get(v, key) : undefined;

export function metricsPath(req: Omit<BarsRequest, "signal" | "clock">, side: BarSide): string {
  const entry: Record<string, string> = { side };
  if (req.serverThreshold && !isZero(req.minNotionalUsd)) {
    entry["min_notional_usd"] = req.minNotionalUsd;
  }
  const q = new URLSearchParams({
    symbol: req.symbol,
    metric: METRIC,
    bar_type: "time",
    param: req.param,
    from: new Date(req.fromMs).toISOString(),
    to: new Date(req.toMs).toISOString(),
    params: JSON.stringify({ [METRIC]: entry }),
  });
  return `/api/v1/market/metrics?${q.toString()}`;
}

type SideRead =
  | { readonly kind: "ok"; readonly points: Map<number, string | null>; readonly malformed: number }
  | Extract<BarsRead, { kind: "failed" }>;

const bad = (status: number): SideRead => ({
  kind: "failed",
  status,
  code: "malformed",
  detail: null,
});

/** The one `liquidation_notional` series of a response for `side`, or a failure. */
export function parseSide(body: unknown, side: BarSide): SideRead {
  const series = get(body, "series");
  const mine = Array.isArray(series)
    ? series.filter((s: unknown) => get(s, "metric") === METRIC)
    : [];
  const only: unknown = mine[0];
  const points = get(only, "points");
  // the echoed params and unit are checked: a series for the wrong side or unit would be drawn as the right one
  if (mine.length !== 1 || !Array.isArray(points)) return bad(200);
  if (get(get(only, "params"), "side") !== side || get(only, "unit") !== UNIT) return bad(200);
  const out = new Map<number, string | null>();
  let malformed = 0;
  for (const p of points) {
    const t = get(p, "t");
    const ms = typeof t === "string" ? Date.parse(t) : NaN;
    if (!Number.isFinite(ms) || out.has(ms)) {
      malformed += 1;
      continue;
    }
    const v = get(p, "v");
    const value = asNotional(v);
    if (value === null && v !== null) malformed += 1;
    out.set(ms, value);
  }
  return { kind: "ok", points: out, malformed };
}

async function readSide(
  req: BarsRequest,
  side: BarSide,
  clock: LiqHistoryClock,
): Promise<SideRead> {
  const call = new AbortController();
  const end = (): void => call.abort();
  const deadline = clock.setTimeout(end, DEADLINE_MS);
  req.signal.addEventListener("abort", end);
  try {
    if (req.signal.aborted) return { kind: "failed", status: null, code: null, detail: null };
    const res = await apiFetch(metricsPath(req, side), { method: "GET", signal: call.signal });
    const body: unknown = await res.json().catch(() => null);
    if (res.status !== 200) {
      const code = get(body, "code");
      const detail = get(body, "detail");
      return {
        kind: "failed",
        status: res.status,
        code: typeof code === "string" ? code : null,
        detail: typeof detail === "string" ? detail : null,
      };
    }
    return parseSide(body, side);
  } catch {
    return { kind: "failed", status: null, code: null, detail: null };
  } finally {
    clock.clearTimeout(deadline);
    req.signal.removeEventListener("abort", end);
  }
}

/** Both sides, or the first failure: half a pair would draw one side as zero. */
export async function fetchLiquidationBars(req: BarsRequest): Promise<BarsRead> {
  const clock = req.clock ?? SYSTEM;
  const [long, short] = await Promise.all([
    readSide(req, "long", clock),
    readSide(req, "short", clock),
  ]);
  if (long.kind === "failed") return long;
  if (short.kind === "failed") return short;
  return {
    kind: "ok",
    long: long.points,
    short: short.points,
    malformed: long.malformed + short.malformed,
  };
}
