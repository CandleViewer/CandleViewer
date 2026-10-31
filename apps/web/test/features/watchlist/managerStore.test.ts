/**
 * E08-S08 (#4702 PR (c)): SCR-101's lists (E08-D07 §4.3, D15): read on open; a new list named in place and created when
 * its name settles; duplicate and import into a new list created at once; a failed create rolled back with Retry (none
 * after a 403); a taken name (409) back to the name field; names checked first (1-80, unique, trimmed,
 * case-insensitive); a delete; a conflict settled by Reload or Overwrite; each list stored told to the panel. A fake
 * `/watchlists` (no network) whose answers the test releases.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SaveOutcome, Watchlist } from "../../../src/features/watchlist/listEdits";
import {
  createManagerStore,
  type ManagerStore,
} from "../../../src/features/watchlist/manager/managerStore";
import { createWatchlistSync, type ListChange } from "../../../src/features/watchlist/sync";
import type {
  ManagerApi,
  NewWatchlist,
  RemoveOutcome,
} from "../../../src/features/watchlist/watchlistApi";

const list = (name: string, symbols: readonly string[], n: number): Watchlist => ({
  id: `${n}${n}${n}${n}${n}${n}${n}${n}-0000-4000-8000-000000000000`,
  name,
  symbols: [...symbols],
  columns: [],
  version: 1,
  created_at: "2026-10-30T10:00:00Z",
  updated_at: "2026-10-30T10:00:00Z",
});
const MAJORS = list("Majors", ["BTCUSDT", "ETHUSDT"], 1);
const ALTS = list("Alts", ["SOLUSDT"], 2);

/** A `/watchlists` whose creates and lists the test answers; replaces and deletes answer at once. */
function fakeApi(lists: readonly Watchlist[]) {
  let read = [...lists];
  const creates: { input: NewWatchlist; answer: (outcome: SaveOutcome) => void }[] = [];
  let ids = 10;
  const api: ManagerApi = {
    list: vi.fn(async () => read),
    replace: vi.fn(async (current: Watchlist, next) => ({
      kind: "saved" as const,
      list: {
        ...current,
        ...next,
        symbols: [...next.symbols],
        columns: [...next.columns],
        version: current.version + 1,
      },
    })),
    create: vi.fn(
      (input: NewWatchlist) =>
        new Promise<SaveOutcome>((resolve) => {
          creates.push({ input, answer: resolve });
        }),
    ),
    remove: vi.fn(async (): Promise<RemoveOutcome> => ({ kind: "deleted" })),
  };
  const stored = (input: NewWatchlist): Watchlist => {
    ids += 1;
    return {
      ...list(input.name, input.symbols, ids % 10),
      id: `new-${ids}`,
      columns: [...(input.columns ?? [])],
    };
  };
  return {
    api,
    creates,
    stored,
    setRead(next: readonly Watchlist[]) {
      read = [...next];
    },
  };
}

const settle = async (): Promise<void> => {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
};

let store: ManagerStore;
afterEach(() => store?.dispose());

async function open(lists: readonly Watchlist[] = [MAJORS, ALTS]) {
  const fake = fakeApi(lists);
  const sync = createWatchlistSync();
  const heard: ListChange[] = [];
  sync.subscribe((change) => heard.push(change));
  store = createManagerStore({ api: fake.api, sync, now: () => Date.UTC(2026, 9, 31, 10, 31, 2) });
  store.load();
  await settle();
  return { ...fake, heard };
}

describe("reading", () => {
  it("reads the lists on open, the first selected", async () => {
    await open();
    expect(store.getState()).toMatchObject({ phase: "ready", selected: MAJORS.id });
    expect(store.getState().items.map((i) => [i.name, i.count, i.pending])).toEqual([
      ["Majors", 2, false],
      ["Alts", 1, false],
    ]);
  });

  it("a failed read is the failed phase; load reads again", async () => {
    const fake = fakeApi([MAJORS]);
    vi.mocked(fake.api.list).mockRejectedValueOnce(new Error("503"));
    store = createManagerStore({ api: fake.api, sync: createWatchlistSync() });
    store.load();
    await settle();
    expect(store.getState().phase).toBe("failed");
    store.load();
    await settle();
    expect(store.getState().phase).toBe("ready");
  });
});

