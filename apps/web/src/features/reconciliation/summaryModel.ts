/**
 * The while-you-were-offline summary (E29-D03 §4.6; the deck's `summary.*`, D03:381–384), built
 * from the server's digest and the offline window's fills, never from the client's cache (BQ-9 of
 * the ruling of record 6575172489).
 *
 * - **Line 1** `summary.body`: "While you were offline: {clauses}." The clauses are orders filled
 *   (then partly filled); a rule-action clause ("stops moved by a rule") is never shown, since no
 *   read carries rule actions and D03 forbids a guess. No clause: no line 1 ("Reconnected" alone).
 *   One order links to its row (`/positions/order/{id}`, R-132, until SCR-078 exists); several to
 *   the Positions screen (the Fills tab filtered to the window is E29-S04's, G-W3).
 * - **Line 2** `summary.line2`: the offline window (the client's own outage, never B19's
 *   `gap_window`), then per account whose reconnect pass reported changes: "{Account}: N changes,
 *   including N stop attached automatically — review them in Positions.", the repaired stop named
 *   first (D03 C-12, "the repaired-stop entry appears in the summary instead"). With no digest at
 *   all it is `summary.interim`.
 * - **The announcement** `summary.announce` (SR-03, assertive, once): "Reconnected. {clauses} while
 *   offline." or "Reconnected." alone.
 */
import type { FillsOutcome, ReconciliationDigest } from "./digest";

export interface SummaryAccount {
  readonly id: string;
  /** The account's label as the session names it ("Sub-1"); the summary names no other account. */
  readonly label: string;
  /** "LIVE", "DEMO" or "TESTNET". */
  readonly env: string;
}

export interface SummaryInput {
  readonly window: { readonly fromMs: number; readonly toMs: number };
  readonly accounts: readonly SummaryAccount[];
  /** The accounts' digests as read after the reconnect; an account with none is absent. */
  readonly digests: ReadonlyMap<string, ReconciliationDigest>;
  readonly fills: FillsOutcome;
}

/** A run of text, linked when `href` is set (each link goes to the affected row or screen). */
export interface Segment {
  readonly text: string;
  readonly href?: string;
}

export interface RecoveredSummary {
  readonly title: "Reconnected";
  readonly body: readonly Segment[] | null;
  readonly line2: readonly Segment[] | null;
  readonly announce: string;
}

/** The report's correction categories (`24` §8.5), counted as "changes" on an account's line. */
const CHANGES = [
  "sl_repaired",
  "corrected",
  "resolved_from_history",
  "newly_unknown",
  "untracked",
  "position_drift",
  "abandoned",
  "unpaired",
  "anomalies",
  "held",
  "foreign_stops",
  "sl_restored",
  "sl_restore_refused",
  "sl_tighter",
] as const;

const pad = (n: number): string => String(n).padStart(2, "0");
const hms = (ms: number): string => {
  const d = new Date(ms);
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
};
/** "14:01:30–14:02:11": the deck's window, UTC. */
export const formatWindow = (w: SummaryInput["window"]): string =>
  `${hms(w.fromMs)}–${hms(w.toMs)}`;

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

/** A list's full length: `counts` when the server gives it (lists are cut at 256), else its own. */
function countOf(digest: ReconciliationDigest, name: (typeof CHANGES)[number]): number {
  const full = digest.counts[name];
  if (typeof full === "number" && Number.isSafeInteger(full) && full >= 0) return full;
  const list: unknown = (digest as Record<string, unknown>)[name];
  return Array.isArray(list) ? list.length : 0;
}

/** Whether the digest is this reconnect's pass: started by it, and read the exchange after the drop. */
export function isReconnectPass(
  digest: ReconciliationDigest,
  window: SummaryInput["window"],
): boolean {
  const confirmed = Date.parse(digest.confirmed_at);
  return digest.trigger === "reconnect" && Number.isFinite(confirmed) && confirmed >= window.fromMs;
}

function fillClauses(fills: FillsOutcome): Segment[] {
  if (fills === null) return [];
  const filled = fills.filter((o) => o.filled);
  const partly = fills.filter((o) => !o.filled);
  const clause = (orders: typeof fills, one: string, many: string): Segment[] => {
    const only = orders.length === 1 ? orders[0] : undefined;
    if (orders.length === 0) return [];
    const href =
      only === undefined ? "/positions" : `/positions/order/${encodeURIComponent(only.orderId)}`;
    return [{ text: plural(orders.length, one, many), href }];
  };
  return [
    ...clause(filled, "order filled", "orders filled"),
    ...clause(partly, "order partly filled", "orders partly filled"),
  ];
}

function accountClause(account: SummaryAccount, digest: ReconciliationDigest): Segment[] {
  const changes = CHANGES.reduce((sum, name) => sum + countOf(digest, name), 0);
  if (changes === 0) return [];
  const repaired = countOf(digest, "sl_repaired");
  const including =
    repaired === 0 ? "" : `, including ${plural(repaired, "stop", "stops")} attached automatically`;
  return [
    { text: ` · ${account.label}: ${plural(changes, "change", "changes")}${including} — ` },
    { text: "review them in Positions", href: `/positions/${encodeURIComponent(account.id)}` },
  ];
}

export function buildSummary(input: SummaryInput): RecoveredSummary {
  const clauses = fillClauses(input.fills);
  const body: Segment[] | null =
    clauses.length === 0
      ? null
      : [
          { text: "While you were offline: " },
          ...clauses.flatMap((c, i) => (i === 0 ? [c] : [{ text: ", " }, c])),
          { text: "." },
        ];
  const window = formatWindow(input.window);
  const reported = input.accounts.flatMap((account) => {
    const digest = input.digests.get(account.id);
    return digest !== undefined && isReconnectPass(digest, input.window)
      ? [{ account, digest }]
      : [];
  });
  let line2: Segment[] | null;
  if (reported.length === 0) {
    line2 = [
      { text: `Offline ${window} UTC. Rule actions are not listed here yet — check your stops.` },
    ];
  } else {
    // The account with a repaired stop first (D03 C-12), then the order the session lists them in.
    const ordered = [...reported].sort(
      (a, b) =>
        Number(countOf(b.digest, "sl_repaired") > 0) - Number(countOf(a.digest, "sl_repaired") > 0),
    );
    const parts = ordered.flatMap(({ account, digest }) => accountClause(account, digest));
    line2 =
      parts.length === 0
        ? [{ text: `Offline ${window} UTC.` }]
        : [{ text: `Offline ${window} UTC` }, ...parts, { text: "." }];
  }
  const spoken = clauses.map((c) => c.text).join(" and ");
  return {
    title: "Reconnected",
    body,
    line2,
    announce: spoken === "" ? "Reconnected." : `Reconnected. ${spoken} while offline.`,
  };
}

/** A segment list as plain text (tests, the region's accessible text). */
export const textOf = (segments: readonly Segment[] | null): string =>
  segments === null ? "" : segments.map((s) => s.text).join("");
