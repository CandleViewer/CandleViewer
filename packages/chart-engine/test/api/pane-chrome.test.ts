// E11-S09 PR 1's DOM chrome (#446 BQ-11, BQ-16, BQ-19, BQ-20; E11-D02 §8, §12): the separators'
// keys, values and announcements, the collapsed stub and its restore button, the pane regions in
// the mirror, and teardown. On the package's fake DOM (it has no jsdom: no new dependency); the
// facade half runs the inline runtime under fake timers.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart, type ChartInternal } from "../../src/api/chart.js";
import type { PaneInternal } from "../../src/api/pane.js";
import { ANNOUNCE_EVENT } from "../../src/host/axis-stop.js";
import {
  createPaneChrome,
  PANE_ANNOUNCE_KEY,
  type LayoutMessage,
  type PaneChromeSink,
} from "../../src/host/pane-chrome.js";
import type { ThemeTokens } from "../../src/index.js";
import type { PaneBox } from "../../src/worker/protocol.js";
import { asHtml, fakeContainer, type FakeElement } from "./fake-dom.js";

type Said = { politeness: string; text: string; key: string };
type Shares = readonly (readonly [number, number])[];

const LABELS = ["Price pane", "Volume pane", "CVD pane"];
const labelOf = (key: number): string => LABELS[key] ?? `Pane ${key + 1}`;

/** 60 / 20 / 20 of a 600 px stack, optionally with pane 1 collapsed to its 24 px stub. */
function layout(collapsed = false): LayoutMessage {
  const panes: PaneBox[] = collapsed
    ? [
        { pane: 0, top: 0, height: 432, share: 0.6, collapsed: false },
        { pane: 1, top: 432, height: 24, share: 0.2, collapsed: true },
        { pane: 2, top: 456, height: 144, share: 0.2, collapsed: false },
      ]
    : [
        { pane: 0, top: 0, height: 360, share: 0.6, collapsed: false },
        { pane: 1, top: 360, height: 120, share: 0.2, collapsed: false },
        { pane: 2, top: 480, height: 120, share: 0.2, collapsed: false },
      ];
  return { t: "layout", id: 1, panes, timeAxis: [600, 24], plotWidth: 736 };
}

let container: FakeElement;
let mirror: FakeElement;
let said: Said[];
let sent: Shares[];
let restored: number[];

const sink: PaneChromeSink = {
  shares: (s) => void sent.push(s),
  restore: (pane) => void restored.push(pane),
};
const clock = {
  now: () => Date.now(),
  setTimer: (cb: () => void, ms: number) => void setTimeout(cb, ms),
};
const theme = { "color.surface.raised": "#1e2329", "color.text.secondary": "#929aa5" };

function chrome() {
  return createPaneChrome(asHtml(container), asHtml(mirror), sink, theme, clock);
}

/** A key on the separator, 600 ms after the last (past the announcer's 500 ms window). */
function press(el: HTMLElement | undefined, key: string, shiftKey = false): boolean {
  vi.advanceTimersByTime(600); // the fake timers move Date.now() too
  return (el as unknown as FakeElement).dispatch("keydown", {
    key,
    shiftKey,
    stopPropagation: () => undefined,
  });
}

const attr = (el: HTMLElement | undefined, name: string): string | null =>
  el?.getAttribute(name) ?? null;
const stubs = (): FakeElement[] =>
  container.children.filter((c) => c.attributes.has("data-cv-pane-stub"));
const total = (s: Shares | undefined): number => (s ?? []).reduce((a, [, x]) => a + x, 0);

