/**
 * SCR-101's lists (E08-D07 §4.3, D15, D24): the caller's lists as read when the manager opens, each with its
 * local-first edits (`createListEdits`: name, symbols and columns, one `PUT` in flight, rollback, Retry, Reload,
 * Overwrite), and the lists being created. A new list ("+ New watchlist") shows at once as "Watchlist" (then
 * "Watchlist 2", …) in rename mode and is created (`POST`) when its name settles: `Enter` with a valid name, `Esc` or
 * leaving the field with its default one. A duplicate ("Majors copy") or an import into a new list is created at
 * once. A create that fails is rolled back with the error (Retry after a failure, none after a 403), each failure kept
 * with its own Retry; a taken name (409) sends the new list back to its name field, and `Esc` there sends it under
 * its own name made free (a copy's "Majors copy 2", a new list's "Watchlist"). A draft is sent once: a second commit
 * while it is in flight (the field's blur after `Enter`) sends nothing. A delete runs from the confirm and the list goes
 * when the server says so. A conflict is settled once per list at a time (`resolving`). Each list stored goes to the
 * panel (`sync`), so SCR-100 never shows or saves against a stale version (C-2.12). Names are checked here first
 * (§4.3: 1-80 characters, unique among the caller's lists, trimmed and case-insensitive; their control and format
 * characters dropped, as `22` refuses them), and again by the server.
 */
import { reportWatchlist } from "../analytics";
import { createListEdits, type ListEdits, type Watchlist } from "../listEdits";
import type { WatchlistSync } from "../sync";
import type { ManagerApi, RemoveOutcome } from "../watchlistApi";
import { MANAGER_COPY, NAME_MAX } from "./copy";
import { cleanName, freeName } from "./symbolText";

/** Why a name is refused (§4.3 Validation). */
export type NameProblem = "empty" | "long" | "taken";

/** One entry of the Lists column. */
export interface ManagerItem {
  /** The list's id; a new list's local key until the server answers its create. */
  readonly key: string;
  /** Stable for the entry's life, a create included: a React key that keeps its node (and focus). */
  readonly uiKey: string;
  readonly name: string;
  readonly count: number;
  /** Not stored yet: a new list being named, or a create in flight. */
  readonly pending: boolean;
}

/** A create that was rolled back: Retry sends it again, unless it was refused (403). One object per failure. */
export interface CreateFailure {
  /** Stable for the failure's life (an announcement says it once). */
  readonly id: number;
  readonly kind: "failed" | "refused";
  readonly name: string;
}

export interface ManagerState {
  readonly phase: "loading" | "failed" | "ready";
  readonly items: readonly ManagerItem[];
  readonly selected: string | null;
  /** The entry whose name field is open. */
  readonly renaming: string | null;
  /** The server's refusal of the name being edited (a taken name on a create). */
  readonly nameProblem: NameProblem | null;
  /** The creates rolled back since the last create began, oldest first. */
  readonly createFailures: readonly CreateFailure[];
  /** The lists whose conflict is being settled (Reload, Overwrite): one at a time per list. */
  readonly resolving: readonly string[];
  /** A save or a create in flight ("Saving…"). */
  readonly saving: boolean;
  /** When the last save or create landed (the clock's ms): "Saved 10:31:02 UTC". */
  readonly savedAt: number | null;
}

export interface ManagerStore {
  getState(): ManagerState;
  subscribe(listener: () => void): () => void;
  /** Reads the lists (on open, and Retry after a failed read). */
  load(): void;
  select(key: string): void;
  /** The edits of a stored list. */
  editsOf(id: string): ListEdits | undefined;
  /** A new list, named in place; returns its key. */
  newList(): string;
  startRename(key: string): void;
  /** The name's problem, or `null` once applied (a rename saved, a new list created). */
  checkName(key: string, name: string): NameProblem | null;
  commitName(key: string, name: string): NameProblem | null;
  /** Closes the name field: a rename is dropped; a new list is created with its own name made free. */
  cancelRename(key: string): void;
  /** "Majors copy", with the symbols `keep` holds (all without it): its name and the symbols left out. */
  duplicate(
    id: string,
    keep?: (symbol: string) => boolean,
  ): { readonly name: string; readonly left: readonly string[] } | null;
  /** Import into a new list: `name` made free, created with `symbols`. */
  createFrom(name: string, symbols: readonly string[]): void;
  /** Sends the create of failure `id` again (none after a refusal). */
  retryCreate(id: number): void;
  remove(id: string): Promise<RemoveOutcome>;
  /**
   * After a conflict: the list read again and shown ("Reload Majors"), or the change undone saved over it. One at a time
   * per list: a call while one runs answers with it.
   */
  resolveConflict(id: string, how: "reload" | "overwrite"): Promise<"done" | "gone" | "failed">;
  dispose(): void;
}

