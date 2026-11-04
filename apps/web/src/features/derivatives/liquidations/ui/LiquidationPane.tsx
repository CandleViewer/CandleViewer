// E24-S05 (#780): the liquidation feed on SCR-054 (CMP-186's liquidations sub-pane, the feed part). A named region
// with a heading; the toolbar (the burst counter, the filter line, the topic's CMP-239 chip, Pause); the read's band
// and the coverage; the feed region (the `N new` control, the "newest 40 of N" line, the table); the completeness
// sentence. The view freezes under Pause, focus in the feed region or the pointer over it (D02 §6, WCAG 2.2.2) and
// counts what arrived meanwhile; the `N new` control sits inside that region, so reaching it never thaws the view.
// Nothing here is a live region (D02 §13: the counter is `aria-live="off"`); AN-4's cascade summary is the connected
// pane's, through the shell announcer (PR 4).
// TODO(#723, G-row 6618391299): the `Liq 1 h · long … · short …` readout (BQ 4, ruled 6612481277: a client sum of
// the served 1 h buckets, labelled "served buckets") waits on a served `liquidation_notional`; the counter stands alone.
// TODO(#778): `Pause` is component state; any `liq` display setting joins #778's `deriv` block, never local storage.
import { useEffect, useRef, useState, type FocusEvent, type JSX } from "react";
import { Button, EmptyState } from "@candleviewer/ui";
import type { LiqSnapshot } from "../liquidationFeed";
import type { FeedRow } from "../buckets";
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
  /**
   * A row activated (`Enter` or a click): the host moves the crosshair to its time (D02 §6). A bucket row's `tsMs`
   * is its 250 ms bucket's start; a lone print's is the print's own time.
   */
  readonly onPrintActivate?: ((print: FeedRow) => void) | undefined;
}

interface Held {
  /** The feed the rows came from: a symbol or filter change never shows them (review A M1). */
  readonly identity: string;
  readonly rows: readonly FeedRow[];
  readonly seq: number;
}

export function LiquidationPane({
  symbol,
  snapshot,
  onRetry,
  defaultPaused = false,
  onPrintActivate,
}: LiquidationPaneProps): JSX.Element {
  const [paused, setPaused] = useState(defaultPaused);
  const [pointer, setPointer] = useState(false);
  const [focusIn, setFocusIn] = useState(false);
  const [held, setHeld] = useState<Held | null>(null);
  const feedRef = useRef<HTMLDivElement>(null);
  const focusGrid = useRef(false);
  const identity = `${symbol}|${snapshot.minNotionalUsd ?? ""}`;
  const frozen = paused || pointer || focusIn;
  const now: Held = { identity, rows: snapshot.rows, seq: snapshot.newestSeq };
  // derived during render (React's "storing information from previous renders"): no effect, no extra frame
  if (frozen && (held === null || held.identity !== identity)) setHeld(now);
  if (!frozen && held !== null) setHeld(null);
  const view = frozen && held !== null && held.identity === identity ? held : now;
  // a backfill merge renumbers the ring: prints up to the merge point are history, never "new" (review A m2)
  const fresh = snapshot.newestSeq - Math.max(view.seq, snapshot.mergedSeq);

  useEffect(() => {
    if (!focusGrid.current) return;
    focusGrid.current = false;
    feedRef.current?.querySelector<HTMLElement>('[role="grid"] [tabindex="0"]')?.focus();
  });

  const showNewest = (): void => {
    setPaused(false);
    setHeld(now); // still frozen by focus: jump to the top
    focusGrid.current = true; // review B M2: focus lands on the grid, never on a control that goes away
  };
  const onBlur = (e: FocusEvent<HTMLDivElement>): void => {
    if (!(e.relatedTarget instanceof Node && e.currentTarget.contains(e.relatedTarget))) {
      setFocusIn(false);
    }
  };
  // a row's activation (a click, or `Enter` on its cell): delegated from the feed region, since CMP-049's grid
  // has no row callback; the time cell's `data-cv-seq` names the print
  const shown = view.rows;
  useEffect(() => {
    const region = feedRef.current;
    if (region === null) return undefined;
    const activate = (e: Event): void => {
      if (e instanceof KeyboardEvent && e.key !== "Enter") return;
      // a click that ends a text-selection drag selects, it does not activate
      if (e.type === "click" && window.getSelection()?.isCollapsed === false) return;
      const row = e.target instanceof Element ? e.target.closest("tr, [role='row']") : null;
      const seq = Number(row?.querySelector("[data-cv-seq]")?.getAttribute("data-cv-seq"));
      const print = shown.find((r) => r.seq === seq);
      if (print !== undefined) onPrintActivate?.(print);
    };
    region.addEventListener("click", activate);
    region.addEventListener("keydown", activate);
    return () => {
      region.removeEventListener("click", activate);
      region.removeEventListener("keydown", activate);
    };
  });
  const heading = useRef<HTMLHeadingElement>(null);
  const retry = (): void => {
    onRetry();
    heading.current?.focus(); // the band goes while it loads: focus stays in the pane
  };
  const base = baseUnit(symbol);
  const empty = view.rows.length === 0;
  const coverage = coverageView(symbol, snapshot);
  const printsShown = view.rows.reduce((n, r) => n + r.prints, 0);
  const cut = snapshot.held > printsShown && printsShown > 0;

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
          ref={feedRef}
          className="cv-liq-pane__feed"
          onPointerEnter={() => setPointer(true)}
          onPointerLeave={() => setPointer(false)}
          onFocus={() => setFocusIn(true)}
          onBlur={onBlur}
        >
          {fresh > 0 || cut ? (
            <div className="cv-liq-pane__feedbar">
              {fresh > 0 ? (
                // PROPOSED: CMP-011 `neutral` is a static chip in packages/ui; an activatable chip is a ghost
                // CMP-001 until the DS owner rules (G-row in the #780 report)
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
              {cut ? (
                <span className="cv-liq-pane__caption">
                  {copy.newestOf(printsShown, snapshot.held)}
                </span>
              ) : null}
            </div>
          ) : null}
          <LiquidationTable
            symbol={symbol}
            baseUnit={base}
            rows={view.rows}
            activatable={onPrintActivate !== undefined}
            emptyState={<EmptyState title={coverage.emptyTitle ?? copy.WAITING} headingLevel={4} />}
          />
        </div>
      )}
      <p className="cv-liq-pane__caption">{copy.COMPLETENESS}</p>
    </section>
  );
}