beforeEach(() => {
  vi.useFakeTimers();
  container = fakeContainer(800, 624);
  mirror = container.ownerDocument.createElement("div");
  container.appendChild(mirror);
  said = [];
  sent = [];
  restored = [];
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
  container.addEventListener(ANNOUNCE_EVENT, (e) => said.push((e as { detail: Said }).detail));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Scenario: Splitters are operable without a mouse", () => {
  it("Down x3 then Home: 60 -> 58 -> 56 -> 54 %, then equal; 4 announcements; sums of exactly 1", () => {
    const c = chrome();
    c.update(layout(), labelOf);
    const sep = c.separators[0];
    expect(c.separators).toHaveLength(2);
    expect(attr(sep, "aria-valuenow")).toBe("60");
    const values: string[] = [];
    for (let i = 0; i < 3; i += 1) {
      expect(press(sep, "ArrowDown")).toBe(true); // handled: the page never scrolls
      values.push(attr(sep, "aria-valuenow") ?? "");
    }
    expect(values).toEqual(["58", "56", "54"]);
    expect(attr(sep, "aria-valuetext")).toBe("Price pane 54 percent, Volume pane 26 percent");
    press(sep, "Home");
    expect(attr(sep, "aria-valuenow")).toBe("33");
    expect(sent).toHaveLength(4);
    for (const s of sent) expect(total(s)).toBe(1); // exactly, never 0.999
    expect(sent[2]?.map(([k, x]) => [k, x.toFixed(6)])).toEqual([
      [0, "0.540000"],
      [1, "0.260000"],
      [2, "0.200000"],
    ]);
    expect(sent[3]?.map(([k, x]) => [k, x.toFixed(6)])).toEqual([
      [0, "0.333333"],
      [1, "0.333333"],
      [2, "0.333333"],
    ]);
    vi.advanceTimersByTime(2000); // no trailing repeat
    expect(said).toEqual([
      { politeness: "polite", text: "Volume pane 22 percent", key: PANE_ANNOUNCE_KEY },
      { politeness: "polite", text: "Volume pane 24 percent", key: PANE_ANNOUNCE_KEY },
      { politeness: "polite", text: "Volume pane 26 percent", key: PANE_ANNOUNCE_KEY },
      { politeness: "polite", text: "Panes equal", key: PANE_ANNOUNCE_KEY },
    ]);
    c.update(layout(), labelOf); // the worker's next layout: aria follows it, nothing is said
    expect(attr(sep, "aria-valuenow")).toBe("60");
    expect(said).toHaveLength(4);
    c.dispose();
  });

  it("names both panes; Shift steps 10 %, End maximises, the limits hold and say nothing", () => {
    const c = chrome();
    c.update(layout(), labelOf);
    const [top, bottom] = c.separators;
    expect(
      ["role", "aria-orientation", "tabindex", "aria-label", "aria-valuemin", "aria-valuemax"].map(
        (n) => attr(bottom, n),
      ),
    ).toEqual(["separator", "horizontal", "0", "Resize Volume pane and CVD pane", "8", "32"]);
    press(top, "ArrowUp", true);
    expect(attr(top, "aria-valuenow")).toBe("70");
    press(bottom, "End");
    expect(attr(bottom, "aria-valuenow")).toBe("84"); // the others at their 8 % minimum
    expect(said.at(-1)?.text).toBe("Volume pane 84 percent");
    const before = sent.length;
    press(bottom, "ArrowUp"); // already at its maximum
    expect(sent).toHaveLength(before);
    expect(press(bottom, "Tab")).toBe(false); // Tab leaves: not handled
    press(bottom, "Escape");
    expect(container.ownerDocument.activeElement).toBe(container);
    expect(said.map((s) => s.text)).toEqual(["Volume pane 10 percent", "Volume pane 84 percent"]);
    c.dispose();
  });

  it("the separators let pointers through; the cursor shows row-resize over a band only", () => {
    const c = chrome();
    c.update(layout(), labelOf);
    const sep = c.separators[0];
    expect([sep?.style.pointerEvents, sep?.style.top, sep?.style.height]).toEqual([
      "none",
      "348px",
      "24px",
    ]);
    container.dispatch("pointermove", { clientY: 355 });
    expect(container.style["cursor"]).toBe("row-resize");
    container.dispatch("pointermove", { clientY: 356 });
    container.dispatch("pointermove", { clientY: 200 });
    expect(container.style["cursor"]).toBe("");
    c.dispose();
  });
});

