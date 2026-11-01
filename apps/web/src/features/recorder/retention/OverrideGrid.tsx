/**
 * Region (c) of SCR-141, the per-symbol overrides (E16-D03 §2 (c), §6; E16-D06 KB-11, FM-08 to FM-10, SR-19, T2-06):
 * CMP-065 holding a CMP-049 grid (one roving Tab stop; arrows between cells and rows, `Enter` into a cell's control,
 * `Esc` back to the cell with the value it had when the edit began) of Symbol · Stream · Retention (days) · Action ·
 * Status · Remove; Remove shows its verb and names its object to assistive tech (the fields' pattern). A pinned
 * symbol's row stays editable and says "Exempt (pinned)": the pin exempts its data, nothing is refused. Remove only
 * stages the removal (D03-D15): the row is struck, its Status says which global rule it follows and Undo takes the
 * cell, and Undo says the Status words that return; every change goes through Apply. "Add override" appends one
 * editable row whose Symbol and Stream are chosen there (a recorded symbol and a stream it has no rule for); the row
 * joins the diff once both are. While viewing as, every control is T2 and points at the one notice; reads go on.
 */
import {
  useEffect,
  useId,
  useRef,
  useState,
  type JSX,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import {
  Button,
  Combobox,
  FormSection,
  Icon,
  NumericStepperInput,
  Select,
  Table,
  type TableColumn,
  type TableRowContext,
} from "@candleviewer/ui";
import { ACTION_OPTIONS, type WriteGate } from "./GlobalDefaults";
import { RETENTION_DECK, STREAM_WORDS } from "./retentionCopy";
import {
  SEED,
  STREAMS,
  validateDays,
  type DraftRow,
  type OfferedAction,
  type RowKey,
  type StreamKind,
  type SymbolCode,
} from "./retentionModel";
import {
  RETENTION_TEXT,
  fieldErrorText,
  removeLabel,
  removedStatusText,
  streamWord,
} from "./retentionText";

/** The row "Add override" appends, before its symbol and stream make it part of the draft. */
export interface PendingAdd {
  /** A new id for every appended row: focus moves to its Symbol (FM-08). */
  readonly id: number;
  /** What is typed in the Symbol combobox; a recorded symbol makes the row complete. */
  readonly symbol: string;
  readonly stream: StreamKind;
  /** Null until edited: the stream's effective days (D03 §6 `row-add`). */
  readonly days: number | null;
  readonly action: OfferedAction;
}

const keyOf = (row: RowKey): string => `${row.symbol ?? ""}/${row.stream}`;

/** The streams `symbol` has no row for yet: the add row offers only these, so no pair is listed twice. */
export function freeStreams(rows: readonly DraftRow[], symbol: SymbolCode): readonly StreamKind[] {
  const taken = new Set(rows.filter((r) => r.symbol === symbol).map((r) => r.stream));
  return STREAMS.filter((stream) => !taken.has(stream));
}

/** The recorded symbol the add row names, when it names one with its stream free; else null. */
export function pendingSymbol(
  pending: PendingAdd,
  symbols: readonly SymbolCode[],
  rows: readonly DraftRow[],
): SymbolCode | null {
  const wanted = pending.symbol.trim().toUpperCase();
  const known = symbols.find((s) => s === wanted);
  return known !== undefined && freeStreams(rows, known).includes(pending.stream) ? known : null;
}

/**
 * The add row's days: as typed, else its stream's effective days (D03 §6 `row-add`): the global row's while that
 * field is valid, else the seed's, as the model's `addOverride` takes them.
 */
export function pendingDays(
  pending: PendingAdd,
  globals: ReadonlyMap<StreamKind, DraftRow>,
): number {
  if (pending.days !== null) return pending.days;
  const global = globals.get(pending.stream)?.days;
  return global !== undefined && validateDays(global) === null
    ? global
    : SEED[pending.stream].hotDays;
}

export interface OverrideGridProps {
  /** The draft's override rows (symbol set), in its order: stored, then added. */
  readonly rows: readonly DraftRow[];
  readonly pending: PendingAdd | null;
  /** The global rows as they stand: a removal falls back to its stream's, the add row starts on it. */
  readonly globals: ReadonlyMap<StreamKind, DraftRow>;
  readonly pinned: ReadonlySet<SymbolCode>;
  /** The storage report's symbols: the add row's choices. */
  readonly symbols: readonly SymbolCode[];
  readonly fieldId: (key: RowKey) => string;
  readonly gate: WriteGate | null;
  readonly onDays: (key: RowKey, days: number) => void;
  readonly onAction: (key: RowKey, action: OfferedAction) => void;
  readonly onRemove: (key: RowKey) => void;
  readonly onUndo: (key: RowKey) => void;
  readonly onAdd: () => void;
  readonly onPending: (next: PendingAdd | null) => void;
  /** Once, politely (SR-19): a staged removal's Status. */
  readonly say: (text: string) => void;
}

/** One row of the grid: an override of the draft, or the add row. */
interface GridRow {
  readonly id: string;
  readonly row: DraftRow | null;
  readonly pending: PendingAdd | null;
}

const COLUMN_IDS = ["symbol", "stream", "days", "action", "status", "remove"] as const;
/**
 * The columns in `em` of the table's font (a `<col>`; Status takes what is left) and the narrowest each reads well,
 * where the grid stacks: Retention (days) holds the stepper with four digits, Action "Move to Parquet after" whole
 * (A-5353-04) and Remove its verb (A-5353-06), at both densities (measured in Chromium at 1280 x 800).
 */
const WIDTH_EM = [9, 12, 13.5, 15, null, 6] as const;
const MIN_EM = [9, 12, 13.5, 15, 9, 6] as const;
const COLUMNS: readonly TableColumn<GridRow>[] = COLUMN_IDS.map((id, i) => {
  const width = WIDTH_EM[i] ?? null;
  return {
    id,
    header: RETENTION_TEXT.grid[i] ?? id,
    minWidthEm: MIN_EM[i] ?? 8,
    ...(width === null ? {} : { widthEm: width }),
    interactive: id !== "status",
    cell: (r: GridRow) => (id === "symbol" ? (r.row?.symbol ?? r.pending?.symbol ?? "") : ""),
  };
});

const STRUCK = { textDecoration: "line-through" } as const;
/**
 * A cell's field, free to shrink with its cell: stacked, a text input's own width would hold the dialog wider than a
 * 320 px viewport (A-5353-09); it grows into the cell instead.
 */
const SHRINK = { contain: "inline-size", flex: "1 1 auto" } as const;
/** The days field keeps the stepper with four digits; stacked, the cell's label wraps beside it instead. */
const SHRINK_DAYS = { ...SHRINK, minInlineSize: "10rem" } as const;
const [, , , , , REMOVE] = RETENTION_TEXT.grid;

/**
 * Remove's words: the verb shown, its object after it for assistive tech only (A-5353-06), as the fields name their
 * row; the name stays the deck's `retention.remove`, and a T2 lock still leads it.
 */
function removeWords(label: string): ReactNode {
  if (!label.startsWith(REMOVE)) return label;
  return (
    <>
      {REMOVE}
      <span className="cv-visually-hidden">{label.slice(REMOVE.length)}</span>
    </>
  );
}
const DAYS_UNIT = RETENTION_DECK["retention.field.days"][1];
const [EXEMPT] = RETENTION_DECK["retention.exempt"];
const [, DAYS_HEADER, ACTION_HEADER] = RETENTION_TEXT.global;

type Part = "undo" | "remove" | "symbol";
type Focus = { readonly row: string; readonly part: Part } | null;

export function OverrideGrid({
  rows,
  pending,
  globals,
  pinned,
  symbols,
  fieldId,
  gate,
  onDays,
  onAction,
  onRemove,
  onUndo,
  onAdd,
  onPending,
  say,
}: OverrideGridProps): JSX.Element {
  const id = useId();
  const addRef = useRef<HTMLSpanElement>(null);
  const [focus, setFocus] = useState<Focus>(null);
  /** `Esc` in a cell's field drops its typed text: the field is drawn afresh and its blur commit ignored. */
  const discard = useRef<string | null>(null);
  const [drawn, setDrawn] = useState<ReadonlyMap<string, number>>(new Map());
  /** Each field's committed value when its edit began (focus came in): what `Esc` restores. */
  const began = useRef(new Map<string, number>());
  const partId = (row: string, part: string): string => `${id}-${row}-${part}`;
  const t2 = gate === null ? {} : { disabledReason: gate.reason };
  const t2Button =
    gate === null ? {} : { disabledReason: gate.reason, disabledReasonId: gate.noticeId };

  // FM-08: a new add row takes focus on its Symbol.
  const pendingId = pending?.id ?? null;
  useEffect(() => {
    if (pendingId !== null) setFocus({ row: "pending", part: "symbol" });
  }, [pendingId]);
  // FM-08 to FM-10: the focus a press asked for, once the row has drawn it.
  useEffect(() => {
    if (focus === null) return;
    const target = document.getElementById(`${id}-${focus.row}-${focus.part}`);
    (focus.part === "symbol" ? target?.querySelector("input") : target)?.focus();
    setFocus(null);
  }, [focus, id]);
  useEffect(() => {
    discard.current = null;
  }, [drawn]);

  const gridRows: GridRow[] = [
    ...rows.map((row) => ({ id: keyOf(row), row, pending: null })),
    ...(pending === null ? [] : [{ id: "pending", row: null, pending }]),
  ];

  /**
   * Esc in a cell's field ends the edit: the value it had when the edit began comes back (each arrow step committed),
   * the typed text is dropped and the cell takes focus. All here, in the capture phase: the field is drawn afresh,
   * and a browser commits that before the grid's own Esc handler could run (A-5353-02), so the key stops here and
   * never reaches the dialog's Esc.
   */
  const escape = (row: string, key: RowKey, now: number) => (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    const was = began.current.get(row);
    began.current.delete(row);
    discard.current = row;
    setDrawn((prev) => new Map(prev).set(row, (prev.get(row) ?? 0) + 1));
    if (was !== undefined && was !== now) onDays(key, was);
    event.currentTarget.closest("td")?.focus();
  };
  const days = (row: string, key: RowKey) => (next: number) => {
    if (discard.current !== row) onDays(key, next);
  };

  /** The Status words of a live row: its error line, "Exempt (pinned)" or "—". */
  function statusWords(n: number, symbol: string): string {
    const error = validateDays(n);
    if (error !== null) return fieldErrorText(error);
    return pinned.has(symbol) ? EXEMPT : "—";
  }

  /** The Status cell (D03 §6): the removal's rule, the error line, "Exempt (pinned)" or "—". */
  function status(errorId: string, n: number, symbol: string, removed: DraftRow | null): ReactNode {
    if (removed !== null) {
      return (
        <span style={STRUCK}>{removedStatusText(globals.get(removed.stream)?.days ?? n)}</span>
      );
    }
    const error = validateDays(n);
    return (
      <span style={{ display: "inline-flex", gap: "var(--space-inset-xs)", alignItems: "center" }}>
        {error !== null ? (
          <span style={{ color: "var(--color-status-danger-strong)", display: "inline-flex" }}>
            <Icon name="danger" />
          </span>
        ) : pinned.has(symbol) ? (
          <>
            <span style={{ color: "var(--color-text-secondary)", display: "inline-flex" }}>
              <Icon name="pin" />
            </span>
            {EXEMPT}
          </>
        ) : (
          "—"
        )}
        {/* SR-17: the error line, said once politely as it changes; in the row from its first paint. */}
        <span id={errorId} aria-live="polite">
          {error === null ? null : fieldErrorText(error)}
        </span>
      </span>
    );
  }

  function savedRow(r: GridRow, row: DraftRow, grid: TableRowContext): JSX.Element {
    const symbol = row.symbol ?? "";
    const key: RowKey = { symbol: row.symbol, stream: row.stream };
    const name = `${symbol} ${streamWord(row.stream)}`;
    const errorId = partId(r.id, "error");
    const statusId = partId(r.id, "status");
    const cell = (column: number, content: ReactNode, controls = true) => (
      <td {...grid.cellProps(column)} data-cv-interactive={controls ? "" : undefined}>
        {grid.label(column)}
        {content}
      </td>
    );
    const struck = (text: string): ReactNode =>
      row.removed ? <span style={STRUCK}>{text}</span> : text;
    return (
      <tr {...grid.rowProps}>
        <th {...grid.cellProps(0, { header: true })}>
          {grid.label(0)}
          {struck(symbol)}
        </th>
        {cell(1, struck(STREAM_WORDS[row.stream]), false)}
        {row.removed
          ? cell(2, struck(`${row.days} ${DAYS_UNIT}`), false)
          : cell(
              2,
              // The field's own keys stay its own; Esc ends the edit here (see `escape`).
              <div
                style={SHRINK_DAYS}
                onKeyDownCapture={escape(r.id, key, row.days)}
                onFocusCapture={() => {
                  if (!began.current.has(r.id)) began.current.set(r.id, row.days);
                }}
                onBlurCapture={() => began.current.delete(r.id)}
              >
                <NumericStepperInput
                  key={drawn.get(r.id) ?? 0}
                  id={fieldId(key)}
                  label={`${name} ${DAYS_HEADER}`}
                  value={row.days}
                  step={1}
                  largeStep={10}
                  precision={0}
                  suffix={DAYS_UNIT}
                  invalid={validateDays(row.days) !== null}
                  aria-describedby={errorId}
                  {...t2}
                  onChange={days(r.id, key)}
                />
              </div>,
            )}
        {row.removed
          ? cell(3, struck(RETENTION_DECK[`retention.action.${row.action}`][0]), false)
          : cell(
              3,
              <Select
                aria-label={`${name} ${ACTION_HEADER}`}
                options={ACTION_OPTIONS}
                value={row.action}
                {...t2}
                onChange={(value) => {
                  const action = ACTION_OPTIONS.find((o) => o.value === value)?.value;
                  if (action !== undefined) onAction(key, action);
                }}
              />,
            )}
        <td {...grid.cellProps(4)} id={statusId}>
          {grid.label(4)}
          {status(errorId, row.days, symbol, row.removed ? row : null)}
        </td>
        {cell(
          5,
          row.removed ? (
            <Button
              id={partId(r.id, "undo")}
              variant="ghost"
              size="sm"
              aria-describedby={statusId}
              {...t2Button}
              onClick={() => {
                onUndo(key);
                // SR-19, BQ-07 (c): the Status words that return, said once.
                say(statusWords(row.days, symbol));
                setFocus({ row: r.id, part: "remove" });
              }}
            >
              {RETENTION_DECK["retention.undo"][0]}
            </Button>
          ) : (
            <Button
              id={partId(r.id, "remove")}
              variant="ghost"
              size="sm"
              {...t2Button}
              onClick={() => {
                onRemove(key);
                say(removedStatusText(globals.get(row.stream)?.days ?? row.days));
                setFocus({ row: r.id, part: "undo" });
              }}
            >
              {removeWords(removeLabel(symbol, row.stream))}
            </Button>
          ),
        )}
      </tr>
    );
  }

  function addRow(p: PendingAdd, grid: TableRowContext): JSX.Element {
    const chosen = pendingSymbol(p, symbols, rows);
    const streams = chosen === null ? STREAMS : freeStreams(rows, chosen);
    const n = pendingDays(p, globals);
    const key: RowKey = { symbol: chosen ?? p.symbol, stream: p.stream };
    const errorId = partId("pending", "error");
    const options = symbols
      .filter((s) => freeStreams(rows, s).length > 0)
      .map((s) => ({ value: s, label: s }));
    const cell = (column: number, content: ReactNode, controls = true) => (
      <td {...grid.cellProps(column)} data-cv-interactive={controls ? "" : undefined}>
        {grid.label(column)}
        {content}
      </td>
    );
    return (
      <tr {...grid.rowProps}>
        <th {...grid.cellProps(0, { header: true })} data-cv-interactive="">
          {grid.label(0)}
          <div id={partId("pending", "symbol")} style={SHRINK}>
            <Combobox
              aria-label={RETENTION_TEXT.grid[0]}
              value={p.symbol}
              options={options}
              {...t2}
              onChange={(value) => {
                const free = freeStreams(rows, value.trim().toUpperCase());
                const stream = free.includes(p.stream) ? p.stream : (free[0] ?? p.stream);
                onPending({ ...p, symbol: value, stream });
              }}
            />
          </div>
        </th>
        {cell(
          1,
          <Select
            aria-label={RETENTION_TEXT.grid[1]}
            options={streams.map((s) => ({ value: s, label: STREAM_WORDS[s] }))}
            value={p.stream}
            {...t2}
            onChange={(value) => {
              const stream = STREAMS.find((s) => s === value);
              if (stream !== undefined) onPending({ ...p, stream });
            }}
          />,
        )}
        {cell(
          2,
          <div style={SHRINK_DAYS}>
            <NumericStepperInput
              id={fieldId(key)}
              label={DAYS_HEADER}
              value={n}
              step={1}
              largeStep={10}
              precision={0}
              suffix={DAYS_UNIT}
              invalid={validateDays(n) !== null}
              aria-describedby={errorId}
              {...t2}
              onChange={(next) => onPending({ ...p, days: next })}
            />
          </div>,
        )}
        {cell(
          3,
          <Select
            aria-label={ACTION_HEADER}
            options={ACTION_OPTIONS}
            value={p.action}
            {...t2}
            onChange={(value) => {
              const action = ACTION_OPTIONS.find((o) => o.value === value)?.value;
              if (action !== undefined) onPending({ ...p, action });
            }}
          />,
        )}
        <td {...grid.cellProps(4)}>
          {grid.label(4)}
          {status(errorId, n, chosen ?? "", null)}
        </td>
        {cell(
          5,
          <Button
            variant="ghost"
            size="sm"
            {...t2Button}
            onClick={() => {
              onPending(null);
              addRef.current?.querySelector("button")?.focus();
            }}
          >
            {removeWords(removeLabel(chosen ?? p.symbol.trim(), p.stream).replace(/\s+/g, " "))}
          </Button>,
        )}
      </tr>
    );
  }

  const [rule] = RETENTION_DECK["retention.rule"];
  return (
    <FormSection
      title={RETENTION_DECK["retention.section.overrides"][0]}
      description={rule.slice(0, rule.indexOf(".") + 1)}
      headingLevel={3}
    >
      {gridRows.length === 0 ? null : (
        <Table
          columns={COLUMNS}
          rows={gridRows}
          rowKey={(r) => r.id}
          caption={RETENTION_DECK["retention.section.overrides"][0]}
          captionHidden
          grid
          renderRow={(r, grid) =>
            r.pending !== null
              ? addRow(r.pending, grid)
              : r.row === null
                ? null
                : savedRow(r, r.row, grid)
          }
        />
      )}
      <span ref={addRef}>
        <Button variant="secondary" iconLeft="plus" {...t2Button} onClick={onAdd}>
          {RETENTION_DECK["retention.add"][0]}
        </Button>
      </span>
    </FormSection>
  );
}
