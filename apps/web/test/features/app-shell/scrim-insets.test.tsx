// E10-S04 (#306) slice 10b: the shell owns the modal scrim's band (E05-D02 H23; `dialog.css` and
// `drawer.css` read it): AppShell insets every layer to `main`'s rows while it is mounted, and
// re-measures as `main` resizes (its ResizeObserver) and as the viewport does (a zoom fires a
// resize).
import { fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "../../../src/features/app-shell/AppShell";

/** Every observer made, newest last. */
const observers: FakeObserver[] = [];
/** A ResizeObserver that reports only when a test calls `report`. */
class FakeObserver {
  readonly observed: Element[] = [];
  disconnected = false;
  constructor(readonly report: ResizeObserverCallback) {
    observers.push(this);
  }
  observe(target: Element): void {
    this.observed.push(target);
  }
  disconnect(): void {
    this.disconnected = true;
  }
}

/** `main`'s rows in the viewport, as the layout would report them. */
let band = { top: 80, bottom: 720 };
const insets = (): string[] =>
  ["top", "bottom"].map((side) =>
    document.documentElement.style.getPropertyValue(`--cv-scrim-inset-${side}`),
  );
const shell = () =>
  render(
    <AppShell mainId="m">
      <p>Canvas</p>
    </AppShell>,
  );

beforeEach(() => {
  band = { top: 80, bottom: 720 };
  observers.length = 0;
  vi.stubGlobal("ResizeObserver", FakeObserver);
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(() => band as DOMRect);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("AppShell owns the modal scrim's band (E05-D02 H23)", () => {
  it("insets the layers to main's rows while mounted, and lets go when unmounted", () => {
    const view = shell();
    expect(insets()).toEqual(["80px", `${window.innerHeight - 720}px`]);
    view.unmount();
    expect(insets()).toEqual(["", ""]);
  });

  it("follows main as it resizes (its ResizeObserver), and disconnects on unmount", () => {
    const view = shell();
    const observer = observers.at(-1);
    expect(observer?.observed).toEqual([view.container.querySelector("main")]);
    band = { top: 120, bottom: 700 };
    observer?.report([], observer as unknown as ResizeObserver);
    expect(insets()).toEqual(["120px", `${window.innerHeight - 700}px`]);
    view.unmount();
    expect(observer?.disconnected).toBe(true);
  });

  it("follows the viewport (a resize: a zoom fires one), and stops listening on unmount", () => {
    const view = shell();
    band = { top: 100, bottom: 640 };
    fireEvent(window, new Event("resize"));
    expect(insets()).toEqual(["100px", `${window.innerHeight - 640}px`]);
    view.unmount();
    fireEvent(window, new Event("resize"));
    expect(insets()).toEqual(["", ""]);
  });
});
