// E11-S07 in the render runtime (BQ-1 to BQ-6, BQ-10, BQ-20): the pointer becomes the local
// crosshair once per frame, its message and the readout post only on change, the magnet follows
// `setCrosshair`, the lines hide during a gesture and come back after 150 ms of rest, and a
// synced crosshair is drawn only: never announced, never a readout (E11-D01 D3).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createRenderRuntime,
  CROSSHAIR_REST_MS,
  type RenderRuntime,
} from "../../src/worker/runtime.js";
import {
  BACKGROUND_TOKEN,
  INPUT,
  type FromWorker,
  type MagnetMode,
  type ToWorker,
} from "../../src/worker/protocol.js";
import { formatNumber } from "../../src/axes/format.js";
import { columnSource } from "../../src/viewport/index.js";
import { FakeCtx2D } from "../canvas2d/fake-ctx2d.js";
import { FULL } from "../gl/fake-gl.js";
import { MIN_US, source, T0, timeMap } from "../overlays/fixture.js";

const BARS = source(50);
const RED = "rgba(255, 0, 0, 1)";
/** The worker's text for a tick (en-GB grouping, tick size 1). */
const text = (tick: number): string => formatNumber(64_000 + tick, 0);
const THEME = { [BACKGROUND_TOKEN]: "#000000", "color.crosshair": "#ff0000" };

type Of<T extends FromWorker["t"]> = Extract<FromWorker, { t: T }>;
let out: FromWorker[];
let rt: RenderRuntime;
const frame = (n = 1): void => void vi.advanceTimersByTime(16 * n);
const of = <T extends FromWorker["t"]>(t: T, id = 1): Of<T>[] =>
  out.filter((m): m is Of<T> => m.t === t && m.id === id);

function make(id = 1, syncGroup: string | null = null, bench = false): FakeCtx2D {
  const ctx = new FakeCtx2D();
  rt.handle({
    t: "init",
    id,
    canvas: { width: 464, height: 300, getContext: () => ctx },
    dpr: 1,
    theme: THEME,
    config: { bench, syncGroup },
  } satisfies ToWorker);
  // The main series' params (BQ-115): priceOrigin 64 000, tick 1, so the axes and pills format.
  rt.handle({
    t: "data",
    id,
    store: "bars",
    op: "replace",
    layout: { count: 0, columns: [], params: [64_000, 1] },
    buffer: new ArrayBuffer(0),
  });
  // Bars 10 to 29 over the plot: 20 bars, ~20 px each.
  const cmd = { k: "setViewport", timeStart: T0 + 10 * MIN_US, timeEnd: T0 + 30 * MIN_US } as const;
  rt.handle({ t: "command", id, cmd });
  frame(2);
  return ctx;
}

const move = (x: number, y: number, id = 1): void =>
  rt.handle({
    t: "input",
    id,
    kind: "pointer",
    events: new Float32Array([INPUT.move, x, y, 0, 0, 0]),
  });
const magnet = (m: MagnetMode, id = 1): void =>
  rt.handle({ t: "command", id, cmd: { k: "setCrosshair", magnetMode: m } });
