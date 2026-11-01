/**
 * E08-S08 (#4702): SCR-102's "Add to watchlist…" item (E08-D05 §6.3; E08-D07 D36, board 08 "Adding from search"):
 * the submenu of the user's lists as read, the list SCR-100 showed last first, a list that holds the symbol shown with
 * its outcome (never T2), a full one T2 with D10's words, "New watchlist with ETHUSDT" with no list, and the item T2
 * without `workspaces:write`.
 */
import { describe, expect, it, vi } from "vitest";
import type { MenuItem } from "@candleviewer/ui";
import type { Watchlist } from "../../../src/features/watchlist/listEdits";
import {
  watchlistChooserItem,
  type ChooserActions,
  type ChooserLists,
} from "../../../src/features/watchlist/searchChooser";

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

  it("while the lists are read, one busy item; if they cannot be, one that says so", () => {
    const loading = sub(
      watchlistChooserItem("ETHUSDT", { kind: "loading" }, true, undefined, actions()),
    );
    expect(loading).toMatchObject([{ label: "Loading watchlists…", busy: true }]);
    const failed = sub(
      watchlistChooserItem("ETHUSDT", { kind: "failed" }, true, undefined, actions()),
    );
    expect(failed).toMatchObject([{ label: "Watchlists could not be loaded.", disabled: true }]);
  });
});
