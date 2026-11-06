/**
 * SCR-101's symbol grid (E08-D07 §4.3 Reorder, §6.4, §6.5; board 11): CMP-049 in grid mode over the selected list,
 * one row per symbol in its order: "#", the symbol (the row's header), then "Move BTCUSDT up", "Move BTCUSDT down" and
 * "Remove BTCUSDT", each a cell the arrows reach, focus on its one button (CMP-049's widget cell), one Tab stop for the
 * grid. A press moves the row and focus stays on the pressed button of the moved row, so repeated presses keep moving
 * it; `Alt+↑`/`Alt+↓` on any cell of a row does the same, and `Del` removes the row, focus going to the next row (else
 * the previous). The ends are T2 (2b: the lock badge, the reason in CMP-016's echo and the description): "Already
 * first.", "Already last."; without `workspaces:write` every move and removal is T2 with the notice's reason. A refused
 * press or key changes nothing and says the reason once (the gated announcement). The drag handle leads the Move up
 * cell (`aria-hidden`: the buttons are the accessible path): a row dropped on another takes its place.
 */
import { useEffect, useRef, type DragEvent, type JSX, type KeyboardEvent } from "react";
import {
  EmptyState,
  Icon,
  IconButton,
  Table,
  type TableColumn,
  type TableRowContext,
} from "@candleviewer/ui";
import { COPY } from "../copy";
import { MANAGER_COPY } from "./copy";

const HANDLE = {
  display: "inline-flex",
  verticalAlign: "middle",
  color: "var(--color-text-secondary)",
  cursor: "grab",
} as const;

/** The grid's columns; the rows draw their own cells (`renderRow`). */
const COLUMNS: readonly TableColumn<string>[] = [
  { id: "position", header: MANAGER_COPY.position, cell: () => null, align: "end", minWidthEm: 3 },
  { id: "symbol", header: MANAGER_COPY.symbol, cell: (symbol) => symbol, minWidthEm: 8 },
  { id: "up", header: MANAGER_COPY.moveUpHeader, cell: () => null, minWidthEm: 6 },
  { id: "down", header: MANAGER_COPY.moveDownHeader, cell: () => null, minWidthEm: 6 },
  { id: "remove", header: MANAGER_COPY.removeHeader, cell: () => null, minWidthEm: 6 },
];

export interface SymbolsGridProps {
  readonly name: string;
  readonly symbols: readonly string[];
  /** T2 for every write, and the notice that shows it. */
  readonly writeReason: string | undefined;
  readonly noticeId: string | undefined;
  /** Says a line once through the surface's announcer. */
  readonly say: (text: string) => void;
  /** Moves `symbol` to index `to`. */
  readonly onMove: (symbol: string, to: number) => void;
  readonly onRemove: (symbol: string) => void;
  /** A row to focus once it shows (the first added after a paste or an import), then `onFocused`. */
  readonly focusSymbol: string | null;
  readonly onFocused: () => void;
}

/**
 * A cell whose one button takes focus in its place: the cell carries the grid's place and drops its roving
 * `tabindex`, which goes to the button (CMP-049's own widget cells do the same; its row contract names no such cell).
 */
function widgetCell(grid: TableRowContext, column: number) {
  const { tabIndex, ...cell } = grid.cellProps(column);
  return { cell: { ...cell, "data-cv-widget": "" }, tabIndex };
}

