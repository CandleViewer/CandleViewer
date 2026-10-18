import { describe, expect, it, vi } from "vitest";
import {
  THEME_STORAGE_KEY,
  createThemeStore,
  type ThemePreferences,
  type ThemeStore,
} from "@candleviewer/ui";
import {
  applyAppearance,
  applyChartColorMode,
  readStoredChartColorMode,
} from "../../../src/shell/bootstrap/preferencesApply.js";

function makeRoot(): HTMLElement {
  return document.createElement("html");
}

/** A store of its own (own root, storage and OS), so no test leaks into the shared store of the page. */
function makeStore(options: { stored?: Partial<ThemePreferences>; osDark?: boolean } = {}) {
  const root = makeRoot();
  const data = new Map<string, string>();
  if (options.stored) data.set(THEME_STORAGE_KEY, JSON.stringify(options.stored));
  const setItem = vi.fn((key: string, value: string) => void data.set(key, value));
  const onAnalytics = vi.fn();
  const store = createThemeStore({
    root,
    storage: { getItem: (key) => data.get(key) ?? null, setItem },
    // A stand-in for the two media queries the runtime reads; the cast is limited to the members it uses.
    matchMedia: (query) =>
      ({
        matches: query.includes("color-scheme") ? (options.osDark ?? true) : false,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
      }) as unknown as MediaQueryList,
    onAnalytics,
  });
  return { root, store, setItem, onAnalytics };
}

describe("applyAppearance: the runtime is the only writer", () => {
  it("One writer: system theme, spacious density and high contrast give high-contrast and comfortable", () => {
    const { root, store } = makeStore();
    applyAppearance(
      { appearance: { theme: "system", density: "spacious", high_contrast: true } },
      store,
    );
    expect(root.getAttribute("data-theme")).toBe("high-contrast");
    expect(root.getAttribute("data-density")).toBe("comfortable");
    expect(store.getSnapshot()).toMatchObject({ matchSystem: true, highContrast: true });
  });

  it("applies stored theme and density without needing a reload", () => {
    const { root, store } = makeStore();
    applyAppearance({ appearance: { theme: "light", density: "compact" } }, store);
    expect(root.getAttribute("data-theme")).toBe("light");
    expect(root.getAttribute("data-density")).toBe("compact");
  });

  it("applies high contrast, reduced motion and the nearest text scale", () => {
    const { root, store } = makeStore();
    applyAppearance(
      { appearance: { high_contrast: true, reduce_motion: true, font_scale: 1.25 } },
      store,
    );
    expect(root.getAttribute("data-theme")).toBe("high-contrast");
    expect(root.getAttribute("data-motion")).toBe("reduce");
    expect(root.getAttribute("data-text-scale")).toBe("125");
  });

  it("lets the tri-state accessibility setting win over the appearance boolean", () => {
    const { root, store } = makeStore();
    applyAppearance(
      { appearance: { reduce_motion: true }, accessibility: { reduced_motion: "off" } },
      store,
    );
    expect(root.getAttribute("data-motion")).toBe("safe");
  });

  it("feeds the store with persist:false and track:false, as one change", () => {
    const apply = vi.fn();
    applyAppearance({ appearance: { theme: "light" } }, { apply } as unknown as ThemeStore);
    expect(apply).toHaveBeenCalledTimes(1);
    expect(apply).toHaveBeenCalledWith(
      { baseTheme: "light", matchSystem: false },
      { persist: false, track: false },
    );
  });

  it("neither writes server values to local storage nor reports them as a user's choice", () => {
    const { store, setItem, onAnalytics } = makeStore();
    applyAppearance(
      { appearance: { theme: "light", density: "comfortable", font_scale: 1.5 } },
      store,
    );
    expect(setItem).not.toHaveBeenCalled();
    expect(onAnalytics).not.toHaveBeenCalled();
  });

  it("does not write the retired attributes or the legacy font-scale property", () => {
    const { root, store } = makeStore();
    applyAppearance(
      { appearance: { high_contrast: true, reduce_motion: true, font_scale: 1.25 } },
      store,
    );
    for (const retired of ["data-reduced-motion", "data-high-contrast", "data-contrast"]) {
      expect(root.hasAttribute(retired), retired).toBe(false);
    }
    expect(root.style.getPropertyValue("--cv-font-scale")).toBe("");
  });
});

describe("applyAppearance: no clobber", () => {
  const persisted: Partial<ThemePreferences> = {
    baseTheme: "light",
    highContrast: true,
    density: "comfortable",
    motionOverride: "on",
    textScale: 150,
  };

  it.each([
    ["nothing (preferences failed to load)", undefined],
    ["an empty payload", {}],
    ["empty subtrees", { appearance: {}, accessibility: {} }],
    ["values that are not valid", { appearance: { theme: "auto", density: 3, font_scale: "big" } }],
  ])("keeps the persisted values when the server sends %s", (_name, settings) => {
    const { store } = makeStore({ stored: persisted });
    const before = store.getSnapshot();
    applyAppearance(settings as Parameters<typeof applyAppearance>[0], store);
    expect(store.getSnapshot()).toBe(before);
  });

  it("changes only the fields the server sent", () => {
    const { store } = makeStore({ stored: persisted });
    applyAppearance({ appearance: { theme: "dark" } }, store);
    expect(store.getSnapshot()).toMatchObject({ ...persisted, baseTheme: "dark" });
  });
});

describe("applyChartColorMode", () => {
  it("defaults to standard palette and convention", () => {
    const root = makeRoot();
    applyChartColorMode({}, root);
    expect(root.getAttribute("data-palette")).toBe("default");
    expect(root.getAttribute("data-convention")).toBe("standard");
  });

  it("applies cvd-safe palette and inverted convention to the root", () => {
    const root = makeRoot();
    applyChartColorMode({ palette: "cvd-safe", convention: "inverted" }, root);
    expect(root.getAttribute("data-palette")).toBe("cvd-safe");
    expect(root.getAttribute("data-convention")).toBe("inverted");
  });

  it("theme switch and palette are independent root attributes", () => {
    const { root, store } = makeStore();
    applyChartColorMode({ palette: "cvd-safe" }, root);
    applyAppearance({ appearance: { theme: "light" } }, store);
    expect(root.getAttribute("data-theme")).toBe("light");
    expect(root.getAttribute("data-palette")).toBe("cvd-safe");
  });
});

describe("readStoredChartColorMode", () => {
  const store = (v: string | null) => ({ getItem: () => v });
  it("reads valid stored values", () => {
    expect(
      readStoredChartColorMode(store('{"palette":"cvd-safe","convention":"inverted"}')),
    ).toEqual({
      palette: "cvd-safe",
      convention: "inverted",
    });
  });
  it("ignores junk and invalid JSON", () => {
    expect(readStoredChartColorMode(store("{bad"))).toEqual({});
    expect(readStoredChartColorMode(store('{"palette":"x"}'))).toEqual({});
    expect(readStoredChartColorMode(store(null))).toEqual({});
  });
});