describe("Scenario: A pane too small to read collapses honestly (chrome)", () => {
  it("a stub names the pane, says collapsed and restores; collapse and restore are said once", () => {
    const c = chrome();
    c.update(layout(), labelOf);
    expect(stubs()).toHaveLength(0);
    c.update(layout(true), labelOf);
    const [row] = stubs();
    expect(row?.children.map((el) => el.textContent)).toEqual(["Volume pane", "collapsed", ""]);
    expect([row?.style["top"], row?.style["height"], row?.style["background"]]).toEqual([
      "432px",
      "24px",
      "#1e2329",
    ]);
    expect(row?.children[1]?.style["color"]).toBe("#929aa5");
    const button = row?.children[2];
    expect([button?.tagName, button?.attributes.get("aria-label")]).toEqual([
      "BUTTON",
      "Restore Volume pane",
    ]);
    button?.dispatch("click", {});
    expect(restored).toEqual([1]);
    c.update(layout(true), labelOf); // the same state again: nothing new
    c.update(layout(), labelOf);
    expect(stubs()).toHaveLength(0);
    vi.advanceTimersByTime(2000);
    expect(said.map((s) => s.text)).toEqual(["Volume pane collapsed", "Volume pane restored"]);
    c.dispose();
  });

  it("keys beside a stub: arrows and End move nothing and say why; Home and End skip stubs", () => {
    const c = chrome();
    c.update(layout(true), labelOf); // pane 1 is a stub
    const [top, bottom] = c.separators;
    press(top, "ArrowDown");
    press(bottom, "ArrowUp");
    press(bottom, "End"); // the pane above it is the stub
    expect(sent).toEqual([]);
    expect(said.map((x) => x.text)).toEqual([
      "Volume pane collapsed",
      "Volume pane collapsed",
      "Volume pane collapsed",
    ]);
    press(top, "Home"); // the expanded panes share what the stub does not keep
    expect(sent.at(-1)?.map(([k, x]) => [k, x.toFixed(6)])).toEqual([
      [0, "0.400000"],
      [1, "0.200000"],
      [2, "0.400000"],
    ]);
    press(top, "End"); // price at its maximum; the stub keeps its share
    expect(sent.at(-1)?.map(([k, x]) => [k, x.toFixed(6)])).toEqual([
      [0, "0.720000"],
      [1, "0.200000"],
      [2, "0.080000"],
    ]);
    for (const v of sent) expect(total(v)).toBe(1);
    // Shown over the expanded panes: 0.72 of the 0.8 the stub does not keep.
    expect(said.slice(3).map((x) => x.text)).toEqual(["Panes equal", "Price pane 90 percent"]);
    c.dispose();
  });

  it("with a stub present, values and announcements are height shares over the expanded panes", () => {
    const c = chrome();
    const msg = layout();
    const panes: PaneBox[] = [
      { pane: 0, top: 0, height: 406, share: 0.6, collapsed: false },
      { pane: 1, top: 406, height: 170, share: 0.25, collapsed: false },
      { pane: 2, top: 576, height: 24, share: 0.15, collapsed: true },
    ];
    c.update({ ...msg, panes }, labelOf);
    const [top, bottom] = c.separators;
    const spoken = (el: HTMLElement | undefined): number[] =>
      [...(attr(el, "aria-valuetext") ?? "").matchAll(/(\d+) percent/g)].map((m) => Number(m[1]));
    expect(attr(top, "aria-valuetext")).toBe("Price pane 71 percent, Volume pane 29 percent");
    expect(spoken(top).reduce((x, y) => x + y, 0)).toBe(100);
    expect(attr(top, "aria-valuenow")).toBe("71");
    expect(attr(bottom, "aria-valuetext")).toBe("Volume pane 29 percent, CVD pane collapsed");
    press(top, "ArrowDown");
    expect(spoken(top)).toEqual([68, 32]); // 0.58 / 0.85 and 0.27 / 0.85
    expect(said.at(-1)?.text).toBe("Volume pane 32 percent");
    c.dispose();
  });

  it("an aria-labelled region per pane in the mirror; a removed pane takes its chrome along", () => {
    const c = chrome();
    c.update(layout(true), labelOf);
    const regions = () => mirror.children.map((r) => [r.getAttribute("role"), r.textContent]);
    expect(mirror.children.map((r) => r.getAttribute("aria-label"))).toEqual(LABELS);
    expect(regions().every(([role]) => role === "region")).toBe(true);
    const two = layout(true);
    c.update({ ...two, panes: [two.panes[0] as PaneBox, two.panes[2] as PaneBox] }, labelOf);
    expect(mirror.children.map((r) => r.getAttribute("aria-label"))).toEqual([
      "Price pane",
      "CVD pane",
    ]);
    expect([c.separators.length, stubs().length]).toEqual([1, 0]);
    c.dispose();
  });

  it("the chrome's DOM keeps the a11y rules axe checks here (name, value, role, button name)", () => {
    const c = chrome();
    c.update(layout(true), labelOf);
    const all = (el: FakeElement): FakeElement[] => [el, ...el.children.flatMap(all)];
    const nodes = all(container);
    for (const el of nodes) {
      const role = el.getAttribute("role");
      // aria-required-attr / aria-input-field-name: a focusable separator is a widget.
      if (role === "separator") {
        expect(el.getAttribute("tabindex")).toBe("0");
        for (const a of ["aria-valuenow", "aria-valuemin", "aria-valuemax", "aria-label"]) {
          expect(el.getAttribute(a), a).toMatch(/\S/);
        }
        expect(Number(el.getAttribute("aria-valuemin"))).toBeLessThanOrEqual(
          Number(el.getAttribute("aria-valuenow")),
        );
      }
      // region: a landmark has a name. button-name: every button is named.
      if (role === "region") expect(el.getAttribute("aria-label")).toMatch(/\S/);
      if (el.tagName === "BUTTON") expect(el.getAttribute("aria-label")).toMatch(/^Restore /);
      // Decorative glyphs and the grip stay out of the tree.
      if (el.textContent === "⌄" || el.style["borderRadius"] === "2px") {
        expect(el.getAttribute("aria-hidden")).toBe("true");
      }
    }
    c.dispose();
  });

  it("dispose removes every element and the pointer listener; later updates do nothing", () => {
    const c = chrome();
    c.update(layout(true), labelOf);
    container.dispatch("pointermove", { clientY: 432 });
    expect(container.style["cursor"]).toBe("row-resize");
    const kids = container.children.length;
    c.dispose();
    c.dispose();
    expect(container.children.length).toBe(kids - 3); // two separators and the stub
    expect(mirror.children).toHaveLength(0);
    expect(container.listeners.get("pointermove")?.size ?? 0).toBe(0);
    expect(container.style["cursor"]).toBe("");
    c.update(layout(), labelOf);
    expect(container.children.length).toBe(kids - 3);
  });
});

