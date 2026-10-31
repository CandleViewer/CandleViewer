/**
 * SCR-101 Watchlist manager (E08-S08; E08-D07 D24, §4.3–§4.5, §6.4–§6.7; `14` SCR-101): a CMP-043 dialog at
 * `?modal=watchlists` (R-110 `/watchlist` opens it), "Watchlists", 960 px. The Lists column (create, rename with `F2`,
 * duplicate, delete with CMP-044's standard confirm, Cancel focused) and the selected list's editor (symbols in order,
 * moved by buttons, `Alt+↑/↓` or a drag, removed with `Del`; paste with a preview; import and export as plain text;
 * the list's columns). Each change applies at once and is saved; "Saving…", then "Saved 10:31:02 UTC". The lists are
 * read when it opens; each list it stores goes to SCR-100 (`sync`). It owns no live region: it says through the app's
 * one announcer, and its gated controls' refusals go there too (the shell's own `GatedAnnounceProvider` is a no-op).
 * Without `workspaces:write`: one notice under the title, every write T2 pointing at it (no list: the sentence form).
 * Focus: on the list shown when it opens (or on what the path asked for: a new list's name, the paste, the import; a
 * delete's confirm returns it to that list's option); `Esc` cancels a rename first, then closes; closing returns focus
 * to the opener, else to the page's fallback (a deep link has none). Its keys are its own (E08-D12 KB-21, KB-22): a
 * key typed in it stops at its root but `Esc` and a Global chord (`stopManagerKeys`, E08-D05 §8), so the window keymap
 * neither runs nor reports another view's command on one (the rules editor's "Rename node" on `F2`).
 */
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type JSX,
  type RefObject,
} from "react";
import {
  Button,
  ConfirmDialog,
  Dialog,
  EmptyState,
  ErrorState,
  GatedAnnounceProvider,
  InlineError,
  Skeleton,
  type ConfirmFailure,
  type MenuItem,
} from "@candleviewer/ui";
import { announce, forget } from "../../app-shell/announcer";
import { COPY } from "../copy";
import { useInstrumentFacts, type InstrumentSource } from "../instruments";
import type { WatchlistSync } from "../sync";
import type { ManagerApi } from "../watchlistApi";
import { stopManagerKeys } from "../keys";
import { MANAGER_COPY } from "./copy";
import { exportList } from "./exportList";
import { ImportControl } from "./ImportControl";
import type { ManagerIntent } from "./intent";
import { ListEditor, type EditorTab } from "./ListEditor";
import { ListsColumn } from "./ListsColumn";
import { createManagerStore, type NameProblem } from "./managerStore";
import { cleanName } from "./symbolText";

/** The announcer's keys: each line said once, the same words again on a new press. */
const KEY = "watchlists:manager";

const BODY: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "flex-start",
  gap: "var(--space-4)",
};
const NOTE: CSSProperties = { margin: 0, color: "var(--color-text-secondary)" };
const FOOTER: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: "var(--space-2)",
  inlineSize: "100%",
};
const EMPTY: CSSProperties = { flex: "1 1 24rem", minInlineSize: 0 };

/** What the page reads when the manager closes. */
export interface ManagerOutcome {
  /** The stored lists as the manager leaves them. */
  readonly listIds: readonly string[];
  /** The stored list it shows, if any. */
  readonly selectedId: string | null;
}

export interface WatchlistManagerProps {
  readonly api: ManagerApi;
  readonly sync: WatchlistSync;
  readonly instruments: InstrumentSource;
  /** The list to show first (the panel's). */
  readonly initialListId?: string | undefined;
  readonly intent?: ManagerIntent | undefined;
  /** No `workspaces:write` (E08-D07 D13): every write T2 with one notice. */
  readonly readOnly?: boolean;
  readonly onClose: (outcome: ManagerOutcome) => void;
  /** The clock (ms), for "Saved 10:31:02 UTC" and the export's stamp. */
  readonly now?: () => number;
  /** Where focus goes on close when the opener is gone or there was none (a deep link, R-110). */
  readonly fallbackFocusRef?: RefObject<HTMLElement | null>;
}

type Focus = "option" | "new" | "import" | "paste";

const nameWords = (problem: NameProblem, name: string): string =>
  problem === "empty"
    ? MANAGER_COPY.nameEmpty
    : problem === "long"
      ? MANAGER_COPY.nameLong
      : MANAGER_COPY.nameTaken(cleanName(name));

