// E11-S06 through the §8 facade on the fake DOM (README BQ-197, BQ-198, BQ-200): the axis stops
// appear with the first axes, their keys rescale through the worker, the announcement leaves as a
// `candleviewer:announce` event (no live region in the engine), the mirror lists the labels, and
// the lock badge hands focus to the price stop when it goes (G-19's focus half).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart, type ChartInternal } from "../../src/api/chart.js";
import { AxisModel } from "../../src/axes/axis-model.js";
import { ANNOUNCE_EVENT, createAnnouncer, createAxisStops } from "../../src/host/axis-stop.js";
import { ChartViewport } from "../../src/viewport/index.js";
import { minuteMap } from "../interaction/fixtures.js";
import type { ThemeTokens } from "../../src/index.js";
import { asHtml, fakeContainer, type FakeElement } from "./fake-dom.js";

const theme: ThemeTokens = { palette: "default", convention: "standard", colors: {} };
let container: FakeElement;
const frames = (n = 4): void => void vi.advanceTimersByTime(16 * n);
const stop = (axis: string): FakeElement | undefined =>
  container.children.find((el) => el.attributes.get("data-cv-axis-stop") === axis);
const press = (el: FakeElement | undefined, key: string): void =>
  void el?.dispatch("keydown", { key, code: key, stopPropagation: () => undefined });

function mount(): ChartInternal {
  const chart = createChart({ container: asHtml(container), theme }) as ChartInternal;
  const n = 300;
  const close = Int32Array.from({ length: n }, (_, i) => 127_900 + (i % 40));
  chart
    .addPane({})
    .addSeries("candles", { upColorToken: "u", downColorToken: "d" })
    .setData({
      time: Float64Array.from({ length: n }, (_, i) => 1_790_000_000_000_000 + i * 60e6),
      open: close,
      high: close.map((c) => c + 4),
      low: close.map((c) => c - 4),
      close,
      volume: new Float32Array(n),
      priceOrigin: 0,
      tickSize: 0.5,
    });
  return chart;
}

beforeEach(() => {
  vi.useFakeTimers();
  container = fakeContainer(800, 400);
  const view = container.ownerDocument.defaultView as { CustomEvent?: unknown };
  view.CustomEvent = class {
    readonly detail: unknown;
    constructor(
      readonly type: string,
      init: { detail: unknown },
    ) {
      this.detail = init.detail;
    }
  };
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the axis stops through the facade", () => {
  it("appear with the first axes: named groups, a mirror list per axis", () => {
    const chart = mount();
    expect(stop("price")).toBeUndefined(); // no axes before the first frame
    frames();
    const price = stop("price");
    expect(price?.attributes.get("role")).toBe("group");
    expect(price?.attributes.get("tabindex")).toBe("0");
    // No price source inline until E12, so the window is the empty default: no span yet.
    expect(price?.attributes.get("aria-label")).toMatch(/^Price axis(, .+ to .+)?, linear, auto$/);
    expect(stop("time")?.attributes.get("aria-label")).toMatch(/^UTC time axis/);
    const lists = (chart.getDomMirrorRoot() as unknown as FakeElement).children.filter(
      (el) => el.tagName === "UL",
    );
    expect(lists.map((ul) => ul.attributes.get("aria-label"))).toEqual([
      "Time axis labels",
      "Price axis labels",
    ]);
    expect(lists[0]?.children.length).toBeGreaterThan(2);
    chart.dispose();
    expect(stop("price")).toBeUndefined();
  });

  it("Up on the price stop locks and announces through the app's announcer, not a region", () => {
    const chart = mount();
    frames();
    const heard: unknown[] = [];
    container.addEventListener(ANNOUNCE_EVENT, (e) =>
      heard.push((e as { detail: unknown }).detail),
    );
    press(stop("price"), "ArrowUp");
    frames();
    expect(chart.panes[0]?.priceScale.getState().autoScale).toBe(false);
    expect(heard).toEqual([
      { politeness: "polite", text: "Price scale locked", key: "chart:axis" },
    ]);
    expect(container.children.some((el) => el.attributes.has("aria-live"))).toBe(false);
    // The badge, activated from the keyboard, hands focus to the price stop (G-19).
    const badge = container.children.find((el) => el.attributes.has("data-cv-scale-badge"));
    container.ownerDocument.activeElement = badge ?? null;
    badge?.dispatch("click", {});
    frames();
    expect(container.ownerDocument.activeElement).toBe(stop("price"));
    press(stop("price"), "Escape");
    expect(container.ownerDocument.activeElement).toBe(container);
    chart.dispose();
  });

  it("Shift+F10 on the price stop opens the scale menu by key", () => {
    const chart = mount();
    frames();
    const menus: unknown[] = [];
    stop("price")?.addEventListener("candleviewer:pricescalemenu", (e) =>
      menus.push((e as { detail: unknown }).detail),
    );
    stop("price")?.dispatch("keydown", { key: "F10", shiftKey: true, stopPropagation: () => 0 });
    expect(menus).toEqual([{ pane: 0, x: 0, y: 0, byKey: true }]);
    chart.dispose();
  });
});