describe("a new list (§4.3 Lists)", () => {
  it("shows at once as 'Watchlist', in rename mode, selected, not sent until its name settles", async () => {
    const { creates } = await open();
    const key = store.newList();
    expect(store.getState()).toMatchObject({ selected: key, renaming: key });
    expect(store.getState().items.at(-1)).toMatchObject({ name: "Watchlist", pending: true });
    expect(creates).toHaveLength(0);
  });

  it("Enter with a valid name creates it; once stored it is selected under its id, told to the panel", async () => {
    const { creates, stored, heard } = await open();
    const key = store.newList();
    expect(store.commitName(key, "  Breakouts ")).toBeNull();
    expect(creates[0]?.input).toEqual({ name: "Breakouts", symbols: [] });
    expect(store.getState().saving).toBe(true);
    const sent = creates[0];
    if (sent === undefined) throw new Error("no create was sent");
    const created = stored(sent.input);
    sent.answer({ kind: "saved", list: created });
    await settle();
    const item = store.getState().items.at(-1);
    expect(item).toMatchObject({ key: created.id, uiKey: key, name: "Breakouts", pending: false });
    expect(store.getState()).toMatchObject({
      selected: created.id,
      renaming: null,
      saving: false,
      savedAt: Date.UTC(2026, 9, 31, 10, 31, 2),
    });
    expect(heard).toEqual([{ kind: "stored", list: created }]);
  });

  it("Esc (or leaving the field) creates it with its default name", async () => {
    const { creates } = await open();
    const key = store.newList();
    store.cancelRename(key);
    expect(creates[0]?.input.name).toBe("Watchlist");
  });

  it("names are checked first: empty, over 80 characters, or taken (trimmed, case-insensitive)", async () => {
    await open();
    const key = store.newList();
    expect(store.commitName(key, "   ")).toBe("empty");
    expect(store.commitName(key, "x".repeat(81))).toBe("long");
    expect(store.commitName(key, " majors ")).toBe("taken");
    expect(store.getState().renaming).toBe(key);
    expect(store.checkName(MAJORS.id, "MAJORS")).toBeNull(); // its own name
  });

  it("a name taken meanwhile (409) sends it back to its name field, with the reason", async () => {
    const { creates } = await open();
    const key = store.newList();
    store.commitName(key, "Breakouts");
    creates[0]?.answer({ kind: "name_taken" });
    await settle();
    expect(store.getState()).toMatchObject({ renaming: key, nameProblem: "taken", selected: key });
    expect(store.getState().items.at(-1)).toMatchObject({ name: "Breakouts", pending: true });
  });

  it("a failed create is rolled back with the error; Retry sends it again", async () => {
    const { creates } = await open();
    store.select(ALTS.id);
    const key = store.newList();
    store.commitName(key, "Breakouts");
    creates[0]?.answer({ kind: "failed" });
    await settle();
    expect(store.getState().items.map((i) => i.name)).toEqual(["Majors", "Alts"]);
    expect(store.getState()).toMatchObject({
      selected: ALTS.id,
      createFailures: [{ kind: "failed", name: "Breakouts" }],
    });
    store.retryCreate(store.getState().createFailures[0]?.id ?? -1);
    expect(creates[1]?.input.name).toBe("Breakouts");
    expect(store.getState().createFailures).toEqual([]);
  });

  it("a refused create (403) is rolled back with no Retry", async () => {
    const { creates } = await open();
    store.cancelRename(store.newList());
    creates[0]?.answer({ kind: "refused" });
    await settle();
    expect(store.getState().createFailures).toMatchObject([{ kind: "refused", name: "Watchlist" }]);
    store.retryCreate(store.getState().createFailures[0]?.id ?? -1);
    expect(creates).toHaveLength(1);
  });

  it("the default name is free: 'Watchlist', then 'Watchlist 2'", async () => {
    await open([MAJORS, list("Watchlist", [], 3)]);
    store.newList();
    expect(store.getState().items.at(-1)?.name).toBe("Watchlist 2");
  });
});

