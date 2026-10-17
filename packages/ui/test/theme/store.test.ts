// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_PREFERENCES,
  DENSITIES,
  THEMES,
  THEME_CHANGE_EVENT,
  THEME_STORAGE_KEY,
  createThemeStore,
  parsePreferences,
  resetSharedThemeStores,
  sharedThemeStore,
  type MotionOverride,
  type ThemeAnalyticsEvent,
  type ThemePreferences,
  type ThemeStoreOptions,
} from "../../src/theme/index.js";
import { mediaStub, memoryStorage, themeChanges } from "./helpers.js";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  localStorage.clear();
  resetSharedThemeStores();
});

function setup(os: { dark?: boolean; reduce?: boolean } = {}, extra: ThemeStoreOptions = {}) {
  const root = document.createElement("html");
  const media = mediaStub(os);
  const storage = memoryStorage();
  const store = createThemeStore({ root, storage, matchMedia: media.matchMedia, ...extra });
  return { root, media, storage, store };
}
const attrs = (root: HTMLElement): (string | null)[] =>
  ["theme", "density", "motion", "text-scale"].map((name) => root.getAttribute(`data-${name}`));

describe("theme store attributes", () => {
  it.each(THEMES)("sets data-theme=%s on the root", (theme) => {
    const { root, store } = setup();
    store.connect();
    store.setTheme(theme);
    expect(root.getAttribute("data-theme")).toBe(theme);
  });

  it("starts dark/compact/safe/100 and ignores an OS light preference (match-system is off)", () => {
    const { root, store } = setup({ dark: false });
    store.connect();
    expect(attrs(root)).toEqual(["dark", "compact", "safe", "100"]);
    expect(store.getSnapshot().matchSystem).toBe(false);
  });

  it("match-system follows each OS flip once", () => {
    const { root, media, store } = setup({ dark: true });
    const changes = themeChanges();
    store.connect();
    store.apply({ matchSystem: true });
    media.set({ dark: false });
    expect(root.getAttribute("data-theme")).toBe("light");
    media.set({ dark: true });
    expect(root.getAttribute("data-theme")).toBe("dark");
    expect(changes.map((c) => c.theme)).toEqual(["light", "dark"]);
  });

  it("an explicit theme choice stops the store following the OS", () => {
    const { root, media, store } = setup({ dark: true });
    store.connect();
    store.apply({ matchSystem: true });
    store.setTheme("dark");
    media.set({ dark: false });
    expect(root.getAttribute("data-theme")).toBe("dark");
  });

  it("disconnect removes both the colour-scheme and the reduced-motion listener", () => {
    const { media, store } = setup();
    const disconnect = store.connect();
    const sizes = () => [media.listeners.dark.size, media.listeners.reduce.size];
    expect(sizes()).toEqual([1, 1]);
    disconnect();
    expect(sizes()).toEqual([0, 0]);
  });

  it("connect() announces an OS change that happened since the store was created, exactly once", () => {
    const { media, store } = setup({ dark: true });
    store.apply({ matchSystem: true });
    const changes = themeChanges();
    media.set({ dark: false });
    store.connect();
    expect(changes.map((c) => c.theme)).toEqual(["light"]);
  });

  it("writes to document.documentElement, not the body, when no root is given", () => {
    createThemeStore({ storage: memoryStorage(), matchMedia: mediaStub().matchMedia }).connect();
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(document.body.hasAttribute("data-theme")).toBe(false);
  });

  it("toggleHighContrast overlays high contrast and restores the previous base theme", () => {
    const { store } = setup();
    store.setTheme("light");
    expect(store.toggleHighContrast()).toBe(true);
    expect(store.getSnapshot().theme).toBe("high-contrast");
    expect(store.toggleHighContrast()).toBe(false);
    expect(store.getSnapshot().theme).toBe("light");
  });

  it("uses the token build's theme and density vocabulary", () => {
    const file = resolve(import.meta.dirname, "../../tokens/themes.json");
    const tokens = JSON.parse(readFileSync(file, "utf-8")) as {
      themes: { name: string }[];
      density: { modes: string[] };
    };
    expect(THEMES).toEqual(tokens.themes.map((t) => t.name));
    expect(DENSITIES).toEqual(tokens.density.modes);
  });
});

