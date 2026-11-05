// E11-S09 PR 1b review fixes on the pane chrome alone (fake DOM, a scripted worker): a key is
// answered only by the `layout` that acks it; hover, drag and focus colours (D02 §8); the band's
// y is the container's, whatever child the pointer is over; and a click in a band selects the
// splitter, the non-drag path of WCAG 2.5.7 (05 §3.1 item 8).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ANNOUNCE_EVENT } from "../../src/host/axis-stop.js";
import {
  createPaneChrome,
  type LayoutMessage,
  type PaneChrome,
} from "../../src/host/pane-chrome.js";
import type { ChartId, Command, PaneRow } from "../../src/worker/protocol.js";
import { asHtml, fakeContainer, type FakeElement } from "./fake-dom.js";

const colors = {
  "color.text.tertiary": "#101010",
  "color.text.secondary": "#202020",
  "color.border.strong": "#303030",
  "color.focus.ring": "#404040",
};
const names = ["Price pane", "Volume pane", "CVD pane"];
let container: FakeElement;
let sent: Command[];
let said: string[];
let chrome: PaneChrome;
/** The announcer's clock: a counter the test moves with the fake timers (no wall clock). */
let clock = 0;
const wait = (ms: number): void => {
  clock += ms;
  vi.advanceTimersByTime(ms);
};

/** 60 / 20 / 20 of a 376 px plot: boundaries at 226 and 301. */
const rows = (ack?: number): LayoutMessage => {
  const panes: PaneRow[] = [
    { pane: 0, top: 0, height: 226, share: 0.6, collapsed: false },
    { pane: 1, top: 226, height: 75, share: 0.2, collapsed: false },
    { pane: 2, top: 301, height: 75, share: 0.2, collapsed: false },
  ];
  const base: LayoutMessage = {
    t: "layout",
    id: 1 as ChartId,
    panes,
    timeAxis: [376, 24],
    plotWidth: 736,
  };
  return ack === undefined ? base : { ...base, ack };
};
const press = (el: FakeElement | undefined, key: string): boolean =>
  el?.dispatch("keydown", { key, shiftKey: false, stopPropagation: () => undefined }) ?? false;
const seqOf = (cmd: Command | undefined): number | undefined =>
  cmd !== undefined && "seq" in cmd ? cmd.seq : undefined;

beforeEach(() => {
  vi.useFakeTimers();
  clock = 0;
  container = fakeContainer(800, 400);
  container.rectTop = 100; // the chart sits 100 px down the page
  const view = container.ownerDocument.defaultView as { CustomEvent?: unknown };
  view.CustomEvent = class {
    constructor(
      readonly type: string,
      readonly init: { detail: { text: string } },
    ) {}
  };
  said = [];
  container.addEventListener(ANNOUNCE_EVENT, (e) => {
    said.push((e as { init: { detail: { text: string } } }).init.detail.text);
  });
  sent = [];
  const mirror = container.ownerDocument.createElement("div");
  chrome = createPaneChrome(
    asHtml(container),
    asHtml(mirror),
    { command: (c) => void sent.push(c) },
    (k) => names[k] ?? "Pane",
    colors,
    { now: () => clock, setTimer: (cb, ms) => void setTimeout(cb, ms) },
  );
  chrome.update(rows());
});

afterEach(() => {
  chrome.dispose();
  vi.useRealTimers();
});