/** Strokes painted since `from` in `style`, and their segments. */
const strokes = (ctx: FakeCtx2D, from: number, style: string): number =>
  ctx.paths
    .slice(from)
    .filter((p) => p.op === "stroke" && p.style === style)
    .reduce((n, p) => n + p.parts.filter((s) => s.startsWith("moveTo")).length, 0);

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  out = [];
  rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => void setTimeout(cb, 16),
    now: () => Number(vi.getMockedSystemTime()),
    setTimer: (cb, ms) => void setTimeout(cb, ms),
    probe: () => FULL,
    timeMap: timeMap(50),
    priceSources: [columnSource(() => BARS)],
    readoutSources: [BARS],
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("BQ-1: the crosshair message", () => {
  it("test_hover_manyMovesInOneFrame_postsOneCrosshairAndNoA11y", () => {
    make();
    move(100, 80);
    move(110, 90);
    move(120, 100);
    frame();
    const [c, ...rest] = of("crosshair");
    expect(rest).toEqual([]);
    expect(c).toMatchObject({ visible: true, driver: "pointer", snap: null, y: 100 });
    expect(c?.bar).toBeGreaterThanOrEqual(10);
    expect(c?.time).toBe(T0 + (c?.bar ?? 0) * MIN_US);
    expect(c?.timeText).toMatch(/^14 Oct 14:\d\d$/);
    expect(c?.priceText).toBe(text(c?.price ?? 0));
    expect(of("a11y")).toEqual([]); // BQ-3: only key moves are announced
    frame(4);
    move(120, 100); // the same point: nothing changed
    frame();
    expect(of("crosshair")).toHaveLength(1);
  });

  it("test_hover_leaveRow_postsOneHiddenMessage_thenStaysQuiet", () => {
    make();
    move(120, 100);
    frame();
    const leave = new Float32Array([INPUT.leave, 0, 0, 0, 0, 0]);
    rt.handle({ t: "input", id: 1, kind: "pointer", events: leave });
    frame();
    expect(of("crosshair").map((m) => m.visible)).toEqual([true, false]);
    move(420, 100); // the price gutter: no crosshair, no message
    frame(3);
    expect(of("crosshair")).toHaveLength(2);
  });

  it("test_counters_eventsEmitted_countsBarEdgesOnly", () => {
    make();
    const first = (): number => of("crosshair")[0]?.x ?? 0;
    move(100, 50);
    frame();
    const x = first();
    for (let dy = 1; dy <= 5; dy += 1) {
      move(x, 50 + dy); // the same bar, a new price
      frame();
    }
    expect(rt.crosshairCounters(1)).toEqual({ eventsEmitted: 1 });
    move(x + 40, 50); // two bars right
    frame();
    expect(rt.crosshairCounters(1)).toEqual({ eventsEmitted: 2 });
    expect(rt.crosshairCounters(9)).toBeUndefined();
  });
});

describe("AC5: crosshair events are edge-triggered", () => {
  it("test_sweep_200pxInsideOneMaxWidthBar_oneEdgeAndOneReadout_manyMessages", () => {
    make();
    // One bar over the plot: spacing clamps to BAR_SPACING_MAX (200 px; the pure model's 240 px
    // case is test/overlays/crosshair.test.ts). Bar 11 spans x in [100, 300).
    const cmd = {
      k: "setViewport",
      timeStart: T0 + 10 * MIN_US,
      timeEnd: T0 + 11 * MIN_US,
    } as const;
    rt.handle({ t: "command", id: 1, cmd });
    frame();
    for (let x = 100; x < 300; x += 1) {
      move(x, 40 + (x - 100) / 2);
      frame();
    }
    const cross = of("crosshair");
    expect(new Set(cross.map((m) => m.bar))).toEqual(new Set([11]));
    expect(cross.length).toBeGreaterThan(90); // each new price posts, once a frame
    expect(new Set(cross.map((m) => m.priceText)).size).toBeGreaterThan(10);
    expect(rt.crosshairCounters(1)?.eventsEmitted).toBe(1);
    expect(of("readout")).toHaveLength(1); // the data at bar 11 never changed
  });
});

describe("BQ-2: the readout message", () => {
  it("test_readout_barChange_postsFieldsAtThatBar", () => {
    make();
    move(100, 80);
    frame();
    const bar = of("crosshair")[0]?.bar ?? -1;
    const [r] = of("readout");
    expect(r?.bar).toBe(bar);
    expect(r?.fields.map((f) => [f.key, f.label])).toEqual([
      ["open", "O"],
      ["high", "H"],
      ["low", "L"],
      ["close", "C"],
      ["volume", "Vol"],
      ["delta", "Δ"],
    ]);
    expect(r?.fields[1]?.value).toBe(text(300 + bar)); // exact, never interpolated
  });

  it("test_readout_dataChangeAtTheBar_postsAgain_otherBarsDoNot", () => {
    make();
    move(100, 80);
    frame();
    const bar = of("crosshair")[0]?.bar ?? 0;
    const close = BARS.close[bar] ?? 0;
    BARS.close[bar + 5] = close + 99; // another bar: nothing at the cursor moved
    rt.handle({ t: "command", id: 1, cmd: { k: "setSeriesOptions", series: 0, options: {} } });
    frame();
    expect(of("readout")).toHaveLength(1);
    BARS.close[bar] = close + 7; // a forming-bar patch at the cursor
    rt.handle({ t: "command", id: 1, cmd: { k: "setSeriesOptions", series: 0, options: {} } });
    frame();
    BARS.close[bar] = close;
    BARS.close[bar + 5] = (BARS.close[bar + 5] ?? 0) - 99;
    expect(of("readout")).toHaveLength(2);
    expect(of("readout")[1]?.fields[3]?.value).toContain(text(close + 7));
  });

  it("test_registerReadoutProvider_joinsAfterDelta_andUnregisters", () => {
    make();
    const off = rt.registerReadoutProvider(1, {
      key: "ema",
      label: "EMA 20",
      value: (b) => `v${b}`,
    });
    move(100, 80);
    frame();
    const bar = of("crosshair")[0]?.bar ?? -1;
    expect(of("readout")[0]?.fields.at(-1)).toMatchObject({ key: "ind:ema", value: `v${bar}` });
    off?.();
    frame();
    expect(of("readout").at(-1)?.fields).toHaveLength(6);
    expect(
      rt.registerReadoutProvider(9, { key: "x", label: "x", value: () => null }),
    ).toBeUndefined();
  });
});

