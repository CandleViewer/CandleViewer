/**
 * The CandleViewer band's coverage rows (E08-D06 §4.3, §11.3): `GET /market/data-coverage?symbol=` once per open,
 * mapped to "trades from 1 Sep · order book from 7 Sep", the gap count and the latest gap (F10: its start rounded
 * down and its end rounded up to the minute, so the band never understates a gap), and the as-of line. The reasons
 * list is open-ended: a reason this client does not know is still a gap (C-6.3). Recording state and the Owner's
 * internals are E16-S02's, not here.
 */
import type { generated } from "@candleviewer/protocol";
import { SYSTEM_CLOCK, type Clock } from "../symbol-search/instrumentIndex";
import * as copy from "./copy";
import { getAnswer } from "./http";

export type DataCoverage = generated.rest.components["schemas"]["DataCoverage"];

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MINUTE = 60_000;
const SENDABLE = /^[A-Z0-9]{2,16}USDT$/;

export interface CoverageView {
  /** "Coverage as of 10:31:02 UTC · trades can include imported days"; `null` without `generated_at`. */
  readonly asOf: string | null;
  /** "trades from 1 Sep", one per stream the deck names, earliest `from` each. */
  readonly streams: readonly string[];
  /** The count of gaps in the window, or `null` when the window has no data (the row is omitted). */
  readonly gapCount: number | null;
  /** "4 Sep 02:11–02:15 UTC, connection lost" for the latest gap. */
  readonly latestGap: string | null;
  /** Gap dates in full, with seconds, for the row's accessible description (F10). */
  readonly latestGapExact: string | null;
  /** "No recorded data in the last 90 days": no stream has an interval. */
  readonly empty: string | null;
}

const utcDay = (ms: number): string => {
  const d = new Date(ms);
  return `${String(d.getUTCDate())} ${MONTHS[d.getUTCMonth()] ?? ""}`;
};
const utcTime = (ms: number, seconds = false): string =>
  new Date(ms).toISOString().slice(11, seconds ? 19 : 16);

/** F10's words for a gap: minutes, the start down, the end up; the day repeats when the gap crosses midnight. */
export function gapText(fromMs: number, toMs: number, reason: string | undefined): string {
  const from = Math.floor(fromMs / MINUTE) * MINUTE;
  const to = Math.ceil(toMs / MINUTE) * MINUTE;
  const same = utcDay(from) === utcDay(to);
  const span = same
    ? `${utcDay(from)} ${utcTime(from)}–${utcTime(to)}`
    : `${utcDay(from)} ${utcTime(from)}–${utcDay(to)} ${utcTime(to)}`;
  const words =
    reason !== undefined && Object.hasOwn(copy.GAP_REASONS, reason)
      ? (copy.GAP_REASONS[reason] ?? copy.GAP_UNKNOWN)
      : copy.GAP_UNKNOWN;
  return `${span} UTC, ${words}`;
}

const time = (iso: string | undefined): number | null => {
  const ms = iso === undefined ? NaN : Date.parse(iso);
  return Number.isFinite(ms) ? ms : null;
};

/** The deck's stream words: the two D06 names; a kind it does not name has no row (never invented). */
const streamWord = (stream: string | undefined): string | null =>
  stream === "trades"
    ? copy.STREAM_WORDS.trades
    : stream === "orderbook_delta" || stream === "orderbook_snapshot"
      ? copy.STREAM_WORDS.orderbook
      : null;

export function coverageView(coverage: DataCoverage): CoverageView {
  const earliest = new Map<string, number>();
  let hasData = false;
  const gaps: { from: number; to: number; reason: string | undefined }[] = [];
  for (const stream of coverage.streams ?? []) {
    for (const interval of stream.intervals ?? []) {
      const from = time(interval.from);
      if (from === null) continue;
      hasData = true;
      const word = streamWord(stream.stream);
      if (word !== null) earliest.set(word, Math.min(earliest.get(word) ?? from, from));
    }
    for (const gap of stream.gaps ?? []) {
      const from = time(gap.from);
      const to = time(gap.to);
      if (from !== null && to !== null) gaps.push({ from, to, reason: gap.reason });
    }
  }
  const generated = time(coverage.generated_at);
  const asOf =
    generated === null
      ? null
      : `${copy.coverageAsOf(utcTime(generated, true))} · ${copy.IMPORTED_DAYS}`;
  const streams = [...earliest].map(([word, from]) => copy.streamFrom(word, utcDay(from)));
  if (!hasData) {
    return {
      asOf,
      streams: [],
      gapCount: null,
      latestGap: null,
      latestGapExact: null,
      empty: copy.NO_RECORDED_DATA,
    };
  }
  const latest = gaps.reduce<(typeof gaps)[number] | null>(
    (best, gap) => (best === null || gap.to > best.to ? gap : best),
    null,
  );
  return {
    asOf,
    streams,
    gapCount: gaps.length,
    latestGap: latest === null ? null : gapText(latest.from, latest.to, latest.reason),
    latestGapExact:
      latest === null
        ? null
        : `${new Date(latest.from).toISOString().slice(0, 19)}Z–${new Date(latest.to).toISOString().slice(0, 19)}Z`,
    empty: null,
  };
}

export type CoverageOutcome =
  | { readonly kind: "ok"; readonly view: CoverageView }
  /** 422: not Trading (CR-13), or the server holds no catalogue yet. The host reads it by the contract band (§11.3). */
  | { readonly kind: "refused_422" }
  | { readonly kind: "forbidden" }
  | { readonly kind: "failed"; readonly status: number | null };

const isCoverage = (body: unknown): body is DataCoverage =>
  typeof body === "object" && body !== null;

/** Once per open; resolves `null` when `signal` aborted first. */
export async function fetchCoverage(
  symbol: string,
  signal: AbortSignal,
  clock: Clock = SYSTEM_CLOCK,
): Promise<CoverageOutcome | null> {
  if (!SENDABLE.test(symbol)) return { kind: "failed", status: null };
  const answer = await getAnswer(
    `/api/v1/market/data-coverage?symbol=${encodeURIComponent(symbol)}`,
    signal,
    clock,
  );
  if (signal.aborted) return null;
  if (answer === null) return { kind: "failed", status: null };
  if (answer.ok) {
    return isCoverage(answer.body)
      ? { kind: "ok", view: coverageView(answer.body) }
      : { kind: "failed", status: answer.status };
  }
  if (answer.status === 422) return { kind: "refused_422" };
  if (answer.status === 403) return { kind: "forbidden" };
  return { kind: "failed", status: answer.status };
}
