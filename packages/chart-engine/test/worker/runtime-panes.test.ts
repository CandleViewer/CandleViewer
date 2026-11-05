// E11-S09 PR 1a through the runtime: the pane stack (BQ-1 to BQ-5, BQ-10, BQ-11, BQ-14). Panes
// share time by construction, so a seeded pan / zoom / glide session on a TestClock can never
// drift them apart; the `layout` message tiles the plot; collapse hides a pane's nodes.
import { beforeEach, describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { MOD } from "../../src/interaction/wheel.js";
import { INPUT, KEY, MAX_PANES, type FromWorker } from "../../src/worker/protocol.js";
import { FakeCtx2D } from "../canvas2d/fake-ctx2d.js";
import { FakeGl, FULL, ROOMY } from "../gl/fake-gl.js";
import { minuteMap, rows } from "../interaction/fixtures.js";
import { TestClock } from "../scene/test-clock.js";

type Layout = Extract<FromWorker, { t: "layout" }>;
type Viewport = Extract<FromWorker, { t: "viewport" }>;

let out: FromWorker[];
let rt: RenderRuntime;
let gl: FakeGl;
let clock: TestClock;
const cmd = (c: object): void => rt.handle({ t: "command", id: 1, cmd: c });
const input = (kind: string, ...r: number[][]): void =>
  rt.handle({ t: "input", id: 1, kind, events: rows(...r) });
const layouts = (): Layout[] => out.filter((m): m is Layout => m.t === "layout");
const frame = (ms = 16): void => void clock.tick(ms);
const viewports = (): Viewport[] => out.filter((m): m is Viewport => m.t === "viewport");
/** Each key's last `viewport` row: its scale state. */
const scales = (): Record<number, unknown> =>
  Object.fromEntries(
    viewports().map((m) => [
      m.pane,
      { mode: m.mode, requested: m.requestedMode, inverted: m.inverted, auto: m.autoScale },
    ]),
  );
const rowsOf = (l: Layout | undefined): unknown[] =>
  (l?.panes ?? []).map((p) => [p.pane, p.top, p.height, p.share, p.collapsed]);

beforeEach(() => {
  out = [];
  clock = new TestClock();
  gl = new FakeGl({ params: ROOMY });
  rt = createRenderRuntime({
    runMode: "inline",
    post: (m) => out.push(m),
    requestFrame: (cb) => void clock.requestFrame(() => cb()),
    now: () => clock.now(),
    setTimer: () => undefined,
    probe: () => FULL,
    timeMap: minuteMap(),
  });
  const canvas = { width: 1064, height: 624, getContext: () => gl };
  rt.handle({ t: "init", id: 1, canvas, dpr: 1, theme: {}, config: { syncGroup: null } });
  cmd({ k: "addPane", pane: 0 }); // the facade's first key adopts slot 0
  cmd({ k: "addPane", pane: 1 });
  cmd({ k: "addPane", pane: 2 });
  frame();
});

describe("Scenario: Panes cannot drift", () => {
  it("a seeded 10 s pan, zoom and glide keeps every pane's x words identical, every frame", () => {
    const rng = mulberry32(20261104);
    const int = (n: number): number => Math.floor(rng() * n);
    let checked = 0;
    const from = rt.paneStats(1)?.[0]?.timeStart;
    for (let f = 0; f < 600; f += 1) {
      const x = 20 + int(900);
      const y = int(600);
      const op = int(6);
      if (op === 0) input("wheel", [INPUT.wheel, x, y, (rng() - 0.5) * 400, 0, 16]);
      if (op === 1) input("wheel", [INPUT.wheel, x, y, (rng() - 0.5) * 400, MOD.pan, 16]);
      if (op === 2) input("pointer", [INPUT.down, x, y, 1, 0, 0], [INPUT.move, x + 40, y, 1, 0, 8]);
      if (op === 3)
        input("pointer", [INPUT.move, x + 90, y, 1, 0, 8], [INPUT.up, x + 90, y, 0, 0, 8]);
      if (op === 4) input("key", [INPUT.key, int(2) === 0 ? KEY.zoomIn : KEY.left, 0, 0, 0, 0]);
      frame(); // op 5: a glide frame, or a still one
      const stats = rt.paneStats(1) ?? [];
      expect(stats.map((s) => s.key)).toEqual([0, 1, 2]);
      for (const s of stats)
        expect(s, `frame ${f}`).toEqual(stats[0] && { ...stats[0], key: s.key });
      checked += 1;
    }
    expect(checked).toBe(600);
    expect(rt.paneStats(1)?.[0]?.timeStart).not.toBe(from); // the session did move the view
    const v = out.filter((m): m is Viewport => m.t === "viewport");
    expect(new Set(v.slice(-3).map((m) => `${m.timeStart} ${m.timeEnd}`)).size).toBe(1);
    const graph = rt.graph(1);
    expect(graph?.walk().filter((n) => n.kind === "time-axis")).toHaveLength(1);
  });

  it("lays the panes out in equal shares that tile the plot, the time strip under the last", () => {
    const l = layouts().at(-1) as Layout;
    expect(l.panes.map((p) => [p.pane, p.top, p.height, p.collapsed])).toEqual([
      [0, 0, 200, false],
      [1, 200, 200, false],
      [2, 400, 200, false],
    ]);
    expect(l.panes.reduce((a, p) => a + p.share, 0)).toBe(1);
    expect(l.timeAxis).toEqual([600, 24]);
    const posted = layouts().length;
    frame();
    expect(layouts()).toHaveLength(posted); // a still frame posts no layout
  });
});

describe("shares, collapse and removal through the commands", () => {
  it("setPaneShares rescales the others; a share under the minimum collapses to the stub", () => {
    cmd({ k: "setPaneShares", shares: [[0, 0.6]] });
    frame();
    expect(
      layouts()
        .at(-1)
        ?.panes.map((p) => p.height),
    ).toEqual([360, 120, 120]);
    cmd({ k: "setPaneShares", shares: [[2, 0.05]] }); // 30 px < 48
    frame();
    const l = layouts().at(-1) as Layout;
    expect(l.panes.map((p) => [p.height, p.collapsed])).toEqual([
      [426, false],
      [142, false],
      [32, true],
    ]);
    expect(rt.graph(1)?.get("pane.2")?.visible).toBe(false); // nothing on it draws
    cmd({ k: "setPaneCollapsed", pane: 2, collapsed: false });
    frame();
    expect(
      layouts()
        .at(-1)
        ?.panes.map((p) => p.height),
    ).toEqual([414, 138, 48]); // the minimum
  });

  it("a price wheel acts on the pane under the pointer only", () => {
    const vp = (): Viewport[] => out.filter((m): m is Viewport => m.t === "viewport");
    input("wheel", [INPUT.wheel, 1040, 500, 120, 0, 16]); // pane 2's price gutter
    frame();
    const last = vp().slice(-3);
    expect(last.map((m) => [m.pane, m.autoScale])).toEqual([
      [0, true],
      [1, true],
      [2, false],
    ]);
  });

  it("adding a pane re-uploads no ring; removal keeps the keys; the last pane stays keyless", () => {
    const writes = gl.writes.length;
    cmd({ k: "addPane", pane: 3, share: 0.25 });
    frame();
    expect(gl.writes.length).toBe(writes);
    expect(
      layouts()
        .at(-1)
        ?.panes.map((p) => p.pane),
    ).toEqual([0, 1, 2, 3]);
    cmd({ k: "removePane", pane: 1 });
    cmd({ k: "removePane", pane: 2 });
    cmd({ k: "removePane", pane: 3 });
    cmd({ k: "removePane", pane: 0 });
    frame();
    expect(
      layouts()
        .at(-1)
        ?.panes.map((p) => [p.pane, p.share]),
    ).toEqual([[-1, 1]]);
    cmd({ k: "addPane", pane: 4 }); // a StrictMode re-mount: the keyless slot is adopted
    cmd({ k: "setPaneShares", shares: [[9, 0.5]] }); // unknown key: refused, recoverably
    frame();
    expect(
      layouts()
        .at(-1)
        ?.panes.map((p) => p.pane),
    ).toEqual([4]);
    expect(out.filter((m) => m.t === "error").at(-1)).toMatchObject({ recoverable: true });
  });
});

describe("review: removing the first key, the stub, the key target and the bounds", () => {
  it("removing key 0 while panes remain keeps them tiling the plot, keyed, and appends after", () => {
    cmd({ k: "removePane", pane: 0 });
    frame();
    const near = expect.closeTo(0.5, 12);
    expect(rowsOf(layouts().at(-1))).toEqual([
      [1, 0, 300, near, false],
      [2, 300, 300, near, false],
    ]);
    out.length = 0;
    input("wheel", [INPUT.wheel, 400, 100, 120, 0, 16]); // a time zoom: every pane re-posts
    frame();
    expect(viewports().map((m) => m.pane)).toEqual([1, 2]); // no keyless row
    cmd({ k: "addPane", pane: 3 });
    frame();
    expect(
      layouts()
        .at(-1)
        ?.panes.map((p) => p.pane),
    ).toEqual([1, 2, 3]); // at the bottom
  });

  it("a price wheel over a collapsed stub's gutter changes no pane's scale", () => {
    cmd({ k: "setPaneShares", shares: [[2, 0.05]] }); // pane 2 folds to the 32 px stub at 568
    frame();
    expect(layouts().at(-1)?.panes.at(-1)).toMatchObject({ pane: 2, collapsed: true });
    input("wheel", [INPUT.wheel, 1040, 580, 120, 0, 16]);
    input("wheel", [INPUT.wheel, 400, 100, 120, 0, 16]); // a time zoom: every pane re-posts
    frame();
    expect(Object.values(scales()).map((s) => (s as { auto: boolean }).auto)).toEqual([
      true,
      true,
      true,
    ]);
  });

  it("a price-axis key acts on the stop's pane (slot 0), not the last pane wheeled", () => {
    input("wheel", [INPUT.wheel, 1040, 300, 120, 0, 16]); // pane 1's gutter: pane 1 locks
    frame();
    const before = viewports()
      .filter((m) => m.pane === 1)
      .at(-1);
    input("key", [INPUT.key, KEY.up, 2, 0, 0, 0]); // the price-axis stop
    frame();
    const last = (k: number): Viewport | undefined =>
      viewports()
        .filter((m) => m.pane === k)
        .at(-1);
    expect(last(0)?.autoScale).toBe(false);
    expect(last(1)).toEqual(before);
  });

  it("refuses a pane beyond MAX_PANES and keeps the graph flat under add/remove churn", () => {
    for (let k = 3; k < MAX_PANES; k += 1) cmd({ k: "addPane", pane: k });
    cmd({ k: "addPane", pane: MAX_PANES });
    frame();
    expect(layouts().at(-1)?.panes).toHaveLength(MAX_PANES);
    expect(out.filter((m) => m.t === "error").at(-1)).toMatchObject({ recoverable: true });
    for (let k = 3; k < MAX_PANES; k += 1) cmd({ k: "removePane", pane: k });
    frame();
    const nodes = rt.graph(1)?.walk().length;
    for (let c = 0; c < 1000; c += 1) {
      cmd({ k: "addPane", pane: 1000 + c });
      cmd({ k: "removePane", pane: 1000 + c });
    }
    frame();
    expect(rt.graph(1)?.walk().length).toBe(nodes);
    expect(
      layouts()
        .at(-1)
        ?.panes.map((p) => p.pane),
    ).toEqual([0, 1, 2]);
  });
});

describe("BQ-10: the degraded-2d handoff keeps the pane stack", () => {
  const degrade = (): void => {
    const ctx = new FakeCtx2D();
    const canvas = {
      width: 1064,
      height: 624,
      getContext: (id: string) => (id === "2d" ? ctx : null),
    };
    rt.handle({
      t: "init",
      id: 1,
      canvas,
      dpr: 1,
      theme: {},
      config: { syncGroup: null },
      profile: "degraded-2d",
    });
    frame();
  };

  it("keeps every pane's key, share, collapse and price-scale state", () => {
    cmd({
      k: "setPaneShares",
      shares: [
        [0, 0.5],
        [1, 0.3],
      ],
    });
    cmd({ k: "setPaneCollapsed", pane: 1, collapsed: true });
    cmd({ k: "setPriceScale", pane: 2, mode: "percent" });
    cmd({ k: "setPriceScale", pane: 0, inverted: true });
    frame();
    const [rows, state] = [rowsOf(layouts().at(-1)), scales()];
    expect(rows.map((r) => (r as unknown[])[4])).toEqual([false, true, false]);
    degrade();
    expect(rowsOf(layouts().at(-1))).toEqual(rows);
    expect(scales()).toEqual(state);
  });

  it("after key 0 was removed, the handoff keeps the remaining keys in order", () => {
    cmd({ k: "removePane", pane: 0 });
    frame();
    const rows = rowsOf(layouts().at(-1));
    expect(rows.map((r) => (r as unknown[])[0])).toEqual([1, 2]);
    degrade();
    expect(rowsOf(layouts().at(-1))).toEqual(rows);
  });
});

describe("E11-S09 PR 1b: the splitters through the runtime (D02 §8)", () => {
  const heights = (): unknown[] =>
    (layouts().at(-1)?.panes ?? []).map((p) => (p.collapsed ? "stub" : p.height));
  const { down, move, up } = INPUT;

  it("a pointer-down in the 24 px band drags the boundary; only its two panes change", () => {
    input("pointer", [down, 500, 210, 1, 0, 0], [move, 500, 260, 1, 0, 8]); // 10 px under it
    frame();
    expect(heights()).toEqual([250, 150, 200]);
    input("pointer", [move, 500, 380, 1, 0, 8], [up, 500, 380, 0, 0, 8]); // pane 1 under 48 px
    frame();
    expect(heights()).toEqual([379, "stub", 189]); // folded into pane 0; pane 2's share kept
    expect(layouts().at(-1)?.panes[2]?.share).toBeCloseTo(1 / 3, 12);
  });

  it("hover, and a drag that starts outside the band, never move a splitter", () => {
    const posted = layouts().length;
    input("pointer", [move, 500, 200, 0, 0, 8], [move, 500, 405, 0, 0, 8]); // hover passes
    input("pointer", [down, 500, 150, 1, 0, 0], [move, 500, 190, 1, 0, 8], [up, 500, 190, 0, 0, 8]);
    frame();
    expect([layouts().length, heights()]).toEqual([posted, [200, 200, 200]]);
  });

  it("moveSplitter: 2 % steps, clamped at the minimum, and a layout after every key", () => {
    cmd({ k: "moveSplitter", pane: 0, by: -0.02 });
    frame();
    expect(
      layouts()
        .at(-1)
        ?.panes.map((p) => p.share),
    ).toEqual([1 / 3 - 0.02, 1 / 3 + 0.02, 1 / 3].map((x) => expect.closeTo(x, 12)));
    cmd({ k: "moveSplitter", pane: 0, by: -1 }); // End's opposite: pane 0 at its 48 px minimum
    frame();
    expect(heights()).toEqual([48, 352, 200]);
    const posted = layouts().length;
    cmd({ k: "moveSplitter", pane: 0, by: -0.02 }); // at the limit: unchanged, still posted
    frame();
    expect([layouts().length, heights()]).toEqual([posted + 1, [48, 352, 200]]);
    cmd({ k: "moveSplitter", pane: 9, by: 0.02 }); // an unknown key: nothing
    frame();
    expect(layouts()).toHaveLength(posted + 1);
  });

  it("a key's seq comes back once as the next layout's ack; Home's even when nothing moved", () => {
    cmd({ k: "moveSplitter", pane: 0, by: -0.02, seq: 7 });
    frame();
    expect(layouts().at(-1)?.ack).toBe(7);
    cmd({ k: "setPaneShares", shares: [[0, 0.5]] }); // no seq: no ack
    frame();
    expect(layouts().at(-1)?.ack).toBeUndefined();
    const posted = layouts().length;
    const equal = [0, 1, 2].map((k) => [k, 1 / 3]);
    cmd({ k: "setPaneShares", shares: equal, seq: 8 });
    frame();
    cmd({ k: "setPaneShares", shares: equal, seq: 9 }); // already equal: still answered
    frame();
    expect(
      layouts()
        .slice(posted)
        .map((l) => l.ack),
    ).toEqual([8, 9]);
    cmd({ k: "setPaneShares", shares: [[9, 1]], seq: 10 }); // refused: never acked
    frame();
    cmd({ k: "setPaneShares", shares: [[0, 0.5]] });
    frame();
    expect(layouts().at(-1)?.ack).toBeUndefined();
  });

  it("removePane's seq is acked on the layout that announces the re-key, every slot keyed (R58)", () => {
    const posted = layouts().length;
    cmd({ k: "removePane", pane: 0, seq: 11 }); // slot 0 takes key 1, slot 1 key 2
    frame();
    const acked = layouts().slice(posted);
    expect(acked.map((l) => [l.ack, l.panes.map((p) => p.pane)])).toEqual([[11, [1, 2]]]);
    cmd({ k: "removePane", pane: 0, seq: 12 }); // a dead key removes nothing: never acked
    frame();
    expect(layouts().slice(posted)).toHaveLength(1);
    cmd({ k: "removePane", pane: 2, seq: 13 });
    cmd({ k: "removePane", pane: 1, seq: 14 }); // the sole pane: keyless, and still announced
    frame();
    expect(
      layouts()
        .slice(posted + 1)
        .map((l) => [l.ack, l.panes.map((p) => p.pane)]),
    ).toEqual([[14, [-1]]]);
  });
});
