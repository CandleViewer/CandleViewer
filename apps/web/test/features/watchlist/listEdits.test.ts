/**
 * E08-S08 (#4702): SCR-100's local-first list edits (E08-D07 D15, §6.2, §6.4): each change applies at once, then
 * `PUT /watchlists/{watchlistId}` replaces the list (one save in flight, the latest state next); a failure rolls back
 * with an inline error and Retry; `Del` has Undo, which restores every removal since, in place; each saved list goes
 * back to the host, and a list read again after a conflict is adopted whole. SCR-101 (#4702 PR (c)) adds the name to
 * the change, a bulk add up to the cap, and "Overwrite with my version" after a conflict.
 */
import { describe, expect, it } from "vitest";
import {
  createListEdits,
  type ListEdits,
  type SaveOutcome,
  type Watchlist,
  type WatchlistSaver,
} from "../../../src/features/watchlist/listEdits";

const MAJORS: Watchlist = {
  id: "0b7a2f2e-6a0e-4c8e-9a52-6f0f2b1d0c11",
  name: "Majors",
  symbols: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"],
  columns: [],
  version: 3,
  created_at: "2026-10-30T10:00:00Z",
  updated_at: "2026-10-30T10:00:00Z",
};

/** A saver whose answers the test releases one by one. */
function saver() {
  const calls: {
    list: Watchlist;
    name: string | undefined;
    symbols: readonly string[];
    columns: readonly string[];
  }[] = [];
  const answers: ((outcome: SaveOutcome) => void)[] = [];
  const port: WatchlistSaver = {
    replace: (list, next) =>
      new Promise<SaveOutcome>((resolve) => {
        calls.push({ list, name: next.name, symbols: next.symbols, columns: next.columns });
        answers.push(resolve);
      }),
  };
  const saved = (symbols: readonly string[], version: number): SaveOutcome => ({
    kind: "saved",
    list: { ...MAJORS, symbols: [...symbols], version },
  });
  const answer = async (outcome: SaveOutcome) => {
    answers.shift()?.(outcome);
    // the edits read the answer in a promise callback: let it run
    await new Promise((resolve) => setTimeout(resolve, 0));
  };
  return { port, calls, saved, answer };
}

