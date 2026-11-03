// E24-S05 (#780) slice 2: the feed's states in text (D02 §6, §9; D03 S54-45 … S54-50, S54-70 … S54-75). Precedence
// per D02 §9, first match wins: disconnected > stale > the retry band > the loading band; the partial chip and the
// coverage sentences keep their own slot, and no state hides them. An empty list is never drawn where the window is
// outside coverage: the no-coverage state says why it is empty (the ticket's sc. 4; memo F18).
// TODO(#780, E12-D03 C-36): the `Recording settings for {symbol}…` route and its T2 sentence form (S54-45 / S54-46)
// need the `recording:write` grant on the session; they land with the SCR-054 mount (slice 3).
import type { JSX } from "react";
import { Button, EmptyState, FreshnessMarker, Skeleton, Tag } from "@candleviewer/ui";
import type { LiqSnapshot } from "../liquidationFeed";
import * as copy from "./copy";
import { coverageTime, utcTime } from "./format";

/**
 * CMP-239 for the topic's own state, its time the topic's last data frame (review B m4); liquidation silence never
 * shades (D02 §9). PROPOSED: packages/ui's CMP-239 has only `stale`, so `disconnected` is the stale chip with the
 * word as its label until the DS owner adds the state (G-row in the #780 report).
 */
export function FeedStatusChip({ snapshot }: { snapshot: LiqSnapshot }): JSX.Element | null {
  const last = snapshot.lastFrameAtMs;
  if (snapshot.feed === "resyncing" || snapshot.feed === "revoked") {
    return (
      <FreshnessMarker
        presentation="compact"
        state="stale"
        escalated
        label={copy.disconnected(last)}
      />
    );
  }
  if (snapshot.feed === "stale") {
    return <FreshnessMarker presentation="compact" state="stale" label={copy.stale(last)} />;
  }
  return null;
}

/** The read's own band: retry with `last_success_at`, or loading (skeleton, or a caption while rows exist). */
export function HistoryBand({
  snapshot,
  onRetry,
}: {
  snapshot: LiqSnapshot;
  onRetry: () => void;
}): JSX.Element | null {
  const { history } = snapshot;
  if (history.phase === "failed") {
    return (
      <div className="cv-liq-pane__retry">
        {/* no status role: the sub-pane keeps one status node (review B m6) */}
        <p className="cv-liq-pane__retry-title">
          {history.status === 503 ? copy.COVERAGE_RETRY : copy.RETRY_TITLE}
        </p>
        <Button
          variant="secondary"
          size="sm"
          density="compact"
          aria-label={copy.RETRY_NAME}
          onClick={onRetry}
        >
          {copy.RETRY}
        </Button>
        {history.lastSuccessAtMs === null ? null : (
          <p className="cv-liq-pane__caption">{copy.lastLoaded(history.lastSuccessAtMs)}</p>
        )}
      </div>
    );
  }
  if (history.phase === "loading") {
    return snapshot.rows.length === 0 ? (
      <div className="cv-liq-pane__loading" aria-busy="true">
        <Skeleton shape="row" count={3} />
        <p className="cv-visually-hidden">{copy.LOADING}</p>
      </div>
    ) : (
      <p className="cv-liq-pane__caption">{copy.LOADING}</p>
    );
  }
  const cut = history.truncated;
  return cut === null ? null : (
    <p className="cv-liq-pane__caption">{copy.truncated(cut.side, utcTime(cut.atMs))}</p>
  );
}

export interface CoverageView {
  /** The partial chip and its sentence, or the no-coverage state. */
  readonly node: JSX.Element | null;
  /** What an empty table says inside coverage; `null` before coverage is known. */
  readonly emptyTitle: string | null;
  /** The window is outside coverage: no table is drawn while it holds no row. */
  readonly noCoverage: boolean;
}

/**
 * Coverage from the last read's `meta.coverage` (kept while a retry runs or fails, so the chip never goes), compared
 * with the requested window, never the oldest row.
 */
export function coverageView(symbol: string, snapshot: LiqSnapshot): CoverageView {
  const { coverage, window } = snapshot;
  if (coverage === null || window === null) {
    return { node: null, emptyTitle: null, noCoverage: false };
  }
  const when = (ms: number): string => coverageTime(ms, window.toMs);
  const first = coverage.firstAvailableMs;
  if (coverage.noCoverage) {
    const live = snapshot.feed === "live" ? copy.LIVE_STREAMING : undefined;
    const node =
      first === null ? (
        <EmptyState
          variant="recording-not-started"
          title={copy.neverRecorded(symbol)}
          {...(live === undefined ? {} : { description: live })}
          headingLevel={4}
        />
      ) : (
        <EmptyState
          variant="recording-not-started"
          title={copy.beforeCoverage(when(first))}
          headingLevel={4}
        />
      );
    return { node, emptyTitle: null, noCoverage: true };
  }
  const from = coverage.coveredFromMs ?? first;
  const emptyTitle = from === null ? null : copy.emptyRecorded(when(from));
  if (first === null || first <= window.fromMs)
    return { node: null, emptyTitle, noCoverage: false };
  return {
    node: (
      <div className="cv-liq-pane__partial">
        {/* PROPOSED: CMP-239 `partial` is not in packages/ui; a neutral CMP-011 Tag until it is (G-row) */}
        <Tag label={copy.sinceChip(when(first))} density="compact" />
        <p className="cv-liq-pane__caption">{copy.partialSentence(when(first))}</p>
      </div>
    ),
    emptyTitle,
    noCoverage: false,
  };
}