describe("rename, duplicate, import, delete", () => {
  it("a rename saves the list with its new name and reports watchlist.renamed", async () => {
    const { api } = await open();
    const events: unknown[] = [];
    const listen = (e: Event) => events.push((e as CustomEvent).detail);
    window.addEventListener("cv:analytics", listen);
    store.startRename(MAJORS.id);
    expect(store.commitName(MAJORS.id, "Core")).toBeNull();
    window.removeEventListener("cv:analytics", listen);
    expect(store.getState().items[0]?.name).toBe("Core");
    expect(vi.mocked(api.replace).mock.calls[0]?.[1]).toMatchObject({ name: "Core" });
    expect(events).toContainEqual({ name: "watchlist.renamed", watchlist_id: MAJORS.id });
  });

  it("duplicate creates 'Majors copy' at once, with the symbols and columns, selected", async () => {
    const { creates } = await open();
    store.duplicate(MAJORS.id);
    expect(creates[0]?.input).toEqual({
      name: "Majors copy",
      symbols: MAJORS.symbols,
      columns: [],
    });
    expect(store.getState().items.at(-1)).toMatchObject({ name: "Majors copy", pending: true });
    expect(store.getState().selected).toBe(store.getState().items.at(-1)?.key);
  });

  it("import into a new list takes the name made free", async () => {
    const { creates } = await open();
    store.createFrom("Majors", ["SOLUSDT"]);
    expect(creates[0]?.input).toEqual({ name: "Majors 2", symbols: ["SOLUSDT"] });
  });

  it("a delete goes when the server says so: the next list is selected, the previous at the end", async () => {
    const { api } = await open();
    store.select(ALTS.id);
    expect(await store.remove(ALTS.id)).toEqual({ kind: "deleted" });
    expect(store.getState()).toMatchObject({ selected: MAJORS.id });
    vi.mocked(api.remove).mockResolvedValueOnce({ kind: "failed" });
    expect(await store.remove(MAJORS.id)).toEqual({ kind: "failed" });
    expect(store.getState().items.map((i) => i.name)).toEqual(["Majors"]);
    expect(await store.remove(MAJORS.id)).toEqual({ kind: "deleted" });
    expect(store.getState()).toMatchObject({ selected: null, items: [] });
  });
});

describe("a conflict (412), settled", () => {
  it("Reload adopts the list as stored now and tells the panel", async () => {
    const { api, setRead, heard } = await open();
    vi.mocked(api.replace).mockResolvedValueOnce({ kind: "conflict" });
    store.editsOf(MAJORS.id)?.remove("ETHUSDT");
    await settle();
    expect(store.editsOf(MAJORS.id)?.getState().error).toEqual({ kind: "conflict" });
    const fresh = { ...MAJORS, symbols: ["XRPUSDT"], version: 5 };
    setRead([fresh, ALTS]);
    expect(await store.resolveConflict(MAJORS.id, "reload")).toBe("done");
    expect(store.editsOf(MAJORS.id)?.getState()).toMatchObject({
      symbols: ["XRPUSDT"],
      error: null,
    });
    expect(heard).toContainEqual({ kind: "stored", list: fresh });
  });

  it("Overwrite saves the change undone over the version stored now", async () => {
    const { api, setRead } = await open();
    vi.mocked(api.replace).mockResolvedValueOnce({ kind: "conflict" });
    store.editsOf(MAJORS.id)?.remove("ETHUSDT");
    await settle();
    setRead([{ ...MAJORS, symbols: ["XRPUSDT"], version: 5 }, ALTS]);
    expect(await store.resolveConflict(MAJORS.id, "overwrite")).toBe("done");
    expect(vi.mocked(api.replace).mock.calls.at(-1)?.[0].version).toBe(5);
    expect(vi.mocked(api.replace).mock.calls.at(-1)?.[1].symbols).toEqual(["BTCUSDT"]);
  });

  it("a list deleted in another window goes from the manager", async () => {
    const { setRead } = await open();
    setRead([ALTS]);
    expect(await store.resolveConflict(MAJORS.id, "reload")).toBe("gone");
    expect(store.getState().items.map((i) => i.name)).toEqual(["Alts"]);
    expect(store.getState().selected).toBe(ALTS.id);
  });

  it("no answer leaves the conflict as it is", async () => {
    const { api } = await open();
    vi.mocked(api.list).mockRejectedValueOnce(new Error("down"));
    expect(await store.resolveConflict(MAJORS.id, "reload")).toBe("failed");
  });
});

describe("saved lists reach the panel", () => {
  it("each list a save stores is told, with its new version", async () => {
    const { heard } = await open();
    store.editsOf(MAJORS.id)?.move("ETHUSDT", 0);
    await settle();
    expect(heard).toEqual([
      { kind: "stored", list: expect.objectContaining({ id: MAJORS.id, version: 2 }) },
    ]);
    expect(store.getState().savedAt).toBe(Date.UTC(2026, 9, 31, 10, 31, 2));
  });
});

