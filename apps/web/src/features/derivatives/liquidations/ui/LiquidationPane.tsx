// E24-S05 (#780): the liquidation feed on SCR-054 (CMP-186's liquidations sub-pane, the feed part). A named
// region with a heading; the toolbar (the burst counter, the filter line, the topic's CMP-239 chip, the `N new`
// control, Pause); the read's band and the coverage (slice 2); the feed table; the completeness sentence. The view freezes under Pause, focus in the table or the pointer
// over it (D02 §6, WCAG 2.2.2) and counts what arrived meanwhile; nothing here is a live region (D02 §13:
// the counter is `aria-live="off"`; the AN-4 summary is slice 3's).
// TODO(#780): the `Liq 1 h · long … · short …` readout (BQ 4, ruled 6612481277: a client sum of the served 1 h
// buckets, labelled "served buckets") follows outside PR 1's line budget; the counter stands alone until then.
// TODO(#778): `Pause` is component state; any `liq` display setting joins #778's `deriv` block, never local storage.
import { useRef, useState, type FocusEvent, type JSX } from "react";
import { Button, EmptyState } from "@candleviewer/ui";
import type { LiqSnapshot } from "../liquidationFeed";
import type { HeldPrint } from "../ring";
import * as copy from "./copy";
import { baseUnit, rateSpoken, rateText } from "./format";
import { coverageView, FeedStatusChip, HistoryBand } from "./LiquidationStates";
import { LiquidationTable } from "./LiquidationTable";
import "./liquidationPane.css";

export interface LiquidationPaneProps {
  readonly symbol: string;
  readonly snapshot: LiqSnapshot;
  /** The retry band's action. */
  readonly onRetry: () => void;
  readonly defaultPaused?: boolean;
}

interface Held {
  readonly rows: readonly HeldPrint[];
  readonly seq: number;
}

export function LiquidationPane({
  symbol,
  snapshot,
  onRetry,
  defaultPaused = false,
}: LiquidationPaneProps): JSX.Element {
  const [paused, setPaused] = useState(defaultPaused);
  const [pointer, setPointer] = useState(false);
  const [focusIn, setFocusIn] = useState(false);
  const [held, setHeld] = useState<Held | null>(null);
  const frozen = paused || pointer || focusIn;
  // derived during render (React's "storing information from previous renders"): no effect, no extra frame
  if (frozen && held === null) setHeld({ rows: snapshot.rows, seq: snapshot.newestSeq });
  if (!frozen && held !== null) setHeld(null);
  const view = frozen && held !== null ? held : { rows: snapshot.rows, seq: snapshot.newestSeq };
  const fresh = snapshot.newestSeq - view.seq;

  const showNewest = (): void => {
    setPaused(false);
    setHeld({ rows: snapshot.rows, seq: snapshot.newestSeq }); // still frozen by focus: jump to the top
  };
  const onBlur = (e: FocusEvent<HTMLDivElement>): void => {
    if (!(e.relatedTarget instanceof Node && e.currentTarget.contains(e.relatedTarget))) {
      setFocusIn(false);
    }
  };
  const heading = useRef<HTMLHeadingElement>(null);
  const retry = (): void => {
    onRetry();
    heading.current?.focus(); // the band goes while it loads: focus stays in the pane
  };
  const base = baseUnit(symbol);
  const empty = view.rows.length === 0;
  const coverage = coverageView(symbol, snapshot);

  return (
    <section className="cv-liq-pane" aria-label={copy.regionName(symbol)} data-cmp="CMP-186">
      <div className="cv-liq-pane__toolbar">
        <h3 ref={heading} tabIndex={-1} className="cv-liq-pane__title">
          {copy.PANE_LABEL}
        </h3>
        {snapshot.ratePerSec > 0 ? (
          <span className="cv-liq-pane__rate" aria-live="off">
            <span aria-hidden="true">{rateText(snapshot.ratePerSec)}</span>
            <span className="cv-visually-hidden">{rateSpoken(snapshot.ratePerSec)}</span>
          </span>
        ) : null}
        {snapshot.minNotionalUsd === null ? null : (
          <span className="cv-liq-pane__caption">{copy.filterLine(snapshot.minNotionalUsd)}</span>
        )}
        <FeedStatusChip snapshot={snapshot} />
        <span className="cv-liq-pane__controls">
          {fresh > 0 ? (
            <Button
              variant="ghost"
              size="sm"
              density="compact"
              aria-label={copy.newCountName(fresh)}
              onClick={showNewest}
            >
              {copy.newCount(fresh)}
            </Button>
          ) : null}
          <Button
            variant="secondary"
            size="sm"
            density="compact"
            aria-pressed={paused}
            onClick={() => setPaused((p) => !p)}
          >
            {copy.PAUSE}
          </Button>
        </span>
      </div>
      <HistoryBand snapshot={snapshot} onRetry={retry} />
      {coverage.node}
      {empty && coverage.noCoverage ? null : (
        <div
          className="cv-liq-pane__feed"
          onPointerEnter={() => setPointer(true)}
          onPointerLeave={() => setPointer(false)}
          onFocus={() => setFocusIn(true)}
          onBlur={onBlur}
        >
          <LiquidationTable
            symbol={symbol}
            baseUnit={base}
            rows={view.rows}
            emptyState={<EmptyState title={coverage.emptyTitle ?? copy.WAITING} headingLevel={4} />}
          />
        </div>
      )}
      <p className="cv-liq-pane__caption">{copy.COMPLETENESS}</p>
    </section>
  );
}