interface Entry {
  readonly edits: ListEdits;
  readonly off: () => void;
}

interface Draft {
  readonly key: string;
  readonly name: string;
  /** The name `Esc` sends it with, made free: a new list's default, a copy's or an import's own. */
  readonly fallback: string;
  /** The names the server refused it (409). */
  readonly taken: readonly string[];
  readonly symbols: readonly string[];
  readonly columns?: readonly string[];
  readonly sending: boolean;
  /** What a create reports once stored (`14` SCR-101 "Analytics/audit"). */
  readonly report: "watchlist.created" | "watchlist.duplicated" | "watchlist.imported";
  /** The entry selected before it, selected again if it is rolled back. */
  readonly before: string | null;
}

export interface ManagerDeps {
  readonly api: ManagerApi;
  readonly sync: WatchlistSync;
  readonly now?: () => number;
}

export function createManagerStore({ api, sync, now = Date.now }: ManagerDeps): ManagerStore {
  const listeners = new Set<() => void>();
  const entries = new Map<string, Entry>();
  /** A created list's id → the key it had while it was being created. */
  const born = new Map<string, string>();
  let order: readonly string[] = [];
  let drafts: readonly Draft[] = [];
  let phase: ManagerState["phase"] = "loading";
  let selected: string | null = null;
  let renaming: string | null = null;
  let nameProblem: NameProblem | null = null;
  /** Each failure's object is kept as it is until it goes, so a subscriber sees it change only when it does. */
  let failures: readonly { readonly failure: CreateFailure; readonly draft: Draft }[] = [];
  let createFailures: readonly CreateFailure[] = [];
  const settling = new Map<string, Promise<"done" | "gone" | "failed">>();
  let savedAt: number | null = null;
  let seq = 0;
  let failureSeq = 0;
  let reading: AbortController | null = null;

  const items = (): readonly ManagerItem[] => [
    ...order.flatMap((id): ManagerItem[] => {
      const shown = entries.get(id)?.edits.getState();
      return shown === undefined
        ? []
        : [
            {
              key: id,
              uiKey: born.get(id) ?? id,
              name: shown.name,
              count: shown.symbols.length,
              pending: false,
            },
          ];
    }),
    ...drafts.map((d) => ({
      key: d.key,
      uiKey: d.key,
      name: d.name,
      count: d.symbols.length,
      pending: true,
    })),
  ];
  const snapshot = (): ManagerState => ({
    phase,
    items: items(),
    selected,
    renaming,
    nameProblem,
    createFailures,
    resolving: [...settling.keys()],
    saving:
      drafts.some((d) => d.sending) || [...entries.values()].some((e) => e.edits.getState().saving),
    savedAt,
  });
  let state = snapshot();
  const emit = (): void => {
    state = snapshot();
    for (const listener of [...listeners]) listener();
  };

  /** A stored list joins the manager with its own edits; each save of it goes to the panel. */
  const enter = (list: Watchlist): void => {
    if (entries.has(list.id)) return;
    const edits = createListEdits(list, api, (saved) => {
      // The edits told their own change first; "Saved 10:31:02 UTC" follows it.
      savedAt = now();
      sync.publish({ kind: "stored", list: saved });
      emit();
    });
    entries.set(list.id, { edits, off: edits.subscribe(emit) });
  };
  const drop = (id: string): void => {
    entries.get(id)?.off();
    entries.delete(id);
    const at = order.indexOf(id);
    order = order.filter((key) => key !== id);
    if (selected === id) selected = order[at] ?? order[at - 1] ?? drafts[0]?.key ?? null;
  };

  const setFailures = (next: typeof failures): void => {
    failures = next;
    createFailures = next.map((f) => f.failure);
  };
  const checkName = (key: string, name: string): NameProblem | null => {
    const trimmed = cleanName(name);
    if (trimmed === "") return "empty";
    if ([...trimmed].length > NAME_MAX) return "long";
    const folded = trimmed.toLowerCase();
    return items().some((i) => i.key !== key && i.name.trim().toLowerCase() === folded)
      ? "taken"
      : null;
  };
  const names = (): readonly string[] => items().map((i) => i.name);

  const send = (draft: Draft): void => {
    // Sent once: a second commit while it is in flight (the field's blur after `Enter`) sends nothing.
    if (drafts.some((d) => d.key === draft.key && d.sending)) return;
    const sent: Draft = { ...draft, sending: true };
    drafts = drafts.some((d) => d.key === draft.key)
      ? drafts.map((d) => (d.key === draft.key ? sent : d))
      : [...drafts, sent];
    emit();
    void api
      .create({
        name: sent.name,
        symbols: sent.symbols,
        ...(sent.columns === undefined ? {} : { columns: sent.columns }),
      })
      .catch(() => ({ kind: "failed" }) as const)
      .then((outcome) => {
        if (outcome.kind === "saved") {
          drafts = drafts.filter((d) => d.key !== sent.key);
          born.set(outcome.list.id, sent.key);
          enter(outcome.list);
          order = [...order, outcome.list.id];
          if (selected === sent.key) selected = outcome.list.id;
          savedAt = now();
          sync.publish({ kind: "stored", list: outcome.list });
          reportWatchlist(
            sent.report === "watchlist.imported"
              ? { name: sent.report, watchlist_id: outcome.list.id, count: sent.symbols.length }
              : { name: sent.report, watchlist_id: outcome.list.id },
          );
        } else if (outcome.kind === "name_taken") {
          // Taken meanwhile (another window): the new list goes back to its name field, with the reason; one that is
          // gone meanwhile has no field to go back to.
          if (!drafts.some((d) => d.key === sent.key)) return;
          const refused: Draft = { ...sent, sending: false, taken: [...sent.taken, sent.name] };
          drafts = drafts.map((d) => (d.key === sent.key ? refused : d));
          selected = sent.key;
          renaming = sent.key;
          nameProblem = "taken";
        } else {
          drafts = drafts.filter((d) => d.key !== sent.key);
          if (selected === sent.key) selected = sent.before ?? order[0] ?? null;
          failureSeq += 1;
          setFailures([
            ...failures,
            {
              failure: {
                id: failureSeq,
                kind: outcome.kind === "refused" ? "refused" : "failed",
                name: sent.name,
              },
              draft: { ...sent, sending: false },
            },
          ]);
        }
        emit();
      });
  };
  const draftOf = (
    name: string,
    symbols: readonly string[],
    report: Draft["report"],
    columns?: readonly string[],
  ): Draft => {
    seq += 1;
    return {
      key: `new-${seq}`,
      name,
      fallback: report === "watchlist.created" ? MANAGER_COPY.defaultName : name,
      taken: [],
      symbols,
      ...(columns === undefined ? {} : { columns }),
      sending: false,
      report,
      before: selected,
    };
  };

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    load() {
      reading?.abort();
      const controller = new AbortController();
      reading = controller;
      phase = "loading";
      emit();
      api.list(controller.signal).then(
        (lists) => {
          if (controller.signal.aborted) return;
          for (const list of lists) enter(list);
          order = lists.map((l) => l.id);
          if (selected === null || !order.includes(selected)) selected = order[0] ?? null;
          phase = "ready";
          emit();
        },
        () => {
          if (controller.signal.aborted) return;
          phase = "failed";
          emit();
        },
      );
    },
    select(key) {
      if (key === selected || !items().some((i) => i.key === key)) return;
      selected = key;
      emit();
    },
    editsOf: (id) => entries.get(id)?.edits,
    newList() {
      const draft = draftOf(freeName(MANAGER_COPY.defaultName, names()), [], "watchlist.created");
      drafts = [...drafts, draft];
      selected = draft.key;
      renaming = draft.key;
      nameProblem = null;
      setFailures([]);
      emit();
      return draft.key;
    },
    startRename(key) {
      if (drafts.some((d) => d.key === key && d.sending)) return;
      if (!items().some((i) => i.key === key)) return;
      selected = key;
      renaming = key;
      nameProblem = null;
      emit();
    },
    checkName,
    commitName(key, name) {
      const draft = drafts.find((d) => d.key === key);
      if (draft?.sending === true) return null; // sent already (the field's blur after `Enter`)
      const problem = checkName(key, name);
      if (problem !== null) return problem;
      const trimmed = cleanName(name);
      renaming = null;
      nameProblem = null;
      if (draft !== undefined) {
        send({ ...draft, name: trimmed });
        return null;
      }
      const edits = entries.get(key)?.edits;
      if (edits !== undefined && edits.getState().name !== trimmed) {
        edits.rename(trimmed);
        reportWatchlist({ name: "watchlist.renamed", watchlist_id: key });
      }
      emit();
      return null;
    },
    cancelRename(key) {
      if (renaming !== key) return;
      renaming = null;
      nameProblem = null;
      const draft = drafts.find((d) => d.key === key);
      if (draft !== undefined && !draft.sending) {
        // Its own name (a new list's default, a copy's, an import's), made free again: a name refused is taken.
        const others = items()
          .filter((i) => i.key !== key)
          .map((i) => i.name);
        send({ ...draft, name: freeName(draft.fallback, [...others, ...draft.taken]) });
        return;
      }
      emit();
    },
    duplicate(id, keep = () => true) {
      const shown = entries.get(id)?.edits.getState();
      if (shown === undefined) return null;
      // A create judges every symbol against the catalogue (`22` 422 `unknown_symbol`): those no longer trading stay.
      const kept = shown.symbols.filter(keep);
      const draft = draftOf(
        freeName(MANAGER_COPY.copyOf(shown.name), names()),
        kept,
        "watchlist.duplicated",
        shown.columns,
      );
      selected = draft.key;
      setFailures([]);
      send(draft);
      return { name: draft.name, left: shown.symbols.filter((symbol) => !kept.includes(symbol)) };
    },
    createFrom(name, symbols) {
      const draft = draftOf(
        freeName(name === "" ? MANAGER_COPY.defaultName : name, names()),
        symbols,
        "watchlist.imported",
      );
      selected = draft.key;
      setFailures([]);
      send(draft);
    },
    retryCreate(id) {
      const failed = failures.find((f) => f.failure.id === id);
      if (failed === undefined || failed.failure.kind === "refused") return;
      setFailures(failures.filter((f) => f !== failed));
      // The same name, unless another list took it meanwhile.
      const draft = { ...failed.draft, name: freeName(failed.draft.name, names()) };
      selected = draft.key;
      send(draft);
    },
    async remove(id) {
      const list = entries.get(id)?.edits.getState().list;
      if (list === undefined) return { kind: "deleted" };
      const outcome = await api.remove(list).catch((): RemoveOutcome => ({ kind: "failed" }));
      if (outcome.kind === "deleted") {
        drop(id);
        reportWatchlist({ name: "watchlist.deleted", watchlist_id: id });
        emit();
      }
      return outcome;
    },
    resolveConflict(id, how) {
      // One at a time per list: a second press while the re-read runs would re-adopt the list over the save in flight.
      const running = settling.get(id);
      if (running !== undefined) return running;
      const settle = (async (): Promise<"done" | "gone" | "failed"> => {
        const lists = await api.list().catch(() => null);
        const edits = entries.get(id)?.edits;
        if (lists === null || edits === undefined) return "failed";
        const fresh = lists.find((l) => l.id === id);
        if (fresh === undefined) {
          drop(id);
          return "gone";
        }
        if (how === "reload") {
          edits.adopt(fresh);
          sync.publish({ kind: "stored", list: fresh });
        } else edits.overwrite(fresh);
        return "done";
      })().finally(() => {
        settling.delete(id);
        emit();
      });
      settling.set(id, settle);
      emit();
      return settle;
    },
    dispose() {
      reading?.abort();
      for (const entry of entries.values()) entry.off();
      listeners.clear();
    },
  };
}
