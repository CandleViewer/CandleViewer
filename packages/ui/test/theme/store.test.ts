// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  DEFAULT_PREFERENCES,
  DENSITIES,
  THEMES,
  THEME_STORAGE_KEY,
  createThemeStore,
  parsePreferences,
  type ThemeAnalyticsEvent,
  type ThemeStoreOptions,
} from "../../src/theme/index.js";
import { mediaStub, memoryStorage, themeChanges } from "./helpers.js";

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

  it("match-system follows the OS once per flip until an explicit theme is chosen", () => {
    const { root, media, store } = setup({ dark: true });
    const changes = themeChanges();
    const disconnect = store.connect();
    expect(media.listeners.size).toBe(1);
    store.apply({ matchSystem: true });
    media.set({ dark: false });
    expect(root.getAttribute("data-theme")).toBe("light");
    store.setTheme("dark");
    media.set({ dark: true });
    media.set({ dark: false });
    expect(root.getAttribute("data-theme")).toBe("dark");
    expect(changes.map((c) => c.theme)).toEqual(["light", "dark"]);
    disconnect();
    expect(media.listeners.size).toBe(0);
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

  it("reports changes to the injectable analytics sink, and survives a throwing sink", () => {
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