describe("AC6 and BQ-4: the magnet follows setCrosshair", () => {
  it("test_setCrosshair_strongThenWeakThenOff_snapsPredictably", () => {
    make();
    magnet("strong");
    move(100, 5); // far above every field: strong still snaps, to the nearest (the high)
    frame();
    const s = of("crosshair").at(-1);
    const bar = s?.bar ?? 0;
    expect(s).toMatchObject({ snap: "high", price: BARS.high[bar] });
    expect(of("readout").at(-1)?.fields[1]?.label).toBe("High"); // AC6's label
    const highY = s?.y ?? 0;
    magnet("weak");
    move(100, highY + 12); // inside the 12 px radius (BQ-8)
    frame();
    expect(of("crosshair").at(-1)).toMatchObject({ snap: "high", y: highY });
    move(100, highY + 30); // released
    frame();
    expect(of("crosshair").at(-1)).toMatchObject({ snap: null, y: Math.fround(highY + 30) });
    magnet("off");
    move(100, highY + 1);
    frame();
    expect(of("crosshair").at(-1)).toMatchObject({ snap: null, y: Math.fround(highY + 1) });
    expect(of("a11y")).toEqual([]); // a magnet change is the host's announcement, never a11y
  });
});

describe("G-28: the degraded-2d re-init keeps the crosshair's settings", () => {
  it("test_reinit_keepsMagnetProvidersAndCounters", () => {
    make();
    magnet("strong");
    rt.registerReadoutProvider(1, { key: "ema", label: "EMA", value: () => "1" });
    move(100, 5);
    frame();
    const before = rt.crosshairCounters(1);
    make(); // the handoff's second init: a fresh canvas and scene
    move(100, 5);
    frame();
    expect(of("crosshair").at(-1)?.snap).toBe("high");
    expect(of("readout").at(-1)?.fields.at(-1)?.key).toBe("ind:ema");
    expect(rt.crosshairCounters(1)).toBe(before);
  });
});

describe("D06 §5.2: the lines hide during a gesture and return after 150 ms of rest", () => {
  it("test_wheel_hidesInstantly_showsAfterRest", () => {
    const ctx = make();
    move(100, 80);
    frame();
    const shown = ctx.paths.length;
    expect(strokes(ctx, 0, RED)).toBeGreaterThan(10); // dashed: many segments
    rt.handle({
      t: "input",
      id: 1,
      kind: "wheel",
      events: new Float32Array([INPUT.wheel, 100, 80, 40, 0, 0]),
    });
    frame();
    expect(of("crosshair").at(-1)?.visible).toBe(false);
    const hidden = ctx.paths.length;
    expect(strokes(ctx, shown, RED)).toBe(0); // an instant hide (BQ-16)
    vi.advanceTimersByTime(CROSSHAIR_REST_MS - 40);
    expect(of("crosshair").at(-1)?.visible).toBe(false);
    vi.advanceTimersByTime(80);
    expect(of("crosshair").at(-1)?.visible).toBe(true);
    expect(strokes(ctx, hidden, RED)).toBeGreaterThan(10);
  });

  it("test_drag_hidesWhileActive_andAGlideKeepsItHidden", () => {
    make();
    move(100, 80);
    frame();
    const drag = (type: number, x: number, b: number): void =>
      rt.handle({
        t: "input",
        id: 1,
        kind: "pointer",
        events: new Float32Array([type, x, 80, b, 0, 16]),
      });
    drag(INPUT.down, 100, 1);
    drag(INPUT.move, 140, 1);
    frame();
    expect(of("crosshair").at(-1)?.visible).toBe(false);
    drag(INPUT.up, 140, 0);
    frame();
    expect(of("crosshair").at(-1)?.visible).toBe(false); // gliding
    vi.advanceTimersByTime(4000); // the glide runs out, then 150 ms of rest
    expect(of("crosshair").at(-1)?.visible).toBe(true);
  });

  it("test_up_noGlide_showsOnTheNextFrame", () => {
    make();
    rt.handle({ t: "command", id: 1, cmd: { k: "setMotion", reduce: true } }); // never coasts
    move(100, 80);
    frame();
    const drag = (type: number, x: number, b: number): void =>
      rt.handle({
        t: "input",
        id: 1,
        kind: "pointer",
        events: new Float32Array([type, x, 80, b, 0, 16]),
      });
    drag(INPUT.down, 100, 1);
    drag(INPUT.move, 140, 1);
    frame();
    expect(of("crosshair").at(-1)?.visible).toBe(false);
    drag(INPUT.up, 140, 0);
    frame(); // one frame, not 150 ms
    expect(of("crosshair").at(-1)?.visible).toBe(true);
  });

  it("test_wheelHold_nextPointerMove_showsBeforeTheRest", () => {
    make();
    move(100, 80);
    frame();
    const wheel = new Float32Array([INPUT.wheel, 100, 80, 40, 0, 0]);
    rt.handle({ t: "input", id: 1, kind: "wheel", events: wheel });
    frame();
    expect(of("crosshair").at(-1)?.visible).toBe(false);
    vi.advanceTimersByTime(30); // well inside the 150 ms hold
    move(120, 90);
    frame();
    expect(of("crosshair").at(-1)).toMatchObject({ visible: true, y: 90 });
  });
});

