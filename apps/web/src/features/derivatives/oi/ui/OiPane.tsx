// E24-S01 (#776) slice 2: the CMP-186 OiFundingLiqPane shell with its OI sub-pane only (the catalogue's
// `OiOnly`; funding and liquidations slot in with E24-S03 / S05). A named region (the ticket's a11y notes):
// legend row 0 (label, the granularity note, the table toggle), the CMP-036 readout, the state band, the
// plot slot that slice 3 fills with the engine's line series, and the table alternative. Every state is
// conveyed in text, never by shading alone. Presentational: the snapshot comes from `useOiSnapshot`.
import { useId, useRef, useState, type JSX, type ReactNode } from "react";
import { Button, EmptyState, Skeleton, type HeadingLevel } from "@candleviewer/ui";
import type { OiSnapshot } from "../oiFeed";
import { baseCoin, QUOTE_UNIT } from "../intervals";
import * as copy from "./copy";
import { OiReadout, type OiDelta } from "./OiReadout";
import { OiTable } from "./OiTable";
import "./oiPane.css";

export interface OiPaneProps {
  readonly symbol: string;
  readonly snapshot: OiSnapshot;
  readonly onRetry: () => void;
  /** BQ 2: the served per-bar delta, when the host has it. */
  readonly delta?: OiDelta | undefined;
  /** Slice 3: the engine's linked sub-pane. Until then the region is a placeholder. */
  readonly plot?: ReactNode;
  readonly visible?: { readonly fromMs: number; readonly toMs: number } | undefined;
  readonly defaultTableOpen?: boolean;
  /** The pane label's level in its host's outline (default 3); the empty state's heading is one below. */
  readonly headingLevel?: 2 | 3 | 4 | 5;
  /**
   * D03 §9: `compact` (default) and `comfortable` are UI densities; `dense` is chart-only (canvas padding,
   * slice 3's), so the DOM chrome stays compact and its 24 px targets never shrink.
   */
  readonly density?: "comfortable" | "compact" | "dense";
}

function Band({
  symbol,
  snapshot,
  onRetry,
  emptyLevel,
  uiDensity,
}: Pick<OiPaneProps, "symbol" | "snapshot" | "onRetry"> & {
  readonly emptyLevel: HeadingLevel;
  readonly uiDensity: "comfortable" | "compact";
}): JSX.Element | null {
  const { history, latest } = snapshot;
  if (history.phase === "failed") {
    // the sentence is the pane's persistent status region (above); the band holds the action
    return (
      <div className="cv-oi-pane__retry">
        <Button variant="secondary" size="sm" density={uiDensity} onClick={onRetry}>
          {copy.RETRY}
        </Button>
        {history.lastSuccessAtMs === null ? null : (
          <p className="cv-oi-pane__caption">{copy.lastLoaded(history.lastSuccessAtMs)}</p>
        )}
      </div>
    );
  }
  if (history.phase === "loading" && latest === null) {
    return (
      <div className="cv-oi-pane__loading" aria-busy="true">
        <Skeleton shape="chart" />
        <p className="cv-visually-hidden">{copy.LOADING}</p>
      </div>
    );
  }
  if (history.phase === "ready" && history.empty) {
    const live = latest?.source === "ws_ticker" ? copy.LIVE_STREAMING : null;
    const starts =
      snapshot.coverageFromMs === null ? null : copy.historyStarts(snapshot.coverageFromMs);
    const description = [starts, live].filter((s): s is string => s !== null).join(" ");
    return (
      <EmptyState
        title={copy.emptyTitle(symbol)}
        {...(description === "" ? {} : { description })}
        headingLevel={emptyLevel}
      />
    );
  }
  return null;
}

export function OiPane({
  symbol,
  snapshot,
  onRetry,
  delta,
  plot,
  visible,
  defaultTableOpen = false,
  headingLevel = 3,
  density = "compact",
}: OiPaneProps): JSX.Element {
  const Heading = `h${String(headingLevel)}` as "h2" | "h3" | "h4" | "h5";
  const emptyLevel = (headingLevel + 1) as HeadingLevel;
  const uiDensity = density === "comfortable" ? "comfortable" : "compact";
  const tableId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const [tableOpen, setTableOpen] = useState(defaultTableOpen);
  const { stale, note, history, latest } = snapshot;
  const base = baseCoin(symbol);
  const retry = (): void => {
    onRetry();
    heading.current?.focus(); // the band goes while it loads: focus stays in the pane
  };
  return (
    <section
      className="cv-oi-pane"
      aria-label={copy.regionName(symbol)}
      data-cmp="CMP-186"
      data-stale={stale.tier === "fresh" ? undefined : stale.tier}
      data-density={density}
    >
      <div className="cv-oi-pane__legend">
        <Heading ref={heading} tabIndex={-1} className="cv-oi-pane__title">
          {copy.PANE_LABEL}
        </Heading>
        {note === null ? null : <span className="cv-oi-pane__caption">{note}</span>}
        {history.phase === "loading" && latest !== null ? (
          <span className="cv-oi-pane__caption">{copy.BACKFILLING}</span>
        ) : null}
        {history.phase === "ready" && history.truncated !== null ? (
          <span className="cv-oi-pane__caption">
            {history.truncated === "older" ? copy.TRUNCATED_OLDER : copy.TRUNCATED_NEWER}
          </span>
        ) : null}
        <span className="cv-oi-pane__toggle">
          <Button
            variant="ghost"
            size="sm"
            density={uiDensity}
            aria-expanded={tableOpen}
            aria-controls={tableId}
            onClick={() => setTableOpen((open) => !open)}
          >
            {tableOpen ? copy.TABLE_HIDE : copy.TABLE_SHOW}
          </Button>
        </span>
      </div>
      <OiReadout
        latest={latest}
        baseUnit={base}
        quoteUnit={QUOTE_UNIT}
        delta={delta}
        stale={stale}
      />
      <div className="cv-oi-pane__body">
        {/* in the DOM from mount and only its text changes, so the failure is said once (05 §6.2) */}
        <p role="status" className="cv-oi-pane__status">
          {history.phase === "failed" ? copy.RETRY_TITLE : ""}
        </p>
        <Band
          symbol={symbol}
          snapshot={snapshot}
          onRetry={retry}
          emptyLevel={emptyLevel}
          uiDensity={uiDensity}
        />
        <div className="cv-oi-pane__plot" data-slot="plot">
          {plot}
        </div>
      </div>
      <div id={tableId} className="cv-oi-pane__table" hidden={!tableOpen}>
        {tableOpen ? (
          <OiTable
            symbol={symbol}
            baseUnit={base}
            rows={snapshot.rows}
            gaps={snapshot.gaps}
            visible={visible}
            density={uiDensity}
          />
        ) : null}
      </div>
    </section>
  );
}
