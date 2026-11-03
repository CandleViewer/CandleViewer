/**
 * SCR-135's grid (E42-S04; E42-D04 §4 Columns, D6, D14, AL-3, AL-28): CMP-049 in grid mode,
 * captioned `audit.caption`, its rows CMP-173's `row` variant and, under an expanded entry, its
 * diff row (`AuditRowDiff`), both through CMP-049's row contract. Time is the one `aria-sort`
 * column, never operable (D6). The record SCR-136 shows is `aria-selected` with the `check` glyph
 * (D14), and focus moving between rows keeps an open drawer on the focused one; focus arriving
 * from outside the grid (the drawer handing it back, a Tab from the filters) picks no record
 * (A-1135P2-01). While the drawer is open the arrows stop at Action, as D1 draws the grid clipped
 * at its edge: → and End stay there, Ctrl+End goes to the last row's Action, and no focus lands
 * on a cell the drawer covers (A-1135P2-04). At 200 % the rows reflow to cards that keep the grid
 * (`reflow="grid"`, AL-28). The grid says no line of its own: the page owns them (AL-2, AL-15).
 *
 * The grid is memoised and every prop its host passes is stable, so a page re-read that changed
 * nothing renders no row (the build plan's §9; CMP-049 memoises none): all 200 rows are drawn
 * whole, as a windowed grid assumes fixed row heights, which an expanded row breaks (BQ-11).
 */
import {
  memo,
  useMemo,
  useRef,
  type FocusEvent,
  type JSX,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import {
  AuditRow,
  AuditRowDiff,
  Table,
  auditColumns,
  auditGridRowKey,
  auditGridRows,
  type AuditGridRow,
  type TableRowContext,
} from "@candleviewer/ui";
import type { AuditEntry, AuditView } from "./auditReads";
import { AUDIT_COPY as COPY } from "./copy";

/** E42-D04 §4 Columns, in order; the same for every page, so built once. */
const COLUMNS = auditColumns();
/** The last column the arrows reach while SCR-136 is open (D1): Target onward is the drawer's. */
const ACTION_COLUMN = COLUMNS.findIndex((column) => column.id === "action");
/** CMP-049's own result line: the page says its lines, and this one never (A-1135P2-06). */
const ignoreTableLine = (): void => undefined;

/** An entry's diff row's id, and its expander's (`${id}-toggle`, CMP-173), within one page. */
export const diffRowId = (prefix: string, entryId: number): string => `${prefix}-${entryId}`;

export interface AuditGridProps {
  /** The page's rows after Environment's facet (D7), newest first as read. */
  readonly rows: readonly AuditEntry[];
  /** Entries whose diff row shows (AL-3). */
  readonly expanded: ReadonlySet<number>;
  /** The record SCR-136 shows (D14). */
  readonly selectedId: number | null;
  readonly view: AuditView;
  /** The standing break's first entry (D11): its diff rows lead with `rec.after_break` (AD-5). */
  readonly afterBreakId: number | null;
  /** The page's id prefix for the diff rows and their expanders. */
  readonly idPrefix: string;
  readonly onExpandedChange: (entryId: number, expanded: boolean) => void;
  readonly onOpen: (entryId: number) => void;
  readonly onRowFocus: (entryId: number) => void;
  /** The first read: CMP-015 rows and `aria-busy` (AL-1). */
  readonly loading: boolean;
  /** SCR-136 is open beside the grid: the arrows stop at Action (D1). */
  readonly drawerOpen: boolean;
  /** Shown across every column when no row is drawn (AL-7, AL-26). */
  readonly emptyState: ReactNode;
}

function AuditGridImpl({
  rows,
  expanded,
  selectedId,
  view,
  afterBreakId,
  idPrefix,
  onExpandedChange,
  onOpen,
  onRowFocus,
  loading,
  drawerOpen,
  emptyState,
}: AuditGridProps): JSX.Element {
  const gridRows = useMemo(() => auditGridRows(rows, expanded), [rows, expanded]);
  /** Whether the focus now arriving in a row came from inside the grid (D14 follows only that). */
  const fromInside = useRef(false);
  const onFocusCapture = (event: FocusEvent<HTMLDivElement>): void => {
    const from = event.relatedTarget;
    fromInside.current = from instanceof Node && event.currentTarget.contains(from);
  };
  const onKeyDownCapture = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (!drawerOpen || event.altKey || event.metaKey || event.shiftKey) return;
    const right = event.key === "ArrowRight" && !event.ctrlKey;
    const end = event.key === "End";
    if (!right && !end) return;
    const cell = (event.target as Element).closest<HTMLElement>("[data-cv-c]");
    // the diff row's one cell walks its own controls (AL-3)
    if (cell === null || cell.hasAttribute("data-cv-composite")) return;
    if (right && Number(cell.dataset["cvC"]) < ACTION_COLUMN) return;
    event.preventDefault();
    event.stopPropagation();
    if (!end) return;
    const action = `[data-cv-c="${ACTION_COLUMN}"]`;
    const cells = event.currentTarget.querySelectorAll<HTMLElement>(action);
    const to = event.ctrlKey ? cells[cells.length - 1] : cell.closest("tr")?.querySelector(action);
    if (to instanceof HTMLElement) to.focus();
  };
  const renderRow = (row: AuditGridRow, grid: TableRowContext): ReactNode => {
    const id = row.entry.id;
    const diffId = diffRowId(idPrefix, id);
    if (row.kind === "diff") {
      return (
        <AuditRowDiff
          grid={grid}
          entry={row.entry}
          id={diffId}
          onExpandedChange={(open) => onExpandedChange(id, open)}
          onOpen={() => onOpen(id)}
          {...(afterBreakId === null ? {} : { afterBreakId })}
        />
      );
    }
    return (
      <AuditRow
        variant="row"
        grid={grid}
        entry={row.entry}
        diffId={diffId}
        expanded={expanded.has(id)}
        onExpandedChange={(open) => onExpandedChange(id, open)}
        onOpen={() => onOpen(id)}
        selected={selectedId === id}
        view={view}
        onRowFocus={() => {
          if (fromInside.current) onRowFocus(id);
        }}
      />
    );
  };
  return (
    <div onFocusCapture={onFocusCapture} onKeyDownCapture={onKeyDownCapture}>
      <Table<AuditGridRow>
        grid
        reflow="grid"
        caption={COPY.audit.caption}
        columns={COLUMNS}
        rows={gridRows}
        rowKey={auditGridRowKey}
        renderRow={renderRow}
        loading={loading}
        emptyState={emptyState}
        announce={ignoreTableLine}
      />
    </div>
  );
}

export const AuditGrid = memo(AuditGridImpl);