describe("#5335's lens round", () => {
  it("A-5335-01: a commit of a draft already sent sends nothing more (the field's blur after Enter)", async () => {
    const { creates } = await open();
    const key = store.newList();
    expect(store.commitName(key, "Breakouts")).toBeNull();
    expect(store.commitName(key, "Breakouts")).toBeNull();
    store.cancelRename(key);
    expect(creates).toHaveLength(1);
  });

  it("C-5335-08: a name drops its control and format characters (Cc, Cf) before it is checked and sent", async () => {
    const { creates } = await open();
    const key = store.newList();
    expect(store.commitName(key, "\u202e\u200b\t")).toBe("empty");
    expect(store.commitName(key, "Core\u200b \u0007")).toBeNull();
    expect(creates[0]?.input.name).toBe("Core");
    store.startRename(MAJORS.id);
    expect(store.commitName(MAJORS.id, "Al\u200dts")).toBe("taken"); // "Alts" once the format character goes
  });

  it("C-5335-01: a duplicate copies the symbols kept (the Trading ones) and returns those left out", async () => {
    const { creates } = await open([list("Old", ["BTCUSDT", "LUNAUSDT"], 1)]);
    const copy = store.duplicate(list("Old", [], 1).id, (symbol) => symbol !== "LUNAUSDT");
    expect(copy).toEqual({ name: "Old copy", left: ["LUNAUSDT"] });
    expect(creates[0]?.input).toEqual({ name: "Old copy", symbols: ["BTCUSDT"], columns: [] });
    // no predicate: every symbol
    expect(store.duplicate(list("Old", [], 1).id)).toEqual({ name: "Old copy 2", left: [] });
    expect(store.duplicate("no such list")).toBeNull();
  });

  it("C-5335-03: a failed create keeps its identity while other things change, so it is said once", async () => {
    const { creates } = await open();
    store.commitName(store.newList(), "Breakouts");
    creates[0]?.answer({ kind: "failed" });
    await settle();
    const [failure] = store.getState().createFailures;
    store.select(ALTS.id);
    store.select(MAJORS.id);
    store.editsOf(MAJORS.id)?.move("ETHUSDT", 0);
    await settle();
    expect(store.getState().createFailures[0]).toBe(failure);
  });

  it("C-5335-12: two failed creates keep both, each with its own Retry", async () => {
    const { creates } = await open();
    store.commitName(store.newList(), "One");
    store.commitName(store.newList(), "Two");
    creates[0]?.answer({ kind: "failed" });
    creates[1]?.answer({ kind: "failed" });
    await settle();
    const failures = store.getState().createFailures;
    expect(failures.map((f) => f.name)).toEqual(["One", "Two"]);
    store.retryCreate(failures[0]?.id ?? -1);
    expect(creates[2]?.input.name).toBe("One");
    expect(store.getState().createFailures.map((f) => f.name)).toEqual(["Two"]);
  });

  it("C-5335-12: Esc after a 409 on a duplicate keeps the copy's own name, made free of the one refused", async () => {
    const { creates } = await open();
    store.duplicate(MAJORS.id);
    creates[0]?.answer({ kind: "name_taken" });
    await settle();
    const key = store.getState().renaming;
    if (key === null) throw new Error("the copy is not back in its name field");
    store.cancelRename(key);
    expect(creates[1]?.input.name).toBe("Majors copy 2");
  });

  it("C-5335-04: Overwrite runs once per list: a second press while it runs joins it; one replace", async () => {
    const { api, setRead } = await open();
    vi.mocked(api.replace).mockResolvedValueOnce({ kind: "conflict" });
    store.editsOf(MAJORS.id)?.remove("ETHUSDT");
    await settle();
    setRead([{ ...MAJORS, symbols: ["XRPUSDT"], version: 5 }, ALTS]);
    const before = vi.mocked(api.replace).mock.calls.length;
    const first = store.resolveConflict(MAJORS.id, "overwrite");
    expect(store.getState().resolving).toEqual([MAJORS.id]);
    const second = store.resolveConflict(MAJORS.id, "overwrite");
    expect(await Promise.all([first, second])).toEqual(["done", "done"]);
    await settle();
    expect(vi.mocked(api.replace).mock.calls.length - before).toBe(1);
    expect(store.editsOf(MAJORS.id)?.getState().symbols).toEqual(["BTCUSDT"]);
    expect(store.getState().resolving).toEqual([]);
  });
});
