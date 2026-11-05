// E11-S09 PR 1b through the §8 facade on the fake DOM (no jsdom in the package: test/api/fake-dom):
// the splitters are focusable `role="separator"`s with live `aria-value*`, keyboard-only resize
// and collapse / restore, one `candleviewer:announce` per key (never per frame, never an engine
// live region), and the collapsed stub names its pane and offers restore (E11-D02 §8, §12).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createChart, type ChartInternal } from "../../src/api/chart.js";
import type { PaneInternal } from "../../src/api/pane.js";
import { ANNOUNCE_EVENT } from "../../src/host/axis-stop.js";
import { PANE_ANNOUNCE_KEY, PANE_LABEL_MAX, paneLabel } from "../../src/host/pane-chrome.js";
import type { ThemeTokens } from "../../src/index.js";
import { asHtml, fakeContainer, type FakeElement } from "./fake-dom.js";

const theme: ThemeTokens = { palette: "default", convention: "standard", colors: {} };
let container: FakeElement;
let said: string[];
let chart: ChartInternal;
let panes: PaneInternal[];

const frames = (n = 4): void => void vi.advanceTimersByTime(16 * n);
/** Past the announcer's 500 ms repeat window, so the next key speaks at once. */
const settle = (): void => void vi.advanceTimersByTime(600);
const splitters = (): FakeElement[] =>
  container.children.filter((el) => el.attributes.get("role") === "separator");
const named = (root: FakeElement, name: string): FakeElement | undefined =>
  [root, ...root.children]
    .flatMap((c) => (c === root ? [] : [c, ...c.children]))
    .find((el) => el.attributes.get("aria-label") === name);
const press = (el: FakeElement | undefined, key: string, shiftKey = false): boolean =>
  el?.dispatch("keydown", { key, shiftKey, stopPropagation: () => undefined }) ?? false;
const aria = (el: FakeElement | undefined, name: string): string | undefined =>
  el?.attributes.get(`aria-${name}`);

beforeEach(() => {
  vi.useFakeTimers();
  container = fakeContainer(800, 400); // a 376 px plot
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
  said = [];
  container.addEventListener(ANNOUNCE_EVENT, (e) => {
    const d = (e as { detail: { key: string; text: string; politeness: string } }).detail;
    if (d.key === PANE_ANNOUNCE_KEY) said.push(`${d.politeness}: ${d.text}`);
  });
  chart = createChart({ container: asHtml(container), theme }) as ChartInternal;
  panes = [{}, { label: "Volume pane" }, { label: "CVD pane" }].map(
    (o) => chart.addPane(o) as PaneInternal,
  );
  frames();
  panes[0]?.setHeightRatio(0.6); // the others rescale into 0.4: 60 / 20 / 20
  frames();
  settle();
});

afterEach(() => {
  chart.dispose();
  vi.useRealTimers();
});

describe("Scenario: Splitters are operable without a mouse", () => {
  it("Down three times then Home: 60 → 58 → 56 → 54 %, then the minimum, 4 announcements", () => {
    const [sep] = splitters();
    expect(splitters()).toHaveLength(2);
    expect(aria(sep, "valuenow")).toBe("60");
    const now: (string | undefined)[] = [];
    for (let i = 0; i < 3; i += 1) {
      expect(press(sep, "ArrowDown")).toBe(true); // prevented: the plot never sees it
      frames();
      now.push(aria(sep, "valuenow"));
      settle();
    }
    expect(now).toEqual(["58", "56", "54"]);
    expect(panes[0]?.heightRatio).toBeCloseTo(0.54, 12);
    expect(panes[2]?.heightRatio).toBeCloseTo(0.2, 12); // only the two adjacent panes moved
    press(sep, "Home"); // End's mirror (BQ-19k, ruled): the pane above to its 48 px minimum
    frames();
    expect(aria(sep, "valuenow")).toBe("13");
    expect(panes.map((p) => p.heightRatio)).toEqual(
      [48 / 376, 0.8 - 48 / 376, 0.2].map((x) => expect.closeTo(x, 12)), // the CVD pane kept
    );
    settle();
    frames(30); // still frames: nothing more is said
    expect(said).toEqual([58, 56, 54, 13].map((n) => `polite: Price pane ${n} percent`));
  });

  it("is a named separator whose value, range and text track the shares", () => {
    const [a, b] = splitters();
    expect(a?.attributes.get("tabindex")).toBe("0");
    expect(aria(a, "orientation")).toBe("horizontal");
    expect(aria(a, "label")).toBe("Resize Price pane and Volume pane");
    expect([aria(a, "valuemin"), aria(a, "valuemax")]).toEqual(["0", "80"]);
    expect(aria(a, "valuetext")).toBe("Price pane 60 percent, Volume pane 20 percent");
    expect(aria(b, "label")).toBe("Resize Volume pane and CVD pane");
    press(b, "ArrowUp", true); // Shift: 10 %, the pane above grows, clamped at 48 of 376 px
    frames();
    expect(aria(b, "valuetext")).toBe("Volume pane 27 percent, CVD pane 13 percent");
    expect(said).toEqual(["polite: Volume pane 27 percent"]); // the pane above, as for End
  });

  it("End gives the pane above all the pane below can spare; Escape returns to the chart", () => {
    const [a] = splitters();
    press(a, "End");
    frames();
    // 48 px of the 376 px plot stay with the Volume pane (its minimum, D02:96).
    expect(panes[1]?.heightRatio).toBeCloseTo(48 / 376, 12);
    expect(said).toEqual([`polite: Price pane ${Math.round((0.8 - 48 / 376) * 100)} percent`]);
    press(a, "Escape");
    expect(container.ownerDocument.activeElement).toBe(container);
    expect(press(a, "Tab")).toBe(false); // the page's own keys pass
  });

  it("a held key announces the latest state, not every step (E06-D03 D5 cadence)", () => {
    const [a] = splitters();
    for (let i = 0; i < 5; i += 1) {
      press(a, "ArrowDown");
      frames(1);
    }
    settle();
    expect(said.length).toBeLessThanOrEqual(2);
    expect(said.at(-1)).toBe("polite: Price pane 50 percent");
  });

  it("the focus ring goes on the grip and the hairline; hovering a band sets row-resize", () => {
    const [a] = splitters();
    a?.focus();
    a?.dispatch("focus", {});
    const [line, grip] = a?.children ?? [];
    expect([grip?.style["outline"], line?.style["background"]]).toEqual(["2px solid ", ""]);
    container.ownerDocument.activeElement = null;
    a?.dispatch("blur", {});
    expect(grip?.style["outline"]).toBe("none");
    expect(grip?.style["width"]).toBe("32px"); // comfortable (D02:94)
    const y = Number.parseFloat(a?.style["top"] ?? "") + 12;
    container.dispatch("pointermove", { clientY: y });
    expect(container.style["cursor"]).toBe("row-resize");
    container.dispatch("pointermove", { clientY: y + 40 });
    expect(container.style["cursor"]).toBe("");
  });
});