export function WatchlistManager(props: WatchlistManagerProps): JSX.Element {
  const { api, sync, instruments, readOnly = false } = props;
  const now = props.now ?? Date.now;
  const [store] = useState(() => createManagerStore({ api, sync, now }));
  useEffect(() => {
    store.load();
    return () => store.dispose();
  }, [store]);
  const state = useSyncExternalStore(store.subscribe, store.getState, store.getState);
  const facts = useInstrumentFacts(instruments);
  // A copy keeps the symbols still trading (a create refuses the others); with no index yet the server judges them.
  const trading = useMemo(
    () => new Set(facts.snapshot.entries.map((entry) => entry.symbol)),
    [facts.snapshot.entries],
  );
  const keep =
    facts.snapshot.phase === "ready" ? (symbol: string) => trading.has(symbol) : undefined;
  const base = useId();
  const optionId = useCallback((key: string): string => `${base}-list-${key}`, [base]);
  const newListId = `${base}-new`;
  const noticeId = `${base}-notice`;
  const body = useRef<HTMLDivElement>(null);

  // The surface's words go to the app's announcer (it owns no live region), each said once.
  const say = useCallback((text: string) => {
    forget(KEY);
    announce("polite", text, KEY);
  }, []);
  const sayAlert = useCallback((text: string) => {
    forget(`${KEY}:alert`);
    announce("assertive", text, `${KEY}:alert`);
  }, []);
  const writeReason = readOnly ? COPY.writeReason : undefined;

  const [tab, setTab] = useState<EditorTab>("symbols");
  const [pasteOpen, setPasteOpen] = useState(false);
  const [focusSymbol, setFocusSymbol] = useState<string | null>(null);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [deleting, setDeleting] = useState<{
    readonly key: string;
    readonly name: string;
    readonly count: number;
  } | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteFailure, setDeleteFailure] = useState<ConfirmFailure | undefined>(undefined);

  const items = state.items;
  const selected = items.find((i) => i.key === state.selected);
  const edits =
    selected === undefined || selected.pending ? undefined : store.editsOf(selected.key);
  const names = items.map((i) => i.name);
  const duplicate = (key: string): void => {
    const copy = store.duplicate(key, keep);
    if (copy !== null && copy.left.length > 0) say(MANAGER_COPY.leftOut(copy.name, copy.left));
  };

  // What the path asked for, once the lists are read (E08-D07 §6.5's initial focus otherwise).
  const intent = useRef<ManagerIntent>(
    props.intent ?? { kind: "open", listId: props.initialListId },
  );
  const applied = useRef(false);
  const apply = useRef<() => void>(() => undefined);
  apply.current = () => {
    const asked = intent.current;
    const listId = asked.kind === "create" ? undefined : (asked.listId ?? props.initialListId);
    const known = listId !== undefined && store.getState().items.some((i) => i.key === listId);
    if (known) store.select(listId);
    if (!readOnly && asked.kind === "create") {
      store.newList();
      return;
    }
    if (!readOnly && known) {
      if (asked.kind === "rename") return store.startRename(listId);
      if (asked.kind === "duplicate") duplicate(listId);
      if (asked.kind === "delete") {
        // The confirm returns focus to its opener: the list's option, never the dialog's title.
        document.getElementById(optionId(listId))?.focus();
        return openDelete(listId);
      }
      if (asked.kind === "paste") {
        setPasteOpen(true);
        return setFocus("paste");
      }
      if (asked.kind === "import") return setFocus("import");
    }
    setFocus(store.getState().selected === null ? "new" : "option");
  };
  useEffect(() => {
    if (state.phase !== "ready" || applied.current) return;
    applied.current = true;
    apply.current();
  }, [state.phase]);
  // A failed read, said once as it fails (§4.2 Errors: an alert).
  useEffect(() => {
    if (state.phase === "failed") sayAlert(COPY.loadFailed);
  }, [state.phase, sayAlert]);

  // A focus move waits until its target is drawn (the lists, the paste pane or the editor change as it does).
  useEffect(() => {
    if (focus === null) return;
    const key = state.selected;
    const target =
      focus === "option"
        ? key === null
          ? null
          : document.getElementById(optionId(key))
        : focus === "new"
          ? document.getElementById(newListId)
          : focus === "import"
            ? (body.current?.querySelector<HTMLElement>('[data-cmp="CMP-067"] button') ?? null)
            : (body.current?.querySelector<HTMLElement>("textarea") ?? null);
    if (target === null) return;
    target.focus();
    setFocus(null);
  }, [focus, state, pasteOpen, tab, optionId, newListId]);

  // Each create rolled back, said once (§4.3 Save failed; a 403 as an alert), whatever else changes after it.
  const failures = state.createFailures;
  const told = useRef(new Set<number>());
  useEffect(() => {
    for (const failure of failures) {
      if (told.current.has(failure.id)) continue;
      told.current.add(failure.id);
      if (failure.kind === "refused") sayAlert(COPY.notSent);
      else say(COPY.saveFailed(failure.name));
    }
  }, [failures, say, sayAlert]);

  function openDelete(key: string): void {
    const item = store.getState().items.find((i) => i.key === key);
    if (item === undefined || item.pending) return;
    setDeleteFailure(undefined);
    setDeleting({ key, name: item.name, count: item.count });
  }
  const confirmDelete = (): void => {
    const target = deleting;
    if (target === null) return;
    setDeleteBusy(true);
    setDeleteFailure(undefined);
    void store.remove(target.key).then((outcome) => {
      setDeleteBusy(false);
      if (outcome.kind === "deleted") {
        setDeleting(null);
        // Focus to the next list, the previous at the end, or "+ New watchlist" when none is left.
        setFocus(store.getState().selected === null ? "new" : "option");
        return;
      }
      setDeleteFailure(
        outcome.kind === "refused"
          ? { message: COPY.notSent }
          : {
              message: MANAGER_COPY.deleteFailed(target.name),
              retry: { label: COPY.retry, onClick: confirmDelete },
            },
      );
    });
  };

  const close = (): void => {
    const open = store.getState().renaming;
    if (open !== null) store.cancelRename(open);
    const stored = store.getState().items.filter((i) => !i.pending);
    const shown = stored.find((i) => i.key === store.getState().selected);
    props.onClose({ listIds: stored.map((i) => i.key), selectedId: shown?.key ?? null });
  };

  const gate =
    writeReason === undefined ? {} : { disabledReason: writeReason, disabledReasonId: noticeId };
  const actions: MenuItem[] =
    selected === undefined
      ? []
      : [
          {
            id: "rename",
            label: MANAGER_COPY.rename,
            onSelect: () => store.startRename(selected.key),
            ...gate,
          },
          {
            id: "duplicate",
            label: MANAGER_COPY.duplicate,
            onSelect: () => {
              duplicate(selected.key);
              setFocus("option");
            },
            ...gate,
          },
          {
            id: "export",
            label: MANAGER_COPY.exportItem,
            onSelect: () => {
              const shown = edits?.getState();
              if (shown !== undefined)
                exportList(
                  { id: selected.key, name: shown.name, symbols: shown.symbols },
                  new Date(now()),
                );
            },
          },
          {
            id: "delete",
            label: MANAGER_COPY.deleteItem,
            opensConfirm: true,
            onSelect: () => openDelete(selected.key),
            ...gate,
          },
        ];

  const renamed = items.find((i) => i.key === state.renaming);
  const lists = (
    <ListsColumn
      items={items}
      selected={state.selected}
      renaming={state.renaming}
      nameError={
        state.nameProblem === null || renamed === undefined
          ? undefined
          : nameWords(state.nameProblem, renamed.name)
      }
      writeReason={writeReason}
      reasonId={readOnly ? noticeId : undefined}
      optionId={optionId}
      newListId={newListId}
      onSelect={(key) => {
        store.select(key);
        setPasteOpen(false);
      }}
      onRename={(key) => store.startRename(key)}
      onDelete={openDelete}
      onNew={() => store.newList()}
      onCommit={(key, name) => {
        const problem = store.commitName(key, name);
        return problem === null ? undefined : nameWords(problem, name);
      }}
      onCancel={(key) => store.cancelRename(key)}
      refuse={say}
    />
  );

  let content: JSX.Element;
  if (state.phase === "loading") content = <Skeleton shape="row" count={4} surface="overlay" />;
  else if (state.phase === "failed")
    content = (
      <ErrorState
        form="panel"
        live="off"
        message={COPY.loadFailed}
        retry={{ label: COPY.retry, onClick: () => store.load() }}
      />
    );
  else {
    const editor =
      selected === undefined ? (
        <div style={EMPTY}>
          {readOnly ? (
            // The sentence form (E09-D09 §2.2): the reason alone, which "+ New watchlist" and "Import…" point at.
            <>
              <EmptyState title={COPY.noListsReadOnly} />
              <p id={noticeId} style={NOTE}>
                {COPY.writeReason}
              </p>
            </>
          ) : (
            <EmptyState
              title={COPY.noListsTitle}
              actions={[{ label: COPY.createList, onClick: () => store.newList() }]}
            />
          )}
          <ImportControl
            list={null}
            names={names}
            facts={facts}
            instruments={instruments}
            writeReason={writeReason}
            reasonId={readOnly ? noticeId : undefined}
            onAddTo={() => undefined}
            onImportNew={(name, symbols) => {
              store.createFrom(name, symbols);
              setFocusSymbol(symbols[0] ?? null);
              say(MANAGER_COPY.imported(symbols.length, name));
            }}
          />
        </div>
      ) : edits === undefined ? (
        // A list being created: its name and count until the server answers.
        <div style={EMPTY}>
          <p style={NOTE}>{MANAGER_COPY.heading(selected.name, selected.count)}</p>
        </div>
      ) : (
        <ListEditor
          key={selected.key}
          id={selected.key}
          edits={edits}
          shown={edits.getState()}
          names={names}
          facts={facts}
          instruments={instruments}
          writeReason={writeReason}
          noticeId={readOnly ? noticeId : undefined}
          tab={tab}
          onTab={setTab}
          pasteOpen={pasteOpen}
          onPasteOpen={(open) => {
            setPasteOpen(open);
            if (open) setFocus("paste");
          }}
          focusSymbol={focusSymbol}
          onFocusSymbol={setFocusSymbol}
          actions={actions}
          say={say}
          sayAlert={sayAlert}
          onImportNew={(name, symbols) => {
            store.createFrom(name, symbols);
            setFocusSymbol(symbols[0] ?? null);
            say(MANAGER_COPY.imported(symbols.length, name));
          }}
          resolving={state.resolving.includes(selected.key)}
          onConflict={(how) => {
            const { key, name } = selected;
            void store.resolveConflict(key, how).then((outcome) => {
              if (outcome === "gone") {
                // Deleted in another window: said, and focus to the next list (or "+ New watchlist").
                say(MANAGER_COPY.gone(name));
                setFocus(store.getState().selected === null ? "new" : "option");
              } else if (outcome === "failed") say(MANAGER_COPY.reloadFailed(name));
            });
          }}
          now={now}
        />
      );
    content = (
      <>
        {readOnly && selected !== undefined ? (
          <p id={noticeId} style={NOTE}>
            {COPY.readOnly}
          </p>
        ) : null}
        <div style={BODY}>
          {lists}
          {editor}
        </div>
        {failures.map((failure) => (
          <InlineError
            key={failure.id}
            live="off"
            message={failure.kind === "refused" ? COPY.notSent : COPY.saveFailed(failure.name)}
            {...(failure.kind === "failed"
              ? { retry: { label: COPY.retry, onClick: () => store.retryCreate(failure.id) } }
              : {})}
          />
        ))}
      </>
    );
  }

  const status = state.saving
    ? MANAGER_COPY.saving
    : state.savedAt === null
      ? ""
      : MANAGER_COPY.saved(new Date(state.savedAt).toISOString().slice(11, 19));
  return (
    // A React ancestor of the portalled dialog, so its keydown is the key stop's root for every key in it (§8).
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- not a widget: no focus, no role
    <div onKeyDown={stopManagerKeys} style={{ display: "contents" }}>
      <GatedAnnounceProvider announce={say}>
        <Dialog
          open
          size="lg"
          title={MANAGER_COPY.title}
          onOpenChange={(open) => {
            if (!open) close();
          }}
          busy={state.phase === "loading"}
          {...(props.fallbackFocusRef === undefined
            ? {}
            : { fallbackFocusRef: props.fallbackFocusRef })}
          footer={
            <div style={FOOTER}>
              <p style={NOTE}>{status}</p>
              <Button onClick={close}>{MANAGER_COPY.close}</Button>
            </div>
          }
        >
          <div ref={body}>{content}</div>
          {deleting === null ? null : (
            <ConfirmDialog
              open
              title={MANAGER_COPY.deleteTitle(deleting.name)}
              message={MANAGER_COPY.deleteBody(deleting.count)}
              confirmLabel={MANAGER_COPY.deleteConfirm(deleting.name)}
              busy={deleteBusy}
              {...(deleteFailure === undefined ? {} : { failure: deleteFailure })}
              {...(props.now === undefined ? {} : { now: props.now })}
              onConfirm={confirmDelete}
              onCancel={() => {
                setDeleting(null);
                setDeleteFailure(undefined);
              }}
            />
          )}
        </Dialog>
      </GatedAnnounceProvider>
    </div>
  );
}
