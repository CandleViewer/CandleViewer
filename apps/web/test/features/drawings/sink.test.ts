import { describe, expect, it } from "vitest";
import { createDrawingStore } from "../../../src/features/drawings/store/drawingStore.js";
import { connectSink, createFakeSink } from "../../../src/features/drawings/store/sink.js";
import { counter, input } from "./fixtures.js";

describe("drawing sink port", () => {
  it("publishes the pane snapshot now and on each reference change, then tears down", () => {
    const store = createDrawingStore({ mintId: counter() });
    const sink = createFakeSink();
    const off = connectSink(store, "BTCUSDT", null, sink);
    expect(sink.published).toEqual([{ symbol: "BTCUSDT", snapshot: [] }]);
    const a = store.create(input());
    store.create(input("ETHUSDT"));
    store.setStatus("BTCUSDT", { kind: "pending" });
    expect(sink.published).toHaveLength(2);
    expect(sink.published[1]?.snapshot.map((d) => d.handle)).toEqual([a]);
    off();
    store.create(input());
    expect(sink.published).toHaveLength(2);
  });
});
