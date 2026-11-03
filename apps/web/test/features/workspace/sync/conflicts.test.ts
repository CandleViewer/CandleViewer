import { describe, expect, it } from "vitest";
import { conflictsOf } from "../../../../src/features/workspace/sync/conflicts";
import type { GroupSnapshot } from "../../../../src/features/workspace/sync/syncBus";
import { ALL_ON } from "./fakes";

const chart = (paneId: string, symbol: string | null, interval: string | null) => ({
  paneId,
  kind: "chart",
  symbol,
  interval,
});
const group = (members: GroupSnapshot["members"], axes = ALL_ON): GroupSnapshot => ({
  group: "A",
  axes,
  members,
});

describe("sync conflict states", () => {
  it("reports an interval mismatch (D-7) against the interval most members share", () => {
    const snap = group([
      chart("p1", "BTCUSDT", "time:1"),
      chart("p2", "BTCUSDT", "time:15"),
      chart("p3", "BTCUSDT", "time:1"),
    ]);
    expect(conflictsOf(snap)).toEqual([
      { kind: "interval_mismatch", group: "A", reference: "time:1", paneIds: ["p2"] },
    ]);
  });

  it("takes the given pane as the reference, and the earliest member on a tie", () => {
    const snap = group([chart("p1", "BTCUSDT", "time:1"), chart("p2", "BTCUSDT", "time:60")]);
    expect(conflictsOf(snap, "p2")[0]?.paneIds).toEqual(["p1"]);
    expect(conflictsOf(snap)[0]?.paneIds).toEqual(["p2"]);
  });

  it("reports drawings across symbols (D-8) for the panel on the other symbol", () => {
    const snap = group(
      [
        chart("p1", "BTCUSDT", "time:1"),
        chart("p2", "BTCUSDT", "time:1"),
        chart("p3", "ETHUSDT", "time:1"),
      ],
      { ...ALL_ON, crosshair: false },
    );
    expect(conflictsOf(snap)).toEqual([
      { kind: "drawings_symbol_mismatch", group: "A", reference: "BTCUSDT", paneIds: ["p3"] },
    ]);
  });

  it("is empty when the axis is off, the values agree, or only non-charts differ", () => {
    const off = { ...ALL_ON, crosshair: false, drawings: false };
    expect(
      conflictsOf(group([chart("p1", "A", "time:1"), chart("p2", "B", "time:5")], off)),
    ).toEqual([]);
    expect(conflictsOf(group([chart("p1", "A", "time:1"), chart("p2", "A", "time:1")]))).toEqual(
      [],
    );
    const dom = { paneId: "d", kind: "dom", symbol: "ETHUSDT", interval: null };
    expect(conflictsOf(group([chart("p1", "A", "time:1"), dom, chart("p2", "A", null)]))).toEqual(
      [],
    );
  });
});