describe("Scenario: Tick labels are present in the accessibility tree", () => {
  it("the mirror lists exactly the frame's tick model, text swapped in place", () => {
    const vp = new ChartViewport(minuteMap());
    vp.setSize(1200, 600, 1);
    vp.setPanePlot(0, 0, 600);
    vp.setPriceInfo(0, 0, 0.5);
    vp.setPriceRange(0, 127_800, 128_600);
    const model = new AxisModel();
    const layout = {
      width: 1261,
      height: 624,
      priceGutter: 61,
      panes: [{ rect: [0, 0, 1200, 600] as [number, number, number, number] }],
      timeAxis: [0, 600, 1200, 24] as [number, number, number, number],
    };
    model.update(vp, layout, {});
    const kept = (set: AxisModel["priceSet"]): string[] =>
      [...Array(set.n).keys()].flatMap((i) => (set.kept[i] === 1 ? [set.text[i] ?? ""] : []));
    const msg = {
      t: "axes" as const,
      id: 1,
      price: [...model.priceLabels],
      time: [...model.timeLabels],
      priceName: model.priceName,
      timeName: model.timeName,
      priceGutter: 61,
      timeZone: "UTC",
    };
    expect(msg.price).toEqual(kept(model.priceSet)); // what E11-S11 draws, frame for frame
    expect(msg.price.slice(0, 3)).toEqual(["63,950.0", "64,000.0", "64,050.0"]); // edges hidden
    const mirror = container.ownerDocument.createElement("div");
    const clock = { now: () => 0, setTimer: () => undefined };
    const stops = createAxisStops(asHtml(container), asHtml(mirror), { input: () => 0 }, {}, clock);
    stops.update(msg);
    const [time, price] = mirror.children;
    expect(price?.children.map((li) => li.textContent)).toEqual(msg.price);
    expect(time?.children.map((li) => li.textContent)).toEqual(msg.time);
    expect(stops.price.getAttribute("aria-label")).toBe(msg.priceName);
    const first = price?.children[0];
    stops.update({ ...msg, price: msg.price.slice(1) }); // one label fewer
    expect(price?.children.map((li) => li.textContent)).toEqual(msg.price.slice(1));
    expect(price?.children[0]).toBe(first); // the node is reused
    stops.dispose();
    expect(mirror.children).toHaveLength(0);
  });
});

describe("announcements (BQ-198): no engine live region, E06-D03 D5's cadence", () => {
  let now: number;
  let timers: { at: number; cb: () => void }[];
  let heard: { text: string; at: number }[];
  let say: (text: string) => void;
  /** Runs every timer due by `to`, in time order. */
  const run = (to: number): void => {
    for (;;) {
      const due = timers.filter((t) => t.at <= to).sort((a, b) => a.at - b.at)[0];
      if (due === undefined) break;
      timers.splice(timers.indexOf(due), 1);
      now = due.at;
      due.cb();
    }
    now = to;
  };
  beforeEach(() => {
    now = 0;
    timers = [];
    heard = [];
    container.addEventListener(ANNOUNCE_EVENT, (e) => {
      heard.push({ text: (e as { detail: { text: string } }).detail.text, at: now });
    });
    say = createAnnouncer(asHtml(container), {
      now: () => now,
      setTimer: (cb, ms) => void timers.push({ at: now + ms, cb }),
    });
  });

  it("dispatches at once, then the latest state once per 500 ms while a key repeats", () => {
    for (let i = 1; i <= 8; i += 1) {
      run(i * 120); // key repeat: one press every 120 ms
      say(`range ${i}`);
    }
    run(2000);
    expect(heard.map((h) => h.text)).toEqual(["range 1", "range 5", "range 8"]);
    for (let i = 1; i < heard.length; i += 1) {
      expect((heard[i]?.at ?? 0) - (heard[i - 1]?.at ?? 0)).toBeGreaterThanOrEqual(500);
    }
  });

  it("the final state lands within 250 ms of the last request (trailingFlush)", () => {
    say("first");
    run(100);
    say("second");
    run(2000);
    expect(heard).toEqual([
      { text: "first", at: 0 },
      { text: "second", at: 350 },
    ]);
  });

  it("a key held 1.5 s announces 2/s and its final state by 1750 ms (E06-D03 §5)", () => {
    for (let t = 0; t <= 1500; t += 60) {
      run(t);
      say(`at ${t}`);
    }
    run(5000);
    const last = heard.at(-1);
    expect(last?.text).toBe("at 1500");
    expect(last?.at).toBeLessThanOrEqual(1750);
    const inside = heard.slice(0, -1);
    for (let i = 1; i < inside.length; i += 1) {
      expect((inside[i]?.at ?? 0) - (inside[i - 1]?.at ?? 0)).toBeGreaterThanOrEqual(500);
    }
    expect(heard.length).toBeLessThanOrEqual(5); // 0, 500, 1000, 1500 and the flush at most
  });

  it("a pending state is dropped once the container is unmounted", () => {
    say("first");
    run(100);
    say("second");
    Object.defineProperty(container, "isConnected", { value: false }); // the DOM getter
    run(2000);
    expect(heard.map((h) => h.text)).toEqual(["first"]);
  });
});
