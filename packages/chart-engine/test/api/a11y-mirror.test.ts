// E11-S13 PR-2: the mirror behind its default-off flag (BQ-S13-15, C-4.13). The render runtime
// posts the window's rows; the facade writes the mirror; the host keeps today's tree when off.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart } from "../../src/api/chart.js";
import { mountSurface } from "../../src/host/mount.js";
import type { ThemeTokens } from "../../src/index.js";
import type * as HostModule from "../../src/worker/host.js";
import type { ChartHostOptions } from "../../src/worker/host.js";
import { BACKGROUND_TOKEN, type FromWorker } from "../../src/worker/protocol.js";
import { createRenderRuntime, type RenderRuntime } from "../../src/worker/runtime.js";
import { makeBars, type MirrorBars } from "../../bench/scenes/dom-mirror.js";
import { FakeCtx2D } from "../canvas2d/fake-ctx2d.js";
import { FULL } from "../gl/fake-gl.js";
import { asHtml, fakeContainer, FakeElement } from "./fake-dom.js";

const captured: { deliver: ((m: FromWorker) => void) | null; opts: ChartHostOptions | null } = {
  deliver: null,
  opts: null,
};
vi.mock("../../src/worker/host.js", async (importOriginal) => {
  const actual = await importOriginal<typeof HostModule>();
  return {
    ...actual,
    createChartHost: (o: ChartHostOptions) => {
      captured.deliver = o.listener.deliver;
      captured.opts = o;
      return actual.createChartHost(o);
    },
  };
});

const theme: ThemeTokens = { palette: "default", convention: "standard", colors: {} };
type A11yMsg = Extract<FromWorker, { t: "a11y" }>;

let out: { msg: FromWorker; transfer: ArrayBuffer[] | undefined }[];
const a11y = (): A11yMsg[] => out.map((o) => o.msg).filter((m): m is A11yMsg => m.t === "a11y");
const frame = (): void => void vi.advanceTimersByTime(16);

function runtime(bars: MirrorBars, opts: { mirror?: boolean; probe?: typeof FULL } = {}) {
  const rt: RenderRuntime = createRenderRuntime({
    runMode: "inline",
    post: (msg, transfer) => out.push({ msg, transfer }),
    requestFrame: (cb) => void setTimeout(cb, 16),
    now: () => Date.now(),
    setTimer: (cb, ms) => void setTimeout(cb, ms),
    probe: () => opts.probe ?? FULL,
    timeMap: bars,
    a11yBars: bars,
  });
  return (profile?: "degraded-2d"): RenderRuntime => {
    const ctx = new FakeCtx2D();
    rt.handle({
      t: "init",
      id: 1,
      canvas: { width: 800, height: 200, getContext: () => ctx },
      dpr: 1,
      theme: { [BACKGROUND_TOKEN]: "#000000" },
      config: { bench: false, syncGroup: null, ...(opts.mirror === true && { a11yMirror: true }) },
      ...(profile !== undefined && { profile }),
    });
    frame();
    return rt;
  };
}

const deliverLast = (): void => {
  const m = a11y().at(-1);
  if (m === undefined) throw new Error("no a11y message");
  captured.deliver?.(m);
  frame(); // the mirror's one batched write
};

beforeEach(() => {
  vi.useFakeTimers();
  out = [];
  FakeElement.markupWrites = 0;
});

afterEach(() => {
  vi.useRealTimers();
});

describe("flag off: today's tree (C-4.13)", () => {
  it("test_mount_flag_off_keeps_the_aria_hidden_canvas_and_no_wrapper", () => {
    const c = fakeContainer();
    const s = mountSurface(asHtml(c));
    const canvas = c.children[0];
    expect(c.children.map((e) => e.tagName)).toEqual(["CANVAS", "DIV"]);
    expect(canvas?.getAttribute("aria-hidden")).toBe("true");
    expect(canvas?.getAttribute("role")).toBeNull();
    s.setCanvasLabel("ignored");
    s.replaceCanvas();
    expect(c.children[0]?.getAttribute("aria-hidden")).toBe("true");
    expect(c.children[0]?.getAttribute("aria-label")).toBeNull();
  });

  it("test_chart_flag_off_builds_no_table_and_asks_the_worker_for_no_rows", () => {
    const c = fakeContainer();
    const chart = createChart({ container: asHtml(c), theme });
    expect(captured.opts?.a11yMirror).toBe(false);
    runtime(makeBars(500), { mirror: true })();
    deliverLast();
    const root = chart.getDomMirrorRoot() as unknown as FakeElement;
    expect(root.children.some((e) => e.tagName === "TABLE")).toBe(false);
    expect(c.children[0]?.getAttribute("aria-hidden")).toBe("true");
    chart.dispose();
  });

  it("test_chart_flag_off_hands_listeners_null_rows_whatever_the_worker_sent", () => {
    const c = fakeContainer();
    const chart = createChart({ container: asHtml(c), theme });
    runtime(makeBars(500), { mirror: true })();
    expect(a11y().at(-1)?.rows?.count).toBe(60); // the worker did send rows
    const seen: unknown[] = [];
    chart.onA11yWindowChange((_w, rows) => seen.push(rows));
    deliverLast();
    expect(seen).toEqual([null]); // 26 §8: rows are null unless `a11y.mirror` is on
    chart.dispose();
  });

  it("test_runtime_flag_off_posts_no_rows", () => {
    runtime(makeBars(500))();
    expect(a11y()[0]?.rows).toBeUndefined();
    expect(a11y()[0]?.barCount).toBe(500);
  });
});

