/**
 * E08-S08 (#4702): SCR-102's "Add to watchlist…" item (E08-D05 §6.3; E08-D07 D36, board 08 "Adding from search"):
 * the submenu of the user's lists as read, the list SCR-100 showed last first, a list that holds the symbol shown with
 * its outcome (never T2), a full one T2 with D10's words, "New watchlist with ETHUSDT" with no list, and the item T2
 * without `workspaces:write`.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { MenuItem } from "@candleviewer/ui";
import type { SaveError, SaveOutcome, Watchlist } from "../../../src/features/watchlist/listEdits";
import {
  useWatchlistChooser,
  watchlistChooserItem,
  type ChooserActions,
  type ChooserLists,
} from "../../../src/features/watchlist/searchChooser";
import type { ManagerApi } from "../../../src/features/watchlist/watchlistApi";

const list = (name: string, symbols: readonly string[], id: string): Watchlist => ({
  id,
  name,
  symbols: [...symbols],
  columns: [],
  version: 1,
  created_at: "2026-10-30T10:00:00Z",
  updated_at: "2026-10-30T10:00:00Z",
});
const MAJORS = list("Majors", ["BTCUSDT", "ETHUSDT"], "m");
const ALTS = list("Alts", ["SOLUSDT"], "a");
const FULL = list(
  "Big",
  Array.from({ length: 200 }, (_, i) => `A${String(i).padStart(3, "0")}USDT`),
  "b",
);
const ready = (...lists: Watchlist[]): ChooserLists => ({ kind: "ready", lists });

function actions() {
  return {
    add: vi.fn<ChooserActions["add"]>(),
    already: vi.fn<ChooserActions["already"]>(),
    create: vi.fn<ChooserActions["create"]>(),
  };
}
const sub = (item: MenuItem): readonly MenuItem[] => item.items ?? [];
const run = (item: MenuItem | undefined): void => item?.onSelect?.();

describe("SCR-102's 'Add to watchlist…'", () => {
  it("without workspaces:write the item is T2 with its reason and opens nothing", () => {
    const item = watchlistChooserItem("ETHUSDT", ready(MAJORS), false, undefined, actions());
    expect(item).toMatchObject({
      label: "Add to watchlist…",
      disabledReason: "Your role can't save workspaces.",
    });
    expect(sub(item)).toEqual([]);
  });

  it("the lists as read: the one SCR-100 showed last first, each named with its count", () => {
    const act = actions();
    const item = watchlistChooserItem("XRPUSDT", ready(MAJORS, ALTS), true, ALTS.id, act);
    expect(item.disabledReason).toBeUndefined();
    expect(sub(item).map((i) => i.label)).toEqual(["Alts, 1 symbol", "Majors, 2 symbols"]);
    run(sub(item)[1]);
    expect(act.add).toHaveBeenCalledExactlyOnceWith(MAJORS);
  });

  it("a list that holds the symbol shows its outcome, never T2; choosing it adds nothing and says so", () => {
    const act = actions();
    const [majors] = sub(watchlistChooserItem("ETHUSDT", ready(MAJORS), true, undefined, act));
    expect(majors).toMatchObject({ label: "Majors, 2 symbols · has ETHUSDT" });
    expect(majors?.disabledReason).toBeUndefined();
    run(majors);
    expect(act.already).toHaveBeenCalledExactlyOnceWith(MAJORS);
    expect(act.add).not.toHaveBeenCalled();
  });

  it("a full list without the symbol is T2 with D10's words", () => {
    const [big] = sub(watchlistChooserItem("ETHUSDT", ready(FULL), true, undefined, actions()));
    expect(big).toMatchObject({
      label: "Big, 200 of 200 symbols",
      disabledReason: "Watching 200 symbols — remove some to add more",
    });
  });

  it("with no list, one item creates one holding the symbol", () => {
    const act = actions();
    const [only, ...rest] = sub(watchlistChooserItem("ETHUSDT", ready(), true, undefined, act));
    expect(only?.label).toBe("New watchlist with ETHUSDT");
    expect(rest).toEqual([]);
    run(only);
    expect(act.create).toHaveBeenCalledOnce();
  });

  it("A-5335-d02: while the lists are read, the item itself is busy and opens nothing; if they cannot be, one child says so", () => {
    const loading = watchlistChooserItem(
      "ETHUSDT",
      { kind: "loading" },
      true,
      undefined,
      actions(),
    );
    // The same row throughout (the menu keys its rows by id): focus on it survives the lists arriving.
    expect(loading).toMatchObject({
      id: "watchlist",
      label: "Add to watchlist…",
      busy: true,
      description: "Loading watchlists…",
      items: [],
    });
    const loaded = watchlistChooserItem("ETHUSDT", ready(MAJORS), true, undefined, actions());
    const failed = watchlistChooserItem("ETHUSDT", { kind: "failed" }, true, undefined, actions());
    expect([loading.id, loaded.id, failed.id]).toEqual(["watchlist", "watchlist", "watchlist"]);
    expect(loaded.busy).toBeUndefined();
    expect(sub(failed)).toMatchObject([
      { label: "Watchlists could not be loaded.", disabled: true },
    ]);
  });
});

describe("SCR-102's chooser says each outcome once (C-5335-d05)", () => {
  /** The REST client as the chooser sees it; `over` answers the calls a case is about. */
  const client = (over: Partial<ManagerApi>): ManagerApi => ({
    list: async () => [MAJORS],
    replace: async (current, next) => ({
      kind: "saved",
      list: { ...current, symbols: [...next.symbols], version: current.version + 1 },
    }),
    create: async (input) => ({
      kind: "saved",
      list: list(input.name, input.symbols, "n"),
    }),
    remove: async () => ({ kind: "deleted" }),
    ...over,
  });
  const answers = (kind: SaveError) => async (): Promise<SaveOutcome> => ({ kind });
  const HOLDER = list("Majors", ["BTCUSDT", "XRPUSDT"], "m");
  type Case = readonly [name: string, over: Partial<ManagerApi>, words: string, item: string];
  const cases: readonly Case[] = [
    ["a list added to", {}, "Added XRPUSDT to Majors.", "Majors, 2 symbols"],
    [
      "a 412",
      { replace: answers("conflict") },
      "Majors changed in another window.",
      "Majors, 2 symbols",
    ],
    [
      "a 403",
      { replace: answers("refused") },
      "Not sent — your access changed.",
      "Majors, 2 symbols",
    ],
    [
      "a 503",
      { replace: answers("failed") },
      "Could not add XRPUSDT to Majors.",
      "Majors, 2 symbols",
    ],
    [
      "a list that holds it",
      { list: async () => [HOLDER] },
      "XRPUSDT is already on Majors.",
      "Majors, 2 symbols · has XRPUSDT",
    ],
    [
      "a new list",
      { list: async () => [] },
      "Added XRPUSDT to Watchlist.",
      "New watchlist with XRPUSDT",
    ],
    [
      "a taken name",
      { list: async () => [], create: answers("name_taken") },
      "A watchlist named Watchlist already exists.",
      "New watchlist with XRPUSDT",
    ],
  ];

  it.each(cases)(
    "%s: one line said, once, and focus returned once",
    async (_name, over, words, item) => {
      const say = vi.fn<(text: string) => void>();
      const done = vi.fn<() => void>();
      const api = client(over);
      const { result } = renderHook(() =>
        useWatchlistChooser(true, { writable: true, say, done, api }),
      );
      await waitFor(() => expect(sub(result.current("XRPUSDT"))[0]?.label).toBe(item));
      run(sub(result.current("XRPUSDT"))[0]);
      await waitFor(() => expect(say).toHaveBeenCalled());
      await act(async () => {
        await Promise.resolve(); // a second say would have landed by now
      });
      expect(say).toHaveBeenCalledExactlyOnceWith(words);
      expect(done).toHaveBeenCalledOnce();
    },
  );
});