describe("persistence", () => {
  it("persists every preference and restores it into a fresh store", () => {
    const first = setup();
    first.store.apply({
      baseTheme: "light",
      density: "comfortable",
      textScale: 125,
      motionOverride: "on",
    });
    const stored = first.storage.data.get(THEME_STORAGE_KEY) ?? "";
    const second = setup({}, { storage: memoryStorage({ [THEME_STORAGE_KEY]: stored }) });
    expect(second.store.getSnapshot()).toEqual(first.store.getSnapshot());
    second.store.connect();
    expect(attrs(second.root)).toEqual(["light", "comfortable", "reduce", "125"]);
  });

  it.each([
    "{bad",
    "null",
    "[1]",
    "5",
    '{"baseTheme":"neon","density":"huge","textScale":"125","motionOverride":7,"matchSystem":"yes"}',
  ])("falls back to the defaults for hostile storage %s", (raw) => {
    expect(parsePreferences(raw)).toEqual(DEFAULT_PREFERENCES);
  });

  it("keeps working when storage throws", () => {
    const denied = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("quota");
      },
    };
    const { store } = setup({}, { storage: denied });
    expect(() => store.setDensity("comfortable")).not.toThrow();
    expect(store.getSnapshot().density).toBe("comfortable");
  });

  it.each([
    ["setTextScale", 130, "text-scale", "125"],
    ["setDensity", "huge", "density", "comfortable"],
    ["setTheme", "neon", "theme", "light"],
  ] as const)(
    "%s(%j) keeps the current value instead of reaching the root or storage",
    (setter, value, attribute, current) => {
      const { root, storage, store } = setup();
      store.apply({ baseTheme: "light", density: "comfortable", textScale: 125 });
      (store[setter] as (value: unknown) => void)(value);
      expect(root.getAttribute(`data-${attribute}`)).toBe(current);
      expect(storage.data.get(THEME_STORAGE_KEY)).not.toContain(String(value));
    },
  );

  it("a malformed patch leaves the current preferences unchanged", () => {
    const { store } = setup();
    store.apply({ highContrast: true, textScale: 125, motionOverride: "off" });
    const before = store.getSnapshot();
    const malformed = { highContrast: "true", textScale: "150", motionOverride: null };
    store.apply(malformed as unknown as Partial<ThemePreferences>);
    expect(store.getSnapshot()).toBe(before);
  });

  it("persist and track are independent switches", () => {
    const events: ThemeAnalyticsEvent[] = [];
    const { storage, store } = setup({}, { onAnalytics: (event) => void events.push(event) });
    store.apply({ density: "comfortable" }, { persist: false });
    expect([storage.data.size, events.length]).toEqual([0, 1]);
    store.apply({ textScale: 125 }, { track: false });
    expect([storage.data.size, events.length]).toEqual([1, 1]);
  });

  it("hydration ({ persist: false, track: false }) still writes the root, announces and notifies", () => {
    const events: ThemeAnalyticsEvent[] = [];
    const { root, storage, store } = setup({}, { onAnalytics: (event) => void events.push(event) });
    const changes = themeChanges();
    const listener = vi.fn();
    store.subscribe(listener);
    store.apply({ density: "comfortable" }, { persist: false, track: false });
    expect(root.getAttribute("data-density")).toBe("comfortable");
    expect(changes.map((c) => c.density)).toEqual(["comfortable"]);
    expect(listener).toHaveBeenCalledTimes(1);
    expect([storage.data.size, events.length]).toEqual([0, 0]);
  });

  it("a user picking the value that hydration already set still persists it", () => {
    const first = setup();
    first.store.apply({ baseTheme: "light" }, { persist: false });
    expect(first.storage.data.size).toBe(0);
    first.store.setTheme("light");
    const reloaded = setup({}, { storage: memoryStorage(Object.fromEntries(first.storage.data)) });
    expect(reloaded.store.getSnapshot().theme).toBe("light");
  });

  it("an OS-driven change is not mistaken for unpersisted hydration", () => {
    const setItem = vi.fn();
    const { media, store } = setup({}, { storage: { getItem: () => null, setItem } });
    store.connect();
    store.apply({ matchSystem: true });
    media.set({ dark: false });
    store.apply({ matchSystem: true });
    expect(setItem).toHaveBeenCalledTimes(1);
  });
});

describe("reduced motion", () => {
  it.each([
    [true, "system", "reduce"],
    [false, "system", "safe"],
    [true, "on", "reduce"],
    [false, "on", "reduce"],
    [true, "off", "safe"],
    [false, "off", "safe"],
  ] as const)(
    "OS reduce=%s + override %s => data-motion=%s (the override wins)",
    (os, override, expected) => {
      const { root, store } = setup({ reduce: os });
      store.setMotionOverride(override);
      store.connect();
      expect(root.getAttribute("data-motion")).toBe(expected);
      expect(store.getSnapshot().motion).toBe(expected);
    },
  );

  it.each([
    ["system", "reduce", "safe"],
    ["on", "reduce", "reduce"],
    ["off", "safe", "safe"],
  ] as const)(
    "a runtime OS flip with override %s gives %s when reduce turns on and %s when it turns off",
    (override, whenOn, whenOff) => {
      const { root, media, store } = setup();
      store.setMotionOverride(override);
      store.connect();
      media.set({ reduce: true });
      expect(root.getAttribute("data-motion")).toBe(whenOn);
      media.set({ reduce: false });
      expect(root.getAttribute("data-motion")).toBe(whenOff);
    },
  );

  it("an invalid motion override never fails open: the default follows the OS, a chosen one stays", () => {
    const { store } = setup({ reduce: true });
    store.setMotionOverride("loud" as MotionOverride);
    expect(store.getSnapshot()).toMatchObject({ motionOverride: "system", motion: "reduce" });
    store.setMotionOverride("off");
    store.setMotionOverride("loud" as MotionOverride);
    expect(store.getSnapshot()).toMatchObject({ motionOverride: "off", motion: "safe" });
  });
});