describe("Scenario: A pane too small to read collapses honestly (the chrome)", () => {
  it("collapse and restore by keyboard: a labelled stub, one announcement each", () => {
    const fold = named(container, "Collapse Volume pane");
    expect(fold?.tagName).toBe("BUTTON");
    fold?.dispatch("click", {}); // Enter or Space on a native button
    frames();
    expect(panes[1]?.collapsed).toBe(true);
    const restore = named(container, "Restore Volume pane");
    const stub = restore?.parent;
    expect(stub?.style["display"]).toBe("block");
    expect(stub?.children.map((c) => c.textContent)).toEqual([
      "Volume pane",
      "collapsed",
      "Restore",
    ]);
    expect(named(container, "Collapse Volume pane")?.style["display"]).toBe("none");
    settle();
    restore?.dispatch("click", {});
    frames();
    expect([panes[1]?.collapsed, stub?.style["display"]]).toEqual([false, "none"]);
    expect(said).toEqual(["polite: Volume pane collapsed", "polite: Volume pane restored"]);
  });

  it("each pane is a labelled region in the DOM mirror; dispose removes the chrome", () => {
    const mirror = chart.getDomMirrorRoot() as unknown as FakeElement;
    const regions = mirror.children.filter((el) => el.attributes.get("role") === "region");
    expect(regions.map((r) => aria(r, "label"))).toEqual(["Price pane", "Volume pane", "CVD pane"]);
    panes[2]?.remove();
    frames();
    expect(splitters()).toHaveLength(1);
    expect(mirror.children.filter((el) => el.attributes.get("role") === "region")).toHaveLength(2);
    chart.dispose();
    expect(splitters()).toHaveLength(0);
  });
});

describe("Review fixes (E11-S09 PR 1b): announcements, labels and collapsed values", () => {
  it("a key that restores a pane says so once; a later unrelated layout says nothing", () => {
    panes[0]?.setHeightRatio(0.2); // 20 / 40 / 40: the Volume pane can give the CVD pane back
    frames();
    named(container, "Collapse CVD pane")?.dispatch("click", {});
    frames();
    settle();
    const [, b] = splitters();
    expect(aria(b, "valuetext")).toMatch(/^Volume pane \d+ percent, CVD pane collapsed$/);
    press(b, "ArrowDown"); // toward the stub: reopens it (BQ-19p)
    frames();
    expect(panes[2]?.collapsed).toBe(false);
    settle();
    panes[0]?.setHeightRatio(0.3); // an unrelated layout
    frames();
    settle();
    expect(said).toEqual(["polite: CVD pane collapsed", "polite: CVD pane restored"]);
  });

  it("a label is trimmed, its whitespace collapsed and capped; a blank one falls back", () => {
    expect(paneLabel("  Funding \n\t pane ", "Pane 2")).toBe("Funding pane");
    expect(paneLabel(" \n ", "Pane 2")).toBe("Pane 2");
    expect(paneLabel(42, "Pane 2")).toBe("Pane 2");
    expect(paneLabel("x".repeat(200), "Pane 2")).toHaveLength(PANE_LABEL_MAX);
    chart.addPane({ label: `  ${"y".repeat(100)}  ` });
    chart.addPane({ label: "   " });
    frames();
    const mirror = chart.getDomMirrorRoot() as unknown as FakeElement;
    const names = mirror.children
      .filter((el) => el.attributes.get("role") === "region")
      .map((r) => aria(r, "label"));
    expect(names.slice(3)).toEqual(["y".repeat(PANE_LABEL_MAX), "Pane 5"]);
  });

  it("a theme switch repaints the grips and the stubs without waiting for a layout", () => {
    named(container, "Collapse Volume pane")?.dispatch("click", {});
    frames();
    const colors = {
      "color.text.tertiary": "#111111",
      "color.surface.raised": "#222222",
      "color.text.primary": "#333333",
    };
    chart.setTheme({ ...theme, colors });
    const [a] = splitters();
    const stub = named(container, "Restore Volume pane")?.parent;
    expect(a?.children[1]?.style["background"]).toBe("#111111");
    expect([stub?.style["background"], stub?.children[0]?.style["color"]]).toEqual([
      "#222222",
      "#333333",
    ]);
  });
});
