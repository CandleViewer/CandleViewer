/**
 * SCR-101's editor of the selected list (E08-D07 §4.3, §6.4–§6.6; boards 10 and 11): "Majors · 12 symbols" and
 * "Actions for Majors" (Rename, Duplicate, Export, Delete…), then the Symbols and Columns tabs (CMP-042). Symbols: the
 * toolbar ("+ Add symbol", D36's popover; "Paste symbols"; "Import…"; "Export Majors"), the paste pane when open, and
 * the symbol grid. Columns: CMP-056's checklist with its move buttons (Symbol locked, Status fixed and not listed);
 * a move that changes no shown column's order is kept in the checklist for the session and saves nothing (only the
 * shown columns are stored). Each change applies at once and is saved (`PUT`, the version last read); a failure rolls
 * back with an inline error: Retry, or after a conflict "Reload Majors" and "Overwrite with my version", which step
 * aside while one runs; none after a 403. A taken name (409) names the name that was sent. Without `workspaces:write`
 * every write is T2 with the notice's reason; Export stays.
 */
import { useEffect, useRef, useState, type CSSProperties, type JSX } from "react";
import {
  Button,
  ColumnPicker,
  Heading,
  InlineError,
  Menu,
  Tabs,
  WATCHLIST_DEFAULT_COLUMNS,
  WATCHLIST_OPTIONAL_COLUMNS,
  watchlistColumns,
  type ColumnPickerColumn,
  type MenuItem,
} from "@candleviewer/ui";
import { AddSymbolPopover } from "../AddSymbolPopover";
import { reportWatchlist } from "../analytics";
import { COPY, LIST_CAP } from "../copy";
import type { InstrumentFacts, InstrumentSource } from "../instruments";
import type { EditsState, ListEdits } from "../listEdits";
import { PastePane } from "./BulkAdd";
import { MANAGER_COPY } from "./copy";
import { ImportControl } from "./ImportControl";
import { exportList } from "./exportList";
import { SymbolsGrid } from "./SymbolsGrid";

const EDITOR: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "var(--space-2)",
  flex: "1 1 24rem",
  minInlineSize: 0,
};
const HEAD: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  justifyContent: "space-between",
  gap: "var(--space-2)",
};
const TOOLBAR: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: "var(--space-2)",
  paddingBlock: "var(--space-2)",
};
const NOTE: CSSProperties = { margin: 0, color: "var(--color-text-secondary)" };
const ALL_COLUMNS: readonly string[] = [
  ...WATCHLIST_DEFAULT_COLUMNS,
  ...WATCHLIST_OPTIONAL_COLUMNS,
];
const HEADERS = new Map(
  watchlistColumns([...WATCHLIST_DEFAULT_COLUMNS, ...WATCHLIST_OPTIONAL_COLUMNS]).map((c) => [
    c.id,
    c.header,
  ]),
);

export type EditorTab = "symbols" | "columns";

export interface ListEditorProps {
  readonly id: string;
  readonly edits: ListEdits;
  readonly shown: EditsState;
  readonly names: readonly string[];
  readonly facts: InstrumentFacts;
  readonly instruments: InstrumentSource;
  readonly writeReason: string | undefined;
  readonly noticeId: string | undefined;
  readonly tab: EditorTab;
  readonly onTab: (tab: EditorTab) => void;
  readonly pasteOpen: boolean;
  readonly onPasteOpen: (open: boolean) => void;
  /** A row to focus once it shows (the first one added), then cleared. */
  readonly focusSymbol: string | null;
  readonly onFocusSymbol: (symbol: string | null) => void;
  readonly actions: readonly MenuItem[];
  readonly say: (text: string) => void;
  readonly sayAlert: (text: string) => void;
  readonly onImportNew: (name: string, symbols: readonly string[]) => void;
  /** A conflict being settled (Reload, Overwrite): its buttons step aside until it is. */
  readonly resolving: boolean;
  readonly onConflict: (how: "reload" | "overwrite") => void;
  readonly now: () => number;
}

