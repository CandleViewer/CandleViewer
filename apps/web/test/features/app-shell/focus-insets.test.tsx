// E47-S05 slice 4 (#1319), Gherkin "A focused control is never hidden": the sticky-chrome inset
// registry, the focusin scroll helper and AppShell's wiring, measured with stubbed geometry.
import { fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "../../../src/features/app-shell/AppShell";
import {
  focusScrollDelta,
  installFocusInsets,
  measureFocusInsets,
  registerFocusInset,
  scrollFocusIntoView,
} from "../../../src/features/app-shell/focusInsets";

const span = (top: number, bottom: number) => ({ top, bottom });
/** Geometry by element, as layout would report it. */
const boxes = new Map<Element, { top: number; bottom: number }>();
const box = (el: Element, top: number, bottom: number): void =>
  void boxes.set(el, span(top, bottom));

beforeEach(() => {
  boxes.clear();
  vi.stubGlobal("innerHeight", 400);
  // jsdom has no layout: the document scroller and an overflowing container are declared.
  Object.defineProperty(document, "scrollingElement", {
    value: document.documentElement,
    configurable: true,
  });
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(900);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(400); // a 1280 x 800 frame at 200 % zoom
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    return (boxes.get(this) ?? span(0, 0)) as DOMRect;
  });
  vi.spyOn(window, "getComputedStyle").mockImplementation(
    (el) =>
      ({ overflowY: el.hasAttribute("data-scroller") ? "auto" : "visible" }) as CSSStyleDeclaration,
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("focusScrollDelta", () => {
  const band = span(0, 400);
  const insets = { top: 60, bottom: 40 };
  it("is 0 for a target inside the clear band", () => {
    expect(focusScrollDelta(span(100, 130), band, insets)).toBe(0);
  });
  it("scrolls up by what the top chrome covers", () => {
    expect(focusScrollDelta(span(20, 50), band, insets)).toBe(-40);
  });
  it("scrolls down by what the bottom chrome covers", () => {
    expect(focusScrollDelta(span(340, 370), band, insets)).toBe(10);
  });
  it("aligns a target taller than the band to its top", () => {
    expect(focusScrollDelta(span(100, 900), band, insets)).toBe(40);
  });
});

describe("registry", () => {
  it("counts only the part of the chrome that covers the band", () => {
    const bar = document.createElement("div");
    const foot = document.createElement("div");
    box(bar, -10, 60);
    box(foot, 360, 400);
    const undo = [registerFocusInset(bar, "top"), registerFocusInset(foot, "bottom")];
    expect(measureFocusInsets(span(0, 400))).toEqual({ top: 60, bottom: 40 });
    box(bar, -90, -10); // scrolled away: no longer over the band
    box(foot, 400, 440); // laid out beside the band, as the shell grid does
    expect(measureFocusInsets(span(0, 400))).toEqual({ top: 0, bottom: 0 });
    undo.forEach((f) => f());
    box(bar, 0, 60);
    expect(measureFocusInsets(span(0, 400))).toEqual({ top: 0, bottom: 0 });
  });
});

describe("installFocusInsets", () => {
  function setup() {
    const root = document.createElement("div");
    const bar = document.createElement("div");
    const field = document.createElement("input");
    root.setAttribute("data-scroller", "");
    root.append(bar, field);
    document.body.append(root);
    box(root, 0, 400);
    box(bar, 0, 56);
    return { root, bar, field };
  }
  it("sets scroll-padding from the chrome over it and clears it on teardown", () => {
    const { root, bar } = setup();
    const undo = registerFocusInset(bar, "top");
    const off = installFocusInsets(root);
    expect(root.style.scrollPaddingTop).toBe("56px");
    expect(root.style.scrollPaddingBottom).toBe("0px");
    off();
    undo();
    expect(root.style.scrollPaddingTop).toBe("");
  });
  it("scrolls a control hidden under the sticky bar into the clear band on focusin", () => {
    const { root, bar, field } = setup();
    const undo = registerFocusInset(bar, "top");
    const off = installFocusInsets(root);
    box(field, 10, 40); // fully under the 56 px bar
    root.scrollTop = 100;
    fireEvent.focusIn(field);
    expect(root.scrollTop).toBe(100 - 46);
    off();
    undo();
  });
  it("leaves a visible control and chrome beside the container alone", () => {
    const { root, bar, field } = setup();
    box(bar, -80, 0); // the header row above the container
    const undo = registerFocusInset(bar, "top");
    const off = installFocusInsets(root);
    box(field, 5, 35);
    root.scrollTop = 100;
    fireEvent.focusIn(field);
    expect(root.scrollTop).toBe(100);
    off();
    undo();
  });
  it("stops listening after teardown", () => {
    const { root, field } = setup();
    installFocusInsets(root)();
    box(field, -30, -5);
    root.scrollTop = 100;
    fireEvent.focusIn(field);
    expect(root.scrollTop).toBe(100);
  });
  it("scrolls the viewport when no ancestor scrolls", () => {
    const field = document.createElement("input");
    document.body.append(field);
    const scroller = document.scrollingElement as HTMLElement;
    box(field, 380, 430);
    Object.defineProperty(scroller, "scrollTop", { value: 0, writable: true, configurable: true });
    scrollFocusIntoView(field);
    expect(scroller.scrollTop).toBe(30);
  });
});

describe("AppShell wiring", () => {
  it("registers the header and footer, pads the canvas scroller and unregisters on unmount", () => {
    const { container, unmount } = render(
      <AppShell mainId="m">
        <button type="button">Under the bar</button>
      </AppShell>,
    );
    const scroller = container.querySelector<HTMLElement>("[data-shell-canvas]");
    const header = container.querySelector("header");
    const footer = container.querySelector("footer");
    if (scroller === null || header === null || footer === null) throw new Error("shell parts");
    box(scroller, 100, 700);
    box(header, 0, 100); // beside the canvas: no inset
    box(footer, 700, 800);
    // The registry holds the header and footer: overlay them and the insets show.
    box(header, 0, 160);
    box(footer, 640, 800);
    expect(measureFocusInsets(span(100, 700))).toEqual({ top: 60, bottom: 60 });
    unmount();
    expect(measureFocusInsets(span(100, 700))).toEqual({ top: 0, bottom: 0 });
  });
});