describe("BQ-6: no echo in the sync group", () => {
  it("test_publish_peerNeverRepublishesARemoteCrosshair_noExtraFrame", () => {
    make(1, "g", true); // bench: every frame posts `frame`, so an echo's extra frame shows
    make(2, "g", true);
    frame(4);
    out.length = 0;
    move(100, 80, 1);
    frame(6);
    // Chart 1 ran one frame for its own move. A peer re-publishing the remote crosshair would
    // hand it back as chart 1's remote line, a change, and so a second frame.
    expect(of("frame", 1)).toHaveLength(1);
    expect(of("frame", 2)).toHaveLength(1); // the remote line drawn once
    expect(of("crosshair", 2)).toEqual([]);
  });
});

describe("BQ-5: a remote crosshair is drawn, never announced (E11-D01 D3)", () => {
  // `opacity.muted` absent from the theme: 0.7 (in float32, as the ring holds it).
  const MUTED = `rgba(255, 0, 0, ${Math.round(Math.fround(0.7) * 255) / 255})`;

  it("test_sync_remoteCrosshair_postsNoA11yCrosshairOrReadout_drawsMutedVertical", () => {
    const ctx = make(1, "g");
    out.length = 0;
    rt.handle({
      t: "sync",
      groupId: "g",
      timeRange: [T0 + 10 * MIN_US, T0 + 30 * MIN_US],
      crosshair: T0 + 15 * MIN_US,
    });
    frame();
    // The regression (it failed before E11-S07): a sync posted `a11y` with the remote's summary.
    expect(of("a11y")).toEqual([]);
    expect(of("crosshair")).toEqual([]);
    expect(of("readout")).toEqual([]);
    expect(strokes(ctx, 0, MUTED)).toBeGreaterThan(5);
    rt.handle({
      t: "sync",
      groupId: "g",
      timeRange: [T0 + 10 * MIN_US, T0 + 30 * MIN_US],
      crosshair: null,
    });
    const mark = ctx.paths.length;
    frame();
    expect(strokes(ctx, mark, MUTED)).toBe(0);
    expect(of("a11y")).toEqual([]);
  });

  it("test_publish_localCursor_reachesPeersAsRemoteOnly_andHidesUnderAPeerCursor", () => {
    make(1, "g");
    const peer = make(2, "g");
    make(3, "other");
    out.length = 0;
    const mark = peer.paths.length;
    move(100, 80, 1);
    frame(2);
    expect(of("crosshair", 1)).toHaveLength(1);
    for (const id of [2, 3]) {
      expect([...of("crosshair", id), ...of("readout", id), ...of("a11y", id)]).toEqual([]);
    }
    expect(strokes(peer, mark, MUTED)).toBeGreaterThan(5); // drawn in the peer only
    move(200, 80, 2); // the peer's own cursor replaces the remote line
    frame(2);
    const later = peer.paths.length;
    frame();
    move(201, 81, 2);
    frame();
    expect(strokes(peer, later, MUTED)).toBe(0);
    expect(strokes(peer, later, RED)).toBeGreaterThan(5);
    // Chart 1 sees chart 2's cursor as remote; nothing it posts changes for it.
    expect(of("crosshair", 1)).toHaveLength(1);
  });
});