describe("a key is announced by the layout that acks it, once", () => {
  it("a layout posted before the key was handled says nothing; the acking one speaks", () => {
    const [a] = chrome.separators as unknown as FakeElement[];
    press(a, "ArrowDown");
    const seq = seqOf(sent.at(-1));
    expect(seq).toBeTypeOf("number");
    chrome.update(rows()); // a resize's layout, posted before the worker saw the key
    wait(600);
    expect(said).toEqual([]);
    chrome.update(rows(seq));
    wait(600);
    chrome.update(rows(seq)); // settled: the same ack again is not a second announcement
    wait(600);
    expect(said).toEqual(["Price pane 60 percent"]); // the pane above: its share is the value
  });

  it("a stale ack is ignored while a newer key is pending; the newer one speaks", () => {
    const [a, b] = chrome.separators as unknown as FakeElement[];
    press(a, "ArrowDown");
    const stale = seqOf(sent.at(-1));
    press(b, "ArrowDown");
    chrome.update(rows(stale)); // the first key's layout, after the second was sent
    wait(600);
    expect(said).toEqual([]);
    chrome.update(rows(seqOf(sent.at(-1))));
    wait(600);
    expect(said).toEqual(["Volume pane 20 percent"]);
  });

  it("a key the worker dropped never speaks through a later unrelated layout", () => {
    const [, b] = chrome.separators as unknown as FakeElement[];
    press(b, "Home");
    expect(sent.at(-1)).toMatchObject({ k: "moveSplitter", pane: 1, by: -1 });
    chrome.update(rows());
    chrome.update(rows());
    wait(600);
    expect(said).toEqual([]);
  });
});

describe("the D02 §8 splitter states and the band's y", () => {
  it("hover over a stub-row child still finds the band (container y, not offsetY)", () => {
    const [a] = chrome.separators as unknown as FakeElement[];
    const [line, grip] = a?.children ?? [];
    expect(grip?.style["background"]).toBe("#101010"); // rest
    // Over a chevron 4 px into its own box: offsetY 4, but the page y is on boundary 226.
    container.dispatch("pointermove", { clientY: 100 + 228, offsetY: 4 });
    expect(container.style["cursor"]).toBe("row-resize");
    expect([grip?.style["background"], line?.style["background"]]).toEqual(["#202020", "#303030"]);
    container.dispatch("pointermove", { clientY: 100 + 100, offsetY: 226 });
    expect(container.style["cursor"]).toBe("");
    expect([grip?.style["background"], line?.style["background"]]).toEqual([
      "#101010",
      "transparent",
    ]);
    container.dispatch("pointermove", { clientY: 100 + 228, offsetY: 4 });
    chrome.dispose(); // mid-hover: the cursor goes with the chrome
    expect(container.style["cursor"]).toBe("");
  });

  it("a drag in the band shows the ring colour on the grip and does not take focus", () => {
    const [a] = chrome.separators as unknown as FakeElement[];
    const grip = a?.children[1];
    container.dispatch("pointerdown", { clientX: 50, clientY: 100 + 226 });
    expect(grip?.style["background"]).toBe("#404040");
    container.dispatch("pointermove", { clientX: 50, clientY: 100 + 260 });
    container.dispatch("pointerup", { clientX: 50, clientY: 100 + 260 });
    expect(grip?.style["background"]).toBe("#101010");
    expect(container.ownerDocument.activeElement).toBeNull();
  });

  it("a click in the band selects the splitter; its arrow keys then nudge it (2.5.7)", () => {
    const [, b] = chrome.separators as unknown as FakeElement[];
    container.dispatch("pointerdown", { clientX: 300, clientY: 100 + 305 });
    container.dispatch("pointerup", { clientX: 301, clientY: 100 + 306 });
    expect(container.ownerDocument.activeElement).toBe(b);
    b?.dispatch("focus", {});
    expect(b?.children[1]?.style["outline"]).toBe("2px solid #404040");
    press(b, "ArrowDown");
    expect(sent.at(-1)).toMatchObject({ k: "moveSplitter", pane: 1, by: -0.02 });
  });

  it("a click outside every band selects nothing", () => {
    container.dispatch("pointerdown", { clientX: 300, clientY: 100 + 150 });
    container.dispatch("pointerup", { clientX: 300, clientY: 100 + 150 });
    expect(container.ownerDocument.activeElement).toBeNull();
  });
});