describe("the chrome through the facade (BQ-16)", () => {
  const tokens: ThemeTokens = { palette: "default", convention: "standard", colors: {} };
  const frame = (): void => void vi.advanceTimersByTime(16);

  it("Pane.setCollapsed reaches the worker: collapsed follows the layout, refusals included", () => {
    const chart = createChart({ container: asHtml(container), theme: tokens }) as ChartInternal;
    const a = chart.addPane({ heightRatio: 0.6 }) as PaneInternal;
    const b = chart.addPane({ heightRatio: 0.4, label: "Volume pane" }) as PaneInternal;
    frame();
    expect(container.children.filter((c) => c.getAttribute("role") === "separator")).toHaveLength(
      1,
    );
    b.setCollapsed(true);
    expect(b.collapsed).toBe(false); // not optimistic: the next layout says
    a.setCollapsed(true); // the last expanded pane: the worker refuses
    frame();
    expect([a.collapsed, b.collapsed]).toEqual([false, true]);
    const [row] = stubs();
    expect(row?.children[0]?.textContent).toBe("Volume pane");
    row?.children[2]?.dispatch("click", {});
    b.setCollapsed(true); // collapse and restore in one tick: the last call wins
    b.setCollapsed(false);
    frame();
    expect(stubs()).toHaveLength(0);
    expect(b.collapsed).toBe(false);
    expect(() => b.setCollapsed(1 as unknown as boolean)).toThrow(TypeError);
    chart.setTheme(tokens);
    chart.dispose();
    expect(container.children.filter((c) => c.getAttribute("role") === "separator")).toHaveLength(
      0,
    );
  });
});
