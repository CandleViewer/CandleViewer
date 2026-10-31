/**
 * E08-S08 (#4702): SCR-100's local-first list edits (E08-D07 D15, §6.2, §6.4): each change applies at once, then
 * `PUT /watchlists/{watchlistId}` replaces the list (one save in flight, the latest state next); a failure rolls back
 * with an inline error and Retry; `Del` has Undo, which restores every removal since, in place.
 */
import { describe, expect, it } from "vitest";
import {
  createListEdits,
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
  const calls: { list: Watchlist; symbols: readonly string[]; columns: readonly string[] }[] = [];
  const answers: ((outcome: SaveOutcome) => void)[] = [];
  const port: WatchlistSaver = {
    replace: (list, next) =>
      new Promise<SaveOutcome>((resolve) => {
        calls.push({ list, symbols: next.symbols, columns: next.columns });
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
});
