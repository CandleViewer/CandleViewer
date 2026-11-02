// E12-S06 SeriesHost: the scene node that runs a series plugin and is its RenderContext. Only its
// own part becomes a batch entry; projection is the transform's own functions (G-2); store
// mutations reach `onMutation`; §8's immediate-mode calls fail loudly until their layers land.
import { describe, expect, it } from "vitest";
import {
  CandleRing,
  SeriesHost,
  type HostContext,
  type HostTheme,
  type HostedPlugin,
} from "../../src/layers/index.js";
import { BarStore, type MutationRange } from "../../src/model/index.js";
import { PooledBatchSink } from "../../src/scene/pool.js";
import {
  ChartViewport,
  indexToScreen,
  priceToScreen,
  screenToTime,
} from "../../src/viewport/index.js";
import { bars } from "../model/fixtures.js";

const THEME: HostTheme = { palette: "default", convention: "standard", colors: {} };

function setup(part: number) {
  const store = new BarStore();
  const ring = new CandleRing();
  ring.sync(store, store.append(bars(0, 50)));
  const viewport = new ChartViewport(store);
  viewport.setSize(800, 400, 2);
  viewport.setPanePlot(0, 0, 400);
  viewport.setPriceInfo(0, 50_000, 0.1);
  const seen: { ctx: HostContext | null; mutations: string[] } = { ctx: null, mutations: [] };
  const plugin: HostedPlugin = {
    collect(ctx) {
      seen.ctx = ctx;
      ctx.instances(ring, "candle", 0);
      ctx.instances(ring, "candle", 1);
    },
    onMutation(view, r) {
      seen.mutations.push(`${r.op} ${r.from} ${r.to} ${view.length}`);
    },
  };
  const host = new SeriesHost(
    `series.candle.${part}`,
    plugin,
    {
      viewport,
      pane: 0,
      theme: () => THEME,
    },
    { part, program: 4 },
  );
  return { store, ring, viewport, host, seen };
}

describe("SeriesHost", () => {
  it("turns only its own part into one batch entry over the ring's bars", () => {
    const { host } = setup(1);
    const sink = new PooledBatchSink(2);
    expect(host.collect(sink)).toBe(true);
    expect(sink.length).toBe(1);
    expect({ ...sink.at(0) }).toEqual({
      nodeId: "series.candle.1",
      program: 4,
      texture: 0,
      first: 0,
      count: 1024, // the ring's capacity: the shader collapses slots past its 50 bars (BQ-14)
    });
  });

  it("is the plugin's context: theme, a refreshed viewport, the transform's projection", () => {
    const { host, viewport, seen } = setup(0);
    host.collect(new PooledBatchSink(2));
    const ctx = seen.ctx as HostContext;
    expect(ctx).toBe(host);
    expect(ctx.theme).toBe(THEME);
    expect({ ...ctx.viewport }).toEqual({
      widthPx: 800,
      heightPx: 400,
      pixelRatio: 2,
      timeStart: screenToTime(viewport, 0),
      timeEnd: screenToTime(viewport, 800),
    });
    for (const i of [0, 7.5, 49])
      expect(ctx.projection.indexToX(i)).toBe(indexToScreen(viewport, i));
    for (const t of [-3, 0, 12])
      expect(ctx.projection.tickToY(t)).toBe(priceToScreen(viewport, 0, t));
    viewport.setSize(600, 300, 1);
    host.collect(new PooledBatchSink(2));
    expect([ctx.viewport.widthPx, ctx.viewport.pixelRatio]).toEqual([600, 1]);
  });

  it("forwards store mutations to the plugin's retained path, and tolerates none", () => {
    const { host, store, seen } = setup(0);
    const r: MutationRange = store.append(bars(50, 2));
    host.onMutation(store.view(), r);
    expect(seen.mutations).toEqual(["append 50 52 52"]);
    const bare = new SeriesHost(
      "bare",
      { collect: () => undefined },
      {
        viewport: new ChartViewport(),
        pane: 0,
        theme: () => THEME,
      },
      { part: 0, program: 0 },
    );
    expect(() => bare.onMutation(store.view(), r)).not.toThrow();
  });

  it("refuses instances outside collect, and every immediate-mode call, loudly", () => {
    const { host, ring } = setup(0);
    expect(() => host.instances(ring, "candle", 0)).toThrow(/outside collect/);
    for (const call of [
      () => host.rect(),
      () => host.line(),
      () => host.glyphRun(),
      () => host.quadBatch(),
      () => host.texture(),
    ]) {
      expect(call).toThrow(/not available to series plugins/);
    }
  });

  it("clears its sink even when the plugin's collect throws", () => {
    const { ring } = setup(0);
    const host = new SeriesHost(
      "boom",
      {
        collect: () => {
          throw new Error("boom");
        },
      },
      {
        viewport: new ChartViewport(),
        pane: 0,
        theme: () => THEME,
      },
      { part: 0, program: 0 },
    );
    expect(() => host.collect(new PooledBatchSink(1))).toThrow("boom");
    expect(() => host.instances(ring, "candle", 0)).toThrow(/outside collect/);
  });
});
