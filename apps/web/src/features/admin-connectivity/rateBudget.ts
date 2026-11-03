import type { generated } from "@candleviewer/protocol";
import { UNNAMED_ACCOUNT } from "./copy";
import type { ReadStatus } from "./selectState";

export type CapacityReport = generated.rest.components["schemas"]["CapacityReport"];

/**
 * One served `CapacityReport.rate_budget[]` row (E08-D09 §3.3; E08-S12 BQ-2, BQ-8): per account, a limit and a
 * peak per minute. There are no endpoint-class rows until D09-G1 serves them, so none is named. The account is
 * shown by its label only; the wire id keys nothing that is rendered.
 */
export interface RateBudgetRow {
  /** Opaque and stable per account, for in-place updates; never the wire id. */
  readonly key: string;
  readonly label: string;
  readonly limitPerMinute: number | null;
  readonly peakUsedPerMinute: number | null;
  readonly utilisationPct: number | null;
}

const num = (n: number | undefined): number | null =>
  typeof n === "number" && Number.isFinite(n) ? n : null;

/** FNV-1a, 32 bit: a stable opaque row key from the account id, so no id reaches the DOM (SR-026). */
export function opaqueKey(id: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < id.length; i += 1) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return `acct-${h.toString(16)}`;
}

/**
 * The slice's read: a failed read is `failed` (S-18), no answer yet `loading`. The served words map as
 * D09 §5.2 says (`ok`, `error` -> S-17, `unavailable` -> S-19); an outcome this client does not know reads as
 * `unavailable` (C-6.3: tolerate values you do not know).
 */
export function rateBudgetRead(
  report: CapacityReport | null | undefined,
  failed = false,
): ReadStatus {
  if (failed) return "failed";
  if (report === null || report === undefined) return "loading";
  const status = report.rate_budget_status?.status;
  return status === "ok" || status === "error" ? status : "unavailable";
}

/** The served rows; none unless the slice reads `ok`. */
export function rateBudgetRows(
  report: CapacityReport | null | undefined,
): readonly RateBudgetRow[] {
  if (rateBudgetRead(report) !== "ok") return [];
  return (report?.rate_budget ?? []).map((row, i) => ({
    key: opaqueKey(row.exchange_account_id ?? `row-${i}`),
    label: row.label ?? `${UNNAMED_ACCOUNT} ${i + 1}`,
    limitPerMinute: num(row.limit_per_minute),
    peakUsedPerMinute: num(row.peak_used_per_minute),
    utilisationPct: num(row.utilisation_pct),
  }));
}