describe("notifications", () => {
  it("dispatches candleviewer:themechange once per change with the resolved payload", () => {
    const { media, store } = setup();
    const changes = themeChanges();
    store.connect();
    store.setTheme("high-contrast");
    store.setTheme("high-contrast");
    store.apply({ density: "comfortable", motionOverride: "on" });
    store.setTextScale(150);
    media.set({ dark: false });
    const uniforms = "theme-uniforms";
    expect(changes).toEqual([
      { theme: "high-contrast", density: "compact", motion: "safe", themeUniforms: uniforms },
      { theme: "high-contrast", density: "comfortable", motion: "reduce", themeUniforms: uniforms },
    ]);
  });

  it("reports changes to the injectable analytics sink", () => {
    const events: ThemeAnalyticsEvent[] = [];
    const { store } = setup({}, { onAnalytics: (event) => void events.push(event) });
    store.setTheme("light");
    store.setDensity("comfortable");
    store.toggleHighContrast();
    store.setMotionOverride("on");
    store.setTextScale(112);
    const a11y = (key: "reduced_motion" | "high_contrast" | "text_scale", value: string) =>
      ({ name: "a11y.preference_changed", key, value }) as const;
    expect(events).toEqual([
      { name: "appearance.theme_changed", theme: "light", matchSystem: false },
      { name: "appearance.density_changed", density: "comfortable" },
      { name: "appearance.theme_changed", theme: "high-contrast", matchSystem: false },
      a11y("high_contrast", "on"),
      a11y("reduced_motion", "on"),
      a11y("text_scale", "112"),
    ]);
  });

  it("survives a throwing analytics sink", () => {
    const loud = setup(
      {},
      {
        onAnalytics: () => {
          throw new Error("sink down");
        },
      },
    );
    expect(() => loud.store.setTheme("light")).not.toThrow();
    expect(loud.store.getSnapshot().theme).toBe("light");
  });
});

