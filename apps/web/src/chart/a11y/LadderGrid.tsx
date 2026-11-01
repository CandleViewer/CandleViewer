/**
 * The DOM-ladder surrogate (E47-S02, #1358; CMP-108 rows in a `role="grid"`, `05` §3.4.2): one Tab stop for the whole
 * ladder, ↑/↓ by row, PageUp/PageDown by page, Home/End and Ctrl+Home/Ctrl+End to the ends, only the window around
 * the stop in the DOM. Each row's name is its one sentence (price, bid, ask, side, own orders). Book churn updates the
 * focused row's name in place and says nothing (BQ-07); the stop follows its price. Enter, Ctrl+Enter and Ctrl+Delete
 * are not bound here (BQ-05): `onRowKeyDown` is the seam E21-S01/S06 bind through the confirm policy, with
 * `keyboardOrderReadback` as the read-back.
 *
 * The name says the price first (the row's identity) and then the columns left to right, while the row draws bid,
 * price, ask: a recorded order difference (SC 2.5.3 holds, every visible number is in the name) for E21-D06 #506. A
 * faulty field draws a dash and reads "not available"; the rest of the ladder still renders. An empty book is a
 * line of text, not a grid with no rows.
 */
import { useMemo, type JSX, type KeyboardEvent } from "react";
import { displayDecimal } from "./format";
import { nearestDecimalKey } from "./compositeGrid";
import { GRID_NAME, LADDER, UNAVAILABLE } from "./orderflowCopy";
import {
  ladderRowMarks,
  ladderRowSentence,
  orUnavailable,
  sizeText,
  type LadderRowFields,
} from "./orderflowFormat";
import { SideLegend } from "./marks";
import { useCompositeGrid } from "./useCompositeGrid";

export interface LadderRow extends LadderRowFields {
  /** The row's identity through churn: its price. */
  readonly key: string;
}

export interface LadderGridProps {
  readonly symbol: string;
  readonly rows: readonly LadderRow[];
  readonly windowRows?: number;
  readonly pageRows?: number;
  readonly initialRow?: number;
  /** The host's keys on the focused row (anything the grid does not move on). */
  readonly onRowKeyDown?: (row: LadderRow, event: KeyboardEvent<HTMLElement>) => void;
}

export function LadderGrid(props: LadderGridProps): JSX.Element {
  const { symbol, rows, onRowKeyDown } = props;
  const rowKeys = useMemo(() => rows.map((r) => r.key), [rows]);
  const grid = useCompositeGrid({
    rows: rows.length,
    cols: 1,
    homeEnd: "col", // one column: Home/End reach the ladder's top and bottom rows
    rowKeys,
    nearestRow: nearestDecimalKey, // a price that left the book hands the stop to the nearest price
    ...(props.windowRows === undefined ? {} : { windowRows: props.windowRows }),
    ...(props.pageRows === undefined ? {} : { pageRows: props.pageRows }),
    ...(props.initialRow === undefined ? {} : { initial: { row: props.initialRow } }),
  });
  const shown = (format: (v: string) => string, v: string): string =>
    orUnavailable(format, v, UNAVAILABLE.shown);
  const drawn: JSX.Element[] = [];
  for (let i = grid.window.first; i <= grid.window.last && i < rows.length; i++) {
    const row = rows[i];
    if (row === undefined) continue;
    const cell = grid.cellProps(i, 0);
    const marks = ladderRowMarks(row);
    drawn.push(
      <div key={row.key} {...grid.rowProps(i)} className="cv-of-ladder__row">
        <div
          {...cell}
          role="gridcell"
          tabIndex={cell.tabIndex}
          aria-label={ladderRowSentence(row)}
          className="cv-of-ladder__cell cv-focus-ring cv-focus-ring--inset"
          data-side={row.side}
          onKeyDown={(event) => onRowKeyDown?.(row, event)}
        >
          <span className="cv-of-ladder__bid" aria-hidden="true">
            {shown(sizeText, row.bid)}
          </span>
          <span className="cv-of-ladder__price" aria-hidden="true">
            {shown(displayDecimal, row.price)}
          </span>
          <span className="cv-of-ladder__ask" aria-hidden="true">
            {shown(sizeText, row.ask)}
          </span>
          <span className="cv-of-ladder__mine" aria-hidden="true">
            {marks.own === null ? null : <span className="cv-of-ladder__own">{marks.own}</span>}
            {marks.position === null ? null : (
              <span className="cv-of-ladder__position">{marks.position}</span>
            )}
          </span>
        </div>
      </div>,
    );
  }
  return (
    <div className="cv-of-ladder" data-scr="SCR-050">
      <SideLegend />
      {rows.length === 0 ? (
        <p role="group" aria-label={GRID_NAME.ladder(symbol)} className="cv-of-ladder__empty">
          {LADDER.empty}
        </p>
      ) : (
        <div
          {...grid.gridProps}
          aria-label={GRID_NAME.ladder(symbol)}
          className="cv-of-ladder__grid"
        >
          {drawn}
        </div>
      )}
    </div>
  );
}
