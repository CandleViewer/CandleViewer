/**
 * SCR-135's grid (E42-S04; E42-D04 §4 Columns, D6, AL-3, AL-28): CMP-049 in grid mode, captioned
 * `audit.caption`, its rows CMP-173's `row` variant and, under an expanded entry, its diff row
 * (`AuditRowDiff`), both through CMP-049's row contract. Time is the one `aria-sort` column, never
 * operable (D6). A row opens SCR-136 once the drawer comes (D14), with its selection and its
 * keys. At 200 % the rows reflow to cards that keep the grid (`reflow="grid"`, AL-28). The grid
 * says no line of its own: the page owns them (AL-2, AL-15).
 *
 * The grid is memoised and every prop its host passes is stable, so a page re-read that changed
 * nothing renders no row (the build plan's §9; CMP-049 memoises none): all 200 rows are drawn
 * whole, as a windowed grid assumes fixed row heights, which an expanded row breaks (BQ-11).
 */
import { memo, useMemo, type JSX, type ReactNode } from "react";
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
/** CMP-049's own result line: the page says its lines, and this one never (A-1135P2-06). */
const ignoreTableLine = (): void => undefined;
/** Enter on a row opens SCR-136, which comes with its drawer: nothing until then. */
const noRecord = (): void => undefined;

/** An entry's diff row's id, and its expander's (`${id}-toggle`, CMP-173), within one page. */
export const diffRowId = (prefix: string, entryId: number): string => `${prefix}-${entryId}`;

export interface AuditGridProps {
  /** The page's rows after Environment's facet (D7), newest first as read. */
  readonly rows: readonly AuditEntry[];
  /** Entries whose diff row shows (AL-3). */
  readonly expanded: ReadonlySet<number>;
  readonly view: AuditView;
  /** The page's id prefix for the diff rows and their expanders. */
  readonly idPrefix: string;
  readonly onExpandedChange: (entryId: number, expanded: boolean) => void;
  /** The first read: CMP-015 rows and `aria-busy` (AL-1). */
  readonly loading: boolean;
  /** Shown across every column when no row is drawn (AL-7, AL-26). */
  readonly emptyState: ReactNode;
}

function AuditGridImpl({
  rows,
  expanded,
  view,
  idPrefix,
  onExpandedChange,
  loading,
  emptyState,
}: AuditGridProps): JSX.Element {
  const gridRows = useMemo(() => auditGridRows(rows, expanded), [rows, expanded]);
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
          onOpen={noRecord}
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
        onOpen={noRecord}
        view={view}
      />
    );
  };
  return (
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
  );
}

export const AuditGrid = memo(AuditGridImpl);