describe("subscriptions and snapshots", () => {
  it("notifies once per change and not at all for a no-op", () => {
    const { store } = setup();
    const listener = vi.fn();
    store.subscribe(listener);
    store.setDensity("comfortable");
    store.setDensity("comfortable");
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("stops notifying once the disposer has run", () => {
    const { store } = setup();
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    unsubscribe();
    store.setDensity("comfortable");
    expect(listener).not.toHaveBeenCalled();
  });

  it("a listener removed by an earlier one in the same dispatch is not called", () => {
    const { store } = setup();
    const calls: string[] = [];
    let removeB = (): void => undefined;
    store.subscribe(() => {
      calls.push("A");
      removeB();
    });
    removeB = store.subscribe(() => void calls.push("B"));
    store.subscribe(() => void calls.push("C"));
    store.setTheme("light");
    expect(calls).toEqual(["A", "C"]);
  });

  it("keeps one snapshot object until something changes, and writes nothing for a no-op", () => {
    const { storage, store } = setup();
    const before = store.getSnapshot();
    store.setTheme("dark");
    expect([store.getSnapshot() === before, storage.data.size]).toEqual([true, 0]);
    store.setTheme("light");
    expect(store.getSnapshot()).not.toBe(before);
    expect(store.getSnapshot()).toBe(store.getSnapshot());
  });

  it("re-subscribing from inside a callback terminates, and the new subscription runs next time", () => {
    const { store } = setup();
    let calls = 0;
    let unsubscribe = (): void => undefined;
    const again = (): void => {
      if (calls > 3) return; // a store that revisits re-added entries fails the count below instead of hanging
      calls += 1;
      unsubscribe();
      unsubscribe = store.subscribe(again);
    };
    unsubscribe = store.subscribe(again);
    store.setTheme("light");
    expect(calls).toBe(1);
    store.setTheme("dark");
    expect(calls).toBe(2);
  });

  it("a different listener added during a dispatch waits for the next change", () => {
    const { store } = setup();
    const late = vi.fn();
    let added = false;
    store.subscribe(() => {
      if (!added) store.subscribe(late);
      added = true;
    });
    store.setTheme("light");
    expect(late).not.toHaveBeenCalled();
    store.setTheme("dark");
    expect(late).toHaveBeenCalledTimes(1);
  });

  it("subscribing the same function twice gives two independent subscriptions", () => {
    const { store } = setup();
    const listener = vi.fn();
    const first = store.subscribe(listener);
    const second = store.subscribe(listener);
    store.setTheme("light");
    first();
    store.setTheme("dark");
    second();
    store.setTheme("light");
    expect(listener).toHaveBeenCalledTimes(3);
  });
});

describe("failing and re-entrant subscribers", () => {
  it("a throwing subscriber skips neither later subscribers nor the event, and is rethrown later", () => {
    const boom = new Error("boom");
    const rethrown: (() => void)[] = [];
    vi.spyOn(globalThis, "queueMicrotask").mockImplementation((task) => void rethrown.push(task));
    const { store } = setup();
    const changes = themeChanges();
    const later = vi.fn();
    store.subscribe(() => {
      throw boom;
    });
    store.subscribe(later);
    store.setTheme("light");
    expect([later.mock.calls.length, changes.length, rethrown.length]).toEqual([1, 1, 1]);
    expect(rethrown[0]).toThrow(boom);
  });

  it("events stay oldest first when a subscriber re-enters apply", () => {
    const { store } = setup();
    const changes = themeChanges();
    let first = true;
    store.subscribe(() => {
      if (!first) return;
      first = false;
      store.setTheme("light");
    });
    store.setTheme("high-contrast");
    expect(changes.map((c) => c.theme)).toEqual(["high-contrast", "light"]);
    expect(changes.at(-1)?.theme).toBe(store.getSnapshot().theme);
  });

  it("events stay oldest first when a themechange handler re-enters apply", () => {
    const { store } = setup();
    document.addEventListener(THEME_CHANGE_EVENT, () => store.setDensity("comfortable"), {
      once: true,
    });
    const changes = themeChanges();
    store.setTheme("high-contrast");
    expect(changes.map((c) => [c.theme, c.density])).toEqual([
      ["high-contrast", "compact"],
      ["high-contrast", "comfortable"],
    ]);
  });

  it("a themechange handler that keeps changing the theme is cut off and reported", () => {
    const rethrown: (() => void)[] = [];
    vi.spyOn(globalThis, "queueMicrotask").mockImplementation((task) => void rethrown.push(task));
    const { store } = setup();
    const changes = themeChanges();
    const stop = new AbortController();
    const flip = (): void =>
      store.setTheme(store.getSnapshot().theme === "dark" ? "light" : "dark");
    document.addEventListener(THEME_CHANGE_EVENT, flip, { signal: stop.signal });
    try {
      store.setTheme("light");
    } finally {
      stop.abort();
    }
    expect([changes.length, rethrown.length]).toEqual([100, 1]);
    expect(rethrown[0]).toThrow("kept changing the theme");
  });
});

describe("browser defaults", () => {
  it("reads the OS from window.matchMedia and persists to window.localStorage when none are injected", () => {
    vi.stubGlobal("matchMedia", mediaStub({ dark: false, reduce: true }).matchMedia);
    const store = createThemeStore({ root: document.createElement("html") });
    expect(store.getSnapshot()).toMatchObject({ theme: "dark", motion: "reduce" });
    store.setTheme("light");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toContain('"baseTheme":"light"');
  });
});

describe("shared store per root", () => {
  it("returns one store per root element", () => {
    const root = document.createElement("html");
    const first = sharedThemeStore({ root, storage: memoryStorage() });
    expect(sharedThemeStore({ root })).toBe(first);
    expect(sharedThemeStore({ root: document.createElement("html") })).not.toBe(first);
  });

  it("keys the default on document.documentElement", () => {
    expect(sharedThemeStore()).toBe(sharedThemeStore({ root: document.documentElement }));
  });

  it("warns in development when a later caller passes options the existing store ignores", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const root = document.createElement("html");
    sharedThemeStore({ root, storage: memoryStorage() });
    sharedThemeStore({ root });
    expect(warn).not.toHaveBeenCalled();
    sharedThemeStore({ root, storage: memoryStorage() });
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn.mock.calls[0]?.[0]).toContain("storage");
    vi.stubEnv("DEV", false);
    sharedThemeStore({ root, storage: memoryStorage() });
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it("resetSharedThemeStores forgets every shared store", () => {
    const root = document.createElement("html");
    const first = sharedThemeStore({ root });
    resetSharedThemeStores();
    expect(sharedThemeStore({ root })).not.toBe(first);
  });
});
