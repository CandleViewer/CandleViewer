// @vitest-environment jsdom
import { act, useRef, type JSX } from "react";
import { createRoot } from "react-dom/client";
import { expect } from "storybook/test";
import { afterEach, describe, it, vi } from "vitest";
import { trapTab, visibleTabbables } from "../src/components/internal/focusTrap.js";
import { modalLayerOpen, useLayer, watchLayers } from "../src/components/internal/layers.js";
import { useScrollLock } from "../src/components/internal/scrollLock.js";
import { mount } from "./theme/mount.js";

afterEach(() => vi.restoreAllMocks());

const build = (): HTMLElement => {
  const root = document.body.appendChild(document.createElement("div"));
  for (const name of ["a", "b", "c"]) {
    const button = root.appendChild(document.createElement("button"));
    button.textContent = name;
  }
  return root;
};

describe("visibleTabbables and trapTab", () => {
  it("drops CSS-hidden elements where the engine has checkVisibility (plan §3 item 2)", () => {
    const root = build();
    const [a, b, c] = [...root.querySelectorAll("button")];
    const check = vi.fn(function (this: HTMLElement) {
      return this !== b;
    });
    Object.defineProperty(HTMLElement.prototype, "checkVisibility", {
      configurable: true,
      value: check,
    });
    try {
      expect(visibleTabbables(root)).toEqual([a, c]);
      expect(check).toHaveBeenCalledWith({ checkVisibilityCSS: true, visibilityProperty: true });
    } finally {
      delete (HTMLElement.prototype as { checkVisibility?: unknown }).checkVisibility;
    }
    expect(visibleTabbables(root)).toEqual([a, b, c]);
  });

  it("cycles at the edges both ways, and holds Tab when there is nothing to reach", () => {
    const root = build();
    const [a, , c] = [...root.querySelectorAll("button")];
    c?.focus();
    const forward = new KeyboardEvent("keydown", { key: "Tab", cancelable: true });
    trapTab(forward, root);
    expect(forward.defaultPrevented).toBe(true);
    expect(a).toHaveFocus();
    const back = new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, cancelable: true });
    trapTab(back, root);
    expect(c).toHaveFocus();
    const other = new KeyboardEvent("keydown", { key: "Enter", cancelable: true });
    trapTab(other, root);
    expect(other.defaultPrevented).toBe(false);
    const empty = document.body.appendChild(document.createElement("div"));
    const none = new KeyboardEvent("keydown", { key: "Tab", cancelable: true });
    trapTab(none, empty);
    expect(none.defaultPrevented).toBe(true);
  });
});

function Layer({ modal, onEscape }: { modal: boolean; onEscape: () => void }): JSX.Element {
  const ref = useRef<HTMLDivElement>(null);
  useLayer(true, { element: ref, modal, onEscape });
  return <div ref={ref}>layer</div>;
}

describe("the layer stack", () => {
  it("counts modal layers and tells its watchers; Esc reaches only the topmost", async () => {
    const watcher = vi.fn();
    const stop = watchLayers(watcher);
    const lower = vi.fn();
    const upper = vi.fn();
    expect(modalLayerOpen()).toBe(false);
    await mount(
      <>
        <Layer modal onEscape={lower} />
        <Layer modal={false} onEscape={upper} />
      </>,
    );
    expect(modalLayerOpen()).toBe(true);
    expect(watcher).toHaveBeenCalledTimes(2);
    const esc = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    await act(async () => document.body.dispatchEvent(esc));
    expect(upper).toHaveBeenCalledTimes(1);
    expect(lower).not.toHaveBeenCalled();
    expect(esc.defaultPrevented).toBe(true);
    const composing = new KeyboardEvent("keydown", {
      key: "Escape",
      bubbles: true,
      isComposing: true,
    });
    await act(async () => document.body.dispatchEvent(composing));
    expect(upper).toHaveBeenCalledTimes(1);
    stop();
  });
});

function Lock({ on }: { on: boolean }): null {
  useScrollLock(on);
  return null;
}

describe("useScrollLock", () => {
  it("nests: the first lock sets the styles and the last one out restores them", async () => {
    vi.spyOn(document.documentElement, "clientWidth", "get").mockReturnValue(
      window.innerWidth - 12,
    );
    const root = document.documentElement;
    root.style.overflow = "scroll";
    await mount(
      <>
        <Lock on />
        <Lock on />
      </>,
    );
    expect(root.style.overflow).toBe("hidden");
    expect(root.style.paddingRight).toBe("12px");
  });

  it("restores the page's own inline styles once the last lock is gone", async () => {
    const root = document.documentElement;
    root.style.overflow = "scroll";
    root.style.setProperty("--cv-scroll-lock-gutter", "3px");
    const outer = createRoot(document.body.appendChild(document.createElement("div")));
    const inner = createRoot(document.body.appendChild(document.createElement("div")));
    await act(async () => outer.render(<Lock on />));
    await act(async () => inner.render(<Lock on />));
    await act(async () => outer.unmount());
    expect(root.style.overflow).toBe("hidden");
    await act(async () => inner.unmount());
    expect(root.style.overflow).toBe("scroll");
    expect(root.style.getPropertyValue("--cv-scroll-lock-gutter")).toBe("3px");
    root.style.overflow = "";
    root.style.removeProperty("--cv-scroll-lock-gutter");
  });

  it("a page that reserves the gutter (scrollbar-gutter: stable) gets no padding", async () => {
    vi.spyOn(document.documentElement, "clientWidth", "get").mockReturnValue(
      window.innerWidth - 12,
    );
    const root = document.documentElement;
    root.style.overflow = "";
    root.style.setProperty("scrollbar-gutter", "stable");
    const computed = window.getComputedStyle;
    vi.spyOn(window, "getComputedStyle").mockImplementation((element) => {
      const style = computed(element);
      if (element !== root) return style;
      return new Proxy(style, {
        get: (target, prop) =>
          prop === "getPropertyValue"
            ? (name: string) =>
                name === "scrollbar-gutter" ? "stable" : target.getPropertyValue(name)
            : (Reflect.get(target, prop) as unknown),
      });
    });
    await mount(<Lock on />);
    expect(root.style.overflow).toBe("hidden");
    expect(root.style.paddingRight).toBe("");
    expect(root.style.getPropertyValue("--cv-scroll-lock-gutter")).toBe("0px");
  });
});