describe("local-first edits", () => {
  it("a removal shows at once and saves the whole list against the version last read", () => {
    const s = saver();
    const edits = createListEdits(MAJORS, s.port);
    edits.remove("ETHUSDT");
    expect(edits.getState().symbols).toEqual(["BTCUSDT", "SOLUSDT", "XRPUSDT"]);
    expect(s.calls).toHaveLength(1);
    expect(s.calls[0]?.list.version).toBe(3);
    expect(s.calls[0]?.symbols).toEqual(["BTCUSDT", "SOLUSDT", "XRPUSDT"]);
  });

  it("Undo restores every removal since, each in its place, in one save", async () => {
    const s = saver();
    const edits = createListEdits(MAJORS, s.port);
    edits.remove("ETHUSDT");
    await s.answer(s.saved(["BTCUSDT", "SOLUSDT", "XRPUSDT"], 4));
    edits.remove("XRPUSDT");
    await s.answer(s.saved(["BTCUSDT", "SOLUSDT"], 5));
    edits.remove("BTCUSDT");
    expect(edits.getState().removed.map((r) => r.symbol)).toEqual([
      "ETHUSDT",
      "XRPUSDT",
      "BTCUSDT",
    ]);
    await s.answer(s.saved(["SOLUSDT"], 6));
    expect(edits.undo()).toEqual(["ETHUSDT", "XRPUSDT", "BTCUSDT"]);
    expect(edits.getState().symbols).toEqual(MAJORS.symbols);
    expect(edits.getState().removed).toEqual([]);
    expect(s.calls.at(-1)?.symbols).toEqual(MAJORS.symbols);
    expect(s.calls.at(-1)?.list.version).toBe(6);
  });

  it("a change other than a removal ends the Undo run", async () => {
    const s = saver();
    const edits = createListEdits(MAJORS, s.port);
    edits.remove("ETHUSDT");
    await s.answer(s.saved(["BTCUSDT", "SOLUSDT", "XRPUSDT"], 4));
    edits.move("SOLUSDT", 0);
    expect(edits.getState().removed).toEqual([]);
    expect(edits.getState().symbols).toEqual(["SOLUSDT", "BTCUSDT", "XRPUSDT"]);
  });

  it("one save in flight: the edits made meanwhile go next, as one save of the latest list", async () => {
    const s = saver();
    const edits = createListEdits(MAJORS, s.port);
    edits.move("XRPUSDT", 0);
    edits.move("SOLUSDT", 0);
    edits.remove("BTCUSDT");
    expect(s.calls).toHaveLength(1);
    await s.answer(s.saved(["XRPUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT"], 4));
    expect(s.calls).toHaveLength(2);
    expect(s.calls[1]?.symbols).toEqual(["SOLUSDT", "XRPUSDT", "ETHUSDT"]);
    expect(s.calls[1]?.list.version).toBe(4);
  });

  it("a failed save rolls back to the list as last saved, with the error, and Retry sends the change again", async () => {
    const s = saver();
    const edits = createListEdits(MAJORS, s.port);
    edits.move("XRPUSDT", 0);
    await s.answer({ kind: "failed" });
    expect(edits.getState().symbols).toEqual(MAJORS.symbols);
    expect(edits.getState().error).toEqual({ kind: "failed" });
    edits.retry();
    expect(edits.getState().symbols).toEqual(["XRPUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT"]);
    expect(edits.getState().error).toBeNull();
    expect(s.calls).toHaveLength(2);
  });

  it("a refusal (403) rolls back and offers no Retry", async () => {
    const s = saver();
    const edits = createListEdits(MAJORS, s.port);
    edits.remove("ETHUSDT");
    await s.answer({ kind: "refused" });
    expect(edits.getState()).toMatchObject({ symbols: MAJORS.symbols, error: { kind: "refused" } });
    edits.retry();
    expect(s.calls).toHaveLength(1);
  });

  it("adds at the end, never twice, and never past 200", () => {
    const s = saver();
    const edits = createListEdits(MAJORS, s.port);
    expect(edits.add("DOGEUSDT")).toBe("added");
    expect(edits.add("DOGEUSDT")).toBe("on-list");
    expect(edits.getState().symbols.at(-1)).toBe("DOGEUSDT");
    const full = createListEdits(
      { ...MAJORS, symbols: Array.from({ length: 200 }, (_, i) => `S${i}USDT`) },
      s.port,
    );
    expect(full.add("DOGEUSDT")).toBe("full");
    expect(full.getState().symbols).toHaveLength(200);
  });

  it("columns save with the symbols (a replace without columns would reset them)", () => {
    const s = saver();
    const edits = createListEdits(MAJORS, s.port);
    edits.setColumns(["symbol", "last", "mark_price"]);
    expect(s.calls[0]?.columns).toEqual(["symbol", "last", "mark_price"]);
    expect(s.calls[0]?.symbols).toEqual(MAJORS.symbols);
  });

  it("tells its host each list it saved, once it holds it itself; a failure tells nothing", async () => {
    const s = saver();
    let edits: ListEdits | null = null;
    const heard: { saved: Watchlist; held: Watchlist | undefined }[] = [];
    edits = createListEdits(MAJORS, s.port, (saved) =>
      heard.push({ saved, held: edits?.getState().list }),
    );
    edits.remove("ETHUSDT");
    await s.answer(s.saved(["BTCUSDT", "SOLUSDT", "XRPUSDT"], 4));
    expect(heard.map((h) => h.saved.version)).toEqual([4]);
    expect(heard[0]?.held).toBe(heard[0]?.saved);
    edits.remove("XRPUSDT");
    await s.answer({ kind: "conflict" });
    expect(heard).toHaveLength(1);
  });

  it("adopt takes a list read again (Reload after a conflict): its version and symbols, no error, nothing to retry", async () => {
    const s = saver();
    const edits = createListEdits(MAJORS, s.port);
    edits.remove("ETHUSDT");
    await s.answer({ kind: "conflict" });
    expect(edits.getState().error).toEqual({ kind: "conflict" });
    const fresh: Watchlist = { ...MAJORS, symbols: ["BTCUSDT", "SOLUSDT"], version: 7 };
    edits.adopt(fresh);
    expect(edits.getState()).toMatchObject({
      list: fresh,
      symbols: fresh.symbols,
      columns: fresh.columns,
      removed: [],
      error: null,
    });
    edits.retry();
    expect(s.calls).toHaveLength(1);
    edits.remove("SOLUSDT");
    expect(s.calls.at(-1)?.list.version).toBe(7);
  });
});

