// E24-S08 (#783) slice 2: the basis readout with its state band and table alternative (US-DERIV-008
// scenario 3, D03 S54-8 / S54-9). A failed source shows the retry band with the last successful time and a
// labelled Retry button, never a blank readout (the last values stay); the L/S ratio says its source is
// unavailable rather than drawing a series. Presentational: the snapshot comes from `useBasisSnapshot`.
import { createElement, useEffect, useId, useRef, useState, type JSX, type RefObject } from "react";
import { Button } from "@candleviewer/ui";
import type { BasisSnapshot } from "../basisFeed";
import type { BasisSource } from "../settings";
import { BasisReadout } from "./BasisReadout";
import { BasisTable } from "./BasisTable";
import * as copy from "./copy";

export interface BasisPanelProps {
  readonly symbol: string;
  readonly snapshot: BasisSnapshot;
  readonly source: BasisSource;
  readonly onSourceChange: (source: BasisSource) => void;
  readonly onRetry: () => void;
  readonly defaultTableOpen?: boolean;
  /** The panel title's heading level; the host sets it from its outline (default 3). */
  readonly headingLevel?: 2 | 3 | 4 | 5 | 6;
}

function RetryBand({
  snapshot,
  onRetry,
  bandRef,
  titleId,
}: Pick<BasisPanelProps, "snapshot" | "onRetry"> & {
  readonly bandRef: RefObject<HTMLDivElement>;
  readonly titleId: string;
}): JSX.Element | null {
  const { source } = snapshot;
  if (source.state !== "failed") return null;
  return (
    <div className="cv-basis__retry" ref={bandRef} role="group" aria-labelledby={titleId}>
      <p id={titleId} className="cv-basis__retry-title">
        {copy.RETRY_TITLE}
      </p>
      <Button variant="secondary" size="sm" density="compact" onClick={onRetry}>
        {copy.RETRY}
      </Button>
      <p className="cv-basis__caption">
        {source.lastSuccessAtMs === null
          ? copy.NEVER_LOADED
          : copy.lastLoaded(source.lastSuccessAtMs)}
      </p>
    </div>
  );
}

export function BasisPanel({
  symbol,
  snapshot,
  source,
  onSourceChange,
  onRetry,
  defaultTableOpen = false,
  headingLevel = 3,
}: BasisPanelProps): JSX.Element {
  const tableId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const [tableOpen, setTableOpen] = useState(defaultTableOpen);
  const band = useRef<HTMLDivElement>(null);
  // set by Retry: the band goes while it reloads, and if the source fails again focus returns to the
  // new Retry button; moving focus elsewhere cancels it
  const refocus = useRef(false);
  const failed = snapshot.source.state === "failed";
  useEffect(() => {
    if (!failed || !refocus.current) return;
    refocus.current = false;
    band.current?.querySelector("button")?.focus();
  }, [failed]);
  const retry = (): void => {
    refocus.current = true;
    onRetry();
    heading.current?.focus(); // focus stays in the panel while it reloads
  };
  // one polite region, mounted from the start so the failure is announced when it is filled
  const announcement = failed ? copy.RETRY_TITLE : "";
  return (
    <section
      className="cv-basis__panel"
      aria-label={copy.panelName(symbol)}
      data-source-state={snapshot.source.state}
    >
      <div className="cv-basis__legend">
        {createElement(
          `h${String(headingLevel)}`,
          {
            ref: heading,
            tabIndex: -1,
            className: "cv-basis__title",
            onBlur: () => {
              refocus.current = false; // the user moved on: nothing to restore
            },
          },
          copy.PANE_LABEL,
        )}
        <span className="cv-basis__toggle">
          <Button
            variant="ghost"
            size="sm"
            density="compact"
            aria-expanded={tableOpen}
            aria-controls={tableId}
            onClick={() => setTableOpen((open) => !open)}
          >
            {tableOpen ? copy.TABLE_HIDE : copy.TABLE_SHOW}
          </Button>
        </span>
      </div>
      <BasisReadout
        symbol={symbol}
        snapshot={snapshot}
        source={source}
        onSourceChange={onSourceChange}
      />
      <p className="cv-visually-hidden" role="status" aria-label={copy.STATE_REGION}>
        {announcement}
      </p>
      <RetryBand snapshot={snapshot} onRetry={retry} bandRef={band} titleId={`${tableId}-retry`} />
      <p className="cv-basis__caption cv-basis__ratio-note">{copy.RATIO_ROW}</p>
      <div id={tableId} className="cv-basis__table-wrap" hidden={!tableOpen}>
        {tableOpen ? <BasisTable symbol={symbol} latest={snapshot.latest} source={source} /> : null}
      </div>
    </section>
  );
}
