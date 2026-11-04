// E24-S03 (#778): the documented-shape fixtures (exception #1778 A, C-13.5)
// `bybit/2026-10-05/rest/funding_history_*.json` mapped row by row to `22` `getFundingHistory` items, and the
// recorded `recorded_tickers_BTCUSDT.json`'s rate as the `predicted` item. Typed by the generated contract (C-4.16).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { generated } from "@candleviewer/protocol";

type Op = generated.rest.operations["getFundingHistory"];
export type FundingOk = Op["responses"][200]["content"]["application/json"];
export type FundingItem = NonNullable<FundingOk["items"]>[number];
type FundingMeta = NonNullable<FundingOk["meta"]>;
type Coverage = NonNullable<FundingMeta["coverage"]>;
type Problem = Op["responses"][404]["content"]["application/problem+json"];

const CAPTURE = resolve(
  import.meta.dirname,
  "../../../../../../packages/fixtures/bybit/2026-10-05/rest",
);

interface BybitRow {
  readonly fundingRate: string;
  readonly fundingRateTimestamp?: string;
  readonly nextFundingTime?: string;
}

const list = (file: string): readonly BybitRow[] =>
  (JSON.parse(readFileSync(resolve(CAPTURE, file), "utf8")) as { result: { list: BybitRow[] } })
    .result.list;

/** A settled item as the fixtures build it: `t` and `funding_rate` always present. */
export type SettledItem = FundingItem & { readonly t: string; readonly funding_rate: string };

/** The settlements as `22` items, ascending (the venue answers newest first). */
export const recordedSettled = (which: "BTCUSDT_8h" | "ETHUSDT_4h"): SettledItem[] =>
  list(`funding_history_${which}.json`)
    .map((r) => ({
      t: new Date(Number(r.fundingRateTimestamp)).toISOString(),
      funding_rate: r.fundingRate,
      predicted: false,
      estimated: false,
    }))
    .sort((a, b) => Date.parse(a.t) - Date.parse(b.t));

/** The recorded ticker's accruing rate at its next settlement, as the `predicted` item. */
export const predictedItem = (): FundingItem => {
  const [row] = list("recorded_tickers_BTCUSDT.json");
  const t = new Date(Number(row?.nextFundingTime)).toISOString();
  return { t, funding_rate: row?.fundingRate ?? "", predicted: true, estimated: true };
};

export const coverage = (over: Partial<Coverage> = {}): Coverage => ({
  first_available_ts: null,
  covered_from: null,
  covered_to: null,
  no_coverage: false,
  gaps: [],
  ...over,
});

/** A contract-valid `22` page: `meta.count` is the page's item count (`PageMeta`). */
export const page = (
  items: readonly FundingItem[],
  extra: { interval?: number | undefined; meta?: Partial<FundingMeta> } = {},
): FundingOk => ({
  symbol: "BTCUSDT",
  ...(extra.interval === undefined ? {} : { funding_interval_minutes: extra.interval }),
  items: [...items],
  meta: { has_more: false, next_cursor: null, count: items.length, ...extra.meta },
});

/** A `22` problem body (RFC 7807, `Problem`'s required members). */
export const problem = (status: number, code: string): Problem => ({
  type: "about:blank",
  title: code,
  status,
  code,
});

export const json = (status: number, body: FundingOk | Problem): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** A body the contract forbids, on purpose: the read must refuse it, never coerce it. */
export const offContract = (body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