describe("SCR-101's edits (#4702 PR (c))", () => {
  it("a rename is one more change: shown at once, sent with the whole list, rolled back on a taken name (409)", async () => {
    const s = saver();
    const edits = createListEdits(MAJORS, s.port);
    edits.rename("Core");
    expect(edits.getState().name).toBe("Core");
    expect(s.calls[0]).toMatchObject({ name: "Core", symbols: MAJORS.symbols });
    await s.answer({ kind: "name_taken" });
    expect(edits.getState()).toMatchObject({ name: "Majors", error: { kind: "name_taken" } });
    edits.rename("Majors");
    expect(s.calls).toHaveLength(1);
  });

  it("C-5335-12: a taken name's error names the name sent, not one typed after it", async () => {
    const s = saver();
    const edits = createListEdits(MAJORS, s.port);
    edits.rename("Core");
    edits.rename("Core 2"); // typed while "Core" is in flight: it goes next
    await s.answer({ kind: "name_taken" });
    expect(edits.getState().error).toEqual({ kind: "name_taken", name: "Core" });
  });

  it("every save carries the name shown, so a symbol change never undoes a rename", async () => {
    const s = saver();
    const edits = createListEdits(MAJORS, s.port);
    edits.rename("Core");
    edits.remove("ETHUSDT");
    await s.answer({ kind: "saved", list: { ...MAJORS, name: "Core", version: 4 } });
    expect(s.calls[1]).toMatchObject({ name: "Core", symbols: ["BTCUSDT", "SOLUSDT", "XRPUSDT"] });
  });

  it("addAll appends the symbols not on the list, as one change, up to the cap", () => {
    const s = saver();
    const edits = createListEdits(MAJORS, s.port);
    expect(edits.addAll(["ETHUSDT", "DOGEUSDT", "DOGEUSDT", "ADAUSDT"])).toEqual([
      "DOGEUSDT",
      "ADAUSDT",
    ]);
    expect(s.calls).toHaveLength(1);
    expect(s.calls[0]?.symbols.slice(-2)).toEqual(["DOGEUSDT", "ADAUSDT"]);
    const near = createListEdits(
      { ...MAJORS, symbols: Array.from({ length: 199 }, (_, i) => `S${i}USDT`) },
      s.port,
    );
    expect(near.addAll(["BTCUSDT", "ETHUSDT"])).toEqual(["BTCUSDT"]);
    expect(near.addAll(["ETHUSDT"])).toEqual([]);
    expect(s.calls).toHaveLength(2);
  });

  it("overwrite, after a conflict: the change undone, saved against the version stored now", async () => {
    const s = saver();
    const edits = createListEdits(MAJORS, s.port);
    edits.move("XRPUSDT", 0);
    await s.answer({ kind: "conflict" });
    const fresh: Watchlist = { ...MAJORS, symbols: ["BTCUSDT", "ETHUSDT"], version: 9 };
    edits.overwrite(fresh);
    expect(edits.getState()).toMatchObject({
      symbols: ["XRPUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT"],
      error: null,
    });
    expect(s.calls.at(-1)).toMatchObject({
      symbols: ["XRPUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT"],
      list: { version: 9 },
    });
  });

  it("overwrite with nothing undone shows the stored list and saves nothing", () => {
    const s = saver();
    const edits = createListEdits(MAJORS, s.port);
    const fresh: Watchlist = { ...MAJORS, symbols: ["BTCUSDT"], version: 9 };
    edits.overwrite(fresh);
    expect(edits.getState().list).toBe(fresh);
    expect(s.calls).toHaveLength(0);
  });
});
