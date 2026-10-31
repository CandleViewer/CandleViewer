/**
 * E08-S08 (#4702 PR (c)): what SCR-101 tells SCR-100: a plain channel, and a list in only as a newer version.
 */
import { describe, expect, it, vi } from "vitest";
import type { Watchlist } from "../../../src/features/watchlist/listEdits";
import { createWatchlistSync, upsertList } from "../../../src/features/watchlist/sync";

const MAJORS: Watchlist = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "Majors",
  symbols: ["BTCUSDT"],
  columns: [],
  version: 2,
  created_at: "2026-10-30T10:00:00Z",
  updated_at: "2026-10-30T10:00:00Z",
};

describe("upsertList", () => {
  it("replaces a list with a newer version in its place, never an older or the same one", () => {
    const alts = { ...MAJORS, id: "22222222-2222-4222-8222-222222222222", name: "Alts" };
    const lists = [MAJORS, alts];
    const newer = { ...MAJORS, symbols: [], version: 3 };
    expect(upsertList(lists, newer)).toEqual([newer, alts]);
    expect(upsertList(lists, { ...MAJORS, version: 1 })).toBe(lists);
    expect(upsertList(lists, { ...MAJORS, symbols: [] })).toBe(lists);
  });

  it("appends a list it does not hold", () => {
    const created = { ...MAJORS, id: "33333333-3333-4333-8333-333333333333", version: 1 };
    expect(upsertList([MAJORS], created)).toEqual([MAJORS, created]);
  });
});

describe("createWatchlistSync", () => {
  it("tells every listener until it lets go", () => {
    const sync = createWatchlistSync();
    const heard = vi.fn();
    const off = sync.subscribe(heard);
    sync.publish({ kind: "reread" });
    off();
    sync.publish({ kind: "reread" });
    expect(heard).toHaveBeenCalledOnce();
  });
});