export function SymbolsGrid(props: SymbolsGridProps): JSX.Element {
  const { name, symbols, writeReason, noticeId, say } = props;
  const root = useRef<HTMLDivElement>(null);
  const dragging = useRef<string | null>(null);

  const { focusSymbol, onFocused } = props;
  useEffect(() => {
    if (focusSymbol === null) return;
    const row = [...(root.current?.querySelectorAll<HTMLElement>("tr[data-symbol]") ?? [])].find(
      (node) => node.dataset["symbol"] === focusSymbol,
    );
    if (row === undefined) return;
    row.querySelector<HTMLElement>('[role="rowheader"], th')?.focus();
    onFocused();
  }, [focusSymbol, symbols, onFocused]);

  const gate = (reason: string | undefined) =>
    reason === undefined
      ? {}
      : {
          disabledReason: reason,
          ...(reason === writeReason && noticeId !== undefined
            ? { disabledReasonId: noticeId }
            : {}),
        };
  const reasons = (index: number) => ({
    up: writeReason ?? (index === 0 ? COPY.first : undefined),
    down: writeReason ?? (index === symbols.length - 1 ? COPY.last : undefined),
  });
  const move = (symbol: string, index: number, direction: "up" | "down"): void => {
    const to = index + (direction === "up" ? -1 : 1);
    props.onMove(symbol, to);
    say(COPY.moved(symbol, to + 1, symbols.length));
  };

  const renderRow = (symbol: string, grid: TableRowContext): JSX.Element => {
    const index = grid.index;
    const why = reasons(index);
    const onKeyDown = (event: KeyboardEvent<HTMLTableRowElement>): void => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.shiftKey) return;
      const arrow = event.key === "ArrowUp" ? "up" : event.key === "ArrowDown" ? "down" : null;
      if (event.altKey && arrow !== null) {
        event.preventDefault();
        const refused = why[arrow];
        if (refused !== undefined) {
          if (!event.repeat) grid.refuse(refused);
        } else move(symbol, index, arrow);
        return;
      }
      if (event.altKey || event.key !== "Delete") return;
      event.preventDefault();
      if (event.repeat) return; // a held key removes one
      if (writeReason !== undefined) grid.refuse(writeReason);
      else props.onRemove(symbol);
    };
    const onDragOver = (event: DragEvent<HTMLTableRowElement>): void => {
      if (dragging.current === null) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
    };
    const onDrop = (event: DragEvent<HTMLTableRowElement>): void => {
      const from = dragging.current;
      dragging.current = null;
      if (from === null) return;
      event.preventDefault();
      if (from === symbol) return;
      props.onMove(from, index);
      say(COPY.moved(from, index + 1, symbols.length));
    };
    const up = widgetCell(grid, 2);
    const down = widgetCell(grid, 3);
    const remove = widgetCell(grid, 4);
    return (
      <tr
        {...grid.rowProps}
        data-symbol={symbol}
        onKeyDown={onKeyDown}
        onDragOver={onDragOver}
        onDrop={onDrop}
      >
        <td {...grid.cellProps(0, { numeric: true })}>
          {grid.label(0)}
          {index + 1}
        </td>
        <th {...grid.cellProps(1, { header: true })}>
          {grid.label(1)}
          {symbol}
        </th>
        <td {...up.cell}>
          {grid.label(2)}
          <span
            aria-hidden="true"
            style={HANDLE}
            draggable={writeReason === undefined}
            // A press here starts a drag: the grid's press handling (focus to the cell's button, the press's
            // default prevented) would stop it, so the press stays the handle's.
            onMouseDown={(event) => event.stopPropagation()}
            onDragStart={(event) => {
              dragging.current = symbol;
              event.dataTransfer.setData("text/plain", symbol);
              event.dataTransfer.effectAllowed = "move";
            }}
            onDragEnd={() => {
              dragging.current = null;
            }}
          >
            <Icon name="drag-handle" />
          </span>
          <IconButton
            icon="arrow-up"
            label={MANAGER_COPY.moveUp(symbol)}
            variant="ghost"
            tabIndex={up.tabIndex}
            {...gate(why.up)}
            onClick={() => move(symbol, index, "up")}
          />
        </td>
        <td {...down.cell}>
          {grid.label(3)}
          <IconButton
            icon="arrow-down"
            label={MANAGER_COPY.moveDown(symbol)}
            variant="ghost"
            tabIndex={down.tabIndex}
            {...gate(why.down)}
            onClick={() => move(symbol, index, "down")}
          />
        </td>
        <td {...remove.cell}>
          {grid.label(4)}
          <IconButton
            icon="close"
            label={MANAGER_COPY.remove(symbol)}
            variant="ghost"
            tabIndex={remove.tabIndex}
            {...gate(writeReason)}
            onClick={() => props.onRemove(symbol)}
          />
        </td>
      </tr>
    );
  };

  return (
    <div ref={root}>
      <Table<string>
        grid
        reflow="grid"
        caption={MANAGER_COPY.caption(name, symbols.length)}
        captionHidden
        columns={COLUMNS}
        rows={symbols}
        rowKey={(symbol) => symbol}
        rowLabel={(symbol) => symbol}
        renderRow={renderRow}
        announce={say}
        emptyState={<EmptyState title={MANAGER_COPY.emptyList(name)} />}
      />
    </div>
  );
}
