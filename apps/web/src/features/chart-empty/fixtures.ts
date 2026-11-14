/** The E16-D05 §3 fixture, derived from `22`'s data-coverage example (D05:204), for the tests and stories (C-13.5). */
import { coverageView, type CoverageOutcome, type DataCoverage } from "../symbol-info/coverage";
import type { Access, ChartStateInput } from "./model";

type Gap = NonNullable<NonNullable<DataCoverage["streams"]>[number]["gaps"]>[number];
export const cov = (at: string, spans: [string, string][], gaps: Gap[]): DataCoverage => ({
  symbol: "BTCUSDT",
  generated_at: at,
  streams: [{ stream: "trades", intervals: spans.map(([from, to]) => ({ from, to })), gaps }],
});
export const gap = (from: string, to: string, reason: NonNullable<Gap["reason"]>): Gap => ({
  from,
  to,
  reason,
});
const SPANS: [string, string][] = [
  ["2026-09-01T00:00:00Z", "2026-09-07T00:00:00Z"],
  ["2026-09-07T00:00:00Z", "2026-09-14T10:31:00Z"],
];
const REPORT = "2026-09-14T10:31:02Z";

export const COVERAGE_FIXTURE = cov(REPORT, SPANS, [
  gap("2026-09-04T02:11:00Z", "2026-09-04T02:14:20Z", "ws_disconnect"),
]);
/** The AC 4 gap: US-REC-006's 12 minutes at the fixture gap's start (02:11–02:23 UTC). */
export const AC4_COVERAGE = cov(REPORT, SPANS, [
  gap("2026-09-04T02:11:00Z", "2026-09-04T02:23:00Z", "ws_disconnect"),
]);
/** The retention fixture (D05 §3): the report one period later, trim date 2026-09-14. */
export const RETENTION_COVERAGE = cov(
  "2026-10-14T10:31:02Z",
  [["2026-09-14T00:00:00Z", "2026-10-14T10:31:00Z"]],
  [gap("2026-09-01T00:00:00Z", "2026-09-14T00:00:00Z", "retention_purge")],
);
export const NEVER_COVERAGE: DataCoverage = {
  symbol: "SOLUSDT",
  generated_at: REPORT,
  streams: [],
};

/**
 * PROPOSED (D05-G1, BQ-04): `22` does not serve `gaps[].backfilled`; this fixture pins the field-present branch only.
 * The columns exist (`21`:3248-3249, `24`:4176-4177).
 */
const backfilled = {
  ...gap("2026-09-04T02:11:00Z", "2026-09-04T02:23:00Z", "ws_disconnect"),
  backfilled: true,
};
export const PROPOSED_BACKFILLED_COVERAGE = cov(REPORT, SPANS, [backfilled]);

/** `fetchCoverage`'s `ok` outcome for a body, as the reader builds it. */
export const read = (coverage: DataCoverage): CoverageOutcome => ({
  kind: "ok",
  view: coverageView(coverage),
  coverage,
});
export const FAILED: CoverageOutcome = { kind: "failed", status: 503 };

export const at = (iso: string): number => Date.parse(iso);

export const OWNER: Access = { viewAsUser: null, canRecord: true, canAdmin: true };
export const VIEWER: Access = { viewAsUser: null, canRecord: false, canAdmin: false };
export const VIEWING_AS: Access = { viewAsUser: "alex", canRecord: true, canAdmin: true };

/** A zero-bar answer on BTCUSDT 1m inside the fixture gap; override per row. */
export const input = (over: Partial<ChartStateInput> = {}): ChartStateInput => ({
  symbol: "BTCUSDT",
  interval: "1m",
  window: { fromMs: at("2026-09-04T02:11:30Z"), toMs: at("2026-09-04T02:14:00Z") },
  bars: { kind: "ok", count: 0 },
  coverage: read(COVERAGE_FIXTURE),
  instrumentStatus: "Trading",
  access: OWNER,
  ...over,
});
