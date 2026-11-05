// E24-S03 (#778) slice 1: the CMP-186 funding sub-pane (`FundingOnly`): legend row 0 (label, the served
// interval), a persistent status region, the state band (loading, empty vs not recorded, unavailable, retry
// with `last_success_at`), the engine's plot slot and the table alternative, which the group's one
// "Show tables" toggle shows (E24-D04 A-03, `aria-pressed`; the SCR-054 group owns it, not the pane).
import { useRef, type JSX, type ReactNode } from "react";
import { Button, EmptyState, Skeleton, type HeadingLevel } from "@candleviewer/ui";
import type { FundingSnapshot } from "../fundingFeed";
import * as copy from "./copy";
import { FundingTable } from "./FundingTable";
import "./fundingPane.css";

export interface FundingPaneProps {
  readonly symbol: string;
  readonly snapshot: FundingSnapshot;
  readonly onRetry: () => void;
  /** The engine's linked sub-pane, drawn from `snapshot.series`; until it exists the slot is empty. */
  readonly plot?: ReactNode;
  readonly visible?: { readonly fromMs: number; readonly toMs: number } | undefined;
  /** The group's A-03 "Show tables" state (and `accessibility.always_show_tables`), from the SCR-054 group. */
  readonly showTables?: boolean;
  /** The pane label's level in its host's outline (default 3); the band's heading is one below. */
  readonly headingLevel?: 2 | 3 | 4 | 5;
  readonly density?: "comfortable" | "compact";
}

function Band({
  symbol,
  snapshot,
  onRetry,
  level,
  density,
}: Pick<FundingPaneProps, "symbol" | "snapshot" | "onRetry"> & {
  readonly level: HeadingLevel;
  readonly density: "comfortable" | "compact";
}): JSX.Element | null {
  const { history } = snapshot;
  const retryButton = (
    <Button
      variant="secondary"
      size="sm"
      density={density}
      aria-label={copy.RETRY_NAME}
      onClick={onRetry}
    >
      {copy.RETRY}
    </Button>
  );
  switch (history.phase) {
    case "failed":
      // the sentence is the pane's status region; the band holds the action and the last good time
      return (
        <div className="cv-funding-pane__retry">
          {retryButton}
          {snapshot.lastSuccessAtMs === null ? null : (
            <p className="cv-funding-pane__caption">{copy.lastLoaded(snapshot.lastSuccessAtMs)}</p>
          )}
        </div>
      );
    case "unavailable":
      return <div className="cv-funding-pane__retry">{retryButton}</div>;
    case "loading":
      return snapshot.series.settled.length > 0 ? null : (
        <div className="cv-funding-pane__loading" aria-busy="true">
          <Skeleton shape="chart" />
          <p className="cv-visually-hidden">{copy.LOADING}</p>
        </div>
      );
    case "ready":
      if (!history.empty) return null;
      return (
        <EmptyState
          title={
            history.coverage === "covered" ? copy.emptyTitle(symbol) : copy.notRecordedTitle(symbol)
          }
          headingLevel={level}
        />
      );
  }
}

const statusText = (snapshot: FundingSnapshot, symbol: string): string =>
  snapshot.history.phase === "failed"
    ? copy.RETRY_TITLE
    : snapshot.history.phase === "unavailable"
      ? copy.unavailableTitle(symbol)
      : "";

export function FundingPane({
  symbol,
  snapshot,
  onRetry,
  plot,
  visible,
  showTables = false,
  headingLevel = 3,
  density = "compact",
}: FundingPaneProps): JSX.Element {
  const Heading = `h${String(headingLevel)}` as "h2" | "h3" | "h4" | "h5";
  const heading = useRef<HTMLHeadingElement>(null);
  const { history, series } = snapshot;
  const unavailable = history.phase === "unavailable";
  // a read has answered for the series shown: a failed first read says nothing about the interval
  // (a retry in flight keeps the last good series, so its legend and table stay while the read runs)
  const lastGood =
    snapshot.lastSuccessAtMs !== null &&
    (series.settled.length > 0 || series.gaps.length > 0 || series.intervalMs !== null);
  const answered =
    history.phase === "ready" ||
    ((history.phase === "failed" || history.phase === "loading") && lastGood);
  const retry = (): void => {
    onRetry();
    heading.current?.focus(); // the band goes while it loads: focus stays in the pane
  };
  const minutes = series.intervalMs === null ? null : series.intervalMs / 60_000;
  return (
    <section
      className="cv-funding-pane"
      aria-label={copy.regionName(symbol)}
      data-cmp="CMP-186"
      data-density={density}
    >
      <div className="cv-funding-pane__legend">
        <Heading ref={heading} tabIndex={-1} className="cv-funding-pane__title">
          {copy.PANE_LABEL}
        </Heading>
        {!answered ? null : (
          <span className="cv-funding-pane__caption">
            {minutes === null ? copy.INTERVAL_UNKNOWN : copy.settlesEvery(minutes)}
          </span>
        )}
        {history.phase === "ready" && history.truncated ? (
          <span className="cv-funding-pane__caption">{copy.TRUNCATED}</span>
        ) : null}
      </div>
      <div className="cv-funding-pane__body">
        {/* in the DOM from mount and only its text changes, so a failure is said once (05 §6.2) */}
        <p role="status" className="cv-funding-pane__status">
          {statusText(snapshot, symbol)}
        </p>
        <Band
          symbol={symbol}
          snapshot={snapshot}
          onRetry={retry}
          level={(headingLevel + 1) as HeadingLevel}
          density={density}
        />
        <div className="cv-funding-pane__plot" data-slot="plot">
          {unavailable ? null : plot}
        </div>
      </div>
      {/* the empty-table sentence is the answer of a read: not drawn before one has answered */}
      {showTables && !unavailable && answered ? (
        <div className="cv-funding-pane__table">
          <FundingTable
            symbol={symbol}
            series={series}
            visible={visible}
            density={density}
            headingLevel={(headingLevel + 1) as HeadingLevel}
          />
        </div>
      ) : null}
    </section>
  );
}