export function ListEditor(props: ListEditorProps): JSX.Element {
  const { id, edits, shown, facts, writeReason, noticeId, say } = props;
  const { name, symbols } = shown;
  const headingId = `${id}-heading`;
  const capId = `${id}-cap`;
  const root = useRef<HTMLElement>(null);
  const [addOpen, setAddOpen] = useState(false);

  const gate =
    writeReason === undefined
      ? {}
      : {
          disabledReason: writeReason,
          ...(noticeId === undefined ? {} : { disabledReasonId: noticeId }),
        };

  // Save failures (§4.3 Save failed): rolled back, said once.
  const error = shown.error;
  const sayError = useRef<(kind: NonNullable<EditsState["error"]>["kind"]) => void>(
    () => undefined,
  );
  sayError.current = (kind) => {
    if (kind === "refused") props.sayAlert(COPY.notSent);
    else if (kind === "conflict") say(COPY.conflict(name));
    else if (kind === "name_taken") say(MANAGER_COPY.nameTaken(error?.name ?? name));
    else say(COPY.saveFailed(name));
  };
  useEffect(() => {
    if (error !== null) sayError.current(error.kind);
  }, [error]);

  /** A button that goes with what it answered hands focus to the grid's tab stop first (WCAG 2.4.3). */
  const focusGrid = (): void => {
    root.current?.querySelector<HTMLElement>('[role="grid"] [tabindex="0"]')?.focus();
  };

  const added = (symbols: readonly string[], line: string): void => {
    props.onPasteOpen(false);
    props.onFocusSymbol(symbols[0] ?? null);
    say(line);
  };
  const addAll = (wanted: readonly string[]): void => {
    const done = edits.addAll(wanted);
    if (done.length === 0) return;
    reportWatchlist({ name: "watchlist.bulk_added", watchlist_id: id, count: done.length });
    added(done, MANAGER_COPY.added(done.length, name));
  };
  const importAll = (wanted: readonly string[]): void => {
    const done = edits.addAll(wanted);
    if (done.length === 0) return;
    reportWatchlist({ name: "watchlist.imported", watchlist_id: id, count: done.length });
    added(done, MANAGER_COPY.added(done.length, name));
  };
  const move = (symbol: string, to: number): void => {
    edits.move(symbol, to);
    reportWatchlist({ name: "watchlist.reordered", watchlist_id: id, symbol, position: to + 1 });
  };
  const remove = (symbol: string): void => {
    edits.remove(symbol);
    say(MANAGER_COPY.removed(symbol));
    reportWatchlist({ name: "watchlist.symbol_removed", watchlist_id: id, symbol });
  };

  // Columns (CMP-056): the shown ones in their order, then the others; Symbol locked, Status not listed. A move that
  // leaves the shown order as it is (among or past the hidden ones) is kept here for the session, so the checklist
  // shows it where the picker said it went; it saves nothing (C-5335-07).
  const visible = (shown.columns.length > 0 ? shown.columns : WATCHLIST_DEFAULT_COLUMNS).filter(
    (c) => ALL_COLUMNS.includes(c),
  );
  const unknown = shown.columns.filter((c) => !ALL_COLUMNS.includes(c)); // a newer client's: kept as stored
  const [placed, setPlaced] = useState<readonly string[] | null>(null);
  const shownIn = (order: readonly string[]): readonly string[] =>
    order.filter((c) => visible.includes(c));
  const sameOrder = (a: readonly string[], b: readonly string[]): boolean =>
    a.length === b.length && a.every((c, i) => b[i] === c);
  // The kept order stands while it holds every column and the stored shown order; a save or a reload that changed it
  // gives the stored order back.
  const listed =
    placed !== null && placed.length === ALL_COLUMNS.length && sameOrder(shownIn(placed), visible)
      ? placed
      : [...visible, ...ALL_COLUMNS.filter((c) => !visible.includes(c))];
  const pickerColumns: ColumnPickerColumn[] = listed.map((cid) => ({
    id: cid,
    label: HEADERS.get(cid) ?? cid,
    visible: visible.includes(cid),
    ...(cid === "symbol" ? { lockedReason: COPY.symbolFixed } : {}),
  }));
  const saveColumns = (order: readonly string[], on: ReadonlySet<string>): void =>
    edits.setColumns([...order.filter((c) => on.has(c)), ...unknown]);

  const capped = symbols.length >= LIST_CAP;
  const addReason =
    writeReason !== undefined
      ? { text: writeReason, nodeId: noticeId ?? "" }
      : capped
        ? { text: COPY.capFull, nodeId: capId }
        : undefined;

  const symbolsPane = (
    <div>
      <div style={TOOLBAR}>
        <AddSymbolPopover
          listName={name}
          listSymbols={symbols}
          facts={facts}
          open={addOpen}
          onOpenChange={setAddOpen}
          onAdd={(symbol) => {
            const outcome = edits.add(symbol);
            if (outcome === "added")
              reportWatchlist({ name: "watchlist.symbol_added", watchlist_id: id, symbol });
            return outcome;
          }}
          say={say}
          reason={addReason}
          onPasteSeveral={() => props.onPasteOpen(true)}
        />
        {capped && writeReason === undefined ? (
          <span id={capId} style={NOTE}>
            {COPY.capFull}
          </span>
        ) : null}
        <span>
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={props.pasteOpen}
            {...gate}
            onClick={() => props.onPasteOpen(!props.pasteOpen)}
          >
            {MANAGER_COPY.paste}
          </Button>
        </span>
        <ImportControl
          list={{ name, symbols }}
          names={props.names}
          facts={facts}
          instruments={props.instruments}
          writeReason={writeReason}
          reasonId={noticeId}
          onAddTo={importAll}
          onImportNew={props.onImportNew}
        />
        <span>
          <Button
            variant="ghost"
            size="sm"
            iconLeft="download"
            onClick={() => exportList({ id, name, symbols }, new Date(props.now()))}
          >
            {MANAGER_COPY.exportList(name)}
          </Button>
        </span>
      </div>
      {props.pasteOpen && writeReason === undefined ? (
        <PastePane
          listName={name}
          symbols={symbols}
          facts={facts}
          instruments={props.instruments}
          onAdd={addAll}
          say={say}
        />
      ) : null}
      <SymbolsGrid
        name={name}
        symbols={symbols}
        writeReason={writeReason}
        noticeId={noticeId}
        say={say}
        onMove={move}
        onRemove={remove}
        focusSymbol={props.focusSymbol}
        onFocused={() => props.onFocusSymbol(null)}
      />
    </div>
  );
  const columnsPane = (
    <ColumnPicker
      variant="list"
      label={COPY.columns}
      columns={pickerColumns}
      announce={say}
      onChange={(cid, on) => {
        // A host ignores the picker while a write reason is set (#5146's hand-off); Symbol is always shown.
        if (writeReason !== undefined || cid === "symbol") return;
        const next = new Set(visible);
        if (on) next.add(cid);
        else next.delete(cid);
        saveColumns(listed, next);
        reportWatchlist({
          name: "watchlist.column_changed",
          watchlist_id: id,
          column: cid,
          visible: on,
        });
      }}
      onReorder={(cid, to) => {
        if (writeReason !== undefined) return;
        const order = listed.filter((c) => c !== cid);
        order.splice(to, 0, cid);
        setPlaced(order);
        if (!sameOrder(shownIn(order), visible)) saveColumns(order, new Set(visible));
      }}
      {...(writeReason === undefined
        ? {}
        : { writeReason, ...(noticeId === undefined ? {} : { writeReasonId: noticeId }) })}
    />
  );

  return (
    <section ref={root} aria-labelledby={headingId} style={EDITOR}>
      <div style={HEAD}>
        <Heading level={3} variant="heading-sm" id={headingId}>
          {MANAGER_COPY.heading(name, symbols.length)}
        </Heading>
        <Menu
          trigger={
            <Button variant="ghost" size="sm" iconRight="chevron-down">
              {MANAGER_COPY.actionsFor(name)}
            </Button>
          }
          items={props.actions}
          announceReason={say}
        />
      </div>
      <Tabs
        aria-labelledby={headingId}
        tabs={[
          { id: "symbols", label: MANAGER_COPY.symbolsTab },
          { id: "columns", label: MANAGER_COPY.columnsTab },
        ]}
        value={props.tab}
        onChange={(next) => props.onTab(next === "columns" ? "columns" : "symbols")}
        renderPanel={(tab) => (tab === "columns" ? columnsPane : symbolsPane)}
      />
      {error === null ? null : (
        <InlineError
          live="off"
          message={
            error.kind === "refused"
              ? COPY.notSent
              : error.kind === "conflict"
                ? COPY.conflict(name)
                : error.kind === "name_taken"
                  ? MANAGER_COPY.nameTaken(error.name ?? name)
                  : COPY.saveFailed(name)
          }
          {...(error.kind === "failed"
            ? {
                retry: {
                  label: COPY.retry,
                  onClick: () => {
                    focusGrid();
                    edits.retry();
                  },
                },
              }
            : error.kind === "conflict" && !props.resolving
              ? {
                  retry: {
                    label: COPY.reload(name),
                    onClick: () => {
                      focusGrid();
                      props.onConflict("reload");
                    },
                  },
                  action: {
                    label: MANAGER_COPY.overwrite,
                    onClick: () => {
                      focusGrid();
                      props.onConflict("overwrite");
                    },
                  },
                }
              : {})}
        />
      )}
    </section>
  );
}