describe("flag on: the mirror, the application root and the canvas img", () => {
  it("test_mount_flag_on_canvas_img_is_named_before_the_first_label_roll", () => {
    const c = fakeContainer();
    const s = mountSurface(asHtml(c), true);
    const canvas = c.children[0]?.children[0];
    expect(canvas?.getAttribute("role")).toBe("img");
    expect(canvas?.getAttribute("aria-label")).toBe("Chart");
    expect(canvas?.getAttribute("tabindex")).toBe("-1"); // D4: not a tab stop
    s.setCanvasLabel("");
    expect(canvas?.getAttribute("aria-label")).toBe("Chart");
    s.unmount();
  });

  it("test_mount_flag_on_wraps_an_img_canvas_and_reapplies_its_label_on_replace", () => {
    const c = fakeContainer();
    const s = mountSurface(asHtml(c), true);
    const wrapper = c.children[0];
    expect(wrapper?.getAttribute("role")).toBe("application");
    expect(wrapper?.getAttribute("aria-roledescription")).toBe("trading chart"); // D4
    expect(wrapper?.getAttribute("aria-label")).toBe("Chart");
    expect(wrapper?.children.map((e) => e.tagName)).toEqual(["CANVAS", "DIV"]);
    s.setCanvasLabel("60 bars visible");
    const next = s.replaceCanvas() as unknown as FakeElement;
    expect(wrapper?.children[0]).toBe(next);
    expect(next.getAttribute("role")).toBe("img");
    expect(next.getAttribute("aria-hidden")).toBeNull();
    expect(next.getAttribute("aria-label")).toBe("60 bars visible");
    expect(next.getAttribute("tabindex")).toBe("-1");
    s.unmount();
    expect(c.children).toHaveLength(0);
  });

  it("test_chart_mirror_rows_match_the_worker_rows_and_label_rolls (AC4, AC6)", () => {
    const c = fakeContainer();
    const chart = createChart({ container: asHtml(c), theme, a11y: { mirror: true } });
    expect(captured.opts?.a11yMirror).toBe(true);
    const bars = makeBars(100_000);
    runtime(bars, { mirror: true })();
    const msg = a11y()[0];
    expect(msg?.rows?.count).toBe(60);
    expect(out.find((o) => o.msg === msg)?.transfer).toHaveLength(8);
    const seen: unknown[] = [];
    chart.onA11yWindowChange((_w, rows) => seen.push(rows));
    deliverLast();
    expect(seen).toEqual([msg?.rows]);
    const root = chart.getDomMirrorRoot() as unknown as FakeElement;
    const table = root.children.find((e) => e.tagName === "TABLE");
    const body = table?.children[1]?.children ?? [];
    expect(body).toHaveLength(60);
    expect(table?.getAttribute("aria-rowcount")).toBe("100001");
    expect(body.at(-1)?.getAttribute("aria-current")).toBe("true");
    const canvas = c.children[0]?.children[0];
    expect(canvas?.getAttribute("role")).toBe("img");
    expect(canvas?.getAttribute("aria-label")).toMatch(/bars visible, last close [\d.]+, delta/);
    expect(FakeElement.markupWrites).toBe(0);
    chart.dispose();
    expect(c.children).toHaveLength(0); // teardown: wrapper, canvas, mirror and table
  });

  it("test_runtime_reposts_rows_when_bars_change_without_a_window_move", () => {
    const bars = makeBars(500);
    const rt = runtime(bars, { mirror: true })();
    const n = a11y().length;
    bars.close[499] = 1;
    const buffer = new ArrayBuffer(0);
    const layout = { count: 0, columns: [], params: [] };
    rt.handle({ t: "data", id: 1, store: "bars", op: "patch", layout, buffer });
    frame();
    expect(a11y()).toHaveLength(n + 1);
    expect(a11y().at(-1)?.rows?.close[59]).toBe(1);
  });
});

describe("one mirror snapshot under every RenderProfile (26 §12 :783 contract)", () => {
  it("test_mirror_rows_are_identical_under_full_reduced_and_degraded_2d", () => {
    const snapshots = (["full", "reduced", "degraded-2d"] as const).map((profile) => {
      out = [];
      const probe = { ...FULL, profile: profile === "reduced" ? "reduced" : FULL.profile };
      const start = runtime(makeBars(2_000), { mirror: true, probe: probe as typeof FULL });
      start(profile === "degraded-2d" ? "degraded-2d" : undefined);
      const c = fakeContainer();
      const chart = createChart({ container: asHtml(c), theme, a11y: { mirror: true } });
      deliverLast();
      const table = (chart.getDomMirrorRoot() as unknown as FakeElement).children.find(
        (e) => e.tagName === "TABLE",
      );
      const text = (table?.children[1]?.children ?? []).map((tr) => [
        tr.getAttribute("aria-rowindex"),
        ...tr.children.map((td) => td.textContent),
      ]);
      chart.dispose();
      const wire = a11y()[0];
      return { wire, text };
    });
    expect(snapshots[0]?.text).toHaveLength(60);
    expect(snapshots[1]).toEqual(snapshots[0]);
    expect(snapshots[2]).toEqual(snapshots[0]);
  });
});
