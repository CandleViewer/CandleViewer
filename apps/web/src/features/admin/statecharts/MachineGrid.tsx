/**
 * The machine grid (E42-S08 §5.1; E42-D05 §11 SI-1): CMP-049 as an APG grid (one Tab stop, roving
 * `tabindex`, the arrows by cell, Home / End, PgUp / PgDn), each row a live machine as served:
 * machine, kind, environment, state, its hash's first 8 hex with "matches the lock" or "differs",
 * chain trips, the latch ("Latched — chain trips: 2" beside the octagon, else blank), deferred
 * depth ("—", named "not recorded", when the snapshot has none) and the update time in UTC. Enter
 * on a row, or a press on it, opens its machine (§5.2): the row handles the key, as SCR-045's
 * `ChartDataTable` does, so no cell holds a control and CMP-049's own keys stay its own. A held
 * Enter opens once. Rows are drawn in the server's order (kind, key, environment): a latched row is
 * marked, never moved. At 200 % the grid reflows to cards that keep its keys (`reflow="grid"`).
 */
import {
  memo,
  useId,
  type CSSProperties,
  type JSX,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import {
  ADMIN_COPY,
  EmptyState,
  Icon,
  MonoText,
  Table,
  type TableColumn,
  type TableError,
  type TableRowContext,
} from "@candleviewer/ui";
import { INSPECTOR_COPY as COPY } from "./copy";
import { utcTime } from "./format";
import type { StatechartMachine } from "./inspectorReads";
import { kindLabel } from "./kinds";

const SILENT = (): void => undefined;
const HINT: CSSProperties = { margin: 0, color: "var(--color-text-secondary)" };
/** A served state name wraps in its cell, never runs into the next one (A-1137-d02). */
const WRAP: CSSProperties = { whiteSpace: "normal", overflowWrap: "anywhere" };

/** The octagon in `color.status.danger.strong` (D05 §16); the words carry the latch. */
const OCTAGON: CSSProperties = {
  display: "inline-flex",
  verticalAlign: "middle",
  marginInlineEnd: "var(--space-1)",
  color: "var(--color-status-danger-strong)",
};

/** A row's address in the DOM, so the page can give focus back to it: "{key}@{env}". */
export const rowIdOf = (machine: { readonly machine_key: string; readonly environment: string }) =>
  `${machine.machine_key}@${machine.environment}`;

/** `renderRow` draws every cell (`MachineRow`), so no column's `cell` is ever called. */
const HEADER_ONLY = (): string => "";

/**
 * The grid's columns: headers only, as `renderRow` draws each cell (one per column, in order). Their
 * minimums sum to 58 em, so the grid is a table at 1280 px (the rail expanded) and stacks into cards
 * at 200 % (D05 §4.2); a cell cut at its minimum keeps its whole text (the machine's in the echo).
 */
const COLUMNS: readonly TableColumn<StatechartMachine>[] = [
  { id: "machine", header: COPY.list.columns.machine, cell: HEADER_ONLY, minWidthEm: 10 },
  { id: "kind", header: COPY.facts.kind, cell: HEADER_ONLY, minWidthEm: 7 },
  { id: "environment", header: COPY.facts.environment, cell: HEADER_ONLY, minWidthEm: 5 },
  { id: "state", header: COPY.facts.state, cell: HEADER_ONLY, minWidthEm: 6 },
  { id: "hash", header: COPY.facts.hash, cell: HEADER_ONLY, minWidthEm: 8 },
  {
    id: "chain_trips",
    header: COPY.facts.chainTrips,
    cell: HEADER_ONLY,
    align: "end",
    minWidthEm: 4,
  },
  { id: "latched", header: COPY.facts.latched, cell: HEADER_ONLY, minWidthEm: 8 },
  { id: "deferred", header: COPY.facts.deferred, cell: HEADER_ONLY, align: "end", minWidthEm: 4 },
  { id: "updated", header: COPY.facts.updated, cell: HEADER_ONLY, minWidthEm: 6 },
];

/** "—", named "not recorded" for assistive technology. */
function NotRecorded(): JSX.Element {
  return (
    <>
      <span aria-hidden="true">—</span>
      <span className="cv-visually-hidden">{COPY.notRecorded}</span>
    </>
  );
}

interface RowProps {
  readonly machine: StatechartMachine;
  readonly grid: TableRowContext;
  readonly today: number;
  readonly hintId: string;
  readonly onOpen: (machine: StatechartMachine) => void;
}

function MachineRow({ machine, grid, today, hintId, onOpen }: RowProps): JSX.Element {
  const onKeyDown = (event: KeyboardEvent<HTMLTableRowElement>): void => {
    if (event.key !== "Enter" || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
      return;
    }
    event.preventDefault();
    if (!event.repeat) onOpen(machine); // a held Enter opens once
  };
  // A cell's content is one node beside its label, so a stacked card keeps it whole (A-1137-09).
  const cell = (column: number, content: ReactNode, style?: CSSProperties): JSX.Element => (
    <td {...grid.cellProps(column)}>
      {grid.label(column)}
      <span style={style}>{content}</span>
    </td>
  );
  return (
    <tr
      {...grid.rowProps}
      data-machine-row={rowIdOf(machine)}
      onKeyDown={onKeyDown}
      onClick={() => onOpen(machine)}
    >
      <th {...grid.cellProps(0, { header: true, cut: machine.machine_key, describedBy: hintId })}>
        {grid.label(0)}
        {machine.machine_key}
      </th>
      {cell(1, kindLabel(machine.machine_kind))}
      {cell(2, ADMIN_COPY.env[machine.environment])}
      {cell(3, machine.state, WRAP)}
      {cell(
        4,
        <>
          <MonoText size="sm">{machine.machine_hash.slice(0, 8)}</MonoText>
          {` · ${machine.lock_matches ? COPY.matches : COPY.differs}`}
        </>,
      )}
      <td {...grid.cellProps(5, { numeric: true })}>
        {grid.label(5)}
        <span>{String(machine.chain_trips)}</span>
      </td>
      {cell(
        6,
        machine.degraded ? (
          <>
            <span style={OCTAGON}>
              <Icon name="danger" />
            </span>
            {COPY.latched(machine.chain_trips)}
          </>
        ) : null,
      )}
      <td {...grid.cellProps(7, { numeric: true })}>
        {grid.label(7)}
        <span>
          {machine.deferred_depth === null ? <NotRecorded /> : String(machine.deferred_depth)}
        </span>
      </td>
      {cell(8, utcTime(Date.parse(machine.updated_at), today))}
    </tr>
  );
}

/** Why the grid has no rows, when it has none. */
export type GridEmpty = "none_latched" | "no_rows" | "no_rows_rowless";

export interface MachineGridProps {
  readonly machines: readonly StatechartMachine[];
  readonly loading: boolean;
  /** A first read that failed: CMP-049's error with Retry. */
  readonly error?: TableError | undefined;
  readonly empty: GridEmpty;
  /** The start of the answer's UTC day: an update on another day shows its date. */
  readonly today: number;
  /** Opens a row's machine (the page's query state, §5.2). */
  readonly onOpen: (machine: StatechartMachine) => void;
}

function emptyBlock(empty: GridEmpty): JSX.Element {
  if (empty === "none_latched") return <EmptyState title={COPY.list.noneLatched} />;
  return empty === "no_rows_rowless" ? (
    <EmptyState title={COPY.list.noRows} description={COPY.list.noRowsRowless} />
  ) : (
    <EmptyState title={COPY.list.noRows} />
  );
}

export const MachineGrid = memo(function MachineGrid({
  machines,
  loading,
  error,
  empty,
  today,
  onOpen,
}: MachineGridProps): JSX.Element {
  const hintId = useId();
  // The visible cue that a row opens (A-1137-13) and the row headers' description, while rows show.
  const rows = machines.length > 0 && !loading && error === undefined;
  return (
    <>
      {rows ? (
        <p id={hintId} style={HINT}>
          {COPY.list.openHint}
        </p>
      ) : null}
      <Table
        caption={COPY.list.machinesHeading}
        captionHidden
        columns={COLUMNS}
        rows={machines}
        rowKey={rowIdOf}
        grid
        reflow="grid"
        loading={loading}
        {...(error === undefined ? {} : { error })}
        emptyState={emptyBlock(empty)}
        announce={SILENT}
        renderRow={(machine, grid) => (
          <MachineRow
            key={rowIdOf(machine)}
            machine={machine}
            grid={grid}
            today={today}
            hintId={hintId}
            onOpen={onOpen}
          />
        )}
      />
    </>
  );
});
